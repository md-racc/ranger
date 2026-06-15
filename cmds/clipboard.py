from __future__ import (absolute_import, division, print_function)
import os
import subprocess
import time
from urllib.parse import quote
from ranger.api.commands import Command
from cmds._util import clipboard_copy


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


class copy_rel_path(Command):
    """:copy_rel_path  (<Space>yr)

    Copy the path(s) of selected files relative to ranger's cwd, one per line.
    """

    def execute(self):
        items = _selection(self.fm)
        if not items:
            self.fm.notify("Nothing selected", bad=True)
            return
        cwd = self.fm.thisdir.path
        paths = [os.path.relpath(f.path, cwd) for f in items]
        text = '\n'.join(paths)
        if not clipboard_copy(self.fm, text):
            return
        if len(items) == 1:
            self.fm.notify("Copied relative: " + text)
        else:
            self.fm.notify("Copied {} relative paths".format(len(items)))


class copy_git_rel_path(Command):
    """:copy_git_rel_path  (<Space>yg)

    Copy the path(s) of selected files relative to the git repo root, one per line.
    """

    def execute(self):
        items = _selection(self.fm)
        if not items:
            self.fm.notify("Nothing selected", bad=True)
            return
        result = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True, text=True,
            cwd=self.fm.thisdir.path,
        )
        if result.returncode != 0:
            self.fm.notify("Not in a git repository", bad=True)
            return
        git_root = result.stdout.strip()
        paths = [os.path.relpath(f.path, git_root) for f in items]
        text = '\n'.join(paths)
        if not clipboard_copy(self.fm, text):
            return
        if len(items) == 1:
            self.fm.notify("Copied git-relative: " + text)
        else:
            self.fm.notify("Copied {} git-relative paths".format(len(items)))


class copy_markdown_link(Command):
    """:copy_markdown_link  (<Space>yl)

    Copy selected file(s) as Markdown link(s), one per line.
    """

    def execute(self):
        items = _selection(self.fm)
        if not items:
            self.fm.notify("Nothing selected", bad=True)
            return
        links = ['[{}]({})'.format(f.basename, 'file://' + quote(f.path, safe='/'))
                 for f in items]
        text = '\n'.join(links)
        if not clipboard_copy(self.fm, text):
            return
        if len(items) == 1:
            self.fm.notify("Copied link: " + text)
        else:
            self.fm.notify("Copied {} markdown links".format(len(items)))


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
