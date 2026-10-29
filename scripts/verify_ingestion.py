"""Ingestion acceptance for 4DGS scene product versions: import, per-file upload and recovery, publish, whole-version delete.

Two ways to run:
* External isolated instance (any OS): --base-url, --admin-base-url and --credentials-file drive HTTP (and an optional
  browser) checks through `run_http_checks`; nothing is started or installed.
* Windows runtime (review.py, harness): a new private PostgreSQL 17 / Redis / Spring Boot / Vite directory, with
  database and private-storage fault injection on top of the same HTTP checks. Never uses the running Demo database.

Synthetic model bytes are not renderable 4DGS content; this verifies the management and transfer contract only.
"""
import argparse
import copy
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / '.local/python'))
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
MIB = 1024 * 1024


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def synthetic_package(label, standard_segments=2):
    """A small valid version: a settings file plus model files in nested directories.

    Returns {relativePath: bytes}. The model files are synthetic text and are not renderable."""
    files = {'settings.json': json.dumps({'synthetic': label}).encode() + b'\n'}
    for index in range(standard_segments):
        files[f'models/standard/{index:02d}.c.ply'] = f'synthetic standard segment {index} {label}\n'.encode() * (index + 3)
    files['models/high/00.c.ply'] = f'synthetic high segment {label}\n'.encode() * 7
    return files


def version_request(files, description='', request_key=None):
    return {'requestKey': request_key or str(uuid.uuid4()), 'description': description,
            'files': [{'relativePath': path, 'bytes': len(data), 'sha256': sha256(data)} for path, data in sorted(files.items())]}


class Session:
    """Minimal JSON/bytes HTTP client against the administrator API base (gateway /prod-api or backend root)."""

    def __init__(self, admin_base_url):
        self.base = admin_base_url.rstrip('/')
        self.token = None

    def raw(self, path, method='GET', body=None, auth=True, headers=None, timeout=60):
        hdrs = dict(headers or {})
        if auth and self.token:
            hdrs['Authorization'] = 'Bearer ' + self.token
        if body is not None:
            hdrs.setdefault('Content-Type', 'application/octet-stream' if isinstance(body, bytes) else 'application/json')
            body = body if isinstance(body, bytes) else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=body, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def api(self, path, method='GET', body=None, auth=True, headers=None, timeout=60):
        status, _, content = self.raw(path, method, body, auth, headers, timeout)
        try:
            return status, json.loads(content) if content else {}
        except ValueError:
            return status, {}

    def login(self, username, password):
        status, body = self.api('/login', 'POST', {'username': username, 'password': password}, auth=False)
        self.token = body.get('token') if status == 200 else None
        return self.token


def former_lock_bucket(file_id):
    """Segment of the removed 256-way striped lock; only used to pick files that collided under it."""
    value = uuid.UUID(file_id).int
    hilo = (value >> 64) ^ (value & (2 ** 64 - 1))
    return (hilo ^ (hilo >> 32)) & 0xff


def held_upload(s, path, data, sent):
    """Open a PUT whose body is withheld after `sent` bytes so the server keeps the upload in flight."""
    parsed = urllib.parse.urlsplit(s.base + path)
    assert parsed.scheme == 'http', 'the in-flight upload check needs an http base URL'
    sock = socket.create_connection((parsed.hostname, parsed.port or 80), timeout=30)
    try:
        head = (f'PUT {parsed.path} HTTP/1.1\r\nHost: {parsed.netloc}\r\nAuthorization: Bearer {s.token}\r\n'
                f'Content-Length: {len(data)}\r\nContent-Type: application/octet-stream\r\nConnection: close\r\n\r\n')
        sock.sendall(head.encode() + data[:sent])
    except BaseException:
        sock.close()
        raise
    return sock


def finish_held(sock, rest):
    sock.sendall(rest)
    response = http.client.HTTPResponse(sock)
    response.begin()
    response.read()
    return response.status


def upload_lock_checks(s, check):
    """Different files must upload concurrently even when they shared a bucket of the former striped lock."""
    count = 257
    files = {f'models/standard/{i:03d}.c.ply': f'lock isolation {i}\n'.encode() * 16 for i in range(count)}
    config = s.api('/api/v1/scene-versions/config')[1]
    check('upload limits fit the lock isolation fixture', config.get('versionMaxFiles', 0) >= count
          and config.get('versionMaxBytes', 0) >= sum(map(len, files.values())) and config.get('maxBytes', 0) >= max(map(len, files.values())))
    scene = s.api('/api/v1/scenes', 'POST', {'name': 'upload-lock-isolation'})[1]
    status, version = s.api(f'/api/v1/scenes/{scene["id"]}/versions', 'POST', version_request(files))
    check('lock isolation version created', status == 201)
    ids = {f['relativePath']: f['fileId'] for f in version['files']}
    groups = {}
    for path, file_id in sorted(ids.items()):
        groups.setdefault(former_lock_bucket(file_id), []).append(path)
    held, other = next(group for group in groups.values() if len(group) >= 2)[:2]
    base = '/api/v1/scene-versions/' + version['id']
    def file_path(path): return f'{base}/files/{ids[path]}'
    def put(path): return s.api(file_path(path) + '/content', 'PUT', files[path])
    data = files[held]
    sock = held_upload(s, file_path(held) + '/content', data, len(data) - 1)
    try:
        deadline = time.time() + 10
        state = None
        while time.time() < deadline:
            state = s.api(file_path(held))[1].get('status')
            if state == 'UPLOADING':
                break
            time.sleep(0.05)
        check('held upload is marked UPLOADING', state == 'UPLOADING')
        status, body = put(other)
        check('a different file uploads while another file is in flight', status == 200 and body.get('status') == 'AVAILABLE')
        check('the same file while in flight returns 409', put(held)[0] == 409)
        check('held upload completes as AVAILABLE', finish_held(sock, data[-1:]) == 200
              and s.api(file_path(held))[1].get('status') == 'AVAILABLE')
    finally:
        sock.close()
    attempts = s.api(file_path(held))[1]['attempts']
    status, body = put(held)
    check('finished upload leaves no in-flight marker', status == 200 and body.get('status') == 'AVAILABLE' and body['attempts'] == attempts)
    return {'versionId': version['id']}


def scenario(s, check):
    """Product-version scenario over HTTP only. Returns identifiers the caller may inspect or reuse."""
    anonymous = s.api
    config_status, config = s.api('/api/v1/scene-versions/config')
    check('administrator can read upload limits', config_status == 200 and all(
        isinstance(config.get(k), int) and config[k] > 0 for k in ('maxBytes', 'versionMaxFiles', 'versionMaxBytes')))
    check('anonymous version config rejected', anonymous('/api/v1/scene-versions/config', auth=False)[0] == 401)
    check('anonymous publish rejected', anonymous('/api/v1/scene-versions/' + str(uuid.uuid4()) + '/publish', 'POST',
                                                  {'expectedSceneVersion': 0}, auth=False)[0] == 401)
    check('anonymous file content rejected', s.raw('/api/v1/scene-versions/%s/files/%s/content' % (uuid.uuid4(), uuid.uuid4()),
                                                   auth=False)[0] == 401)

    scene = s.api('/api/v1/scenes', 'POST', {'name': 'ingestion-acceptance'})[1]
    scene_id = scene['id']
    versions_path = f'/api/v1/scenes/{scene_id}/versions'
    scene_lock = lambda: s.api('/api/v1/scenes/' + scene_id)[1]['lockVersion']
    files1 = synthetic_package('v1')
    status, missing = s.api(f'/api/v1/scenes/{uuid.uuid4()}/versions', 'POST', version_request(files1))
    check('version on missing scene rejected with the shared error format',
          status == 404 and missing.get('code') == 'AR_404' and bool(missing.get('traceId')))
    gone = s.api('/api/v1/scenes', 'POST', {'name': 'deleted-scene'})[1]
    check('deleted scene delete', s.api('/api/v1/scenes/%s?expectedVersion=0' % gone['id'], 'DELETE')[0] == 204)
    check('version on deleted scene rejected', s.api('/api/v1/scenes/%s/versions' % gone['id'], 'POST',
                                                     version_request(files1))[0] == 404)

    def rejected(label, expected_status, mutate):
        files = copy.deepcopy(files1)
        body_override = mutate(files)
        body = version_request(files)
        body.update(body_override or {})
        status, error = s.api(versions_path, 'POST', body)
        check(f'{label} returns {expected_status}', status == expected_status and bool(error.get('message')))

    def traversal(files):
        files['../escape.bin'] = files.pop('models/high/00.c.ply')
    def absolute(files):
        files['/etc/escape.bin'] = files.pop('models/high/00.c.ply')
    def duplicate_file(files):
        entry = version_request(files)['files'][0]
        return {'files': version_request(files)['files'] + [entry]}
    def case_duplicate(files):
        files['Settings.json'] = files['settings.json']
    def no_files(files):
        return {'files': []}
    for label, mutate in [('path traversal', traversal), ('absolute path', absolute),
                          ('same path registered twice', duplicate_file), ('case-insensitive duplicate path', case_duplicate),
                          ('empty file list', no_files)]:
        rejected(label, 400, mutate)

    def oversize(files):
        body = version_request(files)
        body['files'][0]['bytes'] = config['maxBytes'] + 1
        return {'files': body['files']}
    rejected('file larger than the single-file limit', 413, oversize)

    def too_many(files):
        count = config['versionMaxFiles']
        listed = [{'relativePath': f'm/{i}.c.ply', 'bytes': 1, 'sha256': sha256(b'x')} for i in range(count)]
        listed.append({'relativePath': 'settings.json', 'bytes': 1, 'sha256': sha256(b'x')})
        return {'files': listed}
    if config['versionMaxFiles'] <= 5000:
        rejected('more files than the per-version limit', 413, too_many)
    check('rejected requests created no version', s.api(versions_path)[1]['total'] == 0)

    request1 = version_request(files1, 'first version')
    status, v1 = s.api(versions_path, 'POST', request1)
    check('create version returns 201 with detail', status == 201 and v1['sceneId'] == scene_id and v1['versionNo'] == 1)
    check('new version is PENDING with every file registered', v1['uploadStatus'] == 'PENDING' and v1['fileCount'] == len(files1)
          and v1['availableCount'] == 0 and all(f['status'] == 'PENDING' and f['attempts'] == 0 for f in v1['files']))
    check('stored file set equals the request and the detail has no descriptor',
          sorted(f['relativePath'] for f in v1['files']) == sorted(files1) and 'descriptor' not in v1 and not v1['published'])
    v1_id, v1_path = v1['id'], '/api/v1/scene-versions/' + v1['id']
    status, retry = s.api(versions_path, 'POST', request1)
    check('identical request-key retry returns the original version', status == 200 and retry['id'] == v1_id
          and s.api(versions_path)[1]['total'] == 1)
    changed = copy.deepcopy(request1)
    changed['files'][0]['sha256'] = sha256(b'different')
    check('same request key with a different digest conflicts', s.api(versions_path, 'POST', changed)[0] == 409)
    check('same request key with a different description conflicts',
          s.api(versions_path, 'POST', {**request1, 'description': 'other'})[0] == 409)
    listed = s.api(versions_path)[1]
    check('version list carries the scene revision and no published pointer yet',
          isinstance(listed['sceneLockVersion'], int) and 'published' not in listed and listed['items'][0]['uploadStatus'] == 'PENDING')
    check('incomplete version cannot publish', s.api(v1_path + '/publish', 'POST', {'expectedSceneVersion': scene_lock()})[0] == 400)
    edited = s.api(v1_path, 'PUT', {'description': 'edited description', 'expectedVersion': v1['lockVersion']})
    check('description can be edited', edited[0] == 200 and edited[1]['description'] == 'edited description'
          and sorted(f['relativePath'] for f in edited[1]['files']) == sorted(files1))
    check('stale description edit conflicts', s.api(v1_path, 'PUT', {'description': 'stale', 'expectedVersion': v1['lockVersion']})[0] == 409)

    ids = {f['relativePath']: f['fileId'] for f in v1['files']}
    def content(version_path, file_id): return f'{version_path}/files/{file_id}/content'
    def upload(path, data): return s.api(content(v1_path, ids[path]), 'PUT', data)
    target = 'models/standard/00.c.ply'
    good = files1[target]
    bad = bytes(b ^ 1 for b in good)
    check('digest mismatch with the declared size returns 422', upload(target, bad)[0] == 422)
    file_status = s.api(f'{v1_path}/files/{ids[target]}')[1]
    check('digest mismatch is persisted as FAILED with a reason and one attempt',
          file_status['status'] == 'FAILED' and 'SHA256' in file_status['failureReason'] and file_status['attempts'] == 1)
    check('failed file makes the version FAILED', s.api(v1_path)[1]['uploadStatus'] == 'FAILED' and s.api(v1_path)[1]['failedCount'] == 1)
    check('actual size beyond the declaration returns 422', upload(target, good + b'x')[0] == 422)
    check('wrong version cannot reach the file', s.api(content('/api/v1/scene-versions/' + str(uuid.uuid4()), ids[target]), 'PUT', good)[0] == 404)
    check('anonymous upload rejected', s.api(content(v1_path, ids[target]), 'PUT', good, auth=False)[0] == 401)
    status, uploaded = upload(target, good)
    check('failed file is retried completely and becomes AVAILABLE', status == 200 and uploaded['status'] == 'AVAILABLE'
          and uploaded['attempts'] == 3 and uploaded['failureReason'] is None)
    first_attempts = {target: uploaded['attempts']}
    check('available file upload is idempotent and does not overwrite', upload(target, good)[1]['status'] == 'AVAILABLE')
    for path in sorted(files1):
        if path != target:
            first_attempts[path] = upload(path, files1[path])[1]['attempts']
            check('upload ' + path, s.api(f'{v1_path}/files/{ids[path]}')[1]['status'] == 'AVAILABLE')
    ready = s.api(v1_path)[1]
    check('all files AVAILABLE makes the version READY', ready['uploadStatus'] == 'READY' and ready['availableCount'] == len(files1)
          and all(f['status'] == 'AVAILABLE' for f in ready['files']))
    check('completed files are not attempted again', all(f['attempts'] == first_attempts[f['relativePath']] for f in ready['files']))

    sample_path = 'models/high/00.c.ply'
    sample = files1[sample_path]
    status, headers, body = s.raw(content(v1_path, ids[sample_path]))
    check('administrator downloads exact bytes with the SHA256 strong ETag', status == 200 and body == sample
          and headers.get('ETag') == '"' + sha256(sample) + '"')
    status, headers, body = s.raw(content(v1_path, ids[sample_path]), headers={'Range': 'bytes=0-3'})
    check('administrator Range 0-3 returns 206 with exact bytes', status == 206 and body == sample[:4]
          and headers.get('Content-Range') == f'bytes 0-3/{len(sample)}')
    status, headers, body = s.raw(content(v1_path, ids[sample_path]), headers={'Range': 'bytes=2-'})
    check('administrator open-ended Range returns the tail', status == 206 and body == sample[2:])
    check('administrator out-of-range request returns 416', s.raw(content(v1_path, ids[sample_path]),
                                                                   headers={'Range': 'bytes=99999999-'})[0] == 416)
    status, headers, body = s.raw(content(v1_path, ids[sample_path]), headers={'Range': 'bytes=0-3', 'If-Range': '"' + '0' * 64 + '"'})
    check('mismatched If-Range returns the full file', status == 200 and body == sample)
    status, headers, body = s.raw(content(v1_path, ids[sample_path]), 'HEAD')
    check('HEAD returns the length without a body', status == 200 and int(headers['Content-Length']) == len(sample) and body == b'')
    check('anonymous content download rejected', s.raw(content(v1_path, ids[sample_path]), auth=False)[0] == 401)

    before = scene_lock()
    check('stale scene revision cannot publish', s.api(v1_path + '/publish', 'POST', {'expectedSceneVersion': before + 1})[0] == 409
          and not s.api(v1_path)[1]['published'])
    status, published = s.api(v1_path + '/publish', 'POST', {'expectedSceneVersion': before})
    check('publish switches the single pointer', status == 200 and published['published'] is True and scene_lock() == before + 1)
    status, again = s.api(v1_path + '/publish', 'POST', {'expectedSceneVersion': before + 99})
    check('repeat publish is idempotent without a revision check or write', status == 200 and again['published'] is True
          and scene_lock() == before + 1)
    listed = s.api(versions_path)[1]
    check('exactly one published version', listed['published']['id'] == v1_id and sum(1 for x in listed['items'] if x['published']) == 1)
    check('published version cannot be deleted', s.api(v1_path, 'DELETE')[0] == 409)
    check('published description stays editable', s.api(v1_path, 'PUT', {'description': 'published note',
          'expectedVersion': s.api(v1_path)[1]['lockVersion']})[0] == 200)

    files2 = synthetic_package('v2')
    request2 = version_request(files2, 'second version')
    v2 = s.api(versions_path, 'POST', request2)[1]
    v2_path = '/api/v1/scene-versions/' + v2['id']
    check('second version gets the next number', v2['versionNo'] == 2)
    for entry in v2['files']:
        s.api(content(v2_path, entry['fileId']), 'PUT', files2[entry['relativePath']])
    check('second version READY', s.api(v2_path)[1]['uploadStatus'] == 'READY')
    check('replacement publish', s.api(v2_path + '/publish', 'POST', {'expectedSceneVersion': scene_lock()})[0] == 200
          and s.api(versions_path)[1]['published']['id'] == v2['id'] and not s.api(v1_path)[1]['published'])
    check('current version cannot be deleted', s.api(v2_path, 'DELETE')[0] == 409)
    check('previous version is still viewable', s.api(v1_path)[0] == 200 and s.raw(content(v1_path, ids[sample_path]))[2] == sample)
    check('previous version delete', s.api(v1_path, 'DELETE')[0] == 204)
    check('repeat delete is idempotent', s.api(v1_path, 'DELETE')[0] == 204)
    check('deleted version is gone', s.api(v1_path)[0] == 404 and s.raw(content(v1_path, ids[sample_path]))[0] == 404
          and s.api(versions_path)[1]['total'] == 1)
    check('late create retry after delete returns 410', s.api(versions_path, 'POST', request1)[0] == 410
          and s.api(versions_path)[1]['total'] == 1)
    check('unknown version id delete returns 404', s.api('/api/v1/scene-versions/' + str(uuid.uuid4()), 'DELETE')[0] == 404)

    audits = s.api('/api/v1/audits?limit=100')[1]['items']
    actions = [(a['action'], a['detail']) for a in audits if a['sceneId'] == scene_id]
    check('version lifecycle audits are written', {'VERSION_CREATE', 'VERSION_EDIT', 'VERSION_PUBLISH', 'VERSION_DELETE_REQUEST',
                                                   'VERSION_DELETE'} <= {name for name, _ in actions})
    check('repeat publish wrote no second audit', sum(1 for name, detail in actions
                                                      if name == 'VERSION_PUBLISH' and json.loads(detail).get('toVersionId') == v1_id) == 1)

    big = None
    if config['maxBytes'] >= 22 * MIB and config['versionMaxBytes'] >= 22 * MIB:
        # Larger than the gateway's default 20 MiB body limit and not above the configured per-file limit.
        scene_big = s.api('/api/v1/scenes', 'POST', {'name': 'large-upload'})[1]
        payload = os.urandom(21 * MIB)
        files_big = {'settings.json': b'{"large":true}\n', 'models/standard/00.c.ply': payload}
        big = s.api(f'/api/v1/scenes/{scene_big["id"]}/versions', 'POST', version_request(files_big, 'large file'))[1]
        big_path = '/api/v1/scene-versions/' + big['id']
        results = {e['relativePath']: s.api(content(big_path, e['fileId']), 'PUT', files_big[e['relativePath']], timeout=300)
                   for e in big['files']}
        check('21 MiB file uploads through the configured base URL', all(r[0] == 200 and r[1]['status'] == 'AVAILABLE' for r in results.values()))
        large_id = next(e['fileId'] for e in big['files'] if e['relativePath'].endswith('.ply'))
        status, headers, body = s.raw(content(big_path, large_id), headers={'Range': f'bytes={21 * MIB - 8}-'})
        check('large file tail Range returns exact bytes', status == 206 and body == payload[-8:])
        check('large version deletes physically', s.api(big_path, 'DELETE')[0] == 204 and s.api(big_path)[0] == 404)
    return {'sceneId': scene_id, 'config': config, 'versionIds': {'deleted': v1_id, 'current': v2['id']}, 'largeUploadChecked': big is not None}


def browser_scenario(s, web_base_url, executable, check, channel='msedge'):
    """Real browser: import a resource directory through the panel, publish, reload and check nothing is covered."""
    from playwright.sync_api import sync_playwright
    name = 'ui-' + uuid.uuid4().hex[:8]
    scene = s.api('/api/v1/scenes', 'POST', {'name': name})[1]
    files = synthetic_package('browser')
    with tempfile.TemporaryDirectory() as temporary, sync_playwright() as playwright:
        package = Path(temporary) / 'scene-package'
        for path, data in files.items():
            (package / path).parent.mkdir(parents=True, exist_ok=True)
            (package / path).write_bytes(data)
        launch = {'executable_path': str(executable)} if executable else {'channel': channel}
        browser = playwright.chromium.launch(headless=True, **launch)
        try:
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.add_cookies([{'name': 'Admin-Token', 'value': s.token, 'url': web_base_url}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(web_base_url + '/admin/scenes')
            row = page.get_by_role('row').filter(has_text=name)
            row.get_by_role('button', name='版本与文件', exact=True).click()
            page.get_by_role('heading', name='当前发布版本').wait_for()
            check('browser panel opens for the clicked scene', f'sceneId={scene["id"]}' in page.url
                  and page.get_by_text('该场景尚未发布').count() == 1)
            page.locator('input[type=file][webkitdirectory]').set_input_files(str(package))
            page.get_by_role('heading', name='待导入：%d 个文件' % len(files), exact=False).wait_for()
            page.get_by_role('button', name='开始导入', exact=True).click()
            drawer = page.locator('.el-drawer')
            drawer.get_by_role('row').filter(has_text='v1').get_by_text('已就绪', exact=True).first.wait_for(timeout=60000)
            listed = s.api(f'/api/v1/scenes/{scene["id"]}/versions')[1]
            check('browser import creates one READY version with every file of the directory', listed['total'] == 1
                  and listed['items'][0]['uploadStatus'] == 'READY'
                  and sorted(f['relativePath'] for f in s.api('/api/v1/scene-versions/' + listed['items'][0]['id'])[1]['files'])
                  == sorted(files))
            for width in (1440, 1024):
                page.set_viewport_size({'width': width, 'height': 1000})
                buttons = [b for b in drawer.get_by_role('button').all() if b.is_visible()]
                obscured = []
                for b in buttons:
                    b.scroll_into_view_if_needed()
                    # Fully inside the viewport and the topmost element at its centre is the button itself.
                    if not b.evaluate(
                            """el => { const r = el.getBoundingClientRect();
                               if (r.x < 0 || r.x + r.width > innerWidth) return false;
                               const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
                               return !!top && (top === el || el.contains(top)); }"""):
                        obscured.append(b.inner_text() or b.get_attribute('class'))
                check(f'browser panel buttons are not covered at {width}px', not obscured and len(buttons) > 0)
            version_row = drawer.get_by_role('row').filter(has_text='v1')
            version_row.get_by_role('button', name='发布', exact=True).click()
            page.get_by_role('button', name='确认发布', exact=True).click()
            page.get_by_text('该场景尚未发布').wait_for(state='hidden')
            check('browser publish pins the version', s.api(f'/api/v1/scenes/{scene["id"]}/versions')[1]['published']['versionNo'] == 1)
            page.reload()
            page.get_by_role('heading', name='当前发布版本').wait_for()
            check('browser reload keeps the scene and version in the address', 'sceneId=' in page.url and 'versionId=' in page.url)
            check('browser page reported no script errors', not errors)
        finally:
            browser.close()


def run_http_checks(base_url, admin_base_url, credentials_file, report_dir, browser_executable, runtime=None):
    """HTTP (and optional browser) ingestion checks against an already running isolated instance.

    Writes <report_dir>/validation-ingestion.json and returns it. Starts nothing and installs nothing. `runtime`
    is supplied only by the Windows launcher for database/storage fault injection."""
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    checks = []
    def check(name, condition):
        checks.append({'name': name, 'passed': bool(condition)})
        print(('PASS ' if condition else 'FAIL ') + name, flush=True)
        if not condition:
            raise AssertionError(name)
    credentials = json.loads(Path(credentials_file).read_text(encoding='utf-8'))
    s = Session(admin_base_url)
    report = {'passed': False, 'baseUrl': base_url, 'adminBaseUrl': admin_base_url, 'checks': checks,
              'limitations': ['Synthetic model bytes are not renderable 4DGS content', 'No client download or playback validation',
                              'No power-loss or disk-full injection']}
    try:
        check('administrator login', bool(s.login(credentials['username'], credentials['password'])))
        report['scenario'] = scenario(s, check)
        report['uploadLockIsolation'] = upload_lock_checks(s, check)
        if runtime is not None:
            report.update(runtime.fault_checks(s, check))
        if browser_executable is not None or (runtime is not None and runtime.browser_channel):
            browser_scenario(s, base_url, browser_executable, check, getattr(runtime, 'browser_channel', None) or 'msedge')
        else:
            report['limitations'].append('Browser checks not run: no browser executable was provided')
        report['passed'] = True
    except AssertionError as failure:
        report['failedCheck'] = str(failure)
        raise
    finally:
        (report_dir / 'validation-ingestion.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


class WindowsRuntime:
    """Database and private-storage fault injection that only the isolated native runtime can provide."""
    browser_channel = 'msedge'

    def __init__(self, run, api_port, sql, restart_backend, kill_backend):
        self.run, self.api_port, self.sql = run, api_port, sql
        self.restart_backend, self.kill_backend = restart_backend, kill_backend

    def committed(self, storage_key): return self.run / 'artifacts/committed' / storage_key

    def fault_checks(self, s, check):
        run, sql = self.run, self.sql
        scene = s.api('/api/v1/scenes', 'POST', {'name': 'fault-injection'})[1]
        versions_path = f'/api/v1/scenes/{scene["id"]}/versions'
        def make(label, segments=2):
            files = synthetic_package(label, segments)
            version = s.api(versions_path, 'POST', version_request(files, label))[1]
            return files, version, {f['relativePath']: f['fileId'] for f in version['files']}
        def put(version, file_id, data): return s.api(f'/api/v1/scene-versions/{version["id"]}/files/{file_id}/content', 'PUT', data)
        def state(file_id): return sql('select status from ar_version_file where id=%s', (file_id,))[0][0]
        def key(file_id): return sql('select storage_key from ar_version_file where id=%s', (file_id,))[0][0]

        files, version, ids = make('storage')
        for path, data in files.items():
            put(version, ids[path], data)
        check('formal storage bytes equal the uploaded bytes', all(
            self.committed(key(ids[p])).read_bytes() == files[p] for p in files))
        mismatch_files, mismatch_version, mismatch_ids = make('mismatch')
        path = 'models/high/00.c.ply'
        check('digest mismatch leaves no formal file', put(mismatch_version, mismatch_ids[path], bytes(b ^ 1 for b in mismatch_files[path]))[0] == 422
              and not self.committed(key(mismatch_ids[path])).exists()
              and not (run / 'artifacts/staging' / (mismatch_ids[path] + '.ready')).exists())
        # A never-uploaded file lets the test occupy its storage target with a directory, making delete fail with IO.
        blocked_files, blocked_version, blocked_ids = make('delete-failure')
        put(blocked_version, blocked_ids['settings.json'], blocked_files['settings.json'])
        blocker = self.committed(key(blocked_ids['models/high/00.c.ply']))
        blocker.mkdir()
        blocked_path = '/api/v1/scene-versions/' + blocked_version['id']
        check('storage deletion failure returns 503', s.api(blocked_path, 'DELETE')[0] == 503)
        failing = s.api(blocked_path)[1]
        check('failed deletion keeps the version, marks DELETE_FAILED and keeps the reason',
              failing['uploadStatus'] == 'DELETE_FAILED' and sql('select failure_reason from ar_version_deletion where version_id=%s',
                                                                 (blocked_version['id'],))[0][0] is not None)
        check('a version being deleted accepts no upload', put(blocked_version, blocked_ids['models/standard/00.c.ply'],
                                                               blocked_files['models/standard/00.c.ply'])[0] == 409)
        blocker.rmdir()
        blocked_keys = [row[0] for row in sql('select storage_key from ar_version_file where version_id=%s', (blocked_version['id'],))]
        check('delete retry completes and removes rows and bytes', s.api(blocked_path, 'DELETE')[0] == 204
              and not sql('select 1 from ar_scene_version where id=%s', (blocked_version['id'],))
              and not sql('select 1 from ar_version_file where version_id=%s', (blocked_version['id'],))
              and not any(self.committed(k).exists() for k in blocked_keys))
        check('completed deletion keeps a minimal receipt', sql('select completed_at is not null from ar_version_deletion where version_id=%s',
                                                                (blocked_version['id'],))[0][0])

        # Durable deletion intent at both crash boundaries (before / after the first unlink).
        recovery = []
        for stage in ('before-unlink', 'after-unlink'):
            stage_files, stage_version, stage_ids = make(stage)
            keys = {p: None for p in stage_files}
            for p, data in stage_files.items():
                put(stage_version, stage_ids[p], data)
                keys[p] = key(stage_ids[p])
            sql('insert into ar_version_deletion(version_id,scene_id,request_key,actor_id,actor_name) '
                'select id,scene_id,request_key,creator_id,creator_name from ar_scene_version where id=%s', (stage_version['id'],))
            if stage == 'after-unlink':
                self.committed(keys['settings.json']).unlink()
            recovery.append((stage_version, keys))
        # Unfinished uploads and unconfirmed writes in one version.
        files, version, ids = make('restart', 3)
        paths = sorted(files)
        confirmed, partial, ready, committed, pending = paths[0], paths[1], paths[2], paths[3], paths[4]
        put(version, ids[confirmed], files[confirmed])
        big = files[partial]
        head = (f"PUT /api/v1/scene-versions/{version['id']}/files/{ids[partial]}/content HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                f"Authorization: Bearer {s.token}\r\nContent-Type: application/octet-stream\r\nContent-Length: {len(big)}\r\n"
                'Connection: close\r\n\r\n')
        sock = socket.create_connection(('127.0.0.1', self.api_port), timeout=10)
        sock.sendall(head.encode() + big[:32])
        until = time.monotonic() + 10
        while state(ids[partial]) != 'UPLOADING' and time.monotonic() < until:
            time.sleep(.05)
        check('partial request is durably marked UPLOADING', state(ids[partial]) == 'UPLOADING')
        (run / 'artifacts/staging' / (ids[ready] + '.ready')).write_bytes(files[ready])
        self.committed(key(ids[committed])).write_bytes(files[committed])
        self.kill_backend()
        sock.close()
        check('hard-stopped service retains the unfinished record', state(ids[partial]) == 'UPLOADING')
        self.restart_backend()
        check('restart completes interrupted whole-version deletions', all(
            not sql('select 1 from ar_scene_version where id=%s', (v['id'],)) and not any(self.committed(k).exists() for k in keys.values())
            and sql('select completed_at is not null from ar_version_deletion where version_id=%s', (v['id'],))[0][0]
            for v, keys in recovery))
        check('restart keeps confirmed files and fails the interrupted upload', state(ids[confirmed]) == 'AVAILABLE'
              and state(ids[partial]) == 'FAILED')
        check('restart recovers ready and committed bytes and leaves PENDING alone', state(ids[ready]) == 'AVAILABLE'
              and state(ids[committed]) == 'AVAILABLE' and state(ids[pending]) == 'PENDING')
        check('recovery audit marks the system action', sql("select count(*) from ar_audit where detail->>'versionId'=%s "
              "and detail->>'performedBy'='SYSTEM_RECONCILIATION'", (version['id'],))[0][0] >= 2)
        check('interrupted file retries with the same id', put(version, ids[partial], big)[1]['status'] == 'AVAILABLE')
        return {'faultInjection': 'database and private-storage fixtures in the isolated native runtime'}


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def windows_runtime(args):
    import psycopg
    args.report_dir.mkdir(parents=True, exist_ok=True)
    evidence_root = ROOT / '.local' if args.report_dir == ROOT / 'docs' else args.report_dir
    evidence_root.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='ingestion-check-', dir=evidence_root))
    pg = args.resources_root / '.local/postgresql17/pgsql/bin'
    java = next((args.resources_root / '.local/java21').glob('jdk*/bin/java.exe'))
    pg_port, redis_port, api_port, web_port = [free_port() for _ in range(4)]
    password = secrets.token_urlsafe(24)
    env = dict(os.environ, AR_DATABASE_URL=f'jdbc:postgresql://127.0.0.1:{pg_port}/ingestion',
               AR_DATABASE_USER='ingestion', AR_DATABASE_PASSWORD=password,
               AR_TOKEN_SECRET=secrets.token_urlsafe(64), AR_BOOTSTRAP_PASSWORD=password,
               AR_REDIS_HOST='127.0.0.1', AR_REDIS_PORT=str(redis_port), AR_PORT=str(api_port),
               AR_STORAGE_ENABLED='true', AR_STORAGE_ROOT=str(run / 'artifacts'),
               AR_STORAGE_MAX_BYTES=str(4 * MIB), AR_STORAGE_VERSION_MAX_FILES='1000',
               AR_STORAGE_VERSION_MAX_BYTES=str(64 * MIB), AR_UPLOAD_DIR=str(run / 'framework-uploads'),
               AR_DEV_API_TARGET=f'http://127.0.0.1:{api_port}', PGPASSWORD=password)
    base = f'http://127.0.0.1:{api_port}'
    web = f'http://127.0.0.1:{web_port}'
    processes, logs = [], []
    state = {'backend': None, 'db': None, 'pg': False}

    def cmd(command):
        with tempfile.TemporaryFile() as output:
            result = subprocess.run([str(a) for a in command], env=env, cwd=run, creationflags=FLAGS, stdout=output, stderr=subprocess.STDOUT)
            output.seek(0)
            content = output.read()
        if result.returncode:
            (run / 'command-error.log').write_bytes(content)
            raise RuntimeError('Test command failed; inspect local command-error.log')
        return content.decode(errors='replace')

    def start(name, command, cwd=run):
        log = (run / (name + '.log')).open('ab')
        logs.append(log)
        process = subprocess.Popen([str(a) for a in command], cwd=cwd, env=env, creationflags=FLAGS, stdout=log, stderr=log)
        processes.append(process)
        return process

    probe = Session(base)

    def start_backend():
        process = start('backend', [java, '-Duser.timezone=UTC', '-jar', args.backend_jar, '--server.address=127.0.0.1'])
        until = time.monotonic() + 120
        while time.monotonic() < until:
            if process.poll() is not None:
                raise RuntimeError('Backend exited; inspect ' + str(run / 'backend.log'))
            try:
                if probe.api('/captchaImage', auth=False)[0] == 200:
                    state['backend'] = process
                    return
            except OSError:
                pass
            time.sleep(.5)
        raise RuntimeError('Backend startup timed out')

    def kill_backend():
        state['backend'].kill()
        state['backend'].wait(timeout=15)

    def sql(statement, params=()):
        with state['db'].cursor() as cursor:
            cursor.execute(statement, params)
            return cursor.fetchall() if cursor.description else []

    try:
        version = cmd([pg / 'postgres.exe', '--version']).strip()
        password_file = run / 'init-password'
        password_file.write_text(password)
        try:
            cmd([pg / 'initdb.exe', '-D', run / 'pgdata', '-U', 'ingestion', '--pwfile=' + str(password_file),
                 '--auth=scram-sha-256', '--encoding=UTF8', '--locale=C'])
        finally:
            password_file.unlink(missing_ok=True)
        cmd([pg / 'pg_ctl.exe', '-D', run / 'pgdata', '-l', run / 'postgres.log', '-o', f'-h 127.0.0.1 -p {pg_port}', '-w', 'start'])
        state['pg'] = True
        cmd([pg / 'createdb.exe', '-h', '127.0.0.1', '-p', str(pg_port), '-U', 'ingestion', 'ingestion'])
        state['db'] = psycopg.connect(host='127.0.0.1', port=pg_port, dbname='ingestion', user='ingestion', password=password, autocommit=True)
        start('redis', ['redis-server', '--bind', '127.0.0.1', '--port', str(redis_port), '--save', '', '--appendonly', 'no'])
        start_backend()
        start('vite', ['node', ROOT / 'frontend/node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', str(web_port), '--strictPort'], ROOT / 'frontend')
        until = time.monotonic() + 30
        while time.monotonic() < until:
            try:
                urllib.request.urlopen(web, timeout=1).close()
                break
            except OSError:
                time.sleep(.3)
        credentials = run / 'credentials.json'
        credentials.write_text(json.dumps({'username': 'bootstrap', 'password': password}), encoding='utf-8')
        runtime = WindowsRuntime(run, api_port, sql, start_backend, kill_backend)
        report = run_http_checks(web, base, credentials, args.report_dir, None, runtime)
        report.update(postgres=version, runtime='isolated native PostgreSQL 17 / Redis / Spring Boot / Vite / Edge',
                      backendJar=str(args.backend_jar), backendJarSha256=sha256(args.backend_jar.read_bytes()))
        (args.report_dir / 'validation-ingestion.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return report
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        if state['db']:
            state['db'].close()
        if state['pg']:
            cmd([pg / 'pg_ctl.exe', '-D', run / 'pgdata', '-m', 'fast', '-w', 'stop'])
        for log in logs:
            log.close()
        print('Evidence directory:', run, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--report-dir', type=Path, default=ROOT / 'docs')
    parser.add_argument('--backend-jar', type=Path, default=ROOT / 'backend/ruoyi-admin/target/ruoyi-admin.jar',
                        help='Windows runtime: the already tested Jar to start')
    parser.add_argument('--resources-root', type=Path, default=ROOT, help='Windows runtime: root holding .local PostgreSQL/Java')
    parser.add_argument('--base-url', help='External instance origin serving the frontend and /prod-api, e.g. http://127.0.0.1:18082')
    parser.add_argument('--admin-base-url', help='External instance administrator API base, e.g. http://127.0.0.1:18082/prod-api')
    parser.add_argument('--credentials-file', type=Path, help='External instance JSON with username and password (0600)')
    parser.add_argument('--browser-executable', type=Path, help='External instance: Chrome/Chromium for the browser checks; omit to skip them')
    args = parser.parse_args()
    args.report_dir = args.report_dir.resolve()
    external = [args.base_url, args.admin_base_url, args.credentials_file]
    if any(external):
        if not all(external):
            parser.error('--base-url, --admin-base-url and --credentials-file must be given together')
        run_http_checks(args.base_url, args.admin_base_url, args.credentials_file, args.report_dir, args.browser_executable)
    else:
        args.backend_jar = args.backend_jar.resolve()
        windows_runtime(args)


if __name__ == '__main__':
    main()
