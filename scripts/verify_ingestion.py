"""Ingestion acceptance for 4DGS scenes: combined fixed-manifest creation, per-file upload/recovery, lifecycle and deletion.

Two ways to run:
* External isolated instance (any OS): --base-url, --admin-base-url and --credentials-file drive HTTP (and an optional
  browser) checks through `run_http_checks`; nothing is started or installed.
* Windows runtime (review.py, harness): a new private PostgreSQL 17 / Redis / Spring Boot / Vite directory, with
  database and private-storage fault injection on top of the same HTTP checks. Never uses the running Demo database.

Synthetic model bytes are not renderable 4DGS content; this verifies the distribution contract only: fixed file
manifest, authenticated uploads, range downloads, anonymous visibility for complete enabled scenes, and deletion.
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
    """A small fixed scene file set: settings plus synthetic model files in nested directories.

    Returns {relativePath: bytes}. The model files are synthetic text and are not renderable."""
    files = {'settings.json': json.dumps({'synthetic': label}).encode() + b'\n'}
    for index in range(standard_segments):
        files[f'models/standard/{index:02d}.c.ply'] = f'synthetic standard segment {index} {label}\n'.encode() * (index + 3)
    files['models/high/00.c.ply'] = f'synthetic high segment {label}\n'.encode() * 7
    return files


def manifest(files):
    return [{'relativePath': path, 'bytes': len(data), 'sha256': sha256(data)}
            for path, data in sorted(files.items())]


def scene_request(name, files, description='', request_key=None):
    return {'requestKey': request_key or str(uuid.uuid4()), 'name': name, 'description': description,
            'files': manifest(files)}


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
    config = s.api('/api/v1/scenes/config')[1]
    check('upload limits fit the lock isolation fixture', config.get('sceneMaxFiles', 0) >= count
          and config.get('sceneMaxBytes', 0) >= sum(map(len, files.values()))
          and config.get('maxBytes', 0) >= max(map(len, files.values())))
    status, scene = s.api('/api/v1/scenes', 'POST', scene_request('upload-lock-isolation-' + uuid.uuid4().hex[:8], files))
    check('lock isolation scene created', status == 201)
    ids = {f['relativePath']: f['fileId'] for f in scene['files']}
    groups = {}
    for path, file_id in sorted(ids.items()):
        groups.setdefault(former_lock_bucket(file_id), []).append(path)
    held, other = next(group for group in groups.values() if len(group) >= 2)[:2]
    base = '/api/v1/scenes/' + scene['id']
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
    return {'sceneId': scene['id']}


def scenario(s, check):
    """Scene lifecycle over HTTP only. Returns identifiers the caller may inspect or reuse."""
    anonymous = lambda path, method='GET', body=None, headers=None: s.api(path, method, body, auth=False, headers=headers)
    config_status, config = s.api('/api/v1/scenes/config')
    check('administrator can read scene upload limits', config_status == 200 and all(
        isinstance(config.get(key), int) and config[key] > 0 for key in ('maxBytes', 'sceneMaxFiles', 'sceneMaxBytes')))
    check('anonymous scene config rejected', anonymous('/api/v1/scenes/config')[0] == 401)
    check('anonymous scene create rejected', anonymous('/api/v1/scenes', 'POST',
                                                       scene_request('anonymous', {'settings.json': b'x'}))[0] == 401)
    check('anonymous file content rejected', s.raw('/api/v1/scenes/%s/files/%s/content' % (uuid.uuid4(), uuid.uuid4()),
                                                   auth=False)[0] == 401)

    name = 'ingestion-' + uuid.uuid4().hex[:10]
    files1 = synthetic_package('main')

    def reject(label, expected_status, body):
        status, error = s.api('/api/v1/scenes', 'POST', body)
        check(f'{label} returns {expected_status}', status == expected_status and bool(error.get('message')))

    def traversal(files): files['../escape.bin'] = files.pop('models/high/00.c.ply')
    def absolute(files): files['/etc/escape.bin'] = files.pop('models/high/00.c.ply')
    def duplicate_file(files):
        body = scene_request(name, files)
        body['files'].append(dict(body['files'][0]))
        return body
    def case_duplicate(files): files['Settings.json'] = files['settings.json']
    for label, mutate in [('path traversal', traversal), ('absolute path', absolute),
                          ('case-insensitive duplicate path', case_duplicate)]:
        changed_files = copy.deepcopy(files1)
        mutate(changed_files)
        reject(label, 400, scene_request(name, changed_files))
    reject('same path registered twice', 400, duplicate_file(copy.deepcopy(files1)))
    reject('empty file list', 400, {**scene_request(name, files1), 'files': []})
    reject('blank scene name', 400, {**scene_request(name, files1), 'name': '   '})
    reject('scene name longer than 200', 400, {**scene_request(name, files1), 'name': 'x' * 201})
    reject('description longer than 2000', 400, {**scene_request(name, files1), 'description': 'x' * 2001})
    oversize = scene_request(name, files1)
    oversize['files'][0]['bytes'] = config['maxBytes'] + 1
    reject('file larger than the single-file limit', 413, oversize)
    if config['sceneMaxFiles'] <= 5000:
        too_many = {'files': [{'relativePath': f'm/{index}.c.ply', 'bytes': 1, 'sha256': sha256(b'x')}
                              for index in range(config['sceneMaxFiles'] + 1)]}
        reject('more files than the per-scene limit', 413, {**scene_request(name, files1), **too_many})
    total_count = config['sceneMaxBytes'] // config['maxBytes'] + 1
    if total_count <= config['sceneMaxFiles']:
        remaining = config['sceneMaxBytes'] + 1
        entries = []
        for index in range(total_count):
            size = min(config['maxBytes'], remaining)
            entries.append({'relativePath': f'total/{index}.bin', 'bytes': size, 'sha256': sha256(b'x')})
            remaining -= size
        reject('total bytes above the per-scene limit', 413, {**scene_request(name, files1), 'files': entries})
    check('rejected requests created no scene', s.api('/api/v1/scenes?name=' + urllib.parse.quote(name))[1]['total'] == 0)

    request1 = scene_request(name, files1, 'first scene')
    status, scene = s.api('/api/v1/scenes', 'POST', request1)
    check('combined create returns 201 with detail', status == 201 and isinstance(scene.get('id'), str)
          and scene.get('name') == name and scene.get('description') == 'first scene'
          and isinstance(scene.get('files'), list))
    scene_id, scene_path = scene['id'], '/api/v1/scenes/' + scene['id']
    check('new scene is enabled and PENDING with every file registered',
          scene.get('enabled') is True and scene.get('uploadStatus') == 'PENDING' and scene.get('fileCount') == len(files1)
          and scene.get('availableCount') == 0 and all(file.get('status') == 'PENDING' and file.get('attempts') == 0
                                                       for file in scene['files']))
    check('created detail carries the fixed file set and no version fields',
          sorted(file['relativePath'] for file in scene['files']) == sorted(files1)
          and not any(key in scene for key in ('versionId', 'versionNo', 'published')))
    status, retry = s.api('/api/v1/scenes', 'POST', request1)
    check('identical request-key retry returns the original scene', status == 200 and retry.get('id') == scene_id
          and s.api('/api/v1/scenes?name=' + urllib.parse.quote(name))[1]['total'] == 1)
    changed = copy.deepcopy(request1)
    changed['files'][0]['sha256'] = sha256(b'different')
    check('same request key with a different digest conflicts', s.api('/api/v1/scenes', 'POST', changed)[0] == 409)
    check('same request key with a different description conflicts',
          s.api('/api/v1/scenes', 'POST', {**request1, 'description': 'other'})[0] == 409)
    check('same request key with a different name conflicts',
          s.api('/api/v1/scenes', 'POST', {**request1, 'name': name + '-other'})[0] == 409)
    listed = s.api('/api/v1/scenes?name=' + urllib.parse.quote(name))[1]
    check('scene list exposes summary fields and no publication pointer',
          listed['total'] == 1 and isinstance(listed['items'][0].get('lockVersion'), int)
          and listed['items'][0]['uploadStatus'] == 'PENDING' and 'published' not in listed['items'][0])

    status, edited = s.api(scene_path, 'PUT', {'name': name + '-edited', 'description': 'edited description',
                                               'expectedVersion': scene['lockVersion']})
    check('name and description can be edited', status == 200 and edited.get('name') == name + '-edited'
          and edited.get('description') == 'edited description'
          and sorted(file['relativePath'] for file in edited['files']) == sorted(files1))
    check('stale metadata edit conflicts', s.api(scene_path, 'PUT', {'name': name, 'description': 'stale',
                                                                     'expectedVersion': scene['lockVersion']})[0] == 409)
    scene = edited
    ids = {file['relativePath']: file['fileId'] for file in scene['files']}
    def content(file_id): return f'{scene_path}/files/{file_id}/content'
    def upload(path, data): return s.api(content(ids[path]), 'PUT', data)
    check('incomplete scene is invisible to anonymous clients',
          scene_id not in {item['id'] for item in anonymous('/api/v1/client/scenes')[1].get('items', [])}
          and anonymous('/api/v1/client/scenes/' + scene_id)[0] == 404
          and anonymous(f'/api/v1/client/scenes/{scene_id}/files/{ids["settings.json"]}/content/settings.json')[0] == 404)

    target = 'models/standard/00.c.ply'
    good = files1[target]
    bad = bytes(byte ^ 1 for byte in good)
    check('digest mismatch with the declared size returns 422', upload(target, bad)[0] == 422)
    file_status = s.api(f'{scene_path}/files/{ids[target]}')[1]
    check('digest mismatch is persisted as FAILED with a reason and one attempt',
          file_status.get('status') == 'FAILED' and 'SHA256' in file_status.get('failureReason', '')
          and file_status.get('attempts') == 1)
    check('failed file makes the scene FAILED', s.api(scene_path)[1].get('uploadStatus') == 'FAILED'
          and s.api(scene_path)[1].get('failedCount') == 1)
    check('actual size beyond the declaration returns 422', upload(target, good + b'x')[0] == 422)
    check('another scene cannot reach the file', s.api(f'/api/v1/scenes/{uuid.uuid4()}/files/{ids[target]}/content',
                                                       'PUT', good)[0] == 404)
    check('unknown file in the scene is rejected', s.api(f'{scene_path}/files/{uuid.uuid4()}/content', 'PUT', good)[0] == 404)
    check('anonymous upload rejected', s.api(content(ids[target]), 'PUT', good, auth=False)[0] == 401)
    status, uploaded = upload(target, good)
    check('failed file is retried completely and becomes AVAILABLE', status == 200 and uploaded.get('status') == 'AVAILABLE'
          and uploaded.get('attempts') == 3 and uploaded.get('failureReason') is None)
    first_attempts = {target: uploaded['attempts']}
    status, repeated = upload(target, good)
    check('available file upload is idempotent and does not overwrite',
          status == 200 and repeated.get('status') == 'AVAILABLE' and repeated.get('attempts') == first_attempts[target])
    for path in sorted(files1):
        if path != target:
            status, state = upload(path, files1[path])
            check('upload ' + path, status == 200 and state.get('status') == 'AVAILABLE')
            first_attempts[path] = state['attempts']
    ready = s.api(scene_path)[1]
    check('all files AVAILABLE makes the scene READY', ready.get('uploadStatus') == 'READY'
          and ready.get('availableCount') == len(files1) and ready.get('failedCount') == 0
          and all(file.get('status') == 'AVAILABLE' for file in ready['files']))
    check('completed files are not attempted again',
          all(file['attempts'] == first_attempts[file['relativePath']] for file in ready['files']))

    sample_path = 'models/high/00.c.ply'
    sample = files1[sample_path]
    status, headers, body = s.raw(content(ids[sample_path]))
    check('administrator downloads exact bytes with the SHA256 strong ETag', status == 200 and body == sample
          and headers.get('ETag') == '"' + sha256(sample) + '"')
    status, headers, body = s.raw(content(ids[sample_path]), headers={'Range': 'bytes=0-3'})
    check('administrator Range 0-3 returns 206 with exact bytes', status == 206 and body == sample[:4]
          and headers.get('Content-Range') == f'bytes 0-3/{len(sample)}')
    status, headers, body = s.raw(content(ids[sample_path]), headers={'Range': 'bytes=2-'})
    check('administrator open-ended Range returns the tail', status == 206 and body == sample[2:])
    check('administrator out-of-range request returns 416',
          s.raw(content(ids[sample_path]), headers={'Range': 'bytes=99999999-'})[0] == 416)
    status, headers, body = s.raw(content(ids[sample_path]), headers={'Range': 'bytes=0-3',
                                                                      'If-Range': '"' + '0' * 64 + '"'})
    check('mismatched If-Range returns the full file', status == 200 and body == sample)
    status, headers, body = s.raw(content(ids[sample_path]), 'HEAD')
    check('HEAD returns the length without a body', status == 200 and int(headers['Content-Length']) == len(sample)
          and body == b'')
    check('anonymous administrator download rejected', s.raw(content(ids[sample_path]), auth=False)[0] == 401)

    # A second scene is disabled while its upload is still incomplete; completion must not re-enable it.
    files2 = {'settings.json': b'{"disable":true}\n', 'models/only.ply': b'disabled while uploading\n' * 9}
    status, scene2 = s.api('/api/v1/scenes', 'POST', scene_request('disable-' + uuid.uuid4().hex[:8], files2,
                                                                   'disabled during upload'))
    check('disable-while-uploading scene created', status == 201)
    ids2 = {file['relativePath']: file['fileId'] for file in scene2['files']}
    paths2 = sorted(files2)
    def upload2(path): return s.api(f'/api/v1/scenes/{scene2["id"]}/files/{ids2[path]}/content', 'PUT', files2[path])
    check('first file of the second scene is available', upload2(paths2[0])[1].get('status') == 'AVAILABLE')
    status, disabled = s.api(f'/api/v1/scenes/{scene2["id"]}/enabled', 'PUT',
                             {'enabled': False, 'expectedVersion': scene2['lockVersion'], 'reason': '暂停上传'})
    check('scene can be disabled while an upload is incomplete', status == 200 and disabled.get('enabled') is False)
    check('remaining file uploads on a disabled scene', upload2(paths2[1])[1].get('status') == 'AVAILABLE')
    finished2 = s.api('/api/v1/scenes/' + scene2['id'])[1]
    check('upload completion keeps the scene disabled and READY', finished2.get('uploadStatus') == 'READY'
          and finished2.get('enabled') is False)
    check('admin can read a ready file of a disabled scene',
          s.raw(f'/api/v1/scenes/{scene2["id"]}/files/{ids2[paths2[1]]}/content')[0] == 200)

    client_items = anonymous('/api/v1/client/scenes')[1]
    check('anonymous list includes the complete enabled scene',
          {item['id']: item['name'] for item in client_items['items']}[scene_id] == name + '-edited')
    check('anonymous list excludes the complete disabled scene',
          scene2['id'] not in {item['id'] for item in client_items['items']})
    check('anonymous detail of the disabled scene is hidden', anonymous('/api/v1/client/scenes/' + scene2['id'])[0] == 404)
    check('anonymous file of the disabled scene is hidden',
          anonymous(f'/api/v1/client/scenes/{scene2["id"]}/files/{ids2[paths2[1]]}/content/{Path(paths2[1]).name}')[0] == 404)
    client_detail = anonymous('/api/v1/client/scenes/' + scene_id)
    check('anonymous detail lists the fixed files and totals', client_detail[0] == 200
          and client_detail[1].get('sceneId') == scene_id and client_detail[1].get('fileCount') == len(files1)
          and client_detail[1].get('totalBytes') == sum(map(len, files1.values()))
          and sorted(file['relativePath'] for file in client_detail[1].get('files', [])) == sorted(files1)
          and not any(key in client_detail[1] for key in ('versionId', 'versionNo', 'published')))
    anonymous_file = next(file for file in client_detail[1]['files'] if file['relativePath'] == sample_path)
    download = anonymous_file['downloadPath']
    check('anonymous download path points at the scene file route',
          download.startswith(f'/api/v1/client/scenes/{scene_id}/files/{ids[sample_path]}/content/'))
    status, headers, body = s.raw(download, auth=False)
    check('anonymous download returns exact bytes without store caching', status == 200 and body == sample
          and headers.get('ETag') == '"' + sha256(sample) + '"' and 'no-store' in headers.get('Cache-Control', '')
          and bool(headers.get('Content-Type')))
    status, headers, body = s.raw(download, auth=False, headers={'Range': 'bytes=0-3'})
    check('anonymous Range 0-3 returns 206', status == 206 and body == sample[:4]
          and headers.get('Content-Range') == f'bytes 0-3/{len(sample)}')
    status, headers, body = s.raw(download, auth=False, headers={'Range': 'bytes=0-3', 'If-Range': '"' + '0' * 64 + '"'})
    check('anonymous mismatched If-Range returns the full file', status == 200 and body == sample)
    status, headers, body = s.raw(download, auth=False, method='HEAD')
    check('anonymous HEAD returns the length without a body', status == 200
          and int(headers['Content-Length']) == len(sample) and body == b'')
    wrong = f'/api/v1/client/scenes/{scene_id}/files/{ids2[paths2[0]]}/content/{Path(paths2[0]).name}'
    check('anonymous file from another scene is hidden', anonymous(wrong)[0] == 404)

    status, enabled2 = s.api(f'/api/v1/scenes/{scene2["id"]}/enabled', 'PUT',
                             {'enabled': True, 'expectedVersion': finished2['lockVersion'], 'reason': '完成上传后启用'})
    check('re-enabling a complete scene exposes it to anonymous clients', status == 200 and enabled2.get('enabled') is True
          and scene2['id'] in {item['id'] for item in anonymous('/api/v1/client/scenes')[1]['items']})

    # Deleting an actively uploading scene is refused; the held request can finish before deletion.
    files3 = synthetic_package('active-delete')
    request3 = scene_request('active-delete-' + uuid.uuid4().hex[:8], files3)
    status, scene3 = s.api('/api/v1/scenes', 'POST', request3)
    check('active-delete scene created', status == 201)
    ids3 = {file['relativePath']: file['fileId'] for file in scene3['files']}
    held_path = 'models/standard/00.c.ply'
    sock = held_upload(s, f'/api/v1/scenes/{scene3["id"]}/files/{ids3[held_path]}/content', files3[held_path],
                       len(files3[held_path]) - 1)
    try:
        deadline = time.time() + 10
        while time.time() < deadline and s.api(f'/api/v1/scenes/{scene3["id"]}/files/{ids3[held_path]}')[1].get('status') != 'UPLOADING':
            time.sleep(0.05)
        check('active upload is in flight', s.api(f'/api/v1/scenes/{scene3["id"]}/files/{ids3[held_path]}')[1].get('status') == 'UPLOADING')
        path3 = '/api/v1/scenes/' + scene3['id']
        active3 = s.api(path3)[1]
        check('deletion during an active upload is refused',
              s.api(f'{path3}?expectedVersion={active3["lockVersion"]}', 'DELETE')[0] == 409)
        check('held upload completes', finish_held(sock, files3[held_path][-1:]) == 200)
    finally:
        sock.close()
    for path, data in files3.items():
        if path != held_path:
            s.api(f'{path3}/files/{ids3[path]}/content', 'PUT', data)
    current3 = s.api(path3)[1]
    check('active-delete scene is READY before deletion', current3.get('uploadStatus') == 'READY')
    check('anonymous deletion rejected', s.api(f'{path3}?expectedVersion={current3["lockVersion"]}', 'DELETE', auth=False)[0] == 401)
    check('missing deletion revision rejected', s.api(path3, 'DELETE')[0] == 400)
    check('stale deletion revision rejected',
          s.api(f'{path3}?expectedVersion={current3["lockVersion"] + 99}', 'DELETE')[0] == 409)
    check('unknown scene deletion returns 404',
          s.api(f'/api/v1/scenes/{uuid.uuid4()}?expectedVersion=0', 'DELETE')[0] == 404)
    check('confirmed scene deletion returns 204',
          s.api(f'{path3}?expectedVersion={current3["lockVersion"]}', 'DELETE')[0] == 204)
    check('repeat deletion is idempotent without a revision check',
          s.api(f'{path3}?expectedVersion=0', 'DELETE')[0] == 204)
    check('deleted scene detail is hidden', s.api(path3)[0] == 404)
    check('deleted scene is excluded from the name list',
          s.api('/api/v1/scenes?name=' + urllib.parse.quote(scene3['name']))[1]['total'] == 0)
    check('deleted scene cannot be edited',
          s.api(path3, 'PUT', {'name': 'after-delete', 'description': '', 'expectedVersion': 0})[0] == 404)
    check('deleted scene cannot be enabled',
          s.api(path3 + '/enabled', 'PUT', {'enabled': True, 'expectedVersion': 0, 'reason': 'test'})[0] == 404)
    check('deleted scene file is not readable', s.api(f'{path3}/files/{ids3[held_path]}')[0] == 404)
    check('deleted scene upload is not accepted',
          s.api(f'{path3}/files/{ids3[held_path]}/content', 'PUT', files3[held_path])[0] == 404)
    check('late create retry after deletion returns 410',
          s.api('/api/v1/scenes', 'POST', request3)[0] == 410)

    audits = s.api('/api/v1/audits?limit=100')[1]['items']
    actions = [(item['action'], item['actorName'], item['detail']) for item in audits if item['sceneId'] == scene3['id']]
    check('scene lifecycle audits are written', {'CREATE', 'SCENE_DELETE_REQUEST', 'SCENE_DELETE'}
          <= {action for action, _, _ in actions})
    current_actor = s.api('/getInfo')[1]['user']['userName']
    check('deletion audit records the authenticated actor', all(actor == current_actor for _, actor, _ in actions))
    details = []
    for _, _, raw_detail in actions:
        details.append(json.loads(raw_detail) if isinstance(raw_detail, str) else raw_detail)
    check('new scene audit details do not carry a version id',
          all('versionId' not in (detail or {}) for detail in details))

    files4 = {'settings.json': b'{"race":true}\n', 'models/00.ply': b'race\n'}
    status, scene4 = s.api('/api/v1/scenes', 'POST', scene_request('delete-race-' + uuid.uuid4().hex[:8], files4))
    check('concurrent deletion scene created', status == 201)
    race_path = '/api/v1/scenes/' + scene4['id'] + '?expectedVersion=0'
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(lambda _: s.api(race_path, 'DELETE')[0], range(2)))
    check('concurrent deletes have at least one success and no server error',
          204 in outcomes and all(status in (204, 404, 409) for status in outcomes))
    check('concurrently deleted scene is gone', s.api('/api/v1/scenes/' + scene4['id'])[0] == 404)

    big = None
    if config['maxBytes'] >= 22 * MIB and config['sceneMaxBytes'] >= 22 * MIB:
        # Larger than the gateway's default 20 MiB body limit and not above the configured per-file limit.
        payload = os.urandom(21 * MIB)
        files_big = {'settings.json': b'{"large":true}\n', 'models/standard/00.c.ply': payload}
        status, big = s.api('/api/v1/scenes', 'POST', scene_request('large-upload-' + uuid.uuid4().hex[:8], files_big,
                                                                    'large file'))
        check('large scene created', status == 201)
        big_path = '/api/v1/scenes/' + big['id']
        results = {entry['relativePath']: s.api(f'{big_path}/files/{entry["fileId"]}/content', 'PUT',
                                                files_big[entry['relativePath']], timeout=300)
                   for entry in big['files']}
        check('21 MiB file uploads through the configured base URL',
              all(result[0] == 200 and result[1].get('status') == 'AVAILABLE' for result in results.values()))
        large_id = next(entry['fileId'] for entry in big['files'] if entry['relativePath'].endswith('.ply'))
        status, headers, body = s.raw(f'{big_path}/files/{large_id}/content',
                                      headers={'Range': f'bytes={21 * MIB - 8}-'})
        check('large file tail Range returns exact bytes', status == 206 and body == payload[-8:])
        current_big = s.api(big_path)[1]
        check('large scene deletes physically', s.api(f'{big_path}?expectedVersion={current_big["lockVersion"]}',
                                                      'DELETE')[0] == 204 and s.api(big_path)[0] == 404)
    return {'sceneId': scene_id, 'config': config, 'largeUploadChecked': big is not None}


def browser_scenario(s, web_base_url, executable, check, channel='msedge'):
    """Real browser: create a scene through the unified drawer, upload a directory and reopen the detail."""
    from playwright.sync_api import sync_playwright
    name = 'ui-' + uuid.uuid4().hex[:8]
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
            errors, requests = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: requests.append(request.url))
            page.goto(web_base_url + '/admin/scenes')
            page.get_by_role('button', name='新建场景', exact=True).click()
            drawer = page.locator('.scene-panel')
            drawer.wait_for(state='visible')
            drawer.get_by_role('heading', name='新建场景', exact=True).wait_for()
            name_input = drawer.locator('input:not([type=file])').first
            name_input.fill(name)
            drawer.locator('textarea').first.fill('浏览器验收合成场景')
            drawer.locator('input[data-import-mode=directory]').set_input_files(str(package))
            page.get_by_text(f'待导入：{len(files)} 个文件', exact=False).wait_for()
            drawer.get_by_role('button', name='开始上传', exact=True).click()
            drawer.get_by_text('场景已就绪', exact=False).first.wait_for(timeout=120000)
            drawer.get_by_role('button', name='停止本次传输', exact=True).wait_for(state='hidden', timeout=30000)
            check('browser creates one scene with a fixed file set through the unified drawer',
                  s.api('/api/v1/scenes?name=' + urllib.parse.quote(name))[1]['total'] == 1)
            created = s.api('/api/v1/scenes?name=' + urllib.parse.quote(name))[1]['items'][0]
            detail = s.api('/api/v1/scenes/' + created['id'])[1]
            check('browser upload reaches READY with every file available and no publish call',
                  detail.get('uploadStatus') == 'READY' and detail.get('availableCount') == len(files)
                  and not any('/versions' in url or '/publish' in url or 'versionId' in url for url in requests))
            check('browser panel hides import and resume controls after READY',
                  not any(drawer.get_by_role('button', name=label, exact=True).count()
                          for label in ('开始上传', '继续上传', '重新选择目录', '重新选择文件',
                                        '导入资源目录', '导入文件')))
            for width in (1440, 1024):
                page.set_viewport_size({'width': width, 'height': 1000})
                buttons = [button for button in drawer.get_by_role('button').all() if button.is_visible()]
                obscured = []
                for button in buttons:
                    button.scroll_into_view_if_needed()
                    if not button.evaluate(
                            """el => { const r = el.getBoundingClientRect();
                               if (r.x < 0 || r.x + r.width > innerWidth) return false;
                               const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
                               return !!top && (top === el || el.contains(top)); }"""):
                        obscured.append(button.inner_text() or button.get_attribute('class'))
                check(f'browser panel buttons are not covered at {width}px', not obscured and len(buttons) > 0)
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.goto(web_base_url + '/admin/scenes')
            row = page.get_by_role('row').filter(has_text=name)
            row.get_by_role('button', name='查看', exact=True).click()
            reopened = page.locator('.scene-panel')
            reopened.wait_for(state='visible')
            check('browser detail is addressable only by scene id',
                  f'sceneId={created["id"]}' in page.url and 'versionId' not in page.url)
            check('browser reopens the scene detail with its name and files',
                  name in reopened.inner_text()
                  and all(reopened.get_by_text(path, exact=True).count() for path in ('settings.json', 'models/high/00.c.ply')))
            page.screenshot(path=str(ROOT / '.local/scenes-browser.png'), full_page=True)
            check('browser page reported no script errors', not errors)
            return [{'name': 'real login, unified scene create, directory upload and fixed file detail', 'passed': True}]
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
              'limitations': ['Synthetic model bytes are not renderable 4DGS content',
                              'No client playback or decoder validation',
                              'No power-loss or disk-full injection outside the Windows fault runtime']}
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

    def committed(self, storage_key):
        return self.run / 'artifacts/committed' / storage_key

    def fault_checks(self, s, check):
        run, sql = self.run, self.sql
        def make(label, segments=2):
            files = synthetic_package(label, segments)
            status, scene = s.api('/api/v1/scenes', 'POST', scene_request('fault-' + label + '-' + uuid.uuid4().hex[:6],
                                                                          files, label))
            check('fault fixture ' + label + ' created', status == 201)
            return files, scene, {file['relativePath']: file['fileId'] for file in scene['files']}
        def put(scene, file_id, data):
            return s.api(f'/api/v1/scenes/{scene["id"]}/files/{file_id}/content', 'PUT', data)
        def state(file_id):
            return sql('select status from ar_scene_file where id=%s', (file_id,))[0][0]
        def key(file_id):
            return sql('select storage_key from ar_scene_file where id=%s', (file_id,))[0][0]

        files, scene, ids = make('storage')
        for path, data in files.items():
            put(scene, ids[path], data)
        check('formal storage bytes equal the uploaded bytes',
              all(self.committed(key(ids[path])).read_bytes() == files[path] for path in files))

        mismatch_files, mismatch_scene, mismatch_ids = make('mismatch')
        path = 'models/high/00.c.ply'
        check('digest mismatch leaves no formal file',
              put(mismatch_scene, mismatch_ids[path], bytes(byte ^ 1 for byte in mismatch_files[path]))[0] == 422
              and not self.committed(key(mismatch_ids[path])).exists()
              and not (run / 'artifacts/staging' / (mismatch_ids[path] + '.ready')).exists())

        # A never-uploaded file lets the test occupy its storage target with a directory, making delete fail with IO.
        blocked_files, blocked_scene, blocked_ids = make('delete-failure')
        put(blocked_scene, blocked_ids['settings.json'], blocked_files['settings.json'])
        blocker = self.committed(key(blocked_ids['models/high/00.c.ply']))
        blocker.mkdir()
        blocked_path = '/api/v1/scenes/' + blocked_scene['id']
        blocked_current = s.api(blocked_path)[1]
        check('storage deletion failure returns 503',
              s.api(f'{blocked_path}?expectedVersion={blocked_current["lockVersion"]}', 'DELETE')[0] == 503)
        failing = s.api(blocked_path)[1]
        check('failed deletion keeps the scene, marks DELETE_FAILED and keeps the reason',
              failing.get('uploadStatus') == 'DELETE_FAILED'
              and sql('select failure_reason from ar_scene_deletion where scene_id=%s', (blocked_scene['id'],))[0][0] is not None)
        check('a scene being deleted accepts no upload',
              put(blocked_scene, blocked_ids['models/standard/00.c.ply'],
                  blocked_files['models/standard/00.c.ply'])[0] == 409)
        blocker.rmdir()
        blocked_keys = [row[0] for row in sql('select storage_key from ar_scene_file where scene_id=%s',
                                               (blocked_scene['id'],))]
        check('delete retry ignores a stale revision and completes', s.api(f'{blocked_path}?expectedVersion=0', 'DELETE')[0] == 204)
        check('completed deletion removes file rows and bytes but keeps the scene row and receipt',
              not sql('select 1 from ar_scene_file where scene_id=%s', (blocked_scene['id'],))
              and sql('select deleted_at is not null from ar_scene where id=%s', (blocked_scene['id'],))[0][0]
              and not any(self.committed(storage_key).exists() for storage_key in blocked_keys)
              and sql('select completed_at is not null from ar_scene_deletion where scene_id=%s',
                      (blocked_scene['id'],))[0][0])

        # Durable deletion intent at both crash boundaries (before / after the first unlink).
        recovery = []
        for stage in ('before-unlink', 'after-unlink'):
            stage_files, stage_scene, stage_ids = make(stage)
            keys = {path: None for path in stage_files}
            for path, data in stage_files.items():
                put(stage_scene, stage_ids[path], data)
                keys[path] = key(stage_ids[path])
            sql('insert into ar_scene_deletion(scene_id,request_key,actor_id,actor_name) '
                "select id,request_key,1,'bootstrap' from ar_scene where id=%s", (stage_scene['id'],))
            if stage == 'after-unlink':
                self.committed(keys['settings.json']).unlink()
            recovery.append((stage_scene, keys))

        # Unfinished uploads and unconfirmed writes in one scene.
        files, scene, ids = make('restart', 3)
        paths = sorted(files)
        confirmed, partial, ready, committed, pending = paths[0], paths[1], paths[2], paths[3], paths[4]
        put(scene, ids[confirmed], files[confirmed])
        big = files[partial]
        head = (f"PUT /api/v1/scenes/{scene['id']}/files/{ids[partial]}/content HTTP/1.1\r\nHost: 127.0.0.1\r\n"
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
        check('restart completes interrupted scene deletions', all(
            not sql('select 1 from ar_scene_file where scene_id=%s', (item['id'],))
            and sql('select deleted_at is not null from ar_scene where id=%s', (item['id'],))[0][0]
            and not any(self.committed(storage_key).exists() for storage_key in keys.values())
            and sql('select completed_at is not null from ar_scene_deletion where scene_id=%s', (item['id'],))[0][0]
            for item, keys in recovery))
        check('restart keeps confirmed files and fails the interrupted upload',
              state(ids[confirmed]) == 'AVAILABLE' and state(ids[partial]) == 'FAILED')
        check('restart recovers ready and committed bytes and leaves PENDING alone',
              state(ids[ready]) == 'AVAILABLE' and state(ids[committed]) == 'AVAILABLE' and state(ids[pending]) == 'PENDING')
        check('recovery audit marks the system action', sql(
            "select count(*) from ar_audit where scene_id=%s and detail->>'performedBy'='SYSTEM_RECONCILIATION'",
            (scene['id'],))[0][0] >= 2)
        check('interrupted file retries with the same id', put(scene, ids[partial], big)[1].get('status') == 'AVAILABLE')
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
               AR_STORAGE_MAX_BYTES=str(4 * MIB), AR_STORAGE_SCENE_MAX_FILES='1000',
               AR_STORAGE_SCENE_MAX_BYTES=str(64 * MIB), AR_UPLOAD_DIR=str(run / 'framework-uploads'),
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
