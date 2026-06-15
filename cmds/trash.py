from __future__ import (absolute_import, division, print_function)
import configparser
import datetime
import glob
import os
import shlex
import shutil
import subprocess
import tempfile
from urllib.parse import quote, unquote
from ranger.api.commands import Command
from cmds._util import ask_yes, run_bg

# Files whose combined size exceeds this trigger a confirmation prompt.
# Set to 0 to disable.  Unit: bytes.
_TRASH_SIZE_WARN = 500 * 1024 * 1024  # 500 MB


def _selection_bytes(paths):
    """Return total byte count for a list of paths.
    Directories use their inode size only (no recursive walk — fast over NFS).
    Returns (total_bytes, any_dirs_present).
    """
    total, has_dirs = 0, False
    for p in paths:
        try:
            st = os.stat(p)
            total += st.st_size
            if os.path.isdir(p) and not os.path.islink(p):
                has_dirs = True
        except OSError:
            pass
    return total, has_dirs


def _human_size(n):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if abs(n) < 1024:
            return '{:.1f} {}'.format(n, unit)
        n /= 1024.0
    return '{:.1f} PB'.format(n)


def _trash_manual(files):
    """XDG-compliant trash to ~/.local/share/Trash.

    Works headlessly (no D-Bus/gvfs) and across filesystems (NFS).
    Returns (trashed_names, failed_messages).
    """
    trash_dir = os.path.expanduser('~/.local/share/Trash')
    files_dir = os.path.join(trash_dir, 'files')
    info_dir  = os.path.join(trash_dir, 'info')
    os.makedirs(files_dir, exist_ok=True)
    os.makedirs(info_dir,  exist_ok=True)

    now = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    trashed, failed = [], []

    for path in files:
        path = os.path.abspath(path)
        name = os.path.basename(path)

        # Pick a unique name inside the trash.
        dest_name = name
        n = 1
        while os.path.lexists(os.path.join(files_dir, dest_name)):
            base, ext = os.path.splitext(name)
            dest_name = '{}_{}{}'.format(base, n, ext)
            n += 1

        info_path = os.path.join(info_dir, dest_name + '.trashinfo')
        dest_path = os.path.join(files_dir, dest_name)
        try:
            # The spec wants Path percent-encoded; restore unquotes it.
            with open(info_path, 'w') as fh:
                fh.write('[Trash Info]\nPath={}\nDeletionDate={}\n'.format(
                    quote(path, safe='/', errors='surrogateescape'), now))
            shutil.move(path, dest_path)
            trashed.append(name)
        except Exception as exc:
            try:
                os.unlink(info_path)
            except OSError:
                pass
            failed.append('{}: {}'.format(name, exc))

    return trashed, failed


def _same_device(path, other):
    try:
        return os.lstat(path).st_dev == os.stat(other).st_dev
    except OSError:
        return True


class trash(Command):
    """:trash [force]

    Move selected files to trash.

    If the combined size of the selection exceeds _TRASH_SIZE_WARN, asks
    y/N first (reminding that <Space>X deletes permanently); 'force' skips
    the question.

    Tries gio trash first (requires D-Bus/gvfs — desktop sessions).
    Falls back to a pure-Python XDG implementation (~/.local/share/Trash)
    that works headlessly and over NFS mounts; items on another filesystem
    have to be copied, so those are moved in the background.
    """

    def execute(self):
        force = (self.arg(1) == 'force')
        selection = self.fm.thistab.get_selection()
        if not selection:
            return
        files = [f.path for f in selection]

        # Size gate — skip when the user has already confirmed.
        if not force and _TRASH_SIZE_WARN > 0:
            total, has_dirs = _selection_bytes(files)
            if total > _TRASH_SIZE_WARN:
                dir_note = ' (dirs not recursively counted)' if has_dirs else ''
                ask_yes(self.fm, 'Trash {}{}? (Esc, then <Space>X deletes permanently)'.format(
                    _human_size(total), dir_note), lambda: self._trash(files))
                return
        self._trash(files)

    def _trash(self, files):
        # gio works on a desktop session; fails headlessly or over NFS.
        try:
            result = subprocess.run(['gio', 'trash', '--'] + files, capture_output=True)
            gio_ok = result.returncode == 0
        except OSError:
            gio_ok = False
        if gio_ok:
            self.fm.notify("Trashed {} file(s)".format(len(files)))
            self.fm.reload_cwd()
            return

        # gio may have trashed some of them before failing: retry only the rest.
        remaining = [p for p in files if os.path.lexists(p)]
        gio_done = len(files) - len(remaining)

        # Fallback: manual XDG trash (no D-Bus, works over NFS).  Items on
        # another filesystem are copied, which can take long: do those off
        # the UI thread.
        home_trash = os.path.expanduser('~/.local/share')
        local = [p for p in remaining if _same_device(p, home_trash)]
        remote = [p for p in remaining if p not in local]

        trashed, failed = _trash_manual(local)
        if trashed or gio_done:
            self.fm.notify("Trashed {} file(s)".format(len(trashed) + gio_done))
        if failed:
            self.fm.notify("Failed: " + ';  '.join(failed), bad=True)
        self.fm.reload_cwd()
        if not remote:
            return

        def done(result, error):
            if error is not None:
                self.fm.notify("trash: {}".format(error), bad=True)
            else:
                ok, bad = result
                if ok:
                    self.fm.notify("Trashed {} file(s) from another filesystem".format(len(ok)))
                if bad:
                    self.fm.notify("Failed: " + ';  '.join(bad), bad=True)
            self.fm.reload_cwd()

        self.fm.notify("Copying {} item(s) to the trash in the background…".format(len(remote)))
        run_bg(self.fm, 'Trashing', lambda _ui: _trash_manual(remote), done)


class undo_trash(Command):
    """:undo_trash

    Restore the most recently trashed file(s) to their original locations.
    Files trashed within the same second are treated as one batch and all
    restored together (handles multi-selection x presses).
    """

    def execute(self):
        trash_dir = os.path.expanduser('~/.local/share/Trash')
        info_dir  = os.path.join(trash_dir, 'info')
        files_dir = os.path.join(trash_dir, 'files')

        info_files = glob.glob(os.path.join(info_dir, '*.trashinfo'))
        if not info_files:
            self.fm.notify("Trash is empty", bad=True)
            return

        # Treat all trashinfo files modified within 1 s of the newest as one batch.
        newest = max(os.path.getmtime(f) for f in info_files)
        batch  = [f for f in info_files if newest - os.path.getmtime(f) < 1.0]

        restored, failed = [], []

        for info_path in batch:
            stem = os.path.basename(info_path)[:-len('.trashinfo')]

            # RawConfigParser: skip BasicInterpolation so %(...)s in paths don't raise.
            cfg = configparser.RawConfigParser()
            try:
                with open(info_path, 'r', encoding='utf-8', errors='replace') as fh:
                    cfg.read_file(fh)
            except OSError as e:
                failed.append('{}: cannot read trashinfo ({})'.format(stem, e))
                continue

            try:
                raw_path = cfg.get('Trash Info', 'Path')
            except (configparser.NoSectionError, configparser.NoOptionError):
                failed.append(stem + ' (no Path key in trashinfo)')
                continue

            # Decode FreeDesktop percent-encoding; errors='replace' survives bad sequences.
            orig_path = unquote(raw_path, errors='replace')

            # Guard against empty or relative paths in a malformed trashinfo.
            if not orig_path or not os.path.isabs(orig_path):
                failed.append(stem + ' (invalid path in trashinfo: {!r})'.format(raw_path))
                continue

            trashed = os.path.join(files_dir, stem)

            # lexists counts broken symlinks as present (exists() returns False for them).
            if not os.path.lexists(trashed):
                failed.append(stem + ' (missing from trash)')
                continue
            if os.path.lexists(orig_path):
                failed.append(stem + ' (destination exists)')
                continue

            try:
                parent = os.path.dirname(orig_path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                shutil.move(trashed, orig_path)
                os.remove(info_path)
                restored.append(os.path.basename(orig_path))
            except Exception as e:
                failed.append('{}: {}'.format(stem, e))

        if restored:
            self.fm.notify('Restored: ' + ', '.join(restored))
        if failed:
            self.fm.notify('Failed: ' + ', '.join(failed), bad=True)
        self.fm.reload_cwd()


class trash_list(Command):
    """:trash_list  (<Space>bl)

    Browse trash contents in fzf (searchable, read-only).
    Reads ~/.local/share/Trash/info/ for full metadata.
    Use <Space>br to restore an item interactively.
    """

    def execute(self):
        info_dir = os.path.expanduser('~/.local/share/Trash/info')
        info_files = glob.glob(os.path.join(info_dir, '*.trashinfo'))

        if not info_files:
            self.fm.notify("Trash is empty")
            return

        entries = []
        for info_path in sorted(info_files, key=os.path.getmtime, reverse=True):
            cfg = configparser.RawConfigParser()
            try:
                cfg.read(info_path, encoding='utf-8')
                orig = unquote(cfg.get('Trash Info', 'Path'))
                date = cfg.get('Trash Info', 'DeletionDate', fallback='?')
                name = os.path.basename(orig)
                entries.append('{:<20} {:<32} {}'.format(date, name[:31], orig))
            except Exception:
                continue

        col_header = '{:<20} {:<32} {}'.format('Deleted', 'Name', 'Original path')
        header = '{} item(s) in trash  |  <Space>br to restore  |  {}'.format(
            len(entries), col_header)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.in', delete=False) as tf:
            tf.write('\n'.join(entries))
            in_file = tf.name
        fd, out_file = tempfile.mkstemp(suffix='.out')
        os.close(fd)
        try:
            self.fm.run(
                'fzf --border --no-multi --ansi --header={} < {} > {}'.format(
                    shlex.quote(header),
                    shlex.quote(in_file),
                    shlex.quote(out_file),
                )
            )
        finally:
            for tmp in [in_file, out_file]:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass


class trash_restore(Command):
    """:trash_restore  (<Space>br)

    Interactive fzf picker over trash — select an item to restore to its original path.
    """

    def execute(self):
        info_dir  = os.path.expanduser('~/.local/share/Trash/info')
        files_dir = os.path.expanduser('~/.local/share/Trash/files')
        info_files = glob.glob(os.path.join(info_dir, '*.trashinfo'))

        if not info_files:
            self.fm.notify("Trash is empty")
            return

        entries = []  # (display_line, stem, orig_path, info_path)
        for info_path in sorted(info_files, key=os.path.getmtime, reverse=True):
            cfg = configparser.RawConfigParser()
            try:
                cfg.read(info_path, encoding='utf-8')
                orig = unquote(cfg.get('Trash Info', 'Path'))
                date = cfg.get('Trash Info', 'DeletionDate', fallback='?')
                stem = os.path.basename(info_path)[:-len('.trashinfo')]
                name = os.path.basename(orig)
                line = '{:<20} {:<32} {}'.format(date, name[:31], orig)
                entries.append((line, stem, orig, info_path))
            except Exception:
                continue

        if not entries:
            self.fm.notify("No restorable entries found", bad=True)
            return

        with tempfile.NamedTemporaryFile(mode='w', suffix='.in', delete=False) as tf:
            tf.write('\n'.join(e[0] for e in entries))
            in_file = tf.name
        fd, out_file = tempfile.mkstemp(suffix='.out')
        os.close(fd)
        try:
            self.fm.run(
                'fzf --border --ansi --header={} < {} > {}'.format(
                    shlex.quote('enter: restore   esc: cancel'),
                    shlex.quote(in_file),
                    shlex.quote(out_file),
                )
            )
            try:
                with open(out_file) as f:
                    selected = f.read().strip()
            except OSError:
                selected = ''
        finally:
            for tmp in [in_file, out_file]:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

        if not selected:
            return
        match = next((e for e in entries if e[0] == selected), None)
        if not match:
            self.fm.notify("Could not match selection", bad=True)
            return

        _, stem, orig, info_path = match
        trashed = os.path.join(files_dir, stem)

        if not os.path.exists(trashed):
            self.fm.notify("File missing from trash: " + stem, bad=True)
            return
        if os.path.exists(orig):
            self.fm.notify("Destination already exists: " + orig, bad=True)
            return

        try:
            parent = os.path.dirname(orig)
            if parent:
                os.makedirs(parent, exist_ok=True)
            shutil.move(trashed, orig)
            os.remove(info_path)
            self.fm.notify("Restored: " + os.path.basename(orig))
            self.fm.reload_cwd()
        except Exception as e:
            self.fm.notify("Restore failed: {}".format(e), bad=True)


class trash_empty(Command):
    """:trash_empty [confirm]  (<Space>be)

    Asks y/N, then permanently deletes all trash contents (gio, falling
    back to manual deletion).  'confirm' skips the question.
    """

    def execute(self):
        if self.arg(1) == 'confirm':
            self._empty()
            return
        try:
            count = len(os.listdir(os.path.expanduser('~/.local/share/Trash/files')))
        except OSError:
            count = 0
        if count == 0:
            self.fm.notify("Trash is already empty")
            return
        ask_yes(self.fm, "Permanently delete {} item(s) from trash?".format(count),
                self._empty)

    def _empty(self):
        files_dir = os.path.expanduser('~/.local/share/Trash/files')
        info_dir  = os.path.expanduser('~/.local/share/Trash/info')

        try:
            gio_ok = subprocess.run(['gio', 'trash', '--empty'],
                                    capture_output=True).returncode == 0
        except OSError:
            gio_ok = False
        if gio_ok:
            self.fm.notify("Trash emptied")
            return

        # gio not available — delete manually.
        # Count only items from files_dir (the user-visible file count).
        file_count = 0
        for base_dir in (files_dir, info_dir):
            try:
                for item in os.listdir(base_dir):
                    full = os.path.join(base_dir, item)
                    try:
                        if os.path.isdir(full) and not os.path.islink(full):
                            shutil.rmtree(full)
                        else:
                            os.remove(full)
                        if base_dir == files_dir:
                            file_count += 1
                    except OSError:
                        pass
            except FileNotFoundError:
                pass
        self.fm.notify("Trash emptied ({} items)".format(file_count))
