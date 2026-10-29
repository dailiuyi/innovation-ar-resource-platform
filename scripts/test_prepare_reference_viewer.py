"""Behaviour tests for scripts/prepare_reference_viewer.py.

The viewer source here is a minimal FIXTURE with the file layout the tool checks; it is not the 4DV player and proves
nothing about playback. The real reference source is verified only by running the tool on it.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_4dgs_check
import prepare_reference_viewer as tool

BUILD = 'viewer/20261016/230726'


def fixture(root, import_line=46, with_wasm=True):
    files = {
        f'{BUILD}/manifest.webmanifest': '{"start_url":"http://127.0.0.1:8787/viewer/20261016/230726/"}',
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
        self.assertIn('/viewer/20261016/230726/js/D8TV3hLS.js', html)
        self.assertIn('id="dropArea"', html)
        self.assertFalse((out / 'viewer/sw.js').exists(), 'no service worker is invented')
        self.assertIn('http://127.0.0.1:18082/viewer/20261016/230726/', (out / BUILD / 'manifest.webmanifest').read_text())
        self.assertIn("default-src 'self'", (out / 'viewer/platform.html').read_text())
        self.assertTrue((out / 'viewer/platform.js').is_file())
        marker = json.loads((out / tool.MARKER).read_text())
        self.assertEqual(marker['skippedModelFiles'], ['viewer/model.ply'])
        self.assertEqual(marker['csp'], tool.CSP)

    def test_rerun_replaces_own_output_but_refuses_foreign_directory(self):
        source = fixture(self.root / 'src')
        self.assertEqual(self.run_tool(source), 0)
        self.assertEqual(self.run_tool(source), 0)
        foreign = self.root / 'foreign'
        foreign.mkdir()
        (foreign / 'keep.txt').write_text('mine')
        self.assertEqual(self.run_tool(source, foreign), 2)
        self.assertEqual((foreign / 'keep.txt').read_text(), 'mine')

    def test_source_without_entry_page_is_accepted_and_page_is_not_fetched(self):
        source = fixture(self.root / 'src')
        self.assertFalse((source / 'viewer/index.html').exists())
        self.assertFalse((source / 'viewer/sw.js').exists())
        self.assertEqual(self.run_tool(source), 0)

    def test_origin_must_be_bare(self):
        with self.assertRaises(tool.Blocked):
            tool.validate_origin('http://127.0.0.1:18082/path')


class OverlayConfigTest(unittest.TestCase):
    """The isolated gateway overlay; `nginx -t` on this text was run by hand (braces in a regex must be quoted)."""

    def test_scene_id_route_is_quoted_and_not_shadowed_by_the_viewer_prefix(self):
        config = prepare_4dgs_check.gateway_config(tool.CSP)
        self.assertIn('location ~ "^/viewer/[0-9a-fA-F-]{36}$" {', config)
        self.assertIn('rewrite ^ /viewer/index.html break;', config)
        self.assertNotIn('^~ /viewer/ ', config)
        self.assertEqual(config.count('Cross-Origin-Embedder-Policy require-corp'), 3)
        self.assertEqual(config.count(f'add_header Content-Security-Policy "{tool.CSP}" always;'), 3)
        self.assertEqual(prepare_4dgs_check.gateway_config(None), (prepare_4dgs_check.ROOT / 'deploy/nginx.conf').read_text(encoding='utf-8'))

    def test_csp_comes_from_the_prepared_marker_only(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(prepare_4dgs_check.Blocked):
                prepare_4dgs_check.reference_csp(Path(temp))


if __name__ == '__main__':
    unittest.main()
