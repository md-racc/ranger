# Ranger Keybind Reference

> Search tip: use `/pattern` in your pager, or `grep -i keyword KEYBINDS.md`

---

## Table of Contents

- [Navigation](#navigation)
- [Selection & Marking](#selection--marking)
- [File Operations](#file-operations)
- [Renaming](#renaming)
- [Permissions & Ownership](#permissions--ownership)
- [Archives — `<Space>a`](#archives--spacea)
- [Opening & Inspecting — `<Space>o`](#opening--inspecting--spaceo)
- [Clipboard / Yank — `<Space>y`](#clipboard--yank--spacey)
- [FZF / Fuzzy / Navigate — `<Space>f`](#fzf--fuzzy--navigate--spacef)
- [Searching & Filtering](#searching--filtering)
- [Search-Next by Attribute — `<Space>n`](#search-next-by-attribute--spacen)
- [Filter Stack](#filter-stack)
- [Sorting](#sorting)
- [Tabs](#tabs)
- [Bookmarks](#bookmarks)
- [Disk Usage — `<Space>d`](#disk-usage--spaced)
- [Preview — `<Space>p`](#preview--spacep)
- [Git — `<Space>g`](#git--spaceg)
- [SSH — `<Space>s`](#ssh--spaces)
- [Mount / Devices — `<Space>m`](#mount--devices--spacem)
- [Transfer — `<Space>t`](#transfer--spacet)
- [Permissions (console) — `<Space>c`](#permissions-console--spacec)
- [Checksums — `<Space>h`](#checksums--spaceh)
- [Encrypt / Decrypt — `<Space>e`](#encrypt--decrypt--spacee)
- [Trash / Bin — `<Space>b`](#trash--bin--spaceb)
- [Transform — `<Space>v`](#transform--spacev)
- [LAN Serve — `<Space>l`](#lan-serve--spacel)
- [Flatten](#flatten)
- [Shell & App Control](#shell--app-control)
- [Toggles & Settings](#toggles--settings)
- [Linemodes](#linemodes)
- [Chmod Quick Bindings](#chmod-quick-bindings)
- [Console Mode](#console-mode)
- [Pager Mode](#pager-mode)
- [Taskview Mode](#taskview-mode)
- [Console Commands & Aliases](#console-commands--aliases)

---

## Navigation

| Key | Action |
|-----|--------|
| `h` / `←` | Go up one directory |
| `l` / `→` / `Enter` | Enter directory / open file |
| `j` / `↓` | Move down |
| `k` / `↑` | Move up |
| `gg` / `Home` | Jump to top |
| `G` / `End` | Jump to bottom |
| `J` / `Ctrl-d` | Half-page down |
| `K` / `Ctrl-u` | Half-page up |
| `Ctrl-f` / `PgDn` | Page down |
| `Ctrl-b` / `PgUp` | Page up |
| `H` | History back |
| `L` | History forward |
| `]` | Move to next parent sibling |
| `[` | Move to previous parent sibling |
| `}` | Traverse (next non-empty dir) |
| `{` | Traverse backwards |
| `)` | Jump to next non-empty dir |
| `<Space>fc` | Console: cd to typed path (tab-completes) |
| `<Space>ft` | Travel mode: filter + navigate as you type |
| `<Space>f/` | Quick find (scout, navigate as you type) |

### Quick Directory Jumps (`g` prefix)

Lowercase = system roots · Capital = places in `$HOME` (edit them at the end of `rc.conf`)

| Key | Directory |
|-----|-----------|
| `gh` | `~` (home) |
| `ge` | `/etc` |
| `gu` | `/usr` |
| `gd` | `/dev` |
| `go` | `/opt` |
| `gv` | `/var` |
| `gm` | `/media` |
| `gi` | `/run/media/$USER` |
| `gs` | `/srv` |
| `gp` | `/tmp` |
| `gr` / `g/` | `/` (root) |
| `gl` | Symlink target of current dir |
| `gL` | Symlink target of current file |
| `gR` | Ranger source dir |
| `g?` | Ranger docs dir |
| `gD` | `~/Downloads` |
| `gO` | `~/Documents` |
| `gX` | `~/.config` |
| `<Space>mM` | `/mnt` |

---

## Selection & Marking

| Key | Action |
|-----|--------|
| `,` | Toggle mark on current file |
| `v` | Toggle mark all files in directory |
| `uv` | Unmark all files |
| `V` | Start visual mode (mark range) |
| `uV` | Start reverse visual mode |
| `Esc` | Leave visual mode and clear all marks |
| `t` | Toggle tag on file (persistent across sessions) |
| `ut` | Remove tag |
| `"<char>` | Tag file with custom character (e.g. `"a`) |

### Select by Pattern (console)

| Command | Action |
|---------|--------|
| `:mark <regex>` | Mark files matching regex |
| `:unmark <regex>` | Unmark files matching regex |

---

## File Operations

### Copy / Cut / Paste

| Key | Action |
|-----|--------|
| `yy` | Copy (yank) selection into ranger register |
| `ya` | Add to copy selection |
| `yr` | Remove from copy selection |
| `dd` | Cut selection |
| `da` | Add to cut selection |
| `dr` | Remove from cut selection |
| `ud` / `uy` | Uncut (clear clipboard) |
| `pp` | Paste |
| `po` | Paste (overwrite existing) |
| `pP` | Paste (append if conflict) |
| `pO` | Paste (overwrite + append) |
| `pl` | Paste as absolute symlink |
| `pL` | Paste as relative symlink |
| `phl` | Paste as hardlink |
| `pht` | Paste as hardlinked subtree |
| `pd` | Paste to typed destination |
| `` p`<char> `` / `p'<char>` | Paste into bookmark `<char>` |
| `dt` / `yt` | Toggle selection in the cut / copy register |

### Cut / Copy Range Shortcuts

| Key | Action |
|-----|--------|
| `dgg` | Cut from here to top |
| `dG` | Cut from here to bottom |
| `dj` | Cut current + one below |
| `dk` | Cut current + one above |
| `ygg` / `yG` / `yj` / `yk` | Same as above but copy |

### Delete / Trash

| Key | Action |
|-----|--------|
| `x` / `Delete` | **Trash** selected files (`gio trash`, recoverable) |
| `uu` | Undo the last trash |
| `<Space>X` / `dD` / `F8` | Console: permanent delete — always asks y/N (`confirm_on_delete always`) |

### Create

| Key | Action |
|-----|--------|
| `md` | Console: `mkcd` — create dir and cd into it |
| `Insert` / `%` | Console: `touch` — create new empty file |
| `F7` | Console: `mkdir` |

---

## Renaming

| Key | Action |
|-----|--------|
| `cw` | Console: rename with blank name |
| `a` | Rename: append (cursor before extension) |
| `A` | Rename: edit full name (cursor at end) |
| `I` | Rename: edit full name (cursor at start) |
| `F2` | Same as `a` |
| `cE` | Console: `rename_ext` — change extension of selection |
| `br` | Bulk rename selection in `$EDITOR` |

---

## Permissions & Ownership

| Key | Action |
|-----|--------|
| `=` | `chmod` interactive (built-in) |
| `<Space>cm` | Console: `chmod <octal>` (e.g. `755`) |
| `<Space>co` | Console: `chown <user>[:<group>]` |

### Permission Quick Bindings (`+` add, `-` remove)

Pattern: `+<who><perm>` or `-<who><perm>`

| Who | Meaning |
|-----|---------|
| `u` | user/owner |
| `g` | group |
| `o` | other |
| `a` | all |

| Perm | Meaning |
|------|---------|
| `r` | read |
| `w` | write |
| `x` | execute |
| `X` | execute (dirs only) |
| `s` | setuid/setgid |
| `t` | sticky bit |

Examples:
- `+x` → `chmod u+x` on selection
- `+ax` → `chmod a+x` on selection
- `-uw` → `chmod u-w` on selection

---

## Archives — `<Space>a`

### Extract — `<Space>ae`

| Key | Action |
|-----|--------|
| `<Space>aed` | Extract into named subdir (`archive.tar.gz` → `archive/`) |
| `<Space>aeh` | Extract flat into current directory — refuses if any entry would overwrite an existing file/dir in cwd (use `<Space>aes`/`<Space>aef` instead) |
| `<Space>aes` | **Smart extract** — no double-nesting: if archive has one top-level dir, extract to cwd; otherwise create subdir |
| `<Space>aef` | **Flatten extract** — extract then collapse all nested files into one flat subdir |
| `<Space>aeD` | Console: `extract_to <path>` — extract to typed destination (tab-completes) |
| `<Space>aeo` | Extract into named subdir then `cd` into it |
| `<Space>aep` | **Pick extract** — opens a nested ranger on the archive; mark with `,`/`v` (any folder), `q` extracts the marked entries |

### Compress — `<Space>ac`

| Key | Format |
|-----|--------|
| `<Space>acz` | `.tar.gz` — fast, universal |
| `<Space>acx` | `.tar.xz` — best compression ratio |
| `<Space>acZ` | `.tar.zst` — fast with good compression (modern) |
| `<Space>acb` | `.tar.bz2` — legacy compatibility |
| `<Space>acp` | `.zip` — cross-platform (Windows/macOS) |
| `<Space>ac7` | `.7z` — maximum compression |

Each compress key opens the console pre-filled with `:compress <stem>.<ext>` ready to edit and confirm.

| Key | Each selected item into its own archive |
|-----|--------|
| `<Space>aciz` / `<Space>acix` / `<Space>aciZ` / `<Space>acib` / `<Space>acip` / `<Space>aci7` | `compress_each` — gz / xz / zst / bz2 / zip / 7z |

### Archive-level

| Key | Action |
|-----|--------|
| `<Space>al` | List archive contents with sizes in pager |
| `<Space>at` | Test archive integrity (pv progress, prints PASSED/FAILED) |
| `<Space>ak` | Cancel all active background extractions |
| `<Space>au` | **File-picker dialog only:** zip the marked items (or highlighted one) into a private `/tmp/ranger-upload-XXXX/` and send that one archive. Prompts for the name |

Extraction never overwrites: entries that already exist are kept (and counted), and
subdir extracts get a fresh `stem/` (`stem_1/`, …) instead of merging. A bare
`.gz`/`.bz2`/`.xz`/`.zst` file is decompressed next to itself.

---

## Opening & Inspecting — `<Space>o`

| Key | Action |
|-----|--------|
| `l` / `Enter` | Open with default (rifle) |
| `r` | Choose opener from list |
| `E` / `F4` | Open in `$EDITOR` |
| `i` / `F3` | Display file in ranger pager |
| `<Space>oo` | Open with `xdg-open` (background) |
| `<Space>om` | Open selection in `mpv` as playlist (background) |
| `<Space>od` | Unified diff between 2 selected files (in `less`) |
| `<Space>os` | `stat` on current file (paged) |
| `<Space>of` | `file --mime` on current file (paged) |
| `<Space>oe` | `exiftool` — EXIF / XMP / IPTC metadata (paged) |
| `<Space>oi` | `mediainfo` — codec, bitrate, resolution (paged) |
| `<Space>oj` | `jq .` — pretty-print JSON (paged) |
| `<Space>oP` | Open cwd as project in `$EDITOR` (background) |
| `<Space>oG` | `cd` to git repository root |
| `<Space>oT` | Spawn a terminal in cwd (`$TERMINAL`, else kitty / foot / alacritty / …; floating under Hyprland) |
| `<Space>oF` | Hand off cwd to GUI file manager (`$FILE_MANAGER` / thunar) |
| `<Space>oD` | Recursive dir diff — select 2 dirs (`difft` / `diff -r`, paged) |
| `<Space>oh` | Hexdump (`hexyl`, else `xxd`, paged) |
| `<Space>or` | Drag the selection into another window (web upload areas): `ripdrag -x -a`, `dragon-drop` fallback |

---

## Clipboard / Yank — `<Space>y`

`<Space>y*` text-copy bindings use `wl-copy` (Wayland), falling back to `xclip`/`xsel` on X11. `yy`/`yv` (binary content / paste) remain Wayland-only.

| Key | Action |
|-----|--------|
| `<Space>yy` | Copy file **contents** to clipboard (binary-safe) |
| `<Space>yp` | Copy full path to clipboard |
| `<Space>yn` | Copy filename (basename) to clipboard |
| `<Space>ye` | Copy filename without extension to clipboard |
| `<Space>yd` | Copy current directory path to clipboard |
| `<Space>yr` | Copy path(s) relative to cwd to clipboard |
| `<Space>yg` | Copy path(s) relative to git repo root to clipboard |
| `<Space>yl` | Copy selection as Markdown link(s) to clipboard |
| `<Space>yv` | **Paste** clipboard content as a file in cwd (image or text) |

`<Space>yv` detects clipboard MIME type: saves as `clipboard-TIMESTAMP.png/jpg/txt` etc.

---

## FZF / Fuzzy / Navigate — `<Space>f`

| Key | Action |
|-----|--------|
| `<Space>ff` | FZF search from **current directory** (fd) |
| `<Space>fh` | FZF search from **$HOME** |
| `<Space>fr` | FZF over **cd history** (recent dirs) |
| `<Space>fR` | FZF over **recent files** (GTK `recently-used.xbel`) → jump to it |
| `<Space>fz` | Console: `z <query>` — zoxide jump (tab-completes) |
| `<Space>f/` | Quick find (navigate as you type) |
| `<Space>ft` | Travel mode: incremental filter + navigate |
| `<Space>fc` | Console: cd to typed path |
| `<Space>fg` | Console: `rg_content_search <pattern>` — rg over contents, results in `$EDITOR` quickfix |

In `<Space>ff` / fzf_select:
- `Enter` → navigate to file/dir
- `Alt-Enter` → open file with rifle

---

## Searching & Filtering

| Key | Action |
|-----|--------|
| `/` | Search filenames in current dir |
| `n` | Next search match |
| `N` | Previous search match |
| `zf` / `zz` | Console: filter (show only matching filenames) |

---

## Search-Next by Attribute — `<Space>n`

Cycles through files in the current dir ordered by the given attribute.

| Key | Search by |
|-----|-----------|
| `<Space>nt` | Tag |
| `<Space>ns` | Size |
| `<Space>ni` | MIME type |
| `<Space>nc` | ctime |
| `<Space>nm` | mtime |
| `<Space>na` | atime |
| `<Space>ne` | Console: `jump_type <ext> [first\|last]` — jump to first/last file of a given extension |
| `<Space>nE` | Console pre-filled with `jump_type  last` — jump to the last file of a typed extension |
| `<Space>ng` | Jump to the first file of the next extension group in the listing |
| `<Space>nG` | Jump to the first file of the previous extension group in the listing |
| `<Space>nx` | Jump to the next file sharing the current file's extension (wraps) |
| `<Space>nX` | Jump to the previous file sharing the current file's extension (wraps) |

---

## Filter Stack

Compose complex filters. Active filters shown in statusbar.

| Key | Action |
|-----|--------|
| `.d` | Filter: directories only |
| `.f` | Filter: files only |
| `.l` | Filter: symlinks only |
| `.m` | Console: filter by MIME type |
| `.n` | Console: filter by name (regex) |
| `.#` | Console: filter by hash |
| `."` | Filter: duplicates |
| `.'` | Filter: unique files |
| `.\|` | Combine with OR |
| `.&` | Combine with AND |
| `.!` | Negate top filter |
| `.r` | Rotate filter stack |
| `.c` | Clear all filters |
| `.*` | Decompose current filter |
| `.p` | Pop top filter |
| `..` | Show current filter stack |
| `.t` | Console: filter by tag character (push tag filter onto stack) |
| `.T` | Console: filter by tag + flatten tree (see all tagged files in subtree) |
| `.s` | Console: filter by size (`>10M`, `<500K`, `=1G`, `!=100B`) |
| `.e` | Console: filter by extension (`py`, `mp4`, `rs`) |
| `.a` | Console: filter by age/mtime (`7` = last 7 days, `>30` = older) |

---

## Sorting

| Key | Sort By | Direction |
|-----|---------|-----------|
| `os` | size | ascending |
| `oS` | size | descending |
| `ob` | basename | ascending |
| `oB` | basename | descending |
| `on` | natural | ascending |
| `oN` | natural | descending |
| `om` | mtime | ascending |
| `oM` | mtime | descending |
| `oc` | ctime | ascending |
| `oC` | ctime | descending |
| `oa` | atime | ascending |
| `oA` | atime | descending |
| `ot` | type | ascending |
| `oT` | type | descending |
| `oe` | extension | ascending |
| `oE` | extension | descending |
| `oz` | random | — |
| `or` | toggle reverse | — |

---

## Tabs

Tabs live exclusively on the `alt` layer and Ctrl bindings. The `g` prefix is go-to only.

| Key | Action |
|-----|--------|
| `Ctrl-n` | New tab |
| `Ctrl-w` | Close tab |
| `Tab` | Next tab |
| `Shift-Tab` | Previous tab |
| `Alt-Right` | Next tab |
| `Alt-Left` | Previous tab |
| `Alt-1` … `Alt-9` | Jump to tab N |
| `Alt-r` | Shift tab right |
| `Alt-l` | Shift tab left |
| `uq` | Restore closed tab |

---

## Bookmarks

`m<any>` is a clean namespace — bookmark any single key character.

| Key | Action |
|-----|--------|
| `m<char>` | Set bookmark to key `<char>` |
| `` `<char> `` or `'<char>` | Jump to bookmark `<char>` |
| `um<char>` | Remove bookmark `<char>` |
| `m<Space>` | Show bookmark list |

Bookmarks persist across sessions. ` `` ` (backtick-backtick) jumps to last visited dir.

---

## Disk Usage — `<Space>d`

| Key | Action |
|-----|--------|
| `<Space>dc` | Calculate cumulative size of selection |
| `<Space>du` | `du --max-depth=1` — basic disk usage (paged) |
| `<Space>dU` | `dust` (or `du` sorted) — visual disk usage (paged) |
| `<Space>dn` | `ncdu` — interactive disk usage for current dir |
| `<Space>d/` | `ncdu` — interactive disk usage for `/` |
| `<Space>d~` | `ncdu` — interactive disk usage for `~` |
| `<Space>dd` | Interactive dedup — `rmlint` (preferred) or `fdupes`; review before delete |
| `<Space>df` | `df -h` (paged) |
| `<Space>dt` | `disk_top [N]` — N largest files under cwd |

---

## Preview — `<Space>p`

| Key | Action |
|-----|--------|
| `<Space>pp` | Toggle visual preview mode (images, video, PDF) on/off |
| `<Space>ps` | Peek — preview current file, auto-off on next navigation |
| `<Space>pa` | Pre-render video thumbnails for cwd in background, activates mode |
| `<Space>pc` | Clear all cached previews and free kitty image memory |
| `Alt-j` / `Alt-k` | Scroll the preview down / up |

Visual previews are **off by default**. Text, code, archives, JSON, markdown etc.
always preview regardless of this setting. `zi` also toggles image previews directly.

---

## Git — `<Space>g`

| Key | Action |
|-----|--------|
| `<Space>gg` | Open `lazygit` in current dir |
| `<Space>gb` | `git blame` on current file (paged) |
| `<Space>gd` | `git diff` on current file, paged through `delta` if available |
| `<Space>gl` | `git log --follow --oneline --stat` on current file (paged) |
| `<Space>gs` | `git status` in current dir (paged) |
| `<Space>ga` | `git add` the current selection |
| `<Space>gC` | Discard uncommitted working-tree changes to the selection (confirm-gated, irreversible) |

Directory previews automatically show `git log --oneline --graph` for git repos.

---

## SSH — `<Space>s`

| Key | Action |
|-----|--------|
| `<Space>ss` | Console: `ssh_mount [user@]host[:/path]` — mount remote via SSHFS, open in new tab |
| `<Space>sS` | Open interactive SSH shell to current mount's host |
| `<Space>su` | Unmount current SSHFS tab and close it |
| `<Space>sc` | Copy selection via `ssh host cat` — fallback when paste fails on an SSHFS-mounted file |

All SSHFS mounts are automatically cleaned up when ranger exits.
Tab-completes from `~/.ssh/config` Host entries.

`<Space>sc` bypasses the FUSE mount entirely by piping the file through a plain
`ssh host cat` command. Use it when regular paste (`pp`) fails on a file inside
an SSHFS mount with an error like "Operation not permitted" — this happens when
the remote sshd chroots its SFTP subsystem (what sshfs uses) more narrowly than
an interactive shell, and the file is a symlink pointing outside that chroot.
Directories in the selection are skipped; destination defaults to the current
local directory.

---

## Mount / Devices — `<Space>m`

| Key | Action |
|-----|--------|
| `<Space>mm` | `udisksctl mount -b <file>` — mount block device |
| `<Space>mu` | `udisksctl unmount -b <file>` — unmount block device |
| `<Space>ml` | `lsblk` — list block devices |
| `<Space>mM` | cd `/mnt` |
| `<Space>mi` | Loop-mount the selected ISO/img (`udisksctl loop-setup`) |
| `<Space>me` | Pick a removable device (fzf), unmount and power it off |

---

## Transfer — `<Space>t`

| Key | Action |
|-----|--------|
| `<Space>tm` | Console: `moveto` — move selection to typed dir (tab-completes) |
| `<Space>tc` | Console: `copyto` — copy selection to typed dir (tab-completes) |
| `<Space>tr` | Console: `rsync_to` — rsync selection to typed dest with progress |
| `<Space>td` | Console: `rsync_dry_run` — preview rsync without transferring (paged) |
| `<Space>tw` | Send selection via `croc` (preferred) or `magic-wormhole` |
| `<Space>tW` | Console: receive files via `croc` / `wormhole` (enter transfer code) |

`<Space>tw` suspends ranger and hands the terminal to croc/wormhole for interactive output.
Received files (`<Space>tW`) land in the currently viewed directory.

---

## Permissions (console) — `<Space>c`

See also the bare `=` and `+/-` quick bindings in [Permissions & Ownership](#permissions--ownership).

| Key | Action |
|-----|--------|
| `<Space>cm` | Console: `chmod <octal>` (e.g. `755`) |
| `<Space>co` | Console: `chown <user>[:<group>]` |
| `<Space>cR` | Console: `chmod_recursive <mode>` — `chmod -R` on selected dirs (confirm pattern) |
| `<Space>cO` | Console: `chown_recursive <user>[:<group>]` — recursive chown, confirm-gated like `<Space>cR` |

---

## Checksums — `<Space>h`

| Key | Action |
|-----|--------|
| `<Space>hs` | Show SHA-256 hash of selection (paged) |
| `<Space>hv` | Verify a checksum file (auto-detects sha256/sha512/sha1/md5 from extension) |
| `<Space>hc` | Copy SHA-256 hash of current file to Wayland clipboard |

`<Space>hv` without an argument opens fzf to pick a checksum file from cwd.
Supports `.sha256`, `.sha512`, `.sha1`, `.md5` (and their uppercase variants).

Console form accepts an optional algorithm: `:hash_show sha512` / `:hash_copy md5`
(sha256/sha1/sha512/md5; bare `<Space>hs`/`<Space>hc` still default to sha256).

---

## Encrypt / Decrypt — `<Space>e`

Uses `age` (preferred, modern) with a passphrase, falling back to `gpg -c` if age is unavailable.

| Key | Action |
|-----|--------|
| `<Space>ee` | Encrypt selection — creates `<file>.age` (or `.gpg`) |
| `<Space>ed` | Decrypt current file — auto-detects `.age` vs `.gpg` extension |
| `<Space>em` | Mount VeraCrypt container (`.hc`) — type mountpoint or Enter for temp |
| `<Space>eu` | Dismount a VeraCrypt volume (fzf picker) |

`<Space>ee` / `<Space>ed` hand the terminal to the encryption tool for interactive passphrase entry.
Output file is placed alongside the source file.

`<Space>em` works on the currently selected `.hc`/`.vc`/`.tc` file.  Type a path in
the console to use it as the mountpoint; press Enter with no input to auto-create
`$XDG_RUNTIME_DIR/vc/<name>`.  Ranger navigates to the mountpoint on success.
`<Space>eu` lists all mounted VeraCrypt slots via fzf and dismounts the chosen one;
auto-created temp dirs are removed after dismount.

---

## Trash / Bin — `<Space>b`

Higher-level trash management beyond the `x` / `Delete` bindings.

| Key | Action |
|-----|--------|
| `<Space>bl` | List trash contents with deletion date (paged) |
| `<Space>br` | Restore a file from trash (fzf picker) |
| `<Space>be` | Empty the entire trash (shows the count, asks y/N) |

Standard trashing still uses `x` / `Delete` (via `gio trash`). `<Space>be` calls
`gio trash --empty` with a manual fallback if gio is unavailable.

---

## Transform — `<Space>v`

In-place edits ask y/N when more than one file is involved or a JPEG/WebP would be
re-encoded lossily, run in the background, and report failures as notifications.
New outputs never overwrite an existing file (`name_1.ext`).

### Image — `<Space>vi` (ImageMagick / oxipng / jpegoptim)

| Key | Action |
|-----|--------|
| `<Space>vir` | Console: `image_resize <spec>` — resize in place (e.g. `50%`, `1920x`) |
| `<Space>vic` | Console: `image_convert <ext>` — convert to png/webp/jpg/avif/tiff |
| `<Space>vis` | Strip EXIF/XMP/IPTC metadata in place |
| `<Space>vio` | Optimize losslessly in place (oxipng / jpegoptim) |
| `<Space>via` / `<Space>viA` | Console: stack selected images vertically / horizontally into a new file |
| `<Space>vif` / `<Space>viF` | Flip vertically / mirror horizontally |
| `<Space>vit` | Trim uniform borders |
| `<Space>vin` | Negate colours |
| `<Space>viR` | Console: `image_rotate <degrees>` |

### Video / audio — `<Space>vv` (ffmpeg)

| Key | Action |
|-----|--------|
| `<Space>vvt` | Console: `video_transcode <ext>` — mp4/webm/mkv/mov/avi |
| `<Space>vva` | Console: `video_extract_audio <ext>` — mp3/aac/flac/wav/opus/ogg |
| `<Space>vvx` | Console: `video_trim <start> <duration>` (stream copy) |
| `<Space>vvg` | Console: `video_to_gif [fps [width]]` (default 10 fps, 480px) |
| `<Space>vvs` | Console: `video_snapshot [timestamp]` — one JPEG frame (default 00:00:05) |

### PDF — `<Space>vp`

| Key | Action |
|-----|--------|
| `<Space>vpm` | Console: `pdf_merge <output>` — merge selected PDFs |
| `<Space>vps` | Console: `pdf_split <start>-<end>` — extract a page range |
| `<Space>vpr` | Console: `pdf_rotate <90\|180\|270> [range]` |
| `<Space>vpc` | Console: `pdf_compress [screen\|ebook\|printer\|prepress]` |
| `<Space>vpo` | Console: `pdf_ocr [lang]` — add a text layer (ocrmypdf) |

### Name / organize — `<Space>vn`

| Key | Action |
|-----|--------|
| `<Space>vne` | Rename by EXIF DateTimeOriginal (`%Y%m%d_%H%M%S`) |
| `<Space>vnm` | Rename by mtime |
| `<Space>vns` | Move into `YYYY/MM/` subdirs by mtime (asks y/N) |

---

## LAN Serve — `<Space>l`

Serves over HTTP on the LAN interface only (never `0.0.0.0`). **No authentication** —
anyone on the LAN can read what's served until `<Space>lk`.

| Key | Action |
|-----|--------|
| `<Space>ll` | Serve the current directory (`miniserve`, else `python -m http.server`) |
| `<Space>lf` | Serve only the current file (python fallback: a private temp dir holding just that file) |
| `<Space>lq` | Send the current file via `qrcp` (QR code for phones) |
| `<Space>lk` | Stop the server |

---

## Flatten

| Key | Action |
|-----|--------|
| `zF` | **Visual flatten**: toggle flat view (depth 5) + hide directories. Files-only view of all nested content. Toggling off restores dirs. |
| `zW` | **Physical flatten**: move nested files (down to the given depth) from marked dirs into cwd, then remove only dirs left empty. Asks y/N. |

`zW` workflow:
1. Mark directories you want to flatten (`,` or `v`)
2. Press `zW` — shows how many files move and how many stay (deeper than the depth)
3. Answer `y` to execute; nothing that wasn't moved is deleted

---

## Shell & App Control

| Key | Action |
|-----|--------|
| `S` | Open `$SHELL` in current dir |
| `!` | Console: `shell ` (run arbitrary command) |
| `@` | Console: `shell %s` (run command on selection) |
| `#` | Console: `shell -p ` (run, pipe output to pager) |
| `:` / `;` | Open console |
| `<C-p>` | Open console + recall last command |
| `q` / `ZZ` / `ZQ` | Quit |
| `Q` | Quit all tabs |
| `<Space>q` | Quit |
| `<Space>z` | Zoxide jump (console: `z <query>`, tab-completes) |
| `W` | Display ranger log |
| `w` | Open task view |
| `~` | Toggle viewmode (miller ↔ multipane) |
| `Ctrl-r` | Reset ranger |
| `Ctrl-l` | Redraw window |
| `Ctrl-c` | Abort |
| `?` / `F1` | Help |
| `F2` / `F3` / `F4` | Rename (append) / view in pager / edit |
| `F5` / `F6` / `F7` / `F8` | Copy / cut / mkdir / delete |
| `F10` | Quit |

`q` and `Q` refuse while a copy/move is still running (`quit!` forces); `q` closes
the tab when more than one is open.

---

## Toggles & Settings

| Key | Action |
|-----|--------|
| `zh` / `Ctrl-h` | Toggle hidden files |
| `zc` | Toggle collapse preview |
| `zd` | Toggle dirs-first sorting |
| `zI` | Toggle input flush |
| `zi` | Toggle image previews |
| `zm` | Toggle mouse |
| `zp` | Toggle file previews |
| `zP` | Toggle directory previews |
| `zs` | Toggle case-insensitive sort |
| `zu` | Toggle auto cumulative size |
| `zv` | Toggle preview script |
| `zw` | Toggle word-wrap in plain text previews |
| `zn` | Cycle line numbers: off → absolute → relative (`set line_numbers!`) |
| `zF` | Smart flatten (visual flat view toggle) |
| `zW` | Physical flatten (flatten_write — moves files into cwd) |
| `~` | Toggle viewmode (miller ↔ multipane) |
| `F` | Freeze file list (stop I/O updates) |
| `R` | Reload current directory |

---

## Linemodes

Changes what is displayed next to each filename.

| Key | Linemode |
|-----|----------|
| `Mf` | Filename (default) |
| `Mi` | File info |
| `Mm` | Modification time |
| `Mh` | Human-readable mtime |
| `Mp` | Permissions |
| `Ms` | Size + mtime |
| `MH` | Size + human mtime |
| `Mt` | Meta title |

Active linemode: **devicons** (NerdFont icons, set as default).

---

## Chmod Quick Bindings

Pattern: `+<who><perm>` to add, `-<who><perm>` to remove.

```
+ur  +uw  +ux  +uX  +us  +ut   (user add)
+gr  +gw  +gx  +gX  +gs  +gt   (group add)
+or  +ow  +ox  +oX  +os  +ot   (other add)
+ar  +aw  +ax  +aX  +as  +at   (all add)
+r   +w   +x   +X   +s   +t    (shorthand = user add)

-ur  -uw  -ux  -uX  -us  -ut   (user remove)
-gr  -gw  -gx  -gX  -gs  -gt   (group remove)
-or  -ow  -ox  -oX  -os  -ot   (other remove)
-ar  -aw  -ax  -aX  -as  -at   (all remove)
-r   -w   -x   -X   -s   -t    (shorthand = user remove)
```

---

## Console Mode

Activated by `:` or `;`. Works like a vim command line.

### Navigation

| Key | Action |
|-----|--------|
| `↑` / `Ctrl-p` | Previous command in history |
| `↓` / `Ctrl-n` | Next command in history |
| `←` / `Ctrl-b` | Move cursor left |
| `→` / `Ctrl-f` | Move cursor right |
| `Home` / `Ctrl-a` | Jump to start of line |
| `End` / `Ctrl-e` | Jump to end of line |
| `Alt-b` / `Alt-←` | Move back one word |
| `Alt-f` / `Alt-→` | Move forward one word |
| `Tab` | Autocomplete |
| `Shift-Tab` | Autocomplete (reverse) |

### Editing

| Key | Action |
|-----|--------|
| `Backspace` / `Ctrl-h` | Delete char left |
| `Delete` / `Ctrl-d` | Delete char right |
| `Ctrl-w` | Delete word left |
| `Alt-d` | Delete word right |
| `Ctrl-k` | Delete to end of line |
| `Ctrl-u` | Delete to start of line |
| `Ctrl-y` | Paste deleted text |

### Execute / Exit

| Key | Action |
|-----|--------|
| `Enter` / `Ctrl-j` | Execute command |
| `Esc` / `Ctrl-c` / `Ctrl-g` | Close console |

---

## Pager Mode

Opened by `i`, `F3`, or commands with `-p` flag.

| Key | Action |
|-----|--------|
| `j` / `↓` / `Enter` | Down 1 line |
| `k` / `↑` | Up 1 line |
| `h` / `←` | Left |
| `l` / `→` | Right |
| `g` / `Home` | Top |
| `G` / `End` | Bottom |
| `d` / `Ctrl-d` | Down half page |
| `u` / `Ctrl-u` | Up half page |
| `n` / `f` / `Space` / `Ctrl-f` | Next page |
| `p` / `b` / `Ctrl-b` | Previous page |
| `q` / `Q` / `Esc` / `i` / `F3` | Close pager |
| `E` | Edit the file being viewed |

---

## Taskview Mode

Opened with `w`. Shows running background tasks.

| Key | Action |
|-----|--------|
| `j` / `↓` | Move down |
| `k` / `↑` | Move up |
| `g` / `Home` | Top |
| `G` / `End` | Bottom |
| `J` / `PgDn` | Move task priority down |
| `K` / `PgUp` | Move task priority up |
| `dd` / `Delete` | Remove task |
| `q` / `Q` / `w` / `Esc` | Close taskview |

---

## Console Commands & Aliases

### Built-in Aliases

| Alias | Expands To |
|-------|-----------|
| `e` | `edit` |
| `q` | `quit` |
| `q!` | `quit!` |
| `qa` / `qall` | `quitall` |
| `setl` | `setlocal` |
| `filter` | `scout -prts` |
| `find` | `scout -aets` |
| `mark` | `scout -mr` |
| `unmark` | `scout -Mr` |
| `search` | `scout -rs` |
| `search_inc` | `scout -rts` |
| `travel` | `scout -aefklst` |

### Custom Commands

| Command | Description |
|---------|-------------|
| `:fzf_select` | FZF search from cwd |
| `:fzf_home` | FZF search from $HOME |
| `:fzf_history` | FZF over cd history |
| `:trash` | Move selection to system trash (gio) |
| `:copy_path` | Copy full path to Wayland clipboard |
| `:copy_name` | Copy filename to Wayland clipboard |
| `:copy_name_no_ext` | Copy filename without extension to Wayland clipboard |
| `:copy_dir` | Copy current directory path to Wayland clipboard |
| `:yank_contents` | Copy file contents to Wayland clipboard (binary-safe) |
| `:extract` | Extract archive to named subdir |
| `:extract_here` | Extract archive flat into cwd |
| `:compress <name.ext>` | Compress selection |
| `:moveto <path>` | Move selection to path (tab-completes) |
| `:copyto <path>` | Copy selection to path (tab-completes) |
| `:rsync_to <dest>` | Rsync selection to dest with progress |
| `:mkcd <name>` | Create dir and cd into it |
| `:chmod <octal>` | Set permissions (e.g. `755`) |
| `:chown <user>[:<group>]` | Change ownership |
| `:rename_ext <ext>` | Change file extension |
| `:diff` | Diff 2 selected files in less |
| `:z <query>` | Zoxide jump (tab-completes from zoxide db) |
| `:ssh_mount <host>` | Mount remote via SSHFS |
| `:ssh_shell` | Open SSH shell to current mount's host |
| `:ssh_unmount` | Unmount current SSHFS tab |
| `:ssh_copy [dest]` | Copy selection out of an SSHFS mount via `ssh host cat` (chroot fallback) |
| `:smart_flatten` | Toggle visual flat view with files-only filter |
| `:flatten_write [confirm]` | Physical flatten selected dirs into cwd |
| `:preview_toggle` | Toggle visual preview mode |
| `:preview_peek` | Peek at current file (auto-off on next nav) |
| `:preview_render_all` | Pre-render video thumbnails for cwd in background |
| `:preview_clear` | Flush preview cache and clear kitty image |
| `:trash_list` | List trash contents in pager |
| `:trash_restore` | Restore file from trash via fzf picker |
| `:trash_empty [confirm]` | Empty trash (confirm pattern) |
| `:hash_show` | Show SHA-256 of selection in pager |
| `:hash_verify [file]` | Verify checksum file (auto-detects algorithm) |
| `:hash_copy` | Copy SHA-256 of current file to clipboard |
| `:encrypt_file` | Encrypt selection with age / gpg |
| `:decrypt_file` | Decrypt `.age` / `.gpg` file |
| `:veracrypt_mount [path]` | Mount `.hc` container; omit path for auto temp dir |
| `:veracrypt_umount` | Dismount VeraCrypt volume via fzf slot picker |
| `:wl_paste_file` | Paste clipboard content as file in cwd |
| `:wormhole_send` | Send selection via croc / magic-wormhole |
| `:wormhole_recv [code]` | Receive files via croc / wormhole into cwd |
| `:chmod_recursive <mode> [confirm]` | `chmod -R` on selected dirs (confirm pattern) |

### F-Key Bindings (Midnight Commander style)

| Key | Action |
|-----|--------|
| `F1` | Help |
| `F2` | Rename (append) |
| `F3` | Display file |
| `F4` | Edit |
| `F5` | Copy |
| `F6` | Cut |
| `F7` | mkdir |
| `F8` | Delete |
| `F10` | Exit |
