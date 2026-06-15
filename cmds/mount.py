from __future__ import (absolute_import, division, print_function)
import json
import os
import shlex
import subprocess
import tempfile
from ranger.api.commands import Command
from cmds._util import require_tool


def _lsblk_devices(fm):
    """Return parsed lsblk JSON, or None on failure."""
    if not require_tool(fm, 'lsblk'):
        return None
    result = subprocess.run(
        ['lsblk', '--json', '-o', 'NAME,FSTYPE,SIZE,MOUNTPOINT,MOUNTPOINTS,LABEL,RM,HOTPLUG'],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        return None


def _collect_devices(devices, mounted_only):
    """Walk lsblk tree; return list of (display_line, /dev/path) tuples.

    mounted_only=True  → devices that ARE mounted (for unmount picker).
    mounted_only=False → devices that are NOT mounted (for mount picker).
    """
    entries = []
    for d in devices:
        # Prefer the list form (util-linux ≥2.37) over the scalar.
        mps = d.get('mountpoints') or []
        if not isinstance(mps, list):
            mps = [mps] if mps else []
        mp_scalar = d.get('mountpoint') or ''
        all_mounts = [m for m in mps if m] or ([mp_scalar] if mp_scalar else [])

        fstype = d.get('fstype') or ''
        name   = d.get('name', '')
        size   = d.get('size') or ''
        label  = d.get('label') or ''

        if mounted_only:
            active = [m for m in all_mounts if m != '[SWAP]']
            if active:
                mp_str = ','.join(active)
                display = '/dev/{:<12} {:<8} {:<8} {} ({})'.format(
                    name, fstype, size, mp_str, label)
                entries.append((display, '/dev/' + name))
        else:
            if fstype and not all_mounts:
                display = '/dev/{:<12} {:<8} {:<8} {}'.format(
                    name, fstype, size, label)
                entries.append((display, '/dev/' + name))

        for child in d.get('children') or []:
            entries.extend(_collect_devices([child], mounted_only))
    return entries


def _collect_devices_all(devices):
    """Like _collect_devices but returns every removable/hotplug device
    regardless of mount state. Fixed/system disks are excluded — this
    feeds the eject picker and must never offer to eject the boot disk."""
    entries = []
    for d in devices:
        removable = bool(d.get('rm')) or bool(d.get('hotplug'))
        entries.extend(_collect_removable_subtree(d, removable))
    return entries


def _collect_removable_subtree(d, allowed):
    mps = d.get('mountpoints') or []
    if not isinstance(mps, list):
        mps = [mps] if mps else []
    mp_scalar = d.get('mountpoint') or ''
    all_mounts = [m for m in mps if m] or ([mp_scalar] if mp_scalar else [])
    active = [m for m in all_mounts if m != '[SWAP]']
    status = ','.join(active) if active else 'not mounted'

    fstype = d.get('fstype') or ''
    name   = d.get('name', '')
    size   = d.get('size') or ''
    label  = d.get('label') or ''

    entries = []
    if allowed:
        display = '/dev/{:<12} {:<8} {:<8} {} ({})'.format(name, fstype, size, status, label)
        entries.append((display, '/dev/' + name))

    for child in d.get('children') or []:
        entries.extend(_collect_removable_subtree(child, allowed))
    return entries


def _fzf_pick(fm, entries, prompt, header):
    """Run fzf via fm.run() with temp files so ncurses is suspended properly.
    Returns chosen /dev/path or None if cancelled."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.in', delete=False) as tf:
        tf.write('\n'.join(display for display, _ in entries))
        in_file = tf.name
    fd, out_file = tempfile.mkstemp(suffix='.out')
    os.close(fd)
    try:
        fm.run('fzf --border --prompt={} --header={} < {} > {}'.format(
            shlex.quote(prompt),
            shlex.quote(header),
            shlex.quote(in_file),
            shlex.quote(out_file),
        ))
        try:
            with open(out_file) as f:
                selected = f.read().strip()
        except OSError:
            return None
        for display, path in entries:
            if display == selected:
                return path
        return None
    finally:
        for tmp in [in_file, out_file]:
            try:
                os.unlink(tmp)
            except OSError:
                pass


class device_mount(Command):
    """:device_mount  (<Space>mm)

    Pick an unmounted block device from an fzf list and mount it via
    udisksctl.  Ranger then cd's to the resulting mountpoint.
    """

    def execute(self):
        if not require_tool(self.fm, 'udisksctl'):
            return
        data = _lsblk_devices(self.fm)
        if data is None:
            self.fm.notify("lsblk failed", bad=True)
            return

        entries = _collect_devices(data.get('blockdevices', []), mounted_only=False)
        if not entries:
            self.fm.notify("No unmounted devices found")
            return

        dev = _fzf_pick(self.fm, entries, 'Mount> ', 'Select device to mount')
        if dev is None:
            return

        result = subprocess.run(
            ['udisksctl', 'mount', '--no-user-interaction', '-b', dev],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            self.fm.notify(
                "mount failed: " + (result.stderr.strip() or result.stdout.strip()),
                bad=True,
            )
            return

        output = result.stdout.strip()
        self.fm.notify(output or "Mounted " + dev)
        # udisksctl prints "Mounted /dev/sdX at /run/media/user/label."
        if ' at ' in output:
            mountpoint = output.split(' at ', 1)[1].rstrip('.')
            if os.path.isdir(mountpoint):
                self.fm.cd(mountpoint)


class device_unmount(Command):
    """:device_unmount  (<Space>mu)

    Pick a mounted block device from an fzf list and unmount it via
    udisksctl.
    """

    def execute(self):
        if not require_tool(self.fm, 'udisksctl'):
            return
        data = _lsblk_devices(self.fm)
        if data is None:
            self.fm.notify("lsblk failed", bad=True)
            return

        entries = _collect_devices(data.get('blockdevices', []), mounted_only=True)
        if not entries:
            self.fm.notify("No mounted devices to unmount")
            return

        dev = _fzf_pick(self.fm, entries, 'Unmount> ', 'Select device to unmount')
        if dev is None:
            return

        result = subprocess.run(
            ['udisksctl', 'unmount', '--no-user-interaction', '-b', dev],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            self.fm.notify(result.stdout.strip() or "Unmounted " + dev)
        else:
            self.fm.notify(
                "unmount failed: " + (result.stderr.strip() or result.stdout.strip()),
                bad=True,
            )


class iso_mount(Command):
    """:iso_mount  (<Space>mi)

    Loop-mount the selected image file (ISO, img, …) via
    udisksctl loop-setup.  Reports the created loop device so you
    can then mount it with <Space>mm or let udisks automount it.
    """

    def execute(self):
        if not require_tool(self.fm, 'udisksctl'):
            return
        f = self.fm.thisfile
        if f is None or not os.path.isfile(f.path):
            self.fm.notify("Select an image file to loop-mount", bad=True)
            return

        result = subprocess.run(
            ['udisksctl', 'loop-setup', '--no-user-interaction', '-f', f.path],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            self.fm.notify(result.stdout.strip() or "Loop device created")
        else:
            self.fm.notify(
                "loop-setup failed: " + (result.stderr.strip() or result.stdout.strip()),
                bad=True,
            )


class device_eject(Command):
    """:device_eject  (<Space>me)

    Pick a removable/hotplug block device from an fzf list (mounted or not)
    and unmount then power it off for safe USB removal. Fixed/system disks
    are never listed.
    """

    def execute(self):
        if not require_tool(self.fm, 'udisksctl'):
            return
        data = _lsblk_devices(self.fm)
        if data is None:
            self.fm.notify("lsblk failed", bad=True)
            return

        entries = _collect_devices_all(data.get('blockdevices', []))
        if not entries:
            self.fm.notify("No removable devices found")
            return

        dev = _fzf_pick(self.fm, entries, 'Eject> ', 'Select device to eject')
        if dev is None:
            return

        # Best-effort unmount; ignore failure (device may not be mounted).
        subprocess.run(
            ['udisksctl', 'unmount', '--no-user-interaction', '-b', dev],
            capture_output=True,
        )

        result = subprocess.run(
            ['udisksctl', 'power-off', '--no-user-interaction', '-b', dev],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            self.fm.notify("Ejected: " + dev)
        else:
            self.fm.notify(
                "power-off failed: " + (result.stderr.strip() or result.stdout.strip()),
                bad=True,
            )
