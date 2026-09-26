import importlib
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cmds import picker  # noqa: E402
from _fakes import FakeFM  # noqa: E402


class PickerModeTest(unittest.TestCase):
    def setUp(self):
        picker._PICKER_ENV.clear()

    def test_env_wins(self):
        for mode in ('open', 'multi', 'dir', 'save'):
            with mock.patch.dict(os.environ, {'RANGER_PICKER': mode}):
                self.assertEqual(picker.picker_mode(), mode)

    def test_bogus_env_falls_back_to_args(self):
        args = mock.Mock(choosedir=None, choosefiles='/o', choosefile=None)
        with mock.patch.dict(os.environ, {'RANGER_PICKER': 'nope'}), \
                mock.patch.object(picker, '_picker_args', return_value=args):
            self.assertEqual(picker.picker_mode(), 'multi')

    def test_args_fallback(self):
        env = {k: v for k, v in os.environ.items() if k != 'RANGER_PICKER'}
        cases = [
            (dict(choosedir='/o', choosefiles=None, choosefile=None), 'dir'),
            (dict(choosedir=None, choosefiles=None, choosefile='/o'), 'open'),
            (dict(choosedir=None, choosefiles=None, choosefile=None), None),
        ]
        for kw, want in cases:
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(picker, '_picker_args', return_value=mock.Mock(**kw)):
                self.assertEqual(picker.picker_mode(), want)

    def test_placeholder_only_in_save(self):
        with mock.patch.dict(os.environ, {'RANGER_PICKER': 'save', 'RANGER_PICKER_PATH': '/d/a.txt'}):
            self.assertEqual(picker.placeholder(), '/d/a.txt')
        with mock.patch.dict(os.environ, {'RANGER_PICKER': 'open', 'RANGER_PICKER_PATH': '/d'}):
            self.assertEqual(picker.placeholder(), '')


class PickerEnvNotInheritedTest(unittest.TestCase):
    """RANGER_PICKER* must not leak to child processes (a nested ranger
    started via `S`/:shell inside the picker would otherwise think it's the
    picker and could clobber the portal's out file)."""

    def tearDown(self):
        # Restore a clean module state so later tests aren't affected.
        picker._PICKER_ENV.clear()
        env = {k: v for k, v in os.environ.items() if not k.startswith('RANGER_PICKER')}
        with mock.patch.dict(os.environ, env, clear=True):
            importlib.reload(picker)

    def test_env_captured_and_removed(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith('RANGER_PICKER')}
        env.update({
            'RANGER_PICKER': 'dir',
            'RANGER_PICKER_OUT': '/o',
            'RANGER_PICKER_PATH': '/p',
        })
        with mock.patch.dict(os.environ, env, clear=True):
            importlib.reload(picker)
            self.assertEqual(picker.picker_mode(), 'dir')
            self.assertNotIn('RANGER_PICKER', os.environ)
            self.assertNotIn('RANGER_PICKER_OUT', os.environ)
            self.assertNotIn('RANGER_PICKER_PATH', os.environ)


class NameTest(unittest.TestCase):
    def setUp(self):
        picker._PICKER_ENV.clear()

    def test_suggested_name_strips_portal_underscores(self):
        self.assertEqual(picker.suggested_name('/d/report.pdf'), 'report.pdf')
        self.assertEqual(picker.suggested_name('/d/report.pdf__'), 'report.pdf')
        self.assertEqual(picker.suggested_name('/d/___'), 'untitled')
        self.assertEqual(picker.suggested_name(''), 'untitled')

    def test_unique_name(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(picker.unique_name(d, 'a.pdf'), 'a.pdf')
            open(os.path.join(d, 'a.pdf'), 'w').close()
            self.assertEqual(picker.unique_name(d, 'a.pdf'), 'a (1).pdf')
            open(os.path.join(d, 'a (1).pdf'), 'w').close()
            self.assertEqual(picker.unique_name(d, 'a.pdf'), 'a (2).pdf')
            open(os.path.join(d, '.rc'), 'w').close()
            self.assertEqual(picker.unique_name(d, '.rc'), '.rc (1)')

    def test_unique_name_free_path_counts_as_free(self):
        with tempfile.TemporaryDirectory() as d:
            ph = os.path.join(d, 'a.pdf')
            open(ph, 'w').close()
            self.assertEqual(picker.unique_name(d, 'a.pdf', free=ph), 'a.pdf')


class PathTest(unittest.TestCase):
    def test_resolve_target(self):
        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, 'sub'))
            j = os.path.join
            self.assertEqual(picker.resolve_target('x.txt', d, 'n.pdf'), j(d, 'x.txt'))
            self.assertEqual(picker.resolve_target('sub', d, 'n.pdf'), j(d, 'sub', 'n.pdf'))
            self.assertEqual(picker.resolve_target('new/', d, 'n.pdf'), j(d, 'new', 'n.pdf'))
            self.assertEqual(picker.resolve_target('', d, 'n.pdf'), j(d, 'n.pdf'))
            self.assertEqual(picker.resolve_target('  ', d, 'n.pdf'), j(d, 'n.pdf'))
            self.assertEqual(picker.resolve_target('sub/../y', d, 'n.pdf'), j(d, 'y'))
            self.assertEqual(picker.resolve_target('/abs/z', d, 'n.pdf'), '/abs/z')
            home = os.path.expanduser('~')
            self.assertEqual(picker.resolve_target('~/q', d, 'n.pdf'), j(home, 'q'))

    def test_tilde_and_console_path(self):
        home = os.path.expanduser('~')
        self.assertEqual(picker.tilde(home), '~')
        self.assertEqual(picker.tilde(home + '/a/b'), '~/a/b')
        self.assertEqual(picker.tilde('/tmp/x'), '/tmp/x')
        self.assertEqual(picker.tilde(home + 'xyz'), home + 'xyz')
        self.assertEqual(picker.console_path('/d/sub/f', '/d'), 'sub/f')
        self.assertEqual(picker.console_path('/d/f', '/d'), 'f')
        self.assertEqual(picker.console_path('/tmp/f', '/d'), '/tmp/f')
        self.assertEqual(picker.console_path(home + '/f', '/d'), '~/f')


class SelectFolderTest(unittest.TestCase):
    """select_folder(fm, path): put the cursor on `path` so <CR> picks it,
    even when show_hidden/filtering would otherwise hide it from select_file."""

    def test_visible_folder_lands_no_notify(self):
        fake = FakeFM('/d')
        picker.select_folder(fake, '/d/sub')
        self.assertEqual(fake.selected, '/d/sub')
        self.assertEqual(fake.thisfile.path, '/d/sub')
        self.assertEqual(fake.notes, [])

    def test_hidden_folder_flips_show_hidden_and_lands(self):
        fake = FakeFM('/d')
        picker.select_folder(fake, '/d/.hid')
        self.assertTrue(fake.settings.show_hidden)
        self.assertEqual(fake.thisfile.path, '/d/.hid')
        self.assertEqual(fake.notes, [])

    def test_unreachable_target_cds_and_notifies(self):
        fake = FakeFM('/d')
        fake.reject_select = True
        picker.select_folder(fake, '/')
        self.assertEqual(fake.thisdir.path, '/')
        self.assertEqual(len(fake.notes), 1)
        self.assertIn('press h then ⏎', fake.notes[0])


if __name__ == '__main__':
    unittest.main()
