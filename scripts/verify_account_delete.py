"""Real browser/API checks; only the innovation-ar-resource-platform-infra-check database is modified."""
import hashlib
import json
import secrets
import time
import uuid
from playwright.sync_api import sync_playwright
from verify_infrastructure import BASE, ENV_FILE, ROOT, command, request, check, checks, wait_ready

def sql(statement):
    return command(['exec', '-T', 'postgres', 'psql', '-U', 'innovation', '-d', 'innovation', '-At', '-v', 'ON_ERROR_STOP=1', '-c', statement]).decode().strip()

def api(path, method='GET', body=None, token=None):
    status, content = request('/prod-api' + path, method, body, token)
    return status, json.loads(content) if content else {}

def login(name, password):
    return api('/login', 'POST', {'username': name, 'password': password})[1].get('token')

wait_ready()
settings = dict(line.split('=', 1) for line in ENV_FILE.read_text().splitlines() if line and not line.startswith('#'))
original = sql("select status||','||del_flag from sys_user where user_name='bootstrap'").split(',')
created = []
try:
    token = login('bootstrap', settings['AR_BOOTSTRAP_PASSWORD'])
    assert token, 'Isolated bootstrap must be active before this test'
    for i in range(2):
        name, password = 'del_' + secrets.token_hex(5), secrets.token_urlsafe(20)
        check('create test account ' + str(i), api('/system/user', 'POST', {'userName': name, 'nickName': name, 'password': password}, token)[1].get('code') == 200)
        account_token = login(name, password)
        uid = api('/getInfo', token=account_token)[1]['user']['userId']
        created.append((uid, name, password, account_token))
        if i == 0:
            token = account_token
    owner, victim = created
    path = '/system/user/' + str(victim[0])
    check('anonymous deletion rejected', api(path, 'DELETE')[0] == 401)
    check('self deletion rejected', api('/system/user/' + str(owner[0]), 'DELETE', token=token)[1].get('code') != 200)
    scene = api('/api/v1/scenes', 'POST', {
        'requestKey': str(uuid.uuid4()), 'name': 'account-delete-audit', 'description': '',
        'files': [{'relativePath': 'settings.json', 'bytes': 1, 'sha256': hashlib.sha256(b'x').hexdigest()}]
    }, victim[3])[1]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context()
        context.add_cookies([{'name': 'Admin-Token', 'value': token, 'url': BASE}])
        page = context.new_page()
        deletes = []
        page.on('request', lambda r: deletes.append(r.url) if r.method == 'DELETE' else None)
        page.goto(BASE + '/account/accounts')
        row = page.get_by_role('row').filter(has_text=victim[1])
        row.get_by_role('button', name='删除', exact=True).click()
        dialog = page.get_by_role('dialog', name='删除账号')
        check('confirmation identifies account', victim[1] in dialog.inner_text())
        dialog.get_by_role('button', name='取消', exact=True).click()
        dialog.wait_for(state='hidden')
        check('cancel sends no delete request', not deletes)
        check('cancel preserves login', bool(login(victim[1], victim[2])))
        row.get_by_role('button', name='删除', exact=True).click()
        with page.expect_response(lambda r: r.request.method == 'DELETE') as result:
            page.get_by_role('dialog', name='删除账号').get_by_role('button', name='确认删除', exact=True).click()
        check('confirmed deletion succeeds', result.value.json().get('code') == 200)
        row.wait_for(state='hidden')
        check('only one delete request', len(deletes) == 1)
        browser.close()
    check('deleted account cannot login', not login(victim[1], victim[2]))
    check('old token rejected', api('/getInfo', token=victim[3])[0] == 401)
    check('deleted account cannot be enabled', api('/system/user/changeStatus', 'PUT', {'userId': victim[0], 'status': '0'}, token)[1].get('code') != 200)
    check('deleted account password cannot reset', api('/system/user/resetPwd', 'PUT', {'userId': victim[0], 'password': secrets.token_urlsafe(20)}, token)[1].get('code') != 200)
    check('deleted name remains reserved', api('/system/user', 'POST', {'userName': victim[1], 'nickName': 'test', 'password': victim[2]}, token)[1].get('code') != 200)
    check('last administrator protected', '最后一个' in api('/system/user/' + str(owner[0]), 'DELETE', token=token)[1].get('msg', ''))
    check('historical scene audit retained', sql('select count(*) from ar_audit where actor_id=' + str(victim[0])) == '1')
    bootstrap_id = sql("select user_id from sys_user where user_name='bootstrap'")
    check('disabled bootstrap can be deleted', api('/system/user/' + bootstrap_id, 'DELETE', token=token)[1].get('code') == 200)
    for _ in range(20):
        if int(sql("select count(*) from sys_oper_log where title='删除账号' and status=0 and oper_name='" + owner[1] + "'")) >= 2:
            break
        time.sleep(.2)
    check('account deletions logged', int(sql("select count(*) from sys_oper_log where title='删除账号' and status=0 and oper_name='" + owner[1] + "'")) >= 2)
    (ROOT / 'docs/validation-account-delete.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
finally:
    # Restore only the isolated bootstrap and retire only accounts generated above.
    sql("update sys_user set status='" + original[0] + "',del_flag='" + original[1] + "' where user_name='bootstrap'")
    for uid, *_ in created:
        sql("update sys_user set status='1',del_flag='2' where user_id=" + str(uid))
