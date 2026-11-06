"""Isolated importer contract checks against an in-memory administrator API; no live platform."""
import hashlib
import http.client
import json
import tempfile
import unittest
import uuid
from pathlib import Path

import import_scene_package


def digest(data):
    return hashlib.sha256(data).hexdigest()


class FakeApi:
    """Combined scene-create, scene-detail and per-file upload endpoints with idempotency by requestKey."""

    def __init__(self):
        self.scenes = {}
        self.keys = {}
        self.deleted_keys = set()
        self.calls = []
        self.uploads = []
        self.lose_next_create = False
        self.on_create = None
        self.token = None

    def seed_scene(self, files, name="seeded", description="", request_key=None, statuses=None):
        scene_id = str(uuid.uuid4())
        request_key = request_key or str(uuid.uuid4())
        self.scenes[scene_id] = {"id": scene_id, "name": name, "description": description, "enabled": True,
                                 "lockVersion": 0, "requestKey": request_key, "files": {}}
        for path, data in files.items():
            self.scenes[scene_id]["files"][path] = {
                "fileId": str(uuid.uuid4()), "relativePath": path, "bytes": len(data), "sha256": digest(data),
                "status": (statuses or {}).get(path, "PENDING"), "failureReason": None, "attempts": 0, "data": data}
        self.keys[request_key] = scene_id
        return scene_id

    def detail(self, scene):
        files = [{key: value for key, value in item.items() if key != "data"} for item in scene["files"].values()]
        return {"id": scene["id"], "name": scene["name"], "description": scene["description"], "enabled": scene["enabled"],
                "lockVersion": scene["lockVersion"], "uploadStatus": "READY", "fileCount": len(files),
                "availableCount": sum(1 for f in files if f["status"] == "AVAILABLE"),
                "failedCount": sum(1 for f in files if f["status"] == "FAILED"), "totalBytes": sum(f["bytes"] for f in files),
                "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-01-01T00:00:00Z", "files": files}

    def scene_by_file(self, scene_id, file_id):
        scene = self.scenes.get(scene_id)
        if scene is None:
            return None, None
        return scene, next((item for item in scene["files"].values() if item["fileId"] == file_id), None)

    def request(self, method, path, body=None, stream=None, length=None, timeout=None):
        self.calls.append((method, path))
        if method == "POST" and path == "/login":
            self.token = "token"
            return 200, {"token": self.token}
        if path == "/api/v1/scenes" and method == "POST":
            return self.create(body)
        if path.startswith("/api/v1/scenes/"):
            parts = path.split("/")
            scene_id = parts[4]
            if len(parts) == 5 and method == "GET":
                scene = self.scenes.get(scene_id)
                return (200, self.detail(scene)) if scene else (404, {"message": "missing"})
            if len(parts) == 7 and parts[5] == "files" and method == "GET":
                scene, item = self.scene_by_file(scene_id, parts[6])
                return (200, {key: value for key, value in item.items() if key != "data"}) if item else (404, {"message": "missing"})
            if len(parts) == 8 and parts[5] == "files" and parts[7] == "content" and method == "PUT":
                scene, item = self.scene_by_file(scene_id, parts[6])
                if item is None:
                    return 404, {"message": "missing"}
                sent = stream.read()
                if length is not None and len(sent) != length:
                    return 422, {"message": "length"}
                item["status"] = "AVAILABLE"
                item["attempts"] += 1
                self.uploads.append(item["relativePath"])
                return 200, {key: value for key, value in item.items() if key != "data"}
        raise AssertionError(f"unexpected {method} {path}")

    def create(self, body):
        if self.on_create:
            self.on_create(body)
        request_key, name, description = body["requestKey"], body["name"], body.get("description", "")
        manifest = sorted((f["relativePath"], f["bytes"], f["sha256"]) for f in body["files"])
        if request_key in self.deleted_keys:
            return 410, {"message": "deleted"}
        existing_id = self.keys.get(request_key)
        if existing_id is not None:
            scene = self.scenes[existing_id]
            stored = sorted((f["relativePath"], f["bytes"], f["sha256"]) for f in scene["files"].values())
            if (scene["name"], scene["description"], stored) != (name, description, manifest):
                return 409, {"message": "different manifest"}
            return 200, self.detail(scene)
        scene_id = str(uuid.uuid4())
        self.scenes[scene_id] = {"id": scene_id, "name": name, "description": description, "enabled": True,
                                 "lockVersion": 0, "requestKey": request_key, "files": {}}
        for item in body["files"]:
            self.scenes[scene_id]["files"][item["relativePath"]] = {
                "fileId": str(uuid.uuid4()), "relativePath": item["relativePath"], "bytes": item["bytes"],
                "sha256": item["sha256"], "status": "PENDING", "failureReason": None, "attempts": 0}
        self.keys[request_key] = scene_id
        if self.lose_next_create:
            self.lose_next_create = False
            raise http.client.RemoteDisconnected("response lost after commit")
        return 201, self.detail(self.scenes[scene_id])


class ImportScenePackageTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.package = self.root / "pkg"
        self.package.mkdir()
        (self.package / "settings.json").write_bytes(b"{}")
        (self.package / "model.4dv").write_bytes(b"ab")
        self.state = self.root / "state.json"
        self.api = FakeApi()

    def tearDown(self):
        self.temporary.cleanup()

    def run_import(self, scene_id=None, name="demo scene", description="imported", state=None):
        return import_scene_package.import_package(self.api, self.package, state or self.state, scene_id, name, description,
                                                   log=lambda *_: None)

    def test_create_uploads_every_file_and_rerun_does_not_duplicate_the_scene(self):
        result = self.run_import()
        self.assertTrue(result["created"])
        self.assertEqual(result["sceneId"], json.loads(self.state.read_text())["sceneId"])
        self.assertEqual(result["skippedAvailable"], [])
        self.assertEqual(sorted(self.api.uploads), ["model.4dv", "settings.json"])
        self.assertTrue(result["complete"])
        self.assertEqual(len(self.api.scenes), 1)
        self.assertEqual([call for call in self.api.calls if call[1].endswith("/content")][0][0], "PUT")
        self.assertFalse(any("version" in path or "publish" in path for _, path in self.api.calls))
        request_key = json.loads(self.state.read_text())["requestKey"]

        again = self.run_import()
        self.assertFalse(again["created"])
        self.assertEqual(len(self.api.scenes), 1)
        self.assertEqual(sorted(again["skippedAvailable"]), ["model.4dv", "settings.json"])
        self.assertEqual(self.api.uploads, ["model.4dv", "settings.json"])
        self.assertEqual(json.loads(self.state.read_text())["requestKey"], request_key)

    def test_request_key_is_persisted_before_create_and_a_lost_response_resumes(self):
        seen = {}

        def inspect(body):
            state = json.loads(self.state.read_text())
            seen.update(state=state, body=body)

        self.api.on_create = inspect
        self.api.lose_next_create = True
        with self.assertRaises(http.client.RemoteDisconnected):
            self.run_import()
        self.assertEqual(seen["state"]["requestKey"], seen["body"]["requestKey"])
        self.assertEqual(seen["state"]["name"], "demo scene")
        self.assertNotIn("sceneId", seen["state"])
        self.assertEqual(len(self.api.scenes), 1)

        self.api.on_create = None
        result = self.run_import()
        self.assertFalse(result["created"])
        self.assertEqual(len(self.api.scenes), 1)
        self.assertEqual(json.loads(self.state.read_text())["sceneId"], result["sceneId"])
        self.assertEqual(sorted(self.api.uploads), ["model.4dv", "settings.json"])

    def test_same_request_key_with_different_content_is_rejected(self):
        request_key = str(uuid.uuid4())
        self.api.seed_scene({"other.bin": b"x"}, name="other scene", request_key=request_key)
        self.state.write_text(json.dumps({"formatVersion": 2, "requestKey": request_key}), encoding="utf-8")
        with self.assertRaisesRegex(import_scene_package.ImportError_, "different name"):
            self.run_import(name="demo scene", description="imported")
        self.assertEqual(self.api.uploads, [])

    def test_deleted_scene_request_key_returns_410_and_is_not_recreated(self):
        request_key = str(uuid.uuid4())
        self.api.deleted_keys.add(request_key)
        self.state.write_text(json.dumps({"formatVersion": 2, "requestKey": request_key}), encoding="utf-8")
        with self.assertRaisesRegex(import_scene_package.ImportError_, "deleted"):
            self.run_import(name="demo scene", description="imported")
        self.assertEqual(self.api.scenes, {})
        self.assertEqual(self.api.uploads, [])

    def test_changed_input_is_refused_against_the_fixed_manifest(self):
        scene_id = self.api.seed_scene({"settings.json": b"[]", "model.4dv": b"ab"})
        self.state.write_text(json.dumps({"formatVersion": 2, "sceneId": scene_id}), encoding="utf-8")
        with self.assertRaisesRegex(import_scene_package.ImportError_, "fixed manifest"):
            self.run_import(scene_id=scene_id, name=None, description=None)
        self.assertEqual(self.api.uploads, [])

    def test_available_and_processing_files_are_not_resent(self):
        statuses = {"settings.json": "AVAILABLE", "model.4dv": "UPLOADING"}
        scene_id = self.api.seed_scene({"settings.json": b"{}", "model.4dv": b"ab"}, statuses=statuses)
        self.state.write_text(json.dumps({"formatVersion": 2, "sceneId": scene_id}), encoding="utf-8")
        result = self.run_import(scene_id=scene_id, name=None, description=None)
        self.assertEqual(self.api.uploads, [])
        self.assertEqual(result["skippedAvailable"], ["settings.json"])
        self.assertEqual(result["processing"], ["model.4dv"])
        self.assertFalse(result["complete"])

    def test_scene_id_from_another_state_file_is_refused(self):
        scene_id = self.api.seed_scene({"settings.json": b"{}", "model.4dv": b"ab"})
        self.state.write_text(json.dumps({"formatVersion": 2, "sceneId": str(uuid.uuid4())}), encoding="utf-8")
        with self.assertRaisesRegex(import_scene_package.ImportError_, "already belongs to scene"):
            self.run_import(scene_id=scene_id, name=None, description=None)

    def test_name_is_required_to_create_a_scene(self):
        with self.assertRaisesRegex(import_scene_package.ImportError_, "--name"):
            self.run_import(name=None)
        self.assertEqual(self.api.scenes, {})

    def test_every_file_is_registered_in_sorted_order(self):
        package = self.root / "nested"
        (package / "b" / "c").mkdir(parents=True)
        (package / "b" / "c" / "z.bin").write_bytes(b"z")
        (package / "a.txt").write_bytes(b"a")
        self.assertEqual(import_scene_package.package_paths(package), ["a.txt", "b/c/z.bin"])

    def test_state_file_inside_package_root_is_refused(self):
        with self.assertRaisesRegex(import_scene_package.ImportError_, "state-file"):
            self.run_import(state=self.package / "state.json")


if __name__ == "__main__":
    unittest.main()
