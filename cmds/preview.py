from __future__ import (absolute_import, division, print_function)
import glob
import mimetypes
import os
import subprocess
from hashlib import sha1
from ranger.api.commands import Command
from cmds._util import run_bg


class preview_toggle(Command):
    """:preview_toggle  (<Space>pp)

    Toggle visual preview mode (images, video, PDF) on or off.
    """

    def execute(self):
        mode = not getattr(self.fm, 'preview_mode', False)
        self.fm.preview_mode = mode
        self.fm._preview_peek = False
        self.fm.settings.preview_images = mode
        self.fm.ui.need_redraw = True
        # Notification comes from cmd_feedback.py via setopt.preview_images signal.


class preview_peek(Command):
    """:preview_peek  (<Space>ps)

    Preview the file under the cursor. Auto-disables on the next navigation.
    """

    def execute(self):
        self.fm._preview_peek = True
        self.fm.preview_mode = True
        self.fm.settings.preview_images = True
        self.fm.ui.need_redraw = True


class preview_clear(Command):
    """:preview_clear  (<Space>pc)

    Flush the in-memory preview cache and delete thumbnail files from
    ~/.cache/ranger, then clear the kitty image from the terminal.
    """

    def execute(self):
        cache_dir = os.path.expanduser('~/.cache/ranger')
        self.fm.previews.clear()
        count = 0
        for f in glob.glob(os.path.join(cache_dir, '*.jpg')):
            try:
                os.remove(f)
                count += 1
            except OSError:
                pass
        try:
            preview_col = self.fm.ui.browser.columns[-1]
            preview_col.clear_image(force=True)
            preview_col.need_redraw = True
        except (AttributeError, IndexError):
            pass
        self.fm.ui.need_redraw = True
        self.fm.notify("Cleared {} cached preview(s)".format(count))


class preview_render_all(Command):
    """:preview_render_all  (<Space>pa)

    Pre-generate thumbnails for all video files in the current directory
    using ffmpegthumbnailer. Runs in a background thread; activates preview
    mode immediately so you can browse while generation is in progress.

    Thumbnails are stored in ~/.cache/ranger/<sha1>.jpg — the same path
    scope.sh writes to — so on the next hover scope.sh detects the fresh
    file and exits immediately without re-running ffmpegthumbnailer.
    """

    _VIDEO_EXTS = frozenset(
        '.mp4 .mkv .avi .mov .wmv .flv .webm .m4v .ts .mts .m2ts '
        '.3gp .ogv .asf .rm .rmvb .divx .mpg .mpeg .vob .f4v'.split()
    )

    def execute(self):
        VIDEO_EXTS = self._VIDEO_EXTS
        cache_dir = os.path.expanduser('~/.cache/ranger')
        os.makedirs(cache_dir, exist_ok=True)

        file_infos = [
            (f.path, f.mimetype)
            for f in self.fm.thisdir.files
            if not f.is_directory
        ]
        fm = self.fm

        def _cache_path(path):
            realpath = os.path.realpath(path)
            return os.path.join(
                cache_dir,
                sha1(realpath.encode('utf-8', 'backslashreplace')).hexdigest() + '.jpg'
            )

        def _is_video(path, mime):
            m = mime or mimetypes.guess_type(path)[0] or ''
            ext = os.path.splitext(path)[1].lower()
            return m.startswith('video/') or ext in VIDEO_EXTS

        def _generate(_ui):
            # Worker thread: file work only — fm/ui are touched in _done.
            done = skipped = errors = 0
            for path, mime in file_infos:
                if not _is_video(path, mime):
                    continue
                cache = _cache_path(path)
                try:
                    if (os.path.isfile(cache) and
                            os.path.getmtime(cache) >= os.path.getmtime(path)):
                        skipped += 1
                        continue
                except OSError:
                    pass
                r = subprocess.run(
                    ['ffmpegthumbnailer', '-i', path, '-o', cache,
                     '-s', '0', '-t', '20%'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                if r.returncode == 0:
                    done += 1
                else:
                    errors += 1
            return done, skipped, errors

        def _done(result, error):
            if isinstance(error, FileNotFoundError):
                fm.notify("ffmpegthumbnailer not installed", bad=True)
                return
            if error is not None:
                fm.notify("Thumbnails: {}".format(error), bad=True)
                return
            done, skipped, errors = result
            fm.previews.clear()
            fm.ui.need_redraw = True
            parts = []
            if done:
                parts.append("{} rendered".format(done))
            if skipped:
                parts.append("{} already cached".format(skipped))
            if errors:
                parts.append("{} failed".format(errors))
            fm.notify("Thumbnails: " + (", ".join(parts) if parts else "no video files found"))

        video_count = sum(1 for p, m in file_infos if _is_video(p, m))
        if video_count == 0:
            self.fm.notify("No video files in current directory")
            return

        self.fm.preview_mode = True
        self.fm.settings.preview_images = True
        self.fm.ui.need_redraw = True
        self.fm.notify("Rendering {} video thumbnail(s)…".format(video_count))

        run_bg(fm, 'Rendering thumbnails', _generate, _done)
