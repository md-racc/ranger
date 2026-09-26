"""Minimal stand-ins for ranger's FM so picker commands can run headless."""
import os
from types import SimpleNamespace


class FakeFile(object):
    def __init__(self, path):
        self.path = path
        self.basename = os.path.basename(path)
        self.is_directory = os.path.isdir(path)
        self.marked = False


class FakeConsole(object):
    def __init__(self):
        self.asks = []

    def ask(self, text, callback, choices):
        self.asks.append((text, callback, choices))


class FakeTab(object):
    """history: objects with a .files list (ranger's visited dirs).
    selection: what get_selection() returns (default: nothing)."""

    def __init__(self):
        self.history = []
        self.selection = []

    def get_selection(self):
        return list(self.selection)


class FakeFM(object):
    def __init__(self, cwd, cursor=None):
        self.thisdir = SimpleNamespace(path=cwd)
        self.thisfile = FakeFile(cursor) if cursor else None
        self.thistab = FakeTab()
        self.tabs = {1: self.thistab}
        self.ui = SimpleNamespace(console=FakeConsole())
        self.notes, self.consoles, self.executed, self.moved = [], [], [], []
        self.selected = None
        self.settings = SimpleNamespace(show_hidden=False)
        # Test-only escape hatch: when True, select_file never lands the
        # cursor (simulates '/' or a filtered-out target) so select_folder's
        # cd-and-notify fallback can be exercised.
        self.reject_select = False

    def notify(self, msg, bad=False):
        self.notes.append(msg)

    def open_console(self, text, position=None):
        self.consoles.append(text)

    def execute_console(self, text):
        self.executed.append(text)

    def move(self, **kw):
        self.moved.append(kw)

    def cd(self, path):
        self.thisdir = SimpleNamespace(path=path)

    def select_file(self, path):
        self.selected = path
        if self.reject_select:
            return
        basename = os.path.basename(path)
        if not basename.startswith('.') or self.settings.show_hidden:
            self.thisfile = FakeFile(path)


def snapshot_plugin_patches():
    """Save what plugins/picker_mode.py patches; returns a restore function.
    (Loading it in save/open/multi mode patches ranger globally.)"""
    import ranger.api as api
    import ranger.container.directory as directory
    from ranger.gui.widgets.browsercolumn import BrowserColumn
    saved = [(api, 'hook_init', api.hook_init), (api, 'hook_ready', api.hook_ready),
             (directory, 'accept_file', directory.accept_file),
             (BrowserColumn, '_draw_directory', BrowserColumn.__dict__['_draw_directory']),
             (BrowserColumn, 'click', BrowserColumn.__dict__['click'])]

    def restore():
        for owner, name, value in saved:
            setattr(owner, name, value)
    return restore
