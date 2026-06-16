from ranger.config.commands import scout as _scout


class vim_search(_scout):
    """:vim_search <pattern>

    Incremental regex search: jump to first match as you type.
    Keeps last_search live so <C-n>/<C-p> cycle matches while the
    console is still open.  Flags rts (regex, as-you-type, smart-case)
    are always applied.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Inject rts so no alias wrapper is needed in rc.conf.
        for flag in 'rts':
            if flag not in self.flags:
                self.flags += flag

    def quick(self):
        result = super().quick()
        # Keep last_search current as the user types so that <C-n>/<C-p>
        # (via search_next) work before Enter is pressed.
        if self.pattern:
            self.fm.thistab.last_search = self._build_regex()
            self.fm.set_search_method(order='search')
        return result
