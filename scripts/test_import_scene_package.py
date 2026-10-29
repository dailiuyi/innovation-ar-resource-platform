"""Importer identity checks that do not need a live platform."""
import tempfile
import unittest
from pathlib import Path

import import_scene_package


class WrongSceneApi:
    def __init__(self):
        self.uploads = []

    def request(self, method, path, body=None, stream=None, length=None, timeout=None):
        if method == "GET":
            stored = [{"relativePath": name, "fileId": name, "bytes": 2, "sha256": "unused", "status": "PENDING"}
                      for name in ("model.4dv", "settings.json")]
            return 200, {"id": "VERSION_B", "sceneId": "SCENE_B", "files": stored}
        if method == "PUT":
            self.uploads.append(path)
            return 200, {"status": "AVAILABLE"}
        raise AssertionError(method)


class ImportScenePackageTest(unittest.TestCase):
    def test_version_from_another_scene_is_refused_before_upload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "pkg"
            package.mkdir()
            (package / "settings.json").write_text("{}", encoding="utf-8")
            (package / "model.4dv").write_bytes(b"ab")
            api = WrongSceneApi()
            with self.assertRaisesRegex(import_scene_package.ImportError_, "SCENE_B"):
                import_scene_package.import_package(api, "SCENE_A", package, root / "state.json", version_id="VERSION_B",
                                                    log=lambda *_: None)
            self.assertEqual(api.uploads, [])

    def test_every_file_is_registered_in_sorted_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            (package / "b" / "c").mkdir(parents=True)
            (package / "b" / "c" / "z.bin").write_bytes(b"z")
            (package / "a.txt").write_bytes(b"a")
            self.assertEqual(import_scene_package.package_paths(package), ["a.txt", "b/c/z.bin"])

    def test_state_file_inside_package_root_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            (package / "a.txt").write_bytes(b"a")
            with self.assertRaisesRegex(import_scene_package.ImportError_, "state-file"):
                import_scene_package.import_package(WrongSceneApi(), "SCENE_A", package, package / "state.json",
                                                    log=lambda *_: None)


if __name__ == "__main__":
    unittest.main()
