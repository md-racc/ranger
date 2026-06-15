from __future__ import (absolute_import, division, print_function)
import os
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from ranger.api.commands import Command
from cmds._util import run_bg, unique_dest


# id(proc) -> proc for all active extractions; used by extract_cancel
_active_extractions = {}

_ARCHIVE_EXTS = (
    '.tar.gz', '.tar.bz2', '.tar.xz', '.tar.zst',
    '.tgz', '.tbz2', '.txz', '.tar',
    '.zip', '.gz', '.bz2', '.xz', '.zst',
)

_BARE_EXTS = {'.gz': 'gzip', '.bz2': 'bzip2', '.xz': 'xz', '.zst': 'zstd'}

_COMPOUND_EXTS = ('.tar.gz', '.tar.bz2', '.tar.xz', '.tar.zst')

_KNOWN_ARCHIVE_SUFFIXES = (
    '.tar.gz', '.tar.bz2', '.tar.xz', '.tar.zst',
    '.zip', '.7z', '.gz', '.bz2', '.xz', '.zst',
)


def _split_archive_name(name):
    """Split an archive filename into (stem, suffix), recognizing compound
    suffixes like .tar.gz before falling back to a single extension."""
    lower = name.lower()
    for suf in _KNOWN_ARCHIVE_SUFFIXES:
        if lower.endswith(suf):
            return name[:-len(suf)], name[-len(suf):]
    return os.path.splitext(name)


def _unique_archive_dest(path):
    """Like unique_dest, but suffix-aware so compound extensions like
    .tar.gz aren't split mid-suffix (e.g. notes.tar.gz -> notes_1.tar.gz,
    not notes.tar_1.gz)."""
    if not os.path.exists(path):
        return path
    directory, base = os.path.split(path)
    stem, suffix = _split_archive_name(base)
    n = 1
    while True:
        candidate = os.path.join(directory, '{}_{}{}'.format(stem, n, suffix))
        if not os.path.exists(candidate):
            return candidate
        n += 1


def _archive_stem(basename):
    """Strip known archive extensions from basename and return the stem."""
    bl = basename.lower()
    for ext in _ARCHIVE_EXTS:
        if bl.endswith(ext) and len(basename) > len(ext):
            return basename[:-len(ext)]
    return basename + '_extracted'


def _is_bare_stream(name):
    """True for a single compressed file (x.gz, x.zst…), not a tarball."""
    lower = name.lower()
    if lower.endswith(_COMPOUND_EXTS):
        return False
    return os.path.splitext(lower)[1] in _BARE_EXTS


def _unique_dir(path):
    """path, or path_1, path_2… — suffixes the whole name (dirs have no ext)."""
    out, n = path, 1
    while os.path.lexists(out):
        out = '{}_{}'.format(path, n)
        n += 1
    return out


def _top_entries(listing):
    """Top-level names from a `bsdtar -tf` listing (handles ./ prefixes)."""
    tops = set()
    for line in listing.splitlines():
        entry = line.strip()
        while entry.startswith('./'):
            entry = entry[2:]
        top = entry.rstrip('/').split('/')[0]
        if top and top != '.':
            tops.add(top)
    return tops


def _count_existing(src, dst):
    """How many non-directory entries of archive `src` already exist in dst
    (bsdtar -k will skip — i.e. keep — those)."""
    try:
        r = subprocess.run(['bsdtar', '-tf', src], capture_output=True, text=True)
    except OSError:
        return 0
    n = 0
    for line in r.stdout.splitlines():
        if line.endswith('/'):
            continue
        rel = line[2:] if line.startswith('./') else line
        if rel and os.path.lexists(os.path.join(dst, rel)) and \
                not os.path.isdir(os.path.join(dst, rel)):
            n += 1
    return n


def _extract_bg(fm, src, dst, label, after=None, cleanup=None, count_kept=False):
    """Extract archive `src` into directory `dst` in the background.

    Never overwrites: tarballs/zips go through `bsdtar -k`; a bare .gz/.bz2/
    .xz/.zst stream is decompressed to a new, uniquely named file in dst.

    after(ui, out): optional, runs in the worker after a successful extract
                    (out = dst, or the decompressed file); ui(fn, *a) queues
                    fn(*a) on the UI thread.
    cleanup():      optional, always runs in the worker at the end.
    count_kept:     report how many existing files bsdtar left untouched.

    Progress and results are reported on the UI thread (ranger loader).
    """
    reader = 'pv -n -- "$1"' if shutil.which('pv') else 'cat -- "$1"'
    bare = _is_bare_stream(os.path.basename(src))
    if bare:
        tool = {'gzip': 'gzip', 'bzip2': 'bzip2', 'xz': 'xz', 'zstd': 'zstd -q'}[
            _BARE_EXTS[os.path.splitext(src.lower())[1]]]
        script = '{} | {} -dc > "$2"'.format(reader, tool)
    else:
        script = '{} | bsdtar -xkf - -C "$2"'.format(reader)

    def work(ui):
        out = dst
        try:
            kept = _count_existing(src, dst) if (count_kept and not bare) else 0
            if bare:
                stem = _archive_stem(os.path.basename(src))
                out = unique_dest(os.path.join(dst, stem))
                open(out, 'xb').close()          # claim the name
            proc = subprocess.Popen(
                ['sh', '-c', script, 'extract', src, out],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, start_new_session=True,
            )
            _active_extractions[id(proc)] = proc
            try:
                errors, last = [], -1
                start = time.monotonic()
                for raw in proc.stderr:
                    line = raw.decode('utf-8', 'replace').strip()
                    if not line.isdigit():
                        if line:
                            errors.append(line)
                        continue
                    pct = int(line)
                    if pct == last:
                        continue
                    last = pct
                    elapsed = time.monotonic() - start
                    if pct > 0:
                        msg = "Extracting {} — {}%  ETA {}s".format(
                            label, pct, int(elapsed * (100 - pct) / pct))
                    else:
                        msg = "Extracting {}…".format(label)
                    ui(fm.notify, msg)
                proc.wait()
            finally:
                _active_extractions.pop(id(proc), None)
                proc.stderr.close()
            rc = proc.returncode
            if rc != 0 and bare:
                try:
                    os.remove(out)
                except OSError:
                    pass
            if rc == 0 and after is not None:
                after(ui, out)
            return rc, errors, kept, out
        finally:
            if cleanup is not None:
                cleanup()

    def done(result, error):
        if error is not None:
            fm.notify("extract {}: {}".format(label, error), bad=True)
        else:
            rc, errors, kept, out = result
            if rc == 0:
                msg = "Extracted: {}".format(label)
                if bare:
                    msg += " → {}".format(os.path.basename(out))
                if kept:
                    msg += " ({} existing file(s) kept, not overwritten)".format(kept)
                fm.notify(msg)
            elif rc in (-signal.SIGTERM, -signal.SIGKILL, 128 + signal.SIGTERM):
                fm.notify("Extraction cancelled: {}".format(label))
            else:
                fm.notify("Extraction of {} failed (exit {}): {}".format(
                    label, rc, errors[-1] if errors else 'no output'), bad=True)
        fm.reload_cwd()
        try:
            fm.ui.need_redraw = True
        except AttributeError:
            pass

    run_bg(fm, 'Extracting ' + label, work, done)


def _new_dest_dir(path):
    """Create and return a fresh directory at path (or path_1, …)."""
    dest = _unique_dir(path)
    os.makedirs(dest)
    return dest


# ---------------------------------------------------------------------------
# Extract commands
# ---------------------------------------------------------------------------

class extract(Command):
    """:extract  (<Space>aed)

    Extract selected archive(s) into a new named subdirectory (stem/, or
    stem_1/ if that exists — never merged into an existing dir).  A bare
    .gz/.bz2/.xz/.zst file is decompressed next to itself instead.
    """

    def execute(self):
        cwd = self.fm.thisdir.path
        for f in self.fm.thistab.get_selection():
            if _is_bare_stream(f.basename):
                _extract_bg(self.fm, f.path, cwd, f.basename)
                continue
            try:
                dest = _new_dest_dir(os.path.join(cwd, _archive_stem(f.basename)))
            except OSError as ex:
                self.fm.notify("extract: {}".format(ex), bad=True)
                continue
            self.fm.notify("Extracting {} → {}/".format(f.basename, os.path.basename(dest)))
            _extract_bg(self.fm, f.path, dest, f.basename)


class extract_here(Command):
    """:extract_here  (<Space>aeh)

    Extract selected archive(s) flat into the current directory.
    Refuses to extract if any top-level archive entry already exists in cwd
    — use extract_smart or extract_flatten instead.  Existing files are
    never overwritten in any case (bsdtar -k).
    """

    def execute(self):
        cwd = self.fm.thisdir.path
        for f in self.fm.thistab.get_selection():
            if _is_bare_stream(f.basename):
                _extract_bg(self.fm, f.path, cwd, f.basename)
                continue
            result = subprocess.run(
                ['bsdtar', '-tf', f.path], capture_output=True, text=True)
            if result.returncode != 0:
                self.fm.notify(
                    "Cannot read {}: {}".format(f.basename, result.stderr.strip()),
                    bad=True)
                continue

            top_entries = _top_entries(result.stdout)
            collisions = [t for t in top_entries if os.path.lexists(os.path.join(cwd, t))]
            if collisions:
                self.fm.notify(
                    "extract_here: would overwrite {} — use extract_smart/extract_flatten instead".format(
                        ', '.join(sorted(collisions)[:3])),
                    bad=True)
                continue

            self.fm.notify("Extracting {}…".format(f.basename))
            _extract_bg(self.fm, f.path, cwd, f.basename)


class extract_smart(Command):
    """:extract_smart  (<Space>aes)

    Smart extract: inspect the archive first.  If all entries share a single
    top-level directory that doesn't exist yet, extract directly into cwd
    (avoids archive/archive/ double-nesting).  Otherwise extract into a new
    named subdir (stem/ or stem_1/ …).
    """

    def execute(self):
        cwd = self.fm.thisdir.path
        for f in self.fm.thistab.get_selection():
            if _is_bare_stream(f.basename):
                _extract_bg(self.fm, f.path, cwd, f.basename)
                continue
            result = subprocess.run(
                ['bsdtar', '-tf', f.path], capture_output=True, text=True)
            if result.returncode != 0:
                self.fm.notify(
                    "Cannot read {}: {}".format(f.basename, result.stderr.strip()),
                    bad=True)
                continue

            top_entries = _top_entries(result.stdout)
            if len(top_entries) == 1 and not os.path.lexists(
                    os.path.join(cwd, next(iter(top_entries)))):
                sole = next(iter(top_entries))
                self.fm.notify("Smart extract → {}/".format(sole))
                _extract_bg(self.fm, f.path, cwd, sole)
                continue
            try:
                dest = _new_dest_dir(os.path.join(cwd, _archive_stem(f.basename)))
            except OSError as ex:
                self.fm.notify("extract: {}".format(ex), bad=True)
                continue
            self.fm.notify("Smart extract (subdir): {}/".format(os.path.basename(dest)))
            _extract_bg(self.fm, f.path, dest, f.basename)


def _flatten_into(src_root, dest):
    """Move every file under src_root into dest (renaming on collision)."""
    for root, _, files in os.walk(src_root):
        for fname in files:
            shutil.move(os.path.join(root, fname),
                        unique_dest(os.path.join(dest, fname)))


class extract_flatten(Command):
    """:extract_flatten  (<Space>aef)

    Extract into a hidden temp dir (in cwd, so moves are cheap renames),
    then move every file (regardless of nesting) into a new flat subdir.
    The temp dir is always removed, even if extraction fails.
    """

    def execute(self):
        fm = self.fm
        cwd = fm.thisdir.path
        for f in fm.thistab.get_selection():
            if _is_bare_stream(f.basename):
                _extract_bg(fm, f.path, cwd, f.basename)
                continue
            try:
                tmpdir = tempfile.mkdtemp(prefix='.ranger-flat-', dir=cwd)
            except OSError as ex:
                fm.notify("extract_flatten: {}".format(ex), bad=True)
                continue
            dest_path = _unique_dir(os.path.join(cwd, _archive_stem(f.basename)))

            def _after(ui, _out, tmpdir=tmpdir, dest=dest_path):
                os.makedirs(dest, exist_ok=True)
                _flatten_into(tmpdir, dest)
                ui(fm.notify, "Flattened into {}/".format(os.path.basename(dest)))

            fm.notify("Extracting {}…".format(f.basename))
            _extract_bg(fm, f.path, tmpdir, f.basename, after=_after,
                        cleanup=lambda t=tmpdir: shutil.rmtree(t, ignore_errors=True))


class extract_to(Command):
    """:extract_to <destination>  (<Space>aeD)

    Extract selected archive(s) into a typed destination directory.
    Existing files there are kept, never overwritten (reported).
    Tab-completes paths.
    """

    def execute(self):
        dest = os.path.expanduser(self.rest(1))
        if not dest:
            self.fm.notify("Usage: extract_to <destination>", bad=True)
            return
        dest = os.path.join(self.fm.thisdir.path, dest)
        try:
            os.makedirs(dest, exist_ok=True)
        except OSError as ex:
            self.fm.notify("extract_to: {}".format(ex), bad=True)
            return
        for f in self.fm.thistab.get_selection():
            self.fm.notify("Extracting {}…".format(f.basename))
            _extract_bg(self.fm, f.path, dest, f.basename, count_kept=True)

    def tab(self, tabnum):
        return self._tab_directory_content()


class extract_open(Command):
    """:extract_open  (<Space>aeo)

    Extract selected archive into a new named subdir then cd into it
    (a bare .gz/.zst… is decompressed and the result selected).
    """

    def execute(self):
        fm = self.fm
        cwd = fm.thisdir.path
        for f in fm.thistab.get_selection():
            if _is_bare_stream(f.basename):
                _extract_bg(fm, f.path, cwd, f.basename,
                            after=lambda ui, out: ui(fm.select_file, out))
                continue
            try:
                dest = _new_dest_dir(os.path.join(cwd, _archive_stem(f.basename)))
            except OSError as ex:
                fm.notify("extract: {}".format(ex), bad=True)
                continue
            fm.notify("Extracting {}…".format(f.basename))
            _extract_bg(fm, f.path, dest, f.basename,
                        after=lambda ui, out: ui(fm.cd, out))


class extract_cancel(Command):
    """:extract_cancel  (<Space>ak)

    Cancel all active background extractions.
    """

    def execute(self):
        if not _active_extractions:
            self.fm.notify("No active extractions")
            return
        count = len(_active_extractions)
        for proc in list(_active_extractions.values()):
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except OSError:
                try:
                    proc.kill()
                except OSError:
                    pass
        self.fm.notify("Cancelled {} extraction(s)".format(count))


# ---------------------------------------------------------------------------
# Compress commands
# ---------------------------------------------------------------------------

class compress_format(Command):
    """:compress_format <fmt>  (<Space>ac*)

    Open the console pre-filled with :compress <stem>.<ext> for the given
    format shorthand.  fmt: gz | xz | zst | bz2 | zip | 7z
    """

    _FMT_EXT = {
        'gz':  '.tar.gz',
        'xz':  '.tar.xz',
        'zst': '.tar.zst',
        'bz2': '.tar.bz2',
        'zip': '.zip',
        '7z':  '.7z',
    }

    def execute(self):
        fmt = self.arg(1)
        ext = self._FMT_EXT.get(fmt)
        if not ext:
            self.fm.notify(
                "Unknown format: {}  (gz/xz/zst/bz2/zip/7z)".format(fmt), bad=True)
            return
        selection = self.fm.thistab.get_selection()
        if not selection:
            return
        if len(selection) == 1:
            stem = os.path.splitext(selection[0].basename)[0]
        else:
            stem = os.path.basename(self.fm.thisdir.path)
        self.fm.open_console('compress ' + stem + ext)


class archive_list(Command):
    """:archive_list  (<Space>al)

    Browse archive contents in fzf (searchable, read-only).
    """

    def execute(self):
        f = self.fm.thisfile
        if f is None:
            self.fm.notify("No file selected", bad=True)
            return

        result = subprocess.run(
            ['bsdtar', '-tvf', f.path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            self.fm.notify(
                "Cannot list {}: {}".format(f.basename, result.stderr.strip()), bad=True)
            return

        with tempfile.NamedTemporaryFile(mode='w', suffix='.in', delete=False) as tf:
            tf.write(result.stdout)
            in_file = tf.name
        fd, out_file = tempfile.mkstemp(suffix='.out')
        os.close(fd)
        try:
            self.fm.run(
                'fzf --border --no-multi --ansi --header={} < {} > {}'.format(
                    shlex.quote(f.basename),
                    shlex.quote(in_file),
                    shlex.quote(out_file),
                )
            )
        finally:
            for tmp in [in_file, out_file]:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass


class archive_test(Command):
    """:archive_test  (<Space>at)

    Test archive integrity by doing a dry-run read through pv.
    Shows live progress; prints PASSED or FAILED when done.
    """

    def execute(self):
        f = self.fm.thisfile
        if f is None:
            self.fm.notify("No file selected", bad=True)
            return
        # File names go in as positional args ($1/$2), never into the script.
        script = ('if {reader} | bsdtar -tf - >/dev/null; '
                  'then echo "PASSED: $2"; else echo "FAILED: $2"; fi').format(
                      reader='pv -- "$1"' if shutil.which('pv') else 'cat -- "$1"')
        self.fm.run(['sh', '-c', script, 'archive_test', f.path, f.basename], flags='w')


class compress(Command):
    """:compress <archive_name>

    Compress the selected files into an archive.
    Format is determined by extension. Supported:
      .tar.gz  .tar.bz2  .tar.xz  .tar.zst  .zip  .7z
    A single non-directory file with a bare .gz/.bz2/.xz/.zst extension is
    compressed as a plain stream (gzip/bzip2/xz/zstd), not tar-wrapped.
    Refuses to overwrite an existing archive — appends _1, _2, … instead.
    """

    def execute(self):
        archive_name = self.rest(1)
        if not archive_name:
            self.fm.notify("Usage: compress <archive.tar.gz|zip|7z|...>", bad=True)
            return
        selection = self.fm.thistab.get_selection()
        if not selection:
            return

        archive_path = _unique_archive_dest(os.path.join(self.fm.thisdir.path, archive_name))
        archive_name = os.path.basename(archive_path)
        files = [f.path for f in selection]
        name = archive_name.lower()
        _, bare_ext = os.path.splitext(name)

        if (bare_ext in _BARE_EXTS and len(selection) == 1
                and not selection[0].is_directory
                and not name.endswith(_COMPOUND_EXTS)):
            tool = _BARE_EXTS[bare_ext]
            cmd = '{} -c -- {} > {}'.format(
                tool, shlex.quote(files[0]), shlex.quote(archive_path))
            self.fm.notify("Compressing 1 file → {}".format(archive_name))
            self.fm.run(cmd)
            self.fm.reload_cwd()
            return

        if name.endswith('.zip'):
            cmd = ['zip', '-r', archive_path] + files
        elif name.endswith('.7z'):
            cmd = ['7z', 'a', archive_path] + files
        elif name.endswith('.tar.zst'):
            cmd = ['bsdtar', '--zstd', '-caf', archive_path] + files
        elif name.endswith('.tar.bz2') or name.endswith('.tbz2'):
            cmd = ['bsdtar', '-cjf', archive_path] + files
        elif name.endswith('.tar.xz') or name.endswith('.txz'):
            cmd = ['bsdtar', '-cJf', archive_path] + files
        else:
            cmd = ['bsdtar', '-czf', archive_path] + files
        self.fm.notify("Compressing {} file(s) → {}".format(len(files), archive_name))
        self.fm.run(' '.join(shlex.quote(c) for c in cmd))
        self.fm.reload_cwd()
