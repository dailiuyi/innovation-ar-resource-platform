"""Real PostgreSQL/HTTP integration and transactional fault-injection checks."""
from concurrent.futures import ThreadPoolExecutor
import json
import time
import uuid
import psycopg
from verify_framework import ROOT, CONFIG, call, check, login, results

accounts=json.loads((ROOT/'.local/test-accounts.json').read_text())
a=login('demo_a',accounts['demo_a']);b=login('demo_b',accounts['demo_b'])
conn=psycopg.connect(host='127.0.0.1',port=15432,dbname='ar_demo',user='ar_demo',password=CONFIG['AR_DATABASE_PASSWORD'],autocommit=True)
check('PostgreSQL 17 target',conn.execute('show server_version').fetchone()[0].startswith('17.'))
check('AR anonymous error contract',call('/api/v1/scenes')[0]==401 and 'traceId' in call('/api/v1/scenes')[1])
check('blank name validation',call('/api/v1/scenes','POST',{'name':' '},a)[0]==400)
name='integration-'+str(uuid.uuid4())[:8]
status,scene=call('/api/v1/scenes','POST',{'name':name},a)
check('create scene',status==201)
sid=scene['id']
check('detail matches',call('/api/v1/scenes/'+sid,token=b)[1]['name']==name)
check('search and count',call('/api/v1/scenes?name='+name+'&limit=1&offset=0',token=a)[1]['total']==1)
def update(token): return call('/api/v1/scenes/'+sid,'PUT',{'name':name+'-changed','expectedVersion':0},token)[0]
with ThreadPoolExecutor(2) as pool: statuses=list(pool.map(update,[a,b]))
check('concurrent update one success one conflict',sorted(statuses)==[200,409])
check('exactly one audit for winning update',conn.execute("select count(*) from ar_audit where scene_id=%s and action='UPDATE'",(sid,)).fetchone()[0]==1)
check('audit actor tracked',conn.execute('select actor_name from ar_audit where scene_id=%s order by id limit 1',(sid,)).fetchone()[0]=='demo_a')
status,scene=call('/api/v1/scenes/'+sid+'/enabled','PUT',{'enabled':False,'expectedVersion':1,'reason':'integration'},b)
check('disable scene',status==200 and scene['enabled'] is False and scene['lockVersion']==2)
check('invalid pagination rejected',call('/api/v1/scenes?limit=101',token=a)[0]==400)
check('missing scene 404',call('/api/v1/scenes/'+str(uuid.uuid4()),token=a)[0]==404)
check('anonymous delete rejected',call('/api/v1/scenes/'+sid+'?expectedVersion=2','DELETE')[0]==401)
check('stale delete rejected',call('/api/v1/scenes/'+sid+'?expectedVersion=0','DELETE',token=a)[0]==409)

# Fail the audit insert for this exact scene to prove the preceding update rolls back.
conn.execute("""create function demo_test_reject_audit() returns trigger language plpgsql as $$
begin if NEW.scene_id=cast('%s' as uuid) then raise exception 'test audit failure'; end if; return NEW; end $$;""" % sid)
conn.execute('create trigger demo_test_reject before insert on ar_audit for each row execute function demo_test_reject_audit()')
try:
    check('audit failure surfaces',call('/api/v1/scenes/'+sid,'PUT',{'name':'must-rollback','expectedVersion':2},a)[0]==500)
    unchanged=call('/api/v1/scenes/'+sid,token=a)[1]
    check('business mutation rolled back',unchanged['name']!= 'must-rollback' and unchanged['lockVersion']==2)
    check('delete audit failure surfaces',call('/api/v1/scenes/'+sid+'?expectedVersion=2','DELETE',token=a)[0]==500)
    check('failed delete rolled back',call('/api/v1/scenes/'+sid,token=a)[0]==200)
finally:
    conn.execute('drop trigger demo_test_reject on ar_audit')
    conn.execute('drop function demo_test_reject_audit()')
try:
    conn.execute('delete from ar_audit where scene_id=%s',(sid,))
    check('append-only audit enforced',False)
except psycopg.errors.RaiseException:
    check('append-only audit enforced',True)

check('delete scene',call('/api/v1/scenes/'+sid+'?expectedVersion=2','DELETE',token=a)[0]==204)
check('deleted detail hidden',call('/api/v1/scenes/'+sid,token=a)[0]==404)
check('deleted scene excluded from count',call('/api/v1/scenes?name='+name,token=a)[1]['total']==0)
check('delete audit retained',conn.execute("select count(*) from ar_audit where scene_id=%s and action='DELETE'",(sid,)).fetchone()[0]==1)
check('deleted scene cannot be enabled',call('/api/v1/scenes/'+sid+'/enabled','PUT',{'enabled':True,'expectedVersion':3,'reason':'test'},a)[0]==404)

# Synthetic data is transaction-local and rolled back after EXPLAIN ANALYZE.
perf={}
with conn.transaction(force_rollback=True):
    conn.execute("insert into ar_scene(id,name) select md5('demo-perf-'||n)::uuid,'perf-scene-'||n from generate_series(1,10000) n on conflict do nothing")
    conn.execute('analyze ar_scene')
    for label,sql in {
        'list':"select * from ar_scene order by created_at desc,id limit 20",
        'filter':"select * from ar_scene where position(lower('perf-scene-99') in lower(name))>0 order by created_at desc,id limit 20",
        'detail':"select * from ar_scene where id=md5('demo-perf-99')::uuid",
    }.items():
        perf[label]=conn.execute('explain (analyze,buffers,format json) '+sql).fetchone()[0]
check('synthetic performance data rolled back',conn.execute("select count(*) from ar_scene where name like 'perf-scene-%'").fetchone()[0]==0)
(ROOT/'docs/validation-demo.json').write_text(json.dumps({'database':conn.execute('select version()').fetchone()[0],'checks':results,'performance':perf},ensure_ascii=False,indent=2),encoding='utf-8')
conn.close()
