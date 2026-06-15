from __future__ import (absolute_import, division, print_function)
import os
import shlex
import shutil
from ranger.api.commands import Command
from cmds._util import transfer_items


def _report(fm, verb, dest, done, renamed, failed):
    msg = "{} {} item(s) to {}".format(verb, done, dest)
    if renamed:
        msg += " ({} renamed to avoid collision)".format(renamed)
    fm.notify(msg)
    if failed:
        fm.notify("Failed: " + ';  '.join(failed[:3])
                  + (' …' if len(failed) > 3 else ''), bad=True)


class moveto(Command):
    """:moveto <path>

    Move the selected files to the given directory.  Never overwrites:
    collisions get a _N suffix.  Tab-completion works on the path argument.
    """

    def execute(self):
        dest = os.path.expanduser(self.rest(1))
        if not dest:
            self.fm.notify("Usage: moveto <destination>", bad=True)
            return
        dest = os.path.join(self.fm.thisdir.path, dest)
        if not os.path.isdir(dest):
            self.fm.notify("Not a directory: {}".format(dest), bad=True)
            return
        paths = [f.path for f in self.fm.thistab.get_selection()]
        _report(self.fm, "Moved", dest, *transfer_items(paths, dest))
        self.fm.reload_cwd()

    def tab(self, tabnum):
        return self._tab_directory_content()


class copyto(Command):
    """:copyto <path>

    Copy the selected files/directories to the given directory.  Never
    overwrites: collisions get a _N suffix.  Tab-completion works on the
    path argument.
    """

    def execute(self):
        dest = os.path.expanduser(self.rest(1))
        if not dest:
            self.fm.notify("Usage: copyto <destination>", bad=True)
            return
        dest = os.path.join(self.fm.thisdir.path, dest)
        if not os.path.isdir(dest):
            self.fm.notify("Not a directory: {}".format(dest), bad=True)
            return
        paths = [f.path for f in self.fm.thistab.get_selection()]
        _report(self.fm, "Copied", dest, *transfer_items(paths, dest, copy=True))
        self.fm.reload_cwd()

    def tab(self, tabnum):
        return self._tab_directory_content()


class rsync_to(Command):
    """:rsync_to <destination>

    Copy selected files to destination using rsync with progress display.
    Preferred over copyto for large files or remote paths.
    """

    def execute(self):
        dest = os.path.expanduser(self.rest(1))
        if not dest:
            self.fm.notify("Usage: rsync_to <destination>", bad=True)
            return
        files = [f.path for f in self.fm.thistab.get_selection()]
        self.fm.run('rsync -avh --progress {} {}'.format(
            ' '.join(shlex.quote(f) for f in files),
            shlex.quote(dest),
        ))

    def tab(self, tabnum):
        return self._tab_directory_content()


class rsync_dry_run(Command):
    """:rsync_dry_run <destination>  (<Space>td)

    Dry-run rsync — shows what would be transferred without moving any files.
    Pipe the output to $PAGER for review, then run <Space>tr to commit.
    Accepts local paths or remote rsync targets (user@host:/path).
    """

    def execute(self):
        dest = self.rest(1).strip()
        if not dest:
            self.fm.open_console('rsync_dry_run ')
            return
        dest = os.path.expanduser(dest)
        files = [f.path for f in self.fm.thistab.get_selection()]
        if not files:
            self.fm.notify("No files selected", bad=True)
            return
        pager = os.environ.get('PAGER') or 'more'
        cmd = 'rsync -avhn --progress {} {} | {}'.format(
            ' '.join(shlex.quote(f) for f in files),
            shlex.quote(dest),
            pager,
        )
        self.fm.run(cmd)

    def tab(self, tabnum):
        return self._tab_directory_content()


class wormhole_send(Command):
    """:wormhole_send [code]  (<Space>tw)

    Send selected files via croc (preferred) or magic-wormhole.
    Optional [code] sets a predetermined transfer code (croc --code CODE).
    If omitted, croc generates a random code and prints it.
    CROC_SECRET env var is honoured automatically if set.
    """

    def execute(self):
        code = self.rest(1).strip()

        selection = self.fm.thistab.get_selection()
        files = [f.path for f in selection]
        if not files:
            self.fm.notify("No files selected", bad=True)
            return

        quoted = ' '.join(shlex.quote(f) for f in files)

        if shutil.which('croc'):
            env = 'CROC_SECRET={} '.format(shlex.quote(code)) if code else ''
            cmd = '{}croc send {}'.format(env, quoted)
        elif shutil.which('wormhole'):
            cmd = 'wormhole send ' + quoted
        else:
            self.fm.notify("Install croc or magic-wormhole for peer transfer", bad=True)
            return

        self.fm.run(cmd)


class wormhole_recv(Command):
    """:wormhole_recv [code]  (<Space>tW)

    Receive files into the current directory via croc / magic-wormhole.
    [code] is the transfer code shown by the sender (or your pre-agreed secret).
    CROC_SECRET env var is honoured automatically if set.
    """

    def execute(self):
        code = self.rest(1).strip()
        cwd  = self.fm.thisdir.path

        if shutil.which('croc'):
            # Use CROC_SECRET env var rather than a positional arg — positional args
            # are ambiguous against croc subcommand names and cause silent exits.
            env  = 'CROC_SECRET={} '.format(shlex.quote(code)) if code else ''
            cmd  = '{}croc --yes --out {}'.format(env, shlex.quote(cwd))
        elif shutil.which('wormhole'):
            if code:
                cmd = 'wormhole receive ' + shlex.quote(code)
            else:
                cmd = 'wormhole receive'
        else:
            self.fm.notify("Install croc or magic-wormhole for peer transfer", bad=True)
            return

        self.fm.run(cmd)
        self.fm.reload_cwd()
