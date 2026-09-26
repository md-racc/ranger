#!/usr/bin/env python3
"""Manual smoke test through the REAL portal (opens a ranger dialog window).

    python tests/portal_smoke.py open|multi|dir|save [suggested-name]

Prints the portal response (0=ok 1=cancelled 2=error), the chosen URIs and
the total time. Drive the ranger window by hand.
"""
import sys
import time

import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib  # noqa: E402

mode = sys.argv[1] if len(sys.argv) > 1 else 'open'
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
token = 'smoke{}'.format(GLib.random_int())
sender = bus.get_unique_name()[1:].replace('.', '_')
handle = '/org/freedesktop/portal/desktop/request/{}/{}'.format(sender, token)
loop = GLib.MainLoop()
start = time.monotonic()


def on_response(_conn, _sender, _path, _iface, _signal, params):
    code, results = params.unpack()
    print('response', code, '(0=ok 1=cancelled 2=error)')
    for uri in results.get('uris', []):
        print('  ', uri)
    print('elapsed {:.1f}s'.format(time.monotonic() - start))
    loop.quit()


bus.signal_subscribe('org.freedesktop.portal.Desktop', 'org.freedesktop.portal.Request',
                     'Response', handle, None, Gio.DBusSignalFlags.NONE, on_response)
opts = {'handle_token': GLib.Variant('s', token)}
if mode == 'save':
    method = 'SaveFile'
    opts['current_name'] = GLib.Variant('s', sys.argv[2] if len(sys.argv) > 2 else 'smoke-test.txt')
else:
    method = 'OpenFile'
    opts['multiple'] = GLib.Variant('b', mode == 'multi')
    opts['directory'] = GLib.Variant('b', mode == 'dir')
bus.call_sync('org.freedesktop.portal.Desktop', '/org/freedesktop/portal/desktop',
              'org.freedesktop.portal.FileChooser', method,
              GLib.Variant('(ssa{sv})', ('', 'smoke test', opts)),
              GLib.VariantType('(o)'), Gio.DBusCallFlags.NONE, -1, None)
loop.run()
