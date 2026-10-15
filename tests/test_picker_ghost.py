"""Save-mode ghost row (placeholder follows the cwd), newest-first uploads,
and the y/N before a big folder flatten."""
import importlib
import os
import stat
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import ranger.api as api  # noqa: E402
import ranger.container.directory as directory  # noqa: E402
from cmds import picker  # noqa: E402
from _fakes import FakeFile, snapshot_plugin_patches  # noqa: E402
from test_picker_audit import MultiBase, marked, visited  # noqa: E402
from test_picker_commands import Base  # noqa: E402


def load_plugin(env):
    with mock.patch.dict(os.environ, env):
        sys.modules.pop('plugins.picker_mode', None)
        return importlib.import_module('plugins.picker_mode')


def text(parts):
    return ''.join(t for t, _ in parts)


class SaveHereTest(Base):
    def test_free_name(self):
        self.assertEqual(picker.save_here(self.path('sub'), self.ph), ('report.pdf', 'ok', None))

    def test_placeholder_itself_is_free(self):
        self.assertEqual(picker.save_here(self.work, self.ph), ('report.pdf', 'ok', None))

    def test_taken_name_is_bumped(self):
        self.write(self.path('sub', 'report.pdf'), 'OLD')
        self.assertEqual(picker.save_here(self.path('sub'), self.ph),
                         ('report (1).pdf', 'taken', 'report.pdf'))

    @unittest.skipIf(os.geteuid() == 0, 'root can write anywhere')
    def test_readonly_folder(self):
        ro = self.path('sub')
        os.chmod(ro, stat.S_IRUSR | stat.S_IXUSR)
        try:
            self.assertEqual(picker.save_here(ro, self.ph)[1], 'readonly')
        finally:
            os.chmod(ro, stat.S_IRWXU)


class GhostPluginTest(Base):
    def setUp(self):
        super().setUp()
        self.addCleanup(snapshot_plugin_patches())
        self.addCleanup(sys.modules.pop, 'plugins.picker_mode', None)
        self.envp = self.env('save')
        self.envp.start()
        self.addCleanup(self.envp.stop)
        self.mod = load_plugin(dict(os.environ))

    def test_ghost_row_follows_cwd(self):
        parts = self.mod.ghost_parts(self.path('sub'), 60, indent=3)
        self.assertEqual(parts[0], (' + ', 'mark'))
        self.assertEqual(parts[1], ('report.pdf', 'name'))
        self.assertIn('⏎ saves here', text(parts))
        self.assertEqual(len(text(parts)), 60)

    def test_ghost_row_names_the_clash(self):
        self.write(self.path('sub', 'report.pdf'), 'OLD')
        row = text(self.mod.ghost_parts(self.path('sub'), 80))
        self.assertTrue(row.startswith('report (1).pdf'), row)
        self.assertIn('report.pdf exists — l on it to replace', row)

    def test_narrow_clash_hint_falls_back_to_short_forms(self):
        self.write(self.path('sub', 'report.pdf'), 'OLD')
        self.assertIn('· name taken, l to replace',
                      text(self.mod.ghost_parts(self.path('sub'), 45)))
        self.assertIn('· taken', text(self.mod.ghost_parts(self.path('sub'), 24)))

    def test_title_shows_linemode_icon(self):
        row = text(self.mod.ghost_parts(self.work, 40, title=lambda n: 'I ' + n))
        self.assertTrue(row.startswith('I report.pdf  ⏎ saves here'), row)

    def test_narrow_ghost_drops_hint_then_shortens(self):
        self.assertEqual(text(self.mod.ghost_parts(self.work, 12)), 'report.pdf  ')
        row = text(self.mod.ghost_parts(self.work, 8))
        self.assertEqual(len(row), 8)
        self.assertIn('…', row)

    def test_placeholder_hidden_from_listings(self):
        ph, other = SimpleNamespace(path=self.ph), SimpleNamespace(path=self.other)
        self.assertFalse(directory.accept_file(ph, []))
        self.assertTrue(directory.accept_file(other, []))

    def test_live_banner_name(self):
        self.write(self.path('sub', 'report.pdf'), 'OLD')
        fm = SimpleNamespace(thisdir=SimpleNamespace(path=self.path('sub')))
        self.assertEqual(self.mod._live_name(fm), 'report (1).pdf')


class NoGhostOutsideSaveTest(Base):
    def test_open_mode_leaves_listing_alone(self):
        self.addCleanup(snapshot_plugin_patches())
        self.addCleanup(sys.modules.pop, 'plugins.picker_mode', None)
        accept = directory.accept_file
        with self.env('open'):
            load_plugin(dict(os.environ))
        self.assertIs(directory.accept_file, accept)


class NewestFirstTest(Base):
    def setUp(self):
        super().setUp()
        self.addCleanup(snapshot_plugin_patches())
        self.addCleanup(sys.modules.pop, 'plugins.picker_mode', None)

    def fake_fm(self, files):
        moved = []
        cwd = SimpleNamespace(files=files, pointed_obj=None,
                              load_content=lambda schedule: None, sort=lambda: None)

        def move_to_obj(f):
            moved.append(f)
            cwd.pointed_obj = f
        cwd.move_to_obj = move_to_obj
        fm = SimpleNamespace(thisdir=cwd, thisfile=None,
                             settings=SimpleNamespace(sort='natural', sort_reverse=True))
        return fm, moved

    def test_open_sorts_by_mtime_and_lands_on_newest_file(self):
        with self.env('open'):
            load_plugin(dict(os.environ))
        newest = FakeFile(self.other)
        fm, moved = self.fake_fm([FakeFile(self.path('sub')), newest])
        api.hook_init(fm)
        self.assertEqual((fm.settings.sort, fm.settings.sort_reverse), ('mtime', False))
        api.hook_ready(fm)
        self.assertEqual(moved, [newest])
        self.assertIs(fm.thisfile, newest)

    def test_save_mode_keeps_sort(self):
        with self.env('save'):
            load_plugin(dict(os.environ))
        fm, _ = self.fake_fm([])
        api.hook_init(fm)
        self.assertEqual(fm.settings.sort, 'natural')


class FlattenConfirmTest(MultiBase):
    def setUp(self):
        super().setUp()
        self.big = self.path('big')
        os.makedirs(self.big)
        for i in range(picker.FLATTEN_CONFIRM + 1):
            self.write(os.path.join(self.big, 'f{:02}.txt'.format(i)), 'x')

    def test_big_flatten_asks_first(self):
        with self.env('multi'), self.run_multi():
            fake = self.fm(cursor=self.a)
            fake.thistab.history = [visited(marked(self.big))]
            self.assertIsNone(picker.pick_files(fake))
            self.assertEqual(self.result(), [])
            (prompt, answer, _), = fake.ui.console.asks
            self.assertEqual(prompt, 'Send 21 files from 1 folder? (y/N)')
            answer('n')
            self.assertEqual(self.result(), [])
            with self.assertRaises(SystemExit):
                answer('y')
        self.assertEqual(len(self.result()), 21)

    def test_many_explicit_files_do_not_ask(self):
        files = [os.path.join(self.big, n) for n in sorted(os.listdir(self.big))]
        with self.env('multi'), self.run_multi():
            fake = self.fm(cursor=self.a)
            fake.thistab.history = [visited(*[marked(f) for f in files])]
            with self.assertRaises(SystemExit):
                picker.pick_files(fake)
        self.assertEqual(len(self.result()), 21)

    def test_small_flatten_sends_directly(self):
        with self.env('multi'), self.run_multi():
            fake = self.fm(cursor=self.a)
            fake.thistab.history = [visited(marked(self.path('sub')))]
            with self.assertRaises(SystemExit):
                picker.pick_files(fake)
        self.assertEqual(self.result(), [self.s1])


if __name__ == '__main__':
    unittest.main()
