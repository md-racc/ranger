# Ranger colorscheme based on vim's 'quiet' (dark background)
# Author: vim/colorschemes quiet.vim by Maxence Weynans
# Palette sourced directly from quiet.vim guifg/guibg 256-color values

from ranger.gui.color import *
from ranger.colorschemes.default import Default

# ── Palette ──────────────────────────────────────────────────────────────────
#  Name        cterm   hex       vim group
BG        = 16   # #000000  Normal bg
FG        = 253  # #dadada  Normal fg
MUTED     = 242  # #707070  Comment / EndOfBuffer
DIM       = 240  # #585858  LineNr
SURFACE   = 236  # #303030  CursorLine bg
AMBER     = 214  # #ffaf00  Visual (marked files)
CYAN      = 39   # #00afff  Search (symlinks / copied)
RED       = 197  # #ff005f  Error (broken links / cut)
GREEN     = 34   # #00af00  DiffAdd
STATUSBG  = 253  # #dadada  StatusLine bg
BLUE      = 27   # #005fff  ~#0042ff directories (closest 256-color)


class Scheme(Default):
    progress_bar_color = AMBER

    def use(self, context):
        fg, bg, attr = Default.use(self, context)

        # ── File browser ─────────────────────────────────────────────────────
        if context.in_browser:
            fg   = FG
            bg   = BG
            attr = normal

            # Directories: bold blue (#0042ff → closest 256-color #005fff = 27)
            if context.directory:
                fg   = BLUE
                attr = bold
                if context.empty:
                    fg = MUTED

            # Symlinks
            if context.link:
                fg   = CYAN
                attr = normal
                if context.bad:          # broken symlink
                    fg   = RED
                    attr = bold

            # Media (image / video / audio) — muted grey so they don't
            # visually collide with the amber of marked files
            if context.media:
                fg   = MUTED
                attr = normal

            # Archives
            if context.container:
                fg   = MUTED
                attr = bold

            # Documents
            if context.document:
                fg   = FG
                attr = normal

            # Executables — bold only, asterisk already indicates it
            if context.executable and not context.directory:
                attr = bold

            # ── Clipboard tints ──────────────────────────────────────────────
            # Cut: red tint (DiffDelete colour from quiet.vim)
            if context.cut:
                fg   = RED
                attr = bold
            # Copied: cyan tint (Search colour from quiet.vim)
            elif context.copied:
                fg   = CYAN
                attr = normal

            # ── Marked (selected for batch operation) ────────────────────────
            # Mirrors vim Visual: guifg=#ffaf00 guibg=#000000 gui=reverse
            # Amber on black reversed = black text on amber background
            if context.marked:
                fg   = AMBER
                bg   = BG
                attr = reverse | bold

            # ── Cursor row ───────────────────────────────────────────────────
            # Mirrors vim CursorLine: guibg=#303030
            if context.selected:
                bg   = SURFACE
                attr = attr | bold
                # Marked + cursor: full amber block so it's unmissable
                if context.marked:
                    fg   = BG
                    bg   = AMBER
                    attr = bold

            # Tagged files (persistent t tag)
            if context.tagged and not context.selected:
                attr = attr | underline

        # ── Title bar ────────────────────────────────────────────────────────
        # Mirrors vim StatusLine: guifg=#000000 guibg=#dadada gui=bold
        elif context.in_titlebar:
            fg   = FG
            bg   = BG
            attr = normal

            if context.hostname:
                attr = bold
            elif context.directory:
                attr = bold
            elif context.tab:
                if context.good:         # active tab
                    fg   = BG
                    bg   = STATUSBG
                    attr = bold
                else:                    # inactive tab
                    fg   = MUTED
                    bg   = BG
                    attr = normal
            elif context.link:
                fg = CYAN

        # ── Status bar ───────────────────────────────────────────────────────
        # Transparent bg (default = -1), light grey text for dark wallpaper
        elif context.in_statusbar:
            fg   = FG
            bg   = default
            attr = normal

            if context.permissions:
                if context.good:
                    fg   = GREEN
                    attr = normal
                elif context.bad:
                    fg   = RED
                    attr = bold
                else:
                    fg   = MUTED        # neutral perms (e.g. rw-r--r--)
            if context.marked:           # count of marked files
                fg   = AMBER
                attr = bold
            if context.message:
                if context.bad:
                    fg   = RED
                    attr = bold
                else:
                    fg   = FG
            if context.loaded:           # copy/move progress bar
                fg   = AMBER
                attr = bold

        return fg, bg, attr
