"""Shared helpers for ranger cmds/ modules."""
from __future__ import (absolute_import, division, print_function)
import os
import shlex
import shutil
import subprocess

# Canonical base directory for all sshfs mounts.
# Used by cmds/ssh.py (via import) and plugins/ssh_cleanup.py (lazy import
# inside hook_init, after commands.py has set up sys.path).
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
