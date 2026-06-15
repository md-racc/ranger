from __future__ import (absolute_import, division, print_function)
import os
import shlex
import shutil
import tempfile
from ranger.api.commands import Command
from cmds._util import pager_str, unique_dest


class touch(Command):
    """:touch <fname>  — create file and open in vim."""

    def execute(self):
        fname = os.path.join(self.fm.thisdir.path,
                             os.path.expanduser(self.rest(1)))
        if not os.path.lexists(fname):
            open(fname, 'a').close()
        self.fm.run('vim ' + shlex.quote(fname))

    def tab(self, tabnum):
        return self._tab_directory_content()


class rename_ext(Command):
    """:rename_ext <new_extension>

    Rename the extension of the selected file(s).
    Example: :rename_ext mp4
    """

    def execute(self):
        new_ext = self.rest(1).lstrip('.')
        if not new_ext:
            self.fm.notify("Usage: rename_ext <extension>", bad=True)
            return
        renamed = collided = 0
        failed = []
        for f in self.fm.thistab.get_selection():
            base = os.path.splitext(f.path)[0]
            target = base + '.' + new_ext
            if target == f.path:
                continue  # Already at target extension, skip
            dest = unique_dest(target)
            if dest != target:
                collided += 1
            try:
                os.rename(f.path, dest)
            except OSError as ex:
                failed.append('{}: {}'.format(f.basename, ex.strerror))
                continue
            renamed += 1
        if failed:
            self.fm.notify("Failed: " + ';  '.join(failed[:3]), bad=True)
        if renamed == 0:
            if not failed:
                self.fm.notify("Nothing to rename — already .{}".format(new_ext))
            return
        msg = "Renamed {} file(s) to .{}".format(renamed, new_ext)
        if collided:
            msg += " ({} renamed to avoid collision)".format(collided)
        self.fm.notify(msg)
        self.fm.reload_cwd()


class diff(Command):
    """:diff

    Show a unified diff between the two selected files, piped to less.
    """

    def execute(self):
        selection = self.fm.thistab.get_selection()
        if len(selection) < 2:
            self.fm.notify("Select exactly 2 files to diff", bad=True)
            return
        f1, f2 = selection[0].path, selection[1].path
        self.fm.run('diff --color=always -u -- {} {} | {}'.format(
            shlex.quote(f1), shlex.quote(f2), pager_str(color=True)))


class dedup(Command):
    """:dedup  — interactively find and remove duplicate files under cwd.

    Prefers rmlint; falls back to fdupes.

    rmlint flow:
      1. Scan cwd — generates rmlint.sh listing what would be removed.
      2. Open rmlint.sh in $PAGER for review.
      3. Prompt [y/N] — only runs rmlint.sh on explicit 'y'.

    fdupes flow:
      fdupes -r -d cwd — interactive per-group prompts, never silent.
    """

    def execute(self):
        cwd = self.fm.thisdir.path

        if shutil.which('rmlint'):
            # rmlint.sh / rmlint.json go to a private temp dir, not the
            # scanned directory.
            tmp = tempfile.mkdtemp(prefix='ranger-rmlint-')
            script = os.path.join(tmp, 'rmlint.sh')
            pager = ' '.join(shlex.quote(a) for a in shlex.split(pager_str()))
            cmd = (
                'rmlint -o progressbar -o summary '
                '-o sh:{script} -o json:{json} {cwd} '
                '&& {pager} {script} '
                '&& printf "\\nExecute rmlint.sh? [y/N] " '
                '&& read -r _ans && [ "$_ans" = y ] '
                '&& bash {script} '
                '|| echo "(cancelled)"'
            ).format(
                cwd=shlex.quote(cwd),
                script=shlex.quote(script),
                json=shlex.quote(os.path.join(tmp, 'rmlint.json')),
                pager=pager,
            )
            try:
                self.fm.run(cmd)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            self.fm.reload_cwd()
        elif shutil.which('fdupes'):
            self.fm.run('fdupes -r -d {}'.format(shlex.quote(cwd)))
            self.fm.reload_cwd()
        else:
            self.fm.notify(
                "Install rmlint (preferred) or fdupes",
                bad=True)


class disk_top(Command):
    """:disk_top [N]  (<Space>dt)

    Show the N largest files under cwd, sorted by size descending.
    Uses fd (if available) for the file list, otherwise find.
    N defaults to 20.
    """

    _DEFAULT_N = 20

    def execute(self):
        try:
            n = int(self.arg(1)) if self.arg(1) else self._DEFAULT_N
        except ValueError:
            n = self._DEFAULT_N

        cwd   = self.fm.thisdir.path
        pager = os.environ.get('PAGER') or 'more'

        if shutil.which('fd'):
            # -H includes dotfiles; --no-ignore includes .gitignored files
            finder = 'fd --type f -H --no-ignore -0 . {}'.format(shlex.quote(cwd))
        else:
            finder = 'find {} -type f -print0'.format(shlex.quote(cwd))

        cmd = (
            '{finder} 2>/dev/null'
            ' | xargs -0 du -sh 2>/dev/null'
            ' | sort -rh'
            ' | head -{n}'
            ' | {pager}'
        ).format(finder=finder, n=n, pager=pager)
        self.fm.run(cmd)
