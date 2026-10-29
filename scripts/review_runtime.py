"""Disposable Windows PostgreSQL/Redis/Java runtime, owned by its foreground parent."""
import json
import hashlib
import os
from pathlib import Path
import secrets
import socket
import sys
import subprocess
import time
import urllib.error
import urllib.request
import uuid


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def request(base, path, method='GET', body=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None
    if isinstance(body, bytes):
        headers['Content-Type'] = 'application/octet-stream'
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        response = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        content = response.read()
        return response.status, json.loads(content) if content else {}


class Runtime:
    def __init__(self, source, resources, directory, jar, password=None):
        if os.name != 'nt':
            raise RuntimeError('HTTP preview runtime currently requires Windows')
        self.source, self.directory, self.jar = source, directory, jar
        self.resources = resources
        self.pg = resources / '.local/postgresql17/pgsql/bin'
        self.java = next((resources / '.local/java21').glob('jdk*/bin/java.exe'))
        self.directory.mkdir(parents=True, exist_ok=False)
        self.processes, self.logs = [], []
        self.pg_started = False
        self.password = password or secrets.token_urlsafe(18)
        ports = set()
        while len(ports) < 4:
            ports.add(free_port())
        self.pg_port, redis, api, web = sorted(ports)
        self.base, self.web = f'http://127.0.0.1:{api}', f'http://127.0.0.1:{web}'
        self.web_port = web
        db_password = secrets.token_urlsafe(24)
        # All service-related variables are explicitly scoped to this new runtime.
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('AR_')}
        self.env.update(AR_DATABASE_URL=f'jdbc:postgresql://127.0.0.1:{self.pg_port}/review',
                        AR_DATABASE_USER='review', AR_DATABASE_PASSWORD=db_password,
                        AR_TOKEN_SECRET=secrets.token_urlsafe(64), AR_BOOTSTRAP_PASSWORD=self.password,
                        AR_REDIS_HOST='127.0.0.1', AR_REDIS_PORT=str(redis), AR_PORT=str(api),
                        AR_STORAGE_ENABLED='true', AR_STORAGE_ROOT=str(directory / 'artifacts'),
                        AR_STORAGE_MAX_BYTES=str(256 * 1024 * 1024),
                        AR_UPLOAD_DIR=str(directory / 'uploads'), AR_DEV_API_TARGET=self.base,
                        PGPASSWORD=db_password)
        self.redis_port = redis

    def command(self, args):
        with (self.directory / 'commands.log').open('ab') as log:
            subprocess.run([str(a) for a in args], env=self.env, cwd=self.directory,
                           stdout=log, stderr=log, check=True, timeout=90,
                           creationflags=subprocess.CREATE_NO_WINDOW)

    def start(self, name, args, cwd=None):
        log = (self.directory / (name + '.log')).open('ab')
        self.logs.append(log)
        process = subprocess.Popen([str(a) for a in args], env=self.env, cwd=cwd or self.directory,
                                   stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        self.processes.append(process)
        return process

    def __enter__(self):
        try:
            version = subprocess.check_output([str(self.pg / 'postgres.exe'), '--version'], text=True)
            if ' 17.' not in version:
                raise RuntimeError('PostgreSQL 17 required')
            self.pg_version = version.strip()
            pw = self.directory / 'init-password'
            pw.write_text(self.env['AR_DATABASE_PASSWORD'], encoding='ascii')
            try:
                self.command([self.pg / 'initdb.exe', '-D', self.directory / 'pgdata', '-U', 'review',
                              '--pwfile=' + str(pw), '--auth=scram-sha-256', '--encoding=UTF8', '--locale=C'])
            finally:
                pw.unlink(missing_ok=True)
            # Set before launch so cleanup also handles a partially successful pg_ctl.
            self.pg_started = True
            self.command([self.pg / 'pg_ctl.exe', '-D', self.directory / 'pgdata', '-l',
                          self.directory / 'postgres.log', '-o', f'-h 127.0.0.1 -p {self.pg_port}', '-w', 'start'])
            self.command([self.pg / 'createdb.exe', '-h', '127.0.0.1', '-p', self.pg_port, '-U', 'review', 'review'])
            self.start('redis', ['redis-server', '--bind', '127.0.0.1', '--port', self.redis_port,
                                 '--save', '', '--appendonly', 'no'])
            backend = self.start('backend', [self.java, '-Duser.timezone=UTC', '-jar', self.jar,
                                              '--server.address=127.0.0.1'])
            until = time.monotonic() + 120
            while time.monotonic() < until:
                if backend.poll() is not None:
                    raise RuntimeError('Backend exited; inspect isolated backend.log')
                try:
                    if request(self.base, '/captchaImage')[0] == 200:
                        return self
                except (OSError, ValueError):
                    pass
                time.sleep(.3)
            raise RuntimeError('Backend startup timeout')
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def frontend(self):
        frontend = self.start('frontend', ['node', self.source / 'frontend/node_modules/vite/bin/vite.js',
                                           '--host', '127.0.0.1', '--port', self.web_port, '--strictPort'],
                              self.source / 'frontend')
        until = time.monotonic() + 60
        while time.monotonic() < until:
            if frontend.poll() is not None:
                raise RuntimeError('Vite exited; inspect isolated frontend.log')
            try:
                with urllib.request.urlopen(self.web, timeout=5) as response:
                    html = response.read().decode()
                if '/src/main' in html and request(self.web, '/dev-api/captchaImage')[0] == 200:
                    return
            except (OSError, ValueError):
                pass
            time.sleep(.3)
        raise RuntimeError('Frontend/proxy startup timeout')

    def __exit__(self, *args):
        for process in reversed(self.processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        try:
            if self.pg_started and (self.directory / 'pgdata/postmaster.pid').exists():
                self.command([self.pg / 'pg_ctl.exe', '-D', self.directory / 'pgdata', '-m', 'fast', '-w', 'stop'])
        finally:
            for log in self.logs:
                log.close()


def account_smoke(runtime):
    """Real HTTP flow: 6-char bootstrap first, then create/reset/change and revoked sessions."""
    checks = []

    def check(name, condition):
        checks.append({'name': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)

    def api(path, method='GET', body=None, token=None):
        status, result = request(runtime.base, path, method, body, token)
        return status, result

    def login(user, password):
        status, body = api('/login', 'POST', {'username': user, 'password': password})
        check('login ' + user, status == 200 and body.get('code') == 200 and bool(body.get('token')))
        return body['token']

    def valid(token):
        status, body = api('/getInfo', token=token)
        return status == 200 and body.get('code') == 200

    def reject(result, name):
        status, body = result
        check(name, (status != 200 or body.get('code') != 200) and '6–64' in body.get('msg', ''))

    admin = login('bootstrap', runtime.password)  # Fail fast: this caught PR #8's original defect.
    for size in (5, 65, 6, 64):
        result = api('/system/user', 'POST', {'userName': f'review_{size}', 'nickName': 'Review',
                                             'password': 'a' * size}, admin)
        if size in (5, 65):
            reject(result, f'create rejects {size}')
        else:
            check(f'create accepts {size}', result[0] == 200 and result[1].get('code') == 200)
            created = login(f'review_{size}', 'a' * size)
            if size == 6:
                admin = created  # First account retires bootstrap; never re-enable it.
    rows = api('/system/user/list', token=admin)[1]['rows']
    check('invalid creates leave no accounts', not any(r['userName'] in ('review_5', 'review_65') for r in rows))
    target_id = next(row['userId'] for row in rows if row['userName'] == 'review_64')
    password = 'a' * 64
    for operation in ('reset', 'own'):
        for size in (5, 65, 6, 64):
            old = [login('review_64', password), login('review_64', password)]
            new = ('b' if operation == 'reset' else 'c') * size
            if operation == 'reset':
                result = api('/system/user/resetPwd', 'PUT', {'userId': target_id, 'password': new}, admin)
            else:
                result = api('/system/user/profile/updatePwd', 'PUT',
                             {'oldPassword': password, 'newPassword': new}, old[0])
            if size in (5, 65):
                reject(result, f'{operation} rejects {size}')
                check(f'{operation} failure preserves sessions {size}', all(valid(t) for t in old))
                login('review_64', password)
            else:
                check(f'{operation} accepts {size}', result[0] == 200 and result[1].get('code') == 200)
                check(f'{operation} revokes both sessions {size}', all(not valid(t) for t in old))
                password = new
                login('review_64', password)
    return checks


def seed_preview(runtime):
    """Populate only the newly created runtime through authenticated business APIs."""
    def api(path, method='GET', body=None, token=None):
        status, result = request(runtime.base, path, method, body, token)
        if status not in (200, 201) or result.get('code', 200) != 200:
            raise RuntimeError('Synthetic fixture API failed: ' + path)
        return result
    token = api('/login', 'POST', {'username': 'bootstrap', 'password': runtime.password})['token']
    user = 'review_admin'
    api('/system/user', 'POST', {'userName': user, 'nickName': '隔离验收账号', 'password': runtime.password}, token)
    token = api('/login', 'POST', {'username': user, 'password': runtime.password})['token']
    fixtures = {'username': user, 'scenes': []}
    for index, name in enumerate(['验收场景A', '超长场景名称' + '测试内容' * 25]):
        scene = api('/api/v1/scenes', 'POST', {'name': name}, token)
        draft = api('/api/v1/scenes/' + scene['id'] + '/drafts', 'POST',
                    {'requestKey': str(uuid.uuid4()), 'description': '人工验收用合成版本'}, token)
        payload = '这是隔离验收文件，不是真实客户端资源。'.encode('utf-8')
        path = '/api/v1/drafts/' + draft['id'] + '/files'
        file = api(path, 'POST', {'requestKey': str(uuid.uuid4()), 'fileName': '验收示例.txt',
                                  'kind': 'RESOURCE_FILE', 'bytes': len(payload),
                                  'sha256': hashlib.sha256(payload).hexdigest()}, token)
        uploaded = api(path + '/' + file['id'] + '/content', 'PUT', payload, token)
        if uploaded.get('status') != 'AVAILABLE':
            raise RuntimeError('Synthetic payload was not verified')
        fixtures['scenes'].append({'id': scene['id'], 'name': name, 'draftId': draft['id'], 'fileId': file['id']})
    (runtime.directory / 'fixtures.json').write_text(json.dumps(fixtures, ensure_ascii=False, indent=2), encoding='utf-8')
    return fixtures


def browser_smoke(runtime, fixtures):
    """Real Edge login, scene/detail navigation and frontend proxy, no mocked responses."""
    sys.path.insert(0, str(runtime.resources / '.local/python'))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='msedge', headless=True)
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 1050})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(runtime.web + '/login', wait_until='networkidle', timeout=90000)
            page.get_by_placeholder('账号').fill(fixtures['username'])
            page.get_by_placeholder('密码').fill(runtime.password)
            page.get_by_role('button', name='登 录').click()
            page.wait_for_url(lambda url: '/login' not in url, timeout=30000)
            page.goto(runtime.web + '/admin/scenes', wait_until='networkidle', timeout=90000)
            row = page.get_by_role('row').filter(has_text=fixtures['scenes'][0]['name'])
            row.get_by_role('button', name='场景信息', exact=True).click()
            dialog = page.get_by_role('dialog', name='场景信息')
            dialog.wait_for()
            dialog.locator('.el-dialog__footer').get_by_role('button', name='关闭', exact=True).click()
            dialog.wait_for(state='hidden')
            row.get_by_role('button', name='版本与文件', exact=True).click()
            page.get_by_role('heading', name='内容版本草稿 · ' + fixtures['scenes'][0]['name']).wait_for()
            page.screenshot(path=str(runtime.directory / 'real-browser.png'), full_page=True)
            if errors:
                raise RuntimeError('Browser page errors; inspect isolated browser evidence')
            return [{'name': 'real login, scene information and corresponding draft panel', 'passed': True}]
        finally:
            browser.close()
