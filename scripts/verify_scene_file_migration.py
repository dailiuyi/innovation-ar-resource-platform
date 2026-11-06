"""Exercise V018 against new isolated PostgreSQL databases, retaining them as evidence.

Only loopback connections are accepted. This creates uniquely named databases; it never
connects to application/daily databases or reads private configuration files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / 'backend/ruoyi-admin/src/main/resources/db/demo'


def uid(value):
    return uuid.UUID(int=value)


def initialize(connection, through):
    for migration in sorted(MIGRATIONS.glob('V*.sql')):
        number = int(migration.name.split('__')[0][1:])
        if number <= through:
            with connection.transaction():
                connection.execute(migration.read_text(encoding='utf-8'))


def seed(connection):
    actor = connection.execute(
        "insert into sys_user(dept_id,user_name,nick_name,status,create_time) "
        "values(100,'migration_check','Migration fixture','0',now()) returning user_id").fetchone()[0]
    for scene in range(1, 7):
        connection.execute('insert into ar_scene(id,name,enabled,deleted_at) values(%s,%s,%s,%s)',
                           (uid(scene), f'migration scene {scene}', scene != 3,
                            '2026-01-01T00:00:00Z' if scene == 4 else None))
        connection.execute('insert into ar_audit(scene_id,actor_id,actor_name,action,detail) '
                           'values(%s,%s,%s,%s,%s::jsonb)',
                           (uid(scene), actor, 'migration-check', 'CREATE', json.dumps({'fixture': scene})))
    versions = [(101, 1, 1), (102, 1, 2), (103, 1, 3),
                (104, 2, 1), (105, 2, 2), (106, 3, 1),
                (107, 4, 1), (108, 4, 2), (109, 6, 1)]
    for version, scene, number in versions:
        connection.execute('insert into ar_scene_version(id,scene_id,version_no,request_key,description,'
                           'creator_id,creator_name) values(%s,%s,%s,%s,%s,%s,%s)',
                           (uid(version), uid(scene), number, uid(version + 1000),
                            f'content {version}', actor, 'migration-check'))
        file_id = uid(version + 100)
        digest = hashlib.sha256(f'payload {version}'.encode()).hexdigest()
        available = version not in (103, 109)
        connection.execute('insert into ar_version_file(id,version_id,relative_path,expected_bytes,'
                           'expected_sha256,storage_key,status,verified_bytes,verified_sha256,'
                           'creator_id,creator_name,last_actor_id,last_actor_name) '
                           'values(%s,%s,%s,123,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                           (file_id, uid(version), 'nested/model.bin', digest, f'{file_id}.bin',
                            'AVAILABLE' if available else 'PENDING', 123 if available else None,
                            digest if available else None, actor, 'migration-check', actor, 'migration-check'))
    for scene, published in [(1, 102), (3, 106), (4, 107)]:
        connection.execute('update ar_scene set published_version_id=%s,published_at=now(),'
                           'published_by_id=%s,published_by_name=%s where id=%s',
                           (uid(published), actor, 'migration-check', uid(scene)))
    connection.execute('insert into ar_version_deletion(version_id,scene_id,request_key,actor_id,actor_name,'
                       'failure_reason) values(%s,%s,%s,%s,%s,%s)',
                       (uid(109), uid(6), uid(1109), actor, 'migration-check', 'fixture storage failure'))
    connection.execute('insert into ar_version_deletion(version_id,scene_id,request_key,actor_id,actor_name,'
                       'completed_at) values(%s,%s,%s,%s,%s,now())',
                       (uid(110), uid(6), uid(1110), actor, 'migration-check'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', choices=['127.0.0.1', 'localhost', '::1'], default='127.0.0.1')
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--user', default='postgres')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    connection_args = dict(host=args.host, port=args.port, user=args.user, connect_timeout=10)
    report = {'status': 'running', 'checks': [], 'databases': [],
              'scope': 'Isolated PostgreSQL schema and data migration; no payload IO or HTTP'}

    def check(name, condition):
        report['checks'].append({'name': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)

    def database(label):
        name = 'ar_scene_v018_' + label + '_' + uuid.uuid4().hex[:10]
        with psycopg.connect(dbname='postgres', autocommit=True, **connection_args) as admin:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        report['databases'].append(name)
        return psycopg.connect(dbname=name, autocommit=True, **connection_args)

    upgrade = next(MIGRATIONS.glob('V018__*.sql')).read_text(encoding='utf-8')
    try:
        with database('empty') as connection:
            report['postgres'] = connection.execute('select version()').fetchone()[0]
            initialize(connection, 18)
            check('empty initialization creates direct scene files',
                  connection.execute("select to_regclass('ar_scene_file') is not null "
                                     "and to_regclass('ar_scene_version') is null").fetchone()[0])
        with database('populated') as connection:
            initialize(connection, 17)
            with connection.transaction():
                seed(connection)
            before_files = connection.execute('select id::text,storage_key,expected_bytes,expected_sha256,'
                                              'status,verified_bytes,verified_sha256 from ar_version_file order by id').fetchall()
            before_audit = connection.execute('select * from ar_audit order by id').fetchall()
            with connection.transaction():
                connection.execute(upgrade)
            after_files = connection.execute('select id::text,storage_key,expected_bytes,expected_sha256,'
                                             'status,verified_bytes,verified_sha256 from ar_scene_file order by id').fetchall()
            check('all file identities, keys and verification records preserved exactly', before_files == after_files)
            expected_map = {uid(201): uid(101), uid(202): uid(1), uid(203): uid(103),
                            uid(204): uid(104), uid(205): uid(2), uid(206): uid(3),
                            uid(207): uid(4), uid(208): uid(108), uid(209): uid(6)}
            actual_map = dict(connection.execute('select id,scene_id from ar_scene_file').fetchall())
            check('published/latest/history mapping preserves every file owner', actual_map == expected_map)
            check('audit rows unchanged', before_audit == connection.execute('select * from ar_audit order by id').fetchall())
            for scene, enabled in [(1, True), (2, False), (3, False), (6, False),
                                   (101, False), (103, False), (104, False), (108, False)]:
                check(f'scene {scene} enable policy preserved',
                      connection.execute('select enabled from ar_scene where id=%s', (uid(scene),)).fetchone()[0] == enabled)
            check('deleted current and historical models remain deleted',
                  connection.execute('select count(*) from ar_scene where id=any(%s) and deleted_at is not null',
                                     ([uid(4), uid(108)],)).fetchone()[0] == 2)
            visible = connection.execute("select s.id from ar_scene s where s.enabled and s.deleted_at is null "
                                         "and exists(select 1 from ar_scene_file f where f.scene_id=s.id) "
                                         "and not exists(select 1 from ar_scene_file f where f.scene_id=s.id and f.status<>'AVAILABLE') "
                                         "and not exists(select 1 from ar_scene_deletion d where d.scene_id=s.id and d.completed_at is null)").fetchall()
            check('only originally published enabled complete model is public', visible == [(uid(1),)])
            check('original scene receives published description rather than newer draft',
                  connection.execute('select description from ar_scene where id=%s', (uid(1),)).fetchone()[0] == 'content 102')
            pending = connection.execute('select scene_id,completed_at,failure_reason from ar_scene_deletion where completed_at is null').fetchall()
            check('pending deletion survives with mapped scene and failure',
                  pending == [(uid(6), None, 'fixture storage failure')])
            check('completed deletion receipt survives without a recreated model',
                  connection.execute('select completed_at is not null from ar_scene_deletion where scene_id=%s',
                                     (uid(110),)).fetchone()[0]
                  and connection.execute('select count(*) from ar_scene where id=%s', (uid(110),)).fetchone()[0] == 0)
            check('legacy empty scene preserved without files',
                  connection.execute('select count(*) from ar_scene where id=%s', (uid(5),)).fetchone()[0] == 1
                  and connection.execute('select count(*) from ar_scene_file where scene_id=%s', (uid(5),)).fetchone()[0] == 0)
        with database('inconsistent') as connection:
            initialize(connection, 17)
            with connection.transaction():
                seed(connection)
                actor = connection.execute('select min(user_id) from sys_user').fetchone()[0]
                connection.execute('insert into ar_version_deletion(version_id,scene_id,request_key,actor_id,actor_name,'
                                   'completed_at) values(%s,%s,%s,%s,%s,now())',
                                   (uid(101), uid(1), uid(1101), actor, 'migration-check'))
            failed = False
            try:
                with connection.transaction():
                    connection.execute(upgrade)
            except psycopg.Error:
                failed = True
            check('inconsistent completed deletion aborts upgrade rather than discarding files', failed)
            check('aborted migration preserves original rows and schema',
                  connection.execute('select count(*) from ar_version_file').fetchone()[0] == 9
                  and connection.execute("select to_regclass('ar_scene_file') is null").fetchone()[0])
        report['status'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'
        report['error'] = f'{type(error).__name__}: {error}'
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'checks': len(report['checks']),
                      'report': str(args.report)}, ensure_ascii=False))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
