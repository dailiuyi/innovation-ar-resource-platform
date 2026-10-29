"""场景列表入口与版本面板专项检查。

只启动本仓库的 Vite 开发服务器和真实浏览器，由 Playwright 拦截并返回合成接口响应；
不连接后端、数据库、日常 Demo 或真实存储，因此它证明页面行为和布局，不证明发布、上传、
删除等业务闭环。覆盖：入口按钮可点且不被遮挡、选中版本随地址栏保留、场景切换后迟到响应不写回、
取消确认不产生请求，以及导入目录登记并上传目录下全部文件（无 resource.json 描述）：固定三路并发、单个文件失败不阻断其余、
完整列出请求失败与结果未确认的文件、停止时中止全部在途请求且不再派发、续传只发送 FAILED/PENDING 并跳过 AVAILABLE/UPLOADING。
真实后端点击验收在隔离 Compose 实例上执行。
"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

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
SHORT_VERSION = '33333333-3333-4333-8333-333333333333'
LONG_VERSION_1 = '55555555-5555-4555-8555-555555555555'
LONG_VERSION_2 = '66666666-6666-4666-8666-666666666666'
SHORT_DESCRIPTION = '短场景版本说明'
LONG_DESCRIPTIONS = {LONG_VERSION_1: '长场景版本一', LONG_VERSION_2: '长场景版本二'}
PACKAGE_FILES = ['media/poster.jpg', 'models/high-0.c.ply', 'models/std-0.c.ply', 'models/std-1.c.ply', 'settings.json']
NOTES_FILE = 'notes/报告.md'
IMPORT_FILES = sorted(PACKAGE_FILES + [NOTES_FILE])


def check(name, condition):
    CHECKS.append({'name': name, 'passed': bool(condition)})
    print(('PASS ' if condition else 'FAIL ') + name, flush=True)
    if not condition:
        raise AssertionError(name)


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class Api:
    """合成场景与版本数据；只覆盖本页面用到的接口。"""

    def __init__(self):
        self.scenes = [
            {'id': SHORT_ID, 'name': SHORT_NAME, 'enabled': True, 'lockVersion': 3},
            {'id': LONG_ID, 'name': LONG_NAME, 'enabled': False, 'lockVersion': 12},
        ]
        self.published = {}
        self.versions = {}
        for version_id, scene_id, number, description in (
                (SHORT_VERSION, SHORT_ID, 1, SHORT_DESCRIPTION),
                (LONG_VERSION_1, LONG_ID, 1, LONG_DESCRIPTIONS[LONG_VERSION_1]),
                (LONG_VERSION_2, LONG_ID, 2, LONG_DESCRIPTIONS[LONG_VERSION_2])):
            self.add_version(version_id, scene_id, number, description, PACKAGE_FILES, 'AVAILABLE')
        self.calls = []
        self.detail_requests = []
        self.scene_detail_requests = []
        self.version_detail_requests = []
        self.deleted_versions = []
        self.defer_detail = None
        self.deferred = []
        self.created_bodies = []
        self.uploads = []
        self.fail_once = set()
        self.hold_uploads = False
        self.held_uploads = []
        self.unconfirmed_uploads = set()
        self.state_failures = set()

    def add_version(self, version_id, scene_id, number, description, paths, status, request_key=None):
        self.versions[version_id] = {
            'id': version_id, 'sceneId': scene_id, 'versionNo': number, 'description': description,
            'lockVersion': 0, 'requestKey': request_key,
            'createdAt': '2026-09-20T00:00:00Z', 'updatedAt': '2026-09-20T00:00:00Z',
            'files': [{'fileId': f'{version_id[:8]}-{index:04d}', 'relativePath': path, 'bytes': 8 + index,
                       'sha256': f'{index:x}' * 64, 'status': status, 'failureReason': None, 'attempts': 1 if status == 'AVAILABLE' else 0}
                      for index, path in enumerate(paths)]}
        return self.versions[version_id]

    def scene(self, scene_id):
        return next(scene for scene in self.scenes if scene['id'] == scene_id)

    def list_scenes(self):
        self.calls.append('GET /api/v1/scenes')
        return {'code': 200, 'items': [dict(scene) for scene in self.scenes], 'total': len(self.scenes)}

    def summary(self, version):
        files = version['files']
        count = lambda status: sum(1 for item in files if item['status'] == status)
        status = ('UPLOADING' if count('UPLOADING') else 'FAILED' if count('FAILED')
                  else 'READY' if count('AVAILABLE') == len(files) else 'PENDING')
        return {'id': version['id'], 'sceneId': version['sceneId'], 'versionNo': version['versionNo'],
                'description': version['description'], 'lockVersion': version['lockVersion'],
                'published': self.published.get(version['sceneId']) == version['id'], 'uploadStatus': status,
                'fileCount': len(files), 'availableCount': count('AVAILABLE'), 'failedCount': count('FAILED'),
                'totalBytes': sum(item['bytes'] for item in files),
                'createdAt': version['createdAt'], 'updatedAt': version['updatedAt']}

    def detail(self, version):
        return {'code': 200, **self.summary(version), 'files': version['files']}

    def listing(self, scene_id):
        scene = self.scene(scene_id)
        mine = sorted((v for v in self.versions.values() if v['sceneId'] == scene_id), key=lambda v: -v['versionNo'])
        published = self.versions.get(self.published.get(scene_id))
        return {'code': 200, 'items': [self.summary(v) for v in mine], 'total': len(mine),
                'sceneLockVersion': scene['lockVersion'], 'published': self.summary(published) if published else None}


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
        if path == '/api/v1/scenes' and method == 'GET':
            return reply(api.list_scenes())
        if path == '/api/v1/scene-versions/config' and method == 'GET':
            return reply({'code': 200, 'maxBytes': 10485760, 'versionMaxFiles': 1000, 'versionMaxBytes': 4294967296})
        matched = re.fullmatch(r'/api/v1/scenes/([^/]+)', path)
        if matched and method == 'GET':
            api.scene_detail_requests.append(matched.group(1))
            return reply({'code': 200, **api.scene(matched.group(1))})
        matched = re.fullmatch(r'/api/v1/scenes/([^/]+)/enabled', path)
        if matched and method == 'PUT':
            body = json.loads(request.post_data or '{}')
            scene = api.scene(matched.group(1))
            if body.get('expectedVersion') != scene['lockVersion'] or not str(body.get('reason', '')).strip():
                return reply({'code': 409, 'message': '修订号或原因不合法'}, 409)
            scene['enabled'] = bool(body.get('enabled'))
            scene['lockVersion'] += 1
            return reply({'code': 200, **scene})
        matched = re.fullmatch(r'/api/v1/scenes/([^/]+)/versions', path)
        if matched and method == 'GET':
            return reply(api.listing(matched.group(1)))
        if matched and method == 'POST':
            scene_id = matched.group(1)
            body = json.loads(request.post_data or '{}')
            api.created_bodies.append(body)
            existing = next((v for v in api.versions.values() if v['requestKey'] == body['requestKey']), None)
            if existing:
                return reply(api.detail(existing))
            number = max([v['versionNo'] for v in api.versions.values() if v['sceneId'] == scene_id] or [0]) + 1
            version = api.add_version('77777777-7777-4777-8777-%012d' % number, scene_id, number, body['description'],
                                      [f['relativePath'] for f in body['files']], 'PENDING', body['requestKey'])
            for registered, stored in zip(body['files'], version['files']):
                stored['bytes'], stored['sha256'] = registered['bytes'], registered['sha256']
            return route.fulfill(status=201, content_type='application/json',
                                 body=json.dumps(api.detail(version), ensure_ascii=False))
        matched = re.fullmatch(r'/api/v1/scene-versions/([^/]+)/files/([^/]+)/content', path)
        if matched and method == 'PUT':
            version = api.versions[matched.group(1)]
            item = next(f for f in version['files'] if f['fileId'] == matched.group(2))
            path_ = item['relativePath']
            api.uploads.append(path_)
            item['attempts'] += 1
            if path_ in api.unconfirmed_uploads:
                return route.abort('failed')  # 连接中断：不宣告 FAILED，结果交由状态查询确认

            def deliver():
                if path_ in api.fail_once:
                    api.fail_once.discard(path_)
                    item['status'], item['failureReason'] = 'FAILED', '存储暂时不可用'
                    return reply({'code': 'AR_503', 'message': '存储暂时不可用'}, 503)
                item['status'], item['failureReason'] = 'AVAILABLE', None
                return reply({'code': 200, **item})

            if api.hold_uploads:
                item['status'] = 'UPLOADING'
                api.held_uploads.append((item['fileId'], deliver))
                return
            return deliver()
        matched = re.fullmatch(r'/api/v1/scene-versions/([^/]+)/files/([^/]+)', path)
        if matched and method == 'GET':
            version = api.versions[matched.group(1)]
            file_state = next(f for f in version['files'] if f['fileId'] == matched.group(2))
            if file_state['relativePath'] in api.state_failures:
                return reply({'code': 'AR_503', 'message': '状态查询暂时不可用'}, 503)
            return reply({'code': 200, **file_state})
        matched = re.fullmatch(r'/api/v1/scene-versions/([^/]+)/publish', path)
        if matched and method == 'POST':
            body = json.loads(request.post_data or '{}')
            version = api.versions[matched.group(1)]
            scene = api.scene(version['sceneId'])
            if body.get('expectedSceneVersion') != scene['lockVersion']:
                return reply({'code': 409, 'message': '场景修订号不匹配'}, 409)
            api.published[scene['id']] = version['id']
            scene['lockVersion'] += 1
            return reply({'code': 200, **api.summary(version)})
        matched = re.fullmatch(r'/api/v1/scene-versions/([^/]+)', path)
        if matched and method == 'GET':
            api.version_detail_requests.append(matched.group(1))
            # 需要检查“切换场景后旧响应迟到”时先挂起，由脚本稍后放行。
            if api.defer_detail == matched.group(1):
                api.deferred.append(route)
                return
            return reply(api.detail(api.versions[matched.group(1)]))
        if matched and method == 'DELETE':
            api.deleted_versions.append(matched.group(1))
            del api.versions[matched.group(1)]
            return route.fulfill(status=204)
        unmocked.append(f'{method} {path}')
        route.fulfill(status=404, content_type='application/json',
                      body='{"code":404,"message":"unmocked request"}')
    return handler


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
    # 只看真正可横向滚动的容器：单元格用 overflow:hidden 做省略号，scrollWidth 恒大于 clientWidth，
    # 不能当成表格横向滚动。
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
    check(f'{width}px 操作列包含场景信息与版本与文件入口',
          {'场景信息', '版本与文件'} <= {item['text'] for item in metrics})
    check(f'{width}px 按钮文字未被截断', all(item['scrollWidth'] <= item['clientWidth'] + 1 for item in metrics))
    centers = [item['box']['y'] + item['box']['height'] / 2 for item in metrics]
    check(f'{width}px 按钮不换行', max(centers) - min(centers) <= 1.5)
    ordered = sorted(metrics, key=lambda item: item['box']['x'])
    gaps = [ordered[index + 1]['box']['x'] - (ordered[index]['box']['x'] + ordered[index]['box']['width'])
            for index in range(len(ordered) - 1)]
    check(f'{width}px 按钮不重叠且间距保持', min(gaps) >= 6)
    columns = column_widths(page)
    check(f'{width}px 名称列获得剩余宽度', columns['名称'] > max(columns['状态'], columns['修订号']))
    check(f'{width}px 操作列预留宽度容纳按钮组',
          columns['操作'] >= ordered[-1]['box']['x'] + ordered[-1]['box']['width'] - ordered[0]['box']['x'])
    check(f'{width}px 无需横向滚动', horizontal_scroller(page) is None)
    table_box = page.locator('.el-table').first.bounding_box()
    last_button = ordered[-1]['box']
    check(f'{width}px 操作列未被表格右边界截断',
          last_button['x'] + last_button['width'] <= table_box['x'] + table_box['width'] + 0.5)
    return columns


def panel_closed(page, timeout=5):
    """关闭面板后地址栏应移除 sceneId 与 versionId；抽屉关闭按钮的可访问名随语言包变化，按类名点击。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if 'sceneId' not in page.url and 'versionId' not in page.url:
            return True
        page.wait_for_timeout(100)
    return False


def panel(page):
    # 页面里还有布局自带的抽屉；版本面板是唯一含目录选择输入的那个。
    return page.locator('.el-drawer').filter(has=page.locator('input[webkitdirectory]'))


def close_panel(page):
    panel(page).locator('.el-drawer__close-btn').click()
    return panel_closed(page)


def open_panel(page, row_text):
    page.get_by_role('row').filter(has_text=row_text).get_by_role('button', name='版本与文件', exact=True).click()
    drawer = panel(page)
    drawer.wait_for(state='visible')
    return drawer


def selected_version_in_url(page):
    match = re.search(r'versionId=([0-9a-f-]+)', page.url)
    return match.group(1) if match else None


def wait_until(page, predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        page.wait_for_timeout(100)
    return predicate()


XHR_PROBE = '''(()=>{
  const stats=window.__xhr={active:0,peak:0,aborts:0,sent:0}
  const content=/\\/files\\/[^/]+\\/content$/
  const {open,send,abort}=XMLHttpRequest.prototype
  XMLHttpRequest.prototype.open=function(method,url,...rest){
    this.__put=String(method).toUpperCase()==='PUT'&&content.test(String(url).split('?')[0])
    // 在 Axios 设置 onloadend 之前注册，保证先减计数，再让 Axios 派发下一个请求。
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


def xhr_stats(page):
    return page.evaluate('()=>({...window.__xhr})')


def reset_xhr(page):
    page.evaluate('()=>Object.assign(window.__xhr,{active:0,peak:0,aborts:0,sent:0})')


def import_directory(drawer, package):
    drawer.locator('input[type=file]').set_input_files(str(package))
    drawer.get_by_role('button', name='开始导入', exact=True).wait_for()
    drawer.get_by_role('button', name='开始导入', exact=True).click()


def release_held(api):
    held = list(api.held_uploads)
    api.held_uploads.clear()
    api.hold_uploads = False
    for _, deliver in held:
        deliver()


def latest_version(api, scene_id):
    return max((v for v in api.versions.values() if v['sceneId'] == scene_id), key=lambda v: v['versionNo'])


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
        (root / path).write_bytes(bytes([index + 1]) * (64 + index))
    (root / NOTES_FILE).write_text('说明文档同样属于版本文件', encoding='utf-8')
    return root


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
    port = args.port or free_port()
    web = f'http://127.0.0.1:{port}'
    api = Api()
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
                except Exception as error:  # 没有该浏览器时尝试下一个
                    last = error
            if browser is None:
                raise SystemExit(f'no usable browser: {last}')
            context = browser.new_context(viewport={'width': VIEWPORTS[0], 'height': 1000})
            context.add_cookies([{'name': 'Admin-Token', 'value': 'layout-check-token', 'url': web}])
            page = context.new_page()
            page.add_init_script(XHR_PROBE)
            # 首次访问需要 Vite 现场编译依赖，慢于 Playwright 默认超时；显式放宽避免把环境慢当成失败。
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
            check('场景列表直接提供场景信息入口', short_row.get_by_role('button', name='场景信息', exact=True).count() == 1)
            check('场景列表直接提供版本与文件入口', short_row.get_by_role('button', name='版本与文件', exact=True).count() == 1)

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
            check('表格高度未被超长内容撑破', page.locator('.el-table').first.bounding_box()['height'] < 500)

            page.set_viewport_size({'width': NARROW, 'height': 1000})
            page.wait_for_timeout(300)
            table_box = page.locator('.el-table').first.bounding_box()
            before = button_metrics(page, long_row)
            inside = lambda items: all(item['box']['x'] >= table_box['x'] - 0.5
                                       and item['box']['x'] + item['box']['width'] <= table_box['x'] + table_box['width'] + 0.5
                                       for item in items)
            check(f'{NARROW}px 操作按钮在表格可见区内且文字完整',
                  inside(before) and all(item['scrollWidth'] <= item['clientWidth'] + 1 for item in before))
            # 列再多或窗口再窄时表格会横向滚动；此时操作列必须固定在右侧，滚动前后按钮仍完整可见。
            if horizontal_scroller(page) is not None:
                check('表格可滚动到最右侧', scroll_body_to_end(page))
                page.wait_for_timeout(200)
                after = button_metrics(page, long_row)
                check(f'{NARROW}px 横向滚动后操作列固定在右侧且按钮组不变',
                      [item['text'] for item in after] == [item['text'] for item in before] and inside(after))
            check(f'{NARROW}px 版本与文件入口可点且未被遮挡',
                  long_row.get_by_role('button', name='版本与文件', exact=True).click(trial=True) is None)
            page.screenshot(path=str(run / f'scenes-{NARROW}.png'), full_page=True)

            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.wait_for_timeout(200)
            page.goto(web + '/admin/scenes')
            short_row = page.get_by_role('row').filter(has_text=SHORT_NAME)
            long_row = page.get_by_role('row').filter(has_text=LONG_NAME[:12])
            long_row.wait_for()

            short_row.get_by_role('button', name='场景信息', exact=True).click()
            dialog = page.locator('.el-dialog').filter(has_text='场景信息').first
            dialog.wait_for()
            footer = dialog.locator('.el-dialog__footer')
            check('场景信息弹窗只保留关闭与保存',
                  [item.inner_text().strip() for item in footer.get_by_role('button').all()] == ['关闭', '保存'])
            check('场景信息弹窗不再包含版本与文件按钮',
                  dialog.get_by_role('button', name='版本与文件', exact=True).count() == 0)
            values = [field.input_value() for field in dialog.locator('input').all()]
            check('场景信息弹窗只展示名称字段', values == [SHORT_NAME])
            footer.get_by_role('button', name='关闭', exact=True).click()
            dialog.wait_for(state='hidden')

            # 打开第一个场景：按点击行加载，没有发布时默认选中最近版本，选择写入地址栏。
            api.scene_detail_requests.clear()
            drawer = open_panel(page, SHORT_NAME)
            drawer.get_by_text(SHORT_VERSION).wait_for()
            check('版本与文件入口直接打开该场景面板', f'sceneId={SHORT_ID}' in page.url)
            check('面板按点击行加载场景', api.scene_detail_requests == [SHORT_ID])
            check('面板显示所属场景名称', SHORT_NAME in drawer.inner_text())
            check('没有发布版本时默认选中最近版本', selected_version_in_url(page) == SHORT_VERSION)
            check('打开面板未经过场景信息弹窗', not dialog.is_visible())

            before_publish = api.calls.count('GET /api/v1/scenes')
            drawer.get_by_role('row').filter(has_text=SHORT_DESCRIPTION).get_by_role('button', name='发布', exact=True).click()
            page.get_by_role('button', name='确认发布', exact=True).click()
            page.get_by_role('row').filter(has_text=SHORT_NAME).get_by_text('4', exact=True).wait_for(timeout=10000)
            check('发布后返回列表刷新修订号',
                  api.calls.count('GET /api/v1/scenes') > before_publish and api.scene(SHORT_ID)['lockVersion'] == 4)
            check('发布后记录的当前发布版本是所选版本', api.published.get(SHORT_ID) == SHORT_VERSION)
            check('发布后面板保持选中该版本', selected_version_in_url(page) == SHORT_VERSION)
            check('关闭面板回到场景列表', close_panel(page))

            # 第二个场景有两个版本：默认选最近版本；手动切换后刷新页面仍保留选择。
            api.scene_detail_requests.clear()
            drawer = open_panel(page, LONG_NAME[:12])
            drawer.get_by_text(LONG_VERSION_2).wait_for()
            check('第二个场景的面板对应正确', f'sceneId={LONG_ID}' in page.url and api.scene_detail_requests == [LONG_ID])
            check('默认选中最近版本', selected_version_in_url(page) == LONG_VERSION_2)
            drawer.get_by_role('row').filter(has_text=LONG_DESCRIPTIONS[LONG_VERSION_1]).get_by_role('button', name='查看', exact=True).click()
            drawer.get_by_text(LONG_VERSION_1).wait_for()
            check('手动切换版本写入地址栏', selected_version_in_url(page) == LONG_VERSION_1)
            api.version_detail_requests.clear()
            page.reload()
            panel(page).get_by_text(LONG_VERSION_1).wait_for()
            check('刷新后保留手动选择的版本', selected_version_in_url(page) == LONG_VERSION_1
                  and api.version_detail_requests[:1] == [LONG_VERSION_1])
            drawer = panel(page)
            page.screenshot(path=str(run / 'panel-1440.png'), full_page=True)
            check('1440px 下导入入口可点且未被遮挡',
                  drawer.get_by_role('button', name='导入资源目录', exact=True).click(trial=True) is None)
            page.set_viewport_size({'width': NARROW, 'height': 1000})
            page.wait_for_timeout(300)
            row_buttons = drawer.get_by_role('row').filter(has_text=LONG_DESCRIPTIONS[LONG_VERSION_2]).get_by_role('button')
            for index in range(row_buttons.count()):
                if row_buttons.nth(index).is_enabled():
                    row_buttons.nth(index).click(trial=True)
            check(f'{NARROW}px 下版本行按钮可点且未被遮挡', row_buttons.count() >= 2)
            check(f'{NARROW}px 下导入入口可点且未被遮挡',
                  drawer.get_by_role('button', name='导入资源目录', exact=True).click(trial=True) is None)
            page.screenshot(path=str(run / f'panel-{NARROW}.png'), full_page=True)
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.wait_for_timeout(200)

            # 取消删除确认不产生请求；确认删除后该版本从列表消失。
            drawer.get_by_role('row').filter(has_text=LONG_DESCRIPTIONS[LONG_VERSION_2]).get_by_role('button', name='删除', exact=True).click()
            confirm = page.locator('.el-message-box')
            confirm.wait_for()
            confirm.get_by_role('button', name='取消', exact=True).click()
            confirm.wait_for(state='hidden')
            check('取消删除版本不发出请求且版本仍在',
                  api.deleted_versions == [] and drawer.get_by_role('row').filter(has_text=LONG_DESCRIPTIONS[LONG_VERSION_2]).count() == 1)
            drawer.get_by_role('row').filter(has_text=LONG_DESCRIPTIONS[LONG_VERSION_2]).get_by_role('button', name='删除', exact=True).click()
            confirm.wait_for()
            confirm.get_by_role('button', name='永久删除', exact=True).click()
            check('确认删除后版本被删除并从列表移除',
                  wait_until(page, lambda: api.deleted_versions == [LONG_VERSION_2]
                             and drawer.get_by_role('row').filter(has_text=LONG_DESCRIPTIONS[LONG_VERSION_2]).count() == 0))
            check('删除后面板选中剩余版本', selected_version_in_url(page) == LONG_VERSION_1)
            check('关闭第二个场景面板回到列表', close_panel(page))

            # 迟到响应：第一个场景的版本详情挂起，切到第二个场景后再放行，不得写回新面板。
            api.defer_detail = SHORT_VERSION
            api.deferred.clear()
            drawer = open_panel(page, SHORT_NAME)
            check('版本详情请求保持挂起', wait_until(page, lambda: len(api.deferred) == 1))
            check('关闭挂起中的面板回到列表', close_panel(page))
            drawer = open_panel(page, LONG_NAME[:12])
            drawer.get_by_text(LONG_VERSION_1).wait_for()
            api.defer_detail = None
            api.deferred.pop().fulfill(status=200, content_type='application/json',
                                       body=json.dumps(api.detail(api.versions[SHORT_VERSION]), ensure_ascii=False))
            page.wait_for_timeout(500)
            check('上一场景的迟到详情不写回新面板',
                  SHORT_VERSION not in drawer.inner_text() and selected_version_in_url(page) == LONG_VERSION_1)
            check('迟到响应没有改写地址栏场景', f'sceneId={LONG_ID}' in page.url)
            check('关闭迟到响应检查的面板', close_panel(page))

            # 导入目录：固定三路并发；单个失败不阻断其余；失败后只重传未完成文件，已入库文件不重复发送。
            drawer = open_panel(page, SHORT_NAME)
            drawer.get_by_text(SHORT_VERSION).wait_for()
            api.uploads.clear()
            api.created_bodies.clear()
            api.hold_uploads = True
            api.fail_once = {'models/high-0.c.ply'}
            reset_xhr(page)
            import_directory(drawer, package)
            check('首批三个请求被服务端持有', wait_until(page, lambda: len(api.held_uploads) == 3, timeout=30))
            page.wait_for_timeout(500)
            stats = xhr_stats(page)
            check('首批三个均未完成时恰有三个在途，没有第四个',
                  stats['active'] == 3 and stats['peak'] == 3 and stats['sent'] == 3
                  and len(api.held_uploads) == 3 and api.uploads == IMPORT_FILES[:3])
            release_held(api)
            check('单个文件失败后其余文件继续传完并显示汇总',
                  wait_until(page, lambda: summary_alert(drawer, '本轮请求失败 1 个，结果未确认 0 个').count() == 1, timeout=30))
            check('每个文件恰好请求一次且并发峰值为三',
                  sorted(api.uploads) == IMPORT_FILES and xhr_stats(page)['peak'] == 3)
            check('异常列表完整列出失败文件、分类与原因',
                  issue_rows(drawer, 'models/high-0.c.ply', '请求失败').filter(has_text='存储暂时不可用').count() == 1
                  and drawer.get_by_role('row').filter(has_text='结果未确认').count() == 0)
            check('创建版本只提交一次、登记目录下全部文件且不带 descriptor',
                  len(api.created_bodies) == 1
                  and sorted(f['relativePath'] for f in api.created_bodies[0]['files']) == IMPORT_FILES
                  and 'descriptor' not in api.created_bodies[0])
            check('登记的每个文件都带大小与 SHA-256',
                  all(f['bytes'] > 0 and re.fullmatch(r'[0-9a-f]{64}', f['sha256']) for f in api.created_bodies[0]['files']))
            uploaded_before = list(api.uploads)
            drawer.get_by_role('button', name='继续上传', exact=True).first.click()
            check('继续上传后全部文件入库',
                  wait_until(page, lambda: all(f['status'] == 'AVAILABLE' for v in api.versions.values()
                                               if v['requestKey'] for f in v['files'])
                             and drawer.get_by_text('全部文件已校验入库，可以发布').count() == 1, timeout=30))
            check('继续上传只发送失败的文件', api.uploads[len(uploaded_before):] == ['models/high-0.c.ply'])
            check('已入库文件没有被重复上传', api.uploads.count('media/poster.jpg') == 1)
            check('创建版本没有因继续上传重复提交', len(api.created_bodies) == 1)
            page.screenshot(path=str(run / 'panel-import-1440.png'), full_page=True)

            # 停止：三个在途请求全部中止，不再派发新请求，也不出现成功提示。
            api.hold_uploads = True
            api.uploads.clear()
            api.held_uploads.clear()
            reset_xhr(page)
            import_directory(drawer, package)
            check('停止前首批三个请求被持有', wait_until(page, lambda: len(api.held_uploads) == 3, timeout=30))
            page.wait_for_timeout(500)
            drawer.get_by_role('button', name='停止本次传输', exact=True).click()
            check('停止后传输结束并提示结果未确认',
                  wait_until(page, lambda: drawer.get_by_role('button', name='停止本次传输', exact=True).count() == 0
                             and summary_alert(drawer, '已停止本次传输').count() == 1, timeout=30))
            page.wait_for_timeout(500)
            stats = xhr_stats(page)
            check('停止后三个在途请求全部中止且没有第四个请求',
                  stats['aborts'] == 3 and stats['sent'] == 3 and stats['active'] == 0 and len(api.uploads) == 3)
            check('停止后不出现成功提示', '全部文件已校验入库' not in drawer.inner_text())
            api.held_uploads.clear()  # 已中止的请求不再 fulfill

            # 状态驱动续传：首批三个文件分别为 AVAILABLE、FAILED、仍 UPLOADING，其余 PENDING。
            api.hold_uploads = False
            stopped_files = {f['relativePath']: f for f in latest_version(api, SHORT_ID)['files']}
            check('停止后首批三个文件均处于处理中',
                  all(stopped_files[p]['status'] == 'UPLOADING' for p in IMPORT_FILES[:3]))
            stopped_files[IMPORT_FILES[0]].update(status='AVAILABLE', failureReason=None)
            stopped_files[IMPORT_FILES[1]].update(status='FAILED', failureReason='存储暂时不可用')
            api.uploads.clear()
            drawer.get_by_role('button', name='继续上传', exact=True).first.click()
            check('续传完成并列出仍在处理的文件',
                  wait_until(page, lambda: summary_alert(drawer, '本轮请求失败 0 个，结果未确认 1 个').count() == 1, timeout=30))
            check('续传只发送 FAILED 与 PENDING，AVAILABLE 和 UPLOADING 零新增请求',
                  sorted(api.uploads) == sorted([IMPORT_FILES[1]] + IMPORT_FILES[3:]))
            check('仍在处理的文件显示为结果未确认且未被断言未入库',
                  issue_rows(drawer, IMPORT_FILES[2], '结果未确认').filter(has_text='本轮开始时服务端仍在处理').count() == 1)
            stopped_files[IMPORT_FILES[2]].update(status='AVAILABLE', failureReason=None)
            api.uploads.clear()
            drawer.get_by_role('button', name='继续上传', exact=True).first.click()
            check('处理中文件入库后再次继续：无新增请求且成功',
                  wait_until(page, lambda: drawer.get_by_text('全部文件已校验入库，可以发布').count() == 1, timeout=30)
                  and api.uploads == [] and drawer.locator('.el-alert--error').count() == 0)

            # 结果未确认：四个文件的 PUT 连接中断且状态查询失败，另外两个正常；六个都必须被尝试并完整列出。
            api.hold_uploads = False
            api.fail_once = set()
            api.uploads.clear()
            api.unconfirmed_uploads = set(IMPORT_FILES[:4])
            api.state_failures = set(IMPORT_FILES[:4])
            import_directory(drawer, package)
            check('四个结果未确认时仍完成全部六个文件的请求并显示汇总',
                  wait_until(page, lambda: summary_alert(drawer, '本轮请求失败 0 个，结果未确认 4 个').count() == 1, timeout=30)
                  and sorted(api.uploads) == IMPORT_FILES)
            check('四个异常路径与查询失败原因完整可见且归类为结果未确认',
                  all(issue_rows(drawer, p, '结果未确认').filter(has_text='上传结果未确认，请刷新状态').count() == 1
                      for p in IMPORT_FILES[:4])
                  and drawer.get_by_role('row').filter(has_text='结果未确认').count() == 4
                  and drawer.get_by_role('row').filter(has_text='请求失败').count() == 0)
            unconfirmed_version = latest_version(api, SHORT_ID)
            check('其余两个文件已入库，页面不宣称异常文件确定未入库',
                  all(f['status'] == 'AVAILABLE' for f in unconfirmed_version['files'] if f['relativePath'] in IMPORT_FILES[4:])
                  and '确定未入库' not in drawer.inner_text())
            api.unconfirmed_uploads = set()
            api.state_failures = set()
            check('导入完成后关闭面板回到列表', close_panel(page))

            short_row = page.get_by_role('row').filter(has_text=SHORT_NAME)
            short_row.get_by_role('button', name='停用', exact=True).click()
            prompt = page.locator('.el-message-box')
            prompt.wait_for()
            prompt.locator('input').fill('布局检查停用原因')
            prompt.get_by_role('button', name='确定', exact=True).click()
            short_row.get_by_role('button', name='启用', exact=True).wait_for(timeout=10000)
            check('填写原因后停用生效并刷新状态',
                  short_row.get_by_role('button', name='启用', exact=True).count() == 1
                  and api.scene(SHORT_ID)['enabled'] is False)
            short_row.get_by_role('button', name='启用', exact=True).click()
            prompt = page.locator('.el-message-box')
            prompt.wait_for()
            prompt.locator('input').fill('布局检查启用原因')
            prompt.get_by_role('button', name='确定', exact=True).click()
            short_row.get_by_role('button', name='停用', exact=True).wait_for(timeout=10000)
            check('填写原因后启用生效并刷新状态',
                  short_row.get_by_role('button', name='停用', exact=True).count() == 1
                  and api.scene(SHORT_ID)['enabled'] is True)

            short_row.get_by_role('button', name='删除', exact=True).click()
            confirm = page.locator('.el-message-box').filter(has_text='删除场景')
            confirm.wait_for()
            check('删除确认仍显示场景名称', SHORT_NAME in confirm.inner_text())
            confirm.get_by_role('button', name='取消', exact=True).click()
            confirm.wait_for(state='hidden')
            check('取消删除后场景仍在列表', page.get_by_role('row').filter(has_text=SHORT_NAME).count() == 1)
            page.screenshot(path=str(run / 'scenes-1440-interaction.png'), full_page=True)

            check('浏览器无页面错误', not errors)
            check('未出现未拦截的接口调用', not unmocked)
            browser.close()
    finally:
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
