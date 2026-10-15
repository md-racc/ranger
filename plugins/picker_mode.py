"""File-picker mode UI (no-op outside a portal file dialog).

- Banner: a permanent tag, after user@host at the left of the title bar,
  naming the dialog mode and what <CR> does, e.g. ' SAVE ▸ report.pdf ' +
  '⏎ save · q cancel · ^L path · gD ~/Downloads'. Rebuilt on every title-bar
  redraw so it fits the width: the mode tag and the confirm/cancel hint come
  first, a long save name is shortened with '…', extras are added only when
  there is room, and user@host is dropped if even that doesn't fit. With more
  than one tab open, `q` only closes a tab, so the hint says 'Q cancel'.
- Save mode: the portal's placeholder is hidden from every listing and a
  virtual "ghost" row at the top of the main column shows the file in the
  folder you're in ('+ report.pdf  ⏎ saves here'); it follows you as you
  move. ⏎ saves there. Nothing on disk moves until pick_save.
- Open/multi: start sorted by mtime, cursor on the newest file.
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
                         save_here as _save_here, _finish)

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


def _live_name(fm):
    """Save mode: the name ⏎ would save as in the current folder."""
    try:
        return _save_here(fm.thisdir.path, _placeholder())[0]
    except Exception:  # pylint: disable=broad-except
        return None


def ghost_parts(fm_cwd, width, indent=0, title=None):
    """Save mode: [(text, role)] for the ghost row in folder fm_cwd, cut to
    `width` columns. role: 'mark' (the + in the line-number gutter), 'name',
    'hint', 'bad'. The hint is dropped first when the row is too narrow.
    title(name) → the name as the linemode shows it (e.g. with a devicon)."""
    name, state, clash = _save_here(fm_cwd, _placeholder())
    if title is not None:
        name = title(name)
    if state == 'readonly':
        hints, role = ('  ✗ read-only folder', ' ✗'), 'bad'
    elif state == 'taken':
        hints, role = ('  · {} exists — l on it to replace'.format(clash),
                       '  · name taken, l to replace', '  · taken'), 'hint'
    else:
        hints, role = ('  ⏎ saves here',), 'hint'
    mark = ('+'.rjust(indent - 1) + ' ') if indent > 1 else ''
    parts = [(mark, 'mark'), (name, 'name')]
    used = _width(mark + name)
    for hint in hints:                    # longest that fits
        if used + _width(hint) <= width:
            parts.append((hint, role))
            used += _width(hint)
            break
    if used > width:
        name = _shorten(name, max(width - _width(mark), 0))
        parts = [(mark, 'mark'), (name, 'name')]
        used = _width(mark + name)
    parts.append((' ' * max(width - used, 0), 'hint'))
    return [(t, r) for t, r in parts if t]


def _install_save_ghost():
    """Save mode: hide the portal's placeholder from every listing and draw
    a virtual row for it at the top of the main column, in whatever folder
    you are in. Nothing on disk moves until pick_save."""
    import curses
    import os
    from types import SimpleNamespace
    import ranger.container.directory as _directory
    from ranger.gui.widgets.browsercolumn import BrowserColumn

    ph = _placeholder()
    if ph:
        orig_accept = _directory.accept_file

        def accept_file(fobj, filters):
            if fobj.path == ph:
                return False
            return orig_accept(fobj, filters)
        _directory.accept_file = accept_file

    orig_draw = BrowserColumn._draw_directory
    orig_click = BrowserColumn.click

    def _ghost_on(col):
        return col.main_column and col.hei >= 2 and col.target is not None \
            and getattr(col.target, 'accessible', False)

    def _draw_directory(self):
        if not _ghost_on(self):
            return orig_draw(self)
        full_win, full_hei = self.win, self.hei
        try:
            sub = full_win.derwin(full_hei - 1, self.wid, 1, 0)
        except curses.error:
            return orig_draw(self)
        self.win, self.hei = sub, full_hei - 1
        try:
            orig_draw(self)
        finally:
            self.win, self.hei = full_win, full_hei
        indent = 0
        if self.settings.line_numbers != 'false':
            indent = len(str(self.target.scroll_begin + self.hei - 1)) + 1
        indent += 1                                   # tag-marker column
        scheme = self.settings.colorscheme
        attrs = {
            'mark': scheme.get_attr('in_browser', 'main_column', 'media'),
            'name': scheme.get_attr('in_browser', 'main_column', 'marked'),
            'hint': scheme.get_attr('in_browser', 'main_column', 'media'),
            'bad': scheme.get_attr('in_browser', 'main_column', 'link', 'bad'),
        }
        try:
            parts = ghost_parts(self.target.path, self.wid, indent, _titler(self.target))
        except OSError:
            return None
        self.execute_curses_batch(0, [[t, attrs[r]] for t, r in parts])
        self.color_reset()
        return None

    def _titler(target):
        """The folder's linemode filetitle applied to a would-be file name."""
        sample = next(iter(target.files or ()), None)
        if sample is None:
            return None
        try:
            lm = sample.linemode_dict[sample.linemode]
        except (AttributeError, KeyError):
            return None

        def title(name):
            ext = name.rsplit('.', 1)[1].lower() if '.' in name[1:] else ''
            fake = SimpleNamespace(is_directory=False, relative_path=name, basename=name,
                                   extension=ext, path=os.path.join(target.path, name))
            try:
                return str(lm.filetitle(fake, None))
            except Exception:  # pylint: disable=broad-except
                return name
        return title

    def click(self, event):
        if not _ghost_on(self) or not os.path.isdir(self.target.path):
            return orig_click(self, event)
        if event.y - self.y == 0:
            if event.pressed(1) or event.pressed(3):
                _prompt_save(self.fm)
                return True
            return orig_click(self, event)
        self.y += 1                       # rows below the ghost are shifted
        try:
            return orig_click(self, event)
        finally:
            self.y -= 1

    BrowserColumn._draw_directory = _draw_directory
    BrowserColumn.click = click


def _install_newest_first():
    """Open/multi: start sorted by mtime with the cursor on the newest file
    (usually the one just downloaded or exported). Set before the other
    hook_init plugins bind 'setopt', so it's silent; this ranger only."""
    import ranger.api as _api
    orig_init = _api.hook_init

    def hook_init(fm):
        fm.settings.sort = 'mtime'
        fm.settings.sort_reverse = False
        return orig_init(fm)

    orig_ready = _api.hook_ready

    def hook_ready(fm):
        ret = orig_ready(fm)
        try:
            cwd = fm.thisdir
            cwd.load_content(schedule=False)
            cwd.sort()
            newest = next((f for f in cwd.files if not f.is_directory), None)
            if newest is not None:
                cwd.move_to_obj(newest)
                fm.thisfile = cwd.pointed_obj
        except Exception:  # pylint: disable=broad-except
            pass
        return ret

    _api.hook_init = hook_init
    _api.hook_ready = hook_ready


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
        name = _live_name(self.fm) if mode == 'save' else None
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

    if mode == 'save':
        _install_save_ghost()
    elif mode in ('open', 'multi'):
        _install_newest_first()


install()
