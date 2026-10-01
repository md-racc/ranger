"""Headless data-safety tests for cmds/ (flatten, moves, extract, trash…):
nothing is overwritten or deleted without being asked."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ranger.core.shared import FileManagerAware  # noqa: E402
from _fakes import FakeFM, FakeFile  # noqa: E402


class FM(FakeFM):
    """FakeFM plus a settable selection and the few extra fm calls cmds use."""

    def __init__(self, cwd, selection=()):
        FakeFM.__init__(self, cwd)
        sel = [FakeFile(p) for p in selection]
        self.thistab.get_selection = lambda: list(sel)
        self.bad = []
        self.ran = []
        self.previews = {}

    def notify(self, msg, bad=False):
        self.notes.append(msg)
        if bad:
            self.bad.append(msg)

    def reload_cwd(self):
        pass

    def run(self, *args, **kwargs):
        self.ran.append((args, kwargs))

    def answer(self, key):
        """Answer the oldest pending console.ask question."""
        _text, callback, _choices = self.ui.console.asks.pop(0)
        callback(key)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = os.path.realpath(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def p(self, *parts):
        return os.path.join(self.d, *parts)

    def write(self, rel, data='x'):
        path = self.p(rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as fh:
            fh.write(data)
        return path

    def fm(self, selection=(), cwd=None):
        fake = FM(cwd or self.d, selection)
        FileManagerAware.fm_set(fake)
        return fake

    def files_under(self, root):
        out = set()
        for r, _, files in os.walk(root):
            for f in files:
                out.add(os.path.relpath(os.path.join(r, f), root))
        return out


class FlattenWrite(Base):
    def run_flatten(self, line, answer='y'):
        from cmds.nav import flatten_write
        fm = self.fm([self.p('top')])
        flatten_write(line).execute()
        if fm.ui.console.asks:
            fm.answer(answer)
        return fm

    def test_depth_limited_keeps_deeper_files(self):
        self.write('top/a.txt')
        self.write('top/l1/b.txt')
        self.write('top/l1/l2/deep.txt', 'DEEP')
        fm = self.run_flatten('flatten_write 2')
        self.assertTrue(os.path.exists(self.p('a.txt')))
        self.assertTrue(os.path.exists(self.p('b.txt')))
        # The deeper file survives in place, and so do its parents.
        with open(self.p('top/l1/l2/deep.txt')) as fh:
            self.assertEqual(fh.read(), 'DEEP')
        self.assertTrue(any('left in place' in n for n in fm.notes))

    def test_unlimited_removes_emptied_dirs(self):
        self.write('top/a.txt')
        self.write('top/l1/a.txt', 'second')
        self.run_flatten('flatten_write')
        self.assertFalse(os.path.exists(self.p('top')))
        self.assertEqual(self.files_under(self.d), {'a.txt', 'a_1.txt'})

    def test_no_answer_does_nothing(self):
        self.write('top/a.txt')
        self.run_flatten('flatten_write', answer='n')
        self.assertTrue(os.path.exists(self.p('top/a.txt')))

    def test_prompt_not_prefilled_console(self):
        self.write('top/a.txt')
        from cmds.nav import flatten_write
        fm = self.fm([self.p('top')])
        flatten_write('flatten_write').execute()
        self.assertEqual(fm.consoles, [])
        self.assertEqual(len(fm.ui.console.asks), 1)


@unittest.skipUnless(__import__('shutil').which('bsdtar'), 'needs bsdtar')
class Extract(Base):
    def setUp(self):
        Base.setUp(self)
        import subprocess
        self.write('src/a.txt', 'NEW')
        self.write('src/sub/b.txt', 'NEWB')
        self.arc = self.p('arc.tar.gz')
        subprocess.run(['bsdtar', '-czf', self.arc, '-C', self.p('src'), 'a.txt', 'sub'],
                       check=True)

    def test_extract_twice_never_merges(self):
        from cmds.archives import extract
        self.fm([self.arc])
        extract('extract').execute()
        self.write('arc/a.txt', 'EDITED')
        extract('extract').execute()
        with open(self.p('arc/a.txt')) as fh:
            self.assertEqual(fh.read(), 'EDITED')
        with open(self.p('arc_1/a.txt')) as fh:
            self.assertEqual(fh.read(), 'NEW')

    def test_extract_to_keeps_existing(self):
        from cmds.archives import extract_to
        self.write('dest/a.txt', 'MINE')
        fm = self.fm([self.arc])
        extract_to('extract_to dest').execute()
        with open(self.p('dest/a.txt')) as fh:
            self.assertEqual(fh.read(), 'MINE')
        self.assertTrue(os.path.exists(self.p('dest/sub/b.txt')))
        self.assertTrue(any('1 existing file(s) kept' in n for n in fm.notes), fm.notes)

    def test_bare_gz_is_decompressed(self):
        import gzip
        from cmds.archives import extract_here
        with gzip.open(self.p('notes.txt.gz'), 'wb') as fh:
            fh.write(b'hello')
        self.write('notes.txt', 'OLD')
        fm = self.fm([self.p('notes.txt.gz')])
        extract_here('extract_here').execute()
        with open(self.p('notes.txt')) as fh:
            self.assertEqual(fh.read(), 'OLD')
        with open(self.p('notes_1.txt')) as fh:
            self.assertEqual(fh.read(), 'hello')
        self.assertEqual(fm.bad, [])

    def test_flatten_cleans_tmp_on_failure(self):
        from cmds.archives import extract_flatten
        self.write('broken.tar.gz', 'not an archive')
        fm = self.fm([self.p('broken.tar.gz')])
        extract_flatten('extract_flatten').execute()
        self.assertEqual([n for n in os.listdir(self.d) if n.startswith('.ranger-flat-')], [])
        self.assertTrue(fm.bad)

    def test_flatten_success(self):
        from cmds.archives import extract_flatten
        self.fm([self.arc])
        extract_flatten('extract_flatten').execute()
        self.assertEqual(self.files_under(self.p('arc')), {'a.txt', 'b.txt'})
        self.assertEqual([n for n in os.listdir(self.d) if n.startswith('.ranger-flat-')], [])

    def test_pick_entries(self):
        from cmds.archives import _pick_entries
        entries = ['./', './.hidden', './sub/', './sub/b.txt', './subway.txt', 'a.txt']
        self.assertEqual(_pick_entries(entries, ['sub']), ['./sub/', './sub/b.txt'])
        self.assertEqual(_pick_entries(entries, ['.hidden', 'a.txt']), ['./.hidden', 'a.txt'])
        self.assertEqual(_pick_entries(entries, ['../escape']), [])


class Transfer(Base):
    def test_copyto_dir_and_collision(self):
        from cmds.transfer import copyto
        self.write('d/inner.txt', 'IN')
        self.write('f.txt', 'NEW')
        self.write('dest/f.txt', 'OLD')
        os.makedirs(self.p('dest/d'))
        fm = self.fm([self.p('d'), self.p('f.txt')])
        copyto('copyto dest').execute()
        with open(self.p('dest/f.txt')) as fh:
            self.assertEqual(fh.read(), 'OLD')
        with open(self.p('dest/f_1.txt')) as fh:
            self.assertEqual(fh.read(), 'NEW')
        self.assertTrue(os.path.exists(self.p('dest/d_1/inner.txt')))
        self.assertEqual(fm.bad, [])

    def test_moveto_partial_failure_reports(self):
        from cmds.transfer import moveto
        self.write('a.txt')
        os.makedirs(self.p('dest'))
        fm = self.fm([self.p('a.txt'), self.p('missing.txt')])
        moveto('moveto dest').execute()
        self.assertTrue(os.path.exists(self.p('dest/a.txt')))
        self.assertEqual(len(fm.bad), 1)

    def test_moveto_into_itself_is_reported(self):
        from cmds.transfer import moveto
        os.makedirs(self.p('d/sub'))
        fm = self.fm([self.p('d')])
        moveto('moveto d/sub').execute()
        self.assertTrue(os.path.isdir(self.p('d/sub')))
        self.assertEqual(len(fm.bad), 1)

    def test_mkcd_copy_dir(self):
        from cmds.nav import mkcd
        self.write('d/x.txt')
        fm = self.fm([self.p('d')])
        fm.ui.close_console = lambda: None
        mkcd('mkcd new').execute()
        fm.answer('c')
        self.assertTrue(os.path.exists(self.p('new/d/x.txt')))
        self.assertTrue(os.path.exists(self.p('d/x.txt')))


@unittest.skipUnless(__import__('shutil').which('magick'), 'needs ImageMagick')
class Transform(Base):
    def img(self, name):
        import subprocess
        subprocess.run(['magick', '-size', '4x2', 'xc:red', self.p(name)], check=True)
        return self.p(name)

    def test_single_png_runs_without_asking(self):
        from cmds.transform import image_flip
        fm = self.fm([self.img('a.png')])
        image_flip('image_flip').execute()
        self.assertEqual(fm.ui.console.asks, [])
        self.assertTrue(any('Flip: 1 file' in n for n in fm.notes), fm.notes)

    def test_jpeg_asks_and_no_means_untouched(self):
        from cmds.transform import image_negate
        path = self.img('a.jpg')
        before = os.path.getmtime(path), os.path.getsize(path)
        fm = self.fm([path])
        image_negate('image_negate').execute()
        self.assertIn('lossily', fm.ui.console.asks[0][0])
        fm.answer('n')
        self.assertEqual((os.path.getmtime(path), os.path.getsize(path)), before)

    def test_failure_is_notified_not_raised(self):
        from cmds.transform import image_trim
        self.write('bad.png', 'not an image')
        fm = self.fm([self.img('a.png'), self.p('bad.png')])
        image_trim('image_trim').execute()
        fm.answer('y')
        self.assertTrue(any('1 of 2 failed' in n for n in fm.bad), fm.notes)

    def test_convert_never_overwrites(self):
        from cmds.transform import image_convert
        src = self.img('a.png')
        self.write('a.jpg', 'MINE')
        self.fm([src])
        image_convert('image_convert jpg').execute()
        with open(self.p('a.jpg')) as fh:
            self.assertEqual(fh.read(), 'MINE')
        self.assertTrue(os.path.exists(self.p('a_1.jpg')))

    def test_pdf_merge_unique_output(self):
        import shutil as sh
        from cmds.transform import pdf_merge
        if not (sh.which('pdfunite') or sh.which('gs')):
            self.skipTest('no pdf tool')
        self.write('out.pdf', 'MINE')
        fm = self.fm([self.p('a.pdf'), self.p('b.pdf')])
        pdf_merge('pdf_merge out').execute()
        with open(self.p('out.pdf')) as fh:
            self.assertEqual(fh.read(), 'MINE')
        self.assertTrue(fm.bad)   # inputs don't exist → reported, not raised


class Trash(Base):
    def setUp(self):
        Base.setUp(self)
        from unittest import mock
        os.makedirs(self.p('home'))
        self._env = mock.patch.dict(os.environ, {'HOME': self.p('home')})
        self._env.start()
        # Force the manual fallback: no gio.
        self._gio = mock.patch('cmds.trash.subprocess.run', side_effect=OSError('no gio'))
        self._gio.start()

    def tearDown(self):
        self._gio.stop()
        self._env.stop()
        Base.tearDown(self)

    def test_percent_name_roundtrip(self):
        from cmds.trash import trash, undo_trash
        path = self.write('100%20off.txt', 'DATA')
        self.fm([path])
        trash('trash').execute()
        self.assertFalse(os.path.exists(path))
        self.fm()
        undo_trash('undo_trash').execute()
        with open(path) as fh:
            self.assertEqual(fh.read(), 'DATA')

    def test_large_selection_asks(self):
        from unittest import mock
        from cmds.trash import trash
        path = self.write('big.bin')
        fm = self.fm([path])
        with mock.patch('cmds.trash._TRASH_SIZE_WARN', 0.5):
            trash('trash').execute()
        self.assertTrue(os.path.exists(path))
        self.assertEqual(fm.consoles, [])
        fm.answer('y')
        self.assertFalse(os.path.exists(path))

    def test_trash_empty_asks(self):
        from cmds.trash import trash, trash_empty
        self.fm([self.write('a.txt')])
        trash('trash').execute()
        fm = self.fm()
        trash_empty('trash_empty').execute()
        files = self.p('home/.local/share/Trash/files')
        fm.answer('n')
        self.assertEqual(len(os.listdir(files)), 1)
        trash_empty('trash_empty').execute()
        fm.answer('y')
        self.assertEqual(os.listdir(files), [])


class SshMountUsers(Base):
    def test_refcount(self):
        import subprocess
        from cmds._util import ssh_mount_users
        m = self.p('host_')
        other = subprocess.Popen(['sleep', '30'])
        try:
            self.assertEqual(ssh_mount_users(m, add=os.getpid()), [os.getpid()])
            self.assertEqual(ssh_mount_users(m, add=other.pid), [os.getpid(), other.pid])
            # Releasing ours leaves the other live user → caller must not unmount.
            self.assertEqual(ssh_mount_users(m, remove=os.getpid()), [other.pid])
        finally:
            other.kill()
            other.wait()
        # Dead PIDs are pruned; the file goes away with the last user.
        self.assertEqual(ssh_mount_users(m), [])
        self.assertFalse(os.path.exists(m + '.pid'))

    def test_release_keeps_mount_used_by_other(self):
        import subprocess
        from unittest import mock
        from cmds import ssh
        m = self.p('host_')
        os.makedirs(m)
        other = subprocess.Popen(['sleep', '30'])
        try:
            ssh.ssh_mount_users(m, add=other.pid)
            ssh._ssh_sessions[m] = ('host', '')
            with mock.patch.object(ssh, 'fuse_unmount') as um, \
                    mock.patch('os.path.ismount', return_value=True):
                unmounted, others, _ = ssh._release_mount(m)
            self.assertFalse(unmounted)
            self.assertEqual(others, [other.pid])
            um.assert_not_called()
        finally:
            other.kill()
            other.wait()


if __name__ == '__main__':
    unittest.main()
