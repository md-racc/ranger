"""
Patch ranger's _draw_hints to:
  1. Show descriptive labels for every submap key.
  2. Confine drawing to the left+centre columns so the preview image
     is never cleared or overwritten.

Two label tables work together:

  _SUBMAP_LABELS  – fires when the collapse threshold is exceeded and
                    multiple bindings share the same first character.
                    Key: tuple of pressed keycodes.  Value: {char: label}.

  _KEY_LABELS     – fires for every binding unconditionally, replacing
                    the raw command string with a friendly name.
                    Key: (context_tuple, key_string).  Value: label.

Most submaps have all-unique first characters so they never collapse;
those are handled entirely by _KEY_LABELS.
_SUBMAP_LABELS is only needed where grouped children collapse into one
representative entry (e.g. <Space> top-level, <Space>a archive).
"""

import ranger.gui.widgets.view_base as _view_base

# ---------------------------------------------------------------------------
# _SUBMAP_LABELS
# Needed only when multiple bindings SHARE a first character and the total
# hint count exceeds hint_collapse_threshold (default 10).
# ---------------------------------------------------------------------------
_SUBMAP_LABELS = {
    # <Space> top-level — every letter groups many children, all collapse.
    (32,): {
        'a': 'Archive',
        'b': 'Bin / trash',
        'd': 'Disk',
        'e': 'Encrypt',
        'f': 'Find',
        'h': 'Hash',
        'l': 'LAN serve',
        'n': 'Next search',
        'p': 'Preview',
        's': 'SSH',
        'v': 'Transform',
        'y': 'Clipboard',
    },
    # <Space>a — 'e' and 'c' each have 6-7 children that collapse.
    (32, ord('a')): {
        'e': 'Extract',
        'c': 'Compress',
    },
    # <Space>v — four domain groups, each with multiple children.
    (32, ord('v')): {
        'i': 'Image',
        'v': 'Video',
        'p': 'PDF',
        'n': 'Name / organize',
    },
    # p — only 'h' collapses (phl + pht share first char 'h').
    (ord('p'),): {
        'h': 'Hardlink',
    },
}

# ---------------------------------------------------------------------------
# _KEY_LABELS
# Applied unconditionally: replaces raw command strings with friendly names.
# Organised by context (the tuple of keycodes already pressed).
# ---------------------------------------------------------------------------
_KEY_LABELS = {

    # ── <Space> — singles that never collapse ────────────────────────────────
    ((32,), 'X'): 'Delete',
    ((32,), 'q'): 'Quit',
    ((32,), 'z'): 'Zoxide jump',

    # ── <Space>b  trash / bin ────────────────────────────────────────────────
    ((32, ord('b')), 'l'): 'List trash',
    ((32, ord('b')), 'r'): 'Restore from trash',
    ((32, ord('b')), 'e'): 'Empty trash',

    # ── <Space>h  checksums / hashes ────────────────────────────────────────
    ((32, ord('h')), 's'): 'SHA-256 of selection',
    ((32, ord('h')), 'v'): 'Verify checksum file',
    ((32, ord('h')), 'c'): 'Copy SHA-256 to clipboard',

    # ── <Space>e  encrypt / decrypt / veracrypt ──────────────────────────────
    ((32, ord('e')), 'e'): 'Encrypt (age / gpg)',
    ((32, ord('e')), 'd'): 'Decrypt (.age / .gpg)',

    # ── <Space>f  find / fzf ─────────────────────────────────────────────────
    ((32, ord('f')), 'f'): 'Fuzzy find (cwd)',
    ((32, ord('f')), 'h'): 'Fuzzy find (home)',
    ((32, ord('f')), 'r'): 'Recent dirs',
    ((32, ord('f')), 'z'): 'Zoxide jump',
    ((32, ord('f')), '/'): 'Find',
    ((32, ord('f')), 't'): 'Travel',
    ((32, ord('f')), 'c'): 'Jump to dir',

    # ── <Space>p  preview ────────────────────────────────────────────────────
    ((32, ord('p')), 'p'): 'Toggle preview',
    ((32, ord('p')), 's'): 'Peek (one file)',
    ((32, ord('p')), 'a'): 'Render all videos',
    ((32, ord('p')), 'c'): 'Clear cache',

    # ── <Space>d  disk usage ─────────────────────────────────────────────────
    ((32, ord('d')), 'c'): 'Cumulative size',
    ((32, ord('d')), 'u'): 'du (here)',
    ((32, ord('d')), 'U'): 'dust / du (here)',
    ((32, ord('d')), 'n'): 'ncdu (here)',
    ((32, ord('d')), '/'): 'ncdu /',
    ((32, ord('d')), '~'): 'ncdu ~',

    # ── <Space>a  archive — non-collapsing singles ───────────────────────────
    ((32, ord('a')), 'l'): 'List archive',
    ((32, ord('a')), 't'): 'Test archive',
    ((32, ord('a')), 'k'): 'Cancel extract',

    # ── <Space>ae  extract ───────────────────────────────────────────────────
    ((32, ord('a'), ord('e')), 'd'): 'Extract',
    ((32, ord('a'), ord('e')), 'h'): 'Extract here',
    ((32, ord('a'), ord('e')), 's'): 'Smart extract',
    ((32, ord('a'), ord('e')), 'f'): 'Flatten extract',
    ((32, ord('a'), ord('e')), 'D'): 'Extract to...',
    ((32, ord('a'), ord('e')), 'o'): 'Extract & open',

    # ── <Space>ac  compress (aggregate) ─────────────────────────────────────
    ((32, ord('a'), ord('c')), 'z'): '.tar.gz',
    ((32, ord('a'), ord('c')), 'x'): '.tar.xz',
    ((32, ord('a'), ord('c')), 'Z'): '.tar.zst',
    ((32, ord('a'), ord('c')), 'b'): '.tar.bz2',
    ((32, ord('a'), ord('c')), 'p'): '.zip',
    ((32, ord('a'), ord('c')), '7'): '.7z',

    # ── <Space>s  SSH ────────────────────────────────────────────────────────
    ((32, ord('s')), 's'): 'Mount SSH',
    ((32, ord('s')), 'S'): 'Shell via SSH',
    ((32, ord('s')), 'u'): 'Unmount SSH',

    # ── <Space>l  LAN serve ──────────────────────────────────────────────────
    ((32, ord('l')), 'l'): 'Serve cwd',
    ((32, ord('l')), 'f'): 'Serve file',
    ((32, ord('l')), 'q'): 'QR code (qrcp)',
    ((32, ord('l')), 'k'): 'Kill server',

    # ── <Space>vi  image ops ─────────────────────────────────────────────────
    ((32, ord('v'), ord('i')), 'r'): 'Resize',
    ((32, ord('v'), ord('i')), 'c'): 'Convert format',
    ((32, ord('v'), ord('i')), 's'): 'Strip EXIF',
    ((32, ord('v'), ord('i')), 'o'): 'Optimize',

    # ── <Space>vv  video / audio ops ─────────────────────────────────────────
    ((32, ord('v'), ord('v')), 't'): 'Transcode',
    ((32, ord('v'), ord('v')), 'a'): 'Extract audio',
    ((32, ord('v'), ord('v')), 'x'): 'Trim',
    ((32, ord('v'), ord('v')), 'g'): 'Make GIF',
    ((32, ord('v'), ord('v')), 's'): 'Snapshot',

    # ── <Space>vp  PDF ops ───────────────────────────────────────────────────
    ((32, ord('v'), ord('p')), 'm'): 'Merge',
    ((32, ord('v'), ord('p')), 's'): 'Split pages',
    ((32, ord('v'), ord('p')), 'r'): 'Rotate',
    ((32, ord('v'), ord('p')), 'c'): 'Compress',
    ((32, ord('v'), ord('p')), 'o'): 'OCR',

    # ── <Space>vn  name / organize ───────────────────────────────────────────
    ((32, ord('v'), ord('n')), 'e'): 'Rename by EXIF date',
    ((32, ord('v'), ord('n')), 'm'): 'Rename by mtime',
    ((32, ord('v'), ord('n')), 's'): 'Sort into YYYY/MM',

    # ── <Space>y  clipboard ──────────────────────────────────────────────────
    ((32, ord('y')), 'y'): 'Copy file contents to clipboard',
    ((32, ord('y')), 'n'): 'Copy filename',
    ((32, ord('y')), 'p'): 'Copy absolute path',
    ((32, ord('y')), 'e'): 'Copy filename without extension',
    ((32, ord('y')), 'd'): 'Copy directory path',
    ((32, ord('y')), 'v'): 'Paste clipboard to file',

    # ── <Space>n  next search ────────────────────────────────────────────────
    ((32, ord('n')), 't'): 'Next tagged',
    ((32, ord('n')), 's'): 'Next by size',
    ((32, ord('n')), 'i'): 'Next by mime',
    ((32, ord('n')), 'c'): 'Next by ctime',
    ((32, ord('n')), 'm'): 'Next by mtime',
    ((32, ord('n')), 'a'): 'Next by atime',

    # ── .  filter stack ──────────────────────────────────────────────────────
    ((ord('.'),), 'd'): 'Dirs',
    ((ord('.'),), 'f'): 'Files',
    ((ord('.'),), 'l'): 'Links',
    ((ord('.'),), 'm'): 'MIME',
    ((ord('.'),), 'n'): 'Name / regex',
    ((ord('.'),), '#'): 'Hash',
    ((ord('.'),), '"'): 'Duplicates',
    ((ord('.'),), "'"): 'Unique',
    ((ord('.'),), '|'): 'OR',
    ((ord('.'),), '&'): 'AND',
    ((ord('.'),), '!'): 'NOT',
    ((ord('.'),), 'r'): 'Rotate',
    ((ord('.'),), 'c'): 'Clear all',
    ((ord('.'),), '*'): 'Decompose',
    ((ord('.'),), 'p'): 'Pop',
    ((ord('.'),), '.'): 'Show stack',
    ((ord('.'),), 't'): 'Filter by tag',
    ((ord('.'),), 'T'): 'Filter by tag (flat tree)',
    ((ord('.'),), 's'): 'Size  (>10M <500K)',
    ((ord('.'),), 'e'): 'Extension  (py mp4)',
    ((ord('.'),), 'a'): 'Age / mtime  (7 days, >30)',

    # ── g  go to / cd ────────────────────────────────────────────────────────
    ((ord('g'),), 'h'): '~ home',
    ((ord('g'),), 'e'): '/etc',
    ((ord('g'),), 'u'): '/usr',
    ((ord('g'),), 'd'): '/dev',
    ((ord('g'),), 'l'): 'Relative link .',
    ((ord('g'),), 'L'): 'Relative link %f',
    ((ord('g'),), 'o'): '/opt',
    ((ord('g'),), 'v'): '/var',
    ((ord('g'),), 'm'): '/media',
    ((ord('g'),), 'i'): '/run/media',
    ((ord('g'),), 's'): '/srv',
    ((ord('g'),), 'p'): '/tmp',
    ((ord('g'),), 'r'): '/',
    ((ord('g'),), 'R'): 'Ranger dir',
    ((ord('g'),), '/'): '/',
    ((ord('g'),), '?'): 'Ranger docs',
    ((ord('g'),), 'D'): '~/Downloads',
    ((ord('g'),), 'O'): '~/Documents',
    ((ord('g'),), 'X'): '~/.config',

    # ── o  sort order ────────────────────────────────────────────────────────
    ((ord('o'),), 'r'): 'Toggle reverse',
    ((ord('o'),), 'z'): 'Random',
    ((ord('o'),), 's'): 'Size ▲',
    ((ord('o'),), 'S'): 'Size ▼',
    ((ord('o'),), 'b'): 'Name ▲',
    ((ord('o'),), 'B'): 'Name ▼',
    ((ord('o'),), 'n'): 'Natural sort ▲ (2 before 10)',
    ((ord('o'),), 'N'): 'Natural sort ▼ (2 before 10)',
    ((ord('o'),), 'm'): 'Modify time ▲',
    ((ord('o'),), 'M'): 'Modify time ▼',
    ((ord('o'),), 'c'): 'Change time ▲',
    ((ord('o'),), 'C'): 'Change time ▼',
    ((ord('o'),), 'a'): 'Access time ▲',
    ((ord('o'),), 'A'): 'Access time ▼',
    ((ord('o'),), 't'): 'File type ▲',
    ((ord('o'),), 'T'): 'File type ▼',
    ((ord('o'),), 'e'): 'Extension ▲',
    ((ord('o'),), 'E'): 'Extension ▼',

    # ── z  settings toggles ──────────────────────────────────────────────────
    ((ord('z'),), 'c'): 'Collapse preview',
    ((ord('z'),), 'z'): 'Filter',
    ((ord('z'),), 'd'): 'Dirs first',
    ((ord('z'),), 'f'): 'Filter',
    ((ord('z'),), 'F'): 'Smart flatten',
    ((ord('z'),), 'h'): 'Hidden files',
    ((ord('z'),), 'i'): 'Image preview',
    ((ord('z'),), 'I'): 'Flush input',
    ((ord('z'),), 'm'): 'Mouse',
    ((ord('z'),), 'n'): 'Line numbers',
    ((ord('z'),), 'p'): 'File preview',
    ((ord('z'),), 'P'): 'Dir preview',
    ((ord('z'),), 's'): 'Case insensitive',
    ((ord('z'),), 'u'): 'Auto cumulative size',
    ((ord('z'),), 'v'): 'Preview script',
    ((ord('z'),), 'w'): 'Word wrap',
    ((ord('z'),), 'W'): 'Flatten write',

    # ── M  linemode ──────────────────────────────────────────────────────────
    ((ord('M'),), 'f'): 'Filename',
    ((ord('M'),), 'i'): 'File info',
    ((ord('M'),), 'm'): 'Mtime',
    ((ord('M'),), 'h'): 'Human mtime',
    ((ord('M'),), 'H'): 'Size + human mtime',
    ((ord('M'),), 'p'): 'Permissions',
    ((ord('M'),), 's'): 'Size + mtime',
    ((ord('M'),), 't'): 'Meta title',

    # ── y  yank / copy selection ─────────────────────────────────────────────
    ((ord('y'),), 'y'): 'Copy',
    ((ord('y'),), 'a'): 'Add to copy',
    ((ord('y'),), 'r'): 'Remove from copy',
    ((ord('y'),), 't'): 'Toggle copy',
    ((ord('y'),), 'gg'): 'Copy to top',
    ((ord('y'),), 'G'): 'Copy to end',
    ((ord('y'),), 'j'): 'Copy down',
    ((ord('y'),), 'k'): 'Copy up',

    # ── d  cut selection ─────────────────────────────────────────────────────
    ((ord('d'),), 'd'): 'Cut',
    ((ord('d'),), 'a'): 'Add to cut',
    ((ord('d'),), 'r'): 'Remove from cut',
    ((ord('d'),), 't'): 'Toggle cut',
    ((ord('d'),), 'gg'): 'Cut to top',
    ((ord('d'),), 'G'): 'Cut to end',
    ((ord('d'),), 'j'): 'Cut down',
    ((ord('d'),), 'k'): 'Cut up',

    # ── p  paste ─────────────────────────────────────────────────────────────
    ((ord('p'),), 'p'): 'Paste',
    ((ord('p'),), 'o'): 'Overwrite',
    ((ord('p'),), 'P'): 'Append',
    ((ord('p'),), 'O'): 'Overwrite + append',
    ((ord('p'),), 'l'): 'Symlink (abs)',
    ((ord('p'),), 'L'): 'Symlink (rel)',
    ((ord('p'),), 'd'): 'Paste to path...',
    ((ord('p'), ord('h')), 'l'): 'Hardlink',
    ((ord('p'), ord('h')), 't'): 'Hardlink subtree',

    # ── u  undo / unset ──────────────────────────────────────────────────────
    ((ord('u'),), 'd'): 'Uncut',
    ((ord('u'),), 'y'): 'Uncut (yank)',
    ((ord('u'),), 'm'): 'Unset bookmark',
    ((ord('u'),), 'q'): 'Restore tab',
    ((ord('u'),), 't'): 'Remove tag',
    ((ord('u'),), 'u'): 'Undo trash',
    ((ord('u'),), 'v'): 'Unmark all',
    ((ord('u'),), 'V'): 'Visual reverse',

    # ── c  rename ────────────────────────────────────────────────────────────
    ((ord('c'),), 'w'): 'Rename',
    ((ord('c'),), 'E'): 'Rename extension',
}


def _patched_draw_hints(self):
    import curses
    import math
    from ranger.ext.keybinding_parser import key_to_string

    if not self.columns:
        return

    # Always use the live window dimensions so the layout is correct after
    # a terminal resize (self.hei / self.wid can be stale).
    try:
        hei, wid = self.win.getmaxyx()
    except Exception:
        hei, wid = self.hei, self.wid

    preview_col = self.columns[-1]
    draw_wid = preview_col.x
    if draw_wid < 30:
        preview_col.clear_image(force=True)
        draw_wid = wid

    self.color_reset()

    # Do NOT set self.need_clear = True here.  That flag causes draw() to
    # call self.clear() then redraw all columns on the next key press.
    # When the preview column redraws with an image, it queues an async
    # kitty render that lands *after* the synchronous curses hint write,
    # overwriting the hints (the second-submap bug).
    #
    # Instead, erase only the rows occupied by the previous hint display
    # before writing new ones.  Column redraws (which share the same
    # physical curses surface via derwin) handle cleanup on dismiss.
    prev_ystart   = getattr(self, '_hints_ystart',   None)
    prev_nrows    = getattr(self, '_hints_nrows',    0)
    prev_draw_wid = getattr(self, '_hints_draw_wid', draw_wid)
    if prev_ystart is not None:
        import curses as _c
        clear_wid = max(prev_draw_wid, draw_wid)
        blank = ' ' * clear_wid
        for r in range(prev_nrows + 1):   # +1 covers the header row
            try:
                self.addnstr(prev_ystart + r, 0, blank, clear_wid)
            except _c.error:
                pass

    hints = []

    context = tuple(self.fm.ui.keybuffer.keys)

    def populate_hints(keymap, prefix=""):
        for key, value in keymap.items():
            key_str = prefix + key_to_string(key)
            if not key_str:  # skip empty — would crash groupby below
                continue
            if isinstance(value, dict):
                populate_hints(value, key_str)
            else:
                if not isinstance(value, str) or \
                        value.startswith('hint') or \
                        value.startswith('chain hint'):
                    continue
                label = _KEY_LABELS.get((context, key_str), value)
                hints.append((key_str, label))

    try:
        populate_hints(self.fm.ui.keybuffer.pointer)
    except Exception:
        return

    labels = _SUBMAP_LABELS.get(context, {})

    def sort_hints(hints):
        from itertools import groupby
        hints.sort(key=lambda t: t[0])

        def group_hints(hints):
            return (
                sorted(group, key=lambda h: h[1])
                for _, group in groupby(hints, key=lambda h: h[0][0])
            )

        grouped_hints = list(group_hints(hints))

        if len(hints) > self.fm.settings.hint_collapse_threshold:
            def collapse(group):
                first_char = group[0][0][0]
                if first_char in labels:
                    return [(first_char, labels[first_char])]
                return [(first_char, '...')]

            grouped_hints = [
                collapse(g) if len(g) > 1 else g
                for g in grouped_hints
            ]

        grouped_hints = sorted(grouped_hints, key=lambda g: g[0][1])
        return [item for sublist in grouped_hints for item in sublist]

    try:
        hints = sort_hints(hints)
    except Exception:
        return

    if not hints:
        return

    # ── multi-column layout ───────────────────────────────────────────────
    # Measure content so we know the minimum cell width.
    max_key_w = max(len(k) for k, _ in hints)
    max_lbl_w = max(len(l) for _, l in hints)
    key_col_w = max(max_key_w, 3)          # never narrower than "key"
    # cell = " " + key.ljust(key_col_w) + " " + label  (+2 inter-col gap)
    min_cell_w = 1 + key_col_w + 1 + max_lbl_w + 2

    # How many columns fit?  At least 1, never more than 3.
    ncols = max(1, min(3, draw_wid // min_cell_w))
    col_w  = draw_wid // ncols             # each column's pixel budget
    nrows  = math.ceil(len(hints) / ncols)

    # Make sure we don't run off the top of the screen.
    if hei < 3:                           # no room for header + one row
        return
    max_rows = max(1, hei - 2)            # -1 header, -1 margin
    if nrows > max_rows:
        nrows  = max_rows
        ncols  = max(1, min(3, math.ceil(len(hints) / nrows)))
        col_w  = draw_wid // ncols

    ystart = hei - nrows - 1              # row where the header sits

    # ── header (repeated per column so it reads correctly in each) ────────
    whitespace = " " * draw_wid
    self.addnstr(ystart, 0, whitespace, draw_wid)
    hdr_cell = (" " + "key".ljust(key_col_w) + " " + "command").ljust(col_w)
    for col in range(ncols):
        x = col * col_w
        avail = min(col_w, draw_wid - x)
        if avail <= 0:
            break
        self.addnstr(ystart, x, hdr_cell, avail)
    try:
        self.win.chgat(ystart, 0, draw_wid, curses.A_UNDERLINE)
    except curses.error:
        pass

    # ── hint rows ─────────────────────────────────────────────────────────
    for row in range(nrows):
        y = ystart + 1 + row
        self.addnstr(y, 0, whitespace, draw_wid)
        for col in range(ncols):
            idx = col * nrows + row
            if idx >= len(hints):
                break
            key, cmd = hints[idx]
            x = col * col_w
            avail = min(col_w, draw_wid - x)
            if avail <= 0:
                break
            cell = " " + key.ljust(key_col_w) + " " + cmd
            self.addnstr(y, x, cell, avail)

    # Remember geometry so the next call can erase exactly these rows.
    self._hints_ystart   = ystart
    self._hints_nrows    = nrows
    self._hints_draw_wid = draw_wid


_view_base.ViewBase._draw_hints = _patched_draw_hints


# ---------------------------------------------------------------------------
# Make <Escape> walk back one level in a key sequence instead of clearing
# the entire buffer.
#
# Root cause (discovered from handle_input source):
#   A standalone Escape is dispatched as handle_keys(27, -1).
#   handle_key(27)  → self.press(27) — our patch runs here.
#   handle_key(-1)  → self.keybuffer.clear() unconditionally.
#   The -1 fires AFTER press() returns, wiping any replay we did inside press().
#   draw_hints=True is left from the previous submap, but kb.keys is now empty,
#   so the next draw renders the full root-level hint map.
#
# Fix:
#   Instead of replaying inside press(27), store the intended context on
#   self.browser._hint_restore_ctx and set draw_hints=True.  _patched_vm_draw
#   (which runs AFTER the full handle_keys sequence) detects the pending
#   context, replays it into the keybuffer, and recomputes draw_hints so the
#   correct hint level is displayed.
#
# Two cases:
#   Case 1 – mid-submap: kb.keys non-empty.  Go up one level (parent context).
#   Case 2 – parse error: unmapped key was pressed; _orig_press returned False
#             and cleared the buffer.  Restore the pre-error submap context
#             saved in _parse_error_ctx.
# ---------------------------------------------------------------------------
import ranger.gui.ui as _ui

_orig_press = _ui.UI.press


def _patched_press(self, key):
    kb = self.keybuffer

    if key == 27:  # Escape / C-[
        # Case 1: still traversing a submap — go up one level.
        if (kb.keys
                and not kb.finished_parsing
                and isinstance(kb.pointer, dict)):
            parent_keys = list(kb.keys[:-1])
            kb.clear()
            # Store parent context for _patched_vm_draw to replay after
            # handle_key(-1) has cleared the buffer.
            if parent_keys:
                self.browser._hint_restore_ctx = parent_keys
                self.browser.draw_hints = True
            else:
                # Top-level dismiss: nothing to restore, just drop hints.
                self.browser._hint_restore_ctx = None
                self.browser.draw_hints = False
            return True

        # Case 2: a parse error previously cleared the buffer.
        # Queue the saved context for restoration in _patched_vm_draw.
        saved = getattr(self, '_parse_error_ctx', None)
        if saved is not None:
            kb.clear()
            self.browser._hint_restore_ctx = saved
            self.browser.draw_hints = True
            setattr(self, '_parse_error_ctx', None)
            return True

    # Any key that falls through here (non-Escape, or unmatched Escape) cancels
    # a pending restore — the user has moved on.
    self.browser._hint_restore_ctx = None

    # Snapshot the current submap path before forwarding to ranger.
    ctx_before = None
    if kb.keys and not kb.finished_parsing and isinstance(kb.pointer, dict):
        ctx_before = list(kb.keys)

    # Starting a fresh sequence from an empty buffer: discard stale parse-error context.
    if not kb.keys and key != 27:
        setattr(self, '_parse_error_ctx', None)

    result = _orig_press(self, key)

    # _orig_press returns False specifically on parse error.
    # Save the pre-error submap path for Case 2.  ctx_before is None when the
    # error happened at root, so Case 2 will not fire in that case.
    if result is False:
        setattr(self, '_parse_error_ctx', ctx_before)
    elif not kb.keys:
        setattr(self, '_parse_error_ctx', None)

    return result


_ui.UI.press = _patched_press


# ---------------------------------------------------------------------------
# Patch ViewMiller.draw() to erase lingering hint rows when the overlay is
# dismissed.  ViewMiller is the actual browser class and has its own draw()
# that does NOT call super() — it calls DisplayableContainer.draw() directly —
# so patching ViewBase.draw is a no-op.
#
# After the normal draw, if _hints_ystart is still set but draw_hints is now
# False, write blanks to those rows.  They are the last writes to those cells
# in the shared ncurses buffer and therefore win at the next doupdate(),
# clearing the stale hint text without triggering a full column redraw.
# ---------------------------------------------------------------------------
import ranger.gui.widgets.view_miller as _view_miller

_orig_vm_draw = _view_miller.ViewMiller.draw


def _patched_vm_draw(self):
    # If _patched_press queued a context restore (Escape while mid-submap),
    # replay those keys into the keybuffer NOW — before _orig_vm_draw calls
    # _draw_hints — so the hint overlay renders the correct parent submap.
    # handle_key(-1) cleared the buffer after press() returned; this is the
    # first draw() call after that, so we restore it here.
    ctx = getattr(self, '_hint_restore_ctx', None)
    if ctx is not None:
        self._hint_restore_ctx = None
        kb = self.fm.ui.keybuffer
        kb.clear()
        for k in ctx:
            kb.add(k)
        self.draw_hints = True

    # When the hint overlay has just been dismissed (draw_hints is now False
    # but _hints_ystart is still set from the last _draw_hints call), force a
    # column redraw BEFORE doing anything else.  Columns share the same ncurses
    # buffer via derwins; their redraw writes the correct file-list content on
    # top of the stale hint cells so that the refresh shows the right content.
    # Writing explicit blanks instead would leave those rows empty until the
    # next navigation event triggers its own column redraw.
    if not getattr(self, 'draw_hints', False) \
            and getattr(self, '_hints_ystart', None) is not None:
        # need_clear triggers win.erase() + need_redraw inside ViewMiller.draw().
        # need_redraw alone restores file-list cells (written by column derwins)
        # but not border separator cells (written to browser.win directly by
        # _draw_borders).  erase() zeroes the entire shared buffer so the
        # subsequent column and border redraws start from a clean slate.
        # This is the same path ranger takes on every navigation event and does
        # not invalidate the preview cache, so no scope.sh re-run occurs.
        self.need_clear = True
        self._hints_ystart = None
    _orig_vm_draw(self)


_view_miller.ViewMiller.draw = _patched_vm_draw
