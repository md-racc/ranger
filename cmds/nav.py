from __future__ import (absolute_import, division, print_function)
import os
import shlex
import shutil
import subprocess
import tempfile
from ranger.api.commands import Command
from cmds._util import ask_yes, require_tool, transfer_items, unique_dest


_QF_EDITORS = frozenset({'nvim', 'vim', 'gvim', 'vi'})


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


class rg_content_search(Command):
    """:rg_content_search <pattern>  (<Space>fg)

    Search file contents recursively with rg --vimgrep from cwd,
    then open results in $EDITOR quickfix (nvim/vim -q <file>).
    Falls back to coloured rg output in $PAGER for other editors.

    Without argument: pre-fills the console so you can type the pattern.
    """

    def execute(self):
        pattern = self.rest(1)
        if not pattern:
            self.fm.open_console('rg_content_search ')
            return

        if not require_tool(self.fm, 'rg', "rg (ripgrep) not found"):
            return

        root   = self.fm.thisdir.path
        editor = (os.environ.get('EDITOR') or os.environ.get('VISUAL') or 'nvim')
        base   = os.path.basename(shlex.split(editor)[0])

        if base in _QF_EDITORS:
            result = subprocess.run(
                ['rg', '--vimgrep', '--color=never', '--', pattern, root],
                capture_output=True, text=True,
            )
            if not result.stdout.strip():
                self.fm.notify('No matches for: ' + pattern)
                return
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.qf', prefix='ranger_rg_', delete=False
            ) as tf:
                tf.write(result.stdout)
                qf_path = tf.name
            try:
                self.fm.run(shlex.split(editor) + ['-q', qf_path])
            finally:
                try:
                    os.unlink(qf_path)
                except OSError:
                    pass
        else:
            pager = (os.environ.get('PAGER') or 'more')
            self.fm.run(
                'rg --color=always -- {} {} | {}'.format(
                    shlex.quote(pattern), shlex.quote(root), pager
                )
            )
