"""Regression tests for picker edge cases (one class per issue) plus
coverage for pick_selection, _flatten, _marked_and_selected and
pick_archive."""
import importlib
import os
import sys
import tempfile
import time
import types
import unittest
from types import SimpleNamespace
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import ranger.core.actions as actions  # noqa: E402
import ranger.gui.widgets.titlebar as titlebar  # noqa: E402
from ranger.gui.bar import Bar  # noqa: E402
from cmds import picker  # noqa: E402
from _fakes import FakeFile, snapshot_plugin_patches  # noqa: E402
from test_picker_commands import Base  # noqa: E402


def visited(*files):
    """A history entry (ranger's visited dir) holding FakeFiles."""
    return SimpleNamespace(files=list(files))


def marked(path):
    fobj = FakeFile(path)
    fobj.marked = True
    return fobj


class MultiBase(Base):
    """Base + a.txt, b.txt, sub/s1.txt, sub/.hidden, and multi-mode args."""

    def setUp(self):
        super().setUp()
        self.a = self.path('a.txt')
        self.b = self.path('b.txt')
        self.s1 = self.path('sub', 's1.txt')
        for p in (self.a, self.b, self.s1, self.path('sub', '.hidden')):
            self.write(p, 'x')

    def args(self, mode='multi'):
        if mode == 'multi':
            return mock.Mock(choosefiles=self.out, choosefile=None, choosedir=None)
        return mock.Mock(choosefile=self.out, choosefiles=None, choosedir=None)

    def run_multi(self, mode='multi'):
        return mock.patch.object(picker, '_picker_args', return_value=self.args(mode))


# ── 1. <CR> on a directory always enters it ─────────────────────────────
class EnterDirWithMarksTest(MultiBase):
    def test_enter_on_dir_with_marks_elsewhere_enters(self):
        with self.env('multi'), self.run_multi():
            fake = self.fm(cursor=self.path('sub'))
            fake.thistab.history = [visited(marked(self.a))]
            picker.enter_or_pick('enter_or_pick').execute()
        self.assertEqual(fake.moved, [{'right': 1}])
        self.assertEqual(self.result(), [])

    def test_enter_on_file_with_marks_sends_marks_and_file(self):
        with self.env('multi'), self.run_multi():
            fake = self.fm(cursor=self.b)
            fake.thistab.history = [visited(marked(self.a), FakeFile(self.b))]
            fake.thistab.selection = [fake.thistab.history[0].files[0]]
            with self.assertRaises(SystemExit):
                picker.enter_or_pick('enter_or_pick').execute()
        self.assertEqual(self.result(), [self.a, self.b])


# ── pick_selection / _flatten / _marked_and_selected ─────────────────────
class SelectionHelpersTest(MultiBase):
    def test_marked_and_selected_order_and_dedupe(self):
        fake = self.fm(cursor=self.b)
        fake.thistab.history = [visited(marked(self.a)), visited(marked(self.a), FakeFile(self.b))]
        fake.thistab.selection = [FakeFile(self.b), FakeFile(self.a)]
        self.assertEqual(picker._marked_and_selected(fake), [self.a, self.b])

    def test_marked_and_selected_tolerates_unloaded_dirs(self):
        fake = self.fm()
        fake.thistab.history = [SimpleNamespace(files=None)]
        self.assertEqual(picker._marked_and_selected(fake), [])

    def test_flatten_expands_dirs_skips_hidden_and_dupes(self):
        os.symlink(self.path('sub'), self.path('linkdir'))
        got = picker._flatten([self.a, self.path('sub'), self.s1, self.path('linkdir'),
                               self.path('missing')])
        # an explicitly passed symlinked folder is walked; dupes by path are dropped
        self.assertEqual(got[:2], [self.a, self.s1])
        self.assertNotIn(self.path('sub', '.hidden'), got)
        self.assertEqual(len(got), len(set(got)))

    def test_flatten_keeps_explicit_hidden_file(self):
        hidden = self.path('sub', '.hidden')
        self.assertEqual(picker._flatten([hidden]), [hidden])

    def test_pick_selection_flattens_marked_folder(self):
        with self.env('multi'), self.run_multi():
            fake = self.fm(cursor=self.a)
            fake.thistab.history = [visited(marked(self.path('sub')), marked(self.a))]
            fake.thistab.selection = list(fake.thistab.history[0].files)
            with self.assertRaises(SystemExit):
                picker.pick_selection('pick_selection').execute()
        self.assertEqual(self.result(), [self.s1, self.a])

    def test_pick_selection_nothing_to_send(self):
        empty = self.path('empty')
        os.mkdir(empty)
        with self.env('multi'), self.run_multi():
            fake = self.fm()
            fake.thistab.selection = [marked(empty)]
            picker.pick_selection('pick_selection').execute()
        self.assertIn('Nothing to send', fake.notes[-1])
        self.assertEqual(self.result(), [])

    def test_pick_selection_single_dialog_refuses_many(self):
        with self.env('open'), self.run_multi('open'):
            fake = self.fm()
            fake.thistab.selection = [marked(self.a), marked(self.b)]
            picker.pick_selection('pick_selection').execute()
        self.assertIn('<Space>au', fake.notes[-1])

    def test_pick_selection_outside_picker(self):
        with mock.patch.object(picker, '_picker_args', return_value=None):
            fake = self.fm()
            picker.pick_selection('pick_selection').execute()
        self.assertIn('not running as a file picker', fake.notes[-1])


# ── 2. execute_file (l / <Right> / rifle) per mode ───────────────────────
class ExecuteFileGuardTest(MultiBase):
    def setUp(self):
        super().setUp()
        self.orig_exec = actions.Actions.execute_file
        self.addCleanup(snapshot_plugin_patches())
        self.calls = []

        def stub(fm, files, **kw):
            self.calls.append((files, kw))
            return 'launched'
        actions.Actions.execute_file = stub

    def tearDown(self):
        actions.Actions.execute_file = self.orig_exec
        sys.modules.pop('plugins.picker_mode', None)
        super().tearDown()

    def load(self, mode):
        with self.env(mode):
            sys.modules.pop('plugins.picker_mode', None)
            importlib.import_module('plugins.picker_mode')

    def test_multi_l_flattens_marks_and_adds_highlighted(self):
        self.load('multi')
        with self.env('multi'), self.run_multi():
            fake = self.fm(cursor=self.b)
            fake.thistab.history = [visited(marked(self.path('sub')), FakeFile(self.b))]
            fake.thistab.selection = [fake.thistab.history[0].files[0]]
            with self.assertRaises(SystemExit):
                actions.Actions.execute_file(fake, fake.thistab.get_selection())
        self.assertEqual(self.result(), [self.s1, self.b])
        self.assertEqual(self.calls, [])

    def test_multi_explicit_app_launches_not_picks(self):
        self.load('multi')
        with self.env('multi'), self.run_multi():
            fake = self.fm(cursor=self.a)
            result = actions.Actions.execute_file(fake, [FakeFile(self.a)], app='vim', mode=0)
        self.assertEqual(result, 'launched')
        files, kw = self.calls[0]
        self.assertEqual(kw.get('label'), 'vim')
        self.assertNotIn('app', kw)
        self.assertEqual(self.result(), [])

    def test_open_explicit_app_launches_not_picks(self):
        self.load('open')
        with self.env('open'), self.run_multi('open'):
            fake = self.fm(cursor=self.a)
            actions.Actions.execute_file(fake, [FakeFile(self.a)], app='vim')
        self.assertEqual(self.calls[0][1].get('label'), 'vim')
        self.assertFalse(os.path.exists(self.out))

    def test_open_l_picks_highlighted(self):
        self.load('open')
        with self.env('open'), self.run_multi('open'):
            fake = self.fm(cursor=self.a)
            with self.assertRaises(SystemExit):
                actions.Actions.execute_file(fake, [FakeFile(self.a)])
        self.assertEqual(self.read(self.out), self.a)

    def test_dir_mode_l_on_file_does_nothing(self):
        self.load('dir')
        with self.env('dir'):
            fake = self.fm(cursor=self.a)
            result = actions.Actions.execute_file(fake, [FakeFile(self.a)])
        self.assertIsNone(result)
        self.assertEqual(self.calls, [])
        self.assertIn('folder', fake.notes[-1].lower())
        self.assertEqual(self.result(), [])

    def test_numbered_open_with_still_launches(self):
        self.load('multi')
        with self.env('multi'), self.run_multi():
            fake = self.fm(cursor=self.a)
            actions.Actions.execute_file(fake, [FakeFile(self.a)], mode=2)
        self.assertEqual(self.calls[0][1], {'mode': 2})


# ── 3. pick_archive: unique dir per pick, cleanup, nothing to archive ────
class PickArchiveTest(MultiBase):
    def setUp(self):
        super().setUp()
        self.runtime = os.path.join(self.d, 'tmp')
        os.mkdir(self.runtime, 0o700)

    def archive(self, line, selection):
        env = mock.patch.object(tempfile, 'tempdir', self.runtime)
        with self.env('multi'), self.run_multi(), env:
            fake = self.fm(cursor=selection[0])
            fake.thistab.selection = [marked(p) for p in selection]
            try:
                picker.pick_archive(line).execute()
            except SystemExit:
                return fake, self.result()
            return fake, None

    def test_no_name_prefills_console(self):
        fake, res = self.archive('pick_archive', [self.a])
        self.assertIsNone(res)
        self.assertEqual(fake.consoles, ['pick_archive a.zip'])

    def test_same_name_twice_keeps_both(self):
        _, first = self.archive('pick_archive up.zip', [self.a])
        _, second = self.archive('pick_archive up.zip', [self.b])
        self.assertNotEqual(first, second)
        self.assertEqual(os.path.basename(first[0]), 'up.zip')
        self.assertEqual(os.path.basename(second[0]), 'up.zip')
        import zipfile
        with zipfile.ZipFile(first[0]) as zf:
            self.assertEqual(zf.namelist(), ['a.txt'])
        with zipfile.ZipFile(second[0]) as zf:
            self.assertEqual(zf.namelist(), ['b.txt'])
        self.assertTrue(first[0].startswith(self.runtime + '/ranger-upload-'))
        self.assertEqual(os.stat(os.path.dirname(first[0])).st_mode & 0o777, 0o700)

    def test_name_is_basename_and_gets_zip(self):
        _, res = self.archive('pick_archive ../../evil', [self.a])
        self.assertEqual(os.path.basename(res[0]), 'evil.zip')
        self.assertTrue(res[0].startswith(self.runtime + '/'))

    def test_folder_structure_kept_hidden_skipped(self):
        _, res = self.archive('pick_archive t.zip', [self.path('sub'), self.a])
        import zipfile
        with zipfile.ZipFile(res[0]) as zf:
            self.assertEqual(sorted(zf.namelist()), ['a.txt', 'sub/s1.txt'])

    def test_old_upload_dirs_cleaned_symlinks_untouched(self):
        old = os.path.join(self.runtime, 'ranger-upload-old')
        os.mkdir(old)
        self.write(os.path.join(old, 'x.zip'), 'z')
        week = time.time() - 7 * 86400
        os.utime(old, (week, week))
        fresh = os.path.join(self.runtime, 'ranger-upload-new')
        os.mkdir(fresh)
        victim = os.path.join(self.d, 'victim')
        os.mkdir(victim)
        self.write(os.path.join(victim, 'keep'), 'k')
        link = os.path.join(self.runtime, 'ranger-upload-link')
        os.symlink(victim, link)
        os.utime(link, (week, week), follow_symlinks=False)
        self.archive('pick_archive t.zip', [self.a])
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.isdir(fresh))
        self.assertTrue(os.path.exists(os.path.join(victim, 'keep')))

    def test_nothing_to_archive_leaves_no_dir(self):
        empty = self.path('empty')
        os.mkdir(empty)
        fake, res = self.archive('pick_archive t.zip', [empty])
        self.assertIsNone(res)
        self.assertIn('Nothing to archive', fake.notes[-1])
        self.assertEqual([n for n in os.listdir(self.runtime) if n.startswith('ranger-upload-')], [])


# ── 4. pick_save: placeholder rolled back if the result can't be written ─
class SaveRollbackTest(Base):
    def test_unwritable_out_moves_placeholder_back(self):
        self.out = os.path.join(self.d, 'no-such-dir', 'out')
        with self.env('save'):
            fake = self.fm()
            picker.pick_save('pick_save new.txt').execute()
        self.assertFalse(os.path.exists(self.path('new.txt')))
        self.assertEqual(self.read(self.ph), 'HELP')
        self.assertTrue(any('result' in n.lower() for n in fake.notes), fake.notes)

    def test_unset_out_notifies_instead_of_silent_cancel(self):
        env = {'RANGER_PICKER': 'save', 'RANGER_PICKER_PATH': self.ph, 'RANGER_PICKER_OUT': ''}
        with mock.patch.dict(os.environ, env):
            fake = self.fm()
            picker.pick_save('pick_save new.txt').execute()   # must not raise
        self.assertTrue(any('RANGER_PICKER_OUT' in n for n in fake.notes), fake.notes)
        self.assertEqual(self.read(self.ph), 'HELP')
        self.assertFalse(os.path.exists(self.path('new.txt')))

    def test_unset_out_in_dir_mode_notifies(self):
        env = {'RANGER_PICKER': 'dir', 'RANGER_PICKER_PATH': self.work, 'RANGER_PICKER_OUT': ''}
        with mock.patch.dict(os.environ, env):
            fake = self.fm(cursor=self.path('sub'))
            picker.enter_or_pick('enter_or_pick').execute()
        self.assertTrue(any('RANGER_PICKER_OUT' in n for n in fake.notes), fake.notes)


# ── 5. placeholder reached through a symlinked folder ────────────────────
class PlaceholderAliasTest(Base):
    def test_alias_of_placeholder_is_not_an_overwrite(self):
        alias = os.path.join(self.d, 'alias')
        os.symlink(self.work, alias)
        with self.env('save'):
            fake = self.fm(cwd=alias)
            with self.assertRaises(SystemExit):
                picker.pick_save('pick_save report.pdf').execute()
        self.assertEqual(fake.ui.console.asks, [])
        self.assertEqual(len(self.result()), 1)
        self.assertTrue(os.path.samefile(self.result()[0], self.ph))

    def test_alias_prefill_not_bumped(self):
        alias = os.path.join(self.d, 'alias')
        os.symlink(self.work, alias)
        with self.env('save'):
            fake = self.fm(cwd=alias, cursor=os.path.join(alias, 'report.pdf'))
            picker.prompt_save(fake)
        self.assertEqual(fake.consoles, ['pick_save report.pdf'])


# ── 6. output encoding / newlines ────────────────────────────────────────
class OutputEncodingTest(MultiBase):
    def test_non_utf8_name_written_as_raw_bytes(self):
        raw = os.path.join(os.fsencode(self.work), b'caf\xe9.txt')
        with open(raw, 'w') as f:
            f.write('x')
        name = os.fsdecode(raw)
        with self.env('multi'), self.run_multi():
            fake = self.fm(cursor=name)
            fake.thistab.selection = [FakeFile(name)]
            with self.assertRaises(SystemExit):
                picker.pick_selection('pick_selection').execute()
        with open(self.out, 'rb') as f:
            self.assertEqual(f.read(), raw + b'\n')

    def test_newline_in_name_refused(self):
        bad = self.path('a\nb.txt')
        self.write(bad, 'x')
        with self.env('multi'), self.run_multi():
            fake = self.fm(cursor=bad)
            fake.thistab.selection = [FakeFile(bad)]
            picker.pick_selection('pick_selection').execute()   # must not raise
        self.assertFalse(os.path.exists(self.out))
        self.assertIn('newline', fake.notes[-1])

    def test_newline_in_save_name_refused(self):
        with self.env('save'):
            fake = self.fm()
            picker.pick_save('pick_save x\ny.txt').execute()
        self.assertFalse(os.path.exists(self.out))
        self.assertTrue(os.path.exists(self.ph))
        self.assertIn('newline', fake.notes[-1])


# ── 7. unique_name keeps compound extensions ─────────────────────────────
class CompoundExtTest(unittest.TestCase):
    def test_compound_extensions(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ('a.tar.gz', 'a.tar.bz2', 'a.tar.xz', 'a.tar.zst', 'b.TAR.GZ',
                         '.bashrc', 'noext', 'x.y.pdf', '.tar.gz'):
                open(os.path.join(d, name), 'w').close()
            u = picker.unique_name
            self.assertEqual(u(d, 'a.tar.gz'), 'a (1).tar.gz')
            self.assertEqual(u(d, 'a.tar.bz2'), 'a (1).tar.bz2')
            self.assertEqual(u(d, 'a.tar.xz'), 'a (1).tar.xz')
            self.assertEqual(u(d, 'a.tar.zst'), 'a (1).tar.zst')
            self.assertEqual(u(d, 'b.TAR.GZ'), 'b (1).TAR.GZ')
            self.assertEqual(u(d, '.bashrc'), '.bashrc (1)')
            self.assertEqual(u(d, 'noext'), 'noext (1)')
            self.assertEqual(u(d, 'x.y.pdf'), 'x.y (1).pdf')
            self.assertEqual(u(d, '.tar.gz'), '.tar (1).gz')


# ── 8. resolve_target keeps the user's spaces ────────────────────────────
class ResolveSpacesTest(unittest.TestCase):
    def test_trailing_space_kept_newline_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(picker.resolve_target('a.txt ', d, 'n'), os.path.join(d, 'a.txt '))
            self.assertEqual(picker.resolve_target('a.txt\n', d, 'n'), os.path.join(d, 'a.txt'))
            self.assertEqual(picker.resolve_target('   ', d, 'n'), os.path.join(d, 'n'))

    def test_pick_location_tolerates_trailing_space_on_existing(self):
        with tempfile.TemporaryDirectory() as d:
            d = os.path.realpath(d)
            os.mkdir(os.path.join(d, 'sub'))
            from _fakes import FakeFM
            from ranger.core.shared import FileManagerAware
            picker._PICKER_ENV.clear()
            with mock.patch.dict(os.environ, {'RANGER_PICKER': 'open'}):
                fake = FakeFM(d)
                FileManagerAware.fm_set(fake)
                picker.pick_location('pick_location sub ').execute()
            self.assertEqual(fake.thisdir.path, os.path.join(d, 'sub'))


# ── 9. leaked picker env (sibling terminal window) is not a picker ──────
class EnvLeakTest(unittest.TestCase):
    def setUp(self):
        picker._PICKER_ENV.clear()

    def tearDown(self):
        picker._PICKER_ENV.clear()
        env = {k: v for k, v in os.environ.items() if not k.startswith('RANGER_PICKER')}
        with mock.patch.dict(os.environ, env, clear=True):
            importlib.reload(picker)

    def mode_with(self, env, **args):
        base = dict(choosefile=None, choosefiles=None, choosedir=None, selectfile=None,
                    show_only_dirs=False, paths=[])
        base.update(args)
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(picker, '_picker_args', return_value=SimpleNamespace(**base)):
            return picker.picker_mode()

    def test_plain_ranger_with_leaked_env_is_not_picker(self):
        for mode in ('open', 'multi', 'dir', 'save'):
            env = {'RANGER_PICKER': mode, 'RANGER_PICKER_OUT': '/tmp/o',
                   'RANGER_PICKER_PATH': '/tmp/p'}
            self.assertIsNone(self.mode_with(env), mode)

    def test_wrapper_args_match(self):
        env = {'RANGER_PICKER_OUT': '/tmp/o', 'RANGER_PICKER_PATH': '/tmp/p'}
        self.assertEqual(self.mode_with(dict(env, RANGER_PICKER='open'), choosefile='/tmp/o'), 'open')
        self.assertEqual(self.mode_with(dict(env, RANGER_PICKER='multi'), choosefiles='/tmp/o'),
                         'multi')
        self.assertEqual(self.mode_with(dict(env, RANGER_PICKER='dir'), show_only_dirs=True,
                                        paths=['/tmp/p']), 'dir')
        self.assertEqual(self.mode_with(dict(env, RANGER_PICKER='save'), selectfile='/tmp/p',
                                        paths=['/tmp']), 'save')

    def test_leaked_env_does_not_hijack_stock_choosedir(self):
        env = {'RANGER_PICKER': 'dir', 'RANGER_PICKER_OUT': '/tmp/o', 'RANGER_PICKER_PATH': '/tmp/p'}
        self.assertEqual(self.mode_with(env, choosedir='/tmp/cd'), 'dir')
        args = SimpleNamespace(choosedir='/tmp/cd', choosefile=None, choosefiles=None,
                               selectfile=None, show_only_dirs=False, paths=[])
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(picker, '_picker_args', return_value=args):
            self.assertIsNone(picker._env_mode())   # so _finish won't write the env's OUT

    def reload_with(self, env):
        clean = {k: v for k, v in os.environ.items() if not k.startswith('RANGER_PICKER')}
        clean.update(env)
        with mock.patch.dict(os.environ, clean, clear=True):
            importlib.reload(picker)
            leaked = [k for k in os.environ if k.startswith('RANGER_PICKER')]
        return leaked

    def test_token_consumed_once(self):
        with tempfile.TemporaryDirectory() as d:
            token = os.path.join(d, 'tok')
            open(token, 'w').close()
            env = {'RANGER_PICKER': 'dir', 'RANGER_PICKER_OUT': '/o',
                   'RANGER_PICKER_PATH': '/p', 'RANGER_PICKER_TOKEN': token}
            self.assertEqual(self.reload_with(env), [])
            self.assertEqual(picker._PICKER_ENV.get('RANGER_PICKER'), 'dir')
            self.assertFalse(os.path.exists(token))
            # a second ranger with the same (leaked) env: token gone → not a picker
            self.reload_with(env)
            self.assertEqual(picker._PICKER_ENV, {})

    def test_token_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, 'real')
            open(target, 'w').close()
            token = os.path.join(d, 'tok')
            os.symlink(target, token)
            self.reload_with({'RANGER_PICKER': 'dir', 'RANGER_PICKER_TOKEN': token})
            self.assertEqual(picker._PICKER_ENV, {})
            self.assertTrue(os.path.exists(target))


# ── 10/11. title-bar banner degrades gracefully ──────────────────────────
class BannerFitTest(unittest.TestCase):
    def setUp(self):
        self.orig_left = titlebar.TitleBar._get_left_part
        self.addCleanup(snapshot_plugin_patches())
        picker._PICKER_ENV.clear()

    def tearDown(self):
        titlebar.TitleBar._get_left_part = self.orig_left
        sys.modules.pop('plugins.picker_mode', None)

    def load(self, env):
        with mock.patch.dict(os.environ, env):
            sys.modules.pop('plugins.picker_mode', None)
            return importlib.import_module('plugins.picker_mode')

    def test_full_width_has_extras(self):
        mod = self.load({'RANGER_PICKER': 'open'})
        tag, hint = mod.banner_parts('open', width=200)
        self.assertEqual(tag, ' OPEN ')
        self.assertIn('⏎ pick · q cancel', hint)
        self.assertIn('^L path', hint)
        self.assertIn('gD ~/Downloads', hint)

    def test_narrow_keeps_tag_and_essential(self):
        mod = self.load({'RANGER_PICKER': 'dir'})
        for width in (40, 33):
            tag, hint = mod.banner_parts('dir', width=width)
            self.assertEqual(tag.strip(), 'PICK FOLDER')
            self.assertEqual(hint.strip(), '⏎ pick · q cancel')
            self.assertLessEqual(len(tag + hint), width)
        # tighter: padding goes, then the tag gets its short form
        tag, hint = mod.banner_parts('dir', width=26)
        self.assertEqual((tag, hint), (' FOLDER', ' ⏎ pick · q cancel '))
        tag, hint = mod.banner_parts('multi', width=30)
        self.assertIn('MULTI', tag)
        self.assertIn('⏎ send · q cancel', hint)
        self.assertLessEqual(len(tag + hint), 30)

    def test_save_name_truncated_with_ellipsis(self):
        mod = self.load({'RANGER_PICKER': 'save'})
        name = 'a-very-long-suggested-download-name-from-firefox.pdf'
        tag, hint = mod.banner_parts('save', width=45, name=name)
        self.assertIn('⏎ save here · q cancel', hint)
        self.assertIn('…', tag)
        self.assertTrue(tag.rstrip().endswith('.pdf'), tag)
        self.assertLessEqual(len(tag + hint), 45)
        tag, _ = mod.banner_parts('save', width=200, name='r.pdf')
        self.assertEqual(tag, ' SAVE ▸ r.pdf ')

    def test_more_tabs_says_Q(self):
        mod = self.load({'RANGER_PICKER': 'open'})
        _, hint = mod.banner_parts('open', width=200, tabs=2)
        self.assertIn('Q cancel', hint)
        self.assertNotIn('q cancel', hint)

    def render(self, mode, width, env, name_path=None, tabs=1):
        env = dict(env, RANGER_PICKER=mode)
        if name_path:
            env['RANGER_PICKER_PATH'] = name_path

        def stub(self, bar):
            for part in ('user', '@', 'host', ' '):
                bar.add(part, 'hostname', fixed=True)
            for d in ('home', 'user', 'Downloads'):
                bar.add(d, 'directory')
                bar.add('/', 'directory', fixed=True)
            bar.add('somefile.txt', 'file')

        titlebar.TitleBar._get_left_part = stub
        self.load(env)
        fake = types.SimpleNamespace(
            wid=width, settings=types.SimpleNamespace(hostname_in_titlebar=True),
            fm=types.SimpleNamespace(tabs={i: None for i in range(tabs)}))
        bar = Bar('in_titlebar')
        with mock.patch.dict(os.environ, env):
            titlebar.TitleBar._get_left_part(fake, bar)
        bar.addright('  ', 'space', fixed=True)
        try:
            bar.shrink_from_the_left(width)
        except ValueError:
            bar.shrink_by_removing(width)
        return ''.join(str(p) for p in bar.combine())

    def test_titlebar_40_columns_shows_mode_and_hint(self):
        text = self.render('dir', 40, {})
        self.assertIn('PICK FOLDER', text)
        self.assertIn('q cancel', text)

    def test_titlebar_60_columns_long_save_name(self):
        text = self.render('save', 60, {}, name_path='/d/' + 'x' * 50 + '.pdf')
        self.assertIn('SAVE', text)
        self.assertIn('⏎ save here · q cancel', text)
        self.assertIn('…', text)


if __name__ == '__main__':
    unittest.main()
