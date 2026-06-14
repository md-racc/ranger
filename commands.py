# commands.py — custom ranger commands
#
# Every Command subclass defined here becomes a ranger console command.

from __future__ import (absolute_import, division, print_function)

import atexit
import configparser
import datetime
import glob
import os
import re as _re
import shlex
import shutil
import subprocess
import tempfile
import time
from urllib.parse import quote, unquote
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
