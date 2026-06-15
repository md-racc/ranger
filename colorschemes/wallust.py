# Ranger colorscheme — ANSI terminal colors 0–15 only.
# Follows the terminal's palette (whatever wallust or any theme sets there);
# no hardcoded 256-color indices.
#
# Slot mapping (mirrors quiet.py intent, but palette-driven):
#   black  (0)  = color0  — background
#   red    (1)  = color1  — errors, broken links, cut
#   green  (2)  = color2  — good permissions
#   yellow (3)  = color3  — marked files, progress bar
#   blue   (4)  = color4  — directories (the wallust accent slot)
#   magenta(5)  = color5  — (unused, available)
#   cyan   (6)  = color6  — symlinks, copied
#   white  (7)  = color7  — default foreground
#   8           = color8  — muted / dim (bright-black)
#
# Optional cache: ~/.cache/wallust/ranger-colors.py (rendered by wallust from
# contrib/wallust/ranger-colors.py).  COLORS maps slot -> "#rrggbb" and is
# applied with curses.init_color when the terminal allows it; ROLES picks the
# slot for directories / links+copied / marked+progress / active tab, plus an
# optional "fill" hex for the cursor bar.  No cache (no wallust installed) =
# the defaults below, i.e. the mapping above on the terminal's own palette.

import os as _os
import curses as _curses
import signal as _signal
from ranger.gui.color import *
from ranger.colorschemes.default import Default

_WALLUST_CACHE = _os.path.expanduser("~/.cache/wallust/ranger-colors.py")


def _sigusr2(_signum, _frame):
    """A theme switcher sends SIGUSR2 after re-rendering the cache (see
    contrib/wallust/ranger-reload). ColorScheme.get and the per-file
    display_data are cached, so flagging a reinit alone would only reach
    rows ranger hasn't drawn yet: drop both caches and repaint.
    Python runs this between bytecodes on the main thread, so touching
    curses here can't interrupt a half-finished curses call."""
    Scheme._needs_reinit = True
    from ranger.gui.colorscheme import ColorScheme
    ColorScheme.get._cache.clear()        # pylint: disable=no-member,protected-access
    ColorScheme.get_attr._cache.clear()   # pylint: disable=no-member,protected-access
    try:
        from ranger.core.shared import FileManagerAware
        fm = FileManagerAware.fm
        for directory in fm.directories.values():
            for fobj in directory.files_all or ():
                fobj.display_data = {}
        fm.ui.redraw_window()
    except Exception:  # pylint: disable=broad-except
        pass  # signal arrived before the UI exists; the reinit flag covers it

_signal.signal(_signal.SIGUSR2, _sigusr2)


def _hex_to_curses(h):
    h = h.lstrip('#')
    return (int(h[0:2], 16) * 1000 // 255,
            int(h[2:4], 16) * 1000 // 255,
            int(h[4:6], 16) * 1000 // 255)


_ROLE_DEFAULTS = {"dir": blue, "link": cyan, "marked": yellow, "tab": white, "fill": None}
# role "fill" (hex) is drawn with two spare curses colours beyond the 16-colour palette
_FILL_BG, _FILL_FG = 16, 17


class Scheme(Default):
    _needs_reinit = True  # load on first use
    progress_bar_color = yellow  # color3
    roles = dict(_ROLE_DEFAULTS)

    def _reinit(self):
        ns = {}
        try:
            with open(_WALLUST_CACHE) as f:
                exec(f.read(), ns)
        except Exception:
            return
        # None = unset (the template renders non-slot values as None)
        roles = {k: v for k, v in ns.get("ROLES", {}).items() if v is not None}
        Scheme.roles = {**_ROLE_DEFAULTS, **roles}
        Scheme.progress_bar_color = Scheme.roles["marked"]
        if not _curses.can_change_color():
            return
        try:
            for idx, hex_val in ns.get("COLORS", {}).items():
                _curses.init_color(idx, *_hex_to_curses(hex_val))
            if Scheme.roles["fill"] and _curses.COLORS > _FILL_FG:
                _curses.init_color(_FILL_BG, *_hex_to_curses(Scheme.roles["fill"]))
                _curses.init_color(_FILL_FG, 0, 0, 0)
            else:
                Scheme.roles["fill"] = None
        except Exception:
            Scheme.roles["fill"] = None

    def use(self, context):
        if Scheme._needs_reinit:
            self._reinit()
            Scheme._needs_reinit = False

        fg, bg, attr = Default.use(self, context)
        r = Scheme.roles

        # ── File browser ──────────────────────────────────────────────────────
        if context.in_browser:
            fg   = white    # color7
            bg   = -1       # terminal default — respects kitty transparency
            attr = normal

            if context.directory:
                fg   = r["dir"]     # default color4 — wallust accent
                attr = bold
                if context.empty:
                    fg = 8      # color8 — muted

            if context.link:
                fg   = r["link"]    # default color6
                attr = normal
                if context.bad:
                    fg   = red  # color1
                    attr = bold

            if context.media:
                fg   = 8        # color8 — muted so media doesn't compete
                attr = normal

            if context.container:
                fg   = 8
                attr = bold

            if context.document:
                fg   = white
                attr = normal

            if context.executable and not context.directory:
                attr = bold

            # Clipboard tints
            if context.cut:
                fg   = red
                attr = bold
            elif context.copied:
                fg   = r["link"]
                attr = normal

            # Marked — reverse amber block (mirrors quiet.py Visual)
            if context.marked:
                fg   = r["marked"]  # default color3
                bg   = -1
                attr = reverse | bold

            # Cursor row — reverse swaps the row's fg into the bg, always visible
            if context.selected:
                attr = attr | reverse | bold
                if r["fill"]:           # electric fill bar, black text
                    fg, bg, attr = _FILL_FG, _FILL_BG, (attr & ~reverse) | bold
                if context.marked:
                    fg   = black
                    bg   = r["marked"]
                    attr = bold

            if context.tagged and not context.selected:
                attr = attr | underline

        # ── Title bar ─────────────────────────────────────────────────────────
        elif context.in_titlebar:
            fg   = white
            bg   = black
            attr = normal

            if context.hostname:
                attr = bold
            elif context.directory:
                attr = bold
            elif context.tab:
                if context.good:    # active tab
                    fg   = black
                    bg   = r["tab"]
                    attr = bold
                else:               # inactive tab
                    fg   = 8
                    bg   = black
                    attr = normal
            elif context.link:
                fg = r["link"]

        # ── Status bar ────────────────────────────────────────────────────────
        elif context.in_statusbar:
            fg   = white
            bg   = default
            attr = normal

            if context.permissions:
                if context.good:
                    fg   = green    # color2
                    attr = normal
                elif context.bad:
                    fg   = red
                    attr = bold
                else:
                    fg   = 8        # neutral perms
            if context.marked:
                fg   = r["marked"]
                attr = bold
            if context.message:
                if context.bad:
                    fg   = red
                    attr = bold
                else:
                    fg   = white
            if context.loaded:
                fg   = r["marked"]
                attr = bold

        return fg, bg, attr
