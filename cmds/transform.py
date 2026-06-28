from __future__ import (absolute_import, division, print_function)
import os
import shlex
import shutil
import subprocess
import time
from ranger.api.commands import Command
from cmds._util import ask_yes, get_selection, require_tool, run_bg, unique_dest


def _invalidate_preview(fm):
    """Clear cached previews so an in-place edit's new content shows immediately."""
    fm.previews.clear()
    fm.ui.need_redraw = True


def _run_ffmpeg_batch(fm, sel, build_cmd, label):
    """Run one ffmpeg invocation per selected file, sequentially, via fm.run().

    build_cmd(f) -> shell command string for file f.
    label: verb used in the pre-flight notify, e.g. 'Transcoding'.
    """
    if not require_tool(fm, 'ffmpeg'):
        return
    parts = [build_cmd(f) for f in sel]
    fm.notify('{} {} file(s)…'.format(label, len(parts)))
    fm.run(' && '.join(parts))
    fm.reload_cwd()


# ── Image ops  (<Space>vi*) ───────────────────────────────────────────────────

# Formats that ImageMagick re-encodes lossily when it rewrites a file.
_LOSSY_EXTS = frozenset({'jpg', 'jpeg', 'jfif', 'webp', 'avif', 'heic', 'heif'})


def _is_lossy(path):
    return os.path.splitext(path)[1].lstrip('.').lower() in _LOSSY_EXTS


def _confirm_then(fm, files, prompt, action, lossy=True):
    """Run action() right away for one lossless file; otherwise ask y/N first.

    lossy: whether the operation re-encodes (mogrify does; jpegoptim/oxipng
    and renames don't)."""
    lossy_files = [f for f in files if lossy and _is_lossy(f)]
    if len(files) <= 1 and not lossy_files:
        action()
        return
    text = prompt.format(n=len(files))
    if lossy_files:
        text += ' — re-encodes {} JPEG/WebP file(s) lossily'.format(len(lossy_files))
    ask_yes(fm, text, action)


def _run_jobs(fm, descr, jobs, ok_msg, inplace=False):
    """Run each argv in `jobs` in the background, one after another.

    stdout/stderr are captured (nothing draws over curses); failures are
    collected and reported once on the UI thread, then the listing reloads.
    """
    def work(_ui):
        failed = []
        for argv in jobs:
            try:
                r = subprocess.run(argv, stdin=subprocess.DEVNULL,
                                   capture_output=True, text=True, errors='replace')
            except OSError as ex:
                failed.append(str(ex))
                continue
            if r.returncode != 0:
                err = (r.stderr or r.stdout).strip().splitlines()
                failed.append(err[-1] if err else '{} exited {}'.format(argv[0], r.returncode))
        return failed

    def done(failed, error):
        if error is not None:
            failed = [str(error)]
        if failed:
            fm.notify('{}: {} of {} failed — {}'.format(
                descr, len(failed), len(jobs), failed[0]), bad=True)
        else:
            fm.notify(ok_msg)
        if inplace:
            _invalidate_preview(fm)
        fm.reload_cwd()

    fm.notify('{}…'.format(descr))
    run_bg(fm, descr, work, done)


def _mogrify_inplace(cmd, args, verb):
    """Shared body for the in-place mogrify commands."""
    sel = get_selection(cmd.fm)
    if sel is None:
        return
    if not require_tool(cmd.fm, 'magick'):
        return
    files = [f.path for f in sel]
    jobs = [['magick', 'mogrify'] + args + ['--', p] for p in files]
    _confirm_then(
        cmd.fm, files, '{} {{n}} file(s) in place?'.format(verb),
        lambda: _run_jobs(cmd.fm, verb, jobs,
                          '{}: {} file(s)'.format(verb, len(files)), inplace=True))


class image_resize(Command):
    """:image_resize <spec>  (<Space>vir)

    Resize all selected images in-place via mogrify (asks first when more
    than one file or a lossy format is involved).
    <spec> is any ImageMagick geometry string, e.g.:
        50%        half size
        800x600    fit within box (keep aspect)
        1920x1080^ fill box (crop to fit)
        800x600!   force exact size (distort)
    Requires: mogrify (ImageMagick).
    """

    def execute(self):
        spec = self.rest(1).strip()
        if not spec:
            self.fm.notify("Usage: image_resize <spec>  e.g. 50%  800x600", bad=True)
            return
        _mogrify_inplace(self, ['-resize', spec], 'Resize to ' + spec)


class image_convert(Command):
    """:image_convert <ext>  (<Space>vic)

    Convert selected images to a different format.
    <ext> is the target format extension, e.g.: png  webp  jpg  avif  tiff
    Output files are written alongside originals with the new extension;
    an existing file of that name is never overwritten (name_1.ext …).
    Requires: magick (ImageMagick).
    """

    def execute(self):
        ext = self.rest(1).strip().lstrip('.')
        if not ext:
            self.fm.notify("Usage: image_convert <ext>  e.g. png  webp  jpg", bad=True)
            return

        sel = get_selection(self.fm)
        if sel is None:
            return
        if not require_tool(self.fm, 'magick'):
            return

        jobs = []
        taken = set()
        for f in sel:
            out = unique_dest(os.path.splitext(f.path)[0] + '.' + ext, taken=taken)
            jobs.append(['magick', f.path, out])
        _run_jobs(self.fm, 'Convert to .' + ext, jobs,
                  "Converted {} file(s) → .{}".format(len(jobs), ext))


class image_strip(Command):
    """:image_strip  (<Space>vis)

    Strip all EXIF/XMP/IPTC metadata from selected images in-place.
    Requires: mogrify (ImageMagick).
    """

    def execute(self):
        _mogrify_inplace(self, ['-strip'], 'Strip metadata from')


class image_optimize(Command):
    """:image_optimize  (<Space>vio)

    Losslessly optimize selected images in-place (asks first for 2+ files).
    PNGs  → oxipng -o2 --strip safe
    JPEGs → jpegoptim --strip-all
    Requires: oxipng (PNG) and/or jpegoptim (JPEG).
    """

    def execute(self):
        sel = get_selection(self.fm)
        if sel is None:
            return

        pngs  = [f.path for f in sel if f.extension and f.extension.lower() == 'png']
        jpegs = [f.path for f in sel if f.extension and f.extension.lower() in ('jpg', 'jpeg')]

        jobs = []
        if pngs and shutil.which('oxipng'):
            jobs.append(['oxipng', '-o2', '--strip', 'safe', '--'] + pngs)
        else:
            pngs = []
        if jpegs and shutil.which('jpegoptim'):
            jobs.append(['jpegoptim', '--strip-all', '--'] + jpegs)
        else:
            jpegs = []

        if not jobs:
            self.fm.notify("No supported files or tools (need oxipng / jpegoptim)", bad=True)
            return
        _confirm_then(
            self.fm, pngs + jpegs, 'Optimize {n} file(s) in place?',
            lambda: _run_jobs(self.fm, 'Optimize', jobs, "Optimized {} PNG(s), {} JPEG(s)".format(
                len(pngs), len(jpegs)), inplace=True),
            lossy=False)


# ── Image composite / in-place ops  (<Space>vi a/A/f/F/t/n/R/g) ─────────────

def _parse_stack_args(arg_str):
    """Parse '[width] output.ext' for vstack/hstack.

    Returns (width_str_or_None, output_filename).
    width is a pixel count that each frame is scaled to before compositing;
    it keeps aspect ratio (WxN for vstack, Nx for hstack callers decide which).
    """
    parts = arg_str.strip().split(None, 1)
    if len(parts) == 2 and parts[0].isdigit():
        return parts[0], parts[1]
    return None, arg_str.strip()


class image_vstack(Command):
    """:image_vstack [width] <output>  (<Space>via)

    Vertically stack selected images (top→bottom) into a new file.
    Files are composited in sorted (lexicographic) order.

    Optional width: scale every frame to this pixel width (keeping aspect
    ratio) before stacking.  Strongly recommended for large images — without
    it the output is the sum of all source pixels.

    Requires: magick (ImageMagick 7).
    Usage:
        image_vstack stacked.jpg          full resolution
        image_vstack 1920 stacked.jpg     scale each frame to 1920 px wide
    """

    def execute(self):
        width, out = _parse_stack_args(self.rest(1))
        if not out:
            self.fm.notify(
                "Usage: image_vstack [width] <output.ext>  e.g. 1920 stacked.jpg", bad=True)
            return
        if not require_tool(self.fm, 'magick'):
            return
        sel = get_selection(self.fm, min_count=2, msg="Select 2+ images to stack")
        if sel is None:
            return
        files = sorted(f.path for f in sel)
        out_path = unique_dest(os.path.join(self.fm.thisdir.path, out))
        cmd = ['magick'] + files
        if width:
            cmd += ['-resize', '{}x'.format(width)]
        cmd += ['-append', out_path]
        note = " (scaled to {}px wide)".format(width) if width else ""
        _run_jobs(self.fm, 'Stack', [cmd], "Stacked {}{} → {}".format(
            len(files), note, os.path.basename(out_path)))


class image_hstack(Command):
    """:image_hstack [height] <output>  (<Space>viA)

    Horizontally stack selected images (left→right) into a new file.
    Files are composited in sorted order.

    Optional height: scale every frame to this pixel height before stacking.

    Requires: magick (ImageMagick 7).
    Usage:
        image_hstack row.jpg              full resolution
        image_hstack 1080 row.jpg         scale each frame to 1080 px tall
    """

    def execute(self):
        height, out = _parse_stack_args(self.rest(1))
        if not out:
            self.fm.notify(
                "Usage: image_hstack [height] <output.ext>  e.g. 1080 row.png", bad=True)
            return
        if not require_tool(self.fm, 'magick'):
            return
        sel = get_selection(self.fm, min_count=2, msg="Select 2+ images to stack")
        if sel is None:
            return
        files = sorted(f.path for f in sel)
        out_path = unique_dest(os.path.join(self.fm.thisdir.path, out))
        cmd = ['magick'] + files
        if height:
            cmd += ['-resize', 'x{}'.format(height)]
        cmd += ['+append', out_path]
        note = " (scaled to {}px tall)".format(height) if height else ""
        _run_jobs(self.fm, 'Stack', [cmd], "Stacked {}{} → {}".format(
            len(files), note, os.path.basename(out_path)))


class image_flip(Command):
    """:image_flip  (<Space>vif)

    Flip selected images vertically (upside-down) in-place via mogrify.
    Requires: mogrify (ImageMagick).
    """

    def execute(self):
        _mogrify_inplace(self, ['-flip'], 'Flip')


class image_flop(Command):
    """:image_flop  (<Space>viF)

    Mirror selected images horizontally (left↔right) in-place via mogrify.
    Requires: mogrify (ImageMagick).
    """

    def execute(self):
        _mogrify_inplace(self, ['-flop'], 'Flop')


class image_trim(Command):
    """:image_trim  (<Space>vit)

    Auto-trim uniform borders/whitespace from selected images in-place.
    Uses mogrify -trim +repage (resets the canvas offset).
    Requires: mogrify (ImageMagick).
    """

    def execute(self):
        _mogrify_inplace(self, ['-trim', '+repage'], 'Trim')


class image_negate(Command):
    """:image_negate  (<Space>vin)

    Invert (negate) pixel colours in selected images in-place via mogrify.
    Requires: mogrify (ImageMagick).
    """

    def execute(self):
        _mogrify_inplace(self, ['-negate'], 'Negate')


class image_rotate(Command):
    """:image_rotate <degrees>  (<Space>viR)

    Rotate selected images by an arbitrary angle in-place via mogrify.
    Positive = clockwise.  JPEGs are re-encoded (lossy) — you'll be asked.
    Requires: mogrify (ImageMagick).
    Usage:  image_rotate 90
    """

    def execute(self):
        deg = self.rest(1).strip()
        if not deg:
            self.fm.notify("Usage: image_rotate <degrees>  e.g. 90  180  -45", bad=True)
            return
        _mogrify_inplace(self, ['-rotate', deg], 'Rotate {}°'.format(deg))


# ── Video / audio ops  (<Space>vv*) ──────────────────────────────────────────

class video_transcode(Command):
    """:video_transcode <ext>  (<Space>vvt)

    Re-encode selected videos to a different container via ffmpeg.
    <ext>: mp4  webm  mkv  mov  avi
    Output: <name>.<ext> alongside source. Interactive ffmpeg progress shown.
    Requires: ffmpeg.
    """

    def execute(self):
        ext = self.rest(1).strip().lstrip('.')
        if not ext:
            self.fm.notify("Usage: video_transcode <ext>  e.g. mp4  webm", bad=True)
            return
        sel = get_selection(self.fm)
        if sel is None:
            return

        taken = set()

        def _cmd(f):
            stem = os.path.splitext(f.basename)[0]
            out = unique_dest(os.path.join(f.dirname, stem + '.' + ext), taken=taken)
            return 'ffmpeg -i {} {}'.format(shlex.quote(f.path), shlex.quote(out))

        _run_ffmpeg_batch(self.fm, sel, _cmd, 'Transcoding')


class video_extract_audio(Command):
    """:video_extract_audio <ext>  (<Space>vva)

    Extract the audio track from selected videos via ffmpeg.
    <ext>: mp3  aac  flac  wav  opus  ogg
    Output: <name>.<ext> alongside source.
    Requires: ffmpeg.
    """

    def execute(self):
        ext = self.rest(1).strip().lstrip('.')
        if not ext:
            self.fm.notify("Usage: video_extract_audio <ext>  e.g. mp3  flac", bad=True)
            return
        sel = get_selection(self.fm)
        if sel is None:
            return

        taken = set()

        def _cmd(f):
            stem = os.path.splitext(f.basename)[0]
            out = unique_dest(os.path.join(f.dirname, stem + '.' + ext), taken=taken)
            return 'ffmpeg -i {} -vn {}'.format(shlex.quote(f.path), shlex.quote(out))

        _run_ffmpeg_batch(self.fm, sel, _cmd, 'Extracting audio from')


class video_trim(Command):
    """:video_trim <start> <duration>  (<Space>vvx)

    Trim selected video to [start, start+duration] via stream copy (fast, lossless).
    Times: HH:MM:SS, MM:SS, or bare seconds.
    Example: video_trim 0:30 1:00  →  extract 30s–1m30s
    Output: <name>_trim.<ext> alongside source.
    Requires: ffmpeg.
    """

    def execute(self):
        args = self.args[1:]
        if len(args) < 2:
            self.fm.notify("Usage: video_trim <start> <duration>  e.g. 0:30 1:00", bad=True)
            return
        start, duration = args[0], args[1]
        sel = get_selection(self.fm)
        if sel is None:
            return

        taken = set()

        def _cmd(f):
            stem, sfx = os.path.splitext(f.basename)
            out = unique_dest(os.path.join(f.dirname, stem + '_trim' + sfx), taken=taken)
            return 'ffmpeg -ss {} -i {} -t {} -c copy {}'.format(
                shlex.quote(start), shlex.quote(f.path),
                shlex.quote(duration), shlex.quote(out))

        _run_ffmpeg_batch(self.fm, sel, _cmd, 'Trimming')


class video_to_gif(Command):
    """:video_to_gif [fps [width]]  (<Space>vvg)

    Convert selected video to an animated GIF via ffmpeg.
    Defaults: 10 fps, 480px wide (height auto-scaled).
    Output: <name>.gif alongside source.
    Requires: ffmpeg.
    """

    def execute(self):
        args = self.args[1:]
        fps   = args[0] if len(args) > 0 else '10'
        width = args[1] if len(args) > 1 else '480'
        sel = get_selection(self.fm)
        if sel is None:
            return

        taken = set()

        def _cmd(f):
            stem = os.path.splitext(f.basename)[0]
            out = unique_dest(os.path.join(f.dirname, stem + '.gif'), taken=taken)
            vf = 'fps={},scale={}:-1:flags=lanczos'.format(fps, width)
            return 'ffmpeg -i {} -vf {} {}'.format(
                shlex.quote(f.path), shlex.quote(vf), shlex.quote(out))

        _run_ffmpeg_batch(self.fm, sel, _cmd, 'Converting to GIF')


class video_snapshot(Command):
    """:video_snapshot [timestamp]  (<Space>vvs)

    Grab a single frame from selected videos as a JPEG.
    Default timestamp: 00:00:05 (5 seconds in).
    Output: <name>_thumb.jpg alongside source.
    Requires: ffmpeg.
    """

    def execute(self):
        ts = self.rest(1).strip() or '00:00:05'
        sel = get_selection(self.fm)
        if sel is None:
            return

        taken = set()

        def _cmd(f):
            stem = os.path.splitext(f.basename)[0]
            out = unique_dest(os.path.join(f.dirname, stem + '_thumb.jpg'), taken=taken)
            return 'ffmpeg -ss {} -i {} -frames:v 1 {}'.format(
                shlex.quote(ts), shlex.quote(f.path), shlex.quote(out))

        _run_ffmpeg_batch(self.fm, sel, _cmd, 'Grabbing snapshot from')


# ── PDF ops  (<Space>vp*) ─────────────────────────────────────────────────────

class pdf_merge(Command):
    """:pdf_merge <output>  (<Space>vpm)

    Merge all selected PDFs into one file.
    Uses pdfunite (poppler) if available, falls back to gs (ghostscript).
    Output is written in cwd.
    Requires: pdfunite or gs.
    """

    def execute(self):
        out = self.rest(1).strip()
        if not out:
            self.fm.notify("Usage: pdf_merge <output.pdf>", bad=True)
            return
        if not out.lower().endswith('.pdf'):
            out += '.pdf'

        sel = get_selection(self.fm, min_count=2, msg="Select 2+ PDF files to merge")
        if sel is None:
            return

        # Never write over an existing file — in particular one of the inputs.
        out_path = unique_dest(os.path.join(self.fm.thisdir.path, out))
        files = [f.path for f in sel]

        if shutil.which('pdfunite'):
            cmd = ['pdfunite'] + files + [out_path]
        elif shutil.which('gs'):
            cmd = ['gs', '-dBATCH', '-dNOPAUSE', '-dSAFER', '-q',
                   '-sDEVICE=pdfwrite', '-sOutputFile=' + out_path] + files  # paths are absolute
        else:
            self.fm.notify("Install pdfunite (poppler) or gs (ghostscript)", bad=True)
            return
        _run_jobs(self.fm, 'Merge PDFs', [cmd], "Merged {} PDFs → {}".format(
            len(sel), os.path.basename(out_path)))


class pdf_split(Command):
    """:pdf_split <start>-<end>  (<Space>vps)

    Extract a page range from the selected PDF.
    Range is 1-based, e.g.: 1-5  3-3  2-10
    Output: <name>_p1-5.pdf alongside source.
    Requires: qpdf.
    """

    def execute(self):
        rng = self.rest(1).strip()
        if not rng or '-' not in rng:
            self.fm.notify("Usage: pdf_split <start>-<end>  e.g. 1-5", bad=True)
            return

        if not require_tool(self.fm, 'qpdf', "Install qpdf for PDF splitting"):
            return

        sel = get_selection(self.fm)
        if sel is None:
            return

        jobs = []
        for f in sel:
            stem = os.path.splitext(f.basename)[0]
            out = unique_dest(os.path.join(f.dirname, '{}_p{}.pdf'.format(stem, rng)))
            jobs.append(['qpdf', '--empty', '--pages', f.path, rng, '--', out])
        _run_jobs(self.fm, 'Split PDF', jobs,
                  "Split pages {} from {} file(s)".format(rng, len(sel)))


class pdf_rotate(Command):
    """:pdf_rotate <degrees> [range]  (<Space>vpr)

    Rotate pages in selected PDFs. degrees: 90 | 180 | 270
    range (optional, qpdf syntax): e.g. 1-3, 5, 1-3,7  — defaults to all pages.
    Overwrites originals in-place.
    Requires: qpdf.
    """

    def execute(self):
        deg = self.arg(1)
        if deg not in ('90', '180', '270'):
            self.fm.notify("Usage: pdf_rotate <90|180|270> [range]", bad=True)
            return
        page_range = self.arg(2) or '1-z'

        if not require_tool(self.fm, 'qpdf', "Install qpdf for PDF rotation"):
            return

        sel = get_selection(self.fm)
        if sel is None:
            return

        for f in sel:
            tmp = f.path + '._qpdf_tmp'
            r = subprocess.run([
                'qpdf', '--rotate=+{}:{}'.format(deg, page_range), f.path, tmp
            ], capture_output=True, text=True, errors='replace')
            if r.returncode == 0:
                os.replace(tmp, f.path)
            else:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                self.fm.notify("qpdf failed on {}".format(f.basename), bad=True)
                return

        self.fm.notify("Rotated {}° (pages {}) — {} file(s)".format(deg, page_range, len(sel)))
        self.fm.reload_cwd()


class pdf_compress(Command):
    """:pdf_compress [quality]  (<Space>vpc)

    Compress selected PDFs via Ghostscript.
    quality: screen  ebook  printer  prepress  (default: ebook)
    Output: <name>_compressed.pdf alongside source.
    Requires: gs (ghostscript).
    """

    def execute(self):
        quality = self.rest(1).strip() or 'ebook'
        valid = ('screen', 'ebook', 'printer', 'prepress')
        if quality not in valid:
            self.fm.notify("Usage: pdf_compress [{}]".format('|'.join(valid)), bad=True)
            return

        if not require_tool(self.fm, 'gs', "Install ghostscript (gs) for PDF compression"):
            return

        sel = get_selection(self.fm)
        if sel is None:
            return

        jobs = []
        for f in sel:
            stem = os.path.splitext(f.basename)[0]
            out = unique_dest(os.path.join(f.dirname, stem + '_compressed.pdf'))
            jobs.append(['gs', '-dBATCH', '-dNOPAUSE', '-dSAFER', '-q',
                         '-sDEVICE=pdfwrite', '-dPDFSETTINGS=/' + quality,
                         '-sOutputFile=' + out, f.path])
        _run_jobs(self.fm, 'Compress PDF', jobs,
                  "Compressed {} PDF(s) [{}]".format(len(sel), quality))


class pdf_ocr(Command):
    """:pdf_ocr [lang]  (<Space>vpo)

    Add a text layer to selected PDFs via ocrmypdf (Tesseract).
    lang: Tesseract language code, e.g. eng  deu  fra  (default: eng)
    Overwrites originals in-place. Skips pages already containing text.
    Requires: ocrmypdf.
    """

    def execute(self):
        lang = self.rest(1).strip() or 'eng'

        if not require_tool(self.fm, 'ocrmypdf', "Install ocrmypdf for PDF OCR"):
            return

        sel = get_selection(self.fm)
        if sel is None:
            return

        for f in sel:
            self.fm.run('ocrmypdf --skip-text -l {} {} {}'.format(
                shlex.quote(lang), shlex.quote(f.path), shlex.quote(f.path)))

        self.fm.reload_cwd()


# ── Name / organize  (<Space>vn*) ─────────────────────────────────────────────

class name_by_exif(Command):
    """:name_by_exif [format]  (<Space>vne)

    Rename selected images/videos using the EXIF DateTimeOriginal field.
    Default format: %Y%m%d_%H%M%S  →  20240315_143022.jpg
    Appends a counter if a filename collision occurs.
    Requires: exiftool.
    """

    def execute(self):
        fmt = self.rest(1).strip() or '%Y%m%d_%H%M%S'

        if not require_tool(self.fm, 'exiftool', "Install exiftool for EXIF rename"):
            return

        sel = get_selection(self.fm)
        if sel is None:
            return

        files = [f.path for f in sel]
        # exiftool never overwrites: %-c appends -1, -2 … on collision.
        job = ['exiftool', '-d', fmt + '%%-c.%%e', '-FileName<DateTimeOriginal', '--'] + files
        _confirm_then(
            self.fm, files, 'Rename {n} file(s) by EXIF date?',
            lambda: _run_jobs(self.fm, 'Rename by EXIF', [job],
                              "Renamed {} file(s) by EXIF date".format(len(files))),
            lossy=False)


class name_by_mtime(Command):
    """:name_by_mtime [format]  (<Space>vnm)

    Rename selected files using their modification timestamp.
    Default format: %Y%m%d_%H%M%S  →  20240315_143022.jpg
    Appends _1, _2 … on collision. No external tools required.
    """

    def execute(self):
        fmt = self.rest(1).strip() or '%Y%m%d_%H%M%S'

        sel = get_selection(self.fm)
        if sel is None:
            return

        def _do():
            renamed, failed = 0, []
            for f in sel:
                try:
                    ts = time.strftime(fmt, time.localtime(os.path.getmtime(f.path)))
                    ext = os.path.splitext(f.basename)[1]
                    new_path = os.path.join(f.dirname, ts + ext)
                    counter = 1
                    while os.path.lexists(new_path) and new_path != f.path:
                        new_path = os.path.join(f.dirname, '{}_{}{}'.format(ts, counter, ext))
                        counter += 1
                    if new_path != f.path:
                        os.rename(f.path, new_path)
                        renamed += 1
                except (OSError, ValueError) as ex:
                    failed.append('{}: {}'.format(f.basename, ex))
            self.fm.notify("Renamed {} file(s) by mtime".format(renamed))
            if failed:
                self.fm.notify("Failed: " + ';  '.join(failed[:3]), bad=True)
            self.fm.reload_cwd()

        _confirm_then(self.fm, [f.path for f in sel],
                      'Rename {n} file(s) by mtime?', _do, lossy=False)


class name_sort_date(Command):
    """:name_sort_date [confirm]  (<Space>vns)

    Move selected files into YYYY/MM subdirectories based on mtime.
    Shows where they'll go and asks y/N; 'confirm' skips the question.
    Never overwrites: collisions get a _N suffix.
    """

    def execute(self):
        confirm = 'confirm' in self.args[1:]

        sel = get_selection(self.fm)
        if sel is None:
            return

        cwd = self.fm.thisdir.path
        moves = []
        for f in sel:
            try:
                lt = time.localtime(os.path.getmtime(f.path))
            except OSError:
                continue
            subdir = os.path.join(cwd, time.strftime('%Y', lt), time.strftime('%m', lt))
            moves.append((f.path, subdir, os.path.join(subdir, f.basename)))
        if not moves:
            self.fm.notify("Nothing to sort", bad=True)
            return

        def _do():
            ok = fail = 0
            for src, subdir, dest in moves:
                try:
                    os.makedirs(subdir, exist_ok=True)
                    if dest != src:
                        dest = unique_dest(dest)
                    shutil.move(src, dest)
                    ok += 1
                except (OSError, shutil.Error):
                    fail += 1
            msg = "Sorted {} file(s) into YYYY/MM".format(ok)
            if fail:
                msg += ", {} failed".format(fail)
            self.fm.notify(msg, bad=bool(fail))
            self.fm.reload_cwd()

        if confirm:
            _do()
            return
        dirs = sorted(set(m[1] for m in moves))
        preview = ', '.join(os.path.relpath(d, cwd) for d in dirs[:3])
        if len(dirs) > 3:
            preview += '…'
        ask_yes(self.fm, "Sort {} file(s) into {}?".format(len(moves), preview), _do)
