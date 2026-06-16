"""
ssh_cleanup.py — ranger plugin

Two jobs:
  1. On startup: scan /tmp/ranger-sshfs/*.pid and unmount any mounts none
     of whose user PIDs is still running (stale mounts from crashed sessions).
  2. Install a SIGTERM handler that calls sys.exit(0), which triggers the
     atexit handlers registered in commands.py so mounts are cleaned up even
     when ranger is killed via SIGTERM rather than a clean quit.
"""

import glob
import os
import signal
import sys

import ranger.api


_orig_hook_init = ranger.api.hook_init


def hook_init(fm):
    _orig_hook_init(fm)

    # commands.py has run by now, so cmds/ is on sys.path.
    from cmds._util import SSH_MOUNT_BASE as _BASE, fuse_unmount, ssh_mount_users

    # ── Sweep stale mounts from crashed/killed previous sessions ─────────────
    # <mount>.pid lists every ranger using the mount; only unmount when none
    # of them is alive any more (another running ranger may still use it).
    if os.path.isdir(_BASE):
        for pid_file in glob.glob(_BASE + '/*.pid'):
            mount_dir = pid_file[:-4]   # strip .pid suffix
            if not ssh_mount_users(mount_dir) and os.path.ismount(mount_dir):
                fuse_unmount(mount_dir)

    # ── Make SIGTERM trigger atexit (sys.exit raises SystemExit) ────────────
    def _sigterm_handler(signum, frame):
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sigterm_handler)


ranger.api.hook_init = hook_init
