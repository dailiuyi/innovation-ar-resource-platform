"""Reference client: download ONE variant of the current published version of a scene, resumably.

Reference tooling for integration, not an Android/iOS SDK. Anonymous (no Authorization header).

Layout, all under <output>/<sceneId>/<versionId>/<variantId>/ :
  .download-state.json  identity, fixed file list and the set of files verified complete
  .transfer/            part files, validators and locks (never inside payload/)
  payload/              declared files at their relative paths (the root the descriptor's paths refer to)
  ready.json            written last, atomically, only when every needed file is verified

Rerun the same command after any interruption. A 409 means the published version changed: the tool stops,
keeps the old directory untouched, and a new run fetches the new description into its own version directory.
Exit codes: 0 done, 1 error/interrupted, 2 variant not found, 3 version changed (409).
"""
import argparse
from datetime import datetime, timezone
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import shutil
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid

from artifact_transfer import DownloadBusy, download, os_lock, validate_relative_paths

STATE = ".download-state.json"
READY = "ready.json"
VARIANT_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


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
        raise SceneError(f"{url}: {http_error_text(error)}") from error


def plan_files(detail, variant_id):
    """The selected variant's segments plus the declared common files, each exactly once, in a stable order."""
    descriptor = detail["descriptor"]
    variant = next((v for v in descriptor["variants"] if v["id"] == variant_id), None)
    if variant is None:
        available = ", ".join(v["id"] for v in descriptor["variants"])
        raise SceneError(f"variant {variant_id!r} does not exist in this scene; available: {available}", 2)
    wanted = [segment["path"] for segment in variant["segments"]]
    wanted += [descriptor[key] for key in ("settings", "poster", "audio", "preview") if descriptor.get(key)]
    known = {item["relativePath"]: item for item in detail["files"]}
    manifest, seen = [], set()
    for path in wanted:
        if path in seen:
            continue
        seen.add(path)
        item = known.get(path)
        if item is None:
            raise SceneError(f"the description references {path!r} but the file list does not contain it")
        manifest.append({"fileId": item["fileId"], "relativePath": path, "bytes": item["bytes"],
                         "sha256": item["sha256"], "downloadPath": item["downloadPath"]})
    validate_relative_paths([item["relativePath"] for item in manifest])
    for item in manifest:
        if not item["downloadPath"].startswith("/"):
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


def open_task(version_dir, variant_id, identity, manifest):
    """Create the task directory with its state in place before any payload or part file exists."""
    directory = version_dir / variant_id
    if directory.exists():
        completed = load_state(directory, identity, manifest)
        if completed is not None:
            return directory, completed
        if any(directory.iterdir()):
            raise SceneError(f"{directory} is not empty and has no download state of this task")
        directory.rmdir()
    staging = version_dir / (variant_id + ".tmp")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    (staging / "payload").mkdir()
    (staging / ".transfer").mkdir()
    write_json_atomic(staging / STATE, {"formatVersion": 1, **identity, "files": manifest, "completed": []})
    os.rename(staging, directory)
    return directory, set()


def complete_on_disk(payload, item):
    target = payload.joinpath(*item["relativePath"].split("/"))
    return target.is_file() and target.stat().st_size == item["bytes"]


def run(base_url, scene_id, variant_id, output, timeout=30, log=print):
    base = base_url.rstrip("/")
    detail = fetch_json(f"{base}/api/v1/client/scenes/{scene_id}", timeout)
    version_id = str(uuid.UUID(detail["versionId"]))
    manifest = plan_files(detail, variant_id)
    identity = {"sceneId": scene_id, "versionId": version_id, "variantId": variant_id}
    version_dir = Path(output).absolute() / scene_id / version_id
    version_dir.mkdir(parents=True, exist_ok=True)
    try:
        with os_lock(version_dir / (variant_id + ".lock")):
            directory, completed = open_task(version_dir, variant_id, identity, manifest)
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
                write_json_atomic(directory / STATE, {"formatVersion": 1, **identity, "files": manifest,
                                                      "completed": sorted(completed)})
                log(f"complete {item['relativePath']} ({item['bytes']} bytes)")
            if not all(complete_on_disk(payload, item) for item in manifest):
                raise SceneError("a completed file disappeared while downloading; rerun to repair")
            write_json_atomic(directory / READY, {
                "formatVersion": 1, **identity, "payload": "payload",
                "files": [{key: item[key] for key in ("relativePath", "bytes", "sha256")} for item in manifest],
                "totalBytes": sum(item["bytes"] for item in manifest),
                "completedAt": datetime.now(timezone.utc).isoformat()})
            log(f"ready: {payload}")
            return payload
    except DownloadBusy as error:
        raise SceneError(f"another download of this variant is running ({error})") from error
    except HTTPError as error:
        if error.code == 409:
            raise SceneError(f"the published version changed ({http_error_text(error)}); nothing was mixed. "
                             "Rerun to fetch the new description into its own directory", 3) from error
        raise SceneError(http_error_text(error)) from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args(argv)
    try:
        scene_id = str(uuid.UUID(args.scene_id))
        if not VARIANT_ID.fullmatch(args.variant):
            raise SceneError("--variant is not a valid variant id", 2)
        run(args.base_url, scene_id, args.variant, args.output, args.timeout)
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
