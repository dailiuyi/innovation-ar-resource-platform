"""Stage 5 acceptance on the isolated 4DGS instance (project innovation-ar-resource-platform-infra-check, 127.0.0.1:18082).

Real sample packages are imported through scripts/import_scene_package.py, published, read anonymously (catalogue,
description, Range, full bytes vs the source files) and downloaded per variant with scripts/download_scene.py. A file-I/O
JFR recording of the TEST backend (jdk.FileRead/jdk.FileWrite, started by prepare_4dgs_check.py through
JAVA_TOOL_OPTIONS) is dumped on each normal backend stop, copied out with docker cp, exported to JSON by the Java 21
tool image and attributed to request windows, to show where model bytes are (not) read. Browser playback of the
reference viewer runs only when --viewer-root really contains the fixed build; otherwise it is reported BLOCKED with
the missing paths (nothing is fabricated or substituted).

Accepts only the fixed test runtime (project, 127.0.0.1:18082); never the daily instance. Reports go to --report-dir.
Exit codes: 0 all executed checks passed and nothing blocked, 1 a check failed, 2 unusable input/runtime,
4 all executed checks passed but items are BLOCKED (see "blocked" in the report).
"""
import argparse
import datetime
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import download_scene
import import_scene_package
import verify_ingestion

PROJECT = 'innovation-ar-resource-platform-infra-check'
HOST, PORT = '127.0.0.1', 18082
BASE = f'http://{HOST}:{PORT}'
TOOL_IMAGE = 'innovation-ar-resource-platform-java-check:4dgs'
SCENES = ('wedding', 'dance_color', 'shiku_dtwd')
DOWNLOADS = (('wedding', 'standard_quality'), ('dance_color', 'standard_quality'))
PLAYBACK = (('wedding', 'standard_quality', False), ('wedding', 'high_quality', False), ('dance_color', 'standard_quality', True))
VIEWER_FILES = ('viewer/index.html', 'viewer/platform.html', 'viewer/20261016/230726/js/D8TV3hLS.js',
                'viewer/20261016/230726/js/Drq6wweV.js', 'viewer/20261016/230726/js/DfIBC3Nc.js')
# The reference source has no service worker and no font files; these requests 404 on the platform gateway by design of the source.
KNOWN_MISSING_PATHS = ('/viewer/sw.js', '/viewer-static/Gineso-ConMed.png', '/viewer-static/Gineso-ConMed.json')
GIB = 1024 ** 3
STORAGE = ('/data/artifacts/staging/', '/data/artifacts/committed/')
UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


class Report:
    def __init__(self):
        self.checks, self.blocked, self.data = [], [], {}
        self.failed = False

    def check(self, name, condition, detail=''):
        self.checks.append({'name': name, 'passed': bool(condition), 'detail': '' if condition else str(detail)[:800]})
        print(('PASS ' if condition else 'FAIL ') + name + ('' if condition else '  ' + str(detail)[:300]), flush=True)
        if not condition:
            self.failed = True
        return bool(condition)

    def block(self, item, reason, **extra):
        self.blocked.append({'item': item, 'reason': reason, **extra})
        print('BLOCKED ' + item + ': ' + reason, flush=True)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        while block := stream.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def utc(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


class Anonymous:
    """Anonymous client reads through the gateway; never sends Authorization."""

    def request(self, method, path, headers=None, hash_body=False):
        connection = http.client.HTTPConnection(HOST, PORT, timeout=300)
        try:
            begin = time.monotonic()
            connection.request(method, path, headers={'Accept-Encoding': 'identity', **(headers or {})})
            response = connection.getresponse()
            digest, count, body = hashlib.sha256(), 0, bytearray()
            while block := response.read(1 << 20):
                count += len(block)
                if hash_body:
                    digest.update(block)
                else:
                    body += block
            return {'status': response.status, 'headers': {k.lower(): v for k, v in response.getheaders()}, 'bytes': count,
                    'sha256': digest.hexdigest() if hash_body else None, 'body': bytes(body), 'seconds': time.monotonic() - begin}
        finally:
            connection.close()

    def json(self, path):
        result = self.request('GET', path)
        return result['status'], (json.loads(result['body']) if result['body'] else None), result['seconds']


class Instance:
    def __init__(self, runtime):
        self.runtime = runtime
        self.compose = runtime['compose']

    def run(self, *args, timeout=600, check=True, stdout=None):
        result = subprocess.run([*self.compose, *args], capture_output=stdout is None, stdout=stdout, text=stdout is None, timeout=timeout)
        if check and result.returncode:
            raise RuntimeError('compose ' + ' '.join(args) + ' failed: ' + (result.stderr or '')[-400:])
        return result

    def container(self, service):
        return self.run('ps', '-a', '-q', service).stdout.strip()

    def psql(self, sql):
        result = self.run('exec', '-T', 'postgres', 'psql', '-U', 'innovation', '-d', 'innovation_ar_resource_platform', '-At', '-c', sql)
        return result.stdout.strip()

    def wait_ready(self, seconds=240):
        anonymous, until = Anonymous(), time.monotonic() + seconds
        restarted_gateway = False
        while time.monotonic() < until:
            try:
                if anonymous.request('GET', '/api/v1/client/scenes?limit=1')['status'] == 200:
                    return
            except OSError:
                pass
            if not restarted_gateway and time.monotonic() > until - seconds + 45:
                self.run('restart', 'gateway')  # nginx may hold the stopped backend's old address
                restarted_gateway = True
            time.sleep(2)
        raise RuntimeError('backend did not become ready through the gateway')

    def restart_backend(self):
        """Normal stop (SIGTERM, JFR dumponexit), copy out the recording, start again. Returns the local JFR path."""
        container = self.container('backend')
        self.run('stop', 'backend', timeout=300)
        return container

    def start_backend(self):
        self.run('start', 'backend')
        self.wait_ready()


LOG_LINE = re.compile(r'\[(\d\d/\w{3}/\d{4}:\d\d:\d\d:\d\d) \+0000\] "GET (/api/v1/client/scenes/([0-9a-f-]{36})/[^ ]*/files/([0-9a-f-]{36})/content/[^ ]+) HTTP/1\.1" (\d{3}) (\d+)')


def gateway_gets(text, scene_id, begin, end):
    """(path, fileId, status, bytes) for GET content lines of one scene whose whole-second log time lies in [begin, end]."""
    rows = []
    for match in LOG_LINE.finditer(text):
        stamp = datetime.datetime.strptime(match.group(1), '%d/%b/%Y:%H:%M:%S').replace(tzinfo=datetime.timezone.utc).timestamp()
        if match.group(3) == scene_id and int(begin) <= stamp <= end + 1:
            rows.append((match.group(2), match.group(4), match.group(5), match.group(6)))
    return rows


def disk_free():
    return shutil.disk_usage(ROOT).free


# ---- JFR ------------------------------------------------------------------------------------------------

def parse_time(text):
    match = re.match(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:\d\d)', text)
    base = datetime.datetime.fromisoformat(match.group(1) + (match.group(3).replace('Z', '+00:00')))
    return base.timestamp() + (float('0' + match.group(2)) if match.group(2) else 0.0)


JSON_FILTER = r"""
import json, sys
STORAGE = ('/data/artifacts/staging/', '/data/artifacts/committed/')
decoder, stream, out = json.JSONDecoder(), sys.stdin, sys.stdout
buf, pos, started = '', 0, False
while True:
    chunk = stream.read(1 << 20)
    buf += chunk
    if not started:
        mark = buf.find('"events"')
        bracket = buf.find('[', mark) if mark >= 0 else -1
        if bracket < 0:
            if not chunk:
                break
            continue
        pos, started = bracket + 1, True
    while True:
        while pos < len(buf) and buf[pos] in ' \n\r\t,':
            pos += 1
        if pos >= len(buf) or buf[pos] == ']':
            break
        try:
            event, pos = decoder.raw_decode(buf, pos)
        except ValueError:
            break
        values = event['values']
        path = values.get('path') or ''
        if path.startswith(STORAGE):
            read = event['type'] == 'jdk.FileRead'
            out.write(json.dumps({'t': values['startTime'], 'read': read, 'path': path,
                                  'bytes': max(0, values.get('bytesRead' if read else 'bytesWritten') or 0)}) + '\n')
    if pos > (4 << 20):
        buf, pos = buf[pos:], 0
    if not chunk:
        break
"""

TEXT_FILTER = r"""
import collections, json, re, sys
STORAGE = ('/data/artifacts/staging/', '/data/artifacts/committed/')
reads, writes, verify = 0, 0, 0
frames = collections.Counter()
current = None
for line in sys.stdin:
    if line.startswith('jdk.File'):
        current = {'read': line.startswith('jdk.FileRead'), 'path': '', 'frames': [], 'in': False}
    elif current is None:
        continue
    elif line.startswith('}'):
        if current['path'].startswith(STORAGE):
            if current['read']:
                reads += 1
                if any('verify' in f.lower() for f in current['frames']):
                    verify += 1
                for f in current['frames']:
                    if f.startswith('com.ruoyi'):
                        frames[f] += 1
            else:
                writes += 1
        current = None
    elif line.strip().startswith('path = '):
        quoted = re.search(r'"(.*)"', line)
        current['path'] = quoted.group(1) if quoted else ''
    elif line.strip().startswith('stackTrace = ['):
        current['in'] = True
    elif current['in']:
        if line.strip() == ']':
            current['in'] = False
        elif line.strip() != '...':
            current['frames'].append(line.strip())
print(json.dumps({'storageReadEvents': reads, 'storageWriteEvents': writes, 'storageReadEventsWithVerifyFrame': verify,
                  'ruoyiFramesInStorageReadStacks': dict(frames.most_common(12))}))
"""


def export_jfr(container, destination, tool_user):
    """docker cp the recordings of a stopped backend; exact per-event byte counts come from `jfr print --json` (stack
    depth 1, filtered to the storage directories inside the tool container so no huge JSON is written), the stack
    evidence from `jfr print` text with 24 frames filtered the same way."""
    destination.mkdir(parents=True, exist_ok=True)
    cp = subprocess.run(['docker', 'cp', f'{container}:/app/.local/logs/.', str(destination)], capture_output=True, text=True)
    if cp.returncode:
        raise RuntimeError('docker cp failed: ' + cp.stderr[-300:])
    recordings = [p for p in sorted(destination.glob('backend-*.jfr'), key=lambda p: p.stat().st_mtime) if p.stat().st_size > 0]
    if not recordings:
        raise RuntimeError('no non-empty JFR recording was dumped')
    latest = recordings[-1]
    (destination / 'filter_json.py').write_text(JSON_FILTER, encoding='utf-8')
    (destination / 'filter_text.py').write_text(TEXT_FILTER, encoding='utf-8')

    def tool(command):
        result = subprocess.run(['docker', 'run', '--rm', '--user', tool_user, '-e', 'HOME=/tmp', '-v', f'{destination}:/data:ro', TOOL_IMAGE, 'sh', '-c', command],
                                capture_output=True, text=True, timeout=1800)
        if result.returncode:
            raise RuntimeError('jfr export failed: ' + result.stderr[-300:])
        return result.stdout
    lines = tool(f'jfr print --json --events jdk.FileRead,jdk.FileWrite --stack-depth 1 /data/{latest.name} | python3 /data/filter_json.py')
    events = []
    for line in lines.splitlines():
        if not line.startswith('{'):
            continue  # the Maven image entrypoint prints permission warnings to stdout
        event = json.loads(line)
        event['t'] = parse_time(event['t'])
        events.append(event)
    stacks = json.loads([line for line in tool(f'jfr print --events jdk.FileRead,jdk.FileWrite --stack-depth 24 /data/{latest.name} | python3 /data/filter_text.py').splitlines()
                         if line.startswith('{')][-1])
    (destination / 'storage-events.json').write_text(json.dumps({'events': len(events), 'stacks': stacks}, indent=2) + '\n', encoding='utf-8')
    return {'recording': latest.name, 'storageEvents': events, 'stacks': stacks}


def window(events, begin, end, read=None):
    return [e for e in events if begin <= e['t'] <= end and (read is None or e['read'] == read)]


def per_file(events):
    totals = {}
    for e in events:
        key = UUID_RE.search(e['path']).group(0) if UUID_RE.search(e['path']) else e['path']
        totals[key] = totals.get(key, 0) + e['bytes']
    return totals


# ---- scenes ---------------------------------------------------------------------------------------------

def referenced(descriptor):
    return import_scene_package.referenced_paths(descriptor)


def ensure_scene(api, name):
    status, body = api.request('GET', '/api/v1/scenes?limit=100&name=' + name)
    for item in body.get('items', []):
        if item['name'] == name:
            return item['id']
    status, body = api.request('POST', '/api/v1/scenes', {'name': name})
    if status != 201:
        raise RuntimeError(f'creating scene {name} failed: HTTP {status}')
    return body['id']


def publish(api, scene_id, version_id):
    status, scene = api.request('GET', f'/api/v1/scenes/{scene_id}')
    begin = time.monotonic()
    status, body = api.request('POST', f'/api/v1/scene-versions/{version_id}/publish', {'expectedSceneVersion': scene['lockVersion']})
    return status, time.monotonic() - begin


def timed_admin_json(api, path):
    begin = time.monotonic()
    status, body = api.request('GET', path)
    return status, body, time.monotonic() - begin


def import_scene(report, api, name, samples_root, descriptors, results):
    package_root = samples_root / name
    descriptor_path = descriptors / name / 'resource.json'
    descriptor = json.loads(descriptor_path.read_text(encoding='utf-8'))
    scene_id = ensure_scene(api, name)
    # A fresh import (new request key, new version) so the JFR window sees real uploads; superseded versions are
    # deleted afterwards (the whole-version delete on real data) to give the disk back.
    descriptor_path.with_name(import_scene_package.STATE_NAME).unlink(missing_ok=True)
    begin_utc = time.time()
    result = import_scene_package.import_package(api, scene_id, package_root, descriptor_path, log=lambda line: print('  ' + line, flush=True))
    result.update({'sceneId': scene_id, 'name': name, 'descriptor': descriptor, 'importWindow': [begin_utc, time.time()],
                   'packageRoot': str(package_root)})
    report.check(f'{name}: every referenced file is AVAILABLE after import', result['complete'],
                 {'failed': result['failed'], 'processing': result['processing']})
    status, seconds = publish(api, scene_id, result['versionId'])
    report.check(f'{name}: publish', status == 200, status)
    result['publishSeconds'] = seconds
    again_status, again_seconds = publish(api, scene_id, result['versionId'])
    report.check(f'{name}: second publish is idempotent', again_status == 200, again_status)
    result['publishRepeatSeconds'] = again_seconds
    listing = api.request('GET', f'/api/v1/scenes/{scene_id}/versions?limit=100')[1]
    older = [v for v in listing['items'] if v['id'] != result['versionId']]
    for version in older:
        deleted = api.request('DELETE', f'/api/v1/scene-versions/{version["id"]}')[0]
        report.check(f'{name}: superseded version v{version["versionNo"]} deleted', deleted == 204, deleted)
    results[name] = result
    return result


def verify_public_scene(report, anonymous, name, result):
    scene_id, descriptor = result['sceneId'], result['descriptor']
    first = {}
    status, listing, first['listSeconds'] = anonymous.json('/api/v1/client/scenes?limit=100&name=' + name)
    item = next((i for i in (listing or {}).get('items', []) if i['id'] == scene_id), None)
    report.check(f'{name}: anonymous catalogue lists the published scene', status == 200 and item is not None)
    if item:
        report.check(f'{name}: catalogue variants equal the descriptor', [v['id'] for v in item['variants']] == [v['id'] for v in descriptor['variants']]
                     and item['defaultVariant'] == descriptor['defaultVariant'] and 'posterUrl' in item, item)
    status, detail, first['detailSeconds'] = anonymous.json(f'/api/v1/client/scenes/{scene_id}')
    report.check(f'{name}: anonymous description returns the exact descriptor', status == 200 and detail['descriptor'] == descriptor)
    files = {f['relativePath']: f for f in detail['files']}
    manifest = {m['relativePath']: m for m in result['manifest']}
    report.check(f'{name}: file list is exactly the referenced set with source sizes and digests', set(files) == set(manifest)
                 and all(files[p]['bytes'] == manifest[p]['bytes'] and files[p]['sha256'] == manifest[p]['sha256'] for p in files))
    secrets = json.dumps(detail)
    report.check(f'{name}: description exposes no storage key or disk path', 'storageKey' not in secrets and '/data/' not in secrets and '.bin' not in secrets)
    status, _, repeat_list = anonymous.json('/api/v1/client/scenes?limit=100&name=' + name)
    status, _, repeat_detail = anonymous.json(f'/api/v1/client/scenes/{scene_id}')
    first.update({'listRepeatSeconds': repeat_list, 'detailRepeatSeconds': repeat_detail})
    full_bytes, begin = 0, time.monotonic()
    bad = []
    for path, file in files.items():
        got = anonymous.request('GET', file['downloadPath'], hash_body=True)
        full_bytes += got['bytes']
        etag = got['headers'].get('etag', '')
        if not (got['status'] == 200 and got['sha256'] == manifest[path]['sha256'] and got['bytes'] == manifest[path]['bytes']
                and etag.startswith('"') and 'attachment' not in got['headers'].get('content-disposition', '')):
            bad.append((path, got['status'], got['bytes'], etag))
    report.check(f'{name}: every file downloads with the source SHA-256, a strong ETag and no attachment header', not bad, bad[:3])
    first.update({'fullReadBytes': full_bytes, 'fullReadSeconds': time.monotonic() - begin})
    result['publicTimings'] = first
    return detail


# ---- JFR attribution ------------------------------------------------------------------------------------

def analyze_import_io(report, name, result, events):
    reads = [e for e in events if e['read'] and result['importWindow'][0] <= e['t'] <= result['importWindow'][1]]
    report.check(f'{name}: JFR import window has no staging/committed content reads (no post-write re-hash)', not reads,
                 {'readEvents': len(reads), 'bytes': sum(e['bytes'] for e in reads)})
    ratios = {}
    for path, upload in result['uploads'].items():
        wrote = sum(e['bytes'] for e in window(events, upload['startUtc'], upload['endUtc'], read=False) if upload['fileId'] in e['path'])
        ratios[path] = round(wrote / upload['bytes'], 4)
    result['jfrWriteToSizeRatio'] = ratios
    if ratios:
        report.check(f'{name}: JFR writes per uploaded file are about one copy of the file (staged part; commit is a hard link)',
                     all(0.99 <= r <= 1.5 for r in ratios.values()), {k: v for k, v in ratios.items() if not 0.99 <= v <= 1.5})


# ---- browser --------------------------------------------------------------------------------------------

# Without these flags headless Chrome falls back to SwiftShader (software WebGL); with them ANGLE uses the NVIDIA GPU.
BROWSER_ARGS = ['--use-gl=angle', '--use-angle=gl-egl', '--ignore-gpu-blocklist']
WEBGL_JS = """() => {
    const out = {};
    for (const kind of ['webgl2', 'webgl']) {
        const gl = document.createElement('canvas').getContext(kind);
        out[kind] = !!gl;
        if (gl) {
            const ext = gl.getExtension('WEBGL_debug_renderer_info');
            out[kind + 'Renderer'] = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
            out[kind + 'Vendor'] = ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR);
        }
    }
    return out; }"""
BENCH_JS = """() => {
    const bench = window.__S4D_BENCH__;
    if (!bench) return null;
    const s = bench.snapshot();
    const keep = ['currentTime', 'playerCurrentTime', 'timeCursorValue', 'duration', 'timePaused', 'renderReady', 'appFrame',
                  'graphicsWidth', 'graphicsHeight', 'canvasClientWidth', 'canvasClientHeight', 'deviceType', 'sortingEngine',
                  'showLoading', 'loadedTime', 'loadTimeIndex'];
    return {ready: bench.ready(), ...Object.fromEntries(keep.map((k) => [k, s[k] ?? null]))};
}"""
BIGGEST_CANVAS_JS = """() => {
    let best = -1, area = 0;
    [...document.querySelectorAll('canvas')].forEach((c, i) => { const a = c.clientWidth * c.clientHeight; if (a > area) { area = a; best = i; } });
    return best;
}"""
RESPONSE_FIELDS = ('content-length', 'content-range', 'accept-ranges', 'etag')


def webgl_probe(report, executable):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        info = {'launchArgs': BROWSER_ARGS}
        for label, args in (('gpuArgs', BROWSER_ARGS), ('defaultArgs', [])):
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True, args=args)
            try:
                page = browser.new_context().new_page()
                page.goto(BASE + '/healthz')
                info[label] = page.evaluate(WEBGL_JS)
                info['browserVersion'] = browser.version
            finally:
                browser.close()
        report.data['webgl'] = info
        report.check('real Chrome creates a WebGL2 context with the GPU launch args (recorded, not a playback proof)', bool(info['gpuArgs'].get('webgl2')), info)


def viewer_missing(viewer_root):
    missing = [str(viewer_root / name) for name in VIEWER_FILES if not (viewer_root / name).is_file()]
    catalogue = viewer_root / 'viewer/20261016/230726/js/Drq6wweV.js'
    if not missing:
        text = catalogue.read_text(encoding='utf-8')
        if 'api/v1/client/scenes' not in text or '/4dgs/demo' in text:
            missing.append(f'{catalogue} is not the platform catalogue adapter (built-in scene map still in place)')
    return missing


class Network:
    """Whitelisted request log of one browser context: url, method, type, Range, status and the length/range/etag headers.
    Covers the page, its workers and navigations; response bodies and credentials are never stored."""

    def __init__(self, context):
        self.entries, self.by_request = [], {}
        context.on('request', self.request)
        context.on('response', self.response)
        context.on('requestfailed', self.failed)

    def request(self, request):
        headers = request.headers
        entry = {'url': request.url, 'method': request.method, 'type': request.resource_type, 'at': time.time(),
                 'range': headers.get('range'), 'authorization': 'authorization' in headers}
        self.entries.append(entry)
        self.by_request[request] = entry

    def response(self, response):
        entry = self.by_request.get(response.request)
        if entry is not None:
            entry['status'] = response.status
            entry.update({key: response.headers.get(key) for key in RESPONSE_FIELDS})

    def failed(self, request):
        entry = self.by_request.get(request)
        if entry is not None:
            entry['failure'] = request.failure


def split_network(entries):
    """(served by the platform, external attempts the page CSP blocked, external requests that were not blocked)."""
    served, blocked, leaked = [], [], []
    for entry in entries:
        url = entry['url']
        if url.startswith(('blob:', 'data:')):
            continue
        if url.startswith(BASE + '/'):
            served.append(entry)
        elif 'csp' in str(entry.get('failure', '')).lower():
            blocked.append(entry)
        else:
            leaked.append(entry)
    return served, blocked, leaked


def ok_status(entry):
    return entry.get('status') in (200, 206)


def host_of(url):
    return re.match(r'https?://([^/?]+)', url).group(1)


CSP_CONSOLE = re.compile(r"(?:Connecting to|Loading the script|Fetch API cannot load) '?(https?://[^\s']+)")
MISSING_CONSOLE = ('Failed to load resource: the server responded with a status of 404', 'A bad HTTP response code (404) was received when fetching the script')


def console_findings(errors):
    """(unexpected, hosts the CSP kept the page from reaching). Expected: CSP refusals of external URLs and the 404s of
    KNOWN_MISSING_PATHS (those are pinned separately against the network log)."""
    unexpected, hosts = [], set()
    for text in errors:
        found = CSP_CONSOLE.search(text)
        if found and 'Content Security Policy' in text and not found.group(1).startswith(BASE):
            hosts.add(host_of(found.group(1)))
        elif not any(text.startswith(prefix) for prefix in MISSING_CONSOLE):
            unexpected.append(text[:300])
    return unexpected, hosts


def frame_stats(page):
    """Distinct colours and mean luma of the largest canvas as composited on screen (a screenshot of its box)."""
    from PIL import Image
    index = page.evaluate(BIGGEST_CANVAS_JS)
    if index < 0:
        return {'colours': 0, 'luma': 0.0, 'canvas': False}
    image = Image.open(io.BytesIO(page.locator('canvas').nth(index).screenshot())).convert('RGB').resize((64, 36))
    raw = image.tobytes()
    pixels = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]
    return {'colours': len(set(pixels)), 'luma': sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in pixels) / len(pixels), 'canvas': True}


def longest_run(samples):
    """Longest strictly forward stretch of (monotonic seconds, player time, frame) samples: (wall seconds, player seconds)."""
    best, start = (0.0, 0.0), 0
    for i in range(1, len(samples) + 1):
        if i == len(samples) or samples[i][1] < samples[i - 1][1]:
            best = max(best, (samples[i - 1][0] - samples[start][0], samples[i - 1][1] - samples[start][1]))
            start = i
    return best


def sample_state(page, samples):
    state = page.evaluate(BENCH_JS)
    samples.append((time.monotonic(), state['playerCurrentTime'], state['appFrame']))
    return state


def play(playwright, executable, result, variant, cross, folder, tag):
    """One fresh Chrome context: launcher page -> /viewer/<scene>?showdemo=4dv&variant=<variant> -> observe playback."""
    segments = next(v for v in result['descriptor']['variants'] if v['id'] == variant)['segments']
    trace, errors = {'tag': tag, 'segments': len(segments)}, []
    browser = playwright.chromium.launch(executable_path=str(executable), headless=True, args=BROWSER_ARGS)
    try:
        context = browser.new_context(viewport={'width': 1280, 'height': 720})  # fresh: no service worker, cache or storage
        network = Network(context)
        page = context.new_page()
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
        page.on('pageerror', lambda error: errors.append('pageerror: ' + str(error)))
        page.goto(BASE + '/viewer/platform.html')
        page.wait_for_function("() => !document.getElementById('scene').disabled", timeout=30000)
        page.select_option('#scene', result['sceneId'])
        trace['launcherVariants'] = page.eval_on_selector_all('#variant option', 'options => options.map((o) => o.value)')
        page.select_option('#variant', variant)
        page.click('#open')
        page.wait_for_url(re.compile(r'/viewer/[0-9a-f-]{36}\?'), timeout=30000)
        trace['viewerUrl'] = page.url
        begin = time.monotonic()
        bench = None
        while time.monotonic() - begin < 180:
            bench = page.evaluate(BENCH_JS)
            if bench and bench['ready'] and bench['renderReady']:
                break
            page.wait_for_timeout(500)
        trace['readyAfterSeconds'] = round(time.monotonic() - begin, 1)
        trace['benchAtReady'] = bench
        page.wait_for_timeout(500)
        first = folder / f'playback-{tag}-first.png'
        page.screenshot(path=str(first))
        trace['firstFrame'] = {**frame_stats(page), 'screenshot': str(first)}
        trace['webgl'] = page.evaluate(WEBGL_JS)
        samples = []
        until = time.monotonic() + 5.5
        while time.monotonic() < until:
            sample_state(page, samples)
            page.wait_for_timeout(500)
        trace['samples'] = [[round(t - samples[0][0], 2), round(p, 3), f] for t, p, f in samples]
        trace['advance'] = longest_run(samples)
        if cross:
            boundary = segments[1]['startSeconds'] + 0.5
            trace['crossBoundarySeconds'] = boundary
            until = time.monotonic() + 120
            state = sample_state(page, samples)
            while time.monotonic() < until and state['playerCurrentTime'] < boundary:
                page.wait_for_timeout(250)
                state = sample_state(page, samples)
            trace['crossedAt'] = state
            page.wait_for_timeout(2000)
            trace['afterCross'] = sample_state(page, samples)
        later = folder / f'playback-{tag}-later.png'
        page.screenshot(path=str(later))
        trace['laterFrame'] = {**frame_stats(page), 'screenshot': str(later)}
        trace['finalBench'] = page.evaluate(BENCH_JS)
    finally:
        browser.close()
    trace['maxPlayerTime'] = max(p for _, p, _ in samples)
    return trace, network.entries, errors


def playback(report, executable, viewer_root, results, evidence):
    """Real Chrome (GPU launch args, fresh context per run) against the prepared reference viewer.

    Accepted per run only when: every request that reached the network went to 127.0.0.1:18082 (external attempts were
    stopped by the page CSP and are listed); no request carried Authorization and none used the built-in /4dgs/demo or
    research-server catalogue paths; the selected variant's segments up to the observed time were served non-empty and no
    file of another variant was requested; the player reports ready/renderReady with advancing frames and a non-uniform
    on-screen picture; the player's own time advances >= 2 s without wrapping; the cross-segment run passes the second
    segment's start and requests it. After the wedding runs, standard and high must have requested disjoint model files."""
    from playwright.sync_api import sync_playwright
    folder = evidence / 'playback'
    folder.mkdir(exist_ok=True)
    models = {}
    report.data['playback'] = {}
    with sync_playwright() as playwright:
        for name, variant, cross in PLAYBACK:
            result = results.get(name)
            label = f'playback {name}/{variant}'
            if not result:
                report.block(label, 'scene was not imported')
                continue
            tag = f'{name}-{variant}'
            descriptor = result['descriptor']
            selected = next(v for v in descriptor['variants'] if v['id'] == variant)
            file_ids = result['fileIds']
            wanted = [file_ids[s['path']] for s in selected['segments']]
            other = {file_ids[s['path']] for v in descriptor['variants'] if v['id'] != variant for s in v['segments']} - set(wanted)
            trace, entries, errors = play(playwright, executable, result, variant, cross, folder, tag)
            served, blocked, leaked = split_network(entries)
            unexpected, csp_hosts = console_findings(errors)
            blocked_hosts = sorted({host_of(e['url']) for e in blocked} | csp_hosts)
            urls = [e['url'] for e in served]
            joined = ' '.join(urls)

            def served_ok(file_id):
                return [e for e in served if f'/files/{file_id}/' in e['url'] and ok_status(e)]

            models[tag] = sorted(i for i in wanted if any(f'/files/{i}/' in u for u in urls))
            record = folder / f'playback-{tag}.json'
            record.write_text(json.dumps(
                {'trace': trace, 'requests': [{k: v for k, v in e.items() if k != 'authorization'} for e in served],
                 'externalAttemptsBlockedByCsp': [{'host': host_of(e['url']), 'failure': e.get('failure')} for e in blocked],
                 'consoleCspHosts': sorted(csp_hosts), 'unexpectedConsoleErrors': unexpected}, indent=2, default=str) + '\n', encoding='utf-8')
            report.data['playback'][tag] = {'trace': {k: v for k, v in trace.items() if k != 'samples'}, 'servedRequests': len(served),
                                            'externalBlockedHosts': blocked_hosts, 'file': str(record)}

            report.check(f'{label}: launcher page lists exactly the scene variants and opens /viewer/<scene>?showdemo=4dv&variant={variant}',
                         trace['launcherVariants'] == [v['id'] for v in descriptor['variants']]
                         and trace['viewerUrl'].endswith(f'/viewer/{result["sceneId"]}?showdemo=4dv&variant={variant}'),
                         {'launcher': trace['launcherVariants'], 'url': trace['viewerUrl']})
            report.check(f'{label}: every request that reached the network went to {BASE} (external hosts only attempted, stopped by the page CSP: {blocked_hosts})',
                         not leaked, [e['url'][:120] for e in leaked[:3]])
            report.check(f'{label}: no request carried Authorization and none used the built-in /4dgs/demo or /api/v1/viewer catalogue',
                         not any(e['authorization'] for e in entries) and not any('/4dgs/' in e['url'] or '/api/v1/viewer' in e['url'] for e in entries))
            catalogue = [e for e in served if '/api/v1/client/scenes?' in e['url'] and ok_status(e)]
            detail = [e for e in served if e['url'].endswith(f'/api/v1/client/scenes/{result["sceneId"]}') and ok_status(e)]
            settings = served_ok(file_ids[descriptor['settings']])
            report.check(f'{label}: catalogue, scene description and settings came from the platform', bool(catalogue and detail and settings),
                         {'catalogue': len(catalogue), 'detail': len(detail), 'settings': len(settings)})
            due = [i for i, s in zip(wanted, selected['segments']) if s['startSeconds'] <= trace['maxPlayerTime'] or s is selected['segments'][0]]
            lengths = {i: [int(e['content-length'] or 0) for e in served_ok(i)] for i in due}
            report.check(f'{label}: every segment of the selected variant up to the observed time was served non-empty ({len(due)} of {len(wanted)})',
                         all(lengths[i] and max(lengths[i]) > 0 for i in due), lengths)
            report.check(f'{label}: no file of another variant was requested', not any(f'/files/{i}/' in joined for i in other))
            bench = trace['benchAtReady'] or {}
            final = trace['finalBench'] or {}
            frames = [s[2] for s in trace['samples']]
            report.check(f'{label}: player reports ready/renderReady, a real canvas size and advancing frames',
                         bool(bench.get('ready') and bench.get('renderReady') and (bench.get('graphicsWidth') or 0) > 0
                              and frames[-1] > frames[0] and final.get('renderReady')), {'bench': bench, 'frames': [frames[0], frames[-1]]})
            first_frame, later_frame = trace['firstFrame'], trace['laterFrame']
            report.check(f'{label}: a non-uniform, non-black picture is on screen at first frame and later',
                         first_frame['colours'] > 8 and first_frame['luma'] > 3 and later_frame['colours'] > 8 and later_frame['luma'] > 3,
                         {'first': first_frame, 'later': later_frame})
            wall, played = trace['advance']
            report.check(f'{label}: player time advances >= 2 s without wrapping (wall {wall:.1f} s, player {played:.1f} s)',
                         wall >= 2.0 and played >= 2.0, trace['samples'])
            if cross:
                after = trace['afterCross']
                crossed = trace['crossedAt']
                report.check(f'{label}: time passes {selected["segments"][1]["startSeconds"]} s, keeps advancing, and segment 2 was served',
                             crossed['playerCurrentTime'] >= trace['crossBoundarySeconds'] and after['playerCurrentTime'] > crossed['playerCurrentTime']
                             and bool(after['renderReady']) and bool(served_ok(wanted[1])),
                             {'crossedAt': crossed, 'afterCross': after, 'segment2Responses': len(served_ok(wanted[1]))})
            unknown = [(e['status'], e['url'][len(BASE):][:120]) for e in served
                       if e.get('status', 0) >= 400 and e['url'][len(BASE):].split('?')[0] not in KNOWN_MISSING_PATHS]
            report.check(f'{label}: the only 4xx responses are the reference source\'s absent files {list(KNOWN_MISSING_PATHS)}', not unknown, unknown[:3])
            report.check(f'{label}: no console error other than CSP-stopped external hosts and those absent files', not unexpected, unexpected[:3])
    if 'wedding-standard_quality' in models and 'wedding-high_quality' in models:
        standard, high = models['wedding-standard_quality'], models['wedding-high_quality']
        report.check('switching wedding standard -> high_quality yields different, disjoint model requests',
                     bool(standard) and bool(high) and not set(standard) & set(high), {'standard': standard, 'high': high})
    report.data['playbackScope'] = {'shiku_dtwd': 'not played: its 0-5 s window is a sample assumption (the source timeOption is empty)'}


# ---- main -----------------------------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--samples-root', type=Path, required=True)
    parser.add_argument('--sample-descriptors', type=Path, required=True)
    parser.add_argument('--viewer-root', type=Path, required=True)
    parser.add_argument('--browser-executable', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    runtime = json.loads(args.runtime.read_text(encoding='utf-8'))
    if runtime.get('project') != PROJECT or runtime.get('baseUrl') != BASE:
        print(f'BLOCKED: runtime is not the fixed {PROJECT} at {BASE}', file=sys.stderr)
        return 2
    report_dir = args.report_dir.resolve()
    if not report_dir.is_relative_to(ROOT / '.local'):
        print('BLOCKED: --report-dir must be inside this worktree\'s .local directory', file=sys.stderr)
        return 2
    report_dir.mkdir(parents=True, exist_ok=True)
    report = Report()
    instance = Instance(runtime)
    tool_user = f'{os.getuid()}:{os.getgid()}'
    api = import_scene_package.Api(BASE)
    anonymous = Anonymous()
    results, jfr, timings = {}, {}, {}
    started = time.time()
    try:
        api.login(runtime['credentialsFile'])
        for name in SCENES:
            if not (args.sample_descriptors / name / 'resource.json').is_file() or not (args.samples_root / name).is_dir():
                raise FileNotFoundError(f'missing sample {name}')
        summary = json.loads((args.sample_descriptors / 'samples-summary.json').read_text(encoding='utf-8'))
        report.data['environment'] = {'runtime': {k: runtime[k] for k in ('project', 'jarSha256', 'imageIds', 'postgres', 'limits', 'source')},
                                      'startedUtc': utc(started), 'freeBytesAtStart': disk_free()}

        # 1. HTTP regression of the management contract (also covers the admin UI at 1440 and 1024 widths).
        try:
            http_report = verify_ingestion.run_http_checks(BASE, BASE + '/prod-api', runtime['credentialsFile'], report_dir / 'http', args.browser_executable)
            report.check('verify_ingestion.run_http_checks passed (%d checks)' % len(http_report['checks']), http_report['passed'] and http_report['checks'])
        except AssertionError as failure:
            report.check('verify_ingestion.run_http_checks', False, failure)

        # 2. Import, publish and public reads of the real samples, wedding first, as disk allows.
        try:
            webgl_probe(report, args.browser_executable)
        except Exception as error:
            report.block('WebGL/GPU probe', type(error).__name__ + ': ' + str(error)[:300])
        downloads_needed = {'wedding': summary['wedding']['variantModelBytes']['standard_quality'] + summary['wedding']['commonBytes'],
                            'dance_color': summary['dance_color']['variantModelBytes']['standard_quality'] + summary['dance_color']['commonBytes']}
        for name in SCENES:
            need = summary[name]['totalBytes'] + downloads_needed.get(name, 0) + 2 * GIB
            free = disk_free()
            if free < need:
                report.block(f'import {name}', f'free disk {free} bytes < {need} bytes required (referenced + download + 2 GiB margin)',
                             extraBytesNeeded=need - free)
                continue
            print(f'== {name}: {summary[name]["totalBytes"]} bytes referenced, {free} free', flush=True)
            result = import_scene(report, api, name, args.samples_root, args.sample_descriptors, results)
            result['detail'] = verify_public_scene(report, anonymous, name, result)
        report.data['samples'] = {n: {k: v for k, v in r.items() if k not in ('detail', 'descriptor', 'manifest', 'fileIds', 'uploads', 'prehashPerFile', 'jfrWriteToSizeRatio')}
                                  for n, r in results.items()}

        # 3. Range, HEAD and repeated no-content-read requests, each in its own UTC window, on wedding standard 00.
        windows = {}
        if 'wedding' in results:
            wedding = results['wedding']
            target = wedding['descriptor']['variants'][0]['segments'][0]['path']
            target_id, size = wedding['fileIds'][target], next(m['bytes'] for m in wedding['manifest'] if m['relativePath'] == target)
            source_bytes = (args.samples_root / 'wedding' / target).read_bytes()[:64] + b''
            detail = wedding['detail']
            path = next(f['downloadPath'] for f in detail['files'] if f['relativePath'] == target)

            begin = time.time()
            for _ in range(10):
                anonymous.json('/api/v1/client/scenes?limit=100')
                anonymous.json(f'/api/v1/client/scenes/{wedding["sceneId"]}')
                api.request('POST', f'/api/v1/scene-versions/{wedding["versionId"]}/publish',
                            {'expectedSceneVersion': api.request('GET', f'/api/v1/scenes/{wedding["sceneId"]}')[1]['lockVersion']})
                head = anonymous.request('HEAD', path)
            windows['repeat10'] = [begin, time.time()]
            report.check('HEAD returns 200 with the full length and no body', head['status'] == 200 and head['bytes'] == 0
                         and int(head['headers']['content-length']) == size)

            def ranged(label, header):
                begin = time.time()
                got = anonymous.request('GET', path, {'Range': header})
                windows[label] = [begin, time.time()]
                return got
            first32 = ranged('range_first32', 'bytes=0-31')
            report.check('bytes=0-31 is 206 with the exact first 32 source bytes and Content-Range',
                         first32['status'] == 206 and first32['body'] == source_bytes[:32] and first32['headers']['content-range'] == f'bytes 0-31/{size}')
            tail = ranged('range_last32', 'bytes=-32')
            with open(args.samples_root / 'wedding' / target, 'rb') as stream:
                stream.seek(size - 32)
                expected_tail = stream.read(32)
            report.check('bytes=-32 is 206 with the exact last 32 source bytes', tail['status'] == 206 and tail['body'] == expected_tail
                         and tail['headers']['content-range'] == f'bytes {size - 32}-{size - 1}/{size}')
            begin = time.time()
            full = anonymous.request('GET', path, hash_body=True)
            windows['full_get'] = [begin, time.time()]
            report.check('full GET of the target file matches its source SHA-256', full['status'] == 200 and full['bytes'] == size
                         and full['sha256'] == next(m['sha256'] for m in wedding['manifest'] if m['relativePath'] == target))
            windows['target'] = {'id': target_id, 'path': target, 'bytes': size}

        # 4. Full per-variant download with the reference tool; selected variant only.
        gateway = instance.container('gateway')
        for name, variant in DOWNLOADS:
            result = results.get(name)
            if not result:
                report.block(f'download {name}/{variant}', 'scene not imported (see blocked import)')
                continue
            output = report_dir / 'downloads' / name
            if output.exists():
                shutil.rmtree(output)
            plan = download_scene.plan_files(result['detail'], variant)
            expected_total = sum(item['bytes'] for item in plan)
            time.sleep(2.2)  # nginx logs whole seconds: keep this download's lines apart from earlier traffic
            begin = time.time()
            run = subprocess.run([sys.executable, str(ROOT / 'scripts/download_scene.py'), '--base-url', BASE, '--scene-id', result['sceneId'],
                                  '--variant', variant, '--output', str(output)], capture_output=True, text=True, timeout=1800)
            end = time.time()
            time.sleep(1.2)
            report.check(f'download {name}/{variant}: tool exits 0', run.returncode == 0, run.stderr[-300:])
            payload = output / result['sceneId'] / result['versionId'] / variant / 'payload'
            present = sorted(str(p.relative_to(payload)) for p in payload.rglob('*') if p.is_file()) if payload.is_dir() else []
            report.check(f'download {name}/{variant}: payload is exactly the selected variant plus common files',
                         present == sorted(item['relativePath'] for item in plan), present[:5])
            mismatched = [item['relativePath'] for item in plan
                          if not (payload / item['relativePath']).is_file() or sha256_file(payload / item['relativePath']) != item['sha256']]
            report.check(f'download {name}/{variant}: every file matches its source SHA-256', not mismatched, mismatched[:3])
            other_variants = [s['path'] for v in result['descriptor']['variants'] if v['id'] != variant for s in v['segments']]
            shared = {item['relativePath'] for item in plan}
            leaked = [p for p in other_variants if p not in shared and (payload / p).exists()]
            report.check(f'download {name}/{variant}: no file of any other variant (high_quality / vr_foreground) on disk', not leaked, leaked[:3])
            logs = subprocess.run(['docker', 'logs', '--since', utc(begin - 3), gateway], capture_output=True, text=True)
            gets = gateway_gets(logs.stdout + logs.stderr, result['sceneId'], begin, end)
            requested = {fid for _, fid, status, _ in gets}
            expected_ids = {item['fileId'] for item in plan}
            report.check(f'download {name}/{variant}: gateway log shows GETs for exactly the planned files',
                         requested == expected_ids and all(status == '200' for _, _, status, _ in gets), (len(requested), len(expected_ids)))
            sent = sum(int(n) for _, _, _, n in gets)
            report.check(f'download {name}/{variant}: bytes sent equal selected models + deduplicated common files', sent == expected_total, (sent, expected_total))
            ready = (output / result['sceneId'] / result['versionId'] / variant / 'ready.json').is_file()
            report.check(f'download {name}/{variant}: ready.json written', ready)
            windows[f'download_{name}'] = [begin, end]
            timings[f'download_{name}_{variant}'] = {'seconds': end - begin, 'bytes': expected_total, 'files': len(plan)}

        report.data['windows'] = windows
        report.data['timings'] = timings

        # 5. Stop (JFR dump), export, attribute; restart check; unfinished-recovery fixture.
        container = instance.restart_backend()
        life1 = export_jfr(container, report_dir / 'jfr/life1', tool_user)
        events = life1['storageEvents']
        report.data['jfr'] = {'life1': {'recording': life1['recording'], 'storageEvents': len(events)}}
        report.data['jfr']['life1']['stacks'] = life1['stacks']
        report.check('no storage read in the whole recording has a verify frame in its stack', life1['stacks']['storageReadEventsWithVerifyFrame'] == 0,
                     life1['stacks'])
        for name, result in results.items():
            analyze_import_io(report, name, result, events)
        if 'wedding' in results:
            target = windows['target']
            repeat = window(events, *windows['repeat10'], read=True)
            report.check('10x catalogue/description/publish-idempotent/HEAD: zero storage content reads', not repeat,
                         {'events': len(repeat), 'bytes': sum(e['bytes'] for e in repeat)})
            for label, expect in (('range_first32', 32), ('range_last32', 32)):
                got = window(events, *windows[label], read=True)
                by_file = per_file(got)
                report.check(f'{label}: reads only the target file, {expect} bytes', set(by_file) == {target['id']} and by_file[target['id']] == expect, by_file)
            got = per_file(window(events, *windows['full_get'], read=True))
            report.check('full GET reads only the target file, exactly its length', got == {target['id']: target['bytes']}, got)
        for name, variant in DOWNLOADS:
            if f'download_{name}' in windows:
                got = per_file(window(events, *windows[f'download_{name}'], read=True))
                plan = download_scene.plan_files(results[name]['detail'], variant)
                expected = {item['fileId']: item['bytes'] for item in plan}
                report.check(f'download {name}/{variant}: storage reads are exactly the selected files, once each', got == expected,
                             {'extra': sorted(set(got) - set(expected))[:3], 'wrong': [k for k in got if k in expected and got[k] != expected[k]][:3]})

        instance.start_backend()
        life2_begin = time.time()
        scene_count = anonymous.json('/api/v1/client/scenes?limit=100')[1]['total']
        report.check('restarted backend serves the published catalogue', scene_count >= len(results), scene_count)
        container = instance.restart_backend()
        life2 = export_jfr(container, report_dir / 'jfr/life2', tool_user)
        reads2 = [e for e in life2['storageEvents'] if e['read']]
        report.data['jfr']['life2'] = {'recording': life2['recording'], 'storageReadEvents': len(reads2), 'storageReadBytes': sum(e['bytes'] for e in reads2)}
        report.check('after restart with every file AVAILABLE: zero storage content reads', not reads2, per_file(reads2))

        recovery = recovery_fixture(report, instance, api, tool_user, report_dir)
        report.data['recovery'] = recovery

        # 6. Playback in real Chrome only with the real reference viewer.
        missing = viewer_missing(args.viewer_root)
        if missing:
            for item, variant, _ in PLAYBACK:
                report.block(f'real Chrome playback {item}/{variant}', 'reference viewer not available', missingPaths=missing)
            report.block('shiku_dtwd 0-5 s sample window playback', 'reference viewer not available', missingPaths=missing)
        else:
            playback(report, args.browser_executable, args.viewer_root, results, report_dir)
        report.data['finishedUtc'] = utc(time.time())
    except Exception as error:  # a crash is a failed run, recorded with its type
        report.check('verification ran to completion', False, type(error).__name__ + ': ' + str(error))
    finally:
        api_report = {'passed': not report.failed, 'blocked': report.blocked, 'checks': report.checks, **report.data}
        (report_dir / 'verify-4dgs.json').write_text(json.dumps(api_report, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    print(f'{sum(c["passed"] for c in report.checks)}/{len(report.checks)} checks passed; {len(report.blocked)} blocked')
    if report.failed:
        return 1
    return 4 if report.blocked else 0


def recovery_fixture(report, instance, api, tool_user, report_dir):
    """A fully written file whose row was left UPLOADING (answer lost before the DB confirmed): after a restart only that
    file's bytes are verified, once; every other AVAILABLE file is not read."""
    instance.start_backend()
    scene = api.request('POST', '/api/v1/scenes', {'name': 'recovery-' + uuid.uuid4().hex[:8]})[1]
    files, descriptor = verify_ingestion.synthetic_package('recovery')
    files['models/standard/00.c.ply'] = os.urandom(1_500_000)
    status, version = api.request('POST', f'/api/v1/scenes/{scene["id"]}/versions', verify_ingestion.version_request(files, descriptor))
    ids = {f['relativePath']: f['fileId'] for f in version['files']}
    for path, data in files.items():
        status, body = api.request('PUT', f'/api/v1/scene-versions/{version["id"]}/files/{ids[path]}/content', stream=io.BytesIO(data), length=len(data))
        assert status == 200 and body['status'] == 'AVAILABLE', (path, status)
    victim = ids['models/standard/00.c.ply']
    instance.restart_backend()
    changed = instance.psql(f"update ar_version_file set status='UPLOADING', verified_bytes=null, verified_sha256=null, failure_reason=null "
                            f"where id='{victim}' and status='AVAILABLE' returning id")
    report.check('recovery fixture: row of a fully written file left UPLOADING', changed.splitlines()[:1] == [victim], changed)
    instance.start_backend()
    for _ in range(30):
        status, state = api.request('GET', f'/api/v1/scene-versions/{version["id"]}/files/{victim}')
        if status == 200 and state.get('status') == 'AVAILABLE':
            break
        time.sleep(2)
    report.check('recovery: leftover complete bytes recover to AVAILABLE on startup', status == 200 and state['status'] == 'AVAILABLE', state)
    container = instance.restart_backend()
    export = export_jfr(container, report_dir / 'jfr/recovery-after', tool_user)
    reads = per_file([e for e in export['storageEvents'] if e['read']])
    report.check('recovery: only that file is read, exactly once, by startup', reads == {victim: len(files['models/standard/00.c.ply'])}, reads)
    instance.start_backend()
    return {'sceneId': scene['id'], 'versionId': version['id'], 'file': victim, 'storageReads': reads}


if __name__ == '__main__':
    raise SystemExit(main())
