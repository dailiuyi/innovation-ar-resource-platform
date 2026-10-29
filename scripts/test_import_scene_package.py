"""Importer identity checks that do not need a live platform."""
import json
import tempfile
import unittest
from pathlib import Path

import import_scene_package


DESCRIPTOR = {
    "formatVersion": 1, "defaultVariant": "standard",
    "transform": {"position": [0, 0, 0], "rotation": [0, 0, 0], "scale": [1, 1, 1]},
    "settings": "settings.json",
    "variants": [{"id": "standard", "name": "standard", "format": "4dv-compressed-ply",
                  "segments": [{"path": "model.4dv", "startSeconds": 0, "durationSeconds": 5}]}],
}


class WrongSceneApi:
    def __init__(self):
        self.uploads = []

    def request(self, method, path, body=None, stream=None, length=None, timeout=None):
        if method == "GET":
            stored = [{"relativePath": name, "fileId": name, "bytes": 2, "sha256": "unused", "status": "PENDING"}
                      for name in ("model.4dv", "settings.json")]
            return 200, {"id": "VERSION_B", "sceneId": "SCENE_B", "descriptor": DESCRIPTOR, "files": stored}
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
            descriptor = root / "resource.json"
            descriptor.write_text(json.dumps(DESCRIPTOR), encoding="utf-8")
            api = WrongSceneApi()
            with self.assertRaisesRegex(import_scene_package.ImportError_, "SCENE_B"):
                import_scene_package.import_package(api, "SCENE_A", package, descriptor, version_id="VERSION_B", log=lambda *_: None)
            self.assertEqual(api.uploads, [])


if __name__ == "__main__":
    unittest.main()
