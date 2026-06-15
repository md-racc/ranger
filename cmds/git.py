from __future__ import (absolute_import, division, print_function)
import os
import shlex
import shutil
import subprocess
from ranger.api.commands import Command
from cmds._util import ask_yes


class git_diff(Command):
    """:git_diff  (<Space>gd)

    Show git diff of the current file, paged through delta if available,
    otherwise less -R.
    """

    def execute(self):
        f = self.fm.thisfile
        if f is None:
            self.fm.notify("No file selected", bad=True)
            return

        # Quick check: if the file is clean, notify instead of opening an empty pager.
        probe = subprocess.run(['git', 'diff', '--quiet', '--', f.path])
        if probe.returncode == 0:
            self.fm.notify("No unstaged changes in: " + f.basename)
            return

        path = shlex.quote(f.path)
        # delta is a purpose-built git diff pager; prefer it when installed.
        # Otherwise honour $PAGER, falling back to more.
        if shutil.which('delta'):
            pager = 'delta'
        else:
            pager = os.environ.get('PAGER') or 'more'
        # No flags='p': let the pipeline own the terminal so the pager runs normally.
        self.fm.run('git diff --color=always -- {} | {}'.format(path, pager))


class git_discard(Command):
    """:git_discard [confirm]  (<Space>gC)

    Asks y/N (naming the files), then runs git restore (git >= 2.23) or
    git checkout -- on every selected file.  'confirm' skips the question.
    Discards only working-tree changes; staged changes are kept.
    Irreversible — use with care.
    """

    def execute(self):
        selection = self.fm.thistab.get_selection()
        if not selection:
            selection = [self.fm.thisfile] if self.fm.thisfile else []
        if not selection:
            self.fm.notify("No file selected", bad=True)
            return

        if self.arg(1) == 'confirm':
            self._discard(selection)
            return
        preview = ', '.join(f.basename for f in selection[:3])
        if len(selection) > 3:
            preview += '…'
        ask_yes(self.fm, "Discard uncommitted changes to {}?".format(preview),
                lambda: self._discard(selection))

    def _discard(self, selection):
        ok = fail = 0
        first_err = None
        for f in selection:
            result = subprocess.run(['git', 'restore', '--', f.path], capture_output=True)
            if result.returncode != 0:
                result = subprocess.run(['git', 'checkout', '--', f.path], capture_output=True)
            if result.returncode == 0:
                ok += 1
            else:
                fail += 1
                if first_err is None:
                    first_err = result.stderr.decode('utf-8', 'replace').strip()

        msg = "Discarded changes: {} file(s)".format(ok)
        if fail:
            msg += ", {} failed".format(fail)
            if first_err:
                msg += " ({})".format(first_err)
        self.fm.notify(msg, bad=bool(fail))
        self.fm.reload_cwd()
