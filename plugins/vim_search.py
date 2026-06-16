"""
Patch Console.press so that <C-n>/<C-p> navigate search matches when the
active console command is vim_search, rather than cycling command history.

Key codes: C-n = 14, C-p = 16.
"""

import ranger.gui.widgets.console as _console

_orig_press = _console.Console.press


def _patched_press(self, key):
    if key in (14, 16):
        line = getattr(self, 'line', '')
        if line.lstrip().startswith('vim_search'):
            self.fm.search_next(forward=(key == 14))
            return
    _orig_press(self, key)


_console.Console.press = _patched_press
