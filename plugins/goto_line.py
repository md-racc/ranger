# Intercept bare numeric console input and jump to that line,
# replicating vim's :32 behaviour.

import ranger.gui.widgets.console as _console

_orig_execute = _console.Console.execute


def _execute(self):
    cmd = self.line.strip()
    if cmd.isdigit():
        # :32 means the 32nd entry; fm.move(to=…) is 0-based.
        self.fm.move(to=max(0, int(cmd) - 1))
        self.close()
        return
    _orig_execute(self)


_console.Console.execute = _execute
