"""场景列表入口拆分与列宽布局专项检查。

只启动本仓库的 Vite 开发服务器和真实浏览器，由 Playwright 拦截并返回合成接口响应；
不连接后端、数据库、日常 Demo 或真实存储，因此它证明页面结构和布局，不证明发布、上传、
下载、删除等业务闭环。资源面板部分另用合成 ZIP 响应检查当前对象可下载、切换场景或版本后
上一对象的下载提示与下载错误不再残留，以及准备期间切换对象时旧请求不会写回新面板。
真实后端点击验收仍按开发工作流在 Windows 隔离环境执行。
"""
import argparse
import io
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
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
DRAFT_ID = '33333333-3333-4333-8333-333333333333'
LONG_DRAFT_ID = '55555555-5555-4555-8555-555555555555'
LONG_SPARE_ID = '66666666-6666-4666-8666-666666666666'
ZIP_EXPORT_ID = '77777777-7777-4777-8777-777777777777'
ZIP_FILENAME = 'layout-check.zip'
# 每个场景各自的草稿；资源面板用两个草稿验证切换版本时的下载状态。
DRAFTS = {
    SHORT_ID: [(DRAFT_ID, '布局检查草稿')],
    LONG_ID: [(LONG_DRAFT_ID, '布局检查草稿'), (LONG_SPARE_ID, '布局检查备用草稿')],
}


def synthetic_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('layout-check.txt', '布局检查')
    return buffer.getvalue()


ZIP_BYTES = synthetic_zip()


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
    """合成场景数据；只覆盖本页面用到的接口。"""

    def __init__(self):
        self.scenes = [
            {'id': SHORT_ID, 'name': SHORT_NAME, 'enabled': True, 'lockVersion': 3},
            {'id': LONG_ID, 'name': LONG_NAME, 'enabled': False, 'lockVersion': 12},
        ]
        self.published = {}
        self.calls = []
        self.detail_requests = []
        self.scene_in_panel = None
        self.zip_stall = False
        self.zip_deferred = []

    def scene(self, scene_id):
        return next(scene for scene in self.scenes if scene['id'] == scene_id)

    def list_scenes(self):
        self.calls.append('GET /api/v1/scenes')
        return {'code': 200, 'items': [dict(scene) for scene in self.scenes], 'total': len(self.scenes)}

    def drafts(self, scene_id):
        self.scene_in_panel = scene_id
        scene = self.scene(scene_id)
        published = self.published.get(scene_id)
        items = [{'id': draft_id, 'sceneId': scene_id, 'description': description, 'published': published == draft_id,
                  'lockVersion': 0, 'creatorName': '布局检查', 'fileCount': 0, 'createdAt': '2026-09-20T00:00:00Z'}
                 for draft_id, description in DRAFTS.get(scene_id, [])]
        return {'code': 200, 'items': items, 'total': len(items), 'sceneLockVersion': scene['lockVersion'],
                'published': {'id': published, 'description': '布局检查发布版本', 'publishedByName': '布局检查',
                              'publishedAt': '2026-09-20T00:00:00Z'} if published else None}

    def draft(self, draft_id):
        scene_id = next((sid for sid, did in self.published.items() if did == draft_id), self.scene_in_panel or SHORT_ID)
        self.scene_in_panel = scene_id
        scene = self.scene(scene_id)
        published = self.published.get(scene_id) == draft_id
        return {'code': 200, 'id': draft_id, 'sceneId': scene_id,
                'description': '布局检查发布版本' if published else '布局检查草稿',
                'published': published, 'lockVersion': scene['lockVersion'], 'fileCount': 0,
                'currentCollectionId': '44444444-4444-4444-8444-444444444444', 'collectionGeneration': 1,
                'createdAt': '2026-09-20T00:00:00Z'}


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

        if path == '/getInfo' and request.method == 'GET':
            return reply({'code': 200, 'user': {'userId': 1, 'userName': 'layout-check', 'nickName': '布局检查', 'avatar': ''},
                          'roles': ['admin'], 'permissions': ['*:*:*'], 'isDefaultModifyPwd': False, 'pwdChrtype': '1'})
        if path == '/getRouters' and request.method == 'GET':
            return reply({'code': 200, 'data': [
                {'name': 'Ar', 'path': '/admin', 'hidden': False, 'redirect': 'noRedirect', 'component': 'Layout',
                 'alwaysShow': True, 'meta': {'title': '场景资源', 'icon': 'build'}, 'children': [
                     {'name': 'Scenes', 'path': 'scenes', 'hidden': False, 'component': 'demo/scenes',
                      'meta': {'title': '场景管理', 'icon': 'build', 'noCache': False}}]}]})
        if path == '/api/v1/scenes' and request.method == 'GET':
            return reply(api.list_scenes())
        if path == '/api/v1/drafts/config' and request.method == 'GET':
            return reply({'code': 200, 'maxBytes': 10485760, 'collectionMaxFiles': 200, 'collectionMaxBytes': 104857600})
        matched = re.fullmatch(r'/api/v1/scenes/([^/]+)', path)
        if matched and request.method == 'GET':
            api.detail_requests.append(matched.group(1))
            return reply({'code': 200, **api.scene(matched.group(1))})
        matched = re.fullmatch(r'/api/v1/scenes/([^/]+)/enabled', path)
        if matched and request.method == 'PUT':
            body = json.loads(request.post_data or '{}')
            scene = api.scene(matched.group(1))
            if body.get('expectedVersion') != scene['lockVersion'] or not str(body.get('reason', '')).strip():
                return reply({'code': 409, 'message': '修订号或原因不合法'}, 409)
            scene['enabled'] = bool(body.get('enabled'))
            scene['lockVersion'] += 1
            return reply({'code': 200, **scene})
        matched = re.fullmatch(r'/api/v1/scenes/([^/]+)/drafts', path)
        if matched and request.method == 'GET':
            return reply(api.drafts(matched.group(1)))
        matched = re.fullmatch(r'/api/v1/drafts/([^/]+)/zip-exports', path)
        if matched and request.method == 'POST':
            # 需要检查“准备期间切换对象”时先挂起，由脚本稍后决定成功或失败。
            if api.zip_stall:
                api.zip_deferred.append(route)
                return
            return reply({'code': 200, 'downloadPath': f'/api/v1/drafts/{matched.group(1)}/zip-exports/{ZIP_EXPORT_ID}/content'})
        matched = re.fullmatch(r'/api/v1/drafts/([^/]+)/zip-exports/([^/]+)/content', path)
        if matched and request.method == 'GET':
            return route.fulfill(status=200, content_type='application/zip',
                                 headers={'content-disposition': f'attachment; filename={ZIP_FILENAME}'},
                                 body=ZIP_BYTES)
        matched = re.fullmatch(r'/api/v1/drafts/([^/]+)/publish', path)
        if matched and request.method == 'POST':
            body = json.loads(request.post_data or '{}')
            scene_id = api.scene_in_panel
            if scene_id is None or body.get('expectedSceneVersion') != api.scene(scene_id)['lockVersion']:
                return reply({'code': 409, 'message': '场景修订号不匹配'}, 409)
            api.published[scene_id] = matched.group(1)
            api.scene(scene_id)['lockVersion'] += 1
            return reply({'code': 200, 'id': matched.group(1), 'sceneId': scene_id})
        matched = re.fullmatch(r'/api/v1/drafts/([^/]+)/files', path)
        if matched and request.method == 'GET':
            return reply({'code': 200, 'items': [], 'total': 0})
        matched = re.fullmatch(r'/api/v1/drafts/([^/]+)', path)
        if matched and request.method == 'GET':
            return reply(api.draft(matched.group(1)))
        unmocked.append(f'{request.method} {path}')
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
    check(f'{width}px 操作列直接展示四个按钮', len(metrics) == 4)
    check(f'{width}px 操作列按钮组为场景信息/版本与文件/启用或停用/删除',
          [item['text'] for item in metrics] == ['场景信息', '版本与文件', '启用', '删除'])
    check(f'{width}px 按钮文字未被截断', all(item['scrollWidth'] <= item['clientWidth'] + 1 for item in metrics))
    centers = [item['box']['y'] + item['box']['height'] / 2 for item in metrics]
    check(f'{width}px 按钮不换行', max(centers) - min(centers) <= 1.5)
    ordered = sorted(metrics, key=lambda item: item['box']['x'])
    gaps = [ordered[index + 1]['box']['x'] - (ordered[index]['box']['x'] + ordered[index]['box']['width'])
            for index in range(len(ordered) - 1)]
    check(f'{width}px 按钮不重叠且间距保持', min(gaps) >= 6)
    columns = column_widths(page)
    check(f'{width}px 状态列紧凑', columns['状态'] <= 100)
    check(f'{width}px 修订号列紧凑', columns['修订号'] <= 100)
    check(f'{width}px 操作列预留宽度容纳按钮组',
          columns['操作'] >= ordered[-1]['box']['x'] + ordered[-1]['box']['width'] - ordered[0]['box']['x'])
    check(f'{width}px 无需横向滚动', horizontal_scroller(page) is None)
    table_box = page.locator('.el-table').first.bounding_box()
    last_button = ordered[-1]['box']
    check(f'{width}px 操作列未被表格右边界截断',
          last_button['x'] + last_button['width'] <= table_box['x'] + table_box['width'] + 0.5)
    return columns


def close_clears_scene_query(page, timeout=5):
    """关闭资源面板后地址栏应移除 draftScene；抽屉关闭按钮的可访问名随 Element Plus 语言包变化，按类名点击。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if 'draftScene' not in page.url:
            return True
        page.wait_for_timeout(100)
    return False


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
            context = browser.new_context(viewport={'width': VIEWPORTS[0], 'height': 1000}, accept_downloads=True)
            context.add_cookies([{'name': 'Admin-Token', 'value': 'layout-check-token', 'url': web}])
            page = context.new_page()
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
            scroller = horizontal_scroller(page)
            check(f'{NARROW}px 窄窗口允许表格横向滚动', scroller is not None)
            table_box = page.locator('.el-table').first.bounding_box()
            before = button_metrics(page, long_row)
            check(f'{NARROW}px 未滚动时操作按钮仍在表格可见区内',
                  all(item['box']['x'] >= table_box['x'] - 0.5
                      and item['box']['x'] + item['box']['width'] <= table_box['x'] + table_box['width'] + 0.5
                      for item in before))
            check('表格可滚动到最右侧', scroll_body_to_end(page))
            page.wait_for_timeout(200)
            after = button_metrics(page, long_row)
            check(f'{NARROW}px 横向滚动后操作列固定在右侧',
                  [item['text'] for item in after] == ['场景信息', '版本与文件', '启用', '删除'])
            check(f'{NARROW}px 横向滚动后按钮仍完整可见',
                  all(item['scrollWidth'] <= item['clientWidth'] + 1 for item in after)
                  and all(item['box']['x'] >= table_box['x'] - 0.5
                          and item['box']['x'] + item['box']['width'] <= table_box['x'] + table_box['width'] + 0.5
                          for item in after))
            page.screenshot(path=str(run / f'scenes-{NARROW}-scrolled.png'), full_page=True)

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
            check('场景信息弹窗展示名称字段', SHORT_NAME in values)
            footer.get_by_role('button', name='关闭', exact=True).click()
            dialog.wait_for(state='hidden')

            api.detail_requests.clear()
            short_row.get_by_role('button', name='版本与文件', exact=True).click()
            drawer = page.locator('.el-drawer').filter(has_text='所属场景').first
            drawer.get_by_role('heading', name='内容版本草稿 · ' + SHORT_NAME).wait_for()
            check('版本与文件入口直接打开该场景资源面板', f'draftScene={SHORT_ID}' in page.url)
            check('资源面板显示所属场景名称', f'所属场景：{SHORT_NAME}' in drawer.inner_text())
            check('资源面板按点击行加载场景', api.detail_requests == [SHORT_ID])
            check('打开资源面板未经过场景信息弹窗', not dialog.is_visible())

            before_publish = api.calls.count('GET /api/v1/scenes')
            drawer.get_by_role('button', name='发布', exact=True).click()
            page.get_by_role('button', name='确认发布', exact=True).click()
            page.get_by_role('row').filter(has_text=SHORT_NAME).get_by_text('4', exact=True).wait_for(timeout=10000)
            check('发布后返回列表刷新修订号',
                  api.calls.count('GET /api/v1/scenes') > before_publish and api.scene(SHORT_ID)['lockVersion'] == 4)
            check('发布后资源面板显示新的发布版本', '布局检查发布版本' in drawer.inner_text())
            drawer.locator('.el-drawer__close-btn').click()
            check('关闭资源面板回到场景列表', close_clears_scene_query(page))

            api.detail_requests.clear()
            page.get_by_role('row').filter(has_text=LONG_NAME[:12]).get_by_role('button', name='版本与文件', exact=True).click()
            long_drawer = page.locator('.el-drawer').filter(has_text='所属场景').first
            long_drawer.get_by_role('heading', name='内容版本草稿 · ' + LONG_NAME).wait_for()
            check('第二个场景的资源面板对应正确',
                  f'draftScene={LONG_ID}' in page.url and api.detail_requests == [LONG_ID])
            long_drawer.locator('.el-drawer__close-btn').click()
            check('关闭第二个场景资源面板回到列表', close_clears_scene_query(page))

            # 当前对象的 ZIP 下载提示必须可用；切换版本后上一对象的提示、错误与准备状态必须清除。
            api.zip_stall = False
            long_row = page.get_by_role('row').filter(has_text=LONG_NAME[:12])
            long_row.get_by_role('button', name='版本与文件', exact=True).click()
            version_drawer = page.locator('.el-drawer').filter(has_text='所属场景').first
            version_drawer.get_by_role('heading', name='内容版本草稿 · ' + LONG_NAME).wait_for()
            view_files = version_drawer.get_by_role('button', name='查看文件', exact=True)
            view_files.first.click()
            version_drawer.get_by_role('heading').filter(has_text=LONG_DRAFT_ID).wait_for()
            zip_button = version_drawer.get_by_role('button', name='下载 ZIP', exact=True)
            zip_button.wait_for()
            with page.expect_download() as zip_download:
                zip_button.click()
            version_drawer.get_by_text('ZIP 已开始下载', exact=True).wait_for(timeout=10000)
            zip_name = zip_download.value.suggested_filename
            check('当前对象下载 ZIP 后显示已开始下载',
                  zip_name.startswith('layout-check') and zip_name.endswith('.zip')
                  and version_drawer.locator('.el-alert--error').count() == 0)

            view_files.nth(1).click()
            version_drawer.get_by_role('heading').filter(has_text=LONG_SPARE_ID).wait_for()
            check('切换版本后清除上一对象的 ZIP 提示与下载错误',
                  version_drawer.get_by_text('ZIP 已开始下载', exact=True).count() == 0
                  and version_drawer.get_by_text('正在准备 ZIP', exact=False).count() == 0
                  and version_drawer.locator('.el-alert--error').count() == 0)
            version_drawer.locator('.el-drawer__close-btn').click()
            check('切换版本后关闭资源面板回到列表', close_clears_scene_query(page))

            # 准备期间切换场景：旧请求稍后返回也不得写回新面板，关闭重开同样适用。
            api.zip_stall = True
            api.zip_deferred.clear()
            short_row = page.get_by_role('row').filter(has_text=SHORT_NAME)
            short_row.get_by_role('button', name='版本与文件', exact=True).click()
            stalled_drawer = page.locator('.el-drawer').filter(has_text='所属场景').first
            stalled_zip = stalled_drawer.get_by_role('button', name='下载 ZIP', exact=True)
            stalled_zip.wait_for()
            stalled_zip.click()
            deadline = time.monotonic() + 10
            while not api.zip_deferred and time.monotonic() < deadline:
                page.wait_for_timeout(100)
            check('准备中的 ZIP 请求可保持等待',
                  len(api.zip_deferred) == 1
                  and stalled_drawer.get_by_text('正在准备 ZIP', exact=False).count() >= 1)
            stalled_drawer.locator('.el-drawer__close-btn').click()
            check('准备期间关闭资源面板回到列表', close_clears_scene_query(page))

            long_row.get_by_role('button', name='版本与文件', exact=True).click()
            reopened_drawer = page.locator('.el-drawer').filter(has_text='所属场景').first
            reopened_drawer.get_by_role('heading', name='内容版本草稿 · ' + LONG_NAME).wait_for()
            check('关闭重开的新面板不显示上一对象的准备提示',
                  reopened_drawer.get_by_text('正在准备 ZIP', exact=False).count() == 0
                  and reopened_drawer.locator('.el-alert--error').count() == 0)
            api.zip_deferred.pop().fulfill(
                status=503, content_type='application/json',
                body=json.dumps({'code': 'AR_503', 'message': 'ZIP 准备失败，请稍后重试'}, ensure_ascii=False))
            api.zip_stall = False
            page.wait_for_timeout(500)
            check('上一对象的 ZIP 失败不污染新面板',
                  reopened_drawer.get_by_text('ZIP 准备失败', exact=False).count() == 0
                  and reopened_drawer.locator('.el-alert--error').count() == 0)
            reopened_drawer.locator('.el-drawer__close-btn').click()
            check('下载状态检查后关闭资源面板回到列表', close_clears_scene_query(page))

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
