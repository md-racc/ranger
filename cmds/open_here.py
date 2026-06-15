from __future__ import (absolute_import, division, print_function)
import os
import shlex
import shutil
import subprocess
from ranger.api.commands import Command
from cmds._util import pager_str


# GUI editors: open cwd as project backgrounded; TUI editors: suspend ranger.
_GUI_EDITORS = frozenset({
    'code', 'codium', 'code-oss', 'code-insiders',
    'sublime_text', 'subl', 'atom', 'zed',
    'gedit', 'kate', 'geany', 'mousepad', 'pluma', 'xed',
})

# Terminal emulators and how to pass a working directory.
_TERM_ARGS = {
    'kitty':          lambda d: ['kitty', '--directory', d],
    'foot':           lambda d: ['foot', '--working-directory', d],
    'alacritty':      lambda d: ['alacritty', '--working-directory', d],
    'wezterm':        lambda d: ['wezterm', 'start', '--cwd', d],
    'gnome-terminal': lambda d: ['gnome-terminal', '--working-directory=' + d],
    'xfce4-terminal': lambda d: ['xfce4-terminal', '--working-directory=' + d],
    'xterm':          lambda d: ['xterm', '-e', 'cd {} && exec $SHELL'.format(shlex.quote(d))],
}
# Same terminals, but run a specific command instead of an interactive shell.
_TERM_WITH_CMD = {
    'kitty':          lambda d, c: ['kitty', '--directory', d, '--'] + c,
    'foot':           lambda d, c: ['foot', '--working-directory', d, '--'] + c,
    'alacritty':      lambda d, c: ['alacritty', '--working-directory', d, '-e'] + c,
    'wezterm':        lambda d, c: ['wezterm', 'start', '--cwd', d, '--'] + c,
    'gnome-terminal': lambda d, c: ['gnome-terminal', '--working-directory=' + d, '--'] + c,
    'xfce4-terminal': lambda d, c: ['xfce4-terminal', '--working-directory=' + d, '-e'] + c,
    'xterm':          lambda d, c: ['xterm', '-e'] + c,
}
_TERM_ORDER = ['kitty', 'foot', 'alacritty', 'wezterm',
               'gnome-terminal', 'xfce4-terminal', 'xterm']


def _find_terminal():
    """Return the name of the best available terminal emulator, or None."""
    term_env = os.environ.get('TERMINAL', '').strip()
    if term_env and shutil.which(term_env):
        return term_env
    for t in _TERM_ORDER:
        if shutil.which(t):
            return t
    return None


def _run_in_new_terminal(cwd, cmd_args):
    """Spawn cmd_args in a new terminal window at cwd.

    Honours $TERMINAL, then walks _TERM_ORDER.  Under Hyprland the window
    is dispatched [floating] via hyprctl, matching spawn_terminal behaviour.
    Returns True if a terminal was found and launched, False otherwise.
    """
    term = _find_terminal()
    if term is None:
        return False

    build = _TERM_WITH_CMD.get(term, lambda d, c: [term, '-e'] + c)
    args = build(cwd, cmd_args)

    if (os.environ.get('HYPRLAND_INSTANCE_SIGNATURE') and
            shutil.which('hyprctl')):
        cmd_str = ' '.join(shlex.quote(a) for a in args)
        subprocess.Popen(['hyprctl', 'dispatch', 'exec', '[floating] ' + cmd_str])
    else:
        subprocess.Popen(args)
    return True

# GUI file managers, tried in order.
_FM_ORDER = ['thunar', 'nautilus', 'dolphin', 'nemo', 'pcmanfm', 'caja', 'spacefm']


class open_project(Command):
    """:open_project  (<Space>oP) — open cwd as a project in $EDITOR.

    GUI editors (code, zed, …) are backgrounded; TUI editors (nvim, vim, …)
    suspend ranger and run in the current terminal.
    """

    def execute(self):
        cwd = self.fm.thisdir.path
        editor = (os.environ.get('EDITOR') or
                  os.environ.get('VISUAL') or
                  'nvim')
        # $EDITOR may contain flags (e.g. "nvim -u init.vim"); split to get the binary.
        editor_parts = shlex.split(editor)
        editor_bin = editor_parts[0]
        base = os.path.basename(editor_bin)
        if not shutil.which(editor_bin):
            self.fm.notify("Editor '{}' not found; set $EDITOR".format(editor_bin), bad=True)
            return
        if base in _GUI_EDITORS:
            subprocess.Popen(editor_parts + [cwd])
        else:
            # TUI editor: open in a new terminal so ranger stays alive.
            # Fall back to suspending ranger only if no terminal is found.
            if not _run_in_new_terminal(cwd, editor_parts + [cwd]):
                self.fm.run('{} {}'.format(editor, shlex.quote(cwd)))


class spawn_terminal(Command):
    """:spawn_terminal  (<Space>oT) — open a terminal in the current directory.

    Reads $TERMINAL, then tries kitty / foot / alacritty / wezterm / xterm.
    Under Hyprland the window is dispatched as [floating] via hyprctl.
    """

    def execute(self):
        cwd = self.fm.thisdir.path
        term = _find_terminal()
        if term is None:
            self.fm.notify("No terminal found; set $TERMINAL", bad=True)
            return

        build = _TERM_ARGS.get(term, lambda d: [term, '--working-directory', d])
        args = build(cwd)

        if (os.environ.get('HYPRLAND_INSTANCE_SIGNATURE') and
                shutil.which('hyprctl')):
            cmd_str = ' '.join(shlex.quote(a) for a in args)
            subprocess.Popen(['hyprctl', 'dispatch', 'exec',
                              '[floating] ' + cmd_str])
        else:
            subprocess.Popen(args)


class open_filemanager(Command):
    """:open_filemanager  (<Space>oF) — hand off cwd to a GUI file manager.

    Reads $FILE_MANAGER, then tries thunar / nautilus / dolphin / nemo / pcmanfm.
    """

    def execute(self):
        cwd = self.fm.thisdir.path
        fm_env = os.environ.get('FILE_MANAGER', '').strip()
        manager = None
        if fm_env and shutil.which(fm_env):
            manager = fm_env
        else:
            for m in _FM_ORDER:
                if shutil.which(m):
                    manager = m
                    break
        if manager is None:
            self.fm.notify(
                "No GUI file manager found; set $FILE_MANAGER", bad=True)
            return
        subprocess.Popen([manager, cwd])


class hexdump(Command):
    """:hexdump  (<Space>oh)

    Show a hexdump of the current file in the pager.
    Uses hexyl if available (colour-coded output), otherwise xxd.
    """

    def execute(self):
        f = self.fm.thisfile
        if f is None or not os.path.isfile(f.path):
            self.fm.notify("Select a file to hexdump", bad=True)
            return
        path = shlex.quote(f.path)
        pager = pager_str(color=True)
        if shutil.which('hexyl'):
            self.fm.run('hexyl {} | {}'.format(path, pager))
        elif shutil.which('xxd'):
            self.fm.run('xxd {} | {}'.format(path, pager))
        else:
            self.fm.notify("Neither hexyl nor xxd found", bad=True)


class cd_git_root(Command):
    """:cd_git_root  (<Space>oG) — cd to the root of the current git repository."""

    def execute(self):
        cwd = self.fm.thisdir.path
        try:
            root = subprocess.check_output(
                ['git', 'rev-parse', '--show-toplevel'],
                cwd=cwd, stderr=subprocess.DEVNULL
            ).decode().strip()
        except subprocess.CalledProcessError:
            self.fm.notify("Not inside a git repository", bad=True)
            return
        self.fm.cd(root)


class dir_diff(Command):
    """:dir_diff  (<Space>oD) — recursively diff two selected directories (read-only, paged)."""

    def execute(self):
        selection = self.fm.thistab.get_selection()
        dirs = [f.path for f in selection if os.path.isdir(f.path)]
        if len(dirs) < 2:
            self.fm.notify("Select two directories to diff", bad=True)
            return
        a, b = dirs[0], dirs[1]
        pager = pager_str(color=True)
        if shutil.which('difft'):
            cmd = 'difft --color always {} {} | {}'.format(
                shlex.quote(a), shlex.quote(b), pager)
        else:
            cmd = 'diff -r --color=always {} {} | {}'.format(
                shlex.quote(a), shlex.quote(b), pager)
        self.fm.run(cmd)


class drag_out(Command):
    """:drag_out  (<Space>or) — drag the selection into another window.

    For web upload areas (webmail, chat apps, forms) that accept a dropped
    file without a file dialog. Opens a small ripdrag window (dragon-drop as
    a fallback) holding the selection; drag from it, it closes after the
    drop. -a drags every item at once.
    """

    def execute(self):
        tool = next((t for t in ('ripdrag', 'dragon-drop') if shutil.which(t)), None)
        if tool is None:
            self.fm.notify("No drag tool: install ripdrag or dragon-drop", bad=True)
            return
        paths = [f.path for f in self.fm.thistab.get_selection()]
        if not paths:
            self.fm.notify("Nothing selected", bad=True)
            return
        subprocess.Popen([tool, '-x', '-a', '--'] + paths, start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
