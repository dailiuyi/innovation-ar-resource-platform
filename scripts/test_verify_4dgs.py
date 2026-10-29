"""Tests for the pure helpers of scripts/verify_4dgs.py (log/JFR attribution and playback-evidence classification).
The instance-level behaviour is exercised by running the tool itself against the isolated instance."""
import datetime
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_4dgs as tool

SCENE = '11111111-1111-1111-1111-111111111111'
OTHER = '22222222-2222-2222-2222-222222222222'
FILE_A = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
FILE_B = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'


def line(scene, file, second, status=200, size=10):
    return (f'172.22.0.1 - - [29/Oct/2026:05:09:{second:02d} +0000] "GET /api/v1/client/scenes/{scene}/versions/v/files/{file}/content/x.ply '
            f'HTTP/1.1" {status} {size} "-" "Python-urllib/3.14" "-"\n')


class HelperTest(unittest.TestCase):
    def test_gateway_gets_filters_by_scene_and_whole_second_window(self):
        begin = datetime.datetime(2026, 10, 29, 5, 9, 10, tzinfo=datetime.timezone.utc).timestamp() + 0.4
        text = line(SCENE, FILE_A, 8) + line(SCENE, FILE_A, 10) + line(OTHER, FILE_B, 10) + line(SCENE, FILE_B, 11, size=7) + line(SCENE, FILE_B, 20)
        rows = tool.gateway_gets(text, SCENE, begin, begin + 1.5)
        self.assertEqual([(r[1], r[3]) for r in rows], [(FILE_A, '10'), (FILE_B, '7')])

    def test_parse_time_handles_utc_and_offsets_with_nanoseconds(self):
        base = datetime.datetime(2026, 10, 29, 5, 3, 57, tzinfo=datetime.timezone.utc).timestamp()
        self.assertAlmostEqual(tool.parse_time('2026-10-29T05:03:57.406089063Z'), base + 0.406089063, places=5)
        self.assertAlmostEqual(tool.parse_time('2026-10-29T13:03:57+08:00'), base, places=5)

    def test_windows_and_per_file_totals(self):
        events = [{'t': 1.0, 'read': True, 'path': f'/data/artifacts/committed/{FILE_A}.bin', 'bytes': 32},
                  {'t': 2.0, 'read': True, 'path': f'/data/artifacts/committed/{FILE_B}.bin', 'bytes': 5},
                  {'t': 2.5, 'read': False, 'path': f'/data/artifacts/staging/{FILE_B}.part', 'bytes': 9},
                  {'t': 3.0, 'read': True, 'path': f'/data/artifacts/committed/{FILE_A}.bin', 'bytes': 1}]
        self.assertEqual(tool.per_file(tool.window(events, 0.5, 2.9, read=True)), {FILE_A: 32, FILE_B: 5})
        self.assertEqual(tool.per_file(tool.window(events, 0.5, 2.9, read=False)), {FILE_B: 9})

    def test_longest_run_ignores_the_loop_wrap(self):
        samples = [(0.0, 5.0, 1), (0.5, 5.5, 2), (1.0, 7.9, 3), (1.5, 0.2, 4), (2.0, 0.7, 5), (2.5, 1.2, 6), (3.0, 1.7, 7)]
        self.assertEqual(tool.longest_run(samples), (1.5, 1.5))
        self.assertEqual(tool.longest_run([(0.0, 3.0, 1)]), (0.0, 0.0))

    def test_network_split_separates_platform_csp_blocked_and_leaked_requests(self):
        platform = {'url': tool.BASE + '/api/v1/client/scenes?limit=100', 'status': 200}
        blocked = {'url': 'https://pd.4dv.ai/array/x/config.js', 'failure': 'csp'}
        leaked = {'url': 'https://example.org/a.js', 'status': 200}
        local = {'url': 'blob:http://127.0.0.1:18082/abc', 'status': 200}
        self.assertEqual(tool.split_network([platform, blocked, leaked, local]), ([platform], [blocked], [leaked]))

    def test_console_findings_accept_only_csp_stopped_external_hosts_and_known_404s(self):
        csp = "Connecting to 'https://pd.4dv.ai/flags/?v=2' violates the following Content Security Policy directive: \"connect-src 'self'\"."
        own = f"Connecting to '{tool.BASE}/api/x' violates the following Content Security Policy directive: \"connect-src 'none'\"."
        known = 'Failed to load resource: the server responded with a status of 404 (Not Found)'
        unexpected, hosts = tool.console_findings([csp, known, own, 'pageerror: window is not defined'])
        self.assertEqual(hosts, {'pd.4dv.ai'})
        self.assertEqual(len(unexpected), 2)
        self.assertTrue(unexpected[1].startswith('pageerror'))


if __name__ == '__main__':
    unittest.main()
