"""Import a resource package as one scene through the administrator API: create the scene and its fixed file list, then upload files.

Uses the same scene-create and per-file upload endpoints as the admin UI; there is no hidden import path. The package
root is the scene root: every regular file under it (recursively) is registered at its relative POSIX path. It is read
in place (streamed from disk, never copied) and never written to.

Create once, resume many times: a scene's file manifest is fixed at creation, so a new model is a new scene and a new
state file. The request key and name/description are saved in --state-file (outside the package root) before the
create request, and the returned scene id is saved immediately after it. Rerunning the same command after an
interruption (including a lost create response) reuses the key: HTTP 200 returns the existing scene, HTTP 409 means
the key was used for different metadata or files, HTTP 410 means the scene was deleted and is never recreated.
Continue an existing scene with --scene-id and the same package root; the input is re-hashed and must equal the stored
manifest. AVAILABLE files are skipped, UPLOADING files are left alone (still being processed), FAILED/PENDING ones are
re-sent. Uploading never enables a scene and there is no publish step.

The administrator password and token are read from the private credentials file / memory and are never printed.
Exit codes: 0 all files AVAILABLE, 1 error or files left incomplete, 2 invalid input.
"""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import sys
import time
import urllib.parse
import uuid

CHUNK = 1024 * 1024
STATE_FORMAT = 2


class ImportError_(Exception):
    pass


def package_paths(package_root):
    """Every regular file under the package root as a sorted relative POSIX path; symbolic links are refused."""
    paths = []
    for path in Path(package_root).rglob('*'):
        if path.is_symlink():
            raise ImportError_(f'{path} is a symbolic link; only regular files can be imported')
        if path.is_file():
            paths.append(path.relative_to(package_root).as_posix())
    if not paths:
        raise ImportError_(f'{package_root} contains no files')
    return sorted(paths)


def file_digest(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        while block := stream.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


class Api:
    """JSON and streamed-body client for the administrator API base (gateway .../prod-api or isolated backend root)."""

    def __init__(self, base_url, timeout=900):
        parsed = urllib.parse.urlsplit(base_url.rstrip('/'))
        if parsed.scheme != 'http' or not parsed.hostname or parsed.username or parsed.password:
            raise ImportError_('--base-url must be a plain http URL such as http://127.0.0.1:18080 or '
                               'http://127.0.0.1:18082/prod-api')
        if parsed.query or parsed.fragment:
            raise ImportError_('--base-url must not contain a query or fragment')
        self.host, self.port, self.prefix = parsed.hostname, parsed.port or 80, parsed.path.rstrip('/')
        self.timeout = timeout
        self.token = None

    def request(self, method, path, body=None, stream=None, length=None, timeout=None):
        headers = {'Accept': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        payload = None
        if stream is not None:
            headers['Content-Type'] = 'application/octet-stream'
            headers['Content-Length'] = str(length)
            payload = stream
        elif body is not None:
            headers['Content-Type'] = 'application/json'
            payload = json.dumps(body).encode()
        connection = http.client.HTTPConnection(self.host, self.port, timeout=timeout or self.timeout, blocksize=CHUNK)
        try:
            connection.request(method, self.prefix + path, body=payload, headers=headers)
            response = connection.getresponse()
            content = response.read()
        finally:
            connection.close()
        try:
            return response.status, json.loads(content) if content else {}
        except ValueError:
            return response.status, {}

    def login(self, credentials_file):
        credentials = json.loads(Path(credentials_file).read_text(encoding='utf-8'))
        status, body = self.request('POST', '/login', {'username': credentials['username'], 'password': credentials['password']})
        if status != 200 or not body.get('token'):
            raise ImportError_(f'administrator login failed (HTTP {status})')
        self.token = body['token']


def load_state(path):
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path, state):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def create_scene(api, state_path, states, name, description, manifest, log):
    """Create the scene with its fixed manifest, persisting the request key before the request and the id after it."""
    if name is None:
        raise ImportError_('--name is required to create a scene (or pass --scene-id to continue an existing one)')
    name = name.strip()
    if not name or len(name) > 200:
        raise ImportError_('--name must be nonblank and at most 200 characters')
    if len(description) > 2000:
        raise ImportError_('--description must be at most 2000 characters')
    request_key = states.get('requestKey') or str(uuid.uuid4())
    states.update({'formatVersion': STATE_FORMAT, 'requestKey': request_key, 'name': name, 'description': description})
    states.pop('sceneId', None)
    save_state(state_path, states)
    begin = time.monotonic()
    status, scene = api.request('POST', '/api/v1/scenes',
                                {'requestKey': request_key, 'name': name, 'description': description, 'files': manifest})
    seconds = time.monotonic() - begin
    if status == 409:
        raise ImportError_('the saved request key was already used for a different name, description or file manifest; '
                           'use a new --state-file for a new scene')
    if status == 410:
        raise ImportError_('the scene for the saved request key was deleted or is being deleted; it is not recreated; '
                           'use a new --state-file for a new scene')
    if status not in (200, 201) or not scene.get('id'):
        raise ImportError_(f'create scene failed: HTTP {status} {scene.get("message", "")}'.rstrip())
    scene_id = str(uuid.UUID(str(scene['id'])))
    states['sceneId'] = scene_id
    save_state(state_path, states)
    created = status == 201
    log(f'scene {scene_id} {"created" if created else "already existed (same request key and request)"} in {seconds * 1000:.0f} ms')
    return scene_id, created, seconds


def import_package(api, package_root, state_path, scene_id=None, name=None, description=None, log=print):
    """Returns a result dict with timings. Raises ImportError_ on a hard failure; incomplete files are reported."""
    package_root, state_path = Path(package_root), Path(state_path)
    if not package_root.is_dir():
        raise ImportError_(f'{package_root} is not a directory')
    if package_root.resolve() in state_path.absolute().resolve().parents:
        raise ImportError_('--state-file must not be inside --package-root')
    paths = package_paths(package_root)
    started = time.monotonic()
    manifest = []
    prehash = {}
    for relative in paths:
        source = package_root / relative
        begin = time.monotonic()
        manifest.append({'relativePath': relative, 'bytes': source.stat().st_size, 'sha256': file_digest(source)})
        prehash[relative] = time.monotonic() - begin
    prehash_seconds = time.monotonic() - started
    log(f'hashed {len(manifest)} files, {sum(m["bytes"] for m in manifest)} bytes in {prehash_seconds:.2f}s')

    states = load_state(state_path)
    saved_scene = states.get('sceneId')
    created, create_seconds = False, 0.0
    if scene_id is not None:
        scene_id = str(uuid.UUID(str(scene_id)))
        if saved_scene is not None and str(saved_scene) != scene_id:
            raise ImportError_(f'--state-file already belongs to scene {saved_scene}, not {scene_id}; use a new state file')
        if saved_scene is None and (name is not None or description is not None):
            raise ImportError_('--name and --description only apply when creating a scene; metadata is edited in the admin UI')
        name = states.get('name') if saved_scene is not None else None
        description = states.get('description') if saved_scene is not None else None
        states.update({'formatVersion': STATE_FORMAT, 'sceneId': scene_id})
        save_state(state_path, states)
    elif saved_scene is not None:
        scene_id = str(uuid.UUID(str(saved_scene)))
        log(f'continuing the scene recorded in the state file: {scene_id}')
        if name is not None and states.get('name') is not None and name != states['name']:
            raise ImportError_('--name differs from the scene recorded in the state file; metadata is edited in the admin UI')
        if description is not None and description != states.get('description', ''):
            raise ImportError_('--description differs from the scene recorded in the state file; metadata is edited in the admin UI')
        name, description = states.get('name'), states.get('description', '')
    else:
        name = states.get('name') if name is None else name
        description = states.get('description', '') if description is None else description
        scene_id, created, create_seconds = create_scene(api, state_path, states, name, description, manifest, log)

    status, scene = api.request('GET', f'/api/v1/scenes/{scene_id}')
    if status == 404:
        raise ImportError_(f'scene {scene_id} does not exist (deleted?)')
    if status != 200:
        raise ImportError_(f'scene {scene_id} not readable: HTTP {status}')
    if str(scene.get('id')) != scene_id:
        raise ImportError_(f'scene {scene_id} was returned as {scene.get("id")}; refusing to mix scenes')
    name = scene.get('name') if name is None else name
    description = scene.get('description', '') if description is None else description
    stored = {f['relativePath']: f for f in scene.get('files', [])}
    if sorted(stored) != paths or any(stored[m['relativePath']]['bytes'] != m['bytes'] or stored[m['relativePath']]['sha256'] != m['sha256'] for m in manifest):
        raise ImportError_('input files no longer match the scene fixed manifest (re-hashed from disk); not uploading')

    uploads, skipped, processing, failed = {}, [], [], []
    for item in manifest:
        entry = stored[item['relativePath']]
        if entry['status'] == 'AVAILABLE':
            skipped.append(item['relativePath'])
            continue
        if entry['status'] == 'UPLOADING':
            processing.append(item['relativePath'])
            log(f'{item["relativePath"]}: UPLOADING on the server (processing); not re-sent')
            continue
        content = f'/api/v1/scenes/{scene_id}/files/{entry["fileId"]}/content'
        begin_utc = time.time()
        begin = time.monotonic()
        try:
            with open(package_root / item['relativePath'], 'rb') as stream:
                code, body = api.request('PUT', content, stream=stream, length=item['bytes'])
        except (OSError, http.client.HTTPException) as error:
            # Unconfirmed: ask the server what it recorded before judging.
            code, body = 0, {'message': type(error).__name__ + ': ' + str(error)}
            check_code, check = api.request('GET', f'/api/v1/scenes/{scene_id}/files/{entry["fileId"]}')
            if check_code == 200 and check.get('status') == 'AVAILABLE':
                code, body = 200, check
        seconds = time.monotonic() - begin
        uploads[item['relativePath']] = {'bytes': item['bytes'], 'seconds': seconds, 'startUtc': begin_utc, 'endUtc': time.time(),
                                         'fileId': entry['fileId'], 'httpStatus': code}
        if code == 200 and body.get('status') == 'AVAILABLE':
            log(f'{item["relativePath"]}: uploaded {item["bytes"]} bytes in {seconds:.2f}s')
        else:
            failed.append(item['relativePath'])
            log(f'{item["relativePath"]}: upload failed HTTP {code} {body.get("message", "")}')
    return {'sceneId': scene_id, 'name': name, 'description': description, 'created': created,
            'files': len(manifest), 'bytes': sum(m['bytes'] for m in manifest),
            'prehashSeconds': prehash_seconds, 'prehashPerFile': prehash, 'createSeconds': create_seconds,
            'uploads': uploads, 'skippedAvailable': skipped, 'processing': processing, 'failed': failed,
            'totalSeconds': time.monotonic() - started, 'complete': not processing and not failed,
            'manifest': manifest, 'fileIds': {m['relativePath']: stored[m['relativePath']]['fileId'] for m in manifest}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base-url', required=True,
                        help='Administrator API base used verbatim: isolated backend root (e.g. http://127.0.0.1:18080) '
                             'or gateway administrator path (e.g. http://127.0.0.1:18082/prod-api)')
    parser.add_argument('--scene-id', help='Continue this existing scene instead of creating one')
    parser.add_argument('--package-root', type=Path, required=True, help='Scene root: every file under it is imported')
    parser.add_argument('--state-file', type=Path, required=True, help='Resume state JSON (must be outside the package root)')
    parser.add_argument('--credentials-file', type=Path, required=True, help='Private JSON with username and password')
    parser.add_argument('--name', help='Scene name for the initial create (required unless the state file already has one)')
    parser.add_argument('--description', help='Scene description for the initial create (default empty)')
    parser.add_argument('--report', type=Path, help='Write the result (timings, no secrets) to this JSON file')
    args = parser.parse_args(argv)
    try:
        if args.scene_id:
            uuid.UUID(args.scene_id)
        api = Api(args.base_url)
        api.login(args.credentials_file)
        result = import_package(api, args.package_root, args.state_file, args.scene_id, args.name, args.description)
    except (ImportError_, ValueError, OSError, KeyError, http.client.HTTPException) as error:
        print('ERROR: ' + type(error).__name__ + ': ' + str(error), file=sys.stderr)
        return 2 if isinstance(error, (ValueError, KeyError)) else 1
    if args.report:
        args.report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(f'SCENE_ID={result["sceneId"]}')
    if not result['complete']:
        print(f'INCOMPLETE: failed={result["failed"]} processing={result["processing"]}; rerun the same command to continue',
              file=sys.stderr)
        return 1
    print(f'OK {result["files"]} files, {result["bytes"]} bytes AVAILABLE ({len(result["skippedAvailable"])} already there)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
