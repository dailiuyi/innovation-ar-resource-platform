"""Real PostgreSQL 17, HTTP and browser ingestion acceptance in a new private local directory.
Never connects to the running Demo database. Keeps failed evidence under .local.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile

from artifact_transfer import restore_tree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / '.local/python'))
import psycopg
from playwright.sync_api import sync_playwright
CHECKS = []
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

def check(name, condition):
    CHECKS.append({'name': name, 'passed': bool(condition)})
    print(('PASS ' if condition else 'FAIL ') + name, flush=True)
    if not condition:
        raise AssertionError(name)

def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path, default=ROOT / 'docs')
    parser.add_argument('--backend-jar', type=Path, default=ROOT / 'backend/ruoyi-admin/target/ruoyi-admin.jar')
    parser.add_argument('--resources-root', type=Path, default=ROOT)
    args = parser.parse_args()
    args.report_dir = args.report_dir.resolve()
    args.backend_jar = args.backend_jar.resolve()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    evidence_root = ROOT / '.local' if args.report_dir == ROOT / 'docs' else args.report_dir
    evidence_root.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='ingestion-check-', dir=evidence_root))
    pg = args.resources_root / '.local/postgresql17/pgsql/bin'
    java = next((args.resources_root / '.local/java21').glob('jdk*/bin/java.exe'))
    pg_port, redis_port, api_port, web_port = [free_port() for _ in range(4)]
    password = secrets.token_urlsafe(24)
    env = dict(os.environ, AR_DATABASE_URL=f'jdbc:postgresql://127.0.0.1:{pg_port}/ingestion',
               AR_DATABASE_USER='ingestion', AR_DATABASE_PASSWORD=password,
               AR_TOKEN_SECRET=secrets.token_urlsafe(64), AR_BOOTSTRAP_PASSWORD=password,
               AR_REDIS_HOST='127.0.0.1', AR_REDIS_PORT=str(redis_port), AR_PORT=str(api_port),
               AR_STORAGE_ENABLED='true', AR_STORAGE_ROOT=str(run / 'artifacts'),
               AR_STORAGE_MAX_BYTES=str(4 * 1024 * 1024), AR_UPLOAD_DIR=str(run / 'framework-uploads'),
               AR_DEV_API_TARGET=f'http://127.0.0.1:{api_port}', PGPASSWORD=password)
    base = f'http://127.0.0.1:{api_port}'
    token = None
    processes = []
    logs = []
    pg_started = False
    db = None
    def cmd(args):
        with tempfile.TemporaryFile() as output:
            r = subprocess.run([str(a) for a in args], env=env, cwd=run, creationflags=FLAGS, stdout=output, stderr=subprocess.STDOUT)
            output.seek(0)
            content = output.read()
        if r.returncode:
            (run / 'command-error.log').write_bytes(content)
            raise RuntimeError('Test command failed; inspect local command-error.log')
        return content.decode(errors='replace')
    def start(name, args, cwd=run):
        log = (run / (name + '.log')).open('ab'); logs.append(log)
        p = subprocess.Popen([str(a) for a in args], cwd=cwd, env=env, creationflags=FLAGS, stdout=log, stderr=log)
        processes.append(p)
        return p
    def api(path, method='GET', body=None, auth=True, raw=False):
        headers = {'Content-Type': 'application/octet-stream' if raw else 'application/json'}
        if auth and token:
            headers['Authorization'] = 'Bearer ' + token
        data = body if raw else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                content = r.read(); return r.status, json.loads(content) if content else {}
        except urllib.error.HTTPError as e:
            content = e.read(); return e.code, json.loads(content) if content else {}
    def api_bytes(path, method='GET', body=None, auth=True, headers=None):
        hdrs = {} if headers is None else dict(headers)
        if auth and token:
            hdrs['Authorization'] = 'Bearer ' + token
        if body is not None:
            hdrs.setdefault('Content-Type', 'application/octet-stream')
        req = urllib.request.Request(base + path, data=body, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()
    def start_backend():
        p = start('backend', [java, '-Duser.timezone=UTC', '-jar', args.backend_jar, '--server.address=127.0.0.1'])
        until = time.monotonic() + 120
        while time.monotonic() < until:
            if p.poll() is not None:
                raise RuntimeError('Backend exited; inspect ' + str(run / 'backend.log'))
            try:
                if api('/captchaImage', auth=False)[0] == 200:
                    return p
            except OSError:
                pass
            time.sleep(.5)
        raise RuntimeError('Backend startup timed out')
    def sql(statement, args=()):
        with db.cursor() as c:
            c.execute(statement, args)
            return c.fetchall() if c.description else []
    try:
        version = cmd([pg / 'postgres.exe', '--version']).strip()
        check('real PostgreSQL 17 runtime', ' 17.' in version)
        pw = run / 'init-password'; pw.write_text(password)
        try:
            cmd([pg / 'initdb.exe', '-D', run / 'pgdata', '-U', 'ingestion', '--pwfile=' + str(pw), '--auth=scram-sha-256', '--encoding=UTF8', '--locale=C'])
        finally:
            pw.unlink(missing_ok=True)
        cmd([pg / 'pg_ctl.exe', '-D', run / 'pgdata', '-l', run / 'postgres.log', '-o', f'-h 127.0.0.1 -p {pg_port}', '-w', 'start'])
        pg_started = True
        cmd([pg / 'createdb.exe', '-h', '127.0.0.1', '-p', str(pg_port), '-U', 'ingestion', 'ingestion'])
        db = psycopg.connect(host='127.0.0.1', port=pg_port, dbname='ingestion', user='ingestion', password=password, autocommit=True)
        start('redis', ['redis-server', '--bind', '127.0.0.1', '--port', str(redis_port), '--save', '', '--appendonly', 'no'])
        backend = start_backend()
        token = api('/login', 'POST', {'username':'bootstrap','password':password}, auth=False)[1].get('token')
        check('administrator login', bool(token))
        check('anonymous config rejected', api('/api/v1/drafts/config', auth=False)[0] == 401)
        check('anonymous publish rejected', api('/api/v1/drafts/'+str(uuid.uuid4())+'/publish','POST',{'expectedSceneVersion':0},auth=False)[0]==401)
        scene = api('/api/v1/scenes', 'POST', {'name':'ingestion-acceptance'})[1]
        scene_id = scene['id']
        create = {'requestKey':str(uuid.uuid4()),'description':'first draft'}
        path = f'/api/v1/scenes/{scene_id}/drafts'
        code, draft = api(path, 'POST', create)
        check('create scene draft', code == 200 and draft['sceneId'] == scene_id)
        draft_id = draft['id']; dp = '/api/v1/drafts/' + draft_id
        check('draft create retry is idempotent', api(path,'POST',create)[1]['id'] == draft_id and api(path)[1]['total'] == 1)
        check('missing scene draft rejected', api('/api/v1/scenes/'+str(uuid.uuid4())+'/drafts','POST',create)[0] == 404)
        gone = api('/api/v1/scenes','POST',{'name':'deleted-scene'})[1]
        api('/api/v1/scenes/'+gone['id']+'?expectedVersion=0','DELETE')
        check('deleted scene draft rejected', api('/api/v1/scenes/'+gone['id']+'/drafts','POST',create)[0] == 404)
        check('edit draft description', api(dp,'PUT',{'description':'updated','expectedVersion':0})[1]['description']=='updated')
        check('stale edit rejected', api(dp,'PUT',{'description':'stale','expectedVersion':0})[0] == 409)
        def register(name, data, **overrides):
            body = dict(requestKey=str(uuid.uuid4()),fileName=name,kind='RESOURCE_FILE',bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
            body.update(overrides)
            return api(dp+'/files','POST',body), body
        def upload(record, data):
            return api(dp+'/files/'+record['id']+'/content','PUT',data,raw=True)
        def current(record):
            return sql('select status from ar_draft_file where id=%s',(record['id'],))[0][0]
        a = b'first synthetic resource\n'; b = b'second resource\x00\x01'
        (code, first), meta = register('first.bin',a)
        check('register pending file', code == 200 and first['status']=='PENDING' and first.get('relativePath')=='first.bin')
        check('registration retry returns same row', api(dp+'/files','POST',meta)[1]['id'] == first['id'])
        check('idempotency key metadata conflict', api(dp+'/files','POST',{**meta,'bytes':len(a)+1})[0]==409)
        check('first upload available', upload(first,a)[1]['status']=='AVAILABLE')
        check('duplicate content submission stays available', upload(first,a)[1]['status']=='AVAILABLE')
        (code, second), _ = register('second.bin',b)
        check('second different file available', upload(second,b)[1]['status']=='AVAILABLE')
        check('two files associated with one draft', api(dp+'/files')[1]['total']==2)
        for record,data in ((first,a),(second,b)):
            actual=(run/'artifacts/committed'/record['storageKey']).read_bytes()
            check('formal storage bytes and SHA256 '+record['fileName'],len(actual)==len(data) and hashlib.sha256(actual).digest()==hashlib.sha256(data).digest())
        check('oversized declaration rejected', register('oversize.bin',b'',bytes=4*1024*1024+1)[0][0]==413)
        (_, mismatch), _=register('mismatch.bin',a,sha256='0'*64)
        check('digest mismatch rejected and not available', upload(mismatch,a)[0]==422 and current(mismatch)=='FAILED')
        (_, oversized), _=register('actual-too-large.bin',a)
        check('actual size exceeds declaration rejected', upload(oversized,a+b)[0]==422 and current(oversized)=='FAILED')
        check('failure reason identifies digest mismatch', 'SHA256' in sql('select failure_reason from ar_draft_file where id=%s',(mismatch['id'],))[0][0])
        check('failed files absent from formal storage', not (run/'artifacts/committed'/mismatch['storageKey']).exists() and not (run/'artifacts/committed'/oversized['storageKey']).exists())
        check('AAR requires client library category', register('sample.aar',a)[0][0]==400)
        (_, aar), _=register('sample.aar',a,kind='CLIENT_LIBRARY')
        check('AAR registered only as client library', upload(aar,a)[1]['kind']=='CLIENT_LIBRARY')
        (_, removed), removed_meta=register('remove-me.bin',a)
        upload(removed,a)
        remove_path=dp+'/files/'+removed['id']
        check('anonymous file removal rejected',api(remove_path,'DELETE',auth=False)[0]==401)
        check('wrong draft cannot remove file',api('/api/v1/drafts/'+str(uuid.uuid4())+'/files/'+removed['id'],'DELETE')[0]==404)
        check('remove uploaded file',api(remove_path,'DELETE')[0]==204)
        check('repeat removal is idempotent',api(remove_path,'DELETE')[0]==204)
        check('removed file hidden from list',removed['id'] not in [x['id'] for x in api(dp+'/files')[1]['items']])
        check('physical deletion removes formal bytes',not (run/'artifacts/committed'/removed['storageKey']).exists())
        check('physical deletion removes file row',sql('select count(*) from ar_draft_file where id=%s',(removed['id'],))[0][0]==0)
        check('removed file cannot upload',upload(removed,a)[0]==404)
        check('old registration key cannot resurrect file',api(dp+'/files','POST',removed_meta)[0]==410)
        (_, replacement), _=register('remove-me.bin',a)
        check('new registration can readd removed file',replacement['id']!=removed['id'] and upload(replacement,a)[1]['status']=='AVAILABLE')
        check('removal audit is attributable and singular',sql("select count(*) from ar_audit where action='FILE_DELETE' and detail->>'fileId'=%s and actor_name='bootstrap'",(removed['id'],))[0][0]==1)
        check('failed file can be removed',api(dp+'/files/'+oversized['id'],'DELETE')[0]==204)
        empty={'requestKey':str(uuid.uuid4()),'description':'empty-to-delete'}
        empty_id=api(path,'POST',empty)[1]['id']
        check('anonymous draft removal rejected',api('/api/v1/drafts/'+empty_id,'DELETE',auth=False)[0]==401)
        check('remove empty draft',api('/api/v1/drafts/'+empty_id,'DELETE')[0]==204)
        check('repeat draft removal is idempotent',api('/api/v1/drafts/'+empty_id,'DELETE')[0]==204)
        check('removed draft hidden from list',empty_id not in [x['id'] for x in api(path)[1]['items']])
        packed={'requestKey':str(uuid.uuid4()),'description':'packed-to-delete'}
        packed_id=api(path,'POST',packed)[1]['id']
        packed_path='/api/v1/drafts/'+packed_id
        packed_body=dict(requestKey=str(uuid.uuid4()),fileName='packed.bin',kind='RESOURCE_FILE',bytes=len(a),sha256=hashlib.sha256(a).hexdigest())
        packed_file=api(packed_path+'/files','POST',packed_body)[1]
        check('packed draft file available',api(packed_path+'/files/'+packed_file['id']+'/content','PUT',a,raw=True)[1]['status']=='AVAILABLE')
        packed_key=packed_file['storageKey']
        check('remove draft with files',api(packed_path,'DELETE')[0]==204)
        check('removed draft row gone',sql('select count(*) from ar_draft where id=%s',(packed_id,))[0][0]==0)
        check('removed draft files physically gone',sql('select count(*) from ar_draft_file where draft_id=%s',(packed_id,))[0][0]==0 and not (run/'artifacts/committed'/packed_key).exists())
        check('removed draft cannot be edited',api(packed_path,'PUT',{'description':'gone','expectedVersion':0})[0]==404)
        check('draft deletion audit is attributable',sql("select count(*) from ar_audit where action='DRAFT_DELETE' and detail->>'draftId'=%s and actor_name='bootstrap'",(packed_id,))[0][0]==1)
        check('same request key can create a new draft after deletion',api(path,'POST',packed)[1]['id']!=packed_id)
        (_, pending_removal), _=register('pending-removal.bin',a)
        check('pending file can be removed',api(dp+'/files/'+pending_removal['id'],'DELETE')[0]==204)
        # Inject a non-regular storage target so delete fails without deleting the DB row.
        (_, delete_failure), _=register('delete-failure.bin',a)
        blocked=run/'artifacts/committed'/delete_failure['storageKey']
        blocked.mkdir()
        check('storage deletion failure reports 503',api(dp+'/files/'+delete_failure['id'],'DELETE')[0]==503)
        failing=next(x for x in api(dp+'/files')[1]['items'] if x['id']==delete_failure['id'])
        check('failed deletion stays visible and retryable',failing['status']=='DELETE_FAILED' and bool(failing['failureReason']))
        check('deletion in progress rejects upload',upload(delete_failure,a)[0]==404)
        blocked.rmdir()
        check('failed deletion retry completes',api(dp+'/files/'+delete_failure['id'],'DELETE')[0]==204 and not sql('select id from ar_draft_file where id=%s',(delete_failure['id'],)))
        # Durable intent snapshots at both crash boundaries (before unlink / after unlink).
        recovery_ids=[]
        for stage in ('before-unlink','after-unlink'):
            (_, item), _=register(stage+'.bin',a)
            upload(item,a)
            sql("insert into ar_file_deletion(file_id,draft_id,request_key,actor_id,actor_name) select id,draft_id,request_key,creator_id,creator_name from ar_draft_file where id=%s",(item['id'],))
            if stage=='after-unlink':(run/'artifacts/committed'/item['storageKey']).unlink()
            recovery_ids.append(item)
        # Existing logical removals must not be physically purged without explicit selection.
        (_, legacy), _=register('legacy-removal.bin',a)
        upload(legacy,a)
        sql('update ar_draft_file set removed_at=now(),removed_by=creator_id where id=%s',(legacy['id'],))
        (_, interrupted), _=register('interrupted.bin',a*5000)
        def begin_partial(record, data):
            sock=socket.create_connection(('127.0.0.1',api_port),timeout=10)
            head=f"PUT {dp}/files/{record['id']}/content HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {token}\r\nContent-Type: application/octet-stream\r\nContent-Length: {len(data)}\r\nConnection: close\r\n\r\n"
            sock.sendall(head.encode()+data[:32])
            until=time.monotonic()+10
            while current(record)!='UPLOADING' and time.monotonic()<until: time.sleep(.05)
            check('partial request durably marked uploading',current(record)=='UPLOADING')
            return sock
        sock=begin_partial(interrupted,a*5000)
        check('active upload cannot be removed',api(dp+'/files/'+interrupted['id'],'DELETE')[0]==409)
        check('active upload blocks draft deletion',api(dp,'DELETE')[0]==409)
        check('concurrent upload rejected without false success',upload(interrupted,a*5000)[0]==409)
        sock.shutdown(socket.SHUT_RDWR);sock.close()
        until=time.monotonic()+10
        while current(interrupted)=='UPLOADING' and time.monotonic()<until: time.sleep(.05)
        check('disconnected upload marked failed',current(interrupted)=='FAILED')
        check('interrupted upload retry succeeds with same file id',upload(interrupted,a*5000)[1]['id']==interrupted['id'] and current(interrupted)=='AVAILABLE')
        (_, crash), _=register('crash.bin',a*6000)
        crash_socket=begin_partial(crash,a*6000)
        (_, staged), _=register('staged.bin',b)
        (run/'artifacts/staging'/(staged['id']+'.ready')).write_bytes(b)
        (_, ack), _=register('ack-lost.bin',a)
        (run/'artifacts/committed'/ack['storageKey']).write_bytes(a)
        (_, pending), _=register('pending.bin',b)
        backend.kill();backend.wait(timeout=15);crash_socket.close()
        check('hard-stopped service retains unfinished record',current(crash)=='UPLOADING')
        backend=start_backend()
        check('restart does not restore removed files',removed['id'] not in [x['id'] for x in api(dp+'/files')[1]['items']] and sql('select count(*) from ar_draft_file where id=%s',(removed['id'],))[0][0]==0 and not (run/'artifacts/committed'/removed['storageKey']).exists())
        check('restart completes interrupted physical deletions',all(not sql('select id from ar_draft_file where id=%s',(x['id'],)) and not (run/'artifacts/committed'/x['storageKey']).exists() and sql('select completed_at is not null from ar_file_deletion where file_id=%s',(x['id'],))[0][0] for x in recovery_ids))
        check('legacy removals not purged automatically',(run/'artifacts/committed'/legacy['storageKey']).exists() and bool(sql('select id from ar_draft_file where id=%s',(legacy['id'],))))
        check('completed files remain available after restart',current(first)=='AVAILABLE' and current(second)=='AVAILABLE')
        check('restart identifies interrupted upload and leaves untouched pending',current(crash)=='FAILED' and current(pending)=='PENDING')
        check('restart reconciles ready and committed files',current(staged)=='AVAILABLE' and current(ack)=='AVAILABLE')
        check('explicit legacy deletion clears bytes and row',api(dp+'/files/'+legacy['id'],'DELETE')[0]==204 and not (run/'artifacts/committed'/legacy['storageKey']).exists() and not sql('select id from ar_draft_file where id=%s',(legacy['id'],)))
        check('retry after service restart succeeds',upload(crash,a*6000)[1]['status']=='AVAILABLE')
        check('no duplicate registration after retries',sql('select count(*) from ar_draft_file where draft_id=%s and request_key=%s',(draft_id,meta['requestKey']))[0][0]==1)
        actor=api('/getInfo')[1]['user']['userId']
        check('audit identifies actor draft and file',sql("select count(*) from ar_audit where actor_id=%s and detail->>'draftId'=%s and detail->>'fileId'=%s and action='FILE_AVAILABLE'",(actor,draft_id,first['id']))[0][0]==1)
        check('reconciliation audit marks system action',sql("select count(*) from ar_audit where detail->>'draftId'=%s and detail->>'performedBy'='SYSTEM_RECONCILIATION'",(draft_id,))[0][0]>=4)
        check('anonymous upload rejected',api(dp+'/files/'+first['id']+'/content','PUT',a,auth=False,raw=True)[0]==401)
        # A real authenticated account with no administrator role.
        api('/system/user','POST',{'userName':'nonadmin','nickName':'nonadmin','password':password})
        uid=sql("select user_id from sys_user where user_name='nonadmin'")[0][0]
        sql('delete from sys_user_role where user_id=%s',(uid,))
        admin_token=token
        token=api('/login','POST',{'username':'nonadmin','password':password},auth=False)[1].get('token')
        check('nonadministrator authenticated',bool(token))
        check('nonadministrator removal forbidden',api(dp+'/files/'+first['id'],'DELETE')[0]==403)
        check('nonadministrator draft removal forbidden',api(dp,'DELETE')[0]==403)
        check('nonadministrator draft access forbidden',api(dp)[0]==403 and api(path,'POST',create)[0]==403)
        check('nonadministrator publish forbidden',api(dp+'/publish','POST',{'expectedSceneVersion':0})[0]==403)
        # Account creation intentionally retires bootstrap in the application. Restore only this
        # synthetic isolated account for the subsequent browser checks, then obtain a fresh token.
        sql("update sys_user set status='0',del_flag='0' where user_name='bootstrap'")
        token=api('/login','POST',{'username':'bootstrap','password':password},auth=False)[1].get('token')
        check('fresh administrator session for browser',bool(token))
        pub_scene=api('/api/v1/scenes','POST',{'name':'publication-acceptance'})[1]
        pub_path=f"/api/v1/scenes/{pub_scene['id']}/drafts"
        listed=api(pub_path)[1]
        check('draft list includes publication fields', 'published' not in listed and isinstance(listed.get('sceneLockVersion'),int))
        empty_pub=api(pub_path,'POST',{'requestKey':str(uuid.uuid4()),'description':'empty-cannot-publish'})[1]
        check('empty draft cannot publish', api('/api/v1/drafts/'+empty_pub['id']+'/publish','POST',{'expectedSceneVersion':listed['sceneLockVersion']})[0]==400)
        check('empty draft cannot download', api('/api/v1/drafts/'+empty_pub['id']+'/download-manifest')[0]==400)
        api('/api/v1/drafts/'+empty_pub['id'],'DELETE')
        first_pub=api(pub_path,'POST',{'requestKey':str(uuid.uuid4()),'description':'publish-me'})[1]
        first_pub_path='/api/v1/drafts/'+first_pub['id']
        first_pub_file=api(first_pub_path+'/files','POST',dict(requestKey=str(uuid.uuid4()),fileName='publish.bin',kind='RESOURCE_FILE',bytes=len(a),sha256=hashlib.sha256(a).hexdigest()))[1]
        check('publication source file available', api(first_pub_path+'/files/'+first_pub_file['id']+'/content','PUT',a,raw=True)[1]['status']=='AVAILABLE')
        listed=api(pub_path)[1]
        check('stale scene version rejected', api(first_pub_path+'/publish','POST',{'expectedSceneVersion':listed['sceneLockVersion']+1})[0]==409)
        code, published_draft=api(first_pub_path+'/publish','POST',{'expectedSceneVersion':listed['sceneLockVersion']})
        check('publish draft', code==200 and published_draft.get('published') is True)
        check('publish increments scene lock version', api('/api/v1/scenes/'+pub_scene['id'])[1]['lockVersion']==listed['sceneLockVersion']+1)
        listed=api(pub_path)[1]
        check('one published pointer', listed['published']['id']==first_pub['id'] and sum(1 for x in listed['items'] if x['published'])==1)
        check('repeat publish is idempotent', api(first_pub_path+'/publish','POST',{'expectedSceneVersion':listed['sceneLockVersion']})[1]['published'] is True)
        frozen=dict(requestKey=str(uuid.uuid4()),fileName='frozen.bin',kind='RESOURCE_FILE',bytes=len(a),sha256=hashlib.sha256(a).hexdigest())
        check('published files are frozen', api(first_pub_path+'/files','POST',frozen)[0]==409)
        check('published file cannot be deleted', api(first_pub_path+'/files/'+first_pub_file['id'],'DELETE')[0]==409)
        check('published draft cannot be deleted', api(first_pub_path,'DELETE')[0]==409)
        edited=api(first_pub_path,'PUT',{'description':'published-updated','expectedVersion':published_draft['lockVersion']})[1]
        check('published description can still be edited', edited['description']=='published-updated' and edited['published'] is True)
        other=api(pub_path,'POST',{'requestKey':str(uuid.uuid4()),'description':'replacement'})[1]
        other_path='/api/v1/drafts/'+other['id']
        other_file=api(other_path+'/files','POST',dict(requestKey=str(uuid.uuid4()),fileName='replacement.bin',kind='RESOURCE_FILE',bytes=len(a),sha256=hashlib.sha256(a).hexdigest()))[1]
        check('replacement file available', api(other_path+'/files/'+other_file['id']+'/content','PUT',a,raw=True)[1]['status']=='AVAILABLE')
        listed=api(pub_path)[1]
        code, replaced=api(other_path+'/publish','POST',{'expectedSceneVersion':listed['sceneLockVersion']})
        check('replace publication', code==200 and replaced['published'] is True and api(pub_path)[1]['published']['id']==other['id'])
        check('previous published returns to draft', api(first_pub_path)[1]['published'] is False)
        check('unfrozen draft can register files', api(first_pub_path+'/files','POST',frozen)[0]==200)
        check('previous published can be deleted after replace', api(first_pub_path,'DELETE')[0]==204)
        check('publish audit is attributable', sql("select count(*) from ar_audit where action='DRAFT_PUBLISH' and detail->>'toDraftId'=%s and actor_name='bootstrap'",(other['id'],))[0][0]==1)
        listed=api(pub_path)[1]
        ingest_listed=api(f'/api/v1/scenes/{scene_id}/drafts')[1]
        check('failed files cannot publish', api(dp+'/publish','POST',{'expectedSceneVersion':ingest_listed['sceneLockVersion']})[0]==400)
        check('failed files cannot download', api(dp+'/download-manifest')[0]==400)
        folder_draft=api(pub_path,'POST',{'requestKey':str(uuid.uuid4()),'description':'folder-replace'})[1]
        folder_path='/api/v1/drafts/'+folder_draft['id']
        keep=b'keep-old\n'
        keep_file=api(folder_path+'/files','POST',dict(requestKey=str(uuid.uuid4()),fileName='keep.bin',kind='RESOURCE_FILE',bytes=len(keep),sha256=hashlib.sha256(keep).hexdigest()))[1]
        check('replacement source available', api(folder_path+'/files/'+keep_file['id']+'/content','PUT',keep,raw=True)[1]['status']=='AVAILABLE')
        nested=b'nested-zh\n'; zero=b''; same=b'same-name\n'
        folder_items=[
            dict(requestKey=str(uuid.uuid4()),relativePath='场景A/models/a.bundle',kind='RESOURCE_FILE',bytes=len(nested),sha256=hashlib.sha256(nested).hexdigest()),
            dict(requestKey=str(uuid.uuid4()),relativePath='场景A/models/zero.bin',kind='RESOURCE_FILE',bytes=0,sha256=hashlib.sha256(zero).hexdigest()),
            dict(requestKey=str(uuid.uuid4()),relativePath='场景A/other/a.bundle',kind='RESOURCE_FILE',bytes=len(same),sha256=hashlib.sha256(same).hexdigest()),
        ]
        payloads={'场景A/models/a.bundle':nested,'场景A/models/zero.bin':zero,'场景A/other/a.bundle':same}
        check('path traversal rejected', api(folder_path+'/replacements','POST',{'requestKey':str(uuid.uuid4()),'files':[{**folder_items[0],'relativePath':'../escape.bin'}]})[0]==400)
        batch_key=str(uuid.uuid4())
        code, batch=api(folder_path+'/replacements','POST',{'requestKey':batch_key,'files':folder_items})
        check('folder replacement starts', code==200 and batch['status']=='PENDING' and batch['fileCount']==3)
        check('same replacement resume', api(folder_path+'/replacements','POST',{'requestKey':batch_key,'files':folder_items})[1]['id']==batch['id'])
        check('changed replacement fingerprint rejected', api(folder_path+'/replacements','POST',{'requestKey':batch_key,'files':folder_items[:1]})[0]==409)
        check('download blocked during replacement', api(folder_path+'/download-manifest')[0]==409)
        listed=api(pub_path)[1]
        check('publish blocked during replacement', api(folder_path+'/publish','POST',{'expectedSceneVersion':listed['sceneLockVersion']})[0]==409)
        check('append blocked during replacement', api(folder_path+'/files','POST',dict(requestKey=str(uuid.uuid4()),fileName='extra.bin',kind='RESOURCE_FILE',bytes=len(keep),sha256=hashlib.sha256(keep).hexdigest()))[0]==409)
        check('current files remain during replacement', api(folder_path+'/files')[1]['total']==1 and api(folder_path+'/files')[1]['items'][0]['fileName']=='keep.bin')
        check('cancel replacement restores old collection', api(folder_path+'/replacements/'+batch['id']+'/cancel','POST')[0]==200 and api(folder_path+'/files')[1]['items'][0]['fileName']=='keep.bin')
        check('cancelled batch key cannot restart', api(folder_path+'/replacements','POST',{'requestKey':batch_key,'files':folder_items})[0]==409)
        check('case-insensitive path prefix rejected', api(folder_path+'/replacements','POST',{'requestKey':str(uuid.uuid4()),'files':[
            dict(requestKey=str(uuid.uuid4()),relativePath='root/A',kind='RESOURCE_FILE',bytes=len(keep),sha256=hashlib.sha256(keep).hexdigest()),
            dict(requestKey=str(uuid.uuid4()),relativePath='root/a/b.bin',kind='RESOURCE_FILE',bytes=len(keep),sha256=hashlib.sha256(keep).hexdigest()),
        ]})[0]==400)
        code, batch=api(folder_path+'/replacements','POST',{'requestKey':str(uuid.uuid4()),'files':folder_items})
        check('replacement after cancel', code==200)
        for item in batch['items']:
            data=payloads[item['relativePath']]
            check('replacement file available '+item['relativePath'], api(folder_path+'/files/'+item['id']+'/content','PUT',data,raw=True)[1]['status']=='AVAILABLE')
        check('replacement switched current files', api(folder_path+'/files')[1]['total']==3)
        check('old collection file removed', sql("select count(*) from ar_draft_file where id=%s",(keep_file['id'],))[0][0]==0)
        man=api(folder_path+'/download-manifest')[1]
        check('manifest lists all relative paths', sorted(x['relativePath'] for x in man['files'])==sorted(payloads) and man['fileCount']==3)
        tree=run/'restored-tree'
        restore_tree(man, tree, base, {'Authorization':'Bearer '+token})
        check('restored tree matches manifest', all((tree/p).read_bytes()==payloads[p] and hashlib.sha256((tree/p).read_bytes()).hexdigest()==hashlib.sha256(payloads[p]).hexdigest() for p in payloads))
        file0=man['files'][0]
        st, hdrs, body=api_bytes(file0['downloadPath'].split(base)[-1] if file0['downloadPath'].startswith('http') else file0['downloadPath'], headers={'Range':'bytes=0-3'})
        check('single file range 206', st==206 and body==payloads[file0['relativePath']][:4] and hdrs.get('ETag')=='"'+file0['sha256']+'"')
        st, hdrs, body=api_bytes(file0['downloadPath'] if file0['downloadPath'].startswith('/') else '/'+file0['downloadPath'], headers={'Range':'bytes=999999-'})
        check('single file range 416', st==416)
        st, hdrs, body=api_bytes(file0['downloadPath'], method='HEAD')
        check('single file head', st==200 and int(hdrs.get('Content-Length','-1'))==file0['bytes'] and body==b'')
        zip_code, exported=api(folder_path+'/zip-exports','POST',{'collectionId':man['collectionId'],'generation':man['generation']})
        check('zip export available', zip_code==200 and exported.get('status')=='AVAILABLE' and exported.get('bytes',0)>0)
        st, hdrs, zbody=api_bytes(exported['downloadPath'])
        check('zip download bytes', st==200 and hashlib.sha256(zbody).hexdigest()==exported['sha256'] and len(zbody)==exported['bytes'])
        with zipfile.ZipFile(io.BytesIO(zbody)) as archive:
            names=set(archive.namelist())
            check('zip entries match manifest', names==set(payloads) and all(archive.read(name)==payloads[name] for name in payloads))
        reused=api(folder_path+'/zip-exports','POST',{'collectionId':man['collectionId'],'generation':man['generation']})[1]
        check('zip export reused', reused['id']==exported['id'])
        st, hdrs, zpart=api_bytes(exported['downloadPath'], headers={'Range':'bytes=0-10'})
        check('zip range 206', st==206 and zpart==zbody[:11])
        # A build that is still running answers 409, and that answer must be distinguishable from other conflicts.
        preparing_draft=api(pub_path,'POST',{'requestKey':str(uuid.uuid4()),'description':'zip preparing conflict'})[1]
        preparing_path='/api/v1/drafts/'+preparing_draft['id']
        preparing_file=api(preparing_path+'/files','POST',dict(requestKey=str(uuid.uuid4()),fileName='prep.bin',kind='RESOURCE_FILE',bytes=len(a),sha256=hashlib.sha256(a).hexdigest()))[1]
        check('zip preparing fixture file available', api(preparing_path+'/files/'+preparing_file['id']+'/content','PUT',a,raw=True)[1]['status']=='AVAILABLE')
        preparing_man=api(preparing_path+'/download-manifest')[1]
        in_flight=uuid.uuid4()
        sql("insert into ar_zip_export(id, collection_id, generation, status) values(%s, %s, %s, 'PREPARING')",
            (str(in_flight), preparing_man['collectionId'], preparing_man['generation']))
        code, still_preparing=api(preparing_path+'/zip-exports','POST',{'collectionId':preparing_man['collectionId'],'generation':preparing_man['generation']})
        check('an in-flight build answers still preparing', code==409 and still_preparing.get('message')=='ZIP 正在准备，请稍后重试')
        sql('delete from ar_zip_export where id=%s',(str(in_flight),))
        code, after_build=api(preparing_path+'/zip-exports','POST',{'collectionId':preparing_man['collectionId'],'generation':preparing_man['generation']})
        check('manual retry after a still-preparing answer reuses the finished zip', code==200 and after_build.get('status')=='AVAILABLE' and after_build.get('bytes',0)>0)
        st, hdrs, after_body=api_bytes(after_build['downloadPath'])
        check('zip finished after the conflict downloads with a matching digest', st==200 and len(after_body)==after_build['bytes'] and hashlib.sha256(after_body).hexdigest()==after_build['sha256'])
        check('anonymous manifest rejected', api(folder_path+'/download-manifest',auth=False)[0]==401)
        check('anonymous zip rejected', api(folder_path+'/zip-exports','POST',{'collectionId':man['collectionId'],'generation':man['generation']},auth=False)[0]==401)
        check('anonymous file download rejected', api_bytes(file0['downloadPath'], auth=False)[0]==401)
        reserved_id=uuid.uuid4()
        check('legacy reserved name gets safe export path', sql("select ar_safe_export_path('CON.txt', %s)",(str(reserved_id),))[0][0]=='export-'+str(reserved_id)[:8]+'.txt')
        check('legacy colon name is sanitized', sql("select ar_safe_export_path('report:2026.txt', %s)",(str(uuid.uuid4()),))[0][0]=='report_2026.txt')
        crash_draft=api(pub_path,'POST',{'requestKey':str(uuid.uuid4()),'description':'startup-switch'})[1]
        crash_path='/api/v1/drafts/'+crash_draft['id']
        keep_crash=api(crash_path+'/files','POST',dict(requestKey=str(uuid.uuid4()),fileName='keep-crash.bin',kind='RESOURCE_FILE',bytes=len(keep),sha256=hashlib.sha256(keep).hexdigest()))[1]
        check('startup replacement seed', api(crash_path+'/files/'+keep_crash['id']+'/content','PUT',keep,raw=True)[1]['status']=='AVAILABLE')
        crash_items=[
            dict(requestKey=str(uuid.uuid4()),relativePath='场景C/a.bin',kind='RESOURCE_FILE',bytes=len(nested),sha256=hashlib.sha256(nested).hexdigest()),
        ]
        crash_batch=api(crash_path+'/replacements','POST',{'requestKey':str(uuid.uuid4()),'files':crash_items})[1]
        last=crash_batch['items'][0]
        (run/'artifacts/committed'/(last['id']+'.bin')).write_bytes(nested)
        sql("update ar_draft_file set status='AVAILABLE', verified_bytes=expected_bytes, verified_sha256=expected_sha256, failure_reason=null where id=%s",(last['id'],))
        check('pending replacement complete before restart', sql("select status from ar_draft_collection where id=%s",(crash_batch['id'],))[0][0]=='PENDING')
        backend.kill();backend.wait(timeout=15)
        backend=start_backend()
        check('startup recovers completed replacement without login', api(crash_path+'/files')[1]['total']==1 and api(crash_path+'/files')[1]['items'][0]['relativePath']=='场景C/a.bin')
        check('startup switch audit marks system recovery', sql("select count(*) from ar_audit where action='COLLECTION_REPLACE_SWITCH' and detail->>'collectionId'=%s and detail->>'performedBy'='SYSTEM_RECONCILIATION'",(crash_batch['id'],))[0][0]==1)
        blob=os.urandom(2*1024*1024)
        held_file=api(folder_path+'/files','POST',dict(requestKey=str(uuid.uuid4()),fileName='held.bin',kind='RESOURCE_FILE',bytes=len(blob),sha256=hashlib.sha256(blob).hexdigest()))[1]
        check('download lock fixture uploaded', api(folder_path+'/files/'+held_file['id']+'/content','PUT',blob,raw=True)[1]['status']=='AVAILABLE')
        held_man=api(folder_path+'/download-manifest')[1]
        held_item=next(x for x in held_man['files'] if x['fileName']=='held.bin')
        held=threading.Event(); consume=threading.Event(); download_error=[]
        def hold_download():
            try:
                req=urllib.request.Request(base+held_item['downloadPath'], headers={'Authorization':'Bearer '+token})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    held.set()
                    consume.wait(timeout=30)
                    resp.read()
            except Exception as exc:
                download_error.append(exc); held.set()
        worker=threading.Thread(target=hold_download); worker.start()
        check('download started before delete', held.wait(timeout=15))
        delete_code=api(folder_path+'/files/'+held_file['id'],'DELETE')[0]
        check('delete during download conflicts', delete_code==409)
        consume.set(); worker.join(timeout=15)
        check('held download did not fail the server', download_error==[])
        held2=threading.Event(); consume2=threading.Event(); zip_code={'v':None}
        def hold_then_pack():
            req=urllib.request.Request(base+held_item['downloadPath'], headers={'Authorization':'Bearer '+token})
            with urllib.request.urlopen(req, timeout=60) as resp:
                held2.set()
                consume2.wait(timeout=30)
                resp.read()
        def pack_zip():
            held2.wait(timeout=15)
            zip_code['v']=api(folder_path+'/zip-exports','POST',{'collectionId':held_man['collectionId'],'generation':held_man['generation']})[0]
        holder=threading.Thread(target=hold_then_pack); packer=threading.Thread(target=pack_zip)
        holder.start(); packer.start()
        check('download held for zip concurrency', held2.wait(timeout=15))
        zip_delete=api(folder_path+'/files/'+held_file['id'],'DELETE')[0]
        consume2.set(); holder.join(timeout=15); packer.join(timeout=30)
        check('delete during zip pack conflicts', zip_delete==409)
        start('vite',['node',ROOT/'frontend/node_modules/vite/bin/vite.js','--host','127.0.0.1','--port',str(web_port),'--strictPort'],ROOT/'frontend')
        web=f'http://127.0.0.1:{web_port}'
        until=time.monotonic()+30
        while time.monotonic()<until:
            try:
                urllib.request.urlopen(web,timeout=1).close();break
            except OSError: time.sleep(.3)
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            context=browser.new_context(viewport={'width':1500,'height':1050})
            context.add_cookies([{'name':'Admin-Token','value':token,'url':web}])
            page=context.new_page()
            page.on('pageerror',lambda e: print('BROWSER ERROR',str(e),flush=True))
            page.goto(web+'/admin/scenes')
            row=page.get_by_role('row').filter(has_text='ingestion-acceptance')
            check('browser scene row exposes both entries',row.get_by_role('button',name='场景信息',exact=True).count()==1 and row.get_by_role('button',name='版本与文件',exact=True).count()==1)
            for width in (1280,1440,1920):
                page.set_viewport_size({'width':width,'height':1050})
                seen=page.get_by_role('row').filter(has_text='ingestion-acceptance')
                check(f'browser scene row keeps four actions at {width}px',[item.inner_text().strip() for item in seen.locator('.scene-actions button').all()]==['场景信息','版本与文件','停用','删除'])
                boxes=[item.bounding_box() for item in seen.locator('.scene-actions button').all()]
                check(f'browser scene actions share one line at {width}px',max(box['y']+box['height']/2 for box in boxes)-min(box['y']+box['height']/2 for box in boxes)<=1.5)
                check(f'browser scene actions keep spacing at {width}px',all(boxes[index+1]['x']-(boxes[index]['x']+boxes[index]['width'])>=6 for index in range(len(boxes)-1)))
                columns={header.inner_text().strip():header.bounding_box()['width'] for header in page.locator('.el-table__header th').all()}
                check(f'browser scene columns stay compact at {width}px',columns['状态']<=110 and columns['修订号']<=110)
            page.set_viewport_size({'width':1500,'height':1050})
            check('browser scene action labels are not truncated',all(button.evaluate('el=>el.scrollWidth<=el.clientWidth+1') for button in row.locator('.scene-actions button').all()))
            row.get_by_role('button',name='场景信息',exact=True).click()
            dialog=page.get_by_role('dialog',name='场景信息')
            dialog.wait_for()
            check('browser scene info dialog keeps only close and save',[item.inner_text().strip() for item in dialog.locator('.el-dialog__footer').get_by_role('button').all()]==['关闭','保存'])
            dialog.locator('.el-dialog__footer').get_by_role('button',name='关闭',exact=True).click()
            dialog.wait_for(state='hidden')
            row.get_by_role('button',name='版本与文件',exact=True).click()
            page.get_by_role('heading',name='内容版本草稿 · ingestion-acceptance').wait_for()
            check('browser resource panel names its scene','所属场景：ingestion-acceptance' in page.locator('.el-drawer').inner_text())
            page.get_by_placeholder('填写版本说明（可留空）').fill('browser draft')
            page.get_by_role('button',name='创建草稿',exact=True).click()
            page.get_by_role('heading',name='草稿文件',exact=False).wait_for()
            payloads=[{'name':'browser-one.bin','mimeType':'application/octet-stream','buffer':a},{'name':'browser-two.bin','mimeType':'application/octet-stream','buffer':b*(200000)}]
            page.locator('#draft-file-picker').set_input_files(payloads)
            page.get_by_role('row').filter(has_text='browser-two.bin').get_by_text('已校验入库',exact=True).wait_for(timeout=30000)
            check('browser creates draft and uploads two files',page.get_by_role('row').filter(has_text='browser-one.bin').get_by_text('已校验入库',exact=True).count()==1)
            browser_draft=page.url.split('draftId=')[1].split('&')[0]
            check('browser multi-chunk hash matches original',sql("select expected_sha256,verified_bytes from ar_draft_file where draft_id=%s and file_name='browser-two.bin'",(browser_draft,))[0]==(hashlib.sha256(b*200000).hexdigest(),len(b)*200000))
            page.reload()
            page.get_by_role('heading',name='内容版本草稿').wait_for()
            page.get_by_role('row').filter(has_text='browser-two.bin').get_by_text('已校验入库',exact=True).wait_for()
            check('browser refresh preserves selected draft and files',page.get_by_role('row').filter(has_text='browser-one.bin').count()==1)
            page.locator('#draft-file-picker').set_input_files(payloads[0])
            page.get_by_role('status').filter(has_text='已校验入库').wait_for(timeout=30000)
            check('browser repeated file selection does not duplicate row',page.get_by_role('row').filter(has_text='browser-one.bin').count()==1)
            row=page.get_by_role('row').filter(has_text='browser-one.bin')
            original_id=sql("select id::text from ar_draft_file where draft_id=%s and file_name='browser-one.bin' and removed_at is null",(browser_draft,))[0][0]
            row.get_by_role('button',name='删除',exact=True).click()
            page.get_by_role('button',name='取消',exact=True).click()
            check('browser cancellation keeps file',sql('select removed_at is null from ar_draft_file where id=%s',(original_id,))[0][0])
            row.get_by_role('button',name='删除',exact=True).click()
            page.get_by_role('button',name='永久删除',exact=True).click()
            row.wait_for(state='hidden')
            page.get_by_role('button',name='刷新',exact=True).click()
            page.get_by_role('heading',name='草稿文件',exact=False).wait_for()
            page.get_by_role('row').filter(has_text='browser-two.bin').wait_for()
            check('browser removal remains hidden after refresh',page.get_by_role('row').filter(has_text='browser-one.bin').count()==0)
            page.locator('#draft-file-picker').set_input_files(payloads[0])
            page.get_by_role('row').filter(has_text='browser-one.bin').get_by_text('已校验入库',exact=True).wait_for(timeout=30000)
            check('browser can explicitly readd removed file',sql("select count(*) from ar_draft_file where draft_id=%s and file_name='browser-one.bin' and removed_at is null",(browser_draft,))[0][0]==1 and not (run/'artifacts/committed'/(original_id+'.bin')).exists())
            page.get_by_text('该场景尚未发布').wait_for()
            draft_row=page.get_by_role('row').filter(has_text=browser_draft)
            draft_row.get_by_role('button',name='发布',exact=True).click()
            page.get_by_role('button',name='取消',exact=True).click()
            check('browser cancellation keeps unpublished',sql('select published_draft_id from ar_scene where id=%s',(scene_id,))[0][0] is None)
            draft_row.get_by_role('button',name='发布',exact=True).click()
            page.get_by_role('button',name='确认发布',exact=True).click()
            page.get_by_text('该场景尚未发布').wait_for(state='hidden')
            check('browser publish pins current version',str(sql('select published_draft_id from ar_scene where id=%s',(scene_id,))[0][0])==browser_draft)
            ver=api('/api/v1/scenes/'+scene_id)[1]['lockVersion']
            page.get_by_role('row').filter(has_text='ingestion-acceptance').get_by_text(str(ver),exact=True).wait_for()
            check('parent scene revision updates after publish',True)
            check('browser hides upload on published draft',page.locator('#draft-file-picker').count()==0 and page.locator('#draft-folder-picker').count()==0)
            check('browser disables published draft delete',draft_row.get_by_role('button',name='删除',exact=True).is_disabled())
            page.goto(web+'/admin/scenes?draftScene='+scene_id)
            page.get_by_role('heading',name='当前查看：发布文件 · '+browser_draft,exact=True).wait_for()
            page.locator('.draft-files').get_by_role('row').filter(has_text='browser-one.bin').wait_for()
            check('browser entry automatically shows published files', 'draftId='+browser_draft in page.url)
            page.locator('.draft-files').get_by_role('button',name='保存说明',exact=True).wait_for()
            check('browser published description remains editable',page.locator('.draft-files').get_by_role('button',name='保存说明',exact=True).is_enabled())
            page.get_by_placeholder('填写版本说明（可留空）').fill('replacement draft')
            page.get_by_role('button',name='创建草稿',exact=True).click()
            page.get_by_role('heading',name='草稿文件',exact=False).wait_for()
            page.locator('#draft-file-picker').set_input_files(payloads[0])
            page.get_by_role('row').filter(has_text='browser-one.bin').get_by_text('已校验入库',exact=True).wait_for(timeout=30000)
            replacement_id=page.url.split('draftId=')[1].split('&')[0]
            page.get_by_role('row').filter(has_text=replacement_id).get_by_role('button',name='替换发布',exact=True).click()
            page.get_by_role('button',name='取消',exact=True).click()
            check('browser cancel replace keeps original',str(sql('select published_draft_id from ar_scene where id=%s',(scene_id,))[0][0])==browser_draft)
            page.get_by_role('row').filter(has_text=replacement_id).get_by_role('button',name='替换发布',exact=True).click()
            page.get_by_role('button',name='确认替换',exact=True).click()
            page.get_by_role('row').filter(has_text=replacement_id).get_by_text('已发布',exact=True).wait_for()
            check('browser replace switches published pointer',str(sql('select published_draft_id from ar_scene where id=%s',(scene_id,))[0][0])==replacement_id)
            page.get_by_role('heading',name='当前查看：发布文件 · '+replacement_id,exact=True).wait_for()
            page.locator('.draft-files').get_by_role('row').filter(has_text='browser-one.bin').wait_for()
            check('browser replacement shows new published files', 'draftId='+replacement_id in page.url)
            page.get_by_role('row').filter(has_text=browser_draft).get_by_role('button',name='查看文件',exact=True).click()
            page.get_by_role('heading',name='当前查看：草稿文件 · '+browser_draft,exact=True).wait_for()
            page.get_by_role('button',name='刷新',exact=True).click()
            page.get_by_role('heading',name='当前查看：草稿文件 · '+browser_draft,exact=True).wait_for()
            check('browser manual draft remains manageable',page.locator('#draft-file-picker').count()==1)
            page.reload()
            page.get_by_role('heading',name='当前查看：草稿文件 · '+browser_draft,exact=True).wait_for()
            check('browser reload preserves manual selection','draftId='+browser_draft in page.url)
            draft_row=page.get_by_role('row').filter(has_text=browser_draft)
            draft_row.get_by_role('button',name='删除',exact=True).click()
            page.get_by_role('button',name='取消',exact=True).click()
            check('browser cancellation keeps draft',sql('select count(*) from ar_draft where id=%s',(browser_draft,))[0][0]==1)
            draft_row.get_by_role('button',name='删除',exact=True).click()
            page.get_by_role('button',name='永久删除',exact=True).click()
            draft_row.wait_for(state='hidden')
            check('browser draft removal hides row and files',sql('select count(*) from ar_draft where id=%s',(browser_draft,))[0][0]==0 and sql('select count(*) from ar_draft_file where draft_id=%s',(browser_draft,))[0][0]==0)
            page.screenshot(path=str(run/'browser.png'),full_page=True)
            page.goto(web+'/admin/scenes?draftScene='+scene_id+'&draftId='+draft_id)
            page.get_by_role('row').filter(has_text='mismatch.bin').get_by_text('失败',exact=True).wait_for()
            check('browser shows failure reason and retry action',page.get_by_role('row').filter(has_text='mismatch.bin').get_by_text('SHA256',exact=False).count()>0 and page.get_by_role('row').filter(has_text='mismatch.bin').get_by_role('button',name='重新选择原文件').count()==1)
            folder_root=run/'browser-folder'/'场景B'/'models'
            folder_root.mkdir(parents=True)
            (folder_root/'one.bin').write_bytes(a)
            before=page.url
            page.get_by_placeholder('填写版本说明（可留空）').fill('folder browser')
            page.get_by_role('button',name='创建草稿',exact=True).click()
            page.wait_for_function('prev => location.href !== prev && location.href.includes("draftId=")', arg=before)
            page.get_by_role('button',name='选择文件夹并上传',exact=True).wait_for()
            page.locator('#draft-folder-picker').set_input_files(str(run/'browser-folder'/'场景B'))
            try:
                page.get_by_role('button',name='确认替换全部文件',exact=True).click(timeout=3000)
            except Exception:
                pass
            page.get_by_role('row').filter(has_text='one.bin').get_by_text('已校验入库',exact=True).wait_for(timeout=30000)
            page.get_by_role('button',name='查看下载清单',exact=True).click()
            page.get_by_role('dialog',name='下载清单').get_by_text('场景B/models/one.bin').first.wait_for()
            page.keyboard.press('Escape')
            with page.expect_download(timeout=30000) as downloaded:
                page.get_by_role('button',name='下载 ZIP',exact=True).click()
            zip_path=run/'browser.zip'; downloaded.value.save_as(zip_path)
            with zipfile.ZipFile(zip_path) as archive:
                names=archive.namelist()
                check('browser zip contains folder path', archive.read('场景B/models/one.bin')==a)
            zip_bytes=zip_path.read_bytes()
            zip_button=page.get_by_role('button',name='下载 ZIP',exact=True)
            unconfirmed='请求等待超时，ZIP 构建结果尚未确认，后端可能仍在处理。请稍后重试。'
            check('browser zip button is operable before retries',zip_button.is_enabled())
            page.route('**/api/v1/drafts/**/zip-exports',lambda route: route.fulfill(status=504,content_type='text/html',body='<html>504 Gateway Time-out</html>'))
            zip_button.click()
            page.get_by_text(unconfirmed,exact=True).first.wait_for(timeout=30000)
            check('browser reports unconfirmed result on gateway timeout',zip_button.is_enabled())
            check('browser never claims a build failure on gateway timeout',page.get_by_text('ZIP 未准备成功',exact=False).count()==0 and page.get_by_text('ZIP 构建失败',exact=False).count()==0)
            page.unroute('**/api/v1/drafts/**/zip-exports')
            with page.expect_download(timeout=30000) as retried:
                zip_button.click()
            retried_zip=run/'browser-retry.zip'; retried.value.save_as(retried_zip)
            check('browser manual retry reuses the prepared zip',retried_zip.read_bytes()==zip_bytes and zip_button.is_enabled())
            page.route('**/api/v1/drafts/**/zip-exports',lambda route: route.abort())
            zip_button.click()
            page.get_by_text(unconfirmed,exact=True).first.wait_for(timeout=30000)
            check('browser treats an interrupted connection as unconfirmed',zip_button.is_enabled())
            page.unroute('**/api/v1/drafts/**/zip-exports')
            still_building='ZIP 正在准备，构建结果尚未确认。请稍后手动重试。'
            page.route('**/api/v1/drafts/**/zip-exports',lambda route: route.fulfill(status=409,content_type='application/json',body=json.dumps({'code':'AR_409','message':'ZIP 正在准备，请稍后重试'})))
            zip_button.click()
            page.get_by_text(still_building,exact=True).first.wait_for(timeout=30000)
            check('browser keeps a still-building answer in progress',zip_button.is_enabled() and page.get_by_text('ZIP 准备失败',exact=False).count()==0)
            page.unroute('**/api/v1/drafts/**/zip-exports')
            with page.expect_download(timeout=30000) as rebuilt:
                zip_button.click()
            rebuilt_zip=run/'browser-rebuilt.zip'; rebuilt.value.save_as(rebuilt_zip)
            check('browser manual retry after a still-building answer reuses the zip',rebuilt_zip.read_bytes()==zip_bytes and zip_button.is_enabled())
            page.route('**/api/v1/drafts/**/zip-exports',lambda route: route.fulfill(status=409,content_type='application/json',body=json.dumps({'code':'AR_409','message':'文件集合已变化，请重新获取清单'})))
            zip_button.click()
            page.get_by_text('文件集合已变化，请重新获取清单',exact=True).first.wait_for(timeout=30000)
            check('browser keeps other 409 conflicts as errors',zip_button.is_enabled() and page.get_by_text(still_building,exact=True).count()==0)
            page.unroute('**/api/v1/drafts/**/zip-exports')
            page.route('**/api/v1/drafts/**/zip-exports',lambda route: route.fulfill(status=503,content_type='application/json',body=json.dumps({'code':'AR_503','message':'ZIP 准备失败，请稍后重试'})))
            zip_button.click()
            page.get_by_text('ZIP 准备失败，请稍后重试',exact=True).first.wait_for(timeout=30000)
            check('browser surfaces an explicit backend build failure',zip_button.is_enabled() and page.get_by_text(unconfirmed,exact=True).count()==0)
            page.unroute('**/api/v1/drafts/**/zip-exports')
            page.route('**/api/v1/drafts/**/zip-exports/*/content',lambda route: route.abort())
            zip_button.click()
            page.get_by_text('ZIP 下载失败，请重试',exact=True).first.wait_for(timeout=30000)
            check('browser reports a download-stage failure separately',zip_button.is_enabled() and page.get_by_text(unconfirmed,exact=True).count()==0)
            page.unroute('**/api/v1/drafts/**/zip-exports/*/content')
            with page.expect_download(timeout=30000) as recovered:
                zip_button.click()
            recovered_zip=run/'browser-recovered.zip'; recovered.value.save_as(recovered_zip)
            check('browser downloads the same zip after a download-stage failure',recovered_zip.read_bytes()==zip_bytes)
            check('browser folder upload restores top-level directory',page.get_by_role('row').filter(has_text='场景B/models/one.bin').count()==1)
            retry_root=run/'browser-retry'/'场景D'/'models'
            retry_root.mkdir(parents=True)
            (retry_root/'retry.bin').write_bytes(a)
            (retry_root/'retry-two.bin').write_bytes(b)
            before=page.url
            page.get_by_placeholder('填写版本说明（可留空）').fill('folder retry')
            page.get_by_role('button',name='创建草稿',exact=True).click()
            page.wait_for_function('prev => location.href !== prev && location.href.includes("draftId=")', arg=before)
            page.get_by_role('button',name='选择文件并上传',exact=True).wait_for()
            page.locator('#draft-file-picker').set_input_files(str(retry_root/'retry.bin'))
            page.get_by_role('row').filter(has_text='retry.bin').get_by_text('已校验入库',exact=True).wait_for(timeout=30000)
            stalled=[]
            def stall_put(route):
                if route.request.method=='PUT' and route.request.url.rstrip('/').endswith('/content'):
                    stalled.append(route)
                    return
                route.continue_()
            page.route('**/api/v1/drafts/**/content', stall_put)
            page.get_by_role('button',name='选择文件夹并上传',exact=True).click()
            page.locator('#draft-folder-picker').set_input_files(str(run/'browser-retry'/'场景D'))
            page.get_by_text('此次操作会替换当前草稿的全部文件',exact=False).wait_for(timeout=15000)
            page.get_by_role('button',name='确认替换全部文件',exact=True).click()
            page.get_by_text('替换进度',exact=False).wait_for(timeout=30000)
            page.get_by_role('button',name='取消本次上传',exact=True).click()
            page.unroute('**/api/v1/drafts/**/content')
            for stalled_route in stalled:
                try: stalled_route.abort()
                except Exception: pass
            page.get_by_role('button',name='取消替换',exact=True).click()
            page.get_by_role('button',name='确认取消替换',exact=True).click()
            page.get_by_role('row').filter(has_text='retry.bin').get_by_text('已校验入库',exact=True).wait_for(timeout=30000)
            page.evaluate("document.getElementById('draft-folder-picker').value=''")
            page.get_by_role('button',name='选择文件夹并上传',exact=True).click()
            page.locator('#draft-folder-picker').set_input_files(str(run/'browser-retry'/'场景D'))
            page.get_by_text('此次操作会替换当前草稿的全部文件',exact=False).wait_for(timeout=15000)
            page.get_by_role('button',name='确认替换全部文件',exact=True).click()
            page.get_by_role('row').filter(has_text='场景D/models/retry.bin').get_by_text('已校验入库',exact=True).wait_for(timeout=30000)
            check('browser reselects same folder after cancel',page.get_by_role('row').filter(has_text='场景D/models/retry.bin').count()==1)
            browser.close()
        report={'passed':True,'postgres':version,'runtime':'isolated native PostgreSQL 17 / Redis / Spring Boot / Vite / Edge',
                'backendJar':str(args.backend_jar),'backendJarSha256':hashlib.sha256(args.backend_jar.read_bytes()).hexdigest(),
                'checks':CHECKS,'limitations':['No Addressables/client-loading validation','No power-loss or disk-full injection','Nginx container route not exercised by this native test',
                    'Gateway timeout and interrupted prepare/download are simulated at the browser route; the real 60s gateway limit and a ~250MB same-environment build comparison stay host acceptance']}
        (args.report_dir/'validation-ingestion.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    finally:
        (run/'checks.json').write_text(json.dumps(CHECKS,ensure_ascii=False,indent=2),encoding='utf-8')
        for p in reversed(processes):
            if p.poll() is None:
                p.terminate()
                try:p.wait(timeout=15)
                except subprocess.TimeoutExpired:p.kill();p.wait()
        if db:db.close()
        if pg_started:cmd([pg/'pg_ctl.exe','-D',run/'pgdata','-m','fast','-w','stop'])
        for log in logs:log.close()
        print('Evidence directory:',run,flush=True)

if __name__=='__main__':
    main()
