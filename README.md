# ranger config

A [ranger](https://github.com/ranger/ranger) configuration built around a
`<Space>` leader: about a hundred extra commands (archives, trash, checksums,
encryption, SSHFS, block devices, image/video/PDF batch edits, LAN sharing,
clipboard paths, git, fuzzy navigation), discoverable through labelled key
hints, plus a file-picker mode that turns ranger into the "Open"/"Save" dialog
of desktop apps via `xdg-desktop-portal-termfilechooser`.

It is meant as a base to fork: everything is plain ranger config and Python,
every external tool is optional and checked before use, and nothing destructive
happens without a y/N question.

- [Requirements](#requirements)
- [Install](#install)
- [What you get](#what-you-get)
- [Layout](#layout)
- [Architecture](#architecture)
- [Design rules](#design-rules)
- [Gotchas](#gotchas)
- [File picker](#file-picker)
- [Colors and wallust](#colors-and-wallust)
- [Customizing](#customizing)
- [Tests](#tests)
- [License](#license)

The full key reference is in [KEYBINDS.md](KEYBINDS.md).

---

## Requirements

**Required**

- ranger 1.9.3 or newer (developed against 1.9.4), Python 3.7+.
  No Python packages beyond the standard library and ranger itself.
- `fzf` and `fd`: the fuzzy finders and every picker (devices, trash,
  checksums, VeraCrypt slots) use fzf.

**Recommended**

- A [Nerd Font](https://www.nerdfonts.com/) in the terminal: the default
  linemode is `devicons` (`plugins/devicons.py`). Without one the icons show
  as boxes; switch to `default_linemode filename` at the end of `rc.conf`.
- `zoxide`: `<Space>z`/`<Space>fz` jumps, and `plugins/zoxide.py` feeds every
  directory change into the zoxide database (silently skipped when missing).
- `bat`, `rg` (ripgrep), `bsdtar` (libarchive), a clipboard tool
  (`wl-clipboard` on Wayland, `xclip` or `xsel` on X11).
- Image previews use the kitty graphics protocol (`preview_images_method
  kitty`), which needs Pillow (`python-pillow`). Previews are off by default;
  `<Space>pp` toggles them. Change the method in `rc.conf` for other terminals.

**Optional, per feature** (each command reports a missing tool instead of failing)

| Area | Tools |
|---|---|
| Archives | `bsdtar`, `zip`, `7z`, `gzip`/`bzip2`/`xz`/`zstd`, `pv`, `archivemount` (for `<Space>aep`) |
| Trash | `gio` (falls back to a built-in XDG trash implementation) |
| Disk | `ncdu`, `dust`, `rmlint` or `fdupes` |
| Mounts | `sshfs` + `fusermount3`, `udisksctl` + `lsblk`, `veracrypt` |
| Transfer | `rsync`, `croc` or `magic-wormhole`, `qrcp`, `miniserve` (else `python3 -m http.server`) |
| Crypto | `age` or `gpg` |
| Transform | ImageMagick 7 (`magick`/`mogrify`), `oxipng`, `jpegoptim`, `ffmpeg`, `ffmpegthumbnailer`, `qpdf`, `pdfunite`, `gs`, `ocrmypdf`, `exiftool` |
| Inspect | `exiftool`, `mediainfo`, `jq`, `hexyl` or `xxd`, `difft`, `delta`, `lazygit` |
| Desktop | `ripdrag` or `dragon-drop`, a GUI file manager, `xdg-open` |
| Previews (`scope.sh`) | `bat`, `glow`, `pdftotext`/`pdftoppm`, `mediainfo`, `fontimage`, `sqlite3`, … (same idea as ranger's stock `scope.sh`) |

## Install

```sh
mv ~/.config/ranger ~/.config/ranger.bak 2>/dev/null   # keep your old config
git clone https://github.com/md-racc/ranger.git ~/.config/ranger
```

`rc.conf` is a complete copy of ranger's defaults plus the additions, so set
`RANGER_LOAD_DEFAULT_RC=FALSE` in your shell profile to skip loading the
stock file first (optional, it only saves a little startup time).

To try it without replacing your config, clone it elsewhere and point
ranger at the clone:

```sh
git clone https://github.com/md-racc/ranger.git ~/src/ranger-config
ranger --confdir=~/src/ranger-config
```

Everything, including the preview script, is resolved relative to the config
directory, so a clone used with `--confdir` is self-contained. ranger's data
(bookmarks, history, tabs) still goes to `~/.local/share/ranger`; add
`--datadir=<dir>` to keep that separate too.

## What you get

`<Space>` opens a hint menu with a label for every key; each letter is a group:

| Leader | Group | Examples |
|---|---|---|
| `<Space>a` | Archives | `aes` smart extract (no double nesting), `aep` pick entries via archivemount, `acz` compress, `aci*` one archive per item, `au` zip & upload (picker) |
| `<Space>b` | Trash | `bl` browse, `br` restore, `be` empty; `x` trashes, `uu` undoes the last trash |
| `<Space>c` | Permissions | `cm` chmod, `co` chown, `cR`/`cO` recursive |
| `<Space>d` | Disk | `dc` size, `du`/`dU`/`dn` du, dust, ncdu, `dd` dedup, `df` free space, `dt` largest files |
| `<Space>e` | Encryption | `ee`/`ed` age or gpg, `em`/`eu` VeraCrypt |
| `<Space>f` | Find | `ff`/`fh` fzf in cwd / home, `fr` recent dirs, `fR` recent files, `fz` zoxide, `fg` ripgrep into the editor's quickfix |
| `<Space>g` | Git | `gg` lazygit, `gd` diff, `gb` blame, `gl` log, `ga` add, `gC` discard |
| `<Space>h` | Checksums | `hs` show, `hv` verify, `hc` copy |
| `<Space>l` | LAN serve | `ll` serve cwd, `lf` one file, `lq` QR code, `lk` stop |
| `<Space>m` | Devices | `mm`/`mu` mount/unmount (fzf), `me` eject, `mi` loop-mount an ISO |
| `<Space>n` | Next by attribute | tag, size, mime, times, extension groups |
| `<Space>o` | Open / inspect | xdg-open, mpv, stat, exiftool, jq, hexdump, project in `$EDITOR`, terminal here, drag-out |
| `<Space>p` | Visual preview | `pp` toggle, `ps` peek one file, `pa` pre-render video thumbnails |
| `<Space>s` | SSH | `ss` mount over SSHFS in a new tab, `sS` shell, `su` unmount, `sc` copy via `ssh cat` |
| `<Space>t` | Transfer | move/copy (never overwrite), rsync (+dry run), croc/wormhole |
| `<Space>v` | Transform | `vi*` images, `vv*` video/audio, `vp*` PDF, `vn*` rename by date |
| `<Space>y` | Clipboard | path, name, dir, relative / git-relative path, Markdown link, file contents, paste to file |

Outside the leader: a `.` filter stack (type, mime, name, size, extension,
age, tags, duplicates), `zF`/`zW` flatten views, `md` mkdir+cd (optionally
moving the selection in), vim-style incremental `/` with `<C-n>`/`<C-p>`,
`:42` jumps to line 42, and notifications for every setting toggle.

## Layout

| Path | Purpose |
|---|---|
| `rc.conf` | Settings and every key binding (stock defaults + custom section at the end) |
| `rifle.conf` | File openers (editor split vim/nvim, mpv, zathura, xdg-open fallback, …) |
| `scope.sh` | Preview script; images/video/PDF only when previews are enabled |
| `commands.py` | Thin loader: puts this directory on `sys.path` and star-imports `cmds/*` |
| `cmds/` | Custom commands, one module per area (see below) |
| `plugins/` | UI patches and hooks loaded by ranger at startup |
| `colorschemes/` | `wallust` (ANSI slots, optional wallust palette) and `quiet` (256-colour) |
| `contrib/wallust/` | wallust template for the colorscheme and a safe reload helper |
| `tests/` | Headless unit tests, wrapper-contract and tmux end-to-end picker suites (need `PICKER_WRAPPER`), a manual portal smoke test |
| `KEYBINDS.md` | Full key reference (kept in sync with `rc.conf`) |

`cmds/`:

| Module | Commands |
|---|---|
| `_util.py` | Shared helpers: `ask_yes`, `run_bg`, `unique_dest`, `transfer_items`, `require_tool`, `get_selection`, pagers, clipboard, sshfs mount bookkeeping |
| `nav.py` | fzf finders, zoxide `:z`, recent files, `mkcd`, `smart_flatten`/`flatten_write`, `rg_content_search`, extension navigation |
| `trash.py` | `trash` (gio, else XDG trash), `undo_trash`, `trash_list`/`restore`/`empty` |
| `clipboard.py` | path/name/dir copies, `yank_contents`, `wl_paste_file` |
| `archives.py` | `extract*`, `compress*`, `archive_list`/`test`, `extract_pick` |
| `picker.py` | File-picker mode: `enter_or_pick`, `escape_or_cancel`, `pick_save`, `pick_location`, `pick_selection`, `pick_archive` |
| `files.py` | `touch`, `rename_ext`, `diff`, `dedup`, `disk_top` |
| `transfer.py` | `moveto`, `copyto`, `rsync_to`, `rsync_dry_run`, `wormhole_send`/`recv` |
| `ssh.py` | `ssh_mount`/`shell`/`unmount`/`copy`, plus `quit`/`quitall` overrides that release mounts |
| `perms.py` | `chmod`, `chown`, recursive variants |
| `preview.py` | `preview_toggle`/`peek`/`clear`/`render_all` |
| `security.py` | `hash_show`/`verify`/`copy`, `encrypt_file`/`decrypt_file`, VeraCrypt |
| `network.py` | `lan_serve`, `lan_serve_file`, `lan_qr`, `lan_kill` |
| `transform.py` | image / video / PDF / rename batch operations |
| `open_here.py` | `open_project`, `spawn_terminal`, `open_filemanager`, `hexdump`, `cd_git_root`, `dir_diff`, `drag_out` |
| `filter_ext.py` | Extra filter-stack types (tag, size, extension, age) and their commands |
| `git.py` | `git_diff`, `git_discard` |
| `mount.py` | `device_mount`/`unmount`/`eject`, `iso_mount` |
| `search.py` | `vim_search` |

`plugins/`:

| Plugin | What it does |
|---|---|
| `space_hints.py` | Replaces the key-hint overlay: labels for every key, multi-column layout, never draws over the image preview, `Esc` walks back one level |
| `keybuffer_statusbar.py` | Shows the pending key sequence in the status bar after the mtime |
| `cmd_feedback.py` | Notifies on every setting change (`zh` → "Hidden files: shown") |
| `preview_mode.py` | Peek auto-off on the next move, clears image previews on directory change and resize |
| `picker_mode.py` | Picker banner, open-action routing per mode, save-mode "ghost" row, newest-first start (no-op outside a picker) |
| `ssh_cleanup.py` | Sweeps stale sshfs mounts at startup; makes SIGTERM run the exit cleanup |
| `devicons.py` | Nerd Font icons linemode |
| `zoxide.py` | `zoxide add` on every directory change |
| `goto_line.py` | `:42` moves to line 42 |
| `vim_search.py` | `<C-n>`/`<C-p>` step through matches while typing a `/` search |

## Architecture

**Loading.** ranger imports `commands.py` with `importlib`, which does not put
the config directory on `sys.path`. The loader inserts it, then star-imports
each `cmds/` module, so ranger registers every `Command` subclass it finds.
Plugins are imported afterwards (alphabetically), so a plugin may import from
`cmds` at module level.

**Commands** are small `ranger.api.commands.Command` subclasses. Shared
behaviour lives in `cmds/_util.py` rather than being repeated: selection
checks, tool checks, collision-free names, confirmation, background work.

**Plugins** patch ranger classes (`ViewBase._draw_hints`, `StatusBar.draw`,
`TitleBar._get_left_part`, `Actions.execute_file`, `BrowserColumn`, …) or chain
`ranger.api.hook_init`/`hook_ready`. Every hook calls the previous one first, so
plugins compose regardless of load order.

**Background work.** `run_bg(fm, descr, work, done)` runs `work(ui)` on its own
thread. A single shared loader item (`_BgPump`) services all running jobs from
ranger's main loop, so jobs run in parallel and appear as one entry in the task
view (`w`). Workers never touch `fm` or the UI directly: they queue calls with
`ui(fn, *args)`, and `done(result, error)` runs on the UI thread. Without a
loader (headless tests) `run_bg` runs synchronously.

**SSHFS mounts** live under `/tmp/ranger-sshfs/<target>`. Each mount has a
`<mount>.pid` file listing every ranger using it (flock-guarded), so several
rangers can share a mount and only the last one unmounts it. `quit`/`quitall`
and an `atexit` hook release mounts; `ssh_cleanup.py` turns SIGTERM into a
normal exit and unmounts leftovers from crashed sessions at startup.

**File picker** — see [File picker](#file-picker).

## Design rules

These hold for every command; please keep them when adding new ones.

- **Ask before destroying.** Destructive or lossy operations call
  `ask_yes(fm, prompt, on_yes)`: a y/N question in the console where Enter and
  Esc mean no. Never pre-fill the console with `cmd confirm` instead: it lands
  in the console history and `<C-p>` replays it. Commands that take a
  `confirm` argument use it only to skip the question from scripts.
- **Never overwrite silently.** New outputs go through `unique_dest` (`name_1.ext`,
  …; compound archive suffixes like `.tar.gz` are kept whole), extraction uses
  `bsdtar -k`, moves and copies rename on collision and report it.
- **No shell injection.** Pass file names as argv lists, or `shlex.quote` them.
  Never put a name inside `"…"` in an `sh -c` string. Shell snippets that need
  names take them as positional parameters (`$1`, `$2`).
- **Check tools first.** `require_tool(fm, 'name')` notifies and returns False
  when a program is missing, instead of a traceback.
- **Keep curses intact.** Interactive programs (fzf, pagers, editors) run
  through `fm.run(...)`, which suspends the UI. Feed fzf through temp files
  (`fzf < in > out`) rather than pipes from `Popen`, and don't pass `--height`
  (fzf must use the alternate screen).
- **Slow work off the UI thread** with `run_bg`; the worker touches only files.
- **Report per item.** Batch operations continue past a failing item and report
  counts and the first few errors at the end.

## Gotchas

- **Single-key prefixes.** Mapping `]e` turns `]` into a prefix, so `]` alone
  stops working. Before adding a multi-key map under an existing single-key
  binding, check that the shorter binding is not lost.
- **Hint labels.** `plugins/space_hints.py` has two tables. `_KEY_LABELS` names
  every key and always applies. `_SUBMAP_LABELS` only applies when a submap has
  more hints than `hint_collapse_threshold` (10) *and* several keys share a
  first character, which then collapse into one labelled entry (`<Space>v` →
  `i` Image, `v` Video, …). New groups usually only need `_KEY_LABELS`.
- **Plugins import functions, not commands.** ranger also registers every
  `Command` class it finds in a plugin module's namespace, so keep command
  classes out of plugins: `picker_mode.py` imports only functions from
  `cmds.picker`.
- **Esc in the key-hint overlay.** ranger dispatches a lone Esc as two key
  events and clears the key buffer after the first; `space_hints.py` therefore
  replays the parent submap from the next draw instead of from `press()`.
- **Colorscheme reload.** The `wallust` colorscheme installs a SIGUSR2 handler
  that clears ranger's cached colour lookups and every file's cached
  `display_data`, then redraws. SIGUSR2 kills a ranger that has not loaded the
  colorscheme yet, so signal only rangers that catch it
  (`contrib/wallust/ranger-reload` checks `SigCgt` in `/proc`).
- **ranger's loader runs only its first item.** One loader item per background
  job would serialise them (a quick image op waiting behind a long extract);
  hence the single shared `_BgPump`.
- **croc receive.** The code goes in `CROC_SECRET`, not as a positional
  argument: croc parses positional words as subcommand names and exits
  silently.
- **LAN server.** It binds the LAN address only (never `0.0.0.0`), refuses to
  start when there is none, and has no authentication. The PID lives in
  `$XDG_RUNTIME_DIR/ranger_lan_server.pid`.
- **Filter stack persists.** `clear_filters_on_dir_change` is false, so filters
  pushed with `.` follow you into other directories until `.c` clears them.
  Easy to mistake for missing files.
- **`flushinput` is on.** ranger drops keys queued behind the one being
  handled, so scripted input (tmux `send-keys`) must arrive one key at a time.
- **Tests and plugins.** Importing `plugins/picker_mode.py` in a picker mode
  patches ranger classes globally. Tests that load it restore the patches with
  `tests/_fakes.py::snapshot_plugin_patches`.

## File picker

With [xdg-desktop-portal-termfilechooser](https://github.com/hunkyburrito/xdg-desktop-portal-termfilechooser),
applications that use the FileChooser portal (Firefox, Chromium, GTK and Qt
apps configured for portals) open ranger in a terminal as their file dialog.
This config adds a picker mode on top: a title-bar banner, `⏎` as the
"finish" key, multi-file uploads with folders flattened, zip-and-upload,
a save dialog that never overwrites without asking, and `<C-l>` to type a path.
How it behaves is documented in [KEYBINDS.md](KEYBINDS.md#file-picker-portal-dialogs).

### Setup

1. Install `xdg-desktop-portal-termfilechooser` and make it the FileChooser
   backend, e.g. in `~/.config/xdg-desktop-portal/portals.conf`:

   ```ini
   [preferred]
   org.freedesktop.impl.portal.FileChooser=termfilechooser
   ```

2. Write a wrapper script that follows the [wrapper contract](#wrapper-contract)
   below (no wrapper ships with this config) and point the portal at it in
   `~/.config/xdg-desktop-portal-termfilechooser/config`:

   ```ini
   [filechooser]
   cmd=/path/to/your-wrapper.sh
   default_dir=$HOME/Downloads
   env=TERMCMD=kitty --class termfilechooser
   open_mode=suggested
   save_mode=suggested
   ```

   The terminal command must block until ranger exits. Giving the window a
   class (as above) lets a window-manager rule float and size the dialog; for
   a Hyprland setup, see [md-racc/hypr](https://github.com/md-racc/hypr).

3. Restart the portal service (or log out and back in) and make sure your
   apps use the portal (Firefox: `widget.use-xdg-desktop-portal.file-picker = 1`;
   GTK apps may need `GTK_USE_PORTAL=1`).

`python tests/portal_smoke.py open|multi|dir|save` asks the real portal for a
dialog and prints what comes back.

### Wrapper contract

The wrapper replaces the stock `ranger-wrapper.sh` that ships with
termfilechooser. The portal calls it with the arguments
`<multiple> <directory> <save> <path> <out> <debug>` (each flag `0` or `1`); it
must export

| Variable | Value |
|---|---|
| `RANGER_PICKER` | `open`, `multi`, `dir` or `save` |
| `RANGER_PICKER_OUT` | the `<out>` file the portal reads the result from |
| `RANGER_PICKER_PATH` | `<path>`: the start folder, or in save mode the placeholder file the portal created |
| `RANGER_PICKER_TOKEN` | optional: a fresh temp file owned by the user (see below) |

and start `$TERMCMD ranger` with exactly these arguments (quote them: paths
can contain spaces and shell metacharacters):

| Mode | ranger arguments |
|---|---|
| open | `--choosefile=<out> <path>` |
| multi | `--choosefiles=<out> <path>` |
| dir | `--show-only-dirs <path>` (no `--choosedir`) |
| save | `--selectfile=<path>` (no `--choosefile`) |

In dir and save mode only `cmds/picker.py` writes `<out>`, so quitting ranger
always means "cancel". The terminal keeps the `RANGER_PICKER*` variables in its
environment, so a ranger started later from another window of that terminal
would inherit them. `picker.py` therefore trusts them only when ranger's own
arguments match the mode, and, if `RANGER_PICKER_TOKEN` is set, only when that
token file exists, is a regular file owned by the user, and can be consumed
(deleted) at startup. The variables are removed from ranger's environment so
shells and programs started from the picker don't inherit them. A wrapper
creates the token with `mktemp` before starting the terminal and removes it
on exit in case ranger never started.

`tests/test_wrapper.py` checks a wrapper against this contract:
`PICKER_WRAPPER=/path/to/your-wrapper.sh python -m unittest tests.test_wrapper -v`.

Without the custom wrapper (stock wrapper) the picker still works through
ranger's own `--choose*` flags, but save dialogs then behave like open dialogs.

**Portal limitations:** termfilechooser does not pass file-type filters,
dialog titles or choices to the wrapper, and has no `SaveFiles` support.

## Colors and wallust

`set colorscheme wallust` is the default because it works everywhere: it only
uses ANSI colour slots 0–8, so it follows whatever palette the terminal has
(directories in slot 4, links in 6, marked files in 3, muted text in 8).
Nothing else is needed; [wallust](https://codeberg.org/explosion-mental/wallust)
is optional (a matching wallust configuration lives in
[md-racc/wallust](https://github.com/md-racc/wallust)).

With wallust, add `contrib/wallust/ranger-colors.py` as a template (target
`~/.cache/wallust/ranger-colors.py`, instructions in the file). The colorscheme
then applies the exact RGB values via `curses.init_color` (when the terminal
allows it) and reads optional per-scheme `ROLES`: which slot directories,
links, marks and the active tab use, and an optional solid `fill` colour for
the cursor bar. Run `contrib/wallust/ranger-reload` after a theme change (for
example as a wallust hook) to repaint running rangers.

`set colorscheme quiet` is a fixed dark 256-colour palette after Vim's
`quiet` colorscheme, if you prefer colours that don't depend on the terminal.

## Customizing

- **Places.** `gD`, `gO`, `gX` at the end of `rc.conf` jump to `~/Downloads`,
  `~/Documents` and `~/.config`. If you change `gD`, update the picker banner
  hint (`_EXTRAS` in `plugins/picker_mode.py`) and its label in
  `plugins/space_hints.py`.
- **Programs.** Commands honour `$EDITOR`/`$VISUAL`, `$PAGER`, `$TERMINAL`
  (new terminal windows; else the first of kitty, foot, alacritty, wezterm,
  gnome-terminal, xfce4-terminal, xterm) and `$FILE_MANAGER`. Under Hyprland
  new terminals open floating via `hyprctl`.
- **Openers.** `rifle.conf` opens light text formats in vim and code in nvim;
  adjust the two `ext …` lines near the top.
- **Adding a command:**
  1. Write a `Command` subclass in the matching `cmds/` module (or a new
     module, star-imported from `commands.py`), following the
     [design rules](#design-rules).
  2. Bind it in the custom section of `rc.conf`.
  3. Give the key a label in `_KEY_LABELS` in `plugins/space_hints.py`.
  4. Document it in `KEYBINDS.md`.
  5. Add a headless test if it touches files (`tests/_fakes.py` has a
     minimal fake `fm`).

## Tests

```sh
python -m unittest discover -s tests -v                          # headless unit tests
PICKER_WRAPPER=/path/to/wrapper python -m unittest tests.e2e_picker -v   # tmux + ranger
python tests/portal_smoke.py save                                # manual, real portal dialog
```

The unit tests run against this checkout with fake `fm` objects and temp
directories. The wrapper-contract tests (`tests/test_wrapper.py`, part of the
discover run) and the end-to-end suite need `PICKER_WRAPPER` pointing at your
portal wrapper and are skipped without it. The end-to-end suite drives real
ranger instances through that wrapper in a private tmux server, using this
checkout's config via a `ranger --confdir` shim and temporary data, cache and
zoxide directories.

## License

MIT, see [LICENSE](LICENSE), except for the third-party files below.

**Third-party files**

- `rc.conf`, `rifle.conf` and `scope.sh` derive from
  [ranger](https://github.com/ranger/ranger)'s default configuration files and
  keep ranger's licence, GPL-3.0.
- `plugins/devicons.py` derives from
  [ranger_devicons](https://github.com/alexanderjeurissen/ranger_devicons)
  (icon mapping from vim-devicons) and keeps its licence, GPL-3.0.

Everything else is MIT. `colorschemes/quiet.py` only borrows the colour values
of Vim's `quiet` colorscheme.
