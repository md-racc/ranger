# commands.py — custom ranger commands
#
# Every Command subclass defined here becomes a ranger console command.

from __future__ import (absolute_import, division, print_function)

import atexit
import configparser
import datetime
import glob
import mimetypes
import os
import re
import re as _re
import shlex
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from urllib.parse import quote, unquote
from hashlib import sha1
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


try:
    from ranger.core.loader import Loadable as _Loadable
except ImportError:            # pragma: no cover — only outside ranger
    _Loadable = object


class _BgTask(object):
    """One run_bg job: `work` runs on its own thread from the start.

    The worker must not touch fm/ui directly; it calls ui(fn, *args) to
    queue fn(*args) for the UI thread.  _BgPump drains those queues and
    runs `done` on the UI thread.
    """

    def __init__(self, fm, descr, work, done):
        import queue
        import threading
        self.fm = fm
        self.description = descr
        self._queue = queue.Queue()
        self._work = work
        self._done = done
        self._result = self._error = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _ui(self, fn, *args, **kwargs):
        self._queue.put((fn, args, kwargs))

    def _run(self):
        try:
            self._result = self._work(self._ui)
        except Exception as ex:          # reported on the UI thread
            self._error = ex

    def drain(self):
        import queue
        while True:
            try:
                fn, args, kwargs = self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                fn(*args, **kwargs)
            except Exception as ex:
                self.fm.notify('{}: {}'.format(self.description, ex), bad=True)

    def finish(self):
        self.drain()
        if self._done is not None:
            self._done(self._result, self._error)
        elif self._error is not None:
            self.fm.notify('{}: {}'.format(self.description, self._error), bad=True)


_BG_TASKS = []        # running _BgTask jobs, oldest first
_BG_PUMP = [None]     # the _BgPump currently in the loader, if any


class _BgPump(_Loadable):
    """The single ranger loader item for every run_bg job.

    ranger's loader steps only its first item, so one loader item per job
    would serialise the jobs (a quick image op waiting behind a long
    extract, <Space>ak missing queued extractions).  Jobs run in parallel
    on their own threads; this item just services them from the main loop
    and leaves the loader once none are left.
    """

    def __init__(self, fm):
        self.fm = fm
        _Loadable.__init__(self, self._generate(), 'Background tasks')

    def _describe(self):
        names = [t.description for t in _BG_TASKS]
        self.description = names[0] if len(names) == 1 else \
            '{} background tasks: {}'.format(len(names), ', '.join(names))

    def _generate(self):
        import time
        try:
            while _BG_TASKS:
                self._describe()
                for task in list(_BG_TASKS):
                    task.drain()
                    if not task.thread.is_alive():
                        _BG_TASKS.remove(task)
                        task.finish()
                yield
                time.sleep(0.02)
        finally:
            _BG_PUMP[0] = None

    def destroy(self):
        _BG_PUMP[0] = None
        # Removed from the taskview (Loader.remove calls this while we're
        # still queued): the threads can't be killed, so keep servicing them
        # and their notifications/done() still happen.  At exit
        # Loader.destroy has already popped us: re-adding would never end.
        if _BG_TASKS and self in self.fm.loader.queue:
            _ensure_pump(self.fm)


def _ensure_pump(fm):
    if _BG_PUMP[0] is None:
        _BG_PUMP[0] = _BgPump(fm)
        fm.loader.add(_BG_PUMP[0], append=True)


def run_bg(fm, descr, work, done=None):
    """Run work(ui) off the UI thread; done(result, error) runs on the UI thread.

    work receives ui(fn, *args), which queues fn(*args) to run on the UI
    thread (use it for fm.notify and friends).  Without a ranger loader
    (headless tests) everything runs synchronously.
    """
    loader = getattr(fm, 'loader', None)
    if loader is None:
        result = error = None
        try:
            result = work(lambda fn, *a, **kw: fn(*a, **kw))
        except Exception as ex:
            error = ex
        if done is not None:
            done(result, error)
        elif error is not None:
            fm.notify('{}: {}'.format(descr, error), bad=True)
        return None
    task = _BgTask(fm, descr, work, done)
    _BG_TASKS.append(task)
    _ensure_pump(fm)
    return task


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


# ═══ nav ═══════════════════════════════════════════════════════════════════

class fzf_select(Command):
    """:fzf_select

    Find a file or directory using fzf+fd and jump to it.
    Searches from the current directory. alt-enter opens with rifle.
    """

    def execute(self):
        env = os.environ.copy()
        env['FZF_DEFAULT_COMMAND'] = 'fd --hidden --follow --exclude .git .'
        fzf = subprocess.Popen(
            ['fzf', '--border', '--ansi',
             '--expect=alt-enter',
             '--header=enter: navigate  alt-enter: open with rifle',
             '--preview=bat --color=always --style=plain {} 2>/dev/null || ls --color=always {}'],
            stdout=subprocess.PIPE,
            env=env,
            cwd=self.fm.thisdir.path,
        )
        stdout, _ = fzf.communicate()
        if fzf.returncode == 0:
            lines = os.fsdecode(stdout).split('\n')
            key = lines[0]
            selected = lines[1].strip() if len(lines) > 1 else ''
            if selected:
                selected = os.path.join(self.fm.thisdir.path, selected)
                if key == 'alt-enter':
                    self.fm.run('rifle ' + shlex.quote(selected))
                elif os.path.isdir(selected):
                    self.fm.cd(selected)
                else:
                    self.fm.select_file(selected)


class fzf_home(Command):
    """:fzf_home

    Find a file anywhere under $HOME using fzf+fd and jump to it.
    """

    def execute(self):
        home = os.path.expanduser('~')
        env = os.environ.copy()
        env['FZF_DEFAULT_COMMAND'] = 'fd --hidden --follow --exclude .git . ' + home
        fzf = subprocess.Popen(
            ['fzf', '--border', '--ansi',
             '--preview=bat --color=always --style=plain {} 2>/dev/null || ls --color=always {}'],
            stdout=subprocess.PIPE,
            env=env,
        )
        stdout, _ = fzf.communicate()
        if fzf.returncode == 0:
            selected = os.fsdecode(stdout).strip()
            if selected:
                if os.path.isdir(selected):
                    self.fm.cd(selected)
                else:
                    self.fm.select_file(selected)


class fzf_history(Command):
    """:fzf_history

    Jump to a previously visited directory using fzf.
    """

    def execute(self):
        history = list(self.fm.tabs[self.fm.current_tab].history.history)
        dirs = list(dict.fromkeys(
            h.path for h in history if os.path.isdir(h.path)
        ))
        if not dirs:
            self.fm.notify("No history available", bad=True)
            return
        with tempfile.NamedTemporaryFile(mode='w', suffix='.in', delete=False) as tf:
            tf.write('\n'.join(dirs))
            in_file = tf.name
        fd, out_file = tempfile.mkstemp(suffix='.out')
        os.close(fd)
        try:
            self.fm.run('fzf --border --tac < {} > {}'.format(
                shlex.quote(in_file), shlex.quote(out_file),
            ))
            try:
                with open(out_file, errors='surrogateescape') as f:
                    selected = f.read().strip()
            except OSError:
                selected = ''
            if selected:
                self.fm.cd(selected)
        finally:
            for tmp in [in_file, out_file]:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass


class mkcd(Command):
    """:mkcd <dirname>

    Create a directory and cd into it.
    If files are marked, asks [m]ove / [c]opy / [n]one / <Esc>=cancel.
    """

    def execute(self):
        name = self.rest(1).strip()
        if not name:
            self.fm.notify("Usage: mkcd <dirname>", bad=True)
            return

        path = os.path.join(self.fm.thisdir.path, name)
        selection = [f for f in self.fm.thistab.get_selection()
                     if f.path != path]

        if not selection:
            try:
                os.makedirs(path, exist_ok=True)
            except OSError as ex:
                self.fm.notify("mkcd: {}".format(ex), bad=True)
                return
            self.fm.cd(path)
            return

        def on_answer(answer):
            self.fm.ui.close_console()
            if answer == 'x':   # Escape — abort, don't create dir
                return
            try:
                os.makedirs(path, exist_ok=True)
            except OSError as ex:
                self.fm.notify("mkcd: {}".format(ex), bad=True)
                return
            if answer in ('m', 'c'):
                done, renamed, failed = transfer_items(
                    [f.path for f in selection], path, copy=(answer == 'c'))
                msg = "{} {} → {}/".format(
                    'Copied' if answer == 'c' else 'Moved', done, name)
                if renamed:
                    msg += " ({} renamed to avoid collision)".format(renamed)
                self.fm.notify(msg)
                if failed:
                    self.fm.notify("Failed: " + ';  '.join(failed[:3]), bad=True)
            # 'n': just create and cd, no file ops
            self.fm.cd(path)

        # choices[0] = Enter default, choices[1] = Escape
        self.fm.ui.console.ask(
            "[m]ove  [c]opy  [n]one  <Esc>=cancel  →  {}/".format(name),
            on_answer,
            ('n', 'x', 'm', 'c'),
        )
        self.fm.open_console('')


class z(Command):
    """:z <query>

    Jump to the best matching directory using zoxide.
    Tab-completion lists candidates from the zoxide database.
    """

    def execute(self):
        query = self.rest(1)
        if not query:
            self.fm.notify("Usage: z <query>", bad=True)
            return
        result = subprocess.run(
            ['zoxide', 'query', '--', query],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            target = result.stdout.strip()
            if target and os.path.isdir(target):
                self.fm.cd(target)
            else:
                self.fm.notify("zoxide: no match for '{}'".format(query), bad=True)
        else:
            self.fm.notify("zoxide: not found or no match", bad=True)

    def tab(self, tabnum):
        query = self.rest(1)
        result = subprocess.run(
            ['zoxide', 'query', '--list', '--', query],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            dirs = [d for d in result.stdout.strip().split('\n') if d]
            return [self.start(1) + d for d in dirs]
        return []


def _min_file_depth(root, max_search=20):
    """BFS from root; return the first depth level (1-indexed) that contains files.
    Stops at max_search to avoid hanging on huge trees. Returns 1 on failure."""
    dirs = [root]
    for depth in range(1, max_search + 1):
        next_dirs = []
        for d in dirs:
            try:
                with os.scandir(d) as it:
                    for entry in it:
                        if entry.is_file(follow_symlinks=False):
                            return depth
                        if entry.is_dir(follow_symlinks=False):
                            next_dirs.append(entry.path)
            except OSError:
                continue
        if not next_dirs:
            break
        dirs = next_dirs
    return 1


def _depth_walk(top, maxdepth=None):
    """os.walk limited to maxdepth directory levels (None = unlimited)."""
    top_sep_count = top.rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(top):
        yield root, dirs, files
        if maxdepth is not None:
            if root.rstrip(os.sep).count(os.sep) - top_sep_count >= maxdepth - 1:
                dirs[:] = []


class smart_flatten(Command):
    """:smart_flatten [depth]

    Toggle flat view.
    - Already flat: disable immediately.
    - No depth given: if exactly one directory is selected, cd into it; then
      ask for depth.
    - With a depth: flatten cwd.
    Enabling hides directories (inode_type_filter=f). Any stack filters are untouched.
    """

    def execute(self):
        if self.fm.thisdir.flat > 0:
            self.fm.thisdir.inode_type_filter = ""
            self.fm.thisdir.unload()
            self.fm.thisdir.flat = 0
            self.fm.thisdir.load_content()
            return

        arg = self.arg(1)
        if not arg:
            # First step only: if exactly one directory is selected, cd there
            # so the flat view is scoped to it.  Not repeated when the depth
            # comes back from the console — by then the cursor sits inside
            # that directory and its first subdir would count as "selected".
            selection = self.fm.thistab.get_selection() or []
            target_dirs = [
                f for f in selection
                if f.is_directory and f.path != self.fm.thisdir.path
            ]
            if len(target_dirs) == 1:
                self.fm.cd(target_dirs[0].path)
            self.fm.open_console('smart_flatten 5', position=len('smart_flatten '))
            return

        try:
            depth = max(1, int(arg))
        except ValueError:
            self.fm.notify("Usage: smart_flatten [depth]", bad=True)
            return

        # Auto-bump depth so inode_type_filter=f actually shows files.
        # e.g. top→months→files: min_file_depth=2, user depth=1 → use 2.
        min_depth = _min_file_depth(self.fm.thisdir.path)
        actual = max(depth, min_depth)
        if actual != depth:
            self.fm.notify("Depth bumped to {} (files start at {})".format(actual, min_depth))

        self.fm.thisdir.unload()
        self.fm.thisdir.flat = actual
        self.fm.thisdir.load_content()
        self.fm.thisdir.inode_type_filter = "f"
        self.fm.thisdir.refilter()


def _flatten_plan(dir_paths, depth=None):
    """Return (files_to_move, items_left_behind) for flatten_write.

    files_to_move: every non-directory entry within `depth` levels.
    items_left_behind: entries that won't be moved (files deeper than
    `depth`, symlinks to directories) — their directories are kept.
    """
    to_move, total = [], 0
    for d in dir_paths:
        for root, _, files in _depth_walk(d, depth):
            to_move.extend(os.path.join(root, f) for f in files)
        for root, dirs, files in os.walk(d):
            total += len(files)
            total += sum(1 for x in dirs if os.path.islink(os.path.join(root, x)))
    return to_move, total - len(to_move)


def _flatten_apply(to_move, dest_dir, dir_paths):
    """Move `to_move` into dest_dir (renaming on collision), then remove only
    the directories that are empty afterwards.  Never deletes a file.
    Returns (moved, failed_messages)."""
    moved, failed = 0, []
    for src in to_move:
        try:
            shutil.move(src, unique_dest(os.path.join(dest_dir, os.path.basename(src))))
            moved += 1
        except (OSError, shutil.Error) as ex:
            failed.append('{}: {}'.format(os.path.basename(src), ex))
    for d in dir_paths:
        for root, _, _ in os.walk(d, topdown=False):
            try:
                os.rmdir(root)          # only succeeds when empty
            except OSError:
                pass
    return moved, failed


class flatten_write(Command):
    """:flatten_write [depth] [confirm]   (zW)

    Physically moves the files nested in the selected directories into cwd,
    then removes the directories that end up empty.  Files deeper than
    `depth` (default: unlimited) stay where they are, and so do their
    directories — nothing is ever deleted.

    Asks y/N before moving.  'confirm' skips the question (for scripts).
    """

    def execute(self):
        # Parse args: optional int depth + optional 'confirm' keyword, any order.
        args = self.line.split()[1:]
        confirm = False
        depth = None
        for a in args:
            if a == 'confirm':
                confirm = True
            else:
                try:
                    depth = max(1, int(a))
                except ValueError:
                    self.fm.notify(
                        "Usage: flatten_write [depth] [confirm]", bad=True)
                    return

        selection = self.fm.thistab.get_selection()
        if not selection:
            self.fm.notify("Mark directories explicitly before flattening", bad=True)
            return

        dirs = [f.path for f in selection if f.is_directory and not os.path.islink(f.path)]
        if not dirs:
            self.fm.notify("No directories in selection", bad=True)
            return

        cwd = self.fm.thisdir.path
        to_move, left = _flatten_plan(dirs, depth)
        if not to_move:
            self.fm.notify("No files to move{}".format(
                ' within depth {}'.format(depth) if depth else ''), bad=True)
            return

        def _do():
            moved, failed = _flatten_apply(to_move, cwd, dirs)
            msg = "Moved {} file(s) into {}/".format(moved, os.path.basename(cwd))
            if left:
                msg += "; {} deeper item(s) left in place".format(left)
            self.fm.notify(msg)
            if failed:
                self.fm.notify("Failed: " + ';  '.join(failed[:3]), bad=True)
            self.fm.reload_cwd()

        if confirm:
            _do()
            return
        prompt = "Move {} file(s) from {} dir(s) into {}/ and remove emptied dirs?".format(
            len(to_move), len(dirs), os.path.basename(cwd) or cwd)
        if left:
            prompt += " ({} deeper item(s) stay)".format(left)
        ask_yes(self.fm, prompt, _do)


# ═══ trash ═════════════════════════════════════════════════════════════════

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


# ═══ clipboard ═════════════════════════════════════════════════════════════

def _selection(fm):
    """Return the current visual selection, falling back to the cursor file."""
    sel = fm.thistab.get_selection()
    if not sel and fm.thisfile is not None:
        sel = [fm.thisfile]
    return [f for f in sel if f is not None]


class copy_path(Command):
    """:copy_path  (<Space>yp)

    Copy the full path(s) of selected files to the system clipboard, one per line.
    """

    def execute(self):
        items = _selection(self.fm)
        if not items:
            self.fm.notify("Nothing selected", bad=True)
            return
        text = '\n'.join(f.path for f in items)
        if not clipboard_copy(self.fm, text):
            return
        if len(items) == 1:
            self.fm.notify("Copied path: " + text)
        else:
            self.fm.notify("Copied {} paths".format(len(items)))


class copy_name(Command):
    """:copy_name  (<Space>yn)

    Copy the basename(s) of selected files to the system clipboard, one per line.
    """

    def execute(self):
        items = _selection(self.fm)
        if not items:
            self.fm.notify("Nothing selected", bad=True)
            return
        text = '\n'.join(f.basename for f in items)
        if not clipboard_copy(self.fm, text):
            return
        if len(items) == 1:
            self.fm.notify("Copied name: " + text)
        else:
            self.fm.notify("Copied {} names".format(len(items)))


class copy_name_no_ext(Command):
    """:copy_name_no_ext  (<Space>ye)

    Copy the filename(s) without extension for selected files, one per line.
    """

    def execute(self):
        items = _selection(self.fm)
        if not items:
            self.fm.notify("Nothing selected", bad=True)
            return
        names = [os.path.splitext(f.basename)[0] for f in items]
        text = '\n'.join(names)
        if not clipboard_copy(self.fm, text):
            return
        if len(items) == 1:
            self.fm.notify("Copied: " + text)
        else:
            self.fm.notify("Copied {} names (no ext)".format(len(items)))


class copy_dir(Command):
    """:copy_dir  (<Space>yd)

    Copy the current directory path to the system clipboard.
    """

    def execute(self):
        path = self.fm.thisdir.path
        if not clipboard_copy(self.fm, path):
            return
        self.fm.notify("Copied dir: " + path)


class yank_contents(Command):
    """:yank_contents  (<Space>yy)

    Copy the contents of the current file to the Wayland clipboard.
    """

    def execute(self):
        f = self.fm.thisfile
        if f is None or f.is_directory:
            self.fm.notify("No file under cursor", bad=True)
            return
        path = f.path
        try:
            with open(path, 'rb') as fh:
                rc = subprocess.run(['wl-copy'], stdin=fh).returncode
            if rc != 0:
                self.fm.notify("wl-copy failed (exit {})".format(rc), bad=True)
                return
            self.fm.notify("File contents yanked to clipboard")
        except OSError as e:
            self.fm.notify("yank_contents: {}".format(e), bad=True)


class wl_paste_file(Command):
    """:wl_paste_file  (<Space>yv)

    Write Wayland clipboard into a new file in cwd.
    Images → clipboard-TIMESTAMP.<ext>   Text → clipboard-TIMESTAMP.txt.
    """

    def execute(self):
        cwd = self.fm.thisdir.path
        ts  = time.strftime('%Y%m%d-%H%M%S')

        type_result = subprocess.run(
            ['wl-paste', '--list-types'], capture_output=True, text=True
        )
        types = type_result.stdout.strip().split('\n') if type_result.returncode == 0 else []
        image_type = next((t for t in types if t.startswith('image/')), None)

        if image_type:
            ext = image_type.split('/')[-1].split(';')[0].strip()
            outpath = os.path.join(cwd, 'clipboard-{}.{}'.format(ts, ext))
            with open(outpath, 'wb') as fh:
                proc = subprocess.run(
                    ['wl-paste', '--no-newline', '--type', image_type], stdout=fh
                )
            if proc.returncode == 0:
                self.fm.notify("Saved: " + os.path.basename(outpath))
                self.fm.reload_cwd()
            else:
                try:
                    os.remove(outpath)
                except OSError:
                    pass
                self.fm.notify("wl-paste: failed to read clipboard image", bad=True)
        else:
            outpath = os.path.join(cwd, 'clipboard-{}.txt'.format(ts))
            with open(outpath, 'wb') as fh:
                proc = subprocess.run(['wl-paste', '--no-newline'], stdout=fh)
            if proc.returncode == 0 and os.path.getsize(outpath) > 0:
                self.fm.notify("Saved: " + os.path.basename(outpath))
                self.fm.reload_cwd()
            else:
                try:
                    os.remove(outpath)
                except OSError:
                    pass
                self.fm.notify("Clipboard is empty", bad=True)


# ═══ archives ══════════════════════════════════════════════════════════════

# id(proc) -> proc for all active extractions; used by extract_cancel
_active_extractions = {}

_ARCHIVE_EXTS = (
    '.tar.gz', '.tar.bz2', '.tar.xz', '.tar.zst',
    '.tgz', '.tbz2', '.txz', '.tar',
    '.zip', '.gz', '.bz2', '.xz', '.zst',
)

_BARE_EXTS = {'.gz': 'gzip', '.bz2': 'bzip2', '.xz': 'xz', '.zst': 'zstd'}

_COMPOUND_EXTS = ('.tar.gz', '.tar.bz2', '.tar.xz', '.tar.zst')

_KNOWN_ARCHIVE_SUFFIXES = (
    '.tar.gz', '.tar.bz2', '.tar.xz', '.tar.zst',
    '.zip', '.7z', '.gz', '.bz2', '.xz', '.zst',
)


def _split_archive_name(name):
    """Split an archive filename into (stem, suffix), recognizing compound
    suffixes like .tar.gz before falling back to a single extension."""
    lower = name.lower()
    for suf in _KNOWN_ARCHIVE_SUFFIXES:
        if lower.endswith(suf):
            return name[:-len(suf)], name[-len(suf):]
    return os.path.splitext(name)


def _unique_archive_dest(path):
    """Like unique_dest, but suffix-aware so compound extensions like
    .tar.gz aren't split mid-suffix (e.g. notes.tar.gz -> notes_1.tar.gz,
    not notes.tar_1.gz)."""
    if not os.path.exists(path):
        return path
    directory, base = os.path.split(path)
    stem, suffix = _split_archive_name(base)
    n = 1
    while True:
        candidate = os.path.join(directory, '{}_{}{}'.format(stem, n, suffix))
        if not os.path.exists(candidate):
            return candidate
        n += 1


def _archive_stem(basename):
    """Strip known archive extensions from basename and return the stem."""
    bl = basename.lower()
    for ext in _ARCHIVE_EXTS:
        if bl.endswith(ext) and len(basename) > len(ext):
            return basename[:-len(ext)]
    return basename + '_extracted'


def _is_bare_stream(name):
    """True for a single compressed file (x.gz, x.zst…), not a tarball."""
    lower = name.lower()
    if lower.endswith(_COMPOUND_EXTS):
        return False
    return os.path.splitext(lower)[1] in _BARE_EXTS


def _unique_dir(path):
    """path, or path_1, path_2… — suffixes the whole name (dirs have no ext)."""
    out, n = path, 1
    while os.path.lexists(out):
        out = '{}_{}'.format(path, n)
        n += 1
    return out


def _top_entries(listing):
    """Top-level names from a `bsdtar -tf` listing (handles ./ prefixes)."""
    tops = set()
    for line in listing.splitlines():
        entry = line.strip()
        while entry.startswith('./'):
            entry = entry[2:]
        top = entry.rstrip('/').split('/')[0]
        if top and top != '.':
            tops.add(top)
    return tops


def _count_existing(src, dst):
    """How many non-directory entries of archive `src` already exist in dst
    (bsdtar -k will skip — i.e. keep — those)."""
    try:
        r = subprocess.run(['bsdtar', '-tf', src], capture_output=True, text=True)
    except OSError:
        return 0
    n = 0
    for line in r.stdout.splitlines():
        if line.endswith('/'):
            continue
        rel = line[2:] if line.startswith('./') else line
        if rel and os.path.lexists(os.path.join(dst, rel)) and \
                not os.path.isdir(os.path.join(dst, rel)):
            n += 1
    return n


def _extract_bg(fm, src, dst, label, after=None, cleanup=None, count_kept=False):
    """Extract archive `src` into directory `dst` in the background.

    Never overwrites: tarballs/zips go through `bsdtar -k`; a bare .gz/.bz2/
    .xz/.zst stream is decompressed to a new, uniquely named file in dst.

    after(ui, out): optional, runs in the worker after a successful extract
                    (out = dst, or the decompressed file); ui(fn, *a) queues
                    fn(*a) on the UI thread.
    cleanup():      optional, always runs in the worker at the end.
    count_kept:     report how many existing files bsdtar left untouched.

    Progress and results are reported on the UI thread (ranger loader).
    """
    reader = 'pv -n -- "$1"' if shutil.which('pv') else 'cat -- "$1"'
    bare = _is_bare_stream(os.path.basename(src))
    if bare:
        tool = {'gzip': 'gzip', 'bzip2': 'bzip2', 'xz': 'xz', 'zstd': 'zstd -q'}[
            _BARE_EXTS[os.path.splitext(src.lower())[1]]]
        script = '{} | {} -dc > "$2"'.format(reader, tool)
    else:
        script = '{} | bsdtar -xkf - -C "$2"'.format(reader)

    def work(ui):
        out = dst
        try:
            kept = _count_existing(src, dst) if (count_kept and not bare) else 0
            if bare:
                stem = _archive_stem(os.path.basename(src))
                out = unique_dest(os.path.join(dst, stem))
                open(out, 'xb').close()          # claim the name
            proc = subprocess.Popen(
                ['sh', '-c', script, 'extract', src, out],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, start_new_session=True,
            )
            _active_extractions[id(proc)] = proc
            try:
                errors, last = [], -1
                start = time.monotonic()
                for raw in proc.stderr:
                    line = raw.decode('utf-8', 'replace').strip()
                    if not line.isdigit():
                        if line:
                            errors.append(line)
                        continue
                    pct = int(line)
                    if pct == last:
                        continue
                    last = pct
                    elapsed = time.monotonic() - start
                    if pct > 0:
                        msg = "Extracting {} — {}%  ETA {}s".format(
                            label, pct, int(elapsed * (100 - pct) / pct))
                    else:
                        msg = "Extracting {}…".format(label)
                    ui(fm.notify, msg)
                proc.wait()
            finally:
                _active_extractions.pop(id(proc), None)
                proc.stderr.close()
            rc = proc.returncode
            if rc != 0 and bare:
                try:
                    os.remove(out)
                except OSError:
                    pass
            if rc == 0 and after is not None:
                after(ui, out)
            return rc, errors, kept, out
        finally:
            if cleanup is not None:
                cleanup()

    def done(result, error):
        if error is not None:
            fm.notify("extract {}: {}".format(label, error), bad=True)
        else:
            rc, errors, kept, out = result
            if rc == 0:
                msg = "Extracted: {}".format(label)
                if bare:
                    msg += " → {}".format(os.path.basename(out))
                if kept:
                    msg += " ({} existing file(s) kept, not overwritten)".format(kept)
                fm.notify(msg)
            elif rc in (-signal.SIGTERM, -signal.SIGKILL, 128 + signal.SIGTERM):
                fm.notify("Extraction cancelled: {}".format(label))
            else:
                fm.notify("Extraction of {} failed (exit {}): {}".format(
                    label, rc, errors[-1] if errors else 'no output'), bad=True)
        fm.reload_cwd()
        try:
            fm.ui.need_redraw = True
        except AttributeError:
            pass

    run_bg(fm, 'Extracting ' + label, work, done)


def _new_dest_dir(path):
    """Create and return a fresh directory at path (or path_1, …)."""
    dest = _unique_dir(path)
    os.makedirs(dest)
    return dest


# ---------------------------------------------------------------------------
# Extract commands
# ---------------------------------------------------------------------------

class extract(Command):
    """:extract  (<Space>aed)

    Extract selected archive(s) into a new named subdirectory (stem/, or
    stem_1/ if that exists — never merged into an existing dir).  A bare
    .gz/.bz2/.xz/.zst file is decompressed next to itself instead.
    """

    def execute(self):
        cwd = self.fm.thisdir.path
        for f in self.fm.thistab.get_selection():
            if _is_bare_stream(f.basename):
                _extract_bg(self.fm, f.path, cwd, f.basename)
                continue
            try:
                dest = _new_dest_dir(os.path.join(cwd, _archive_stem(f.basename)))
            except OSError as ex:
                self.fm.notify("extract: {}".format(ex), bad=True)
                continue
            self.fm.notify("Extracting {} → {}/".format(f.basename, os.path.basename(dest)))
            _extract_bg(self.fm, f.path, dest, f.basename)


class extract_here(Command):
    """:extract_here  (<Space>aeh)

    Extract selected archive(s) flat into the current directory.
    Refuses to extract if any top-level archive entry already exists in cwd
    — use extract_smart or extract_flatten instead.  Existing files are
    never overwritten in any case (bsdtar -k).
    """

    def execute(self):
        cwd = self.fm.thisdir.path
        for f in self.fm.thistab.get_selection():
            if _is_bare_stream(f.basename):
                _extract_bg(self.fm, f.path, cwd, f.basename)
                continue
            result = subprocess.run(
                ['bsdtar', '-tf', f.path], capture_output=True, text=True)
            if result.returncode != 0:
                self.fm.notify(
                    "Cannot read {}: {}".format(f.basename, result.stderr.strip()),
                    bad=True)
                continue

            top_entries = _top_entries(result.stdout)
            collisions = [t for t in top_entries if os.path.lexists(os.path.join(cwd, t))]
            if collisions:
                self.fm.notify(
                    "extract_here: would overwrite {} — use extract_smart/extract_flatten instead".format(
                        ', '.join(sorted(collisions)[:3])),
                    bad=True)
                continue

            self.fm.notify("Extracting {}…".format(f.basename))
            _extract_bg(self.fm, f.path, cwd, f.basename)


class extract_smart(Command):
    """:extract_smart  (<Space>aes)

    Smart extract: inspect the archive first.  If all entries share a single
    top-level directory that doesn't exist yet, extract directly into cwd
    (avoids archive/archive/ double-nesting).  Otherwise extract into a new
    named subdir (stem/ or stem_1/ …).
    """

    def execute(self):
        cwd = self.fm.thisdir.path
        for f in self.fm.thistab.get_selection():
            if _is_bare_stream(f.basename):
                _extract_bg(self.fm, f.path, cwd, f.basename)
                continue
            result = subprocess.run(
                ['bsdtar', '-tf', f.path], capture_output=True, text=True)
            if result.returncode != 0:
                self.fm.notify(
                    "Cannot read {}: {}".format(f.basename, result.stderr.strip()),
                    bad=True)
                continue

            top_entries = _top_entries(result.stdout)
            if len(top_entries) == 1 and not os.path.lexists(
                    os.path.join(cwd, next(iter(top_entries)))):
                sole = next(iter(top_entries))
                self.fm.notify("Smart extract → {}/".format(sole))
                _extract_bg(self.fm, f.path, cwd, sole)
                continue
            try:
                dest = _new_dest_dir(os.path.join(cwd, _archive_stem(f.basename)))
            except OSError as ex:
                self.fm.notify("extract: {}".format(ex), bad=True)
                continue
            self.fm.notify("Smart extract (subdir): {}/".format(os.path.basename(dest)))
            _extract_bg(self.fm, f.path, dest, f.basename)


def _flatten_into(src_root, dest):
    """Move every file under src_root into dest (renaming on collision)."""
    for root, _, files in os.walk(src_root):
        for fname in files:
            shutil.move(os.path.join(root, fname),
                        unique_dest(os.path.join(dest, fname)))


class extract_flatten(Command):
    """:extract_flatten  (<Space>aef)

    Extract into a hidden temp dir (in cwd, so moves are cheap renames),
    then move every file (regardless of nesting) into a new flat subdir.
    The temp dir is always removed, even if extraction fails.
    """

    def execute(self):
        fm = self.fm
        cwd = fm.thisdir.path
        for f in fm.thistab.get_selection():
            if _is_bare_stream(f.basename):
                _extract_bg(fm, f.path, cwd, f.basename)
                continue
            try:
                tmpdir = tempfile.mkdtemp(prefix='.ranger-flat-', dir=cwd)
            except OSError as ex:
                fm.notify("extract_flatten: {}".format(ex), bad=True)
                continue
            dest_path = _unique_dir(os.path.join(cwd, _archive_stem(f.basename)))

            def _after(ui, _out, tmpdir=tmpdir, dest=dest_path):
                os.makedirs(dest, exist_ok=True)
                _flatten_into(tmpdir, dest)
                ui(fm.notify, "Flattened into {}/".format(os.path.basename(dest)))

            fm.notify("Extracting {}…".format(f.basename))
            _extract_bg(fm, f.path, tmpdir, f.basename, after=_after,
                        cleanup=lambda t=tmpdir: shutil.rmtree(t, ignore_errors=True))


class extract_to(Command):
    """:extract_to <destination>  (<Space>aeD)

    Extract selected archive(s) into a typed destination directory.
    Existing files there are kept, never overwritten (reported).
    Tab-completes paths.
    """

    def execute(self):
        dest = os.path.expanduser(self.rest(1))
        if not dest:
            self.fm.notify("Usage: extract_to <destination>", bad=True)
            return
        dest = os.path.join(self.fm.thisdir.path, dest)
        try:
            os.makedirs(dest, exist_ok=True)
        except OSError as ex:
            self.fm.notify("extract_to: {}".format(ex), bad=True)
            return
        for f in self.fm.thistab.get_selection():
            self.fm.notify("Extracting {}…".format(f.basename))
            _extract_bg(self.fm, f.path, dest, f.basename, count_kept=True)

    def tab(self, tabnum):
        return self._tab_directory_content()


class extract_open(Command):
    """:extract_open  (<Space>aeo)

    Extract selected archive into a new named subdir then cd into it
    (a bare .gz/.zst… is decompressed and the result selected).
    """

    def execute(self):
        fm = self.fm
        cwd = fm.thisdir.path
        for f in fm.thistab.get_selection():
            if _is_bare_stream(f.basename):
                _extract_bg(fm, f.path, cwd, f.basename,
                            after=lambda ui, out: ui(fm.select_file, out))
                continue
            try:
                dest = _new_dest_dir(os.path.join(cwd, _archive_stem(f.basename)))
            except OSError as ex:
                fm.notify("extract: {}".format(ex), bad=True)
                continue
            fm.notify("Extracting {}…".format(f.basename))
            _extract_bg(fm, f.path, dest, f.basename,
                        after=lambda ui, out: ui(fm.cd, out))


class extract_cancel(Command):
    """:extract_cancel  (<Space>ak)

    Cancel all active background extractions.
    """

    def execute(self):
        if not _active_extractions:
            self.fm.notify("No active extractions")
            return
        count = len(_active_extractions)
        for proc in list(_active_extractions.values()):
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except OSError:
                try:
                    proc.kill()
                except OSError:
                    pass
        self.fm.notify("Cancelled {} extraction(s)".format(count))


# ---------------------------------------------------------------------------
# Compress commands
# ---------------------------------------------------------------------------

class compress_format(Command):
    """:compress_format <fmt>  (<Space>ac*)

    Open the console pre-filled with :compress <stem>.<ext> for the given
    format shorthand.  fmt: gz | xz | zst | bz2 | zip | 7z
    """

    _FMT_EXT = {
        'gz':  '.tar.gz',
        'xz':  '.tar.xz',
        'zst': '.tar.zst',
        'bz2': '.tar.bz2',
        'zip': '.zip',
        '7z':  '.7z',
    }

    def execute(self):
        fmt = self.arg(1)
        ext = self._FMT_EXT.get(fmt)
        if not ext:
            self.fm.notify(
                "Unknown format: {}  (gz/xz/zst/bz2/zip/7z)".format(fmt), bad=True)
            return
        selection = self.fm.thistab.get_selection()
        if not selection:
            return
        if len(selection) == 1:
            stem = os.path.splitext(selection[0].basename)[0]
        else:
            stem = os.path.basename(self.fm.thisdir.path)
        self.fm.open_console('compress ' + stem + ext)


class archive_list(Command):
    """:archive_list  (<Space>al)

    Browse archive contents in fzf (searchable, read-only).
    """

    def execute(self):
        f = self.fm.thisfile
        if f is None:
            self.fm.notify("No file selected", bad=True)
            return

        result = subprocess.run(
            ['bsdtar', '-tvf', f.path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            self.fm.notify(
                "Cannot list {}: {}".format(f.basename, result.stderr.strip()), bad=True)
            return

        with tempfile.NamedTemporaryFile(mode='w', suffix='.in', delete=False) as tf:
            tf.write(result.stdout)
            in_file = tf.name
        fd, out_file = tempfile.mkstemp(suffix='.out')
        os.close(fd)
        try:
            self.fm.run(
                'fzf --border --no-multi --ansi --header={} < {} > {}'.format(
                    shlex.quote(f.basename),
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


class archive_test(Command):
    """:archive_test  (<Space>at)

    Test archive integrity by doing a dry-run read through pv.
    Shows live progress; prints PASSED or FAILED when done.
    """

    def execute(self):
        f = self.fm.thisfile
        if f is None:
            self.fm.notify("No file selected", bad=True)
            return
        # File names go in as positional args ($1/$2), never into the script.
        script = ('if {reader} | bsdtar -tf - >/dev/null; '
                  'then echo "PASSED: $2"; else echo "FAILED: $2"; fi').format(
                      reader='pv -- "$1"' if shutil.which('pv') else 'cat -- "$1"')
        self.fm.run(['sh', '-c', script, 'archive_test', f.path, f.basename], flags='w')


class compress(Command):
    """:compress <archive_name>

    Compress the selected files into an archive.
    Format is determined by extension. Supported:
      .tar.gz  .tar.bz2  .tar.xz  .tar.zst  .zip  .7z
    A single non-directory file with a bare .gz/.bz2/.xz/.zst extension is
    compressed as a plain stream (gzip/bzip2/xz/zstd), not tar-wrapped.
    Refuses to overwrite an existing archive — appends _1, _2, … instead.
    """

    def execute(self):
        archive_name = self.rest(1)
        if not archive_name:
            self.fm.notify("Usage: compress <archive.tar.gz|zip|7z|...>", bad=True)
            return
        selection = self.fm.thistab.get_selection()
        if not selection:
            return

        archive_path = _unique_archive_dest(os.path.join(self.fm.thisdir.path, archive_name))
        archive_name = os.path.basename(archive_path)
        files = [f.path for f in selection]
        name = archive_name.lower()
        _, bare_ext = os.path.splitext(name)

        if (bare_ext in _BARE_EXTS and len(selection) == 1
                and not selection[0].is_directory
                and not name.endswith(_COMPOUND_EXTS)):
            tool = _BARE_EXTS[bare_ext]
            cmd = '{} -c -- {} > {}'.format(
                tool, shlex.quote(files[0]), shlex.quote(archive_path))
            self.fm.notify("Compressing 1 file → {}".format(archive_name))
            self.fm.run(cmd)
            self.fm.reload_cwd()
            return

        if name.endswith('.zip'):
            cmd = ['zip', '-r', archive_path] + files
        elif name.endswith('.7z'):
            cmd = ['7z', 'a', archive_path] + files
        elif name.endswith('.tar.zst'):
            cmd = ['bsdtar', '--zstd', '-caf', archive_path] + files
        elif name.endswith('.tar.bz2') or name.endswith('.tbz2'):
            cmd = ['bsdtar', '-cjf', archive_path] + files
        elif name.endswith('.tar.xz') or name.endswith('.txz'):
            cmd = ['bsdtar', '-cJf', archive_path] + files
        else:
            cmd = ['bsdtar', '-czf', archive_path] + files
        self.fm.notify("Compressing {} file(s) → {}".format(len(files), archive_name))
        self.fm.run(' '.join(shlex.quote(c) for c in cmd))
        self.fm.reload_cwd()


# ═══ preview ═══════════════════════════════════════════════════════════════

class preview_toggle(Command):
    """:preview_toggle  (<Space>pp)

    Toggle visual preview mode (images, video, PDF) on or off.
    """

    def execute(self):
        mode = not getattr(self.fm, 'preview_mode', False)
        self.fm.preview_mode = mode
        self.fm._preview_peek = False
        self.fm.settings.preview_images = mode
        self.fm.ui.need_redraw = True
        # Notification comes from cmd_feedback.py via setopt.preview_images signal.


class preview_peek(Command):
    """:preview_peek  (<Space>ps)

    Preview the file under the cursor. Auto-disables on the next navigation.
    """

    def execute(self):
        self.fm._preview_peek = True
        self.fm.preview_mode = True
        self.fm.settings.preview_images = True
        self.fm.ui.need_redraw = True


class preview_clear(Command):
    """:preview_clear  (<Space>pc)

    Flush the in-memory preview cache and delete thumbnail files from
    ~/.cache/ranger, then clear the kitty image from the terminal.
    """

    def execute(self):
        cache_dir = os.path.expanduser('~/.cache/ranger')
        self.fm.previews.clear()
        count = 0
        for f in glob.glob(os.path.join(cache_dir, '*.jpg')):
            try:
                os.remove(f)
                count += 1
            except OSError:
                pass
        try:
            preview_col = self.fm.ui.browser.columns[-1]
            preview_col.clear_image(force=True)
            preview_col.need_redraw = True
        except (AttributeError, IndexError):
            pass
        self.fm.ui.need_redraw = True
        self.fm.notify("Cleared {} cached preview(s)".format(count))


class preview_render_all(Command):
    """:preview_render_all  (<Space>pa)

    Pre-generate thumbnails for all video files in the current directory
    using ffmpegthumbnailer. Runs in a background thread; activates preview
    mode immediately so you can browse while generation is in progress.

    Thumbnails are stored in ~/.cache/ranger/<sha1>.jpg — the same path
    scope.sh writes to — so on the next hover scope.sh detects the fresh
    file and exits immediately without re-running ffmpegthumbnailer.
    """

    _VIDEO_EXTS = frozenset(
        '.mp4 .mkv .avi .mov .wmv .flv .webm .m4v .ts .mts .m2ts '
        '.3gp .ogv .asf .rm .rmvb .divx .mpg .mpeg .vob .f4v'.split()
    )

    def execute(self):
        VIDEO_EXTS = self._VIDEO_EXTS
        cache_dir = os.path.expanduser('~/.cache/ranger')
        os.makedirs(cache_dir, exist_ok=True)

        file_infos = [
            (f.path, f.mimetype)
            for f in self.fm.thisdir.files
            if not f.is_directory
        ]
        fm = self.fm

        def _cache_path(path):
            realpath = os.path.realpath(path)
            return os.path.join(
                cache_dir,
                sha1(realpath.encode('utf-8', 'backslashreplace')).hexdigest() + '.jpg'
            )

        def _is_video(path, mime):
            m = mime or mimetypes.guess_type(path)[0] or ''
            ext = os.path.splitext(path)[1].lower()
            return m.startswith('video/') or ext in VIDEO_EXTS

        def _generate(_ui):
            # Worker thread: file work only — fm/ui are touched in _done.
            done = skipped = errors = 0
            for path, mime in file_infos:
                if not _is_video(path, mime):
                    continue
                cache = _cache_path(path)
                try:
                    if (os.path.isfile(cache) and
                            os.path.getmtime(cache) >= os.path.getmtime(path)):
                        skipped += 1
                        continue
                except OSError:
                    pass
                r = subprocess.run(
                    ['ffmpegthumbnailer', '-i', path, '-o', cache,
                     '-s', '0', '-t', '20%'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                if r.returncode == 0:
                    done += 1
                else:
                    errors += 1
            return done, skipped, errors

        def _done(result, error):
            if isinstance(error, FileNotFoundError):
                fm.notify("ffmpegthumbnailer not installed", bad=True)
                return
            if error is not None:
                fm.notify("Thumbnails: {}".format(error), bad=True)
                return
            done, skipped, errors = result
            fm.previews.clear()
            fm.ui.need_redraw = True
            parts = []
            if done:
                parts.append("{} rendered".format(done))
            if skipped:
                parts.append("{} already cached".format(skipped))
            if errors:
                parts.append("{} failed".format(errors))
            fm.notify("Thumbnails: " + (", ".join(parts) if parts else "no video files found"))

        video_count = sum(1 for p, m in file_infos if _is_video(p, m))
        if video_count == 0:
            self.fm.notify("No video files in current directory")
            return

        self.fm.preview_mode = True
        self.fm.settings.preview_images = True
        self.fm.ui.need_redraw = True
        self.fm.notify("Rendering {} video thumbnail(s)…".format(video_count))

        run_bg(fm, 'Rendering thumbnails', _generate, _done)


# ═══ security ══════════════════════════════════════════════════════════════

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


# ═══ transform ═════════════════════════════════════════════════════════════

def _invalidate_preview(fm):
    """Clear cached previews so an in-place edit's new content shows immediately."""
    fm.previews.clear()
    fm.ui.need_redraw = True


def _run_ffmpeg_batch(fm, sel, build_cmd, label):
    """Run one ffmpeg invocation per selected file, sequentially, via fm.run().

    build_cmd(f) -> shell command string for file f.
    label: verb used in the pre-flight notify, e.g. 'Transcoding'.
    """
    if not require_tool(fm, 'ffmpeg'):
        return
    parts = [build_cmd(f) for f in sel]
    fm.notify('{} {} file(s)…'.format(label, len(parts)))
    fm.run(' && '.join(parts))
    fm.reload_cwd()


# ── Image ops  (<Space>vi*) ───────────────────────────────────────────────────

# Formats that ImageMagick re-encodes lossily when it rewrites a file.
_LOSSY_EXTS = frozenset({'jpg', 'jpeg', 'jfif', 'webp', 'avif', 'heic', 'heif'})


def _is_lossy(path):
    return os.path.splitext(path)[1].lstrip('.').lower() in _LOSSY_EXTS


def _confirm_then(fm, files, prompt, action, lossy=True):
    """Run action() right away for one lossless file; otherwise ask y/N first.

    lossy: whether the operation re-encodes (mogrify does; jpegoptim/oxipng
    and renames don't)."""
    lossy_files = [f for f in files if lossy and _is_lossy(f)]
    if len(files) <= 1 and not lossy_files:
        action()
        return
    text = prompt.format(n=len(files))
    if lossy_files:
        text += ' — re-encodes {} JPEG/WebP file(s) lossily'.format(len(lossy_files))
    ask_yes(fm, text, action)


def _run_jobs(fm, descr, jobs, ok_msg, inplace=False):
    """Run each argv in `jobs` in the background, one after another.

    stdout/stderr are captured (nothing draws over curses); failures are
    collected and reported once on the UI thread, then the listing reloads.
    """
    def work(_ui):
        failed = []
        for argv in jobs:
            try:
                r = subprocess.run(argv, stdin=subprocess.DEVNULL,
                                   capture_output=True, text=True, errors='replace')
            except OSError as ex:
                failed.append(str(ex))
                continue
            if r.returncode != 0:
                err = (r.stderr or r.stdout).strip().splitlines()
                failed.append(err[-1] if err else '{} exited {}'.format(argv[0], r.returncode))
        return failed

    def done(failed, error):
        if error is not None:
            failed = [str(error)]
        if failed:
            fm.notify('{}: {} of {} failed — {}'.format(
                descr, len(failed), len(jobs), failed[0]), bad=True)
        else:
            fm.notify(ok_msg)
        if inplace:
            _invalidate_preview(fm)
        fm.reload_cwd()

    fm.notify('{}…'.format(descr))
    run_bg(fm, descr, work, done)


def _mogrify_inplace(cmd, args, verb):
    """Shared body for the in-place mogrify commands."""
    sel = get_selection(cmd.fm)
    if sel is None:
        return
    if not require_tool(cmd.fm, 'magick'):
        return
    files = [f.path for f in sel]
    jobs = [['magick', 'mogrify'] + args + ['--', p] for p in files]
    _confirm_then(
        cmd.fm, files, '{} {{n}} file(s) in place?'.format(verb),
        lambda: _run_jobs(cmd.fm, verb, jobs,
                          '{}: {} file(s)'.format(verb, len(files)), inplace=True))


class image_resize(Command):
    """:image_resize <spec>  (<Space>vir)

    Resize all selected images in-place via mogrify (asks first when more
    than one file or a lossy format is involved).
    <spec> is any ImageMagick geometry string, e.g.:
        50%        half size
        800x600    fit within box (keep aspect)
        1920x1080^ fill box (crop to fit)
        800x600!   force exact size (distort)
    Requires: mogrify (ImageMagick).
    """

    def execute(self):
        spec = self.rest(1).strip()
        if not spec:
            self.fm.notify("Usage: image_resize <spec>  e.g. 50%  800x600", bad=True)
            return
        _mogrify_inplace(self, ['-resize', spec], 'Resize to ' + spec)


class image_convert(Command):
    """:image_convert <ext>  (<Space>vic)

    Convert selected images to a different format.
    <ext> is the target format extension, e.g.: png  webp  jpg  avif  tiff
    Output files are written alongside originals with the new extension;
    an existing file of that name is never overwritten (name_1.ext …).
    Requires: magick (ImageMagick).
    """

    def execute(self):
        ext = self.rest(1).strip().lstrip('.')
        if not ext:
            self.fm.notify("Usage: image_convert <ext>  e.g. png  webp  jpg", bad=True)
            return

        sel = get_selection(self.fm)
        if sel is None:
            return
        if not require_tool(self.fm, 'magick'):
            return

        jobs = []
        taken = set()
        for f in sel:
            out = unique_dest(os.path.splitext(f.path)[0] + '.' + ext, taken=taken)
            jobs.append(['magick', f.path, out])
        _run_jobs(self.fm, 'Convert to .' + ext, jobs,
                  "Converted {} file(s) → .{}".format(len(jobs), ext))


class image_strip(Command):
    """:image_strip  (<Space>vis)

    Strip all EXIF/XMP/IPTC metadata from selected images in-place.
    Requires: mogrify (ImageMagick).
    """

    def execute(self):
        _mogrify_inplace(self, ['-strip'], 'Strip metadata from')


class image_optimize(Command):
    """:image_optimize  (<Space>vio)

    Losslessly optimize selected images in-place (asks first for 2+ files).
    PNGs  → oxipng -o2 --strip safe
    JPEGs → jpegoptim --strip-all
    Requires: oxipng (PNG) and/or jpegoptim (JPEG).
    """

    def execute(self):
        sel = get_selection(self.fm)
        if sel is None:
            return

        pngs  = [f.path for f in sel if f.extension and f.extension.lower() == 'png']
        jpegs = [f.path for f in sel if f.extension and f.extension.lower() in ('jpg', 'jpeg')]

        jobs = []
        if pngs and shutil.which('oxipng'):
            jobs.append(['oxipng', '-o2', '--strip', 'safe', '--'] + pngs)
        else:
            pngs = []
        if jpegs and shutil.which('jpegoptim'):
            jobs.append(['jpegoptim', '--strip-all', '--'] + jpegs)
        else:
            jpegs = []

        if not jobs:
            self.fm.notify("No supported files or tools (need oxipng / jpegoptim)", bad=True)
            return
        _confirm_then(
            self.fm, pngs + jpegs, 'Optimize {n} file(s) in place?',
            lambda: _run_jobs(self.fm, 'Optimize', jobs, "Optimized {} PNG(s), {} JPEG(s)".format(
                len(pngs), len(jpegs)), inplace=True),
            lossy=False)


# ── Video / audio ops  (<Space>vv*) ──────────────────────────────────────────

class video_transcode(Command):
    """:video_transcode <ext>  (<Space>vvt)

    Re-encode selected videos to a different container via ffmpeg.
    <ext>: mp4  webm  mkv  mov  avi
    Output: <name>.<ext> alongside source. Interactive ffmpeg progress shown.
    Requires: ffmpeg.
    """

    def execute(self):
        ext = self.rest(1).strip().lstrip('.')
        if not ext:
            self.fm.notify("Usage: video_transcode <ext>  e.g. mp4  webm", bad=True)
            return
        sel = get_selection(self.fm)
        if sel is None:
            return

        taken = set()

        def _cmd(f):
            stem = os.path.splitext(f.basename)[0]
            out = unique_dest(os.path.join(f.dirname, stem + '.' + ext), taken=taken)
            return 'ffmpeg -i {} {}'.format(shlex.quote(f.path), shlex.quote(out))

        _run_ffmpeg_batch(self.fm, sel, _cmd, 'Transcoding')


class video_extract_audio(Command):
    """:video_extract_audio <ext>  (<Space>vva)

    Extract the audio track from selected videos via ffmpeg.
    <ext>: mp3  aac  flac  wav  opus  ogg
    Output: <name>.<ext> alongside source.
    Requires: ffmpeg.
    """

    def execute(self):
        ext = self.rest(1).strip().lstrip('.')
        if not ext:
            self.fm.notify("Usage: video_extract_audio <ext>  e.g. mp3  flac", bad=True)
            return
        sel = get_selection(self.fm)
        if sel is None:
            return

        taken = set()

        def _cmd(f):
            stem = os.path.splitext(f.basename)[0]
            out = unique_dest(os.path.join(f.dirname, stem + '.' + ext), taken=taken)
            return 'ffmpeg -i {} -vn {}'.format(shlex.quote(f.path), shlex.quote(out))

        _run_ffmpeg_batch(self.fm, sel, _cmd, 'Extracting audio from')


class video_trim(Command):
    """:video_trim <start> <duration>  (<Space>vvx)

    Trim selected video to [start, start+duration] via stream copy (fast, lossless).
    Times: HH:MM:SS, MM:SS, or bare seconds.
    Example: video_trim 0:30 1:00  →  extract 30s–1m30s
    Output: <name>_trim.<ext> alongside source.
    Requires: ffmpeg.
    """

    def execute(self):
        args = self.args[1:]
        if len(args) < 2:
            self.fm.notify("Usage: video_trim <start> <duration>  e.g. 0:30 1:00", bad=True)
            return
        start, duration = args[0], args[1]
        sel = get_selection(self.fm)
        if sel is None:
            return

        taken = set()

        def _cmd(f):
            stem, sfx = os.path.splitext(f.basename)
            out = unique_dest(os.path.join(f.dirname, stem + '_trim' + sfx), taken=taken)
            return 'ffmpeg -ss {} -i {} -t {} -c copy {}'.format(
                shlex.quote(start), shlex.quote(f.path),
                shlex.quote(duration), shlex.quote(out))

        _run_ffmpeg_batch(self.fm, sel, _cmd, 'Trimming')


class video_to_gif(Command):
    """:video_to_gif [fps [width]]  (<Space>vvg)

    Convert selected video to an animated GIF via ffmpeg.
    Defaults: 10 fps, 480px wide (height auto-scaled).
    Output: <name>.gif alongside source.
    Requires: ffmpeg.
    """

    def execute(self):
        args = self.args[1:]
        fps   = args[0] if len(args) > 0 else '10'
        width = args[1] if len(args) > 1 else '480'
        sel = get_selection(self.fm)
        if sel is None:
            return

        taken = set()

        def _cmd(f):
            stem = os.path.splitext(f.basename)[0]
            out = unique_dest(os.path.join(f.dirname, stem + '.gif'), taken=taken)
            vf = 'fps={},scale={}:-1:flags=lanczos'.format(fps, width)
            return 'ffmpeg -i {} -vf {} {}'.format(
                shlex.quote(f.path), shlex.quote(vf), shlex.quote(out))

        _run_ffmpeg_batch(self.fm, sel, _cmd, 'Converting to GIF')


class video_snapshot(Command):
    """:video_snapshot [timestamp]  (<Space>vvs)

    Grab a single frame from selected videos as a JPEG.
    Default timestamp: 00:00:05 (5 seconds in).
    Output: <name>_thumb.jpg alongside source.
    Requires: ffmpeg.
    """

    def execute(self):
        ts = self.rest(1).strip() or '00:00:05'
        sel = get_selection(self.fm)
        if sel is None:
            return

        taken = set()

        def _cmd(f):
            stem = os.path.splitext(f.basename)[0]
            out = unique_dest(os.path.join(f.dirname, stem + '_thumb.jpg'), taken=taken)
            return 'ffmpeg -ss {} -i {} -frames:v 1 {}'.format(
                shlex.quote(ts), shlex.quote(f.path), shlex.quote(out))

        _run_ffmpeg_batch(self.fm, sel, _cmd, 'Grabbing snapshot from')


# ── PDF ops  (<Space>vp*) ─────────────────────────────────────────────────────

class pdf_merge(Command):
    """:pdf_merge <output>  (<Space>vpm)

    Merge all selected PDFs into one file.
    Uses pdfunite (poppler) if available, falls back to gs (ghostscript).
    Output is written in cwd.
    Requires: pdfunite or gs.
    """

    def execute(self):
        out = self.rest(1).strip()
        if not out:
            self.fm.notify("Usage: pdf_merge <output.pdf>", bad=True)
            return
        if not out.lower().endswith('.pdf'):
            out += '.pdf'

        sel = get_selection(self.fm, min_count=2, msg="Select 2+ PDF files to merge")
        if sel is None:
            return

        # Never write over an existing file — in particular one of the inputs.
        out_path = unique_dest(os.path.join(self.fm.thisdir.path, out))
        files = [f.path for f in sel]

        if shutil.which('pdfunite'):
            cmd = ['pdfunite'] + files + [out_path]
        elif shutil.which('gs'):
            cmd = ['gs', '-dBATCH', '-dNOPAUSE', '-dSAFER', '-q',
                   '-sDEVICE=pdfwrite', '-sOutputFile=' + out_path] + files  # paths are absolute
        else:
            self.fm.notify("Install pdfunite (poppler) or gs (ghostscript)", bad=True)
            return
        _run_jobs(self.fm, 'Merge PDFs', [cmd], "Merged {} PDFs → {}".format(
            len(sel), os.path.basename(out_path)))


class pdf_split(Command):
    """:pdf_split <start>-<end>  (<Space>vps)

    Extract a page range from the selected PDF.
    Range is 1-based, e.g.: 1-5  3-3  2-10
    Output: <name>_p1-5.pdf alongside source.
    Requires: qpdf.
    """

    def execute(self):
        rng = self.rest(1).strip()
        if not rng or '-' not in rng:
            self.fm.notify("Usage: pdf_split <start>-<end>  e.g. 1-5", bad=True)
            return

        if not require_tool(self.fm, 'qpdf', "Install qpdf for PDF splitting"):
            return

        sel = get_selection(self.fm)
        if sel is None:
            return

        jobs = []
        for f in sel:
            stem = os.path.splitext(f.basename)[0]
            out = unique_dest(os.path.join(f.dirname, '{}_p{}.pdf'.format(stem, rng)))
            jobs.append(['qpdf', '--empty', '--pages', f.path, rng, '--', out])
        _run_jobs(self.fm, 'Split PDF', jobs,
                  "Split pages {} from {} file(s)".format(rng, len(sel)))


class pdf_rotate(Command):
    """:pdf_rotate <degrees> [range]  (<Space>vpr)

    Rotate pages in selected PDFs. degrees: 90 | 180 | 270
    range (optional, qpdf syntax): e.g. 1-3, 5, 1-3,7  — defaults to all pages.
    Overwrites originals in-place.
    Requires: qpdf.
    """

    def execute(self):
        deg = self.arg(1)
        if deg not in ('90', '180', '270'):
            self.fm.notify("Usage: pdf_rotate <90|180|270> [range]", bad=True)
            return
        page_range = self.arg(2) or '1-z'

        if not require_tool(self.fm, 'qpdf', "Install qpdf for PDF rotation"):
            return

        sel = get_selection(self.fm)
        if sel is None:
            return

        for f in sel:
            tmp = f.path + '._qpdf_tmp'
            r = subprocess.run([
                'qpdf', '--rotate=+{}:{}'.format(deg, page_range), f.path, tmp
            ], capture_output=True, text=True, errors='replace')
            if r.returncode == 0:
                os.replace(tmp, f.path)
            else:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                self.fm.notify("qpdf failed on {}".format(f.basename), bad=True)
                return

        self.fm.notify("Rotated {}° (pages {}) — {} file(s)".format(deg, page_range, len(sel)))
        self.fm.reload_cwd()


class pdf_compress(Command):
    """:pdf_compress [quality]  (<Space>vpc)

    Compress selected PDFs via Ghostscript.
    quality: screen  ebook  printer  prepress  (default: ebook)
    Output: <name>_compressed.pdf alongside source.
    Requires: gs (ghostscript).
    """

    def execute(self):
        quality = self.rest(1).strip() or 'ebook'
        valid = ('screen', 'ebook', 'printer', 'prepress')
        if quality not in valid:
            self.fm.notify("Usage: pdf_compress [{}]".format('|'.join(valid)), bad=True)
            return

        if not require_tool(self.fm, 'gs', "Install ghostscript (gs) for PDF compression"):
            return

        sel = get_selection(self.fm)
        if sel is None:
            return

        jobs = []
        for f in sel:
            stem = os.path.splitext(f.basename)[0]
            out = unique_dest(os.path.join(f.dirname, stem + '_compressed.pdf'))
            jobs.append(['gs', '-dBATCH', '-dNOPAUSE', '-dSAFER', '-q',
                         '-sDEVICE=pdfwrite', '-dPDFSETTINGS=/' + quality,
                         '-sOutputFile=' + out, f.path])
        _run_jobs(self.fm, 'Compress PDF', jobs,
                  "Compressed {} PDF(s) [{}]".format(len(sel), quality))


class pdf_ocr(Command):
    """:pdf_ocr [lang]  (<Space>vpo)

    Add a text layer to selected PDFs via ocrmypdf (Tesseract).
    lang: Tesseract language code, e.g. eng  deu  fra  (default: eng)
    Overwrites originals in-place. Skips pages already containing text.
    Requires: ocrmypdf.
    """

    def execute(self):
        lang = self.rest(1).strip() or 'eng'

        if not require_tool(self.fm, 'ocrmypdf', "Install ocrmypdf for PDF OCR"):
            return

        sel = get_selection(self.fm)
        if sel is None:
            return

        for f in sel:
            self.fm.run('ocrmypdf --skip-text -l {} {} {}'.format(
                shlex.quote(lang), shlex.quote(f.path), shlex.quote(f.path)))

        self.fm.reload_cwd()


# ── Name / organize  (<Space>vn*) ─────────────────────────────────────────────

class name_by_exif(Command):
    """:name_by_exif [format]  (<Space>vne)

    Rename selected images/videos using the EXIF DateTimeOriginal field.
    Default format: %Y%m%d_%H%M%S  →  20240315_143022.jpg
    Appends a counter if a filename collision occurs.
    Requires: exiftool.
    """

    def execute(self):
        fmt = self.rest(1).strip() or '%Y%m%d_%H%M%S'

        if not require_tool(self.fm, 'exiftool', "Install exiftool for EXIF rename"):
            return

        sel = get_selection(self.fm)
        if sel is None:
            return

        files = [f.path for f in sel]
        # exiftool never overwrites: %-c appends -1, -2 … on collision.
        job = ['exiftool', '-d', fmt + '%%-c.%%e', '-FileName<DateTimeOriginal', '--'] + files
        _confirm_then(
            self.fm, files, 'Rename {n} file(s) by EXIF date?',
            lambda: _run_jobs(self.fm, 'Rename by EXIF', [job],
                              "Renamed {} file(s) by EXIF date".format(len(files))),
            lossy=False)


class name_by_mtime(Command):
    """:name_by_mtime [format]  (<Space>vnm)

    Rename selected files using their modification timestamp.
    Default format: %Y%m%d_%H%M%S  →  20240315_143022.jpg
    Appends _1, _2 … on collision. No external tools required.
    """

    def execute(self):
        fmt = self.rest(1).strip() or '%Y%m%d_%H%M%S'

        sel = get_selection(self.fm)
        if sel is None:
            return

        def _do():
            renamed, failed = 0, []
            for f in sel:
                try:
                    ts = time.strftime(fmt, time.localtime(os.path.getmtime(f.path)))
                    ext = os.path.splitext(f.basename)[1]
                    new_path = os.path.join(f.dirname, ts + ext)
                    counter = 1
                    while os.path.lexists(new_path) and new_path != f.path:
                        new_path = os.path.join(f.dirname, '{}_{}{}'.format(ts, counter, ext))
                        counter += 1
                    if new_path != f.path:
                        os.rename(f.path, new_path)
                        renamed += 1
                except (OSError, ValueError) as ex:
                    failed.append('{}: {}'.format(f.basename, ex))
            self.fm.notify("Renamed {} file(s) by mtime".format(renamed))
            if failed:
                self.fm.notify("Failed: " + ';  '.join(failed[:3]), bad=True)
            self.fm.reload_cwd()

        _confirm_then(self.fm, [f.path for f in sel],
                      'Rename {n} file(s) by mtime?', _do, lossy=False)


class name_sort_date(Command):
    """:name_sort_date [confirm]  (<Space>vns)

    Move selected files into YYYY/MM subdirectories based on mtime.
    Shows where they'll go and asks y/N; 'confirm' skips the question.
    Never overwrites: collisions get a _N suffix.
    """

    def execute(self):
        confirm = 'confirm' in self.args[1:]

        sel = get_selection(self.fm)
        if sel is None:
            return

        cwd = self.fm.thisdir.path
        moves = []
        for f in sel:
            try:
                lt = time.localtime(os.path.getmtime(f.path))
            except OSError:
                continue
            subdir = os.path.join(cwd, time.strftime('%Y', lt), time.strftime('%m', lt))
            moves.append((f.path, subdir, os.path.join(subdir, f.basename)))
        if not moves:
            self.fm.notify("Nothing to sort", bad=True)
            return

        def _do():
            ok = fail = 0
            for src, subdir, dest in moves:
                try:
                    os.makedirs(subdir, exist_ok=True)
                    if dest != src:
                        dest = unique_dest(dest)
                    shutil.move(src, dest)
                    ok += 1
                except (OSError, shutil.Error):
                    fail += 1
            msg = "Sorted {} file(s) into YYYY/MM".format(ok)
            if fail:
                msg += ", {} failed".format(fail)
            self.fm.notify(msg, bad=bool(fail))
            self.fm.reload_cwd()

        if confirm:
            _do()
            return
        dirs = sorted(set(m[1] for m in moves))
        preview = ', '.join(os.path.relpath(d, cwd) for d in dirs[:3])
        if len(dirs) > 3:
            preview += '…'
        ask_yes(self.fm, "Sort {} file(s) into {}?".format(len(moves), preview), _do)


# ═══ network ═══════════════════════════════════════════════════════════════

_RUNTIME_DIR = os.environ.get('XDG_RUNTIME_DIR', tempfile.gettempdir())
# Line 1: server PID.  Line 2 (optional): temp dir to delete on lan_kill.
_LAN_PID_FILE = os.path.join(_RUNTIME_DIR, 'ranger_lan_server.pid')
_LAN_LOG_FILE = os.path.join(_RUNTIME_DIR, 'ranger_lan_server.log')


def _parse_port(fm, text, default=8080):
    """Return the port in `text` (default 8080), or notify and return None."""
    text = (text or '').strip()
    if not text:
        return default
    try:
        port = int(text)
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        fm.notify("Invalid port: {!r} (1-65535)".format(text), bad=True)
        return None
    return port


_VIRTUAL_IFACES = ('lo', 'docker', 'br-', 'veth', 'virbr', 'tailscale', 'wg', 'tun',
                   'tap', 'zt', 'vnet', 'podman', 'cni', 'flannel')


def _is_private(ip):
    try:
        import ipaddress
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_private and not addr.is_loopback and not addr.is_link_local and \
        addr not in ipaddress.ip_network('100.64.0.0/10')     # CGNAT / tailscale


def _iface_addrs():
    """[(iface, ip)] for global IPv4 addresses on non-virtual interfaces."""
    import json
    try:
        out = subprocess.run(['ip', '-j', '-4', 'addr', 'show', 'scope', 'global'],
                             capture_output=True, text=True, timeout=2).stdout
        data = json.loads(out or '[]')
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    return [(i.get('ifname', ''), a['local'])
            for i in data for a in i.get('addr_info', ())
            if a.get('local') and not i.get('ifname', '').startswith(_VIRTUAL_IFACES)]


def _lan_ip():
    """The LAN address to bind (never 0.0.0.0): the default route's address
    when it's a private LAN address, else the first private address on a
    physical interface (a full-tunnel VPN owns the default route; an
    isolated LAN or hotspot may have none).  No packet is sent: connecting
    a UDP socket only picks the route.  None when there's no LAN address."""
    route_ip = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('192.0.2.1', 9))          # TEST-NET-1, never routed
            route_ip = s.getsockname()[0]
    except OSError:
        pass
    addrs = _iface_addrs()
    if route_ip and _is_private(route_ip) and \
            (not addrs or route_ip in (ip for _, ip in addrs)):
        return route_ip
    for _, ip in addrs:
        if _is_private(ip):
            return ip
    return None


def _lan_find_tool():
    """Return (tool, base_args) for the best available HTTP server, or None."""
    if shutil.which('miniserve'):
        return ('miniserve', ['miniserve', '--no-symlinks'])
    if shutil.which('python3'):
        return ('python3', ['python3', '-m', 'http.server'])
    if shutil.which('python'):
        return ('python', ['python', '-m', 'http.server'])
    return None


def _lan_server_cmd(tool, ip, port, path):
    """argv serving `path` (a dir, or a single file for miniserve) on ip:port."""
    name, base = tool
    if name == 'miniserve':
        return base + ['--interfaces', ip, '--port', str(port), '--', path]
    return base + ['--bind', ip, '--directory', path, str(port)]


def _lan_read_state():
    """Return (pid, tmpdir) from the pid file; (None, None) if missing/corrupt."""
    try:
        with open(_LAN_PID_FILE) as fh:
            lines = fh.read().splitlines()
        return int(lines[0].strip()), (lines[1].strip() if len(lines) > 1 else None)
    except (OSError, ValueError, IndexError):
        return None, None


def _lan_read_pid():
    return _lan_read_state()[0]


def _lan_pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _lan_cleanup(tmpdir):
    try:
        os.remove(_LAN_PID_FILE)
    except OSError:
        pass
    if tmpdir and os.path.basename(tmpdir).startswith('ranger-lan-'):
        shutil.rmtree(tmpdir, ignore_errors=True)


def _lan_start(fm, cmd, tmpdir=None):
    """Start the server, wait briefly, and confirm it is still running.
    Returns the Popen, or None (after notifying) if it died — e.g. port in use."""
    with open(_LAN_LOG_FILE, 'wb') as log:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            start_new_session=True,
        )
    time.sleep(0.3)
    if proc.poll() is not None:
        try:
            with open(_LAN_LOG_FILE, errors='replace') as fh:
                err = fh.read().strip().splitlines()
        except OSError:
            err = []
        fm.notify("Server failed to start: {}".format(
            err[-1] if err else 'exit {}'.format(proc.returncode)), bad=True)
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        return None
    with open(_LAN_PID_FILE, 'w') as fh:
        fh.write('{}\n{}\n'.format(proc.pid, tmpdir or ''))
    return proc


def _lan_preflight(fm, cmd_self):
    """Common checks; returns (tool, ip, port) or None."""
    port = _parse_port(fm, cmd_self.rest(1))
    if port is None:
        return None
    pid = _lan_read_pid()
    if pid and _lan_pid_alive(pid):
        fm.notify("Server already running (PID {}). Use <Space>lk to stop.".format(pid), bad=True)
        return None
    tool = _lan_find_tool()
    if tool is None:
        fm.notify("Install miniserve or python3 to serve files", bad=True)
        return None
    ip = _lan_ip()
    if ip is None:
        fm.notify("No LAN address found — not serving", bad=True)
        return None
    return tool, ip, port


class lan_serve(Command):
    """:lan_serve [port]  (<Space>ll)

    Serve the current directory over HTTP on the LAN interface only (not
    0.0.0.0).  No authentication — anyone on the LAN can read it while it
    runs.  Uses miniserve if available, falls back to python -m http.server.
    Default port: 8080. Runs in background; kill with <Space>lk.
    """

    def execute(self):
        pre = _lan_preflight(self.fm, self)
        if pre is None:
            return
        tool, ip, port = pre
        cwd = self.fm.thisdir.path
        proc = _lan_start(self.fm, _lan_server_cmd(tool, ip, port, cwd))
        if proc is None:
            return
        self.fm.notify("Serving {} on http://{}:{}  [{}]  PID {}".format(
            os.path.basename(cwd), ip, port, tool[0], proc.pid))


class lan_serve_file(Command):
    """:lan_serve_file [port]  (<Space>lf)

    Serve only the current file over HTTP on the LAN interface.
    miniserve serves the file directly; the python fallback serves a private
    temp dir holding a single symlink to it (removed by <Space>lk).
    Default port: 8080.
    """

    def execute(self):
        f = self.fm.thisfile
        if f is None or f.is_directory:
            self.fm.notify("No file under cursor", bad=True)
            return
        pre = _lan_preflight(self.fm, self)
        if pre is None:
            return
        tool, ip, port = pre

        tmpdir = None
        if tool[0] == 'miniserve':
            target = f.path
        else:
            tmpdir = tempfile.mkdtemp(prefix='ranger-lan-')
            os.symlink(os.path.abspath(f.path), os.path.join(tmpdir, f.basename))
            target = tmpdir

        proc = _lan_start(self.fm, _lan_server_cmd(tool, ip, port, target), tmpdir)
        if proc is None:
            return
        self.fm.notify("Serving {} on http://{}:{}/{}  PID {}".format(
            f.basename, ip, port, quote(f.basename), proc.pid))


class lan_qr(Command):
    """:lan_qr [port]  (<Space>lq)

    Send the current file via qrcp — prints a QR code so phones can pull it.
    Requires: qrcp.
    """

    def execute(self):
        if not require_tool(self.fm, 'qrcp', "Install qrcp for QR-code file transfer"):
            return

        f = self.fm.thisfile
        if f is None:
            self.fm.notify("No file under cursor", bad=True)
            return

        port = _parse_port(self.fm, self.rest(1))
        if port is None:
            return
        self.fm.run(['qrcp', '--port', str(port), 'send', '--', f.path])


class lan_kill(Command):
    """:lan_kill  (<Space>lk)

    Kill the background HTTP server started by lan_serve / lan_serve_file.
    """

    def execute(self):
        pid, tmpdir = _lan_read_state()
        if pid is None:
            self.fm.notify("No server PID found", bad=True)
            return

        if not _lan_pid_alive(pid):
            _lan_cleanup(tmpdir)
            self.fm.notify("Server (PID {}) already dead".format(pid), bad=True)
            return

        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as e:
            self.fm.notify("Could not kill PID {}: {}".format(pid, e), bad=True)
            return
        _lan_cleanup(tmpdir)
        self.fm.notify("Stopped server (PID {})".format(pid))
