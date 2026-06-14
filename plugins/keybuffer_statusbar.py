"""
Move the keybuffer display from the titlebar (top right) to the
statusbar, drawn just after the mtime (right edge of the left part),
so it floats in the gap between file info and the free-space/item-count
stats on the right.

Done by patching _calc_bar to record bar.left.sumsize() on self after
it builds the Bar object, then using that offset in the draw overlay.
"""
import ranger.gui.widgets.titlebar as _titlebar_mod
import ranger.gui.widgets.statusbar as _statusbar_mod
from ranger.gui.bar import Bar as _Bar

_TitleBar = _titlebar_mod.TitleBar
_StatusBar = _statusbar_mod.StatusBar

_orig_statusbar_draw = _StatusBar.draw


def _titlebar_right(self, bar):
    """Suppress keybuffer in titlebar; keep tab indicators."""
    self.old_keybuffer = str(self.fm.ui.keybuffer)
    if len(self.fm.tabs) > 1:
        for tabname in self.fm.get_tab_list():
            tabtext = self._get_tab_text(tabname)
            clr = 'good' if tabname == self.fm.current_tab else 'bad'
            bar.addright(tabtext, 'tab', clr, fixed=True)


def _calc_bar_recording(self):
    """_calc_bar replacement that also records bar.left.sumsize() on self."""
    bar = _Bar('in_statusbar')
    self._get_left_part(bar)
    self._get_right_part(bar)
    bar.shrink_by_removing(self.wid)
    self._left_end = bar.left.sumsize()
    self._right_size = bar.right.sumsize()
    self.result = bar.combine()


def _statusbar_draw(self):
    import curses
    kbuf = str(self.fm.ui.keybuffer)
    # Force full redraw when keybuffer changes so old text is erased cleanly.
    if getattr(self, '_kbuf_prev', None) != kbuf:
        self._kbuf_prev = kbuf
        self.need_redraw = True
    _orig_statusbar_draw(self)
    # Don't overlay during hint or message display — those own the full bar.
    if not kbuf or self.hint or self.msg:
        return
    text = '  [' + kbuf + ']'
    x = getattr(self, '_left_end', 0)
    # Only use the free gap between the left and right parts, so a narrow
    # window doesn't get the right-hand stats overwritten.
    room = self.wid - x - getattr(self, '_right_size', 0)
    if room < 4:
        return
    try:
        self.addnstr(0, x, text, room)
    except curses.error:
        pass


_TitleBar._get_right_part = _titlebar_right
_StatusBar._calc_bar = _calc_bar_recording
_StatusBar.draw = _statusbar_draw
