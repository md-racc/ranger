import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cmds.nav import read_recent  # noqa: E402

XBEL = '''<?xml version="1.0" encoding="UTF-8"?>
<xbel version="1.0">
  <bookmark href="file://{d}/old.txt" added="2026-01-01T00:00:00Z" modified="2026-01-01T00:00:00Z"/>
  <bookmark href="file://{d}/with%20space.pdf" added="2026-03-01T00:00:00Z" modified="2026-03-01T00:00:00Z"/>
  <bookmark href="file://{d}/gone.txt" added="2026-04-01T00:00:00Z" modified="2026-04-01T00:00:00Z"/>
  <bookmark href="https://example.com/x" added="2026-05-01T00:00:00Z" modified="2026-05-01T00:00:00Z"/>
  <bookmark href="file://{d}/old.txt" added="2026-02-01T00:00:00Z" modified="2026-02-01T00:00:00Z"/>
</xbel>
'''


class ReadRecentTest(unittest.TestCase):
    def test_order_filter_dedupe(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ('old.txt', 'with space.pdf'):
                open(os.path.join(d, name), 'w').close()
            xbel = os.path.join(d, 'recent.xbel')
            with open(xbel, 'w') as f:
                f.write(XBEL.format(d=d))
            self.assertEqual(read_recent(xbel), [
                os.path.join(d, 'with space.pdf'),
                os.path.join(d, 'old.txt'),
            ])

    def test_missing_or_broken_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(read_recent(os.path.join(d, 'nope.xbel')), [])
            bad = os.path.join(d, 'bad.xbel')
            with open(bad, 'w') as f:
                f.write('<xbel><bookmark')
            self.assertEqual(read_recent(bad), [])


if __name__ == '__main__':
    unittest.main()
