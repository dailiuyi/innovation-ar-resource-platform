"""Headless local Edge verification; no credentials or authenticated traces saved."""
import json
from pathlib import Path
import sys
import tempfile
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.local/python'))
from playwright.sync_api import sync_playwright
accounts=json.loads((ROOT/'.local/test-accounts.json').read_text())
errors=[]
with tempfile.TemporaryDirectory() as temporary, sync_playwright() as p:
    package=Path(temporary)/'scene-package'
    (package/'models').mkdir(parents=True)
    (package/'settings.json').write_text('{"browser":true}\n')
    (package/'models'/'00.c.ply').write_text('synthetic browser payload\n')
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    page.on('pageerror',lambda e: errors.append(str(e)))
    page.goto('http://127.0.0.1:43174/login')
    page.get_by_placeholder('账号').fill('demo_a')
    page.get_by_placeholder('密码',exact=True).fill(accounts['demo_a'])
    page.get_by_role('button',name='登 录').click()
    page.wait_for_url('**/index')
    page.get_by_role('button',name='进入场景管理').click()
    page.get_by_role('button',name='新建场景').click()
    drawer=page.locator('.scene-panel')
    drawer.wait_for(state='visible')
    name='browser-'+str(uuid.uuid4())[:8]
    name_field=drawer.locator('input:not([type=file])').first
    name_field.fill(name)
    drawer.locator('textarea').first.fill('浏览器验收合成场景')
    drawer.locator('input[data-import-mode=directory]').set_input_files(str(package))
    page.get_by_text('待导入：2 个文件',exact=False).wait_for()
    drawer.get_by_role('button',name='开始上传',exact=True).click()
    drawer.get_by_text('场景已就绪',exact=False).first.wait_for(timeout=120000)
    drawer.get_by_role('button',name='停止本次传输',exact=True).wait_for(state='hidden',timeout=30000)
    assert 'versionId' not in page.url
    if page.locator('.scene-panel').is_visible():
        page.locator('.scene-panel .el-drawer__close-btn').click()
    page.goto('http://127.0.0.1:43174/admin/scenes')
    row=page.get_by_role('row').filter(has_text=name)
    row.get_by_role('button',name='查看',exact=True).click()
    detail=page.locator('.scene-panel')
    detail.wait_for(state='visible')
    assert detail.get_by_role('button',name='版本与文件',exact=True).count()==0
    assert detail.get_by_role('button',name='开始上传',exact=True).count()==0
    assert detail.get_by_role('button',name='继续上传',exact=True).count()==0
    assert 'sceneId=' in page.url and 'versionId' not in page.url
    assert detail.locator('.scene-meta input').first.input_value()==name
    assert 'settings.json' in detail.inner_text() and 'models/00.c.ply' in detail.inner_text()
    detail.locator('.scene-meta input').first.fill(name+'-renamed')
    detail.locator('.scene-meta textarea').first.fill('浏览器验收已修改描述')
    with page.expect_response(lambda r: r.request.method=='PUT' and '/api/v1/scenes/' in r.url
                              and '/enabled' not in r.url) as saved:
        detail.get_by_role('button',name='保存修改',exact=True).click()
    assert saved.value.status==200
    detail.locator('.el-drawer__close-btn').click()
    row=page.get_by_role('row').filter(has_text=name+'-renamed')
    row.wait_for()
    row.get_by_role('button',name='停用',exact=True).click()
    prompt=page.get_by_role('dialog')
    prompt.locator('input').fill('浏览器验收')
    prompt.get_by_role('button',name='确定',exact=True).click()
    row.get_by_role('button',name='启用',exact=True).wait_for(timeout=10000)
    assert row.get_by_text('停用',exact=True).count()>0
    page.screenshot(path=str(ROOT/'.local/scenes-browser.png'),full_page=True)
    page.goto('http://127.0.0.1:43174/admin/audits')
    page.get_by_role('heading',name='场景操作记录').wait_for()
    page.get_by_role('button',name='查看',exact=True).first.click()
    page.get_by_role('dialog').wait_for()
    page.get_by_role('dialog').locator('.el-dialog__headerbtn').click()
    page.locator('.avatar-container').hover()
    page.get_by_text('退出登录',exact=True).click()
    page.get_by_role('button',name='确定',exact=True).click()
    page.wait_for_url('**/login**')
    assert not errors, errors
    browser.close()
(ROOT/'docs/validation-browser.json').write_text(json.dumps({'browser':'Microsoft Edge headless','viewport':'1440x1000','passed':True,'checks':['login','create scene through unified drawer','fixed file detail','edit metadata','disable scene','read audit detail','logout'],'pageErrors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
print('PASS browser workflow')
