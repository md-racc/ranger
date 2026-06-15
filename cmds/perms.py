from __future__ import (absolute_import, division, print_function)
import subprocess
from ranger.api.commands import Command
from cmds._util import ask_yes


class chmod(Command):
    """:chmod <mode>

    Set permissions on the selected files (octal or symbolic mode).
    Example: :chmod 755
    Like ranger's built-in, with no argument the mode is the numeric
    prefix typed before the key: 755= runs chmod 755 (rc.conf: map = chmod).
    """

    def execute(self):
        mode = self.rest(1).strip()
        if not mode and self.quantifier is not None:
            mode = str(self.quantifier)
        if not mode:
            self.fm.notify("Usage: chmod <mode>  e.g. chmod 755, or type 755=", bad=True)
            return
        failed = []
        for f in self.fm.thistab.get_selection():
            result = subprocess.run(['chmod', mode, '--', f.path], capture_output=True)
            if result.returncode != 0:
                failed.append(f.basename)
        if failed:
            self.fm.notify("chmod failed on: {}".format(', '.join(failed)), bad=True)
        self.fm.reload_cwd()


class chown(Command):
    """:chown <user>[:<group>]

    Change the owner (and optionally group) of the selected files.
    Examples:
      :chown alice
      :chown alice:staff
      :chown :staff
    """

    def execute(self):
        target = self.rest(1)
        if not target:
            self.fm.notify("Usage: chown <user>[:<group>]", bad=True)
            return
        failed = []
        for f in self.fm.thistab.get_selection():
            result = subprocess.run(['chown', target, '--', f.path], capture_output=True)
            if result.returncode != 0:
                failed.append(f.basename)
        if failed:
            self.fm.notify("chown failed on: {}".format(', '.join(failed)), bad=True)
        else:
            self.fm.notify("Owner changed to {}".format(target))
        self.fm.reload_cwd()


class chmod_recursive(Command):
    """:chmod_recursive <mode> [confirm]  (<Space>cR)

    Asks y/N, then runs chmod -R <mode> on all selected directories.
    'confirm' skips the question.
    """

    def execute(self):
        parts   = self.args[1:]
        confirm = 'confirm' in parts
        mode    = next((p for p in parts if p != 'confirm'), '')

        if not mode:
            self.fm.notify("Usage: chmod_recursive <mode>  e.g. 755", bad=True)
            return

        selection = self.fm.thistab.get_selection()
        dirs = [f for f in selection if f.is_directory]
        if not dirs:
            self.fm.notify("Select directories first", bad=True)
            return

        def _do():
            ok = fail = 0
            for d in dirs:
                r = subprocess.run(['chmod', '-R', mode, '--', d.path],
                                   capture_output=True)
                if r.returncode == 0:
                    ok += 1
                else:
                    fail += 1
            msg = "chmod -R {}: {} applied".format(mode, ok)
            if fail:
                msg += ", {} failed".format(fail)
            self.fm.notify(msg, bad=bool(fail))
            self.fm.reload_cwd()

        if confirm:
            _do()
            return
        preview = ', '.join(d.basename for d in dirs[:3])
        if len(dirs) > 3:
            preview += '…'
        ask_yes(self.fm, "chmod -R {} on {}?".format(mode, preview), _do)


class chown_recursive(Command):
    """:chown_recursive <target> [confirm]  (<Space>cO)

    Asks y/N, then runs chown -R <target> on all selected directories.
    'confirm' skips the question.
    target: user or user:group, same syntax as :chown.
    """

    def execute(self):
        parts   = self.args[1:]
        confirm = 'confirm' in parts
        target  = next((p for p in parts if p != 'confirm'), '')

        if not target:
            self.fm.notify("Usage: chown_recursive <user>[:<group>]", bad=True)
            return

        selection = self.fm.thistab.get_selection()
        dirs = [f for f in selection if f.is_directory]
        if not dirs:
            self.fm.notify("Select directories first", bad=True)
            return

        def _do():
            ok = fail = 0
            for d in dirs:
                r = subprocess.run(['chown', '-R', target, '--', d.path],
                                   capture_output=True)
                if r.returncode == 0:
                    ok += 1
                else:
                    fail += 1
            msg = "chown -R {}: {} applied".format(target, ok)
            if fail:
                msg += ", {} failed".format(fail)
            self.fm.notify(msg, bad=bool(fail))
            self.fm.reload_cwd()

        if confirm:
            _do()
            return
        preview = ', '.join(d.basename for d in dirs[:3])
        if len(dirs) > 3:
            preview += '…'
        ask_yes(self.fm, "chown -R {} on {}?".format(target, preview), _do)
