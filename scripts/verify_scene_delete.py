"""Deletion and confirmation checks against the isolated Compose test project only."""
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from playwright.sync_api import sync_playwright
from verify_infrastructure import ENV_FILE, ROOT, BASE, request, check, checks, wait_ready
from verify_ingestion import scene_request, synthetic_package

wait_ready()
settings = dict(line.split('=', 1) for line in ENV_FILE.read_text().splitlines()
                if line and not line.startswith('#'))
status, body = request('/prod-api/login', 'POST', {
    'username': 'bootstrap', 'password': settings['AR_BOOTSTRAP_PASSWORD']})
token = json.loads(body)['token']
prefix = '/prod-api/api/v1/scenes'
files = synthetic_package('delete-check')
name = 'delete-check-' + uuid.uuid4().hex[:10]
status, body = request(prefix, 'POST', scene_request(name, files), token)
check('combined scene created', status == 201)
scene = json.loads(body)
scene_id = scene['id']
revision = scene['lockVersion']
path = prefix + '/' + scene_id
check('anonymous delete rejected', request(path + f'?expectedVersion={revision}', 'DELETE')[0] == 401)
check('missing revision rejected', request(path, 'DELETE', token=token)[0] == 400)
check('stale revision rejected', request(path + '?expectedVersion=99', 'DELETE', token=token)[0] == 409)

with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    context = browser.new_context()
    context.add_cookies([{'name': 'Admin-Token', 'value': token, 'url': BASE}])
    page = context.new_page()
    deletes = []
    page.on('request', lambda r: deletes.append(r.url) if r.method == 'DELETE' else None)
    page.goto(BASE + '/admin/scenes')
    page.get_by_placeholder('搜索场景').fill(name)
    page.get_by_role('button', name='查询', exact=True).click()
    row = page.get_by_role('row').filter(has_text=name)
    row.get_by_role('button', name='删除', exact=True).click()
    dialog = page.get_by_role('dialog', name='删除场景')
    dialog.wait_for()
    check('confirmation identifies scene', name in dialog.inner_text())
    dialog.get_by_role('button', name='取消', exact=True).click()
    dialog.wait_for(state='hidden')
    check('cancel sends no deletion request', not deletes)
    check('cancel preserves scene', request(path, token=token)[0] == 200)
    row.get_by_role('button', name='删除', exact=True).click()
    with page.expect_response(lambda r: r.request.method == 'DELETE') as response:
        page.get_by_role('dialog', name='删除场景').get_by_role('button', name='确认删除', exact=True).click()
    check('confirmed deletion succeeds', response.value.status == 204)
    row.wait_for(state='hidden')
    check('confirmation submits once', len(deletes) == 1)
    browser.close()

check('deleted scene hidden', request(path, token=token)[0] == 404)
check('deleted scene excluded from count', json.loads(request(prefix + '?name=' + name, token=token)[1])['total'] == 0)
check('repeated deletion is idempotent', request(path + '?expectedVersion=0', 'DELETE', token=token)[0] == 204)
check('deleted scene cannot be edited',
      request(path, 'PUT', {'name': name, 'description': '', 'expectedVersion': 1}, token)[0] == 404)
check('deleted scene cannot be enabled',
      request(path + '/enabled', 'PUT', {'enabled': True, 'expectedVersion': 1, 'reason': 'test'}, token)[0] == 404)
file_id = scene['files'][0]['fileId']
check('deleted scene file is gone', request(f'{path}/files/{file_id}', token=token)[0] == 404)
audits = json.loads(request('/prod-api/api/v1/audits?limit=100', token=token)[1])['items']
history = [a for a in audits if a['sceneId'] == scene_id]
check('creation and scene deletion audits retained', {'CREATE', 'SCENE_DELETE'} <= {a['action'] for a in history})
check('delete actor recorded', all(a['actorName'] == 'bootstrap' for a in history))

race_files = {'settings.json': b'{"race":true}\n'}
status, body = request(prefix, 'POST', scene_request(name + '-race', race_files), token)
check('race scene created', status == 201)
race = json.loads(body)
race_path = prefix + '/' + race['id']
with ThreadPoolExecutor(2) as pool:
    outcomes = list(pool.map(lambda _: request(race_path + '?expectedVersion=0', 'DELETE', token=token)[0], range(2)))
check('concurrent deletes have one success and no server error',
      204 in outcomes and all(status in (204, 404, 409) for status in outcomes))
check('concurrently deleted scene hidden', request(race_path, token=token)[0] == 404)
(ROOT / 'docs/validation-scene-delete.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
