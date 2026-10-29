"""Guard review identity/gates without operating services."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import review
from check_java import test_counts


class ReviewTests(unittest.TestCase):
    def test_ui_does_not_require_accounts_and_storage_requires_ingestion(self):
        suites = review.select_suites(['frontend/src/views/demo/scenes.vue'])
        self.assertIn('scene-ui', suites)
        self.assertIn('smoke', suites)
        self.assertNotIn('accounts', suites)
        self.assertIn('accounts', review.select_suites(['backend/ruoyi-framework/SysLoginService.java']))
        self.assertIn('ingestion', review.select_suites(['backend/ruoyi-ar/SceneVersionService.java']))

    def test_wrong_sha_cannot_supply_required_evidence(self):
        with patch('review.read', return_value={'status': 'passed', 'sha': 'b' * 40, 'sourceUnchanged': True}):
            with self.assertRaisesRegex(RuntimeError, 'evidence required'):
                review.passing(Path('.'), 'smoke', 'a' * 40)

    def test_path_rejects_ref_injection(self):
        for sha in ('main', '../main', 'a' * 39, 'A' * 40):
            with self.assertRaises(ValueError):
                review.directory(8, sha)
        with self.assertRaises(ValueError):
            review.directory(0, 'a' * 40)

    def test_dirty_source_rejected(self):
        with patch('review.run', side_effect=['a' * 40, ' M backend/pom.xml']):
            with self.assertRaisesRegex(RuntimeError, 'changed'):
                review.clean(Path('.'), 'a' * 40)

    def test_preview_rejects_unreviewed_or_new_head(self):
        with patch('review.clean'), patch('review.remote_head', return_value='b' * 40):
            with self.assertRaisesRegex(RuntimeError, 'must match'):
                review.serve(8, 'a' * 40, 'a' * 40)
        with patch('review.clean'):
            with self.assertRaisesRegex(RuntimeError, 'must match'):
                review.serve(8, 'a' * 40, None)

    def test_preview_rejects_failed_evidence(self):
        with patch('review.clean'), patch('review.remote_head', return_value='a' * 40), \
             patch('review.read', return_value={'status': 'failed'}):
            with self.assertRaisesRegex(RuntimeError, 'evidence required'):
                review.serve(8, 'a' * 40, 'a' * 40)

    def test_atomic_report_and_xml_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'report.json'
            review.write(path, {'status': 'passed'})
            self.assertEqual(review.read(path)['status'], 'passed')
            xml = Path(temp) / 'tests.xml'
            xml.write_text('<testsuite tests="5" failures="0" errors="0" skipped="1"/>')
            self.assertEqual(test_counts([xml]), dict(tests=5, failures=0, errors=0, skipped=1))

    def test_lifecycle_operations_cannot_overlap(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            with review.operation_lock(home):
                with self.assertRaises(FileExistsError):
                    with review.operation_lock(home):
                        self.fail('Overlapping build/preview permitted')
            self.assertFalse((home / 'operation.lock').exists())


if __name__ == '__main__':
    unittest.main()
