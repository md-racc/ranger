from __future__ import (absolute_import, division, print_function)
import atexit
import os
import posixpath
import re as _re
import shlex
import subprocess
from ranger.api.commands import Command
from cmds._util import (SSH_MOUNT_BASE as _BASE, fuse_unmount, require_tool,
                        ssh_mount_users, unique_dest)

# Tracks all mounts opened this ranger session: mount_dir -> (host, remote_base_path)
# Populated by ssh_mount, consumed by ssh_shell, ssh_unmount and ssh_copy.
_ssh_sessions = {}


def _find_mount(path):
    """Return (mount_dir, host, remote_base_path) for the session owning `path`,
    or (None, None, None) if `path` isn't inside any known SSHFS mount."""
    path = os.path.abspath(path)
    best = None
    for mount_dir in _ssh_sessions:
        if path == mount_dir or path.startswith(mount_dir + os.sep):
            if best is None or len(mount_dir) > len(best):
                best = mount_dir
    if best is None:
        return None, None, None
    host, remote_base = _ssh_sessions[best]
    return best, host, remote_base


def _release_mount(mount_dir):
    """Stop using mount_dir in this ranger.  Unmounts only when no other
    live ranger still uses it.  Returns (unmounted, other_pids, error)."""
    _ssh_sessions.pop(mount_dir, None)
    others = ssh_mount_users(mount_dir, remove=os.getpid())
    if others:
        return False, others, ''
    if not os.path.ismount(mount_dir):
        try:
            os.rmdir(mount_dir)
        except OSError:
            pass
        return True, [], ''
    ok, err = fuse_unmount(mount_dir)
    if not ok:
        # Keep our claim so the stale-mount sweep can retry later.
        ssh_mount_users(mount_dir, add=os.getpid())
    return ok, [], err


def _cleanup_ssh_mounts():
    """On exit: release every sshfs mount this session uses (unmounting the
    ones no other ranger is using)."""
    for mount_dir in list(_ssh_sessions):
        _release_mount(mount_dir)


atexit.register(_cleanup_ssh_mounts)


class ssh_mount(Command):
    """:ssh_mount <[user@]host[:/path]>

    Mount a remote filesystem via SSHFS and open it in a new tab.
    All mounts created this session are automatically unmounted when
    ranger exits. Tab-completes from ~/.ssh/config Host entries.

    Examples:
      :ssh_mount myserver
      :ssh_mount user@myserver:/data
      :ssh_mount user@203.0.113.10:/srv/share
    """

    def execute(self):
        target = self.rest(1).strip()
        if not target:
            self.fm.notify("Usage: ssh_mount [user@]host[:/path]", bad=True)
            return

        if ':' not in target:
            target += ':'

        host, remote_base = target.split(':', 1)

        safe = _re.sub(r'[^a-zA-Z0-9._-]', '_', target)
        mount_dir = _BASE + '/' + safe

        if os.path.ismount(mount_dir):
            # Already mounted — by this ranger or another one: share it.
            _ssh_sessions[mount_dir] = (host, remote_base)
            ssh_mount_users(mount_dir, add=os.getpid())
            self.fm.tab_new(mount_dir)
            self.fm.cd(mount_dir)
            self.fm.notify("Reusing mount: " + target)
            return
        _ssh_sessions.pop(mount_dir, None)   # tracked but gone: remount

        if not require_tool(self.fm, 'sshfs'):
            return
        os.makedirs(mount_dir, exist_ok=True)

        self.fm.notify("Mounting " + target + " ...")
        result = subprocess.run(
            ['sshfs',
             '-o', 'ControlMaster=auto,ControlPath=~/.ssh/cm-%r@%h:%p,ControlPersist=60',
             '--', target, mount_dir],
            capture_output=True, text=True,
        )

        if result.returncode != 0:
            try:
                os.rmdir(mount_dir)
            except OSError:
                pass
            self.fm.notify(result.stderr.strip() or 'sshfs: mount failed', bad=True)
            return

        _ssh_sessions[mount_dir] = (host, remote_base)
        ssh_mount_users(mount_dir, add=os.getpid())
        self.fm.notify("Mounted " + target)
        self.fm.tab_new(mount_dir)
        self.fm.cd(mount_dir)

    def tab(self, tabnum):
        """Tab-complete Host entries from ~/.ssh/config."""
        hosts = []
        config_path = os.path.expanduser('~/.ssh/config')
        if os.path.exists(config_path):
            with open(config_path) as f:
                for line in f:
                    m = _re.match(r'^\s*Host\s+(.+)', line, _re.IGNORECASE)
                    if m:
                        for h in m.group(1).split():
                            if '*' not in h and '?' not in h:
                                hosts.append(h)
        partial = self.rest(1)
        return [self.start(1) + h for h in hosts if h.startswith(partial)]


class ssh_shell(Command):
    """:ssh_shell

    Open an interactive SSH session to the host of the current SSHFS mount.
    Suspends ranger's UI and returns when you exit the remote shell.
    Run from anywhere inside an ssh_mount tab.
    """

    def execute(self):
        cwd = self.fm.thisdir.path
        m = _re.match(r'(' + _re.escape(_BASE) + r'/[^/]+)', cwd)
        if not m:
            self.fm.notify("Not inside an SSH mount", bad=True)
            return

        mount_dir = m.group(1)
        session = _ssh_sessions.get(mount_dir)
        if not session:
            self.fm.notify("No session info for this mount", bad=True)
            return

        self.fm.run(['ssh', '--', session[0]])


class ssh_unmount(Command):
    """:ssh_unmount

    Manually unmount the SSHFS mount for the current tab and close it.
    All mounts are also cleaned up automatically when ranger exits.
    """

    def execute(self):
        cwd = self.fm.thisdir.path
        m = _re.match(r'(' + _re.escape(_BASE) + r'/[^/]+)', cwd)
        if not m:
            self.fm.notify("Not inside an SSH mount", bad=True)
            return

        mount_dir = m.group(1)
        self.fm.cd(os.path.expanduser('~'))

        unmounted, others, err = _release_mount(mount_dir)
        if unmounted:
            self.fm.notify("Unmounted")
            self.fm.tab_close()
        elif others:
            self.fm.notify("Left mount in place — still used by ranger PID {}".format(
                ', '.join(str(p) for p in others)))
            self.fm.tab_close()
        else:
            self.fm.notify('Unmount failed: ' + err, bad=True)


class ssh_copy(Command):
    """:ssh_copy [destination]

    Copy the selected file(s) out of the current SSHFS mount via a plain
    `ssh host cat` pipe instead of the FUSE mount.

    Some sshd configs chroot the SFTP subsystem (what sshfs uses) more
    narrowly than an interactive shell. If a mounted file is a symlink
    pointing outside that chroot, sshfs can't resolve it -- readlink/stat
    fail with "Operation not permitted" -- even though `ssh host cat file`
    works fine, since a normal shell session isn't chroot-restricted. Use
    this as a fallback when regular paste fails on an SSHFS-mounted file.

    Destination defaults to the current local directory. Directories in
    the selection are skipped.
    """

    def execute(self):
        dest_arg = self.rest(1).strip()
        dest_dir = os.path.expanduser(dest_arg) if dest_arg else self.fm.thisdir.path

        files = self.fm.thistab.get_selection()
        if not files:
            self.fm.notify("No file selected", bad=True)
            return

        for fobj in files:
            if fobj.is_directory:
                self.fm.notify(
                    "Skipping directory (ssh_copy is file-only): " + fobj.basename, bad=True)
                continue

            mount_dir, host, remote_base = _find_mount(fobj.path)
            if mount_dir is None:
                self.fm.notify(fobj.basename + " is not inside an SSH mount", bad=True)
                continue

            # Writing into the mount would truncate the remote file through
            # FUSE before `ssh cat` reads it.
            real_dest = os.path.realpath(dest_dir)
            real_mount = os.path.realpath(mount_dir)
            if real_dest == real_mount or real_dest.startswith(real_mount + os.sep):
                self.fm.notify(
                    "ssh_copy: destination is inside the SSH mount -- "
                    "pass a local directory, e.g. :ssh_copy ~/Downloads", bad=True)
                return

            rel = os.path.relpath(fobj.path, mount_dir)
            remote_path = posixpath.join(remote_base, rel) if remote_base else rel
            local_path = unique_dest(os.path.join(dest_dir, fobj.basename))
            part_path = local_path + '.part'

            self.fm.notify("Pulling " + fobj.basename + " via ssh ...")
            try:
                with open(part_path, 'wb') as out:
                    result = subprocess.run(
                        ['ssh', host, 'cat', shlex.quote(remote_path)],
                        stdout=out, stderr=subprocess.PIPE,
                    )
            except OSError as ex:
                self.fm.notify("ssh_copy failed: " + str(ex), bad=True)
                continue

            if result.returncode != 0:
                self.fm.notify(
                    'ssh_copy failed: '
                    + (result.stderr.decode(errors='replace').strip()
                       or 'ssh exited with an error'),
                    bad=True,
                )
                try:
                    os.remove(part_path)
                except OSError:
                    pass
            else:
                os.replace(part_path, local_path)
                self.fm.notify("Copied " + os.path.basename(local_path))

        self.fm.get_directory(dest_dir).load_content()


# Override quit/quitall to ensure SSH mounts are cleaned up on actual exit,
# while preserving ranger's built-in tab-close and pending-task guards.

class quit(Command):
    """:quit

    Closes the current tab, if there's more than one tab. Otherwise quits
    if there are no tasks in progress, unmounting any active SSH mounts first.
    """

    def _exit_no_work(self):
        if self.fm.loader.has_work():
            self.fm.notify('Not quitting: Tasks in progress: Use `quit!` to force quit')
        else:
            _cleanup_ssh_mounts()
            self.fm.exit()

    def execute(self):
        if len(self.fm.tabs) >= 2:
            self.fm.tab_close()
        else:
            self._exit_no_work()


class quitall(Command):
    """:quitall

    Quits if there are no tasks in progress, unmounting any active SSH
    mounts first.
    """

    def _exit_no_work(self):
        if self.fm.loader.has_work():
            self.fm.notify('Not quitting: Tasks in progress: Use `quitall!` to force quit')
        else:
            _cleanup_ssh_mounts()
            self.fm.exit()

    def execute(self):
        self._exit_no_work()
