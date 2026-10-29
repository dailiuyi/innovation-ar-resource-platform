"""Container checks against ONLY innovation-ar-resource-platform-infra-check on loopback:18082.

Creates synthetic data in the isolated test project. --recreate also recreates its
containers to check named volumes. Never points at the existing local Demo.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / 'config/compose-test.env'
COMPOSE = ['docker', 'compose', '-p', 'innovation-ar-resource-platform-infra-check', '--env-file', str(ENV_FILE),
           '-f', str(ROOT / 'compose.yaml')]
BASE = 'http://127.0.0.1:18082'
checks = []


def check(name, condition):
    checks.append({'name': name, 'passed': bool(condition)})
    if not condition:
        raise AssertionError(name)
    print('PASS', name, flush=True)


def command(args, data=None):
    result = subprocess.run(COMPOSE + args, input=data, capture_output=True)
    if result.returncode:
        # Never print command output: resolved Compose configuration contains secrets.
        raise RuntimeError('Compose command failed: ' + args[0])
    return result.stdout


def request(path, method='GET', body=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def wait_ready():
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            status, body = request('/prod-api/captchaImage')
            if status == 200 and json.loads(body).get('code') == 200:
                return
        except (OSError, ValueError):
            pass
        time.sleep(2)
    raise RuntimeError('Isolated test stack did not become ready')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recreate', action='store_true')
    args = parser.parse_args()
    settings = dict(line.split('=', 1) for line in ENV_FILE.read_text().splitlines()
                    if line and not line.startswith('#'))
    check('test config uses loopback and isolated port',
          settings.get('AR_BIND_ADDRESS') == '127.0.0.1' and settings.get('AR_HTTP_PORT') == '18082')
    config = json.loads(command(['config', '--format', 'json']))
    services = config['services']
    check('resolved gateway stays on isolated loopback port', all(
        port.get('host_ip') == '127.0.0.1' and str(port.get('published')) == '18082'
        for port in services['gateway']['ports']))
    check('only gateway exposes host ports', all(not value.get('ports') for key, value in services.items() if key != 'gateway'))
    check('service network is internal', config['networks']['services'].get('internal') is True)
    check('Redis session data uses tmpfs', '/data' in services['redis'].get('tmpfs', []))
    check('gateway has no artifact volume', not services['gateway'].get('volumes'))
    check('database and artifacts use named volumes',
          all(volume['type'] == 'volume' for name in ('backend', 'postgres') for volume in services[name]['volumes']))
    check('backend is not root', command(['exec', '-T', 'backend', 'id', '-u']).strip() == b'10001')
    command(['exec', '-T', 'gateway', 'nginx', '-t'])
    check('nginx configuration loads', True)
    wait_ready()
    check('frontend served', request('/')[0] == 200)
    check('scene API requires login', request('/prod-api/api/v1/scenes')[0] == 401)
    for path in ('/artifacts/file.bin', '/_artifacts/file.bin', '/staging/file.part', '/committed/file.bin', '/data/artifacts/file.bin', '/.env'):
        check('private path blocked ' + path, request(path)[0] == 404)
    check('framework upload remains disabled', request('/prod-api/common/upload', 'POST', {})[0] in (401, 403))

    def login():
        status, body = request('/prod-api/login', 'POST', {'username': 'bootstrap', 'password': settings['AR_BOOTSTRAP_PASSWORD']})
        token = json.loads(body).get('token')
        check('isolated bootstrap login', status == 200 and bool(token))
        return token

    token = login()
    name = 'infra-' + str(uuid.uuid4())
    status, body = request('/prod-api/api/v1/scenes', 'POST', {'name': name}, token)
    scene = json.loads(body)
    check('scene write through proxy', status == 201 and scene.get('name') == name)
    scene_id = scene['id']

    # Only writes known synthetic fixture paths in this isolated project's artifact volume.
    fixture = b'innovation infrastructure persistence check\n'
    fixture_name = '00000000-0000-0000-0000-000000000001.bin'
    command(['exec', '-T', 'backend', 'sh', '-c',
             'umask 077; cat > /data/artifacts/committed/.infra-check-new; '
             'ln /data/artifacts/committed/.infra-check-new /data/artifacts/committed/.infra-check-link && '
             'rm /data/artifacts/committed/.infra-check-link && '
             'mv /data/artifacts/committed/.infra-check-new /data/artifacts/committed/' + fixture_name], fixture)
    check('artifact volume supports hard links', True)
    if args.recreate:
        command(['up', '-d', '--no-build', '--force-recreate'])
        wait_ready()
        token = login()
        status, body = request('/prod-api/api/v1/scenes/' + scene_id, token=token)
        check('database survives container recreation', status == 200 and json.loads(body).get('name') == name)
        actual = command(['exec', '-T', 'backend', 'cat', '/data/artifacts/committed/' + fixture_name])
        check('artifact bytes survive container recreation', hashlib.sha256(actual).digest() == hashlib.sha256(fixture).digest())
    report = {
        'stage': 'infrastructure', 'project': 'innovation-ar-resource-platform-infra-check',
        'containerRecreationTested': args.recreate, 'checks': checks,
        'limitations': ['No real artifact/client contract', 'No upload/publication/download APIs',
                        'No real disk-full or power-loss test', 'No physical Linux host migration'],
    }
    (ROOT / 'docs/validation-infrastructure.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
