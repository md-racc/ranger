from __future__ import (absolute_import, division, print_function)
import os
import re
import time
from ranger.api.commands import Command


# Register custom filter types with ranger's filter_stack.
# Each entry in SIMPLE_FILTERS maps a type name → constructor(arg_string).
try:
    from ranger.core.filter_stack import SIMPLE_FILTERS, BaseFilter
    from ranger.core.shared import FileManagerAware as _FMA

    # ── tag filter ────────────────────────────────────────────────────────────
    class _TagFilter(BaseFilter, _FMA):
        def __init__(self, tag_char):
            self.tag_char = tag_char if tag_char else '*'

        def __call__(self, fobj):
            return self.fm.tags.tags.get(fobj.path) == self.tag_char

        def __str__(self):
            return "<Filter: tag == '{}'>".format(self.tag_char)

    if 'tag' not in SIMPLE_FILTERS:
        SIMPLE_FILTERS['tag'] = _TagFilter

    # ── size filter ───────────────────────────────────────────────────────────
    # Accepts expressions like  >10M  <500K  >=1G  <=10M  =1G  !=100B
    # Units (case-insensitive): B K KB M MB G GB T TB  (plain number = bytes)
    class _SizeFilter(BaseFilter):
        _UNITS = {
            '': 1, 'b': 1,
            'k': 1024, 'kb': 1024,
            'm': 1024 ** 2, 'mb': 1024 ** 2,
            'g': 1024 ** 3, 'gb': 1024 ** 3,
            't': 1024 ** 4, 'tb': 1024 ** 4,
        }
        _PAT = re.compile(
            r'^([<>=!]{1,2})\s*([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z]*)$'
        )

        def __init__(self, expr):
            m = self._PAT.match(expr.strip())
            if not m:
                raise ValueError("size filter: use >10M, <500K, =1G, !=100B")
            op, num, unit = m.group(1), float(m.group(2)), m.group(3).lower()
            if op not in ('>', '<', '>=', '<=', '=', '==', '!=', '!'):
                raise ValueError("size filter: unknown operator {!r}".format(op))
            if unit not in self._UNITS:
                raise ValueError("size filter: unknown unit {!r}".format(unit))
            self.threshold = int(num * self._UNITS.get(unit, 1))
            self.op = op
            self.expr = expr.strip()

        def __call__(self, fobj):
            st = fobj.stat
            size = st.st_size if st else 0
            op, t = self.op, self.threshold
            if op == '>':            return size > t
            if op == '<':            return size < t
            if op == '>=':           return size >= t
            if op == '<=':           return size <= t
            if op in ('=', '=='):   return size == t
            if op in ('!=', '!'):   return size != t
            return True

        def __str__(self):
            return "<Filter: size {}>".format(self.expr)

    if 'size' not in SIMPLE_FILTERS:
        SIMPLE_FILTERS['size'] = _SizeFilter

    # ── extension filter ──────────────────────────────────────────────────────
    # Matches files whose extension equals the given string (leading dot optional,
    # case-insensitive).  Directories and extensionless files are excluded.
    class _ExtFilter(BaseFilter):
        def __init__(self, ext):
            self.ext = ext.strip().lstrip('.').lower()

        def __call__(self, fobj):
            _, e = os.path.splitext(fobj.basename)
            return bool(e) and e.lstrip('.').lower() == self.ext

        def __str__(self):
            return "<Filter: ext == '.{}'>".format(self.ext)

    if 'ext' not in SIMPLE_FILTERS:
        SIMPLE_FILTERS['ext'] = _ExtFilter

    # ── age / mtime filter ────────────────────────────────────────────────────
    # Accepts:  7   (modified within last 7 days)
    #          <7   (same — explicit less-than)
    #          >30  (not modified in last 30 days, i.e. older than 30 days)
    class _AgeFilter(BaseFilter):
        _PAT = re.compile(r'^([<>]?)(\d+)$')

        def __init__(self, expr):
            m = self._PAT.match(expr.strip())
            if not m:
                raise ValueError("age filter: use 7, <7, or >30 (days)")
            self.op = m.group(1) or '<'
            self.days = int(m.group(2))
            self.expr = expr.strip()

        def __call__(self, fobj):
            st = fobj.stat
            if not st:
                return False
            age_days = (time.time() - st.st_mtime) / 86400.0
            if self.op == '<':  return age_days < self.days
            if self.op == '>':  return age_days > self.days
            return age_days < self.days

        def __str__(self):
            return "<Filter: mtime {}{}d>".format(self.op, self.days)

    if 'age' not in SIMPLE_FILTERS:
        SIMPLE_FILTERS['age'] = _AgeFilter

except Exception:
    pass


class filter_tag(Command):
    """:filter_tag <char>  (.t)

    Push a tag filter onto the filter_stack showing only files tagged with
    <char>.  Omit <char> to filter for the default tag ('*').
    """

    def execute(self):
        char = self.rest(1).strip() or '*'
        if len(char) != 1:
            self.fm.notify("filter_tag: expected a single character", bad=True)
            return
        if char not in self.fm.tags.tags.values():
            self.fm.notify("No files are tagged with '{}'".format(char), bad=True)
        self.fm.execute_console('filter_stack add tag ' + char)

    def tab(self, tabnum):
        return []


class filter_tag_flat(Command):
    """:filter_tag_flat <char>  (.T)

    Like filter_tag but also flattens the directory tree (-1) so all
    tagged files in the subtree are visible in one list.
    Pressing .T again while a .T-flatten is active undoes just that
    flatten; a smart_flatten (zF) view is left alone. The tag filter
    itself is untouched — clear it with .p/.c.
    """

    def execute(self):
        if self.fm.thisdir.flat == -1:
            self.fm.thisdir.unload()
            self.fm.thisdir.flat = 0
            self.fm.thisdir.load_content()
            return

        char = self.rest(1).strip() or '*'
        if len(char) != 1:
            self.fm.notify("filter_tag_flat: expected a single character", bad=True)
            return
        if char not in self.fm.tags.tags.values():
            self.fm.notify("No files are tagged with '{}'".format(char), bad=True)
        self.fm.execute_console('filter_stack add tag ' + char)
        self.fm.thisdir.unload()
        self.fm.thisdir.flat = -1
        self.fm.thisdir.load_content()

    def tab(self, tabnum):
        return []


class filter_size(Command):
    """:filter_size <expr>  (.s)

    Push a size filter onto the filter_stack.
    Operators: >  <  =  !=
    Units (case-insensitive): B K M G T  (plain number = bytes)
    Examples:  :filter_size >10M   :filter_size <500K   :filter_size >1G
    """

    def execute(self):
        expr = self.rest(1).strip()
        if not expr:
            self.fm.open_console('filter_size ')
            return
        try:
            from ranger.core.filter_stack import SIMPLE_FILTERS
            SIMPLE_FILTERS['size'](expr)  # validate before pushing
        except (ValueError, KeyError) as e:
            self.fm.notify(str(e) or "Invalid size expression", bad=True)
            return
        self.fm.execute_console('filter_stack add size ' + expr)

    def tab(self, tabnum):
        return []


class filter_ext(Command):
    """:filter_ext <ext>  (.e)

    Push an extension filter showing only files with the given extension.
    The leading dot is optional.
    Examples:  :filter_ext py   :filter_ext .mp4   :filter_ext rs
    """

    def execute(self):
        ext = self.rest(1).strip().lstrip('.')
        if not ext:
            self.fm.open_console('filter_ext ')
            return
        self.fm.execute_console('filter_stack add ext ' + ext)

    def tab(self, tabnum):
        return []


class filter_age(Command):
    """:filter_age <expr>  (.a)

    Push an mtime filter onto the filter_stack.
    <N>   — modified within the last N days
    <N    — same (explicit)
    >N    — older than N days (not modified in last N days)
    Examples:  :filter_age 7   :filter_age >30   :filter_age <1
    """

    def execute(self):
        expr = self.rest(1).strip()
        if not expr:
            self.fm.open_console('filter_age ')
            return
        try:
            from ranger.core.filter_stack import SIMPLE_FILTERS
            SIMPLE_FILTERS['age'](expr)  # validate before pushing
        except (ValueError, KeyError) as e:
            self.fm.notify(str(e) or "Invalid age expression", bad=True)
            return
        self.fm.execute_console('filter_stack add age ' + expr)

    def tab(self, tabnum):
        return []
