"""Reference client: download every file of one scene's fixed file list, resumably.

Reference tooling for integration, not an Android/iOS SDK. Anonymous (no Authorization header).
One scene has one fixed file manifest; a new scene id is a new download task.

Layout, all under <output>/<sceneId>/ :
  .download-state.json  identity, fixed file list and the set of files verified complete
  .transfer/            part files, validators and locks (never inside payload/)
  payload/              every file of the scene at its relative path
  ready.json            written last, atomically, only when every file is verified

Rerun the same command after any interruption. A 404 means the scene is disabled, deleted, incomplete or empty;
a 409 means the stored file is unavailable or its bytes/length do not match the manifest (retry later). The tool stops
and never mixes bytes from a different manifest into an existing task.
Exit codes: 0 done, 1 error/interrupted or unavailable, 2 invalid arguments.
"""
import argparse
from datetime import datetime, timezone
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid

from artifact_transfer import DownloadBusy, download, os_lock, validate_relative_paths

STATE = ".download-state.json"
READY = "ready.json"
FORMAT_VERSION = 2


class SceneError(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


def http_error_text(error):
    try:
        body = json.loads(error.read().decode("utf-8"))
        return f"HTTP {error.code}: {body.get('message', '')}"
    except (ValueError, AttributeError, OSError):
        return f"HTTP {error.code}"


def fetch_json(url, timeout):
    request = Request(url, headers={"Accept": "application/json", "Accept-Encoding": "identity"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code == 404:
            raise SceneError(f"{url}: HTTP 404: the scene is disabled, deleted, incomplete, or has no files") from error
        raise SceneError(f"{url}: {http_error_text(error)}") from error


def plan_files(detail):
    """Every file of the scene, each exactly once, in a stable order."""
    items = detail.get("files")
    if not isinstance(items, list) or not items:
        raise SceneError("the scene has no downloadable files")
    manifest = sorted(({"fileId": item["fileId"], "relativePath": item["relativePath"], "bytes": item["bytes"],
                        "sha256": item["sha256"], "downloadPath": item["downloadPath"]} for item in items),
                      key=lambda item: item["relativePath"])
    validate_relative_paths([item["relativePath"] for item in manifest])
    if len({item["relativePath"] for item in manifest}) != len(manifest) or len({item["fileId"] for item in manifest}) != len(manifest):
        raise SceneError("the scene file manifest contains duplicate paths or file ids")
    for item in manifest:
        if not isinstance(item["bytes"], int) or item["bytes"] < 1:
            raise SceneError(f"unexpected size for {item['relativePath']!r}")
        if not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise SceneError(f"unexpected SHA256 for {item['relativePath']!r}")
        if not isinstance(item["downloadPath"], str) or not item["downloadPath"].startswith("/"):
            raise SceneError(f"unexpected download path for {item['relativePath']!r}")
    return manifest


def write_json_atomic(path, value):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=1)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def load_state(directory, identity, manifest):
    """The recorded state if it belongs to exactly this task; None if missing; error if it belongs to another."""
    path = directory / STATE
    if not path.is_file():
        return None
    try:
        state = json.loads(path.read_text("utf-8"))
        same = all(state.get(key) == value for key, value in identity.items()) and state.get("files") == manifest
        completed = set(state["completed"]) if same else None
    except (ValueError, AttributeError, KeyError, TypeError):
        same, completed = False, None
    if not same:
        raise SceneError(f"{directory} holds a different or unreadable download state; refusing to reuse it")
    return completed


def open_task(scene_dir, identity, manifest):
    """Create the task directory with its state in place before any payload or part file exists."""
    if scene_dir.exists():
        completed = load_state(scene_dir, identity, manifest)
        if completed is not None:
            return scene_dir, completed
        if any(scene_dir.iterdir()):
            raise SceneError(f"{scene_dir} is not empty and has no download state of this task")
        scene_dir.rmdir()
    staging = scene_dir.with_name(scene_dir.name + ".tmp")
    if staging.exists():
        completed = load_state(staging, identity, manifest)
        if completed is not None:
            os.rename(staging, scene_dir)
            return scene_dir, completed
        if any(staging.iterdir()):
            raise SceneError(f"{staging} is not empty and has no download state of this task")
        staging.rmdir()
    staging.mkdir()
    (staging / "payload").mkdir()
    (staging / ".transfer").mkdir()
    write_json_atomic(staging / STATE, {"formatVersion": FORMAT_VERSION, **identity, "files": manifest, "completed": []})
    os.rename(staging, scene_dir)
    return scene_dir, set()


def complete_on_disk(payload, item):
    target = payload.joinpath(*item["relativePath"].split("/"))
    return target.is_file() and target.stat().st_size == item["bytes"]


def run(base_url, scene_id, output, timeout=30, log=print):
    base = base_url.rstrip("/")
    detail = fetch_json(f"{base}/api/v1/client/scenes/{scene_id}", timeout)
    actual = str(detail.get("sceneId"))
    if actual != scene_id:
        raise SceneError(f"the server returned scene {actual}, not {scene_id}; refusing to mix scenes")
    manifest = plan_files(detail)
    identity = {"sceneId": scene_id}
    scene_dir = Path(output).absolute() / scene_id
    try:
        with os_lock(scene_dir.with_name(scene_dir.name + ".lock")):
            directory, completed = open_task(scene_dir, identity, manifest)
            payload, control = directory / "payload", directory / ".transfer"
            if (directory / READY).exists():
                if all(item["fileId"] in completed and complete_on_disk(payload, item) for item in manifest):
                    log(f"already ready: {payload}")
                    return payload
                (directory / READY).unlink()
            for item in manifest:
                target = payload.joinpath(*item["relativePath"].split("/"))
                if item["fileId"] in completed:
                    if complete_on_disk(payload, item):
                        log(f"kept     {item['relativePath']}")
                        continue
                    completed.discard(item["fileId"])
                    target.unlink(missing_ok=True)
                download(base + item["downloadPath"], target, item["bytes"], item["sha256"], timeout=timeout,
                         control_dir=control, control_key=item["fileId"])
                completed.add(item["fileId"])
                write_json_atomic(directory / STATE, {"formatVersion": FORMAT_VERSION, **identity, "files": manifest,
                                                      "completed": sorted(completed)})
                log(f"complete {item['relativePath']} ({item['bytes']} bytes)")
            if not all(complete_on_disk(payload, item) for item in manifest):
                raise SceneError("a completed file disappeared while downloading; rerun to repair")
            write_json_atomic(directory / READY, {
                "formatVersion": FORMAT_VERSION, **identity, "payload": "payload",
                "files": [{key: item[key] for key in ("relativePath", "bytes", "sha256")} for item in manifest],
                "totalBytes": sum(item["bytes"] for item in manifest),
                "completedAt": datetime.now(timezone.utc).isoformat()})
            log(f"ready: {payload}")
            return payload
    except DownloadBusy as error:
        raise SceneError(f"another download of this scene is running ({error})") from error
    except HTTPError as error:
        if error.code == 409:
            raise SceneError(f"the scene file is unavailable from storage or no longer matches the manifest "
                             f"({http_error_text(error)}); retry later", 1) from error
        if error.code == 404:
            raise SceneError(f"the scene file is no longer available ({http_error_text(error)})", 1) from error
        raise SceneError(http_error_text(error)) from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args(argv)
    try:
        scene_id = str(uuid.UUID(args.scene_id))
        run(args.base_url, scene_id, args.output, args.timeout)
    except SceneError as error:
        print(f"error: {error}", file=sys.stderr)
        return error.code
    except (OSError, HTTPException) as error:
        print(f"error: {type(error).__name__}: {error}. Rerun the same command to resume.", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
