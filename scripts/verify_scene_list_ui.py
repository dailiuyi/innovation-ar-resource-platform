"""场景列表与统一场景面板专项检查。

只启动本仓库的 Vite 开发服务器和真实浏览器，由 Playwright 拦截并返回合成接口响应；
不连接后端、数据库、日常 Demo 或真实存储，因此它证明页面行为和布局，不证明服务端事务、
匿名可见性或物理删除。覆盖：列表操作按钮与窄屏布局；新建/详情同一抽屉、名称与描述编辑、
仅按 sceneId 路由、迟到响应不写回；新建草稿与 requestKey 在响应丢失后复用；目录哈希真实
Worker 分块进度、固定三路并发、单文件失败隔离、停止中止在途请求、状态驱动续传、结果未确认；
多文件/ZIP 原样上传不解压；READY 后隐藏导入或重选入口；启用/停用原因与删除确认。

真实后端点击验收在隔离 Compose 实例上执行（verify_ingestion.py / verify_scene_delete.py）。
"""
import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.local/python'))
from playwright.sync_api import sync_playwright

FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
CHECKS = []
VIEWPORTS = (1280, 1440, 1920)
NARROW = 1024
SHORT_NAME = '合成场景A'
LONG_NAME = '超长场景名称' + '超长名称内容' * 20
SHORT_ID = '11111111-1111-4111-8111-111111111111'
LONG_ID = '22222222-2222-4222-8222-222222222222'
RESUME_ID = '33333333-3333-4333-8333-333333333333'
STOP_ID = '44444444-4444-4444-8444-444444444444'
UNCONFIRMED_ID = '55555555-5555-4555-8555-555555555555'
FILE_ID = '66666666-6666-4666-8666-666666666666'
SHORT_DESCRIPTION = '短场景描述'
LONG_DESCRIPTION = '长场景描述内容'
RESUME_NAME = '断点续传场景'
STOP_NAME = '停止传输场景'
UNCONFIRMED_NAME = '结果未确认场景'
FILE_NAME = '文件导入场景'
PACKAGE_FILES = ['media/poster.jpg', 'models/high-0.c.ply', 'models/std-0.c.ply', 'models/std-1.c.ply', 'settings.json']
NOTES_FILE = 'notes/报告.md'
IMPORT_FILES = sorted(PACKAGE_FILES + [NOTES_FILE])
DRAFT_NAME = '  未提交的新场景草稿  '


def check(name, condition):
    CHECKS.append({'name': name, 'passed': bool(condition)})
    print(('PASS ' if condition else 'FAIL ') + name, flush=True)
    if not condition:
        raise AssertionError(name)


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def file_id(scene_id, relative_path):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, scene_id + '/' + relative_path))


class Api:
    """In-memory scene API covering the routes used by the unified panel."""

    def __init__(self, package, small, loose):
        self.scenes = []
        self.by_id = {}
        self.deleted = set()
        self.request_keys = {}
        self.next_id = 0
        self.package_meta = {path: {'bytes': (package / path).stat().st_size,
                                    'sha256': hashlib.sha256((package / path).read_bytes()).hexdigest()}
                             for path in IMPORT_FILES}
        self.small_meta = {path: {'bytes': (small / path).stat().st_size,
                                  'sha256': hashlib.sha256((small / path).read_bytes()).hexdigest()}
                           for path in sorted(str(item.relative_to(small)) for item in small.rglob('*') if item.is_file())}
        self.loose_meta = {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                           for name, data in loose.items()}
        statuses = {path: ('AVAILABLE', None) for path in IMPORT_FILES}
        self.add(SHORT_ID, SHORT_NAME, SHORT_DESCRIPTION, True, 3, self.package_meta, statuses)
        self.add(LONG_ID, LONG_NAME, LONG_DESCRIPTION, False, 12, self.package_meta, statuses)
        resume = {path: ('PENDING', None) for path in IMPORT_FILES}
        resume[IMPORT_FILES[0]] = ('AVAILABLE', None)
        resume[IMPORT_FILES[1]] = ('FAILED', '存储暂时不可用')
        resume[IMPORT_FILES[2]] = ('UPLOADING', None)
        self.add(RESUME_ID, RESUME_NAME, '中断后继续上传', False, 2, self.package_meta, resume)
        pending = {path: ('PENDING', None) for path in IMPORT_FILES}
        self.add(STOP_ID, STOP_NAME, '主动停止后核对状态', True, 1, self.package_meta, pending)
        self.add(UNCONFIRMED_ID, UNCONFIRMED_NAME, '连接中断与查询失败', True, 1, self.package_meta, pending)
        self.add(FILE_ID, FILE_NAME, '多文件与 ZIP 原样上传', True, 1, self.loose_meta, pending)
        self.calls = []
        self.scene_detail_requests = []
        self.deferred = []
        self.defer_detail = None
        self.defer_edit = None
        self.deferred_edits = []
        self.scene_creates = []
        self.scene_edits = []
        self.scene_enables = []
        self.deleted_scenes = []
        self.upload = []
        self.uploads = []
        self.upload_bodies = []
        self.upload_receiver = None
        self.fail_once = set()
        self.hold_uploads = False
        self.held_uploads = []
        self.unconfirmed_uploads = set()
        self.state_failures = set()
        self.scene_create_failures = []
        self.abort_scene_create_once = False

    def add(self, scene_id, name, description, enabled, lock_version, meta, statuses):
        scene = {
            'id': scene_id, 'name': name, 'description': description, 'enabled': enabled,
            'lockVersion': lock_version, 'createdAt': '2026-09-20T00:00:00Z',
            'updatedAt': '2026-09-20T00:00:00Z', 'files': [], 'requestKey': None
        }
        for index, path in enumerate(meta):
            status, reason = statuses.get(path, ('PENDING', None))
            scene['files'].append({
                'fileId': file_id(scene_id, path), 'relativePath': path,
                'bytes': meta[path]['bytes'], 'sha256': meta[path]['sha256'],
                'status': status, 'failureReason': reason,
                'attempts': 1 if status in ('FAILED', 'UPLOADING') else (1 if status == 'AVAILABLE' else 0)})
        self.scenes.append(scene)
        self.by_id[scene_id] = scene
        self.next_id = max(self.next_id, len(self.scenes))
        return scene

    def scene(self, scene_id):
        scene = self.by_id.get(scene_id)
        return scene if scene and scene_id not in self.deleted else None

    @staticmethod
    def upload_status(files):
        if any(item['status'] == 'UPLOADING' for item in files):
            return 'UPLOADING'
        if any(item['status'] == 'FAILED' for item in files):
            return 'FAILED'
        if files and all(item['status'] == 'AVAILABLE' for item in files):
            return 'READY'
        return 'PENDING'

    def summary(self, scene):
        files = scene['files']
        return {
            'id': scene['id'], 'name': scene['name'], 'description': scene['description'],
            'enabled': scene['enabled'], 'lockVersion': scene['lockVersion'],
            'uploadStatus': self.upload_status(files), 'fileCount': len(files),
            'availableCount': sum(1 for item in files if item['status'] == 'AVAILABLE'),
            'failedCount': sum(1 for item in files if item['status'] == 'FAILED'),
            'totalBytes': sum(item['bytes'] for item in files),
            'createdAt': scene['createdAt'], 'updatedAt': scene['updatedAt']}

    def detail(self, scene):
        return {'code': 200, **self.summary(scene),
                'files': [dict(item) for item in scene['files']]}

    def list_scenes(self, name=''):
        self.calls.append('GET /api/v1/scenes')
        items = [self.summary(scene) for scene in self.scenes
                 if scene['id'] not in self.deleted and (not name or name.lower() in scene['name'].lower())]
        return {'code': 200, 'items': items, 'total': len(items)}

    def create(self, body):
        canonical = json.dumps(body, sort_keys=True, ensure_ascii=False)
        key = str(body.get('requestKey'))
        if key in self.request_keys:
            record = self.request_keys[key]
            if record['deleted']:
                return 410, {'code': 410, 'message': '场景已删除'}
            if record['body'] != canonical:
                return 409, {'code': 409, 'message': '请求标识已用于另一批文件'}
            return 200, self.detail(record['scene'])
        if key in {record.get('deletedKey') for record in self.request_keys.values()}:
            return 410, {'code': 410, 'message': '场景已删除'}
        self.next_id += 1
        scene_id = '88888888-8888-4888-8888-%012d' % self.next_id
        files = [{'fileId': file_id(scene_id, item['relativePath']), 'relativePath': item['relativePath'],
                  'bytes': item['bytes'], 'sha256': item['sha256'], 'status': 'PENDING',
                  'failureReason': None, 'attempts': 0} for item in body['files']]
        scene = {'id': scene_id, 'name': body['name'], 'description': body.get('description', ''),
                 'enabled': True, 'lockVersion': 0, 'createdAt': '2026-09-20T00:00:00Z',
                 'updatedAt': '2026-09-20T00:00:00Z', 'files': files, 'requestKey': key}
        self.scenes.insert(0, scene)
        self.by_id[scene_id] = scene
        self.request_keys[key] = {'body': canonical, 'scene': scene, 'deleted': False}
        return 201, self.detail(scene)

    def edit(self, scene_id, body):
        scene = self.scene(scene_id)
        if not scene:
            return 404, {'code': 404, 'message': '场景不存在'}
        if body.get('expectedVersion') != scene['lockVersion']:
            return 409, {'code': 409, 'message': '场景修订号不匹配'}
        scene['name'] = body['name']
        scene['description'] = body.get('description', '')
        scene['lockVersion'] += 1
        return 200, self.detail(scene)

    def enable(self, scene_id, body):
        scene = self.scene(scene_id)
        if not scene:
            return 404, {'code': 404, 'message': '场景不存在'}
        if body.get('expectedVersion') != scene['lockVersion'] or not str(body.get('reason', '')).strip():
            return 409, {'code': 409, 'message': '修订号或原因不合法'}
        scene['enabled'] = bool(body.get('enabled'))
        scene['lockVersion'] += 1
        return 200, self.detail(scene)

    def delete(self, scene_id, expected):
        if scene_id in self.deleted:
            return 204, None
        scene = self.by_id.get(scene_id)
        if not scene:
            return 404, {'code': 404, 'message': '场景不存在'}
        if expected != scene['lockVersion']:
            return 409, {'code': 409, 'message': '场景修订号不匹配'}
        self.deleted.add(scene_id)
        self.deleted_scenes.append(scene_id)
        record = self.request_keys.get(scene.get('requestKey'))
        if record:
            record['deleted'] = True
        return 204, None


def route_handler(api, unmocked):
    def handler(route):
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path
        if path.startswith('/dev-api'):
            path = path[len('/dev-api'):]

        def reply(payload, status=200):
            route.fulfill(status=status, content_type='application/json',
                          body=json.dumps(payload, ensure_ascii=False))

        method = request.method
        if path == '/getInfo' and method == 'GET':
            return reply({'code': 200, 'user': {'userId': 1, 'userName': 'layout-check', 'nickName': '布局检查', 'avatar': ''},
                          'roles': ['admin'], 'permissions': ['*:*:*'], 'isDefaultModifyPwd': False, 'pwdChrtype': '1'})
        if path == '/getRouters' and method == 'GET':
            return reply({'code': 200, 'data': [
                {'name': 'Ar', 'path': '/admin', 'hidden': False, 'redirect': 'noRedirect', 'component': 'Layout',
                 'alwaysShow': True, 'meta': {'title': '场景资源', 'icon': 'build'}, 'children': [
                     {'name': 'Scenes', 'path': 'scenes', 'hidden': False, 'component': 'demo/scenes',
                      'meta': {'title': '场景管理', 'icon': 'build', 'noCache': False}}]}]})
        if path == '/api/v1/scenes/config' and method == 'GET':
            return reply({'code': 200, 'maxBytes': 10485760, 'sceneMaxFiles': 1000,
                          'sceneMaxBytes': 4294967296})
        if path == '/api/v1/scenes' and method == 'GET':
            name = parse_qs(parsed.query).get('name', [''])[0]
            return reply(api.list_scenes(name))
        if path == '/api/v1/scenes' and method == 'POST':
            body = json.loads(request.post_data or '{}')
            api.scene_creates.append(body)
            if api.scene_create_failures:
                status = api.scene_create_failures.pop(0)
                return reply({'code': status, 'message': '场景创建暂时失败'}, status)
            status, payload = api.create(body)
            if status in (200, 201) and api.abort_scene_create_once:
                api.abort_scene_create_once = False
                return route.abort('failed')
            return reply(payload, status)
        matched = re.fullmatch(r'/api/v1/scenes/([^/]+)/enabled', path)
        if matched and method == 'PUT':
            body = json.loads(request.post_data or '{}')
            api.scene_enables.append({'sceneId': matched.group(1), **body})
            return reply(*reversed(api.enable(matched.group(1), body)))
        matched = re.fullmatch(r'/api/v1/scenes/([^/]+)/files/([^/]+)/content', path)
        if matched and method == 'PUT':
            scene_id, item_id = matched.group(1), matched.group(2)
            scene = api.scene(scene_id)
            if not scene:
                return reply({'code': 404, 'message': '场景不存在'}, 404)
            item = next((entry for entry in scene['files'] if entry['fileId'] == item_id), None)
            if not item:
                return reply({'code': 404, 'message': '文件不存在'}, 404)
            name = item['relativePath']
            if api.upload_receiver:
                return route.continue_(url=api.upload_receiver + path)
            # Binary upload assertions use the socket receiver, not DevTools post-data decoding.
            api.upload.append(name)
            api.uploads.append(name)
            item['attempts'] += 1
            if name in api.unconfirmed_uploads:
                return route.abort('failed')

            def deliver():
                if name in api.fail_once:
                    api.fail_once.discard(name)
                    item['status'], item['failureReason'] = 'FAILED', '存储暂时不可用'
                    return reply({'code': 'AR_503', 'message': '存储暂时不可用'}, 503)
                item['status'], item['failureReason'] = 'AVAILABLE', None
                return reply({'code': 200, **item})

            if api.hold_uploads:
                item['status'] = 'UPLOADING'
                api.held_uploads.append((item['fileId'], deliver))
                return
            return deliver()
        matched = re.fullmatch(r'/api/v1/scenes/([^/]+)/files/([^/]+)', path)
        if matched and method == 'GET':
            scene = api.scene(matched.group(1))
            if not scene:
                return reply({'code': 404, 'message': '场景不存在'}, 404)
            item = next((entry for entry in scene['files'] if entry['fileId'] == matched.group(2)), None)
            if not item:
                return reply({'code': 404, 'message': '文件不存在'}, 404)
            if item['relativePath'] in api.state_failures:
                return reply({'code': 'AR_503', 'message': '状态查询暂时不可用'}, 503)
            return reply({'code': 200, **item})
        matched = re.fullmatch(r'/api/v1/scenes/([^/]+)', path)
        if matched:
            scene_id = matched.group(1)
            if method == 'GET':
                api.scene_detail_requests.append(scene_id)
                scene = api.scene(scene_id)
                if not scene:
                    return reply({'code': 404, 'message': '场景不存在'}, 404)
                if api.defer_detail == scene_id:
                    api.deferred.append(route)
                    return
                return reply(api.detail(scene))
            if method == 'PUT':
                body = json.loads(request.post_data or '{}')
                api.scene_edits.append({'sceneId': scene_id, **body})
                status, payload = api.edit(scene_id, body)
                if api.defer_edit == scene_id:
                    api.deferred_edits.append((route, status, payload))
                    return
                return reply(payload, status)
            if method == 'DELETE':
                expected = parse_qs(parsed.query).get('expectedVersion', [None])[0]
                if expected is None:
                    return reply({'code': 400, 'message': '缺少修订号'}, 400)
                status, payload = api.delete(scene_id, int(expected))
                return route.fulfill(status=204) if status == 204 else reply(payload, status)
        unmocked.append(f'{method} {path}')
        route.fulfill(status=404, content_type='application/json',
                      body='{"code":404,"message":"unmocked request"}')
    return handler


def upload_receiver(api):
    """Capture real socket bytes, avoiding DevTools' lossy binary Blob post-data representation."""
    class Receiver(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, payload):
            self.send_response(status)
            self.send_header('Access-Control-Allow-Origin', self.headers.get('Origin', '*'))
            self.send_header('Access-Control-Allow-Credentials', 'true')
            self.send_header('Access-Control-Allow-Methods', 'PUT, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', self.headers.get('Access-Control-Request-Headers', '*'))
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode())

        def do_OPTIONS(self):
            self.respond(200, {})

        def do_PUT(self):
            matched = re.fullmatch(r'/api/v1/scenes/([^/]+)/files/([^/]+)/content', self.path)
            if not matched:
                self.respond(404, {})
                return
            scene = api.scene(matched.group(1))
            item = next((entry for entry in scene['files'] if entry['fileId'] == matched.group(2)), None) if scene else None
            if not item:
                self.respond(404, {})
                return
            name = item['relativePath']
            content = self.rfile.read(int(self.headers['Content-Length']))
            api.upload_bodies.append((scene['id'], name, content))
            api.upload.append(name)
            api.uploads.append(name)
            item['attempts'] += 1
            if name in api.fail_once:
                api.fail_once.remove(name)
                item['status'], item['failureReason'] = 'FAILED', '存储暂时不可用'
                self.respond(503, {'code': 'AR_503', 'message': '存储暂时不可用'})
            else:
                item['status'], item['failureReason'] = 'AVAILABLE', None
                self.respond(200, {'code': 200, **item})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Receiver)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def buttons(page, row):
    return row.locator('.scene-actions button')


def button_metrics(page, row):
    metrics = []
    for index in range(buttons(page, row).count()):
        element = buttons(page, row).nth(index)
        box = element.bounding_box()
        size = element.evaluate('el=>({scrollWidth:el.scrollWidth,clientWidth:el.clientWidth})')
        metrics.append({'text': element.inner_text().strip(), 'box': box, **size})
    return metrics


def horizontal_scroller(page):
    return page.evaluate('''()=>{
      const wrapper=document.querySelector('.el-table__body-wrapper')
      if(!wrapper) return null
      const scrollable=el=>['auto','scroll'].includes(getComputedStyle(el).overflowX)&&el.scrollWidth>el.clientWidth+1
      const found=[wrapper,...wrapper.querySelectorAll('*')].find(scrollable)
      return found?{scrollWidth:found.scrollWidth,clientWidth:found.clientWidth}:null
    }''')


def scroll_body_to_end(page):
    return page.evaluate('''()=>{
      const wrapper=document.querySelector('.el-table__body-wrapper')
      if(!wrapper) return false
      const scrollable=el=>['auto','scroll'].includes(getComputedStyle(el).overflowX)&&el.scrollWidth>el.clientWidth+1
      const found=[wrapper,...wrapper.querySelectorAll('*')].find(scrollable)
      if(!found) return false
      found.scrollLeft=found.scrollWidth
      return found.scrollLeft>0
    }''')


def column_widths(page):
    headers = page.locator('.el-table__header th')
    result = {}
    for index in range(headers.count()):
        header = headers.nth(index)
        result[header.inner_text().strip()] = round(header.bounding_box()['width'], 1)
    return result


def assert_layout(page, width, row):
    metrics = button_metrics(page, row)
    check(f'{width}px 操作列包含查看、启用与删除入口',
          {'查看', '启用', '删除'} <= {item['text'] for item in metrics})
    check(f'{width}px 按钮文字未被截断', all(item['scrollWidth'] <= item['clientWidth'] + 1 for item in metrics))
    centers = [item['box']['y'] + item['box']['height'] / 2 for item in metrics]
    check(f'{width}px 按钮不换行', max(centers) - min(centers) <= 1.5)
    ordered = sorted(metrics, key=lambda item: item['box']['x'])
    gaps = [ordered[index + 1]['box']['x'] - (ordered[index]['box']['x'] + ordered[index]['box']['width'])
            for index in range(len(ordered) - 1)]
    check(f'{width}px 按钮不重叠且间距保持', min(gaps) >= 6)
    columns = column_widths(page)
    check(f'{width}px 名称列获得剩余宽度',
          columns['名称'] > max(columns['状态'], columns['更新时间']))
    check(f'{width}px 操作列预留宽度容纳按钮组',
          columns['操作'] >= ordered[-1]['box']['x'] + ordered[-1]['box']['width'] - ordered[0]['box']['x'])
    check(f'{width}px 无需横向滚动', horizontal_scroller(page) is None)
    table_box = page.locator('.el-table').first.bounding_box()
    last_button = ordered[-1]['box']
    check(f'{width}px 操作列未被表格右边界截断',
          last_button['x'] + last_button['width'] <= table_box['x'] + table_box['width'] + 0.5)
    return columns


def panel(page):
    return page.locator('.scene-panel')


def panel_closed(page, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if 'sceneId' not in page.url and not panel(page).is_visible():
            return True
        page.wait_for_timeout(100)
    return 'sceneId' not in page.url and not panel(page).is_visible()


def close_panel(page):
    panel(page).locator('.el-drawer__close-btn').click()
    return panel_closed(page)


def open_panel(page, row_text):
    page.get_by_role('row').filter(has_text=row_text).get_by_role('button', name='查看', exact=True).click()
    drawer = panel(page)
    drawer.wait_for(state='visible')
    return drawer


def open_create(page):
    page.get_by_role('button', name='新建场景', exact=True).click()
    drawer = panel(page)
    drawer.wait_for(state='visible')
    drawer.get_by_text('新建场景', exact=True).wait_for()
    return drawer


def name_input(drawer):
    return drawer.locator('.scene-meta input').first


def description_input(drawer):
    return drawer.locator('.scene-meta textarea').first


def wait_until(page, predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        page.wait_for_timeout(100)
    return predicate()


def wait_idle(page, drawer, timeout=30):
    return wait_until(page, lambda: drawer.get_by_role('button', name='停止本次传输', exact=True).count() == 0, timeout)


XHR_PROBE = '''(()=>{
  const stats=window.__xhr={active:0,peak:0,aborts:0,sent:0}
  const content=/\\/files\\/[^/]+\\/content$/
  const {open,send,abort}=XMLHttpRequest.prototype
  XMLHttpRequest.prototype.open=function(method,url,...rest){
    this.__put=String(method).toUpperCase()==='PUT'&&content.test(String(url).split('?')[0])
    if(this.__put)this.addEventListener('loadend',()=>{if(this.__counted){this.__counted=false;stats.active--}})
    return open.call(this,method,url,...rest)
  }
  XMLHttpRequest.prototype.send=function(...args){
    if(this.__put){this.__counted=true;stats.sent++;stats.active++;stats.peak=Math.max(stats.peak,stats.active)}
    return send.apply(this,args)
  }
  XMLHttpRequest.prototype.abort=function(){
    if(this.__put&&this.__counted)stats.aborts++
    return abort.call(this)
  }
})()'''


HASH_PROBE = '''(()=>{
  const NativeWorker=window.Worker
  const stats=window.__hashProbe={hold:false,messages:[],files:[]}
  // 只挂起真实 Worker 的消息投递，不伪造摘要或已读取字节。
  window.Worker=class extends NativeWorker{
    constructor(...args){
      super(...args)
      this.addEventListener('message',event=>{
        if(stats.hold){
          event.stopImmediatePropagation()
          stats.messages.push({worker:this,event})
        }
      })
    }
    postMessage(file,...rest){
      if(file instanceof File)stats.files.push({name:file.name,bytes:file.size})
      return super.postMessage(file,...rest)
    }
  }
})()'''


def release_hash_message(page):
    return page.evaluate('''()=>{
      const {worker,event}=window.__hashProbe.messages.shift()
      worker.onmessage(event)
      return event.data.loaded??null
    }''')


def release_hashing(page):
    page.evaluate('''()=>{
      const stats=window.__hashProbe
      stats.hold=false
      for(const {worker,event} of stats.messages.splice(0))worker.onmessage(event)
    }''')


def progress_percent(drawer):
    return int(drawer.get_by_role('progressbar').get_attribute('aria-valuenow'))


def xhr_stats(page):
    return page.evaluate('()=>({...window.__xhr})')


def reset_xhr(page):
    page.evaluate('()=>Object.assign(window.__xhr,{active:0,peak:0,aborts:0,sent:0})')


def select_directory(drawer, package):
    drawer.locator('input[data-import-mode=directory]').set_input_files(str(package))


def select_files(drawer, paths):
    drawer.locator('input[data-import-mode=files]').set_input_files([str(path) for path in paths])


def stored_draft(page):
    raw = page.evaluate('()=>localStorage.getItem("ar:new-scene-draft:1")')
    return json.loads(raw) if raw else None


def latest_scene(api, name):
    return next((scene for scene in api.scenes if scene['name'] == name and scene['id'] not in api.deleted), None)


def issue_rows(drawer, path, kind):
    return drawer.get_by_role('row').filter(has_text=path).filter(has_text=kind)


def summary_alert(drawer, text):
    return drawer.locator('.el-alert--error').filter(has_text=text)


def make_package(run):
    root = run / 'import-package' / 'wedding'
    if root.parent.exists():
        for stale in sorted(root.parent.rglob('*'), reverse=True):
            stale.unlink() if stale.is_file() else stale.rmdir()
    (root / 'media').mkdir(parents=True)
    (root / 'models').mkdir()
    (root / 'notes').mkdir()
    for index, path in enumerate(PACKAGE_FILES):
        count = 3 * 2 * 1024 * 1024 + 133 if path == 'models/high-0.c.ply' else 64 + index
        (root / path).write_bytes(bytes([index + 1]) * count)
    (root / NOTES_FILE).write_text('说明文档同样属于场景文件', encoding='utf-8')
    return root


def make_small(run):
    root = run / 'draft-package' / 'draft'
    if root.parent.exists():
        for stale in sorted(root.parent.rglob('*'), reverse=True):
            stale.unlink() if stale.is_file() else stale.rmdir()
    (root / 'nested').mkdir(parents=True)
    (root / 'a.txt').write_text('draft a\n', encoding='utf-8')
    (root / 'nested' / 'b.bin').write_bytes(b'draft b\n' * 4)
    return root


def make_loose(run):
    root = run / 'loose-files'
    root.mkdir(exist_ok=True)
    archive = root / '资源.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr('nested/model.bin', b'\x00\xffUnity archive payload\n' * 20)
    arbitrary = root / 'arbitrary.data'
    arbitrary.write_bytes(b'\x00\xfeopaque resource bytes')
    return {'资源.zip': archive.read_bytes(), 'arbitrary.data': arbitrary.read_bytes()}, [archive, arbitrary]


def scene_draft_scenario(page, api, api_package, run):
    key = 'ar:new-scene-draft:1'
    original_url = page.url
    drawer = open_create(page)
    field = name_input(drawer)
    description = description_input(drawer)
    field.fill('   ')
    select_directory(drawer, api_package)
    page.get_by_text('待导入：2 个文件', exact=False).wait_for()
    start = drawer.get_by_role('button', name='开始上传', exact=True)
    check('空白名称时开始上传被禁用', start.is_disabled())
    field.fill(DRAFT_NAME)
    description.fill('未提交的场景描述')
    data = stored_draft(page)
    check('名称和描述修改立即持久化草稿',
          data and data.get('name') == DRAFT_NAME and data.get('description') == '未提交的场景描述')
    before = len(api.scene_creates)
    drawer.locator('.el-drawer__close-btn').click()
    drawer.wait_for(state='hidden')
    check('关闭未提交的新建抽屉不创建场景', len(api.scene_creates) == before and page.url == original_url)

    drawer = open_create(page)
    check('重新打开保留名称与描述草稿',
          name_input(drawer).input_value() == DRAFT_NAME
          and description_input(drawer).input_value() == '未提交的场景描述')
    drawer.locator('.el-drawer__close-btn').click()
    drawer.wait_for(state='hidden')
    page.reload()
    page.get_by_role('heading', name='场景管理', exact=True).wait_for()
    drawer = open_create(page)
    check('完整刷新后仍能恢复草稿',
          name_input(drawer).input_value() == DRAFT_NAME
          and description_input(drawer).input_value() == '未提交的场景描述')
    drawer.screenshot(path=str(run / 'scene-create-draft-1440.png'), animations='disabled')
    drawer.locator('.el-drawer__close-btn').click()
    drawer.wait_for(state='hidden')

    # Editing an existing scene must not overwrite the new-scene draft.
    draft_before = stored_draft(page)
    row = page.get_by_role('row').filter(has_text=SHORT_NAME)
    row.get_by_role('button', name='查看', exact=True).click()
    detail = panel(page)
    detail.wait_for(state='visible')
    name_input(detail).fill(SHORT_NAME + '临时编辑')
    detail.get_by_role('button', name='保存修改', exact=True).click()
    check('编辑现有场景成功', wait_until(page, lambda: api.scene(SHORT_ID)['name'] == SHORT_NAME + '临时编辑'))
    detail.locator('.el-drawer__close-btn').click()
    detail.wait_for(state='hidden')
    check('编辑现有场景不清除新建草稿', stored_draft(page) == draft_before)
    row = page.get_by_role('row').filter(has_text=SHORT_NAME + '临时编辑')
    row.get_by_role('button', name='查看', exact=True).click()
    detail = panel(page)
    name_input(detail).fill(SHORT_NAME)
    detail.get_by_role('button', name='保存修改', exact=True).click()
    check('恢复场景名称', wait_until(page, lambda: api.scene(SHORT_ID)['name'] == SHORT_NAME))
    detail.locator('.el-drawer__close-btn').click()
    detail.wait_for(state='hidden')

    # A lost create response must reuse the persisted requestKey and create one scene only.
    drawer = open_create(page)
    select_directory(drawer, api_package)
    page.get_by_text('待导入：2 个文件', exact=False).wait_for()
    before = len(api.scene_creates)
    api.abort_scene_create_once = True
    drawer.get_by_role('button', name='开始上传', exact=True).click()
    check('创建响应丢失后显示错误并保留草稿',
          wait_until(page, lambda: len(api.scene_creates) == before + 1
                     and drawer.locator('.el-alert--error').count() == 1)
          and stored_draft(page) is not None)
    first_key = stored_draft(page)['requestKey']
    drawer.get_by_role('button', name='开始上传', exact=True).click()
    drawer.get_by_text('场景已就绪', exact=False).first.wait_for(timeout=60000)
    created = [body for body in api.scene_creates if body['name'] == DRAFT_NAME.strip()]
    check('响应丢失重试复用同一 requestKey',
          len(created) == 2 and created[0]['requestKey'] == created[1]['requestKey'] == first_key)
    check('响应丢失重试只创建一个同名场景',
          sum(1 for scene in api.scenes if scene['name'] == DRAFT_NAME.strip()) == 1)
    check('创建成功后清除持久草稿', stored_draft(page) is None)
    check('创建请求提交名称、描述与固定文件清单',
          created[0]['description'] == '未提交的场景描述'
          and sorted(item['relativePath'] for item in created[0]['files']) == ['a.txt', 'nested/b.bin'])
    drawer.get_by_text('场景已就绪', exact=False).first.wait_for()
    check('创建完成后传输空闲', wait_idle(page, drawer))
    drawer.locator('.el-drawer__close-btn').click()
    drawer.wait_for(state='hidden')


def detail_scenario(page, api):
    api.scene_detail_requests.clear()
    drawer = open_panel(page, SHORT_NAME)
    drawer.get_by_text('场景 · ' + SHORT_NAME, exact=True).wait_for()
    check('查看入口按点击行打开唯一场景抽屉', f'sceneId={SHORT_ID}' in page.url
          and 'versionId' not in page.url and api.scene_detail_requests == [SHORT_ID])
    check('详情显示名称与描述', name_input(drawer).input_value() == SHORT_NAME
          and description_input(drawer).input_value() == SHORT_DESCRIPTION)
    check('详情文件表显示固定文件与已入库状态',
          all(drawer.locator('.scene-files').get_by_text(path, exact=True).count() for path in IMPORT_FILES)
          and drawer.locator('.scene-files').get_by_text('已入库', exact=True).count() == len(IMPORT_FILES))
    check('READY 详情显示就绪并隐藏导入与续传入口',
          '场景已就绪' in drawer.inner_text()
          and not any(drawer.get_by_role('button', name=label, exact=True).count()
                      for label in ('导入资源目录', '导入文件', '开始上传', '继续上传', '重新选择目录', '重新选择文件')))
    edits = len(api.scene_edits)
    name_input(drawer).fill(SHORT_NAME + '-renamed')
    description_input(drawer).fill('修改后的场景描述')
    drawer.get_by_role('button', name='保存修改', exact=True).click()
    check('名称与描述实际保存且不改动文件清单',
          wait_until(page, lambda: len(api.scene_edits) == edits + 1
                     and api.scene(SHORT_ID)['name'] == SHORT_NAME + '-renamed'
                     and api.scene(SHORT_ID)['description'] == '修改后的场景描述'
                     and name_input(drawer).input_value() == SHORT_NAME + '-renamed'
                     and sorted(item['relativePath'] for item in api.scene(SHORT_ID)['files']) == IMPORT_FILES))
    check('关闭详情移除 sceneId', close_panel(page) and 'sceneId' not in page.url)
    row = page.get_by_role('row').filter(has_text=SHORT_NAME + '-renamed')
    row.wait_for()
    check('列表刷新显示保存后的名称', row.count() == 1)

    row.get_by_role('button', name='查看', exact=True).click()
    drawer = panel(page)
    drawer.wait_for(state='visible')
    name_input(drawer).fill(SHORT_NAME)
    description_input(drawer).fill(SHORT_DESCRIPTION)
    drawer.get_by_role('button', name='保存修改', exact=True).click()
    check('恢复原始场景元数据', wait_until(page, lambda: api.scene(SHORT_ID)['name'] == SHORT_NAME))
    close_panel(page)

    # A late detail response for the previous scene must not replace the new panel.
    api.defer_detail = SHORT_ID
    api.deferred.clear()
    drawer = open_panel(page, SHORT_NAME)
    check('详情请求保持挂起', wait_until(page, lambda: len(api.deferred) == 1))
    check('关闭挂起中的详情', close_panel(page))
    drawer = open_panel(page, LONG_NAME[:12])
    drawer.get_by_text('场景 · ' + LONG_NAME, exact=True).wait_for()
    api.defer_detail = None
    api.deferred.pop().fulfill(status=200, content_type='application/json',
                               body=json.dumps(api.detail(api.scene(SHORT_ID)), ensure_ascii=False))
    page.wait_for_timeout(500)
    check('上一场景的迟到详情不写回新面板',
          SHORT_NAME not in drawer.inner_text() and f'sceneId={LONG_ID}' in page.url)
    close_panel(page)

    # A metadata save response for the previous scene must not rewrite the next scene.
    short_lock = api.scene(SHORT_ID)['lockVersion']
    api.defer_edit = SHORT_ID
    api.deferred_edits.clear()
    drawer = open_panel(page, SHORT_NAME)
    name_input(drawer).fill(SHORT_NAME + '-late')
    drawer.get_by_role('button', name='保存修改', exact=True).click()
    check('场景保存请求保持挂起', wait_until(page, lambda: len(api.deferred_edits) == 1))
    check('保存挂起时仍可关闭详情', close_panel(page))
    drawer = open_panel(page, LONG_NAME[:12])
    drawer.get_by_text('场景 · ' + LONG_NAME, exact=True).wait_for()
    route, status, payload = api.deferred_edits.pop()
    api.defer_edit = None
    route.fulfill(status=status, content_type='application/json',
                  body=json.dumps(payload, ensure_ascii=False))
    page.wait_for_timeout(500)
    check('上一场景的迟到保存响应不改写当前详情',
          name_input(drawer).input_value() == LONG_NAME
          and SHORT_NAME + '-late' not in drawer.inner_text()
          and f'sceneId={LONG_ID}' in page.url)
    api.scene(SHORT_ID)['name'] = SHORT_NAME
    api.scene(SHORT_ID)['lockVersion'] = short_lock
    close_panel(page)


def upload_scenario(page, api, package, run):
    name = 'upload-' + uuid.uuid4().hex[:8]
    description = '并发导入 · 场景说明'
    drawer = open_create(page)
    name_input(drawer).fill(name)
    description_input(drawer).fill(description)
    select_directory(drawer, package)
    page.get_by_text(f'待导入：{len(IMPORT_FILES)} 个文件', exact=False).wait_for()
    api.hold_uploads = True
    api.fail_once = {'models/high-0.c.ply'}
    api.uploads.clear()
    before = len(api.scene_creates)
    page.evaluate('()=>{Object.assign(window.__hashProbe,{hold:true,messages:[],files:[]})}')
    reset_xhr(page)
    start = drawer.get_by_role('button', name='开始上传', exact=True)
    start.click()
    check('目录哈希使用真实 Worker 且第一批消息已挂起',
          wait_until(page, lambda: page.evaluate('()=>window.__hashProbe.messages.length>=2'), timeout=30))
    total_bytes = sum((package / path).stat().st_size for path in IMPORT_FILES)
    first_bytes = (package / IMPORT_FILES[0]).stat().st_size
    release_hash_message(page)
    check('首个文件读取完成时进度按目录总字节计算',
          wait_until(page, lambda: progress_percent(drawer) == first_bytes * 100 // total_bytes)
          and progress_percent(drawer) < 100)
    release_hash_message(page)
    check('第二个文件已开始且真实消息可逐条投递',
          wait_until(page, lambda: page.evaluate('()=>window.__hashProbe.files.length===2&&window.__hashProbe.messages.length>0'), timeout=30))
    large_bytes = (package / IMPORT_FILES[1]).stat().st_size
    observed = []
    for chunk_end in (2 * 1024 * 1024, 4 * 1024 * 1024, 6 * 1024 * 1024, large_bytes):
        assert wait_until(page, lambda: page.evaluate('()=>window.__hashProbe.messages.length>0'))
        loaded = release_hash_message(page)
        expected = (first_bytes + chunk_end) * 100 // total_bytes
        assert loaded == chunk_end
        assert wait_until(page, lambda: progress_percent(drawer) == expected)
        observed.append(progress_percent(drawer))
    check('大文件每块哈希进度与实际累计字节相符且单调前进',
          observed == sorted(observed) and observed[0] < observed[-1] < 100)
    assert wait_until(page, lambda: page.evaluate('()=>window.__hashProbe.messages.length>0'))
    release_hash_message(page)
    check('进入下一文件后目录哈希进度不重置',
          wait_until(page, lambda: page.evaluate('()=>window.__hashProbe.files.length===3'), timeout=30)
          and progress_percent(drawer) == observed[-1])
    release_hashing(page)
    check('首批三个请求被服务端持有', wait_until(page, lambda: len(api.held_uploads) == 3, timeout=30))
    page.wait_for_timeout(500)
    stats = xhr_stats(page)
    check('首批三个均未完成时恰有三个在途，没有第四个',
          stats['active'] == 3 and stats['peak'] == 3 and stats['sent'] == 3
          and len(api.held_uploads) == 3 and api.uploads == IMPORT_FILES[:3])
    created = [body for body in api.scene_creates[before:] if body['name'] == name]
    check('一次目录导入只创建一个场景',
          len(created) == 1
          and sorted(item['relativePath'] for item in created[0]['files']) == IMPORT_FILES
          and created[0]['description'] == description)
    check('登记摘要与真实 Worker 结果一致',
          all(item['bytes'] == (package / item['relativePath']).stat().st_size
              and item['sha256'] == hashlib.sha256((package / item['relativePath']).read_bytes()).hexdigest()
              for item in created[0]['files']))
    _, deliver = api.held_uploads.pop(0)
    deliver()
    check('首个文件完成后其余请求仍在途',
          wait_until(page, lambda: len(api.held_uploads) == 3 and len(api.uploads) == 4, timeout=30))
    scene = latest_scene(api, name)
    check('整轮上传未结束时详情与文件表同步已入库数',
          wait_until(page, lambda: '文件 1 / 6' in drawer.locator('.scene-state').inner_text()
                     and drawer.locator('.scene-files').get_by_text('已入库', exact=True).count() == 1))
    page.screenshot(path=str(run / 'panel-upload-progress-1440.png'), full_page=True)
    release_held(api)
    check('单个文件失败后其余文件继续传完并显示汇总',
          wait_until(page, lambda: summary_alert(drawer, '本轮请求失败 1 个，结果未确认 0 个').count() == 1, timeout=30))
    check('有失败文件时不宣称就绪', api.upload_status(scene['files']) == 'FAILED')
    check('每个文件恰好请求一次且并发峰值为三',
          sorted(api.uploads) == IMPORT_FILES and xhr_stats(page)['peak'] == 3)
    check('异常列表完整列出失败文件、分类与原因',
          issue_rows(drawer, 'models/high-0.c.ply', '请求失败').filter(has_text='存储暂时不可用').count() == 1
          and drawer.get_by_role('row').filter(has_text='结果未确认').count() == 0)
    check('失败后仍只有一次场景创建', len([body for body in api.scene_creates[before:] if body['name'] == name]) == 1)
    uploaded_before = list(api.uploads)
    api.uploads.clear()
    drawer.get_by_role('button', name='继续上传', exact=True).first.click()
    drawer.get_by_text('场景已就绪', exact=False).first.wait_for(timeout=60000)
    check('继续上传只重发失败文件', api.uploads == ['models/high-0.c.ply']
          and api.upload_status(scene['files']) == 'READY')
    check('继续上传没有重复创建场景',
          len([body for body in api.scene_creates[before:] if body['name'] == name]) == 1)
    check('READY 后隐藏导入和续传入口',
          not any(drawer.get_by_role('button', name=label, exact=True).count()
                  for label in ('开始上传', '继续上传', '重新选择目录', '重新选择文件',
                                '导入资源目录', '导入文件')))
    check('READY 状态显示全部文件已校验入库', '场景已就绪' in drawer.inner_text())
    check('上传完成后传输空闲', wait_idle(page, drawer))
    page.screenshot(path=str(run / 'panel-upload-ready-1440.png'), full_page=True)
    close_panel(page)


def release_held(api):
    held = list(api.held_uploads)
    api.held_uploads.clear()
    api.hold_uploads = False
    for _, deliver in held:
        deliver()


def resume_scenario(page, api, package, run):
    api.uploads.clear()
    drawer = open_panel(page, RESUME_NAME)
    drawer.get_by_text('场景 · ' + RESUME_NAME, exact=True).wait_for()
    check('未完成场景显示续传入口',
          drawer.get_by_role('button', name='继续上传', exact=True).count() <= 1
          and drawer.get_by_role('button', name='重新选择目录', exact=True).count() == 1)
    # A mismatched file selection is refused before any upload.
    loose = run / 'loose-files' / 'arbitrary.data'
    select_files(drawer, [loose])
    check('重新选择文件不在固定清单时被拒绝且不上传',
          wait_until(page, lambda: summary_alert(drawer, '不在该场景的文件清单中').count() == 1)
          and api.uploads == [])
    api.uploads.clear()
    select_directory(drawer, package)
    check('续传只发送 FAILED 与 PENDING，AVAILABLE 和 UPLOADING 零新增请求',
          wait_until(page, lambda: summary_alert(drawer, '本轮请求失败 0 个，结果未确认 1 个').count() == 1, timeout=60)
          and sorted(api.uploads) == sorted([IMPORT_FILES[1]] + IMPORT_FILES[3:]))
    check('仍在处理的文件显示为结果未确认',
          issue_rows(drawer, IMPORT_FILES[2], '结果未确认').filter(has_text='本轮开始时服务端仍在处理').count() == 1)
    resume_scene = api.scene(RESUME_ID)
    resume_scene['files'][2]['status'] = 'AVAILABLE'
    resume_scene['files'][2]['failureReason'] = None
    api.uploads.clear()
    drawer.get_by_role('button', name='继续上传', exact=True).first.click()
    drawer.get_by_text('场景已就绪', exact=False).first.wait_for(timeout=30000)
    check('处理中文件入库后再次继续无需重传并成功', api.uploads == [] and api.upload_status(resume_scene['files']) == 'READY')
    check('续传完成后传输空闲', wait_idle(page, drawer))
    close_panel(page)


def stop_scenario(page, api, package):
    drawer = open_panel(page, STOP_NAME)
    drawer.get_by_text('场景 · ' + STOP_NAME, exact=True).wait_for()
    api.hold_uploads = True
    api.uploads.clear()
    api.held_uploads.clear()
    reset_xhr(page)
    select_directory(drawer, package)
    check('停止前首批三个请求被持有', wait_until(page, lambda: len(api.held_uploads) == 3, timeout=60))
    page.wait_for_timeout(500)
    drawer.get_by_role('button', name='停止本次传输', exact=True).click()
    check('停止后传输结束并提示结果未确认',
          wait_until(page, lambda: drawer.get_by_role('button', name='停止本次传输', exact=True).count() == 0
                     and summary_alert(drawer, '已停止本次传输').count() == 1, timeout=30))
    page.wait_for_timeout(500)
    stats = xhr_stats(page)
    check('停止后三个在途请求全部中止且没有第四个请求',
          stats['aborts'] == 3 and stats['sent'] == 3 and stats['active'] == 0 and len(api.uploads) == 3)
    scene = api.scene(STOP_ID)
    check('停止后首批三个文件仍为处理中',
          all(scene['files'][index]['status'] == 'UPLOADING' for index in range(3)))
    api.held_uploads.clear()
    api.hold_uploads = False
    scene['files'][0].update(status='AVAILABLE', failureReason=None)
    scene['files'][1].update(status='FAILED', failureReason='存储暂时不可用')
    api.uploads.clear()
    drawer.get_by_role('button', name='继续上传', exact=True).first.click()
    check('停止后续传只发送 FAILED 与 PENDING',
          wait_until(page, lambda: summary_alert(drawer, '本轮请求失败 0 个，结果未确认 1 个').count() == 1, timeout=60)
          and sorted(api.uploads) == sorted([IMPORT_FILES[1]] + IMPORT_FILES[3:]))
    scene['files'][2].update(status='AVAILABLE', failureReason=None)
    api.uploads.clear()
    drawer.get_by_role('button', name='继续上传', exact=True).first.click()
    drawer.get_by_text('场景已就绪', exact=False).first.wait_for(timeout=30000)
    check('停止后无需再传字节的成功续传', api.uploads == []
          and api.upload_status(scene['files']) == 'READY')
    check('停止场景续传完成后传输空闲', wait_idle(page, drawer))
    close_panel(page)


def unconfirmed_scenario(page, api, package):
    api.uploads.clear()
    api.unconfirmed_uploads = set(IMPORT_FILES[:4])
    api.state_failures = set(IMPORT_FILES[:4])
    drawer = open_panel(page, UNCONFIRMED_NAME)
    drawer.get_by_text('场景 · ' + UNCONFIRMED_NAME, exact=True).wait_for()
    select_directory(drawer, package)
    check('四个结果未确认时仍完成全部六个文件的请求并显示汇总',
          wait_until(page, lambda: summary_alert(drawer, '本轮请求失败 0 个，结果未确认 4 个').count() == 1, timeout=60)
          and sorted(api.uploads) == IMPORT_FILES)
    check('四个异常路径与查询失败原因完整可见且归类为结果未确认',
          all(issue_rows(drawer, path, '结果未确认').filter(has_text='上传结果未确认，请刷新状态').count() == 1
              for path in IMPORT_FILES[:4])
          and drawer.get_by_role('row').filter(has_text='结果未确认').count() == 4
          and drawer.get_by_role('row').filter(has_text='请求失败').count() == 0)
    check('未确认时页面不宣称文件确定未入库', '确定未入库' not in drawer.inner_text())
    api.unconfirmed_uploads = set()
    api.state_failures = set()
    close_panel(page)


def file_import_scenario(page, api, receiver, loose):
    name = 'files-' + uuid.uuid4().hex[:8]
    api.upload_receiver = f'http://127.0.0.1:{receiver.server_port}'
    api.uploads.clear()
    api.upload_bodies.clear()
    api.fail_once = {loose[0].name}
    drawer = open_create(page)
    name_input(drawer).fill(name)
    description_input(drawer).fill('多文件与 ZIP 原样上传')
    with page.expect_file_chooser() as chooser:
        drawer.get_by_role('button', name='导入文件', exact=True).click()
    check('导入文件打开非目录多选输入', chooser.value.is_multiple
          and drawer.locator('input[data-import-mode=files]').get_attribute('webkitdirectory') is None)
    chooser.value.set_files([str(path) for path in loose])
    page.get_by_text('待导入：2 个文件', exact=False).wait_for()
    drawer.get_by_role('button', name='开始上传', exact=True).click()
    check('多文件首次上传保留单个失败',
          wait_until(page, lambda: summary_alert(drawer, '本轮请求失败 1 个').count() == 1, timeout=60))
    scene = latest_scene(api, name)
    expected = {path.name: path.read_bytes() for path in loose}
    check('一次多文件选择只创建同一个场景且仅使用文件名',
          len([body for body in api.scene_creates if body['name'] == name]) == 1
          and sorted(item['relativePath'] for item in scene['files']) == sorted(expected))
    received = {(scene_id, relative): body for scene_id, relative, body in api.upload_bodies}
    check('ZIP 与任意文件 PUT 原始字节和登记 SHA-256 完全一致，ZIP 未展开',
          all(received.get((scene['id'], file_name)) == content
              and next(item for item in scene['files'] if item['relativePath'] == file_name)['sha256']
              == hashlib.sha256(content).hexdigest() for file_name, content in expected.items()))
    uploads_before = len(api.uploads)
    api.uploads.clear()
    drawer.get_by_role('button', name='继续上传', exact=True).first.click()
    drawer.get_by_text('场景已就绪', exact=False).first.wait_for(timeout=60000)
    check('多文件失败后只重试失败 ZIP，跳过 AVAILABLE 且不创建新场景',
          api.uploads == [loose[0].name]
          and len([body for body in api.scene_creates if body['name'] == name]) == 1)
    check('重试 ZIP 字节仍保持原样',
          api.upload_bodies[-1] == (scene['id'], loose[0].name, expected[loose[0].name]))
    check('READY 后隐藏文件重选入口',
          drawer.get_by_role('button', name='重新选择文件', exact=True).count() == 0
          and drawer.get_by_role('button', name='导入文件', exact=True).count() == 0)
    check('文件导入完成后传输空闲', wait_idle(page, drawer))
    api.upload_receiver = None
    close_panel(page)


def list_actions_scenario(page, api):
    short_row = page.get_by_role('row').filter(has_text=SHORT_NAME)
    short_row.get_by_role('button', name='停用', exact=True).click()
    prompt = page.get_by_role('dialog')
    prompt.wait_for()
    prompt.locator('input').fill('布局检查停用原因')
    prompt.get_by_role('button', name='确定', exact=True).click()
    check('填写原因后停用生效并刷新列表',
          wait_until(page, lambda: api.scene(SHORT_ID)['enabled'] is False
                     and short_row.get_by_role('button', name='启用', exact=True).count() == 1))
    short_row.get_by_role('button', name='启用', exact=True).click()
    prompt = page.get_by_role('dialog')
    prompt.wait_for()
    prompt.locator('input').fill('布局检查启用原因')
    prompt.get_by_role('button', name='确定', exact=True).click()
    check('填写原因后启用生效并刷新列表',
          wait_until(page, lambda: api.scene(SHORT_ID)['enabled'] is True
                     and short_row.get_by_role('button', name='停用', exact=True).count() == 1))

    long_row = page.get_by_role('row').filter(has_text=LONG_NAME[:12])
    long_row.get_by_role('button', name='删除', exact=True).click()
    confirm = page.locator('.el-message-box').filter(has_text='删除场景')
    confirm.wait_for()
    check('删除确认显示场景名称', LONG_NAME in confirm.inner_text())
    confirm.get_by_role('button', name='取消', exact=True).click()
    confirm.wait_for(state='hidden')
    check('取消删除不发出请求且场景仍在', api.deleted_scenes == [] and long_row.count() == 1)
    long_row.get_by_role('button', name='删除', exact=True).click()
    confirm.wait_for()
    confirm.get_by_role('button', name='确认删除', exact=True).click()
    check('确认删除后场景从列表移除', wait_until(page, lambda: api.deleted_scenes == [LONG_ID]
                                                     and page.get_by_role('row').filter(has_text=LONG_NAME[:12]).count() == 0))


def main():
    global ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path, default=ROOT / '.local')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--channel', default='')
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    ROOT = args.root.resolve()
    report_dir = args.report_dir.resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    run = report_dir / 'scene-list-ui'
    run.mkdir(parents=True, exist_ok=True)
    package = make_package(run)
    small = make_small(run)
    loose_data, loose_files = make_loose(run)
    port = args.port or free_port()
    web = f'http://127.0.0.1:{port}'
    api = Api(package, small, loose_data)
    receiver = upload_receiver(api)
    unmocked = []
    vite = subprocess.Popen(['node', str(ROOT / 'frontend/node_modules/vite/bin/vite.js'),
                             '--host', '127.0.0.1', '--port', str(port), '--strictPort'],
                            cwd=ROOT / 'frontend', stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, creationflags=FLAGS)
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(web, timeout=1).close()
                break
            except (OSError, urllib.error.URLError):
                if vite.poll() is not None:
                    raise SystemExit('vite exited: ' + (vite.stdout.read() if vite.stdout else ''))
                time.sleep(0.3)
        else:
            raise SystemExit('vite did not become ready')
        with sync_playwright() as playwright:
            channel = args.channel
            browser = None
            for candidate in ([channel] if channel else ['msedge', 'chrome', '']):
                try:
                    browser = playwright.chromium.launch(channel=candidate, headless=True) if candidate \
                        else playwright.chromium.launch(headless=True)
                    break
                except Exception as error:
                    last = error
            if browser is None:
                raise SystemExit(f'no usable browser: {last}')
            context = browser.new_context(viewport={'width': VIEWPORTS[0], 'height': 1000})
            context.add_cookies([{'name': 'Admin-Token', 'value': 'layout-check-token', 'url': web}])
            page = context.new_page()
            page.add_init_script(XHR_PROBE)
            page.add_init_script(HASH_PROBE)
            page.set_default_timeout(60000)
            page.set_default_navigation_timeout(180000)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/dev-api/**', route_handler(api, unmocked))
            page.goto(web + '/admin/scenes')
            page.get_by_role('heading', name='场景管理', exact=True).wait_for()
            short_row = page.get_by_role('row').filter(has_text=SHORT_NAME)
            long_row = page.get_by_role('row').filter(has_text=LONG_NAME[:12])
            long_row.wait_for()
            check('场景列表只提供一个查看入口', short_row.get_by_role('button', name='查看', exact=True).count() == 1
                  and short_row.get_by_role('button', name='版本与文件', exact=True).count() == 0
                  and short_row.get_by_role('button', name='场景信息', exact=True).count() == 0)

            for width in VIEWPORTS:
                page.set_viewport_size({'width': width, 'height': 1000})
                page.wait_for_timeout(250)
                assert_layout(page, width, long_row)
                page.screenshot(path=str(run / f'scenes-{width}.png'), full_page=True)
            page.set_viewport_size({'width': VIEWPORTS[0], 'height': 1000})
            page.wait_for_timeout(250)

            name_cell = long_row.locator('td').nth(0)
            overflow = name_cell.locator('.cell').evaluate('el=>({sw:el.scrollWidth,cw:el.clientWidth})')
            check('超长名称使用省略显示', overflow['sw'] > overflow['cw'] + 1)
            name_cell.hover()
            tooltip = page.locator('.el-popper[role=tooltip]').filter(has_text=LONG_NAME).first
            tooltip.wait_for(state='visible', timeout=5000)
            check('悬停可查看完整名称', LONG_NAME in tooltip.inner_text())
            page.mouse.move(0, 0)
            check('表格高度未被超长内容撑破', page.locator('.el-table').first.bounding_box()['height'] < 550)

            page.set_viewport_size({'width': NARROW, 'height': 1000})
            page.wait_for_timeout(300)
            table_box = page.locator('.el-table').first.bounding_box()
            before = button_metrics(page, long_row)
            inside = lambda items: all(item['box']['x'] >= table_box['x'] - 0.5
                                       and item['box']['x'] + item['box']['width'] <= table_box['x'] + table_box['width'] + 0.5
                                       for item in items)
            check(f'{NARROW}px 操作按钮在表格可见区内且文字完整',
                  inside(before) and all(item['scrollWidth'] <= item['clientWidth'] + 1 for item in before))
            if horizontal_scroller(page) is not None:
                check('表格可滚动到最右侧', scroll_body_to_end(page))
                page.wait_for_timeout(200)
                after = button_metrics(page, long_row)
                check(f'{NARROW}px 横向滚动后操作列固定在右侧且按钮组不变',
                      [item['text'] for item in after] == [item['text'] for item in before] and inside(after))
            check(f'{NARROW}px 查看入口可点且未被遮挡',
                  long_row.get_by_role('button', name='查看', exact=True).click(trial=True) is None)
            page.screenshot(path=str(run / f'scenes-{NARROW}.png'), full_page=True)

            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.wait_for_timeout(200)
            page.goto(web + '/admin/scenes')
            long_row.wait_for()
            scene_draft_scenario(page, api, small, run)
            detail_scenario(page, api)
            upload_scenario(page, api, package, run)
            resume_scenario(page, api, package, run)
            stop_scenario(page, api, package)
            unconfirmed_scenario(page, api, package)
            file_import_scenario(page, api, receiver, loose_files)
            list_actions_scenario(page, api)

            check('浏览器无页面错误', not errors)
            check('未出现未拦截的接口调用', not unmocked)
            browser.close()
    finally:
        receiver.shutdown()
        receiver.server_close()
        vite.terminate()
        try:
            vite.wait(timeout=10)
        except subprocess.TimeoutExpired:
            vite.kill()
    (report_dir / 'validation-scene-list-ui.json').write_text(
        json.dumps(CHECKS, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{len(CHECKS)} checks passed; screenshots in {run}')


if __name__ == '__main__':
    main()
