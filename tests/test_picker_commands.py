import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ranger.core.shared import FileManagerAware  # noqa: E402
from cmds import picker  # noqa: E402
from _fakes import FakeFM  # noqa: E402


class Base(unittest.TestCase):
    """Temp dir with: sub/ (dir), other.txt ('KEEP'), and a save placeholder."""
    placeholder_name = 'report.pdf'

    def setUp(self):
        picker._PICKER_ENV.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.d = os.path.realpath(self.tmp.name)
        self.work = os.path.join(self.d, 'work')
        os.makedirs(os.path.join(self.work, 'sub'))
        self.other = self.path('other.txt')
        self.write(self.other, 'KEEP')
        self.ph = self.path(self.placeholder_name)
        self.write(self.ph, 'HELP')
        self.out = os.path.join(self.d, 'out')

    def tearDown(self):
        self.tmp.cleanup()

    def path(self, *parts):
        return os.path.join(self.work, *parts)

    def write(self, path, text):
        with open(path, 'w') as f:
            f.write(text)

    def read(self, path):
        with open(path) as f:
            return f.read()

    def env(self, mode):
        return mock.patch.dict(os.environ, {
            'RANGER_PICKER': mode, 'RANGER_PICKER_OUT': self.out,
            'RANGER_PICKER_PATH': self.ph if mode == 'save' else self.work})

    def fm(self, cursor=None, cwd=None):
        fake = FakeFM(cwd or self.work, cursor)
        FileManagerAware.fm_set(fake)
        return fake

    def result(self):
        return self.read(self.out).splitlines() if os.path.exists(self.out) else []


class EnterOrPickTest(Base):
    def test_dir_mode_picks_highlighted_dir(self):
        with self.env('dir'):
            self.fm(cursor=self.path('sub'))
            with self.assertRaises(SystemExit):
                picker.enter_or_pick('enter_or_pick').execute()
        self.assertEqual(self.result(), [self.path('sub')])

    def test_dir_mode_empty_dir_picks_cwd(self):
        empty = self.path('sub')
        with self.env('dir'):
            self.fm(cursor=None, cwd=empty)
            with self.assertRaises(SystemExit):
                picker.enter_or_pick('enter_or_pick').execute()
        self.assertEqual(self.result(), [empty])

    def test_save_mode_opens_prefilled_console(self):
        with self.env('save'):
            fake = self.fm(cursor=self.ph)
            picker.enter_or_pick('enter_or_pick').execute()
        self.assertEqual(fake.consoles, ['pick_save report.pdf'])
        self.assertEqual(self.result(), [])

    def test_open_mode_moves_right(self):
        with self.env('open'):
            fake = self.fm(cursor=self.other)
            picker.enter_or_pick('enter_or_pick').execute()
        self.assertEqual(fake.moved, [{'right': 1}])

    def test_multi_without_marks_moves_right(self):
        with self.env('multi'):
            fake = self.fm(cursor=self.path('sub'))
            picker.enter_or_pick('enter_or_pick').execute()
        self.assertEqual(fake.moved, [{'right': 1}])


class PromptSaveTest(Base):
    def test_enter_saves_in_cwd_whatever_the_cursor(self):
        # ⏎ = "save here" (the ghost row), even on a folder or another file
        for cursor in (self.path('sub'), self.other):
            with self.env('save'):
                fake = self.fm(cursor=cursor)
                picker.enter_or_pick('enter_or_pick').execute()
            self.assertEqual(fake.consoles, ['pick_save report.pdf'])

    def test_folder_given(self):
        with self.env('save'):
            fake = self.fm(cursor=self.path('sub'))
            picker.prompt_save(fake, fake.thisfile)
        self.assertEqual(fake.consoles, ['pick_save sub/report.pdf'])

    def test_existing_file_given_replaces_it(self):
        # l on a file (execute_file guard) → overwrite that file, after y/N
        with self.env('save'):
            fake = self.fm(cursor=self.other)
            picker.prompt_save(fake, fake.thisfile)
        self.assertEqual(fake.consoles, ['pick_save other.txt'])

    def test_empty_listing(self):
        with self.env('save'):
            fake = self.fm(cursor=None)
            picker.prompt_save(fake)
        self.assertEqual(fake.consoles, ['pick_save report.pdf'])

    def test_cwd_elsewhere_prefills_suggested_name_there(self):
        with self.env('save'):
            fake = self.fm(cursor=None, cwd=self.d)
            picker.prompt_save(fake, None)
        self.assertEqual(fake.consoles, ['pick_save report.pdf'])


class CollisionTest(Base):
    """Portal found report.pdf taken, so the placeholder is report.pdf_."""
    placeholder_name = 'report.pdf_'

    def test_prefill_is_bumped(self):
        self.write(self.path('report.pdf'), 'ORIGINAL')
        with self.env('save'):
            fake = self.fm(cursor=self.ph)
            picker.prompt_save(fake)
        self.assertEqual(fake.consoles, ['pick_save report (1).pdf'])

    def test_save_bumped_name_moves_placeholder(self):
        self.write(self.path('report.pdf'), 'ORIGINAL')
        with self.env('save'):
            self.fm(cursor=self.ph)
            with self.assertRaises(SystemExit):
                picker.pick_save('pick_save report (1).pdf').execute()
        target = self.path('report (1).pdf')
        self.assertEqual(self.result(), [target])
        self.assertTrue(os.path.exists(target))
        self.assertFalse(os.path.exists(self.ph))
        self.assertEqual(self.read(self.path('report.pdf')), 'ORIGINAL')


class PickSaveTest(Base):
    def test_save_on_placeholder(self):
        with self.env('save'):
            self.fm()
            with self.assertRaises(SystemExit):
                picker.pick_save('pick_save report.pdf').execute()
        self.assertEqual(self.result(), [self.ph])

    def test_save_on_placeholder_returns_without_falling_through(self):
        # Belt-and-suspenders: if _finish ever failed to raise, execute()
        # must still stop instead of falling into the overwrite-ask logic.
        with self.env('save'), mock.patch.object(picker, '_finish') as finish:
            fake = self.fm()
            picker.pick_save('pick_save report.pdf').execute()
        finish.assert_called_once_with(fake, [self.ph])
        self.assertEqual(fake.ui.console.asks, [])

    def test_new_name_in_subdir(self):
        with self.env('save'):
            self.fm()
            with self.assertRaises(SystemExit):
                picker.pick_save('pick_save sub/').execute()
        target = self.path('sub', 'report.pdf')
        self.assertEqual(self.result(), [target])
        self.assertTrue(os.path.exists(target))
        self.assertFalse(os.path.exists(self.ph))

    def test_missing_placeholder_creates_empty_target(self):
        os.remove(self.ph)
        with self.env('save'):
            self.fm()
            with self.assertRaises(SystemExit):
                picker.pick_save('pick_save new.txt').execute()
        self.assertEqual(self.read(self.path('new.txt')), '')

    def test_missing_parent_stays(self):
        with self.env('save'):
            fake = self.fm()
            picker.pick_save('pick_save nope/x.txt').execute()
        self.assertEqual(self.result(), [])
        self.assertIn('No such folder', fake.notes[-1])

    def test_missing_folder_trailing_slash_stays(self):
        with self.env('save'):
            fake = self.fm()
            picker.pick_save('pick_save nope/').execute()
        self.assertEqual(self.result(), [])
        self.assertIn('No such folder', fake.notes[-1])
        self.assertFalse(os.path.exists(self.path('nope')))

    def test_overwrite_declined(self):
        with self.env('save'):
            fake = self.fm()
            picker.pick_save('pick_save other.txt').execute()
            self.assertEqual(len(fake.ui.console.asks), 1)
            text, callback, choices = fake.ui.console.asks[0]
            self.assertEqual(text, 'Overwrite other.txt? (y/N)')
            self.assertEqual(choices[0], 'n')        # <Enter> = No
            callback('n')
        self.assertEqual(self.result(), [])
        self.assertEqual(self.read(self.other), 'KEEP')
        self.assertTrue(os.path.exists(self.ph))

    def test_overwrite_accepted(self):
        with self.env('save'):
            fake = self.fm()
            picker.pick_save('pick_save other.txt').execute()
            callback = fake.ui.console.asks[0][1]
            with self.assertRaises(SystemExit):
                callback('y')
        self.assertEqual(self.result(), [self.other])
        self.assertEqual(self.read(self.other), 'KEEP')   # the app overwrites, not us

    def test_broken_symlink_target_refused(self):
        broken = self.path('broken_link.txt')
        os.symlink(self.path('does-not-exist.txt'), broken)
        with self.env('save'):
            fake = self.fm()
            picker.pick_save('pick_save broken_link.txt').execute()
        self.assertEqual(self.result(), [])
        self.assertIn('Broken link', fake.notes[-1])
        self.assertEqual(fake.ui.console.asks, [])
        self.assertTrue(os.path.exists(self.ph))

    def test_not_in_save_mode(self):
        with self.env('open'):
            fake = self.fm()
            picker.pick_save('pick_save x').execute()
        self.assertIn('not in a save dialog', fake.notes[-1])

    def test_percent_in_name_is_literal(self):
        self.assertFalse(picker.pick_save.resolve_macros)
        self.assertFalse(picker.pick_location.resolve_macros)
        with self.env('save'):
            self.fm()
            with self.assertRaises(SystemExit):
                picker.pick_save('pick_save 100%d done.txt').execute()
        self.assertEqual(self.result(), [self.path('100%d done.txt')])


class PickLocationTest(Base):
    def test_outside_picker_redraws(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith('RANGER_PICKER')}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(picker, '_picker_args', return_value=None):
            fake = self.fm()
            picker.pick_location('pick_location').execute()
        self.assertEqual(fake.executed, ['redraw_window'])

    def test_no_arg_prefills_cwd(self):
        with self.env('open'):
            fake = self.fm()
            picker.pick_location('pick_location').execute()
        self.assertEqual(fake.consoles, ['pick_location ' + picker.tilde(self.work) + '/'])

    def test_dir_mode_picks_folder(self):
        with self.env('dir'):
            self.fm()
            with self.assertRaises(SystemExit):
                picker.pick_location('pick_location sub').execute()
        self.assertEqual(self.result(), [self.path('sub')])

    def test_dir_mode_picks_hidden_folder(self):
        hidden = self.path('.hid')
        os.makedirs(hidden)
        with self.env('dir'):
            self.fm()
            with self.assertRaises(SystemExit):
                picker.pick_location('pick_location .hid').execute()
        self.assertEqual(self.result(), [hidden])

    def test_other_mode_cds_into_folder(self):
        with self.env('open'):
            fake = self.fm()
            picker.pick_location('pick_location sub').execute()
        self.assertEqual(fake.thisdir.path, self.path('sub'))

    def test_dir_mode_missing_path_notifies(self):
        with self.env('dir'):
            fake = self.fm()
            picker.pick_location('pick_location nope').execute()
        self.assertIn('No such file or folder', fake.notes[-1])

    def test_multi_mode_existing_file_finishes(self):
        args = mock.Mock(choosefiles=self.out, choosefile=None, choosedir=None)
        with self.env('multi'), mock.patch.object(picker, '_picker_args', return_value=args):
            self.fm()
            with self.assertRaises(SystemExit):
                picker.pick_location('pick_location other.txt').execute()
        self.assertEqual(self.result(), [self.other])

    def test_file_in_save_mode_goes_to_pick_save(self):
        with self.env('save'):
            fake = self.fm()
            picker.pick_location('pick_location other.txt').execute()
        self.assertEqual(fake.executed, ['pick_save ' + self.other])

    def test_missing_dir_in_save_mode_keeps_trailing_slash(self):
        with self.env('save'):
            fake = self.fm()
            picker.pick_location('pick_location nope/').execute()
        self.assertEqual(fake.executed, ['pick_save ' + self.path('nope') + '/'])

    def test_new_path_in_save_mode_goes_to_pick_save(self):
        with self.env('save'):
            fake = self.fm()
            picker.pick_location('pick_location new.txt').execute()
        self.assertEqual(fake.executed, ['pick_save ' + self.path('new.txt')])

    def test_file_in_open_mode_picks(self):
        args = mock.Mock(choosefile=self.out, choosefiles=None, choosedir=None)
        with self.env('open'), mock.patch.object(picker, '_picker_args', return_value=args):
            self.fm()
            with self.assertRaises(SystemExit):
                picker.pick_location('pick_location other.txt').execute()
        self.assertEqual(self.read(self.out), self.other)

    def test_file_in_dir_mode_refused(self):
        with self.env('dir'):
            fake = self.fm()
            picker.pick_location('pick_location other.txt').execute()
        self.assertIn('Not a folder', fake.notes[-1])

    def test_missing_in_open_mode(self):
        with self.env('open'):
            fake = self.fm()
            picker.pick_location('pick_location nope.txt').execute()
        self.assertIn('No such file or folder', fake.notes[-1])


if __name__ == '__main__':
    unittest.main()
