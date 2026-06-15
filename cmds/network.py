from __future__ import (absolute_import, division, print_function)
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from urllib.parse import quote
from ranger.api.commands import Command
from cmds._util import require_tool


_RUNTIME_DIR = os.environ.get('XDG_RUNTIME_DIR', tempfile.gettempdir())
# Line 1: server PID.  Line 2 (optional): temp dir to delete on lan_kill.
_LAN_PID_FILE = os.path.join(_RUNTIME_DIR, 'ranger_lan_server.pid')
_LAN_LOG_FILE = os.path.join(_RUNTIME_DIR, 'ranger_lan_server.log')


def _parse_port(fm, text, default=8080):
    """Return the port in `text` (default 8080), or notify and return None."""
    text = (text or '').strip()
    if not text:
        return default
    try:
        port = int(text)
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        fm.notify("Invalid port: {!r} (1-65535)".format(text), bad=True)
        return None
    return port


_VIRTUAL_IFACES = ('lo', 'docker', 'br-', 'veth', 'virbr', 'tailscale', 'wg', 'tun',
                   'tap', 'zt', 'vnet', 'podman', 'cni', 'flannel')


def _is_private(ip):
    try:
        import ipaddress
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_private and not addr.is_loopback and not addr.is_link_local and \
        addr not in ipaddress.ip_network('100.64.0.0/10')     # CGNAT / tailscale


def _iface_addrs():
    """[(iface, ip)] for global IPv4 addresses on non-virtual interfaces."""
    import json
    try:
        out = subprocess.run(['ip', '-j', '-4', 'addr', 'show', 'scope', 'global'],
                             capture_output=True, text=True, timeout=2).stdout
        data = json.loads(out or '[]')
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    return [(i.get('ifname', ''), a['local'])
            for i in data for a in i.get('addr_info', ())
            if a.get('local') and not i.get('ifname', '').startswith(_VIRTUAL_IFACES)]


def _lan_ip():
    """The LAN address to bind (never 0.0.0.0): the default route's address
    when it's a private LAN address, else the first private address on a
    physical interface (a full-tunnel VPN owns the default route; an
    isolated LAN or hotspot may have none).  No packet is sent: connecting
    a UDP socket only picks the route.  None when there's no LAN address."""
    route_ip = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('192.0.2.1', 9))          # TEST-NET-1, never routed
            route_ip = s.getsockname()[0]
    except OSError:
        pass
    addrs = _iface_addrs()
    if route_ip and _is_private(route_ip) and \
            (not addrs or route_ip in (ip for _, ip in addrs)):
        return route_ip
    for _, ip in addrs:
        if _is_private(ip):
            return ip
    return None


def _lan_find_tool():
    """Return (tool, base_args) for the best available HTTP server, or None."""
    if shutil.which('miniserve'):
        return ('miniserve', ['miniserve', '--no-symlinks'])
    if shutil.which('python3'):
        return ('python3', ['python3', '-m', 'http.server'])
    if shutil.which('python'):
        return ('python', ['python', '-m', 'http.server'])
    return None


def _lan_server_cmd(tool, ip, port, path):
    """argv serving `path` (a dir, or a single file for miniserve) on ip:port."""
    name, base = tool
    if name == 'miniserve':
        return base + ['--interfaces', ip, '--port', str(port), '--', path]
    return base + ['--bind', ip, '--directory', path, str(port)]


def _lan_read_state():
    """Return (pid, tmpdir) from the pid file; (None, None) if missing/corrupt."""
    try:
        with open(_LAN_PID_FILE) as fh:
            lines = fh.read().splitlines()
        return int(lines[0].strip()), (lines[1].strip() if len(lines) > 1 else None)
    except (OSError, ValueError, IndexError):
        return None, None


def _lan_read_pid():
    return _lan_read_state()[0]


def _lan_pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _lan_cleanup(tmpdir):
    try:
        os.remove(_LAN_PID_FILE)
    except OSError:
        pass
    if tmpdir and os.path.basename(tmpdir).startswith('ranger-lan-'):
        shutil.rmtree(tmpdir, ignore_errors=True)


def _lan_start(fm, cmd, tmpdir=None):
    """Start the server, wait briefly, and confirm it is still running.
    Returns the Popen, or None (after notifying) if it died — e.g. port in use."""
    with open(_LAN_LOG_FILE, 'wb') as log:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            start_new_session=True,
        )
    time.sleep(0.3)
    if proc.poll() is not None:
        try:
            with open(_LAN_LOG_FILE, errors='replace') as fh:
                err = fh.read().strip().splitlines()
        except OSError:
            err = []
        fm.notify("Server failed to start: {}".format(
            err[-1] if err else 'exit {}'.format(proc.returncode)), bad=True)
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        return None
    with open(_LAN_PID_FILE, 'w') as fh:
        fh.write('{}\n{}\n'.format(proc.pid, tmpdir or ''))
    return proc


def _lan_preflight(fm, cmd_self):
    """Common checks; returns (tool, ip, port) or None."""
    port = _parse_port(fm, cmd_self.rest(1))
    if port is None:
        return None
    pid = _lan_read_pid()
    if pid and _lan_pid_alive(pid):
        fm.notify("Server already running (PID {}). Use <Space>lk to stop.".format(pid), bad=True)
        return None
    tool = _lan_find_tool()
    if tool is None:
        fm.notify("Install miniserve or python3 to serve files", bad=True)
        return None
    ip = _lan_ip()
    if ip is None:
        fm.notify("No LAN address found — not serving", bad=True)
        return None
    return tool, ip, port


class lan_serve(Command):
    """:lan_serve [port]  (<Space>ll)

    Serve the current directory over HTTP on the LAN interface only (not
    0.0.0.0).  No authentication — anyone on the LAN can read it while it
    runs.  Uses miniserve if available, falls back to python -m http.server.
    Default port: 8080. Runs in background; kill with <Space>lk.
    """

    def execute(self):
        pre = _lan_preflight(self.fm, self)
        if pre is None:
            return
        tool, ip, port = pre
        cwd = self.fm.thisdir.path
        proc = _lan_start(self.fm, _lan_server_cmd(tool, ip, port, cwd))
        if proc is None:
            return
        self.fm.notify("Serving {} on http://{}:{}  [{}]  PID {}".format(
            os.path.basename(cwd), ip, port, tool[0], proc.pid))


class lan_serve_file(Command):
    """:lan_serve_file [port]  (<Space>lf)

    Serve only the current file over HTTP on the LAN interface.
    miniserve serves the file directly; the python fallback serves a private
    temp dir holding a single symlink to it (removed by <Space>lk).
    Default port: 8080.
    """

    def execute(self):
        f = self.fm.thisfile
        if f is None or f.is_directory:
            self.fm.notify("No file under cursor", bad=True)
            return
        pre = _lan_preflight(self.fm, self)
        if pre is None:
            return
        tool, ip, port = pre

        tmpdir = None
        if tool[0] == 'miniserve':
            target = f.path
        else:
            tmpdir = tempfile.mkdtemp(prefix='ranger-lan-')
            os.symlink(os.path.abspath(f.path), os.path.join(tmpdir, f.basename))
            target = tmpdir

        proc = _lan_start(self.fm, _lan_server_cmd(tool, ip, port, target), tmpdir)
        if proc is None:
            return
        self.fm.notify("Serving {} on http://{}:{}/{}  PID {}".format(
            f.basename, ip, port, quote(f.basename), proc.pid))


class lan_qr(Command):
    """:lan_qr [port]  (<Space>lq)

    Send the current file via qrcp — prints a QR code so phones can pull it.
    Requires: qrcp.
    """

    def execute(self):
        if not require_tool(self.fm, 'qrcp', "Install qrcp for QR-code file transfer"):
            return

        f = self.fm.thisfile
        if f is None:
            self.fm.notify("No file under cursor", bad=True)
            return

        port = _parse_port(self.fm, self.rest(1))
        if port is None:
            return
        self.fm.run(['qrcp', '--port', str(port), 'send', '--', f.path])


class lan_kill(Command):
    """:lan_kill  (<Space>lk)

    Kill the background HTTP server started by lan_serve / lan_serve_file.
    """

    def execute(self):
        pid, tmpdir = _lan_read_state()
        if pid is None:
            self.fm.notify("No server PID found", bad=True)
            return

        if not _lan_pid_alive(pid):
            _lan_cleanup(tmpdir)
            self.fm.notify("Server (PID {}) already dead".format(pid), bad=True)
            return

        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as e:
            self.fm.notify("Could not kill PID {}: {}".format(pid, e), bad=True)
            return
        _lan_cleanup(tmpdir)
        self.fm.notify("Stopped server (PID {})".format(pid))
