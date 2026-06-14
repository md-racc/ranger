"""
Global command feedback plugin.

Binds to fm.settings signal 'setopt' (fired after every setting change)
and emits a notify() so the user always sees what was applied.

Timing: rc.conf is processed inside fm.initialize(), which runs before
hook_init is called, so startup configuration is silent. Only interactive
changes (keymaps, console commands, other plugins) generate messages.

Sort notifications include a ▲/▼ direction indicator so direction changes
are visible even when only sort_reverse is toggled.
"""

import os

import ranger.api as _ranger_api

_ORIG_HOOK_INIT = _ranger_api.hook_init


def _hook_init(fm):
    _ORIG_HOOK_INIT(fm)

    # update_tmux_title writes 'ESC k … ESC \\' even outside tmux, which
    # kitty logs as a parse error.  Only keep it inside tmux/screen.  This
    # runs before ui.initialize() (which emits it) and before the setopt
    # binding below, so it is silent.
    if not os.environ.get('TMUX') and 'screen' not in os.environ.get('TERM', ''):
        fm.settings.update_tmux_title = False

    def _on_setopt(signal):
        msg = _label(signal.setting, signal.value, fm)
        if msg:
            fm.notify(msg)

    fm.settings.signal_bind('setopt', _on_setopt)


def _label(name, value, fm):
    b = lambda v: 'on' if v else 'off'

    if name == 'sort':
        arrow = ' \u25bc' if fm.settings.sort_reverse else ' \u25b2'
        return 'Sort: {}{}'.format(value, arrow)
    if name == 'sort_reverse':
        arrow = ' \u25bc' if value else ' \u25b2'
        return 'Sort: {}{}'.format(fm.settings.sort, arrow)
    if name == 'sort_directories_first':
        return 'Dirs first: {}'.format(b(value))
    if name == 'sort_case_insensitive':
        return 'Case insensitive: {}'.format(b(value))
    if name == 'show_hidden':
        return 'Hidden files: {}'.format('shown' if value else 'hidden')
    if name == 'preview_images':
        return 'Image preview: {}'.format(b(value))
    if name == 'preview_files':
        return 'File preview: {}'.format(b(value))
    if name == 'preview_directories':
        return 'Dir preview: {}'.format(b(value))
    if name == 'collapse_preview':
        return 'Collapse preview: {}'.format(b(value))
    if name == 'use_preview_script':
        return 'Preview script: {}'.format(b(value))
    if name == 'wrap_plaintext_previews':
        return 'Word wrap: {}'.format(b(value))
    if name == 'line_numbers':
        return 'Line numbers: {}'.format(value)
    if name == 'mouse_enabled':
        return 'Mouse: {}'.format(b(value))
    if name == 'freeze_files':
        return 'Files {}'.format('frozen' if value else 'unfrozen')
    if name == 'flushinput':
        return 'Flush input: {}'.format(b(value))
    if name == 'autoupdate_cumulative_size':
        return 'Auto cumulative size: {}'.format(b(value))
    return None


_ranger_api.hook_init = _hook_init
