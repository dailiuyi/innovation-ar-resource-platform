"""Import a resource package into a scene through the administrator API: create one immutable version, upload files.

Uses the same file manifest, create-version and per-file upload endpoints as the admin UI; there is no hidden import
path. The package root is the version root: every regular file under it (recursively) is registered at its relative
POSIX path. It is read in place (streamed from disk, never copied) and never written to.

Resume: the request key and version id are saved in --state-file (outside the package root) as soon as they exist.
Rerunning the same command, or passing --version-id, re-hashes the input files, checks that the manifest equals the
stored one, skips AVAILABLE files, leaves UPLOADING files alone (still being processed) and re-sends FAILED/PENDING ones.
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
    """JSON and streamed-body client for the administrator API base (gateway /prod-api)."""

    def __init__(self, base_url, timeout=900):
        parsed = urllib.parse.urlsplit(base_url.rstrip('/'))
        if parsed.scheme != 'http' or not parsed.hostname:
            raise ImportError_('--base-url must be an http URL such as http://127.0.0.1:18082')
        self.host, self.port, self.prefix, self.timeout = parsed.hostname, parsed.port or 80, parsed.path + '/prod-api', timeout
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
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_state(path, state):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def import_package(api, scene_id, package_root, state_path, version_id=None, log=print):
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
    saved = states.get(scene_id, {})
    request_key = saved.get('requestKey') or str(uuid.uuid4())
    description = 'import ' + Path(package_root).name
    created = None
    create_seconds = 0.0
    if version_id is None:
        states[scene_id] = {'requestKey': request_key, **({'versionId': saved['versionId']} if 'versionId' in saved else {})}
        save_state(state_path, states)
        begin = time.monotonic()
        status, version = api.request('POST', f'/api/v1/scenes/{scene_id}/versions',
                                      {'requestKey': request_key, 'description': description, 'files': manifest})
        create_seconds = time.monotonic() - begin
        if status not in (200, 201):
            raise ImportError_(f'create version failed: HTTP {status} {version.get("message", "")}')
        created = status == 201
        version_id = version['id']
        states[scene_id] = {'requestKey': request_key, 'versionId': version_id}
        save_state(state_path, states)
        log(f'version {version_id} {"created" if created else "already existed (same request key and manifest)"} in {create_seconds * 1000:.0f} ms')
    status, version = api.request('GET', f'/api/v1/scene-versions/{version_id}')
    if status != 200:
        raise ImportError_(f'version {version_id} not readable: HTTP {status}')
    if str(version.get('sceneId')) != str(scene_id):
        raise ImportError_(f'version {version_id} belongs to scene {version.get("sceneId")}, not {scene_id}')
    stored = {f['relativePath']: f for f in version['files']}
    if sorted(stored) != paths or any(stored[m['relativePath']]['bytes'] != m['bytes'] or stored[m['relativePath']]['sha256'] != m['sha256'] for m in manifest):
        raise ImportError_('input files no longer match the stored manifest (re-hashed from disk); not uploading')

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
        content = f'/api/v1/scene-versions/{version_id}/files/{entry["fileId"]}/content'
        begin_utc = time.time()
        begin = time.monotonic()
        try:
            with open(package_root / item['relativePath'], 'rb') as stream:
                code, body = api.request('PUT', content, stream=stream, length=item['bytes'])
        except (OSError, http.client.HTTPException) as error:
            # Unconfirmed: ask the server what it recorded before judging.
            code, body = 0, {'message': type(error).__name__ + ': ' + str(error)}
            check_code, check = api.request('GET', f'/api/v1/scene-versions/{version_id}/files/{entry["fileId"]}')
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
    return {'versionId': version_id, 'created': created, 'files': len(manifest), 'bytes': sum(m['bytes'] for m in manifest),
            'prehashSeconds': prehash_seconds, 'prehashPerFile': prehash, 'createSeconds': create_seconds,
            'uploads': uploads, 'skippedAvailable': skipped, 'processing': processing, 'failed': failed,
            'totalSeconds': time.monotonic() - started, 'complete': not processing and not failed,
            'manifest': manifest, 'fileIds': {m['relativePath']: stored[m['relativePath']]['fileId'] for m in manifest}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base-url', required=True, help='Gateway URL, e.g. http://127.0.0.1:18082 (the /prod-api prefix is added)')
    parser.add_argument('--scene-id', required=True)
    parser.add_argument('--package-root', type=Path, required=True, help='Version root: every file under it is imported')
    parser.add_argument('--state-file', type=Path, required=True, help='Resume state JSON (must be outside the package root)')
    parser.add_argument('--credentials-file', type=Path, required=True, help='Private JSON with username and password')
    parser.add_argument('--version-id', help='Continue this existing version instead of creating one')
    parser.add_argument('--report', type=Path, help='Write the result (timings, no secrets) to this JSON file')
    args = parser.parse_args(argv)
    try:
        uuid.UUID(args.scene_id)
        if args.version_id:
            uuid.UUID(args.version_id)
        api = Api(args.base_url)
        api.login(args.credentials_file)
        result = import_package(api, args.scene_id, args.package_root, args.state_file, args.version_id)
    except (ImportError_, ValueError, OSError, KeyError, http.client.HTTPException) as error:
        print('ERROR: ' + type(error).__name__ + ': ' + str(error), file=sys.stderr)
        return 2 if isinstance(error, (ValueError, KeyError)) else 1
    if args.report:
        args.report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(f'VERSION_ID={result["versionId"]}')
    if not result['complete']:
        print(f'INCOMPLETE: failed={result["failed"]} processing={result["processing"]}; rerun the same command to continue '
              f'(or add --version-id {result["versionId"]})', file=sys.stderr)
        return 1
    print(f'OK {result["files"]} files, {result["bytes"]} bytes AVAILABLE ({len(result["skippedAvailable"])} already there)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
