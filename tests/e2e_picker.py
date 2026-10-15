"""End-to-end picker tests: portal wrapper + real ranger + this config,
driven in a private tmux server. Simulates the portal: creates the save
placeholder and reads the result file.

The config under test is the checkout containing this file (not necessarily
~/.config/ranger): a `ranger` shim first on PATH adds --confdir=<checkout>.
No wrapper ships with this config: PICKER_WRAPPER=<path> names the portal
wrapper to test (see the README's wrapper contract); without it the suite is
skipped. ranger's data dir and the zoxide database are redirected to a temp dir.

    cd <checkout> && PICKER_WRAPPER=<path> python -m unittest tests.e2e_picker -v
"""
import os
import shutil
import subprocess
import tempfile
import time
import unittest

CONFDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRAPPER = os.path.expanduser(os.environ.get('PICKER_WRAPPER', ''))
SOCK = 'rangerpicker-e2e'
RANGER = shutil.which('ranger')


def tmux(*args):
    return subprocess.run(['tmux', '-L', SOCK] + list(args), capture_output=True, text=True)


if not WRAPPER:
    SKIP = 'set PICKER_WRAPPER=<path to your portal wrapper> to run the e2e picker tests'
elif not os.path.isfile(WRAPPER):
    SKIP = 'PICKER_WRAPPER not found: ' + WRAPPER
elif not (shutil.which('tmux') and shutil.which('ranger')):
    SKIP = 'needs tmux and ranger'
else:
    SKIP = None


@unittest.skipIf(SKIP, SKIP)
class PickerE2E(unittest.TestCase):
    def setUp(self):
        tmux('kill-server')
        self.root = os.path.realpath(tempfile.mkdtemp(prefix='picker-e2e-'))
        self.work = os.path.join(self.root, 'work')
        os.mkdir(self.work)
        self.out = os.path.join(self.root, 'out')
        # Isolate the real zoxide DB, ranger data (history/bookmarks/tabs) and
        # cache from these throwaway runs — the plugin runs `zoxide add` on
        # every cd.
        for sub in ('zoxide', 'data', 'cache'):
            os.mkdir(os.path.join(self.root, sub))
        # The wrapper runs plain `ranger`: point it at this checkout's config.
        self.bin = os.path.join(self.root, 'bin')
        os.mkdir(self.bin)
        shim = os.path.join(self.bin, 'ranger')
        with open(shim, 'w') as f:
            f.write('#!/bin/sh\nexec "{}" --confdir="{}" "$@"\n'.format(RANGER, CONFDIR))
        os.chmod(shim, 0o755)

    def tearDown(self):
        tmux('kill-server')
        if getattr(self, 'wrapper', None) is not None:
            try:
                self.wrapper.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.wrapper.kill()
        shutil.rmtree(self.root, ignore_errors=True)

    # ── helpers ──────────────────────────────────────────────────────────
    def p(self, *parts):
        return os.path.join(self.work, *parts)

    def write(self, path, text=''):
        with open(path, 'w') as f:
            f.write(text)

    def read(self, path):
        with open(path) as f:
            return f.read()

    def launch(self, multiple, directory, save, path, cols=200, ready='q cancel'):
        # Like kitty, the terminal command blocks until ranger exits: the
        # portal (and the wrapper's one-time token) rely on that.
        termcmd = ('sh -c \'tmux -L {0} new-session -d -x {1} -y 50 "$@" && '
                   'while tmux -L {0} has-session 2>/dev/null; do sleep 0.1; done\' sh'
                   ).format(SOCK, cols)
        env = dict(os.environ, TERMCMD=termcmd)
        env.pop('TMUX', None)
        env['_ZO_DATA_DIR'] = os.path.join(self.root, 'zoxide')
        env['XDG_DATA_HOME'] = os.path.join(self.root, 'data')
        env['XDG_CACHE_HOME'] = os.path.join(self.root, 'cache')
        env['PATH'] = self.bin + os.pathsep + env.get('PATH', '')
        self.wrapper = subprocess.Popen(
            [WRAPPER, str(multiple), str(directory), str(save), path, self.out, '0'], env=env)
        return self.wait_screen(lambda s: ready in s)

    def screen(self):
        return tmux('capture-pane', '-p').stdout

    def wait_screen(self, pred, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            text = self.screen()
            if pred(text):
                return text
            time.sleep(0.1)
        self.fail('timed out; screen was:\n' + self.screen())

    def keys(self, *keys):
        # ranger's flushinput setting discards keys queued behind the one being
        # handled, so keys must arrive one at a time like real typing.
        for key in keys:
            tmux('send-keys', key)
            time.sleep(0.15)
        time.sleep(0.3)

    def type(self, text):
        tmux('send-keys', '-l', text)
        time.sleep(0.2)

    def wait_exit(self, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            if tmux('has-session').returncode != 0:
                if getattr(self, 'wrapper', None) is not None:
                    self.wrapper.wait(timeout=5)   # wrapper exits after ranger
                return
            time.sleep(0.1)
        self.fail('ranger did not exit; screen was:\n' + self.screen())

    def result(self):
        if not os.path.exists(self.out):
            return []
        return [line for line in self.read(self.out).splitlines() if line]

    # ── save ─────────────────────────────────────────────────────────────
    def save_setup(self, placeholder='report.pdf'):
        self.write(self.p('other.txt'), 'KEEP')
        ph = self.p(placeholder)
        self.write(ph, 'HELP')
        return ph

    def test_save_banner_and_enter_enter(self):
        ph = self.save_setup()
        screen = self.launch(0, 0, 1, ph)
        self.assertIn('SAVE ▸ report.pdf', screen)
        self.keys('Enter')
        self.wait_screen(lambda s: 'pick_save report.pdf' in s)
        self.keys('Enter')
        self.wait_exit()
        self.assertEqual(self.result(), [ph])

    def test_save_collision_bumps_name(self):
        self.write(self.p('report.pdf'), 'ORIGINAL')
        ph = self.save_setup('report.pdf_')
        self.launch(0, 0, 1, ph)
        self.keys('Enter')
        self.wait_screen(lambda s: 'pick_save report (1).pdf' in s)
        self.keys('Enter')
        self.wait_exit()
        self.assertEqual(self.result(), [self.p('report (1).pdf')])
        self.assertEqual(self.read(self.p('report.pdf')), 'ORIGINAL')
        self.assertFalse(os.path.exists(ph))

    def test_save_overwrite_declined_then_cancel(self):
        ph = self.save_setup()
        self.launch(0, 0, 1, ph)
        # the placeholder is hidden, so other.txt is the only row; l = replace it
        self.keys('g', 'g')
        self.keys('l')
        self.wait_screen(lambda s: 'pick_save other.txt' in s)
        self.keys('Enter')
        self.wait_screen(lambda s: 'Overwrite other.txt? (y/N)' in s)
        self.keys('n')
        self.keys('q')
        self.wait_exit()
        self.assertEqual(self.result(), [])
        self.assertEqual(self.read(self.p('other.txt')), 'KEEP')

    def test_save_overwrite_accepted(self):
        ph = self.save_setup()
        self.launch(0, 0, 1, ph)
        self.keys('g', 'g')
        self.keys('l')
        self.wait_screen(lambda s: 'pick_save other.txt' in s)
        self.keys('Enter')
        self.wait_screen(lambda s: 'Overwrite other.txt? (y/N)' in s)
        self.keys('y')
        self.wait_exit()
        self.assertEqual(self.result(), [self.p('other.txt')])

    def test_save_l_on_file_never_overwrites(self):
        ph = self.save_setup()
        self.launch(0, 0, 1, ph)
        self.keys('g', 'g')
        self.keys('l')
        self.wait_screen(lambda s: 'pick_save other.txt' in s)
        self.keys('Escape')
        self.keys('q')
        self.wait_exit()
        self.assertEqual(self.result(), [])
        self.assertEqual(self.read(self.p('other.txt')), 'KEEP')

    def test_save_into_subfolder(self):
        ph = self.save_setup()
        os.mkdir(self.p('sub'))
        self.launch(0, 0, 1, ph)
        # ⏎ on a folder saves *here*, not into it
        self.keys('g', 'g')
        self.keys('Enter')
        self.wait_screen(lambda s: 'pick_save report.pdf' in s)
        self.keys('Escape')
        # l enters sub/, the ghost follows, ⏎ saves there
        self.keys('l')
        self.wait_screen(lambda s: 'report.pdf  ⏎ saves here' in s
                         and '/sub' in s.splitlines()[0])
        self.keys('Enter')
        self.wait_screen(lambda s: 'pick_save report.pdf' in s)
        self.keys('Enter')
        self.wait_exit()
        self.assertEqual(self.result(), [self.p('sub', 'report.pdf')])
        self.assertFalse(os.path.exists(ph))

    def test_save_ghost_row(self):
        ph = self.save_setup()
        os.mkdir(self.p('sub'))
        self.write(self.p('sub', 'report.pdf'), 'OLD')
        screen = self.launch(0, 0, 1, ph)
        rows = screen.splitlines()
        # row 1 of the main column is the ghost; the real placeholder is hidden
        main = [r.split('│')[1] for r in rows[1:] if r.count('│') >= 2]
        self.assertRegex(main[0], r'\+ \S* ?report\.pdf  ⏎ saves here')
        self.assertEqual(sum('report.pdf' in r for r in main), 1, screen)
        # the name lines up with the real rows below it
        other = next(r for r in main if 'other.txt' in r)
        self.assertEqual(main[0].index('report.pdf'), other.index('other.txt'), screen)
        self.keys('g', 'g', 'l')
        screen = self.wait_screen(lambda s: 'report (1).pdf' in s)
        self.assertIn('report.pdf exists — l on it to replace', screen)
        self.assertIn('SAVE ▸ report (1).pdf', screen.splitlines()[0])
        self.keys('q')
        self.wait_exit()
        self.assertEqual(self.result(), [])
        self.assertEqual(self.read(ph), 'HELP')     # never moved on cancel

    # ── folder ───────────────────────────────────────────────────────────
    def test_dir_quit_cancels(self):
        os.mkdir(self.p('a'))
        screen = self.launch(0, 1, 0, self.work)
        self.assertIn('PICK FOLDER', screen)
        self.keys('q')
        self.wait_exit()
        self.assertEqual(self.result(), [])

    def test_esc_cancels_every_mode(self):
        self.write(self.p('one.txt'))
        os.mkdir(self.p('a'))
        for args in ((0, 0, 0), (1, 0, 0), (0, 1, 0)):
            with self.subTest(mode=args):
                self.launch(*args, path=self.work)
                if args[0]:
                    self.keys('j', ',')             # a mark must not survive Esc
                self.keys('Escape')
                self.wait_exit()
                self.assertEqual(self.result(), [])
                tmux('kill-server')

    def test_esc_in_visual_mode_only_leaves_it(self):
        self.write(self.p('one.txt'))
        self.write(self.p('two.txt'))
        self.launch(1, 0, 0, self.work)
        self.keys('V', 'j', 'Escape')
        time.sleep(0.5)
        self.assertEqual(tmux('has-session').returncode, 0, 'Esc in visual mode cancelled')
        self.keys('Escape')
        self.wait_exit()
        self.assertEqual(self.result(), [])

    def test_dir_enter_picks_highlighted(self):
        os.mkdir(self.p('a'))
        os.mkdir(self.p('b'))
        self.launch(0, 1, 0, self.work)
        # 'a' sorts first — already highlighted
        self.keys('Enter')
        self.wait_exit()
        self.assertEqual(self.result(), [self.p('a')])

    def test_dir_empty_folder_picks_itself(self):
        os.mkdir(self.p('a'))
        self.launch(0, 1, 0, self.p('a'))
        self.keys('Enter')
        self.wait_exit()
        self.assertEqual(self.result(), [self.p('a')])

    # ── open ─────────────────────────────────────────────────────────────
    def age(self, *paths):
        """Give paths decreasing mtimes: the first is the newest."""
        now = time.time()
        for i, path in enumerate(paths):
            os.utime(path, (now - 100 * i, now - 100 * i))

    def test_open_single(self):
        os.mkdir(self.p('dir'))
        self.write(self.p('one.txt'))
        self.write(self.p('two.txt'))
        self.age(self.p('dir'), self.p('one.txt'), self.p('two.txt'))
        screen = self.launch(0, 0, 0, self.work)
        self.assertIn('OPEN', screen)
        # newest first: the cursor starts on one.txt (the newest *file*)
        self.keys('Enter')
        self.wait_exit()
        self.assertEqual(self.result(), [self.p('one.txt')])

    def test_open_multi_marks(self):
        self.write(self.p('one.txt'))
        self.write(self.p('two.txt'))
        screen = self.launch(1, 0, 0, self.work)
        self.assertIn('OPEN MULTI', screen)
        # one.txt sorts first — already highlighted. mark_files has no
        # movedown, so step down between marks to hit both files.
        self.keys(',')
        self.keys('j')
        self.keys(',')
        self.keys('Enter')
        self.wait_exit()
        self.assertEqual(sorted(self.result()), [self.p('one.txt'), self.p('two.txt')])

    def test_open_ctrl_l(self):
        self.write(self.p('one.txt'))
        self.write(self.p('two.txt'))
        self.launch(0, 0, 0, self.work)
        self.keys('C-l')
        self.wait_screen(lambda s: 'pick_location' in s)
        self.type('two.txt')
        self.keys('Enter')
        self.wait_exit()
        self.assertEqual(self.result(), [self.p('two.txt')])


    # ── regressions ──────────────────────────────────────────────────────
    def multi_tree(self):
        os.mkdir(self.p('A'))
        os.mkdir(self.p('B'))
        self.write(self.p('A', 'a.txt'))
        self.write(self.p('B', 'b1.txt'))
        self.write(self.p('z.txt'))
        self.age(self.p('A'), self.p('B'), self.p('z.txt'))   # gg → A, then B

    def test_multi_enter_on_folder_with_marks_enters_it(self):
        self.multi_tree()
        self.launch(1, 0, 0, self.work)
        # into A, mark a.txt, back out, down to B, ⏎ must enter B (not send it)
        self.keys('g', 'g', 'l', ',', 'h', 'j', 'Enter')
        self.wait_screen(lambda s: 'b1.txt' in s.splitlines()[0])
        self.assertEqual(tmux('has-session').returncode, 0)
        self.keys('Enter')          # ⏎ on b1.txt: marks + this file
        self.wait_exit()
        self.assertEqual(self.result(), [self.p('A', 'a.txt'), self.p('B', 'b1.txt')])

    def test_multi_l_flattens_marked_folder_and_adds_file(self):
        self.multi_tree()
        self.launch(1, 0, 0, self.work)
        self.keys('g', 'g', ',')    # mark folder A (the cursor starts on z.txt)
        self.keys('G', 'l')         # l on z.txt
        self.wait_exit()
        self.assertEqual(self.result(), [self.p('A', 'a.txt'), self.p('z.txt')])

    def test_banner_at_40_columns(self):
        os.mkdir(self.p('a'))
        screen = self.launch(0, 1, 0, self.work, cols=40, ready='cancel')
        top = screen.splitlines()[0]
        self.assertIn('PICK FOLDER', top)
        self.assertIn('⏎ pick · q cancel', top)
        self.keys('q')
        self.wait_exit()

    def test_save_banner_at_60_columns_long_name(self):
        ph = self.save_setup('a-really-long-suggested-name-from-the-browser-2026.pdf')
        screen = self.launch(0, 0, 1, ph, cols=60, ready='cancel')
        top = screen.splitlines()[0]
        self.assertIn('⏎ save here · q cancel', top)
        self.assertIn('….pdf', top)
        self.keys('q')
        self.wait_exit()
        self.assertEqual(self.result(), [])


if __name__ == '__main__':
    unittest.main()
