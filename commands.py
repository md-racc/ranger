# commands.py — thin loader
#
# ranger loads this file via importlib.util.spec_from_file_location, which does
# NOT add the file's directory to sys.path.  The insert below is required so
# that "from cmds.foo import *" can resolve the cmds/ package sitting alongside
# this file.

from __future__ import (absolute_import, division, print_function)

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

# Standard names re-exported so any cmds/ module that does
# "from ranger.api.commands import Command" stays self-contained,
# but keep them here too for any inline snippets ranger might inject.
import os
import shlex
import subprocess
from ranger.api.commands import Command

from cmds.nav        import *   # fzf/zoxide/recent nav, mkcd, flatten, rg, ext nav
from cmds.trash      import *   # trash / undo / list / restore / empty
from cmds.clipboard  import *   # copy_path/name/dir, yank_contents, wl_paste
from cmds.archives   import *   # extract*, compress*, archive_list/test
from cmds.files      import *   # rename_ext, diff, dedup
from cmds.transfer   import *   # moveto, copyto, rsync_to, wormhole send/recv
from cmds.ssh        import *   # sshfs mount/shell/unmount + quit/quitall override
from cmds.perms      import *   # chmod, chown, chmod_recursive
from cmds.preview    import *   # preview_toggle/peek/clear/render_all
from cmds.security   import *   # hash_show/verify/copy, encrypt/decrypt
from cmds.network    import *   # lan_serve/file/qr/kill
from cmds.transform  import *   # image/video/pdf/name ops
from cmds.open_here  import *   # open_project, spawn_terminal, cd_git_root, dir_diff, drag_out
from cmds.git        import *   # git_diff, git_discard
from cmds.mount      import *   # device_mount, device_unmount, iso_mount, device_eject
