"""
Zoxide integration plugin for ranger.

Feeds every directory change into the zoxide database so your ranger
navigation builds up zoxide's frecency rankings. Requires zoxide to be
installed and on $PATH.
"""

import shutil
import subprocess

import ranger.api

_orig_hook_init = ranger.api.hook_init


def hook_init(fm):
    _orig_hook_init(fm)

    if not shutil.which('zoxide'):
        return          # not installed: don't raise on every cd

    def update_zoxide(signal):
        try:
            subprocess.Popen(
                ['zoxide', 'add', '--', fm.thisdir.path],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass        # uninstalled while ranger runs
    fm.signal_bind('cd', update_zoxide)


ranger.api.hook_init = hook_init
