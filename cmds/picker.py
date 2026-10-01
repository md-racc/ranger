"""File-picker mode: ranger as the xdg-desktop-portal-termfilechooser picker.

A custom portal wrapper exports
RANGER_PICKER=open|multi|dir|save, RANGER_PICKER_OUT (portal result file) and
RANGER_PICKER_PATH (save: the placeholder file). open/multi still use ranger's
--choosefile(s); dir/save get no --choose* flag, so only _finish() writes the
result and quitting always cancels. Without the wrapper, picker_mode() falls
back to ranger's --choose* flags (save then looks like open).

Commands:
  enter_or_pick   <CR>        Finish key per mode (see its docstring).
  pick_save       (console)   Save target; y/N before overwriting.
  pick_location   <C-l>       Type a path (GTK Ctrl+L).
  pick_selection  (via <CR>)  Send marks; marked folders flattened.
  pick_archive    <Space>au   Zip the selection, send the archive.

Leaked environment: the terminal the wrapper starts keeps RANGER_PICKER* in
its own environment, so a ranger started from a sibling window/tab would see
it too. The env is only trusted when (a) ranger's own arguments are the ones
the wrapper passes for that mode, and (b) if RANGER_PICKER_TOKEN is set, it
names a one-time token file (regular, ours) that is consumed on startup.

Hidden files/dirs *inside* a marked folder are skipped (no .git internals,
.env, …); a hidden file you marked yourself is kept.
"""

from __future__ import (absolute_import, division, print_function)
import os
import shutil
import stat
import tempfile
import time
import zipfile
from functools import partial
from ranger.api.commands import Command

UPLOAD_PREFIX = 'ranger-upload-'
MODES = ('open', 'multi', 'dir', 'save')
# Multi upload: marked folders flattening into more files than this ask y/N
FLATTEN_CONFIRM = 20
# Multi-part extensions kept whole by unique_name: a.tar.gz → a (1).tar.gz
COMPOUND_EXTS = ('.tar.gz', '.tar.bz2', '.tar.xz', '.tar.zst', '.tar.lz4', '.tar.lz',
                 '.tar.lzma', '.tar.br', '.tar.z', '.tar.sz')

_PICKER_VARS = ('RANGER_PICKER', 'RANGER_PICKER_OUT', 'RANGER_PICKER_PATH',
                'RANGER_PICKER_TOKEN')


def _consume_token(env):
    """True unless a RANGER_PICKER_TOKEN is given and isn't a fresh token
    file of ours. The file is deleted, so only the first ranger counts."""
    token = env.get('RANGER_PICKER_TOKEN')
    if token is None:
        return True                      # wrapper that doesn't use tokens
    try:
        info = os.lstat(token)
        os.remove(token)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()


# Read once and drop from the environment: shells/programs started from the
# picker must not inherit it (a nested ranger would think it's the picker).
_PICKER_ENV = {k: os.environ.pop(k) for k in _PICKER_VARS if k in os.environ}
if not _consume_token(_PICKER_ENV):
    _PICKER_ENV.clear()


def _env(name):
    return _PICKER_ENV.get(name) or os.environ.get(name, '')


def _picker_args():
    import ranger
    return getattr(ranger, 'args', None)


def _same_path(a, b):
    """a and b name the same file (symlinked folders count), or the same
    normalised path when either doesn't exist."""
    if not a or not b:
        return False
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normpath(os.path.abspath(a)) == os.path.normpath(os.path.abspath(b))


def _wrapper_launched(mode, args):
    """ranger's arguments are the ones the wrapper passes for `mode`
    (a plain `ranger` that merely inherited the env fails this)."""
    def arg(name):
        value = getattr(args, name, None)
        return value if isinstance(value, str) else None
    out, path = _env('RANGER_PICKER_OUT'), _env('RANGER_PICKER_PATH')
    if mode in ('open', 'multi'):
        return _same_path(arg('choosefile' if mode == 'open' else 'choosefiles'), out)
    if mode == 'save':
        return _same_path(arg('selectfile'), path)
    paths = getattr(args, 'paths', None) or []
    return getattr(args, 'show_only_dirs', None) is True and \
        any(_same_path(p, path) for p in paths if isinstance(p, str))


def _env_mode():
    """RANGER_PICKER if it is set, valid and trustworthy, else None.
    Outside a running ranger (no ranger.args: tests, headless) it's trusted."""
    mode = _env('RANGER_PICKER')
    if mode not in MODES:
        return None
    args = _picker_args()
    if args is not None and not _wrapper_launched(mode, args):
        return None
    return mode


def picker_mode():
    """'open' | 'multi' | 'dir' | 'save' | None.

    RANGER_PICKER comes from the custom portal wrapper (see _env_mode). Without
    it, fall back to ranger's own --choose* flags (stock wrapper: save looks
    like 'open').
    """
    mode = _env_mode()
    if mode:
        return mode
    args = _picker_args()
    if getattr(args, 'choosedir', None):
        return 'dir'
    if getattr(args, 'choosefiles', None):
        return 'multi'
    if getattr(args, 'choosefile', None):
        return 'open'
    return None


def placeholder():
    """Save mode: the portal's placeholder file (created before ranger starts)."""
    if _env_mode() != 'save':
        return ''
    path = _env('RANGER_PICKER_PATH')
    return os.path.normpath(path) if path else ''


def suggested_name(path):
    """App-suggested file name. The portal appends '_' to the placeholder
    until the name is free (report.pdf → report.pdf_); strip that.
    Trade-off: a genuine trailing '_' in an app-suggested name is also
    stripped, since the portal's '_' suffix is ambiguous — accepted."""
    return os.path.basename(path).rstrip('_') or 'untitled'


def split_ext(name):
    """Like os.path.splitext, but keeps compound extensions (.tar.gz) whole."""
    lower = name.lower()
    for ext in COMPOUND_EXTS:
        if lower.endswith(ext) and len(name) > len(ext):
            return name[:-len(ext)], name[-len(ext):]
    return os.path.splitext(name)


def unique_name(dirpath, name, free=''):
    """name if dirpath/name is unused (or is `free`), else 'stem (N).ext'."""
    def taken(candidate):
        path = os.path.join(dirpath, candidate)
        return os.path.lexists(path) and not _same_path(path, free)
    if not taken(name):
        return name
    stem, ext = split_ext(name)
    n = 1
    while taken('{} ({}){}'.format(stem, n, ext)):
        n += 1
    return '{} ({}){}'.format(stem, n, ext)


def resolve_target(text, cwd, name):
    """Console text → absolute save path. Folders (existing, or text ending
    in '/', or empty text) get `name` appended. The text is taken literally
    (spaces included); only a trailing line break is dropped."""
    text = text.rstrip('\r\n')
    if not text.strip():
        text = ''
    path = os.path.normpath(os.path.join(cwd, os.path.expanduser(text or '.')))
    if not text or text.endswith('/') or os.path.isdir(path):
        path = os.path.join(path, name)
    return path


def tilde(path):
    home = os.path.expanduser('~')
    if path == home or path.startswith(home + '/'):
        return '~' + path[len(home):]
    return path


def console_path(path, cwd):
    """Shortest readable form for a console prefill: relative when under cwd."""
    rel = os.path.relpath(path, cwd)
    return tilde(path) if rel.startswith('..') else rel


def select_folder(fm, path):
    """Put the cursor on folder `path` (in its parent) so <CR> picks it.
    Shows hidden files if that's what hides it; if the cursor still can't
    land on it (e.g. '/', or filtered out) cd into it and say so."""
    fm.select_file(path)
    if fm.thisfile is None or fm.thisfile.path != path:
        if os.path.basename(path).startswith('.') and not fm.settings.show_hidden:
            fm.settings.show_hidden = True
            fm.select_file(path)
    if fm.thisfile is None or fm.thisfile.path != path:
        fm.cd(path)
        fm.notify('In {} — press h then ⏎ to pick it'.format(tilde(path)))


def _marked_and_selected(fm):
    """Same set ranger's own --choosefiles writes: marks from every visited
    dir, then the current selection."""
    paths = []
    for hist in fm.thistab.history:
        for fobj in hist.files or ():
            if fobj.marked and fobj.path not in paths:
                paths.append(fobj.path)
    paths += [f.path for f in fm.thistab.get_selection() if f.path not in paths]
    return paths


def _walk_files(root):
    """Regular files under root, skipping hidden entries and symlinked dirs."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith('.'))
        for name in sorted(filenames):
            if not name.startswith('.'):
                path = os.path.join(dirpath, name)
                if os.path.isfile(path):
                    yield path


def _flatten(paths):
    out = []
    for path in paths:
        if os.path.isdir(path):
            out.extend(p for p in _walk_files(path) if p not in out)
        elif os.path.isfile(path) and path not in out:
            out.append(path)
    return out


def _write_out(out, paths, trailing=True):
    """Write paths one per line as raw bytes (non-UTF-8 names survive)."""
    data = b'\n'.join(os.fsencode(p) for p in paths) + (b'\n' if trailing else b'')
    with open(out, 'wb') as fobj:
        fobj.write(data)


def _upload_base():
    """$TMPDIR or /tmp. Not $XDG_RUNTIME_DIR: it's a small tmpfs that the
    session's sockets live on, and archives of whole folders can be big.
    Each pick gets its own mkdtemp() dir (0700, random name), so the shared
    /tmp is safe: nothing pre-existing is reused or followed."""
    return tempfile.gettempdir()


def _clean_uploads(base, max_age=86400):
    """Remove our own ranger-upload-* dirs older than max_age. Symlinks and
    other users' entries are never touched (lstat, no following)."""
    cutoff = time.time() - max_age
    try:
        names = os.listdir(base)
    except OSError:
        return
    for name in names:
        if not name.startswith(UPLOAD_PREFIX):
            continue
        path = os.path.join(base, name)
        try:
            info = os.lstat(path)
        except OSError:
            continue
        if stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() \
                and info.st_mtime < cutoff:
            shutil.rmtree(path, ignore_errors=True)


def _finish(fm, paths):
    """Write the result where the portal expects it and exit ranger.

    Returns False (after a notify, ranger stays open) if nothing could be
    written; on success it raises SystemExit and never returns."""
    bad = [p for p in paths if '\n' in p]
    if bad:
        fm.notify('Cannot send a name containing a newline: ' + repr(os.path.basename(bad[0])),
                  bad=True)
        return False
    env_mode = _env_mode()
    args = _picker_args()
    try:
        if env_mode in ('dir', 'save'):
            out = _env('RANGER_PICKER_OUT')
            if not out:
                fm.notify('Picker: RANGER_PICKER_OUT is not set, cannot return a result',
                          bad=True)
                return False
            _write_out(out, paths)
        elif getattr(args, 'choosefiles', None):
            _write_out(args.choosefiles, paths)
        elif getattr(args, 'choosefile', None):
            _write_out(args.choosefile, paths[:1], trailing=False)
        elif getattr(args, 'choosedir', None):
            fm.cd(paths[0])          # stock wrapper: ranger writes thisdir on exit
        else:
            fm.notify('Picker: nowhere to write the result (RANGER_PICKER_OUT unset)', bad=True)
            return False
    except OSError as ex:
        fm.notify('Picker: cannot write the result: {}'.format(ex.strerror or ex), bad=True)
        return False
    raise SystemExit


def _is_placeholder(path):
    ph = placeholder()
    return bool(ph) and _same_path(path, ph)


def pick_files(fm, current=None):
    """Multi/open picker: send marks (all visited dirs) + the selection +
    `current` (the highlighted file the user pressed ⏎/l on). Folders are
    flattened. Returns False if nothing was sent (ranger stays open), None
    while a y/N about a big folder flatten is pending."""
    args = _picker_args()
    if not (getattr(args, 'choosefiles', None) or getattr(args, 'choosefile', None)):
        fm.notify('pick_selection: not running as a file picker', bad=True)
        return False
    items = _marked_and_selected(fm)
    if current is not None and current not in items:
        items.append(current)
    files = _flatten(items)
    if not files:
        fm.notify('Nothing to send (empty folders or only hidden files)', bad=True)
        return False
    if getattr(args, 'choosefile', None) and not getattr(args, 'choosefiles', None) \
            and len(files) > 1:
        fm.notify('Single-file dialog: use <Space>au to send them as one archive', bad=True)
        return False
    folders = sum(1 for p in items if os.path.isdir(p))
    if folders and len(files) > FLATTEN_CONFIRM:
        from cmds._util import ask_yes
        ask_yes(fm, 'Send {} files from {} folder{}?'.format(
            len(files), folders, '' if folders == 1 else 's'),
            partial(_finish, fm, files))
        return None
    return _finish(fm, files)


def prompt_save(fm, fobj=None):
    """Save mode: open the console prefilled with where the save would go.

      no fobj        → <cwd>/<suggested>       (⏎: save here, the ghost row;
                                                bumped to 'name (N).ext' if taken)
      folder         → <folder>/<suggested>   (bumped likewise)
      existing file  → that file               (l on it: pick_save asks y/N)
    The placeholder itself never counts as 'taken'.
    """
    ph = placeholder()
    cwd = fm.thisdir.path
    if fobj is not None and fobj.is_directory:
        target = os.path.join(fobj.path, unique_name(fobj.path, suggested_name(ph), free=ph))
    elif fobj is not None and not _is_placeholder(fobj.path) and os.path.isfile(fobj.path):
        target = fobj.path
    else:
        target = os.path.join(cwd, unique_name(cwd, suggested_name(ph), free=ph))
    fm.open_console('pick_save ' + console_path(target, cwd))


class enter_or_pick(Command):
    """:enter_or_pick

    Bound to <CR> — the "finish" key in every picker mode:
      dir    pick the highlighted folder (empty folder → pick the current one)
      save   open the pick_save console prefilled with <cwd>/<name>: the
             file always goes in the folder you are in (the ghost row);
             folders are entered with l, files replaced with l
      multi  folder → enter it (always, even with marks);
             file → send marks + selection + this file (folders flattened)
      open   like `move right=1` (folder → enter; file → picked, see
             plugins/picker_mode.py)
    Outside a picker: plain `move right=1`.
    """

    def execute(self):
        mode = picker_mode()
        target = self.fm.thisfile
        if mode == 'dir':
            if target is not None and target.is_directory:
                _finish(self.fm, [target.path])
            else:
                _finish(self.fm, [self.fm.thisdir.path])
        elif mode == 'save':
            prompt_save(self.fm)
        elif mode == 'multi' and target is not None and not target.is_directory:
            pick_files(self.fm, target.path)
        else:
            self.fm.move(right=1)


class escape_or_cancel(Command):
    """:escape_or_cancel

    Bound to <Esc>.  Visual mode → leave it (in every context).
    In a picker dialog → cancel the dialog, like GTK's Esc.
    Outside a picker → clear all marks.
    """

    def execute(self):
        if self.fm.mode != 'normal':
            self.fm.change_mode('normal')
            if picker_mode() is None:
                self.fm.mark_files(all=True, val=False)
            return
        if picker_mode() is not None:
            self.fm.execute_console('quitall')     # nothing is written: cancel
        else:
            self.fm.mark_files(all=True, val=False)


class pick_selection(Command):
    """:pick_selection

    Multi-file picker: send every marked file (all visited dirs) plus the
    current selection. Marked folders are flattened: each file inside is sent
    individually (hidden entries skipped).
    """

    def execute(self):
        pick_files(self.fm)


class pick_archive(Command):
    """:pick_archive [name.zip]

    Zip the selection (marked files/folders, or the highlighted item) into
    a fresh private /tmp/ranger-upload-XXXXXXXX/<name> ($TMPDIR honoured)
    and send that single archive. Upload dirs older than a day are
    removed on the next pick. Without a name,
    opens the console prefilled with a default so it can be edited.
    Folder structure is kept relative to the items' common parent; hidden
    entries inside marked folders are skipped.
    """

    def execute(self):
        args = _picker_args()
        if not (getattr(args, 'choosefiles', None) or getattr(args, 'choosefile', None)):
            self.fm.notify('pick_archive: not running as a file picker', bad=True)
            return
        items = _marked_and_selected(self.fm)
        if not items:
            return
        if not self.arg(1):
            base = os.path.basename(items[0]) if len(items) == 1 else \
                os.path.basename(self.fm.thisdir.path) or 'upload'
            base = os.path.splitext(base)[0] if os.path.isfile(items[0]) and len(items) == 1 else base
            self.fm.open_console('pick_archive ' + base + '.zip')
            return

        name = self.rest(1).strip()
        if not name.lower().endswith('.zip'):
            name += '.zip'
        name = os.path.basename(name)

        base = _upload_base()
        _clean_uploads(base)
        parents = [os.path.dirname(p.rstrip('/')) for p in items]
        root = os.path.commonpath(parents) if parents else self.fm.thisdir.path
        # One private dir per pick: Firefox reads the file lazily (on form
        # submit), so an earlier field's archive must never be overwritten.
        updir = tempfile.mkdtemp(prefix=UPLOAD_PREFIX, dir=base)
        dest = os.path.join(updir, name)
        count = 0
        try:
            with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as zf:
                for item in items:
                    sources = _walk_files(item) if os.path.isdir(item) else [item]
                    for path in sources:
                        if os.path.isfile(path):
                            zf.write(path, os.path.relpath(path, root))
                            count += 1
        except OSError as ex:
            shutil.rmtree(updir, ignore_errors=True)
            self.fm.notify('Cannot create archive: {}'.format(ex.strerror or ex), bad=True)
            return
        if not count:
            shutil.rmtree(updir, ignore_errors=True)
            self.fm.notify('Nothing to archive', bad=True)
            return
        if _finish(self.fm, [dest]) is False:
            shutil.rmtree(updir, ignore_errors=True)


class pick_save(Command):
    """:pick_save <path>

    Save-dialog finish. <path> is relative to the current folder (~ ok); a
    folder or trailing '/' gets the suggested name appended. New path → the
    portal's placeholder is moved there. Existing file → asks
    'Overwrite <name>? (y/N)'. Missing folder → error, stay in ranger.
    """
    # paths are literal: never expand ranger's %macros (%d, %f, …)
    resolve_macros = False

    def execute(self):
        if picker_mode() != 'save':
            self.fm.notify('pick_save: not in a save dialog', bad=True)
            return
        ph = placeholder()
        target = resolve_target(self.rest(1), self.fm.thisdir.path, suggested_name(ph))
        parent = os.path.dirname(target)
        if not os.path.isdir(parent):
            self.fm.notify('No such folder: ' + parent, bad=True)
            return
        if _is_placeholder(target):
            _finish(self.fm, [target])
            return
        if '\n' in target:
            self.fm.notify('Cannot save to a name containing a newline', bad=True)
            return
        if os.path.isdir(target):
            self.fm.notify('Is a folder: ' + target, bad=True)
            return
        if os.path.lexists(target) and not os.path.exists(target):
            self.fm.notify('Broken link: ' + target, bad=True)
            return
        if os.path.lexists(target):
            self.fm.ui.console.ask(
                'Overwrite {}? (y/N)'.format(os.path.basename(target)),
                partial(self._confirm, target),
                ('n', 'N', 'y', 'Y'),
            )
            return
        moved = bool(ph) and os.path.exists(ph)
        try:
            if moved:
                shutil.move(ph, target)
            else:
                open(target, 'a').close()   # portal needs the path to exist
        except OSError as ex:
            self.fm.notify('Cannot save to {}: {}'.format(target, ex.strerror), bad=True)
            return
        _finish(self.fm, [target])
        # Only reached if the result couldn't be written: undo, so no
        # help-text file (or empty file) is left behind at the target.
        try:
            if moved:
                shutil.move(target, ph)
            else:
                os.remove(target)
        except OSError:
            pass

    def _confirm(self, target, answer):
        if answer in ('y', 'Y'):
            _finish(self.fm, [target])
            return                      # only reached if writing failed (notified)
        self.fm.notify('Not saved — pick another name')

    def tab(self, tabnum):
        return self._tab_directory_content()


class pick_location(Command):
    """:pick_location [path]      (<C-l>, like GTK's Ctrl+L)

    Picker only (elsewhere <C-l> keeps redrawing the window). Without a path,
    opens the console prefilled with the current folder. Folder → cd there;
    in a folder dialog (dir mode) a typed folder is picked immediately
    instead (GTK location-bar behaviour: typed folder + <CR> picks it).
    File → pick it (open/multi) or save to it (save, with y/N). A new path in
    save mode → save there.
    """
    # paths are literal: never expand ranger's %macros (%d, %f, …)
    resolve_macros = False

    def execute(self):
        mode = picker_mode()
        if mode is None:
            self.fm.execute_console('redraw_window')
            return
        text = self.rest(1).rstrip('\r\n')
        if not text.strip():
            self.fm.open_console('pick_location ' + tilde(self.fm.thisdir.path) + '/')
            return
        cwd = self.fm.thisdir.path
        path = os.path.normpath(os.path.join(cwd, os.path.expanduser(text)))
        if not os.path.lexists(path) and text != text.strip():
            # stray spaces: use the existing path they hide, if there is one
            alt = os.path.normpath(os.path.join(cwd, os.path.expanduser(text.strip())))
            if os.path.lexists(alt):
                path, text = alt, text.strip()
        if os.path.isdir(path):
            if mode == 'dir':
                _finish(self.fm, [path])   # location-bar behaviour: pick it now
            else:
                self.fm.cd(path)
        elif mode == 'save':
            self.fm.execute_console('pick_save ' + path + ('/' if text.endswith('/') else ''))
        elif not os.path.isfile(path):
            self.fm.notify('No such file or folder: ' + path, bad=True)
        elif mode == 'dir':
            self.fm.notify('Not a folder: ' + path, bad=True)
        else:
            _finish(self.fm, [path])

    def tab(self, tabnum):
        return self._tab_directory_content()
