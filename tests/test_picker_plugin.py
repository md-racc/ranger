import importlib
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import ranger.core.actions as actions  # noqa: E402
import ranger.gui.widgets.titlebar as titlebar  # noqa: E402
from _fakes import FakeFM, FakeFile, snapshot_plugin_patches  # noqa: E402
from cmds import picker as _picker  # noqa: E402

X = ' · ^L path · gD ~/Downloads  '


class PluginTest(unittest.TestCase):
    def setUp(self):
        self.orig_exec = actions.Actions.execute_file
        self.addCleanup(snapshot_plugin_patches())
        self.orig_left = titlebar.TitleBar._get_left_part
        _picker._PICKER_ENV.clear()

    def tearDown(self):
        actions.Actions.execute_file = self.orig_exec
        titlebar.TitleBar._get_left_part = self.orig_left
        sys.modules.pop('plugins.picker_mode', None)

    def load(self, env):
        with mock.patch.dict(os.environ, env):
            sys.modules.pop('plugins.picker_mode', None)
            return importlib.import_module('plugins.picker_mode')

    def test_banner_texts(self):
        mod = self.load({'RANGER_PICKER': 'open'})
        self.assertEqual(mod.banner_parts('open'), (' OPEN ', ' ⏎ pick · q cancel' + X))
        self.assertEqual(mod.banner_parts('multi'),
                         (' OPEN MULTI ', ' , mark · ⏎ send · q cancel' + X))
        self.assertEqual(mod.banner_parts('dir'),
                         (' PICK FOLDER ', ' ⏎ pick · h⏎ pick current · q cancel' + X))
        self.assertIsNone(mod.banner_parts(None))

    def test_save_banner_uses_suggested_name(self):
        mod = self.load({'RANGER_PICKER': 'save', 'RANGER_PICKER_PATH': '/d/report.pdf_'})
        with mock.patch.dict(os.environ, {'RANGER_PICKER': 'save',
                                          'RANGER_PICKER_PATH': '/d/report.pdf_'}):
            self.assertEqual(mod.banner_parts('save'), (' SAVE ▸ report.pdf ', ' ⏎ save here · l replace · q cancel' + X))

    def test_no_patch_outside_picker(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith('RANGER_PICKER')}
        with mock.patch.dict(os.environ, env, clear=True):
            sys.modules.pop('plugins.picker_mode', None)
            importlib.import_module('plugins.picker_mode')
        self.assertIs(actions.Actions.execute_file, self.orig_exec)
        self.assertIs(titlebar.TitleBar._get_left_part, self.orig_left)

    def test_open_mode_guards_execute_file(self):
        # open mode too: a named program must launch, not pick (see test_picker_audit)
        self.load({'RANGER_PICKER': 'open'})
        self.assertIsNot(actions.Actions.execute_file, self.orig_exec)
        self.assertIsNot(titlebar.TitleBar._get_left_part, self.orig_left)

    def test_save_mode_guard_redirects_open_to_prompt(self):
        with tempfile.TemporaryDirectory() as d:
            ph = os.path.join(d, 'report.pdf')
            other = os.path.join(d, 'other.txt')
            for p in (ph, other):
                open(p, 'w').close()
            env = {'RANGER_PICKER': 'save', 'RANGER_PICKER_PATH': ph}
            self.load(env)
            fake = FakeFM(d, other)
            with mock.patch.dict(os.environ, env):
                result = actions.Actions.execute_file(fake, [FakeFile(other)])
            self.assertIsNone(result)
            self.assertEqual(fake.consoles, ['pick_save other.txt'])

    def test_save_guard_accepts_bare_file(self):
        with tempfile.TemporaryDirectory() as d:
            ph = os.path.join(d, 'report.pdf')
            other = os.path.join(d, 'other.txt')
            for p in (ph, other):
                open(p, 'w').close()
            env = {'RANGER_PICKER': 'save', 'RANGER_PICKER_PATH': ph}
            self.load(env)
            fake = FakeFM(d, other)
            with mock.patch.dict(os.environ, env):
                result = actions.Actions.execute_file(fake, FakeFile(other))
            self.assertIsNone(result)
            self.assertEqual(fake.consoles, ['pick_save other.txt'])

    def test_save_guard_passes_app_calls_through(self):
        with tempfile.TemporaryDirectory() as d:
            ph = os.path.join(d, 'report.pdf')
            other = os.path.join(d, 'other.txt')
            for p in (ph, other):
                open(p, 'w').close()
            env = {'RANGER_PICKER': 'save', 'RANGER_PICKER_PATH': ph}

            calls = []

            def stub(self, files, **kw):
                calls.append((files, kw))
                return 'orig'

            actions.Actions.execute_file = stub
            self.load(env)
            fake = FakeFM(d, other)

            with mock.patch.dict(os.environ, env):
                result = actions.Actions.execute_file(fake, [FakeFile(other)], app='editor')
            self.assertEqual(result, 'orig')
            self.assertEqual(len(calls), 1)
            self.assertEqual(fake.consoles, [])

            # no program named (`r` + flags only) = the default action → prompt
            with mock.patch.dict(os.environ, env):
                result = actions.Actions.execute_file(fake, [FakeFile(other)], app='')
            self.assertIsNone(result)
            self.assertEqual(len(calls), 1)
            self.assertEqual(fake.consoles, ['pick_save other.txt'])

    def test_banner_after_hostname(self):
        with mock.patch.dict(os.environ, {'RANGER_PICKER': 'open'}):
            def stub_with_hostname(self, bar):
                bar.add('user', 'hostname', fixed=True)
                bar.add('@', 'hostname', fixed=True)
                bar.add('host', 'hostname', fixed=True)
                bar.add(' ', 'hostname', fixed=True)
                bar.add('path', 'directory')

            titlebar.TitleBar._get_left_part = stub_with_hostname
            sys.modules.pop('plugins.picker_mode', None)
            importlib.import_module('plugins.picker_mode')

            from ranger.gui.bar import Bar
            bar = Bar('in_titlebar')
            fake_self = types.SimpleNamespace(
                settings=types.SimpleNamespace(hostname_in_titlebar=True))
            titlebar.TitleBar._get_left_part(fake_self, bar)
            self.assertEqual(
                [str(p) for p in bar.left],
                ['user', '@', 'host', ' ', ' OPEN ', ' ⏎ pick · q cancel' + X, 'path'])

        with mock.patch.dict(os.environ, {'RANGER_PICKER': 'open'}):
            def stub_no_hostname(self, bar):
                bar.add('path', 'directory')

            titlebar.TitleBar._get_left_part = stub_no_hostname
            sys.modules.pop('plugins.picker_mode', None)
            importlib.import_module('plugins.picker_mode')

            from ranger.gui.bar import Bar
            bar2 = Bar('in_titlebar')
            fake_self2 = types.SimpleNamespace(
                settings=types.SimpleNamespace(hostname_in_titlebar=False))
            titlebar.TitleBar._get_left_part(fake_self2, bar2)
            self.assertEqual(
                [str(p) for p in bar2.left],
                [' OPEN ', ' ⏎ pick · q cancel' + X, 'path'])


if __name__ == '__main__':
    unittest.main()
