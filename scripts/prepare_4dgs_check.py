"""Prepare or stop the isolated 4DGS acceptance instance (project innovation-ar-resource-platform-infra-check,
127.0.0.1:18082). Never touches the daily Compose project, config/compose.env, or the 18081 gateway.

prepare: private 0600 env/credentials in --report-dir, a Compose override pinning existing image IDs, the already
tested Jar and the handed-off frontend dist, `up --no-build --wait`, then real readiness checks. Writes runtime.json.
stop:    `docker compose stop` only; data, volumes and evidence stay. Never `down -v` or image pruning.
Credentials and tokens are never printed; Compose output goes to a private log, not the terminal.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import frontend_control
import harness
import prepare_compose

PROJECT = 'innovation-ar-resource-platform-infra-check'
HOST = '127.0.0.1'
PORT = 18082
BASE_URL = f'http://{HOST}:{PORT}'
ADMIN_BASE_URL = BASE_URL + '/prod-api'
LABEL = 'com.innovation-ar-resource-platform.4dgs-check'
BACKEND_TAG = 'innovation-ar-resource-platform-backend:infra-v1'
GATEWAY_TAG = 'innovation-ar-resource-platform-gateway:infra-v1'
TASK_TAGS = {'backend': 'innovation-ar-resource-platform-backend:4dgs-check',
             'gateway': 'innovation-ar-resource-platform-gateway:4dgs-check'}
ADMIN_USER = 'check_admin'
SERVICES = ('postgres', 'redis', 'backend', 'gateway')
NGINX_ANCHOR = '    location / {\n'
REFERENCE_MOUNT = '/srv/reference'
JFR_MOUNT = '/opt/jfr/file-io.jfc'
JFR_OPTIONS = ('-XX:StartFlightRecording=settings=' + JFR_MOUNT + ',filename=/app/.local/logs/backend-%p-%t.jfr,'
               'dumponexit=true,disk=true,maxsize=1g')
JFR_JFC = """<?xml version="1.0" encoding="UTF-8"?>
<configuration version="2.0" label="4dgs-file-io" description="File reads and writes only, no environment or property events">
  <event name="jdk.FileRead"><setting name="enabled">true</setting><setting name="stackTrace">true</setting><setting name="threshold">0 ms</setting></event>
  <event name="jdk.FileWrite"><setting name="enabled">true</setting><setting name="stackTrace">true</setting><setting name="threshold">0 ms</setting></event>
</configuration>
"""


class Blocked(Exception):
    """An environment or ownership condition that this tool must not override."""


def write_private(path, text, exclusive=False):
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(text)


def run(command, log=None, timeout=300, data=None):
    """Run a command; output is returned (or appended to a private log), never printed."""
    result = subprocess.run([str(part) for part in command], capture_output=True, timeout=timeout, input=data)
    if log is not None:
        with open(log, 'ab') as stream:
            stream.write(b'$ ' + ' '.join(str(part) for part in command[:6]).encode() + b'\n' + result.stdout + result.stderr)
    return result


def docker(*args, **kwargs):
    return run(['docker', *args], **kwargs)


class Instance:
    def __init__(self, report_dir):
        self.dir = report_dir
        self.env = report_dir / '4dgs-check.env'
        self.override = report_dir / 'compose.override.yaml'
        self.ownership = report_dir / 'ownership.json'
        self.credentials = report_dir / 'credentials.json'
        self.runtime = report_dir / 'runtime.json'
        self.nginx = report_dir / 'nginx.4dgs-check.conf'
        self.log = report_dir / 'prepare.log'
        self.jfr_dir = report_dir / 'jfr'
        self.jfc = self.jfr_dir / 'file-io.jfc'

    @property
    def compose(self):
        command = ['docker', 'compose', '-p', PROJECT, '--env-file', self.env, '-f', ROOT / 'compose.yaml']
        return command + (['-f', self.override] if self.override.exists() else [])

    def token(self):
        try:
            value = json.loads(self.ownership.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        return value['token'] if value.get('project') == PROJECT and value.get('root') == str(ROOT) else None


def project_resources():
    containers = docker('ps', '-a', '--filter', 'label=com.docker.compose.project=' + PROJECT, '--format', '{{.ID}}').stdout.decode().split()
    volumes = docker('volume', 'ls', '--filter', 'label=com.docker.compose.project=' + PROJECT, '--format', '{{.Name}}').stdout.decode().split()
    return containers, volumes


def labels(container):
    inspected = docker('inspect', '--format', '{{json .Config.Labels}}', container)
    return json.loads(inspected.stdout or b'{}') or {}


def require_ownership(instance, containers, volumes):
    """Every existing project resource must belong to this task's ownership token and working tree."""
    token = instance.token()
    if not (containers or volumes):
        return token
    if token is None:
        raise Blocked(f'Project {PROJECT} already has containers or volumes but this report directory does not own it; '
                      'not touching another task\'s resources.')
    for container in containers:
        found = labels(container)
        if found.get(LABEL) != token or found.get('com.docker.compose.project.working_dir') != str(ROOT):
            raise Blocked(f'Container {container[:12]} in {PROJECT} is not owned by this task; not touching it.')
    return token


def port_busy():
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex((HOST, PORT)) == 0


def image_id(tag):
    result = docker('image', 'inspect', '--format', '{{.Id}}', tag)
    return result.stdout.decode().strip() if result.returncode == 0 else None


def resolve_images(log):
    """Reuse the already built runtime images; build only task-specific tags if they are missing."""
    images = {}
    for service, tag in (('backend', BACKEND_TAG), ('gateway', GATEWAY_TAG)):
        found = image_id(tag)
        if found is None:
            task_tag = TASK_TAGS[service]
            found = image_id(task_tag)
            if found is None:
                built = docker('build', '-f', ROOT / 'deploy' / (service + '.Dockerfile'), '-t', task_tag, ROOT, log=log, timeout=3000)
                if built.returncode:
                    raise Blocked(f'{tag} is missing and building {task_tag} failed; see {log}')
                found = image_id(task_tag)
        images[service] = found
    return images


def world_readable(path):
    mode = path.stat().st_mode
    return mode & 0o004 and (not path.is_dir() or mode & 0o001)


def frontend_handoff(dist):
    """The dist must be exactly the content frontend_control recorded for its last passed build."""
    build = frontend_control.read_json(ROOT / '.local/frontend-control/build.json')
    actual = frontend_control.hash_files(dist)
    if build.get('status') != 'passed' or not actual or actual != build.get('output'):
        raise Blocked('--frontend-dist is not the output of the last passed scripts/frontend_control.py build; '
                      'run scripts/agent_check.py --profile frontend first.')
    if not (dist / 'index.html').is_file():
        raise Blocked('--frontend-dist has no index.html')
    return {'sha256': actual['sha256'], 'files': actual['files'], 'buildLog': build.get('log')}


def reference_csp(reference):
    """The CSP recorded by prepare_reference_viewer.py in the prepared copy; the gateway sends it as a header so it also
    binds workers (a meta tag in the page does not)."""
    marker = reference / '.prepared-reference-viewer.json'
    if not marker.is_file():
        raise Blocked(f'{reference} was not prepared by scripts/prepare_reference_viewer.py (no marker file)')
    csp = json.loads(marker.read_text(encoding='utf-8')).get('csp')
    if not csp or '"' in csp or '\n' in csp:
        raise Blocked(f'{marker} has no usable csp')
    return csp


def gateway_config(csp):
    """`csp` is None without a reference viewer (production gateway text unchanged), else the viewer CSP header value."""
    source = (ROOT / 'deploy/nginx.conf').read_text(encoding='utf-8')
    if not csp:
        return source
    if source.count(NGINX_ANCHOR) != 1:
        raise Blocked('deploy/nginx.conf no longer has the single catch-all location this overlay anchors on')
    isolation = ("        add_header X-Content-Type-Options nosniff always;\n"
                 "        add_header Cross-Origin-Opener-Policy same-origin always;\n"
                 "        add_header Cross-Origin-Embedder-Policy require-corp always;\n"
                 "        add_header Cross-Origin-Resource-Policy same-origin always;\n"
                 f'        add_header Content-Security-Policy "{csp}" always;\n')
    locations = (
        '    # Reference viewer overlay for isolated acceptance only; never part of the production gateway.\n'
        '    # Cross-origin isolation headers are what the player\'s shared-memory WASM needs (same as the reference server).\n'
        f'    location ~ "^/viewer/[0-9a-fA-F-]{{36}}$" {{\n        root {REFERENCE_MOUNT};\n        rewrite ^ /viewer/index.html break;\n{isolation}    }}\n'
        f'    location /viewer/ {{\n        root {REFERENCE_MOUNT};\n{isolation}    }}\n'
        f'    location ^~ /viewer-static/ {{\n        root {REFERENCE_MOUNT};\n{isolation}    }}\n\n')
    return source.replace(NGINX_ANCHOR, locations + NGINX_ANCHOR)


def bind(source, target):
    return {'type': 'bind', 'source': str(source), 'target': target, 'read_only': True}


def write_override(instance, images, jar, dist, reference, token):
    write_private(instance.nginx, gateway_config(reference_csp(reference) if reference else None))
    instance.jfr_dir.mkdir(exist_ok=True)
    instance.jfc.write_text(JFR_JFC, encoding='utf-8')
    instance.jfr_dir.chmod(0o755)
    instance.jfc.chmod(0o644)
    gateway_volumes = [bind(dist, '/usr/share/nginx/html'), bind(instance.nginx, '/etc/nginx/conf.d/default.conf')]
    if reference:
        gateway_volumes.append(bind(reference, REFERENCE_MOUNT))
    # Short file-I/O flight recording in the TEST backend only (JAVA_TOOL_OPTIONS), written to the backend_logs volume and
    # dumped on a normal stop. The healthcheck JVM must not inherit it or it would start a recording every probe.
    backend = {'image': images['backend'], 'labels': {LABEL: token}, 'volumes': [bind(jar, '/app/app.jar'), bind(instance.jfc, JFR_MOUNT)],
               'environment': {'JAVA_TOOL_OPTIONS': JFR_OPTIONS}, 'stop_grace_period': '90s',
               'healthcheck': {'test': ['CMD', 'env', '-u', 'JAVA_TOOL_OPTIONS', 'java', '-cp', '/opt/healthcheck', 'Healthcheck']}}
    override = {'services': {
        'postgres': {'labels': {LABEL: token}},
        'redis': {'labels': {LABEL: token}},
        'backend': backend,
        'gateway': {'image': images['gateway'], 'labels': {LABEL: token}, 'volumes': gateway_volumes}}}
    write_private(instance.override, json.dumps(override, indent=2) + '\n')


def http(path, method='GET', body=None, token=None, timeout=15):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(BASE_URL + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, content = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, content = error.code, error.read()
    try:
        return status, json.loads(content or b'{}')
    except ValueError:
        return status, {}


def wait_for_gateway(deadline=120):
    until = time.monotonic() + deadline
    while time.monotonic() < until:
        try:
            health = urllib.request.urlopen(BASE_URL + '/healthz', timeout=5)
            health.close()
            status, body = http('/prod-api/captchaImage')
            if health.status == 200 and status == 200 and body.get('code') == 200:
                return
        except OSError:
            pass
        time.sleep(2)
    raise Blocked('Gateway /healthz or /prod-api/captchaImage did not answer with business code 200')


def login(username, password):
    status, body = http('/prod-api/login', 'POST', {'username': username, 'password': password})
    return body.get('token') if status == 200 and body.get('code') == 200 else None


def ensure_admin(instance, env):
    """check_admin is created once through the normal account API (which retires bootstrap); afterwards only its
    saved credentials are used. Never re-enables bootstrap or mints sessions."""
    try:
        write_private(instance.credentials, json.dumps({'username': ADMIN_USER, 'password': secrets.token_urlsafe(24)}) + '\n',
                      exclusive=True)
    except FileExistsError:
        pass
    saved = json.loads(instance.credentials.read_text(encoding='utf-8'))
    if login(saved['username'], saved['password']):
        return
    bootstrap = login('bootstrap', env['AR_BOOTSTRAP_PASSWORD'])
    if not bootstrap:
        raise Blocked(f'{ADMIN_USER} credentials do not match and bootstrap is retired; not resetting the account.')
    status, body = http('/prod-api/system/user', 'POST',
                        {'userName': saved['username'], 'nickName': 'infra check admin', 'password': saved['password']}, bootstrap)
    if status != 200 or body.get('code') != 200 or not login(saved['username'], saved['password']):
        raise Blocked(f'Creating {ADMIN_USER} failed (HTTP {status}, code {body.get("code")}).')


def compose_ps(instance):
    output = run([*instance.compose, 'ps', '--all', '--format', 'json']).stdout.decode().strip()
    if not output:
        return []
    if output.startswith('['):
        return json.loads(output)
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def verify_running(instance, jar_sha256):
    states = {row['Service']: row for row in compose_ps(instance)}
    for service in SERVICES:
        health = states.get(service, {}).get('Health')
        if health != 'healthy':
            raise Blocked(f'Service {service} is not healthy (state {health or states.get(service, {}).get("State")})')
    version = run([*instance.compose, 'exec', '-T', 'postgres', 'psql', '-U', 'innovation', '-d', 'innovation_ar_resource_platform',
                   '-Atc', 'select version()']).stdout.decode().strip()
    if not version.startswith('PostgreSQL 17.6'):
        raise Blocked('PostgreSQL is not 17.6: ' + version[:60])
    mounted = run([*instance.compose, 'exec', '-T', 'backend', 'sha256sum', '/app/app.jar']).stdout.decode().split()
    if not mounted or mounted[0] != jar_sha256:
        raise Blocked('The backend is not running the Jar passed to --jar')
    return version


def prepare(args):
    report_dir = args.report_dir.resolve()
    if not report_dir.is_relative_to(ROOT / '.local'):
        raise Blocked('--report-dir must be inside this worktree\'s .local directory')
    if args.jar is None or args.frontend_dist is None:
        raise Blocked('prepare requires --jar and --frontend-dist')
    jar, dist = args.jar.resolve(), args.frontend_dist.resolve()
    reference = args.reference_viewer.resolve() if args.reference_viewer else None
    for path, kind in ((jar, 'file'), (dist, 'dir'), (reference, 'dir')):
        if path is not None and not (path.is_file() if kind == 'file' else path.is_dir()):
            raise Blocked(f'{path} does not exist')
        if path is not None and not world_readable(path):
            raise Blocked(f'{path} must be world-readable for the unprivileged container user')
    report_dir.mkdir(parents=True, exist_ok=True)
    report_dir.chmod(0o700)
    instance = Instance(report_dir)
    containers, volumes = project_resources()
    token = require_ownership(instance, containers, volumes)
    if not containers and port_busy():
        raise Blocked(f'{HOST}:{PORT} is already in use by something else; not stopping it.')
    if token is None:
        token = uuid.uuid4().hex
        write_private(instance.ownership, json.dumps({'project': PROJECT, 'root': str(ROOT), 'token': token,
                                                       'createdAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}) + '\n',
                      exclusive=True)
    if not instance.env.exists():
        if volumes:
            raise Blocked('Project volumes exist but the private env file is missing; its database password is lost.')
        prepare_compose.create_environment_file(instance.env, prepare_compose.environment_values(
            1073741824, 1000, 4294967296, HOST, PORT))
    env = dict(line.split('=', 1) for line in instance.env.read_text(encoding='utf-8').splitlines() if line)
    if env.get('AR_BIND_ADDRESS') != HOST or env.get('AR_HTTP_PORT') != str(PORT):
        raise Blocked('The private env file does not bind the fixed 127.0.0.1:18082 address')
    handoff = frontend_handoff(dist)
    jar_sha256 = hashlib.sha256(jar.read_bytes()).hexdigest()
    images = resolve_images(instance.log)
    write_override(instance, images, jar, dist, reference, token)
    if run([*instance.compose, 'config', '--quiet'], instance.log).returncode:
        raise Blocked(f'Compose configuration is invalid; see {instance.log}')
    up = run([*instance.compose, 'up', '--no-build', '-d', '--wait', '--wait-timeout', '180'], instance.log, timeout=300)
    if up.returncode:
        raise Blocked(f'docker compose up failed; see {instance.log}')
    # The gateway is stateless and its bind mounts (nginx config, dist, reference viewer) are rewritten files/directories
    # on every prepare; a running container would keep serving the replaced inodes. Recreate it so it sees the new ones.
    gateway = run([*instance.compose, 'up', '--no-build', '-d', '--wait', '--wait-timeout', '120', '--no-deps', '--force-recreate', 'gateway'],
                  instance.log, timeout=200)
    if gateway.returncode:
        raise Blocked(f'recreating the gateway failed; see {instance.log}')
    wait_for_gateway()
    version = verify_running(instance, jar_sha256)
    ensure_admin(instance, env)
    runtime = {
        'baseUrl': BASE_URL, 'adminBaseUrl': ADMIN_BASE_URL, 'credentialsFile': str(instance.credentials),
        'project': PROJECT, 'compose': [str(part) for part in instance.compose], 'envFile': str(instance.env),
        'jar': str(jar), 'jarSha256': jar_sha256, 'frontendDist': {'path': str(dist), **handoff},
        'referenceViewer': str(reference) if reference else None, 'imageIds': images, 'postgres': version,
        'source': harness.source_identity(ROOT), 'runDirectory': str(instance.dir),
        'jfr': {'jfc': str(instance.jfc), 'containerDirectory': '/app/.local/logs', 'filePattern': 'backend-<pid>-<timestamp>.jfr',
                'events': ['jdk.FileRead', 'jdk.FileWrite']},
        'limits': {key: int(env[key]) for key in ('AR_STORAGE_MAX_BYTES', 'AR_STORAGE_VERSION_MAX_FILES', 'AR_STORAGE_VERSION_MAX_BYTES')},
        'stopCommand': [sys.executable, str(Path(__file__).resolve()), 'stop', '--report-dir', str(instance.dir)]}
    write_private(instance.runtime, json.dumps(runtime, ensure_ascii=False, indent=2) + '\n')
    print('READY ' + BASE_URL + '  runtime=' + str(instance.runtime))


def stop(args):
    report_dir = args.report_dir.resolve()
    instance = Instance(report_dir)
    containers, volumes = project_resources()
    require_ownership(instance, containers, volumes)
    if not containers:
        print('Nothing to stop: no containers for ' + PROJECT)
        return
    if not instance.env.exists():
        raise Blocked('The private env file is missing; cannot address this project safely.')
    result = run([*instance.compose, 'stop'], instance.log, timeout=300)
    if result.returncode:
        raise Blocked(f'docker compose stop failed; see {instance.log}')
    print('STOPPED ' + PROJECT + '; volumes and evidence kept')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=('prepare', 'stop'))
    parser.add_argument('--report-dir', type=Path, required=True, help='Private directory under .local for env, credentials and runtime.json')
    parser.add_argument('--jar', type=Path, help='prepare: the Jar produced by scripts/check_java.py --package')
    parser.add_argument('--frontend-dist', type=Path, help='prepare: dist built through scripts/frontend_control.py')
    parser.add_argument('--reference-viewer', type=Path, help='prepare: optional prepared reference viewer directory (viewer/, viewer-static/)')
    args = parser.parse_args(argv)
    try:
        (prepare if args.action == 'prepare' else stop)(args)
    except Blocked as exc:
        print('BLOCKED: ' + str(exc), file=sys.stderr)
        return 2
    except (OSError, subprocess.SubprocessError, frontend_control.Blocked) as exc:
        print('BLOCKED: ' + type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
