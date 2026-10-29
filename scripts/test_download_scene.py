"""Isolated tests of scripts/download_scene.py against an in-process fake of the client API."""
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import tempfile
import threading
import unittest
import uuid
from urllib.parse import quote

import download_scene
from download_scene import SceneError

SCENE = str(uuid.uuid4())


def blob(seed, size):
    return bytes((seed * 31 + i) % 251 for i in range(size))


class FakeApi:
    """Serves one scene description and its files; behaviour per file id can be changed mid-test."""

    def __init__(self):
        self.version = str(uuid.uuid4())
        self.files = {}      # relativePath -> {"id", "data"}
        self.requests = []   # (method, path, range, authorization)
        self.mode = {}       # fileId -> "ignore_range" | "corrupt" | "cut:<n>" | "conflict"
        self.descriptor = None
        self.add("standard/00.c.ply", blob(1, 150000))
        self.add("standard/01.c.ply", blob(2, 120000))
        self.add("high/00.c.ply", blob(3, 200000))
        self.add("common/settings.json", b'{"params":{}}')
        self.add("common/poster.jpg", blob(4, 5000))
        self.descriptor = {
            "formatVersion": 1, "defaultVariant": "standard",
            "transform": {"position": [0, 0, 0], "rotation": [0, 0, 0], "scale": [1, 1, 1]},
            "settings": "common/settings.json", "poster": "common/poster.jpg",
            "variants": [
                {"id": "standard", "name": "standard", "format": "4dv-compressed-ply", "segments": [
                    {"path": "standard/00.c.ply", "startSeconds": 0, "durationSeconds": 5},
                    {"path": "standard/01.c.ply", "startSeconds": 5, "durationSeconds": 3}]},
                {"id": "high", "name": "high", "format": "4dv-compressed-ply", "segments": [
                    {"path": "high/00.c.ply", "startSeconds": 0, "durationSeconds": 8}]}]}

    def add(self, path, data):
        self.files[path] = {"id": str(uuid.uuid4()), "data": data}

    def file_id(self, path):
        return self.files[path]["id"]

    def detail(self):
        files = []
        for path, item in sorted(self.files.items()):
            name = path.rsplit("/", 1)[-1]
            files.append({"fileId": item["id"], "relativePath": path, "bytes": len(item["data"]),
                          "sha256": hashlib.sha256(item["data"]).hexdigest(), "contentType": "application/octet-stream",
                          "downloadPath": f"/api/v1/client/scenes/{SCENE}/versions/{self.version}/files/{item['id']}/content/{quote(name)}"})
        return {"sceneId": SCENE, "name": "t", "versionId": self.version, "versionNo": 1,
                "descriptor": self.descriptor, "files": files, "fileCount": len(files),
                "totalBytes": sum(len(i["data"]) for i in self.files.values())}

    def content_requests(self, path=None):
        wanted = None if path is None else f"/{self.file_id(path)}/"
        return [r for r in self.requests if r[0] == "GET" and "/content/" in r[1] and (wanted is None or wanted in r[1])]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        api = self.server.api
        api.requests.append(("GET", self.path, self.headers.get("Range"), self.headers.get("Authorization")))
        if self.path == f"/api/v1/client/scenes/{SCENE}":
            body = json.dumps(api.detail()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        match = re.fullmatch(rf"/api/v1/client/scenes/{SCENE}/versions/([^/]+)/files/([^/]+)/content/.+", self.path)
        item = next((i for i in api.files.values() if match and i["id"] == match[2]), None)
        if not match or item is None:
            self.send_error(404)
            return
        mode = api.mode.get(item["id"], "")
        if mode == "conflict" or match[1] != api.version:
            body = b'{"code":"AR_409","message":"changed"}'
            self.send_response(409)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        data, etag = item["data"], '"' + hashlib.sha256(item["data"]).hexdigest() + '"'
        start, status = 0, 200
        range_header = self.headers.get("Range")
        if range_header and mode != "ignore_range" and self.headers.get("If-Range", etag) == etag:
            start, status = int(re.fullmatch(r"bytes=(\d+)-", range_header)[1]), 206
        body = data[start:]
        if mode == "corrupt":
            body = bytes([body[0] ^ 1]) + body[1:]
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        self.end_headers()
        if mode.startswith("cut:"):
            self.wfile.write(body[:int(mode[4:])])
            self.wfile.flush()
            self.close_connection = True
            return
        self.wfile.write(body)


class DownloadSceneTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.out = Path(self.temporary.name)
        self.api = FakeApi()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.api = self.api
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temporary.cleanup()

    def run_tool(self, variant="standard"):
        return download_scene.run(self.base, SCENE, variant, self.out, log=lambda message: None)

    def task_dir(self, variant="standard", version=None):
        return self.out / SCENE / (version or self.api.version) / variant

    def test_selected_variant_only_with_exact_payload_layout(self):
        payload = self.run_tool()
        task = self.task_dir()
        self.assertEqual(payload, task / "payload")
        self.assertEqual(sorted(p.relative_to(payload).as_posix() for p in payload.rglob("*") if p.is_file()),
                         ["common/poster.jpg", "common/settings.json", "standard/00.c.ply", "standard/01.c.ply"])
        for path, item in self.api.files.items():
            if not path.startswith("high/"):
                self.assertEqual((payload / path).read_bytes(), item["data"])
        self.assertEqual(self.api.content_requests(("high/00.c.ply")), [])
        ready = json.loads((task / "ready.json").read_text())
        self.assertEqual((ready["sceneId"], ready["versionId"], ready["variantId"]), (SCENE, self.api.version, "standard"))
        self.assertEqual(ready["totalBytes"], 150000 + 120000 + 13 + 5000)
        self.assertEqual(sorted(p.name for p in (task / ".transfer").iterdir() if p.suffix in (".part", ".json")), [])
        self.assertTrue(all(r[3] is None for r in self.api.requests), "client must be anonymous")

    def test_state_exists_before_any_file_and_ready_only_after_all(self):
        victim = self.api.file_id("standard/00.c.ply")
        self.api.mode[victim] = "cut:30000"
        with self.assertRaises(Exception):
            self.run_tool()
        task = self.task_dir()
        state = json.loads((task / ".download-state.json").read_text())
        self.assertEqual((state["sceneId"], state["versionId"], state["variantId"]), (SCENE, self.api.version, "standard"))
        self.assertEqual(state["completed"], [])
        self.assertFalse((task / "ready.json").exists())
        self.assertFalse((task / "payload" / "standard" / "00.c.ply").exists())
        self.assertEqual((task / ".transfer" / (victim + ".part")).stat().st_size, 30000)

    def test_resume_before_first_file_completes_uses_range(self):
        first = "standard/00.c.ply"
        self.api.mode[self.api.file_id(first)] = "cut:30000"
        with self.assertRaises(Exception):
            self.run_tool()
        del self.api.mode[self.api.file_id(first)]
        self.run_tool()
        resumed = self.api.content_requests(first)[-1]
        self.assertEqual(resumed[2], "bytes=30000-")
        self.assertTrue((self.task_dir() / "ready.json").exists())

    def test_completed_files_are_not_requested_again_after_a_cut(self):
        self.api.mode[self.api.file_id("standard/01.c.ply")] = "cut:1000"
        with self.assertRaises(Exception):
            self.run_tool()
        task = self.task_dir()
        completed = json.loads((task / ".download-state.json").read_text())["completed"]
        self.assertEqual(sorted(completed), sorted(self.api.file_id(p) for p in ("standard/00.c.ply",)))
        self.assertFalse((task / "ready.json").exists())
        self.api.requests.clear()
        self.api.mode.clear()
        self.run_tool()
        self.assertEqual(self.api.content_requests("standard/00.c.ply"), [])
        self.assertEqual(self.api.content_requests("standard/01.c.ply")[0][2], "bytes=1000-")
        self.assertTrue((task / "ready.json").exists())

    def test_leftover_empty_lock_files_do_not_block(self):
        self.api.mode[self.api.file_id("standard/00.c.ply")] = "cut:1000"
        with self.assertRaises(Exception):
            self.run_tool()
        self.assertTrue(list((self.out / SCENE / self.api.version).glob("*.lock")))
        self.assertTrue(list((self.task_dir() / ".transfer").glob("*.lock")))
        self.api.mode.clear()
        self.run_tool()  # would raise "another download is running" if file existence meant a lock

    def test_live_lock_is_reported_not_stolen(self):
        version_dir = self.out / SCENE / self.api.version
        version_dir.mkdir(parents=True)
        with download_scene.os_lock(version_dir / "standard.lock"):
            with self.assertRaisesRegex(SceneError, "another download"):
                self.run_tool()
        self.assertEqual(self.api.content_requests(), [])

    def test_ready_task_makes_no_content_request(self):
        self.run_tool()
        self.api.requests.clear()
        self.run_tool()
        self.assertEqual(self.api.content_requests(), [])

    def test_server_ignoring_range_is_truncated_and_rewritten(self):
        first = "standard/00.c.ply"
        self.api.mode[self.api.file_id(first)] = "cut:30000"
        with self.assertRaises(Exception):
            self.run_tool()
        self.api.mode[self.api.file_id(first)] = "ignore_range"
        payload = self.run_tool()
        self.assertEqual(self.api.content_requests(first)[-1][2], "bytes=30000-")
        self.assertEqual((payload / first).read_bytes(), self.api.files[first]["data"])

    def test_corrupted_transfer_never_becomes_ready_and_only_that_file_is_retried(self):
        bad = "standard/01.c.ply"
        self.api.mode[self.api.file_id(bad)] = "corrupt"
        with self.assertRaisesRegex(ValueError, "Checksum"):
            self.run_tool()
        task = self.task_dir()
        self.assertFalse((task / "ready.json").exists())
        self.assertFalse((task / "payload" / bad).exists())
        self.assertEqual(list((task / ".transfer").glob(self.api.file_id(bad) + ".part")), [])
        self.api.requests.clear()
        self.api.mode.clear()
        self.run_tool()
        self.assertEqual(self.api.content_requests("standard/00.c.ply"), [])
        self.assertEqual(len(self.api.content_requests(bad)), 1)
        self.assertTrue((task / "ready.json").exists())

    def test_version_change_stops_with_409_and_never_mixes_versions(self):
        old_version = self.api.version
        self.api.mode[self.api.file_id("standard/01.c.ply")] = "conflict"
        with self.assertRaises(SceneError) as caught:
            self.run_tool()
        self.assertEqual(caught.exception.code, 3)
        old_task = self.task_dir()
        self.assertFalse((old_task / "ready.json").exists())
        self.assertEqual(len(self.api.content_requests("standard/01.c.ply")), 1)  # no automatic retry loop
        # V2 is published: new ids, changed bytes in the same relative path.
        self.api.mode.clear()
        self.api.version = str(uuid.uuid4())
        self.api.add("standard/00.c.ply", blob(9, 150000))
        self.api.add("standard/01.c.ply", blob(8, 120000))
        payload = self.run_tool()
        new_task = self.task_dir()
        self.assertNotEqual(old_task, new_task)
        self.assertEqual((payload / "standard/00.c.ply").read_bytes(), self.api.files["standard/00.c.ply"]["data"])
        self.assertFalse((old_task / "ready.json").exists())
        self.assertEqual(json.loads((old_task / ".download-state.json").read_text())["versionId"], old_version)
        self.assertEqual((old_task / "payload" / "standard" / "00.c.ply").read_bytes(), blob(1, 150000))

    def test_unknown_variant_is_an_explicit_error_and_writes_nothing(self):
        with self.assertRaises(SceneError) as caught:
            self.run_tool("ultra")
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("standard", str(caught.exception))
        self.assertEqual(list(self.out.iterdir()), [])
        self.assertEqual(self.api.content_requests(), [])

    def test_non_empty_directory_without_state_is_refused(self):
        task = self.task_dir()
        task.mkdir(parents=True)
        (task / "keep.txt").write_text("mine")
        with self.assertRaisesRegex(SceneError, "not empty"):
            self.run_tool()
        self.assertEqual((task / "keep.txt").read_text(), "mine")

    def test_unowned_staging_directory_is_kept(self):
        version_dir = self.out / SCENE / self.api.version
        staging = version_dir / "standard.tmp"
        staging.mkdir(parents=True)
        (staging / "keep.txt").write_text("mine")
        with self.assertRaisesRegex(SceneError, "not empty"):
            self.run_tool()
        self.assertEqual((staging / "keep.txt").read_text(), "mine")
        self.assertFalse((version_dir / "standard").exists())

    def test_completed_file_that_vanished_is_downloaded_again(self):
        payload = self.run_tool()
        (payload / "common" / "settings.json").unlink()
        self.api.requests.clear()
        self.run_tool()
        self.assertEqual(len(self.api.content_requests("common/settings.json")), 1)
        self.assertEqual(self.api.content_requests("standard/00.c.ply"), [])
        self.assertTrue((payload / "common" / "settings.json").exists())

    def test_command_line_exit_codes(self):
        self.assertEqual(download_scene.main(["--base-url", self.base, "--scene-id", SCENE, "--variant", "high",
                                              "--output", str(self.out)]), 0)
        self.assertEqual(download_scene.main(["--base-url", self.base, "--scene-id", SCENE, "--variant", "nope",
                                              "--output", str(self.out)]), 2)


if __name__ == "__main__":
    unittest.main()
