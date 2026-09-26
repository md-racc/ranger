"""Contract between the portal wrapper and cmds/picker.py.

xdg-desktop-portal-termfilechooser runs the wrapper with the arguments
    <multiple> <directory> <save> <path> <out> <debug>
and the wrapper must start `$TERMCMD ranger ...` with the RANGER_PICKER*
environment and exactly the arguments picker.py checks for each mode.

No wrapper ships with this config: point PICKER_WRAPPER at yours, e.g.
    PICKER_WRAPPER=~/.config/xdg-desktop-portal-termfilechooser/<script> \
        python -m unittest tests.test_wrapper -v
Without it the tests are skipped.
"""
import os
import stat
import subprocess
import tempfile
import unittest

WRAPPER = os.path.expanduser(os.environ.get('PICKER_WRAPPER', ''))
SKIP = ('set PICKER_WRAPPER=<path to your portal wrapper> to run the wrapper contract tests'
        if not WRAPPER else
        None if os.path.isfile(WRAPPER) else 'PICKER_WRAPPER not found: ' + WRAPPER)

FAKE_TERM = r'''#!/bin/sh
{
  echo "PICKER=$RANGER_PICKER"
  echo "OUT=$RANGER_PICKER_OUT"
  echo "PPATH=$RANGER_PICKER_PATH"
  for a in "$@"; do echo "ARG=$a"; done
} > "$FAKE_TERM_LOG"
'''


@unittest.skipIf(SKIP, SKIP)
class WrapperTest(unittest.TestCase):
    def run_wrapper(self, multiple, directory, save, path):
        with tempfile.TemporaryDirectory() as d:
            term = os.path.join(d, 'fake-term')
            with open(term, 'w') as f:
                f.write(FAKE_TERM)
            os.chmod(term, stat.S_IRWXU)
            log = os.path.join(d, 'log')
            env = dict(os.environ, TERMCMD=term, FAKE_TERM_LOG=log)
            subprocess.run([WRAPPER, multiple, directory, save, path, '/tmp/out', '0'],
                           env=env, check=True)
            with open(log) as f:
                return f.read().splitlines()

    def test_executable(self):
        self.assertTrue(os.access(WRAPPER, os.X_OK), WRAPPER + ' must be executable')

    def test_open(self):
        self.assertEqual(self.run_wrapper('0', '0', '0', '/d'), [
            'PICKER=open', 'OUT=/tmp/out', 'PPATH=/d',
            'ARG=ranger', 'ARG=--choosefile=/tmp/out', 'ARG=/d'])

    def test_multi(self):
        self.assertEqual(self.run_wrapper('1', '0', '0', '/d'), [
            'PICKER=multi', 'OUT=/tmp/out', 'PPATH=/d',
            'ARG=ranger', 'ARG=--choosefiles=/tmp/out', 'ARG=/d'])

    def test_dir_has_no_choosedir(self):
        self.assertEqual(self.run_wrapper('0', '1', '0', '/d'), [
            'PICKER=dir', 'OUT=/tmp/out', 'PPATH=/d',
            'ARG=ranger', 'ARG=--show-only-dirs', 'ARG=/d'])

    def test_save_has_no_choosefile(self):
        self.assertEqual(self.run_wrapper('0', '0', '1', '/d/r.pdf'), [
            'PICKER=save', 'OUT=/tmp/out', 'PPATH=/d/r.pdf',
            'ARG=ranger', 'ARG=--selectfile=/d/r.pdf'])

    def test_shell_metacharacters_survive(self):
        nasty = '/d/a "b" $HOME `id` \\x.txt'
        lines = self.run_wrapper('0', '0', '1', nasty)
        self.assertIn('ARG=--selectfile=' + nasty, lines)
        self.assertIn('PPATH=' + nasty, lines)


if __name__ == '__main__':
    unittest.main()
