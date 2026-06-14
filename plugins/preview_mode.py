"""
Visual preview mode management plugin.

Responsibilities:
  1. Via hook_init: bind to the 'move' signal (emitted by tab.py whenever
     thisfile changes) to:
       a. Auto-disable peek mode (_preview_peek) after one navigation.
       b. Auto-clear fm.previews and the displayed kitty image when the
          directory changes (e.g. pressing h/l), freeing memory without
          touching the on-disk thumbnail cache in ~/.cache/ranger.
  2. Patch UI.update_size: on terminal resize, clear fm.previews and force
     the preview column to re-render the image at the new dimensions.

No KittyImageDisplayer patching. No cachedir redirection.
Stock ranger handles image scaling (PIL in KittyImageDisplayer.draw()) and
caching (~/.cache/ranger).
"""

import ranger.api as _ranger_api
import ranger.gui.ui as _ui_mod

_ORIG_HOOK_INIT = _ranger_api.hook_init
_orig_update_size = _ui_mod.UI.update_size


# ---------------------------------------------------------------------------
# Patch 1: peek auto-disable + auto-clear on directory change
# ---------------------------------------------------------------------------

def _hook_init(fm):
    _ORIG_HOOK_INIT(fm)

    _last_dir = [None]

    def _clear_preview():
        fm.previews.clear()
        try:
            preview_col = fm.ui.browser.columns[-1]
            preview_col.clear_image(force=True)
            preview_col.need_redraw = True
        except (AttributeError, IndexError):
            pass
        fm.ui.need_redraw = True

    def _on_move(signal):
        # Track directory to detect changes.
        tab = getattr(signal, 'tab', None)
        thisdir = getattr(tab, 'thisdir', None)
        dir_path = getattr(thisdir, 'path', None)
        dir_changed = (dir_path is not None
                       and _last_dir[0] is not None
                       and dir_path != _last_dir[0])
        _last_dir[0] = dir_path

        # Peek mode: disable after first navigation.
        if getattr(fm, '_preview_peek', False):
            fm._preview_peek = False
            fm.preview_mode = False
            fm.settings.preview_images = False
            _clear_preview()
            return

        # Auto-clear in-memory preview cache when leaving a directory so
        # stale fm.previews entries and the displayed image don't linger.
        if dir_changed:
            _clear_preview()

    fm.signal_bind('move', _on_move)


_ranger_api.hook_init = _hook_init


# ---------------------------------------------------------------------------
# Patch 2: re-render preview on terminal resize
# ---------------------------------------------------------------------------

def _patched_update_size(self):
    old_size = getattr(self, 'termsize', None)
    _orig_update_size(self)
    if old_size is None or old_size == self.termsize:
        return

    try:
        self.fm.previews.clear()
    except AttributeError:
        pass

    try:
        preview_col = self.browser.columns[-1]
        preview_col.clear_image(force=True)
        preview_col.need_redraw = True
    except (AttributeError, IndexError):
        pass

    self.need_redraw = True


_ui_mod.UI.update_size = _patched_update_size
