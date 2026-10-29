"""Headless local Edge verification; no credentials or authenticated traces saved."""
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.local/python'))
from playwright.sync_api import sync_playwright
accounts=json.loads((ROOT/'.local/test-accounts.json').read_text())
errors=[]
with sync_playwright() as p:
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
    dialog=page.get_by_role('dialog')
    name='browser-'+str(uuid.uuid4())[:8]
    dialog.locator('input').nth(0).fill(name)
    assert dialog.locator('input').count()==1
    dialog.get_by_role('button',name='保存',exact=True).click()
    dialog.wait_for(state='hidden')
    row=page.get_by_role('row').filter(has_text=name)
    row.get_by_role('button',name='场景信息',exact=True).click()
    assert dialog.get_by_role('button',name='版本与文件',exact=True).count()==0
    assert [item.inner_text().strip() for item in dialog.locator('.el-dialog__footer').get_by_role('button').all()]==['关闭','保存']
    assert dialog.locator('input').count()==1
    dialog.locator('input').nth(0).fill(name+'-renamed')
    dialog.get_by_role('button',name='保存',exact=True).click()
    dialog.wait_for(state='hidden')
    row.get_by_role('button',name='停用',exact=True).click()
    prompt=page.get_by_role('dialog')
    prompt.locator('input').fill('浏览器验收')
    prompt.get_by_role('button',name='确定',exact=True).click()
    page.wait_for_timeout(600)
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
(ROOT/'docs/validation-browser.json').write_text(json.dumps({'browser':'Microsoft Edge headless','viewport':'1440x1000','passed':True,'checks':['login','create scene','scene info dialog','disable scene','read audit detail','logout'],'pageErrors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
print('PASS browser workflow')
