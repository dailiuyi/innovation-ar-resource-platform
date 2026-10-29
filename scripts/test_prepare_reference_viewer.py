"""Behaviour tests for scripts/prepare_reference_viewer.py and scripts/prepare_4dgs_samples.py.

The viewer source here is a minimal FIXTURE with the file layout the tool checks; it is not the 4DV player and proves
nothing about playback. The real reference source is verified only by running the tool on it.
"""
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_4dgs_check
import prepare_4dgs_samples
import prepare_reference_viewer as tool

BUILD = 'viewer/20261016/230726'


def fixture(root, import_line=46, with_wasm=True):
    files = {
        'viewer/index.html': '<!doctype html><html><head><title>x</title><meta http-equiv="Content-Security-Policy" content="default-src *"></head></html>',
        f'{BUILD}/js/D8TV3hLS.js': '\n' * (import_line - 1) + 'import d from"./Drq6wweV.js";const u="http://127.0.0.1:8787/api";const b="20261016230726-5a40c21-local1";\n',
        f'{BUILD}/js/DfIBC3Nc.js': 'export default 1;',
        f'{BUILD}/js/Drq6wweV.js': 'export default {rocket:{}};',
        f'{BUILD}/assets/main.D9zuS0dI.css': 'a{}',
        f'{BUILD}/assets/worker-Cmdae1oK.js': '1',
        f'{BUILD}/assets/worker-Cn3mf7d7.js': '2',
        'viewer/model.ply': 'must not be copied',
        'viewer-static/zip.min.js': '3',
    }
    if with_wasm:
        files[f'{BUILD}/wasm/decoder.wasm'] = '\0asm'
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding='utf-8')
    precache = ','.join('{"revision":"%s","url":"%s"}' % ('0' * 32, url) for url in ('index.html', '20261016/230726/js/D8TV3hLS.js'))
    (root / 'viewer/sw.js').write_text('precacheAndRoute([%s]);' % precache, encoding='utf-8')
    return root


class ReferenceViewerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def run_tool(self, source, output=None):
        return tool.main(['--source', str(source), '--origin', 'http://127.0.0.1:18082', '--output', str(output or self.root / 'out')])

    def test_absent_source_fails_without_creating_anything(self):
        self.assertEqual(self.run_tool(self.root / 'missing'), 2)
        self.assertFalse((self.root / 'out').exists())

    def test_wrong_build_names_what_is_missing(self):
        source = fixture(self.root / 'src', with_wasm=False)
        (source / BUILD / 'js/DfIBC3Nc.js').unlink()
        with self.assertRaises(tool.Blocked) as caught:
            tool.check_source(source)
        self.assertIn('DfIBC3Nc.js', str(caught.exception))
        self.assertIn('wasm', str(caught.exception))
        self.assertEqual(self.run_tool(source), 2)

    def test_main_bundle_not_importing_catalogue_at_recorded_line_fails(self):
        self.assertEqual(self.run_tool(fixture(self.root / 'src', import_line=10)), 2)

    def test_prepared_copy(self):
        source = fixture(self.root / 'src')
        before = {p: p.read_bytes() for p in source.rglob('*') if p.is_file()}
        self.assertEqual(self.run_tool(source), 0)
        out = self.root / 'out'
        self.assertEqual(before, {p: p.read_bytes() for p in source.rglob('*') if p.is_file()}, 'source must stay untouched')
        self.assertFalse((out / 'viewer/model.ply').exists())
        main = (out / BUILD / 'js/D8TV3hLS.js').read_text()
        self.assertIn('http://127.0.0.1:18082/api', main)
        self.assertNotIn('8787', main)
        self.assertIn('20261016230726-5a40c21-platform1', main)
        adapter = (out / BUILD / 'js/Drq6wweV.js').read_text()
        self.assertIn("const ORIGIN = 'http://127.0.0.1:18082';", adapter)
        self.assertNotIn('rocket', adapter)
        html = (out / 'viewer/index.html').read_text()
        self.assertEqual(html.count('Content-Security-Policy'), 1)
        self.assertIn("default-src 'self'", html)
        self.assertNotIn('default-src *', html)
        sw = (out / 'viewer/sw.js').read_text()
        for url in re.findall(r'"url":"([^"]+)"', sw):
            expected = hashlib.md5((out / 'viewer' / url).read_bytes()).hexdigest()
            self.assertIn('{"revision":"%s","url":"%s"}' % (expected, url), sw)
        self.assertIn("default-src 'self'", (out / 'viewer/platform.html').read_text())
        self.assertTrue((out / 'viewer/platform.js').is_file())
        self.assertEqual(json.loads((out / tool.MARKER).read_text())['skippedModelFiles'], ['viewer/model.ply'])

    def test_rerun_replaces_own_output_but_refuses_foreign_directory(self):
        source = fixture(self.root / 'src')
        self.assertEqual(self.run_tool(source), 0)
        self.assertEqual(self.run_tool(source), 0)
        foreign = self.root / 'foreign'
        foreign.mkdir()
        (foreign / 'keep.txt').write_text('mine')
        self.assertEqual(self.run_tool(source, foreign), 2)
        self.assertEqual((foreign / 'keep.txt').read_text(), 'mine')

    def test_service_worker_entry_for_missing_file_fails(self):
        source = fixture(self.root / 'src')
        (source / 'viewer/sw.js').write_text('x([{"revision":"' + '0' * 32 + '","url":"gone.js"}])', encoding='utf-8')
        self.assertEqual(self.run_tool(source), 2)

    def test_origin_must_be_bare(self):
        with self.assertRaises(tool.Blocked):
            tool.validate_origin('http://127.0.0.1:18082/path')


class SamplesTest(unittest.TestCase):
    def make_samples(self, root):
        def touch(path, size=3):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'x' * size)
        wedding = root / 'wedding'
        for variant in ('standard_quality', 'high_quality', 'vr_foreground'):
            for name in ('00.c.ply', '01.c.ply'):
                touch(wedding / variant / name)
        for name in ('wedding_1205.jpg', 'wedding_settings.json', 'wedding.webm', 'wedding.wav'):
            touch(wedding / 'media_and_settings' / name)
        dance = root / 'dance_color'
        for index in range(15):
            start = 300 * index
            touch(dance / 'standard_quality' / f'new_dance_color_seg{start}-{start + 306}_mvc_sh0.4dv')
            touch(dance / 'high_quality' / f'new_dance_color_seg{start}-{start + 306}_mvc.4dv')
            touch(dance / 'vr_foreground' / f'{index:02d}.c.ply')
        for name in ('0512_dance_color.webm', 'dance_color_2_settings.json', '0512_dance_color.png', 'dance_color_audio_new.wav'):
            touch(dance / 'media_and_settings' / name)
        shiku = root / 'shiku_dtwd'
        touch(shiku / 'standard_quality/dtwd_seg_0_l.4dv')
        touch(shiku / 'high_quality/dtwd_seg_0_h.4dv')
        for name in ('shiku_dtwd.png', 'shiku_dtwd.webm', 'dtwd_settings_1.json'):
            touch(shiku / 'media_and_settings' / name)
        touch(root / 'wedding/unreferenced-report.md')

    def test_descriptors(self):
        with tempfile.TemporaryDirectory() as temp:
            source, output = Path(temp) / 'samples', Path(temp) / 'out'
            self.make_samples(source)
            self.assertEqual(prepare_4dgs_samples.main(['--source', str(source), '--output', str(output)]), 0)
            wedding = json.loads((output / 'wedding/resource.json').read_text())
            self.assertEqual([v['id'] for v in wedding['variants']], ['standard_quality', 'high_quality', 'vr_foreground'])
            self.assertEqual([(s['startSeconds'], s['durationSeconds']) for s in wedding['variants'][0]['segments']], [(0, 5), (5, 3)])
            self.assertEqual(wedding['audio'], 'media_and_settings/wedding.wav')
            dance = json.loads((output / 'dance_color/resource.json').read_text())
            segments = dance['variants'][0]['segments']
            self.assertEqual(len(segments), 15)
            self.assertEqual([s['startSeconds'] for s in segments], [5 * i for i in range(15)])
            self.assertEqual([s['durationSeconds'] for s in segments], [5] * 14 + [3])
            self.assertTrue(segments[1]['path'].endswith('seg300-606_mvc_sh0.4dv'))
            self.assertEqual(dance['audioPosition'], [0, 0, 0])
            shiku = json.loads((output / 'shiku_dtwd/resource.json').read_text())
            self.assertNotIn('audio', shiku)
            self.assertNotIn('audioPosition', shiku)
            self.assertEqual(shiku['transform']['scale'], [1.4, 1.4, 1.4])
            self.assertEqual(len(shiku['variants']), 2)
            summary = json.loads((output / 'samples-summary.json').read_text())
            self.assertEqual(summary['wedding']['files'], 10)
            self.assertFalse((source / 'resource.json').exists())

    def test_missing_model_directory_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'samples'
            self.make_samples(source)
            for path in (source / 'wedding/high_quality').iterdir():
                path.unlink()
            (source / 'wedding/high_quality').rmdir()
            self.assertEqual(prepare_4dgs_samples.main(['--source', str(source), '--output', str(Path(temp) / 'out')]), 2)


class OverlayConfigTest(unittest.TestCase):
    """The isolated gateway overlay; `nginx -t` on this text was run by hand (braces in a regex must be quoted)."""

    def test_scene_id_route_is_quoted_and_not_shadowed_by_the_viewer_prefix(self):
        config = prepare_4dgs_check.gateway_config(True)
        self.assertIn('location ~ "^/viewer/[0-9a-fA-F-]{36}$" {', config)
        self.assertIn('rewrite ^ /viewer/index.html break;', config)
        self.assertNotIn('^~ /viewer/ ', config)
        self.assertEqual(config.count('Cross-Origin-Embedder-Policy require-corp'), 3)
        self.assertEqual(prepare_4dgs_check.gateway_config(False), (prepare_4dgs_check.ROOT / 'deploy/nginx.conf').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
