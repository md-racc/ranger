"""File-picker mode UI (no-op outside a portal file dialog).

- Banner: a permanent tag, after user@host at the left of the title bar,
  naming the dialog mode and what <CR> does, e.g. ' SAVE ▸ report.pdf ' +
  '⏎ save · q cancel · ^L path · gD ~/Downloads'. Rebuilt on every title-bar
  redraw so it fits the width: the mode tag and the confirm/cancel hint come
  first, a long save name is shortened with '…', extras are added only when
  there is room, and user@host is dropped if even that doesn't fit. With more
  than one tab open, `q` only closes a tab, so the hint says 'Q cancel'.
- Default "open file" actions (l, <Right>, rifle, `r` with no program):
    save   open the pick_save console instead (never writes without the
           overwrite prompt)
    multi  send marks + selection + the highlighted file, folders flattened
           (same as ⏎ / pick_selection)
    open   pick the highlighted file
    dir    nothing; says it's a folder dialog (never launches an app)
  An explicitly named program (`r` → vim) is launched and never picks.

Mode comes from cmds.picker.picker_mode() (RANGER_PICKER from the custom
portal wrapper). Only functions are imported from cmds.picker: ranger
registers every Command class found in a plugin module.
"""
from __future__ import (absolute_import, division, print_function)

import ranger.core.actions as _actions
import ranger.gui.widgets.titlebar as _titlebar
from ranger.gui.bar import Bar as _Bar
from ranger.ext.widestring import WideString as _WideString

from cmds.picker import (picker_mode as _picker_mode, placeholder as _placeholder,
                         suggested_name as _suggested_name, prompt_save as _prompt_save,
                         pick_files as _pick_files, split_ext as _split_ext,
                         _finish)

# mode → (tag, short tag, ⏎ hint, optional hints in priority order). Keys
# must match rc.conf: <C-l> pick_location, gD cd ~/Downloads, h, `,` mark.
_BANNERS = {
    'open':  ('OPEN', 'OPEN', '⏎ pick', ()),
    'multi': ('OPEN MULTI', 'MULTI', '⏎ send', (', mark',)),
    'dir':   ('PICK FOLDER', 'FOLDER', '⏎ pick', ('h⏎ pick current',)),
    'save':  ('SAVE', 'SAVE', '⏎ save here', ('l replace',)),
}
_EXTRAS = ('^L path', 'gD ~/Downloads')
_SEP = ' · '
_ELLIPSIS = '…'
_MIN_NAME = 8          # shorter than this, a shortened save name is useless


def _width(text):
    return len(_WideString(text))


def _shorten(name, room):
    """name cut to `room` columns with an ellipsis, keeping the extension."""
    if _width(name) <= room:
        return name
    stem, ext = _split_ext(name)
    if room < _width(ext) + 3:          # no room for 2 stem chars + …
        stem, ext = name, ''
    keep = room - _width(ext) - 1
    if keep < 1:
        return ''
    return str(_WideString(stem)[:keep]) + _ELLIPSIS + ext


def _build(tag, hints, pad=True):
    if pad:
        return ' ' + tag + ' ', ' ' + _SEP.join(hints) + '  '
    return ' ' + tag, ' ' + _SEP.join(hints) + ' '


def _size(parts):
    return _width(parts[0]) + _width(parts[1])


def banner_parts(mode, width=None, tabs=1, name=None, extras=True, reserve=0):
    """(tag, hint) strings for the title bar, or None outside a picker.

    width: columns for the banner (None = unlimited). In priority order:
    the mode tag and '⏎ … · q cancel' (always; padding and then the tag are
    shortened when tight), the save name (cut with '…'), and, if `extras`,
    optional hints while they fit in width - reserve.
    """
    if mode not in _BANNERS:
        return None
    tag, short_tag, enter, optional = _BANNERS[mode]
    hints = [enter, 'q cancel' if tabs <= 1 else 'Q cancel']
    limit = float('inf') if width is None else width

    if _size(_build(tag, hints)) > limit:              # very narrow
        for parts in (_build(tag, hints, pad=False), _build(short_tag, hints, pad=False)):
            if _size(parts) <= limit:
                return parts
        return parts

    if mode == 'save':
        if name is None:
            name = _suggested_name(_placeholder())
        room = limit - _size(_build(tag + ' ▸ ', hints))
        short = _shorten(name, room) if width is not None else name
        if short == name or _width(short) >= min(_MIN_NAME, _width(name)):
            tag = tag + ' ▸ ' + short
        if short != name:
            return _build(tag, hints)

    if extras:
        for extra in list(optional) + list(_EXTRAS):
            if extra == ', mark':
                trial = [extra] + hints
            elif extra in ('h⏎ pick current', 'l replace'):
                trial = hints[:1] + [extra] + hints[1:]
            else:
                trial = hints + [extra]
            if _size(_build(tag, trial)) > limit - reserve:
                break
            hints = trial
    return _build(tag, hints)


def _right_size(widget):
    """Columns the title bar's right part (keybuffer, tabs) will take."""
    try:
        scratch = _Bar('in_titlebar')
        _titlebar.TitleBar._get_right_part(widget, scratch)
        return scratch.right.sumsize()
    except Exception:  # pylint: disable=broad-except
        return 2


def _tab_count(widget):
    try:
        return len(widget.fm.tabs)
    except Exception:  # pylint: disable=broad-except
        return 1


def install():
    mode = _picker_mode()
    if mode is None:
        return
    orig_left = _titlebar.TitleBar._get_left_part

    def _get_left_part(self, bar):
        orig_left(self, bar)
        host = 4 if self.settings.hostname_in_titlebar else 0
        host_w = sum(len(p) for p in bar.left[:host])
        path_w = min(sum(len(p) if p.fixed else p.min_size for p in bar.left[host:]), 8)
        wid = getattr(self, 'wid', None)
        tabs = _tab_count(self)
        name = None
        if wid is None:
            tag, hint = banner_parts(mode, tabs=tabs, name=name)
        else:
            avail = wid - _right_size(self)
            # essentials (incl. the whole save name) beat user@host
            needed = banner_parts(mode, tabs=tabs, name=name, extras=False)
            if host and _width(needed[0] + needed[1]) + host_w > avail:
                del bar.left[:host]            # the banner matters more than user@host
                host = host_w = 0
            # extras leave a little room for the path (dropped if it can't fit)
            tag, hint = banner_parts(mode, avail - host_w, tabs=tabs, name=name,
                                     reserve=path_w)
        bar.add(tag, 'tab', 'good', fixed=True)
        bar.add(hint, 'tab', fixed=True)
        banner = bar.left[-2:]
        del bar.left[-2:]
        bar.left[host:host] = banner

    _titlebar.TitleBar._get_left_part = _get_left_part

    orig_exec = _actions.Actions.execute_file

    def execute_file(self, files, **kw):
        if kw.get('mode', 0) != 0 or 'label' in kw or kw.get('app'):
            if kw.get('app') and 'label' not in kw:
                # named program: launch it. (ranger's own chooser code would
                # pick the file instead whenever 'label' is absent.)
                kw = dict(kw)
                kw['label'] = kw.pop('app')
            return orig_exec(self, files, **kw)
        files = list(files) if isinstance(files, (list, tuple, set)) else [files]
        current = self.thisfile
        if mode == 'save':
            _prompt_save(self, files[0] if files else None)
        elif mode == 'dir':
            self.notify('Folder dialog: pick a folder with ⏎ (files can\'t be opened here)')
        elif mode == 'multi':
            _pick_files(self, current.path if current is not None
                        and not current.is_directory else None)
        else:
            target = current if current is not None else (files[0] if files else None)
            if target is not None:
                _finish(self, [target.path])
        return None

    _actions.Actions.execute_file = execute_file


install()
