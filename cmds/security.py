from __future__ import (absolute_import, division, print_function)
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from ranger.api.commands import Command
from cmds._util import pager_argv, clipboard_copy, require_tool, unique_dest


_HASH_TOOLS = {
    'sha256': 'sha256sum',
    'sha1':   'sha1sum',
    'sha512': 'sha512sum',
    'md5':    'md5sum',
}


def _page(fm, data):
    """Show bytes `data` in the pager through fm.run, so curses is suspended
    and restored properly (a bare Popen fights curses for the terminal)."""
    fd, path = tempfile.mkstemp(prefix='ranger-hash-', suffix='.txt')
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
        fm.run(pager_argv(wide=True) + [path])
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


class hash_show(Command):
    """:hash_show [algo]  (<Space>hs)

    Compute checksums of selected files and display in a pager.
    algo: sha256 (default) | sha1 | sha512 | md5
    """

    def execute(self):
        algo = self.arg(1) or 'sha256'
        tool = _HASH_TOOLS.get(algo)
        if not tool:
            self.fm.notify(
                "Unknown algo: {}  (sha256/sha1/sha512/md5)".format(algo), bad=True)
            return
        if not require_tool(self.fm, tool):
            return

        selection = self.fm.thistab.get_selection()
        files = [f.path for f in selection if not f.is_directory]
        if not files:
            self.fm.notify("No files in selection", bad=True)
            return

        result = subprocess.run([tool, '--'] + files, capture_output=True)
        output = result.stdout
        if result.stderr:
            output += b'\n' + result.stderr

        _page(self.fm, output)


class hash_verify(Command):
    """:hash_verify [checksum-file]  (<Space>hv)

    Verify files against a checksum file.  Without argument: fzf-picks from cwd.
    Algorithm auto-detected from extension: .sha256 .sha512 .sha1 .md5.
    """

    _EXTS = ('.sha256', '.SHA256', '.sha512', '.SHA512', '.sha1', '.SHA1', '.md5', '.MD5')
    _EXT_TOOL = {
        '.sha256': 'sha256sum', '.SHA256': 'sha256sum',
        '.sha512': 'sha512sum', '.SHA512': 'sha512sum',
        '.sha1':   'sha1sum',   '.SHA1':   'sha1sum',
        '.md5':    'md5sum',    '.MD5':    'md5sum',
    }

    def execute(self):
        arg = self.rest(1)
        if arg:
            checkfile = os.path.expanduser(arg)
        else:
            candidates = [
                f for f in os.listdir(self.fm.thisdir.path)
                if os.path.splitext(f)[1] in self._EXTS
            ]
            if not candidates:
                self.fm.notify("No checksum files found in cwd", bad=True)
                return
            if len(candidates) == 1:
                checkfile = os.path.join(self.fm.thisdir.path, candidates[0])
            else:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.in', delete=False) as tf:
                    tf.write('\n'.join(candidates))
                    in_file = tf.name
                fd, out_file = tempfile.mkstemp(suffix='.out')
                os.close(fd)
                try:
                    self.fm.run(
                        'fzf --border --header={} < {} > {}'.format(
                            shlex.quote('Select checksum file'),
                            shlex.quote(in_file),
                            shlex.quote(out_file),
                        )
                    )
                    try:
                        with open(out_file) as f:
                            sel = f.read().strip()
                    except OSError:
                        sel = ''
                finally:
                    for tmp in [in_file, out_file]:
                        try:
                            os.unlink(tmp)
                        except OSError:
                            pass
                if not sel:
                    return
                checkfile = os.path.join(self.fm.thisdir.path, sel)

        if not os.path.isfile(checkfile):
            self.fm.notify("Not found: " + checkfile, bad=True)
            return

        ext  = os.path.splitext(checkfile)[1]
        tool = self._EXT_TOOL.get(ext, 'sha256sum')

        result = subprocess.run(
            [tool, '--check', '--', checkfile],
            capture_output=True, text=True,
            cwd=self.fm.thisdir.path,
        )
        _page(self.fm, (result.stdout + result.stderr).encode('utf-8', 'replace'))

    def tab(self, tabnum):
        return self._tab_directory_content()


class hash_copy(Command):
    """:hash_copy [algo]  (<Space>hc)

    Digest(s) of selected files → system clipboard.
    algo: sha256 (default) | sha1 | sha512 | md5
    Single file: copies the bare digest.
    Multiple files: copies "digest  filename" lines (sha256sum format).
    """

    def execute(self):
        algo = self.arg(1) or 'sha256'
        tool = _HASH_TOOLS.get(algo)
        if not tool:
            self.fm.notify(
                "Unknown algo: {}  (sha256/sha1/sha512/md5)".format(algo), bad=True)
            return
        if not require_tool(self.fm, tool):
            return

        selection = self.fm.thistab.get_selection()
        if not selection and self.fm.thisfile is not None:
            selection = [self.fm.thisfile]
        files = [f for f in selection if f is not None and not os.path.isdir(f.path)]
        if not files:
            self.fm.notify("Select files, not directories", bad=True)
            return
        result = subprocess.run(
            [tool, '--'] + [f.path for f in files],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            self.fm.notify("{} failed".format(tool), bad=True)
            return
        lines = result.stdout.splitlines()
        label = algo.upper()
        if len(files) == 1:
            digest = lines[0].split()[0]
            if not clipboard_copy(self.fm, digest):
                return
            self.fm.notify("{} copied: {}…".format(label, digest[:16]))
        else:
            out_lines = []
            for line in lines:
                parts = line.split(None, 1)
                if len(parts) == 2:
                    out_lines.append('{}  {}'.format(parts[0], os.path.basename(parts[1])))
            text = '\n'.join(out_lines)
            if not clipboard_copy(self.fm, text):
                return
            self.fm.notify("{} copied for {} files".format(label, len(files)))


class encrypt_file(Command):
    """:encrypt_file  (<Space>ee)

    Encrypt selected files with age -p (passphrase), fallback to gpg -c.
    Output: <file>.age or <file>.gpg written alongside the source.
    Passphrase is entered interactively in the terminal.
    """

    def execute(self):
        selection = self.fm.thistab.get_selection()
        files = [f.path for f in selection if not f.is_directory]
        if not files:
            self.fm.notify("No files selected", bad=True)
            return

        if shutil.which('age'):
            for path in files:
                out = unique_dest(path + '.age')
                self.fm.run(
                    'age -p -o {} -- {}'.format(shlex.quote(out), shlex.quote(path))
                )
        elif shutil.which('gpg'):
            for path in files:
                self.fm.run('gpg -c -- {}'.format(shlex.quote(path)))
        else:
            self.fm.notify("No encryption tool found — install age or gpg", bad=True)
            return

        self.fm.reload_cwd()


class decrypt_file(Command):
    """:decrypt_file  (<Space>ed)

    Decrypt current file.  Algorithm chosen by extension:
      .age → age -d     .gpg → gpg -d
    Output is written alongside the encrypted file (extension stripped).
    """

    def execute(self):
        if self.fm.thisfile is None:
            self.fm.notify("No file under cursor", bad=True)
            return
        path = self.fm.thisfile.path
        ext  = os.path.splitext(path)[1].lower()

        if ext == '.age':
            if not shutil.which('age'):
                self.fm.notify("age not installed", bad=True)
                return
            out = unique_dest(path[:-4])
            cmd = 'age -d -o {} -- {}'.format(shlex.quote(out), shlex.quote(path))
        elif ext == '.gpg':
            if not shutil.which('gpg'):
                self.fm.notify("gpg not installed", bad=True)
                return
            out = unique_dest(path[:-4])
            cmd = 'gpg -d -o {} -- {}'.format(shlex.quote(out), shlex.quote(path))
        else:
            self.fm.notify(
                "Unknown extension '{}' — select a .age or .gpg file".format(ext), bad=True
            )
            return

        self.fm.run(cmd)
        self.fm.reload_cwd()


class veracrypt_mount(Command):
    """:veracrypt_mount [mountpoint]  (<Space>em)

    Mount a VeraCrypt container (.hc / .vc) interactively.
    Without argument: creates $XDG_RUNTIME_DIR/vc/<name>/ as mountpoint.
    With argument: uses the supplied path (created if needed).
    Navigates to the mountpoint on success.
    """

    _CONTAINER_EXTS = {'.hc', '.vc', '.tc'}

    def execute(self):
        if not shutil.which('veracrypt'):
            self.fm.notify("veracrypt not installed", bad=True)
            return

        f = self.fm.thisfile
        if f is None or not os.path.isfile(f.path):
            self.fm.notify("Select a VeraCrypt container file (.hc)", bad=True)
            return

        container = f.path
        ext = os.path.splitext(container)[1].lower()
        if ext not in self._CONTAINER_EXTS:
            self.fm.notify(
                "Not a recognised container extension ({})"
                " — select a .hc/.vc/.tc file".format(ext),
                bad=True,
            )
            return

        arg = self.rest(1).strip()
        if arg:
            mountpoint = os.path.expanduser(arg)
        else:
            base = os.path.splitext(os.path.basename(container))[0]
            runtime = os.environ.get('XDG_RUNTIME_DIR', '/tmp')
            mountpoint = os.path.join(runtime, 'vc', base)

        try:
            os.makedirs(mountpoint, mode=0o700, exist_ok=True)
        except OSError as exc:
            self.fm.notify("Cannot create mountpoint: " + str(exc), bad=True)
            return

        # --pim=0 -k "" --protect-hidden=no skips the PIM / keyfile /
        # hidden-volume prompts so only the password is asked interactively.
        self.fm.run(
            'veracrypt --text --pim=0 -k "" --protect-hidden=no --mount {} {}'.format(
                shlex.quote(container), shlex.quote(mountpoint)
            )
        )

        if os.path.ismount(mountpoint):
            self.fm.cd(mountpoint)
        else:
            self.fm.notify("Mount failed — see veracrypt output above", bad=True)
            try:
                os.rmdir(mountpoint)
            except OSError:
                pass

    def tab(self, tabnum):
        return self._tab_directory_content()


class veracrypt_umount(Command):
    """:veracrypt_umount  (<Space>eu)

    List mounted VeraCrypt volumes via fzf and dismount the chosen one.
    """

    _SLOT_RE = re.compile(r'^(\d+):')

    def execute(self):
        if not shutil.which('veracrypt'):
            self.fm.notify("veracrypt not installed", bad=True)
            return

        result = subprocess.run(
            ['veracrypt', '--text', '--list'],
            capture_output=True, text=True,
        )
        raw = result.stdout.strip()
        if result.returncode != 0 or not raw:
            msg = result.stderr.strip() or raw
            if not msg or 'No volumes' in msg:
                self.fm.notify("No VeraCrypt volumes mounted")
            else:
                self.fm.notify("veracrypt --list: " + msg, bad=True)
            return

        lines = [l for l in raw.splitlines() if self._SLOT_RE.match(l)]
        if not lines:
            self.fm.notify("No VeraCrypt volumes mounted")
            return

        # Format: "1: /path/volume.hc /dev/mapper/veracryptX /mountpoint"
        entries = []
        for line in lines:
            m = self._SLOT_RE.match(line)
            slot = m.group(1)
            parts = line.split()
            vol_name = os.path.basename(parts[1]) if len(parts) > 1 else '?'
            mountpoint = parts[-1] if len(parts) >= 4 else None
            display = 'slot {:<3} {}  →  {}'.format(
                slot, vol_name, mountpoint or '?'
            )
            entries.append((display, slot, mountpoint))

        fd, in_file = tempfile.mkstemp(suffix='.in')
        os.close(fd)
        fd, out_file = tempfile.mkstemp(suffix='.out')
        os.close(fd)
        try:
            with open(in_file, 'w') as fh:
                fh.write('\n'.join(d for d, _, _ in entries))
            self.fm.run(
                'fzf --border --prompt="Dismount> " '
                '--header="Select VeraCrypt volume to dismount" '
                '< {} > {}'.format(shlex.quote(in_file), shlex.quote(out_file))
            )
            try:
                with open(out_file) as fh:
                    selected = fh.read().strip()
            except OSError:
                selected = ''
        finally:
            for tmp in (in_file, out_file):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

        if not selected:
            return

        slot = mountpoint = None
        for display, s, mp in entries:
            if display == selected:
                slot, mountpoint = s, mp
                break
        if slot is None:
            return

        result = subprocess.run(
            ['veracrypt', '--text', '--dismount', '--slot=' + slot],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            self.fm.notify("Dismounted slot " + slot)
            if mountpoint:
                runtime = os.environ.get('XDG_RUNTIME_DIR', '/tmp')
                vc_dir = os.path.join(runtime, 'vc')
                if mountpoint.startswith(vc_dir + os.sep):
                    try:
                        os.rmdir(mountpoint)
                    except OSError:
                        pass
        else:
            self.fm.notify(
                "dismount failed: " + (result.stderr.strip() or result.stdout.strip()),
                bad=True,
            )
