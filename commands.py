# commands.py — custom ranger commands
#
# Every Command subclass defined here becomes a ranger console command.

from __future__ import (absolute_import, division, print_function)

import atexit
import os
import re as _re
import shlex
import shutil
import subprocess
from ranger.api.commands import Command


# ═══ shared helpers ════════════════════════════════════════════════════════

# Base directory for all sshfs mounts.
SSH_MOUNT_BASE = '/tmp/ranger-sshfs'


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:          # EPERM: exists, owned by someone else
        return True


def ssh_mount_users(mount_dir, add=None, remove=None):
    """Update and return the live ranger PIDs using an sshfs mount.

    The list lives in <mount_dir>.pid, one PID per line, guarded by flock
    so concurrent rangers don't clobber each other.  Dead PIDs are pruned.
    The file is removed when the list ends up empty.  An instance unmounts
    only when it is the last user, so rangers sharing a host never unmount
    each other's mount.
    """
    import fcntl
    path = mount_dir + '.pid'
    try:
        fh = open(path, 'a+')
    except OSError:
        return []
    with fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        pids = []
        for line in fh.read().split():
            try:
                pid = int(line)
            except ValueError:
                continue
            if pid not in pids and pid != remove and _pid_alive(pid):
                pids.append(pid)
        if add is not None and add not in pids:
            pids.append(add)
        fh.seek(0)
        fh.truncate()
        fh.write(''.join('{}\n'.format(p) for p in pids))
        fh.flush()
        if not pids:
            try:
                os.remove(path)
            except OSError:
                pass
    return pids


def fuse_unmount(mount_dir):
    """Unmount (normal, then lazy) and remove the mount dir.  Returns
    (ok, error_text)."""
    err = ''
    for cmd in (['fusermount3', '-u'], ['fusermount', '-u'],
                ['fusermount3', '-uz'], ['fusermount', '-uz']):
        try:
            r = subprocess.run(cmd + ['--', mount_dir], capture_output=True, text=True)
        except OSError:
            continue
        if r.returncode == 0:
            try:
                os.rmdir(mount_dir)
            except OSError:
                pass
            return True, ''
        err = err or r.stderr.strip()
    return False, err or 'fusermount not found'


def get_selection(fm, min_count=1, msg=None):
    """Return the current selection, or notify + return None if too few items.

    min_count: minimum number of selected items required (default 1).
    msg: override the default notification message.
    """
    sel = fm.thistab.get_selection()
    if len(sel) < min_count:
        if msg is None:
            msg = "Select 2+ items" if min_count > 1 else "Nothing selected"
        fm.notify(msg, bad=True)
        return None
    return sel


def require_tool(fm, tool, msg=None):
    """Return True if `tool` is on PATH, otherwise notify and return False."""
    if shutil.which(tool):
        return True
    fm.notify(msg or "Tool not found: {}".format(tool), bad=True)
    return False


def unique_dest(path, is_dir=False, taken=None):
    """Return path unchanged if nothing (not even a broken symlink) is there,
    otherwise suffix _1, _2, … before the extension (or after the whole
    name when is_dir — directory names rarely have extensions).

    taken: a set of paths already planned by the same batch (a.jpg and
    a.png both converting to a.webp); the result is added to it."""
    def used(p):
        return os.path.lexists(p) or (taken is not None and p in taken)
    base, ext = (path, '') if is_dir else os.path.splitext(path)
    n = 1
    while used(path):
        path = '{}_{}{}'.format(base, n, ext)
        n += 1
    if taken is not None:
        taken.add(path)
    return path


def transfer_items(paths, dest_dir, copy=False):
    """Move (or copy) each path into dest_dir, one at a time.

    Never overwrites: a name collision gets a _N suffix.  Directories are
    copied with copytree (symlinks inside kept as symlinks; a selected symlink
    is copied as what it points to).  Items already in
    dest_dir are skipped for a move.  Errors are collected per item instead
    of aborting the batch.  Returns (done, renamed, failed_messages).
    """
    done = renamed = 0
    failed = []
    for src in paths:
        name = os.path.basename(src.rstrip(os.sep))
        try:
            if not copy and os.path.realpath(os.path.dirname(src)) == \
                    os.path.realpath(dest_dir):
                continue                                  # already there
            # copy follows a selected symlink: a relative link copied as a
            # link would dangle at any other depth; links inside a copied
            # tree are kept as links
            is_dir = os.path.isdir(src) if copy else \
                os.path.isdir(src) and not os.path.islink(src)
            target = os.path.join(dest_dir, name)
            out = unique_dest(target, is_dir=is_dir)
            if copy:
                if is_dir:
                    shutil.copytree(src, out, symlinks=True)
                else:
                    shutil.copy2(src, out)
            else:
                shutil.move(src, out)
            done += 1
            renamed += out != target
        except (OSError, shutil.Error) as ex:
            failed.append('{}: {}'.format(name, ex))
    return done, renamed, failed


def pager_str(color=False):
    """Return a pager command string, honouring $PAGER. Falls back to more.
    color=True appends -R when the resolved pager is less.
    """
    env = os.environ.get('PAGER', '')
    for p in ([env] if env else []) + ['less', 'more']:
        bin_ = shlex.split(p)[0] if p else ''
        if bin_ and shutil.which(bin_):
            if color and bin_.endswith('less') and '-R' not in p:
                return p.strip() + ' -R'
            return p.strip()
    return 'cat'


def pager_argv(wide=False):
    """Return argv list for the best available pager.
    Respects $PAGER; falls back to less, then more.
    wide=True appends -S (no line wrap) when the pager is less.
    """
    env = shlex.split(os.environ.get('PAGER', ''))
    for args in ([env] if env else []) + [['less'], ['more']]:
        if shutil.which(args[0]):
            if wide and args[0].endswith('less') and '-S' not in args:
                args = args + ['-S']
            return args
    return ['cat']


def clipboard_copy(fm, data):
    """Copy text `data` to the system clipboard, Wayland or X11.

    Tries wl-copy, then xclip, then xsel. Notifies (bad=True) and returns
    False if none are available or the copy failed.
    """
    if shutil.which('wl-copy'):
        cmd = ['wl-copy', '--']
    elif shutil.which('xclip'):
        cmd = ['xclip', '-selection', 'clipboard']
    elif shutil.which('xsel'):
        cmd = ['xsel', '--clipboard', '--input']
    else:
        fm.notify("No clipboard tool found — install wl-clipboard or xclip", bad=True)
        return False

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    proc.communicate(data.encode())
    return proc.returncode == 0


def ask_yes(fm, prompt, on_yes, on_no=None):
    """Ask a y/N question in ranger's console; Enter and Esc both mean no.

    Unlike pre-filling "cmd confirm" in the console, nothing lands in the
    console history, so a destructive command can't be replayed with C-p.
    """
    def _answer(ans):
        if ans in ('y', 'Y'):
            on_yes()
        elif on_no is not None:
            on_no()
    fm.ui.console.ask('{} (y/N)'.format(prompt), _answer, ('n', 'N', 'y', 'Y'))


_BASE = SSH_MOUNT_BASE


# ═══ ssh ═══════════════════════════════════════════════════════════════════

# Tracks all mounts opened this ranger session: mount_dir -> (host, remote_base_path)
# Populated by ssh_mount, consumed by ssh_shell and ssh_unmount.
_ssh_sessions = {}


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
