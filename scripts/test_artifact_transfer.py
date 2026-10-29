"""Isolated standard-library tests; no project services or real resources are used."""
from http.client import IncompleteRead
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from artifact_transfer import (DownloadBusy, download, reference_server, digest, os_lock, validate_relative_path,
                               restore_tree)


class TransferTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.package = self.root / 'resource.bin'
        self.package.write_bytes(bytes(range(256)) * 1024)
        self.descriptor = {'bytes': self.package.stat().st_size, 'sha256': digest(self.package)}
        self.destination = self.root / "download.bin"
        self.server = reference_server(self.package)
        self.requests = []
        original = self.server.RequestHandlerClass.do_GET
        requests = self.requests

        def observed(handler):
            requests.append(dict(handler.headers))
            original(handler)

        self.server.RequestHandlerClass.do_GET = observed
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/artifact"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def get(self):
        return download(self.url, self.destination, self.descriptor["bytes"], self.descriptor["sha256"])

    def partial(self, size=80000, etag=None):
        partial = self.destination.with_name(self.destination.name + "." + self.descriptor["sha256"] + ".part")
        partial.write_bytes(self.package.read_bytes()[:size])
        partial.with_suffix(".json").write_text(json.dumps({"etag": etag or '"' + self.descriptor["sha256"] + '"'}))
        return partial

    def test_transfer_and_cache(self):
        self.get()
        self.get()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.destination.read_bytes(), self.package.read_bytes())

    def test_resume_exact_offset(self):
        partial = self.partial()
        self.get()
        self.assertEqual(self.requests[0]["Range"], "bytes=80000-")
        self.assertFalse(partial.exists())
        self.assertEqual(digest(self.destination), self.descriptor["sha256"])

    def test_changed_validator_restarts_instead_of_appending(self):
        self.partial(etag='"previous"')
        self.get()
        self.assertEqual(self.destination.read_bytes(), self.package.read_bytes())

    def test_no_validator_restarts(self):
        partial = self.partial()
        partial.with_suffix(".json").unlink()
        self.get()
        self.assertNotIn("Range", self.requests[0])

    def test_completed_partial_needs_no_request(self):
        self.partial(self.descriptor["bytes"])
        self.get()
        self.assertEqual(len(self.requests), 0)

    def test_corrupt_partial_never_becomes_final(self):
        partial = self.partial()
        with partial.open("r+b") as file:
            file.write(b"corrupt")
        with self.assertRaisesRegex(ValueError, "Checksum"):
            self.get()
        self.assertFalse(self.destination.exists())
        self.assertFalse(partial.exists())
        self.get()

    def test_wrong_expected_hash(self):
        with self.assertRaisesRegex(ValueError, "Checksum"):
            download(self.url, self.destination, self.descriptor["bytes"], "0" * 64)
        self.assertFalse(self.destination.exists())

    def test_head_range_and_416(self):
        with urlopen(Request(self.url, method="HEAD")) as response:
            self.assertEqual(response.headers["Content-Length"], str(self.descriptor["bytes"]))
            self.assertEqual(response.read(), b"")
        with urlopen(Request(self.url, headers={"Range": "bytes=7-19"})) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), self.package.read_bytes()[7:20])
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.url, headers={"Range": "bytes=999999999-"}))
        self.assertEqual(error.exception.code, 416)
        self.assertEqual(error.exception.headers["Content-Range"], f"bytes */{self.descriptor['bytes']}")
        error.exception.close()

    def test_real_interruption_then_resume(self):
        original = self.server.RequestHandlerClass.do_GET
        data = self.package.read_bytes()
        etag = '"' + self.descriptor["sha256"] + '"'

        def interrupted(handler):
            handler.send_response(200)
            handler.send_header("Content-Length", str(len(data)))
            handler.send_header("ETag", etag)
            handler.end_headers()
            handler.wfile.write(data[:100000])
            handler.wfile.flush()
            handler.close_connection = True

        self.server.RequestHandlerClass.do_GET = interrupted
        with self.assertRaises((OSError, IncompleteRead)):
            self.get()
        self.assertFalse(self.destination.exists())
        self.server.RequestHandlerClass.do_GET = original
        self.get()
        self.assertIn("Range", self.requests[-1])
        self.assertEqual(digest(self.destination), self.descriptor["sha256"])

    def test_invalid_content_range_preserves_partial(self):
        partial = self.partial()

        def invalid(handler):
            handler.send_response(206)
            handler.send_header("Content-Length", str(self.descriptor["bytes"] - 80000))
            handler.send_header("ETag", '"' + self.descriptor["sha256"] + '"')
            handler.send_header("Content-Range", "bytes 1-2/3")
            handler.end_headers()
            handler.close_connection = True

        self.server.RequestHandlerClass.do_GET = invalid
        with self.assertRaisesRegex(ValueError, "Content-Range"):
            self.get()
        self.assertEqual(partial.stat().st_size, 80000)

    def test_existing_output_is_preserved(self):
        self.destination.write_bytes(b'keep')
        with self.assertRaises(ValueError):
            self.get()
        self.assertEqual(self.destination.read_bytes(), b'keep')

    def test_concurrent_writer_rejected(self):
        lock = self.destination.with_name("download.bin.download.lock")
        with os_lock(lock):
            with self.assertRaises(DownloadBusy):
                self.get()
        self.assertEqual(len(self.requests), 0)

    def test_leftover_lock_file_does_not_block(self):
        # A killed process leaves the empty file behind; only a live operating-system lock counts.
        lock = self.destination.with_name("download.bin.download.lock")
        lock.touch()
        self.get()
        self.assertTrue(lock.exists())
        self.assertEqual(digest(self.destination), self.descriptor["sha256"])

    def test_lock_is_released_after_failure(self):
        with self.assertRaises(ValueError):
            download(self.url, self.destination, self.descriptor["bytes"], "0" * 64)
        self.get()

    def test_control_directory_keeps_transfer_files_out_of_the_payload(self):
        payload = self.root / "payload"
        control = self.root / "control"
        target = payload / "dir" / "file.bin"
        self.partial_in(control, "fid", 80000)
        download(self.url, target, self.descriptor["bytes"], self.descriptor["sha256"],
                 control_dir=control, control_key="fid")
        self.assertEqual(self.requests[0]["Range"], "bytes=80000-")
        self.assertEqual(sorted(path.name for path in payload.rglob("*")), ["dir", "file.bin"])
        self.assertEqual(sorted(path.name for path in control.iterdir()), ["fid.lock"])

    def partial_in(self, control, key, size):
        control.mkdir(parents=True, exist_ok=True)
        (control / (key + ".part")).write_bytes(self.package.read_bytes()[:size])
        (control / (key + ".json")).write_text(json.dumps({"etag": '"' + self.descriptor["sha256"] + '"'}))

    def test_fresh_download_is_hashed_once_while_writing(self):
        with mock.patch("artifact_transfer.digest", wraps=digest) as counted:
            self.get()
        self.assertEqual(counted.call_count, 0)
        self.assertEqual(digest(self.destination), self.descriptor["sha256"])

    def test_resumed_download_is_verified_once_after_completion(self):
        self.partial()
        with mock.patch("artifact_transfer.digest", wraps=digest) as counted:
            self.get()
        self.assertEqual(counted.call_count, 1)

    def test_server_ignoring_range_is_truncated_not_appended(self):
        partial = self.partial()
        data = self.package.read_bytes()
        seen = []

        def ignore_range(handler):
            seen.append(handler.headers.get("Range"))
            handler.send_response(200)
            handler.send_header("Content-Length", str(len(data)))
            handler.send_header("ETag", '"' + self.descriptor["sha256"] + '"')
            handler.end_headers()
            handler.wfile.write(data)

        self.server.RequestHandlerClass.do_GET = ignore_range
        self.get()
        self.assertEqual(seen, ["bytes=80000-"])
        self.assertEqual(self.destination.read_bytes(), data)
        self.assertFalse(partial.exists())

    def test_invalid_checkpoint_restarts(self):
        partial = self.partial()
        partial.with_suffix(".json").write_text('{"etag":')
        self.get()
        self.assertNotIn("Range", self.requests[0])

    def test_http_failure_keeps_partial(self):
        partial = self.partial()

        def unavailable(handler):
            handler.send_error(503)

        self.server.RequestHandlerClass.do_GET = unavailable
        with self.assertRaises(HTTPError) as error:
            self.get()
        self.assertEqual(error.exception.code, 503)
        error.exception.close()
        self.assertEqual(partial.stat().st_size, 80000)
        self.assertFalse(self.destination.exists())

    def test_weak_checkpoint_validator_is_not_sent(self):
        self.partial(etag='W/"old"')
        self.get()
        self.assertNotIn("Range", self.requests[0])

    def test_restore_rejects_unsafe_relative_paths(self):
        self.assertEqual(validate_relative_path("场景A/models/a.bundle"), "场景A/models/a.bundle")
        with self.assertRaises(ValueError):
            validate_relative_path("../escape.bin")
        with self.assertRaises(ValueError):
            restore_tree({"files": [{"relativePath": "a/../b.bin", "downloadPath": self.url,
                                     "bytes": 1, "sha256": "0" * 64}]}, self.root / "out")
        with self.assertRaises(ValueError):
            restore_tree({"files": [
                {"relativePath": "root/A", "downloadPath": self.url, "bytes": 1, "sha256": "0" * 64},
                {"relativePath": "root/a/b.bin", "downloadPath": self.url, "bytes": 1, "sha256": "0" * 64},
            ]}, self.root / "case-prefix")


if __name__ == "__main__":
    unittest.main()
