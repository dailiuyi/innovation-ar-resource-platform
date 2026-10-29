"""Repository checks with isolated evidence; never starts or stops the daily Demo."""
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ('quick', 'frontend', 'ingestion')
BACKEND_JAR = 'backend/ruoyi-admin/target/ruoyi-admin.jar'
EXIT_CODES = {'passed': 0, 'failed': 1, 'blocked': 2}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def environment(root=ROOT):
    env = dict(os.environ)
    env['PYTHONPATH'] = str(root / '.local/python') + os.pathsep + env.get('PYTHONPATH', '')
    env['PYTHONUTF8'] = '1'
    java = next(iter(sorted((root / '.local/java21').glob('jdk*/bin/java.exe'))), None)
    if java:
        env['JAVA_HOME'] = str(java.parent.parent)
        env['PATH'] = str(java.parent) + os.pathsep + env.get('PATH', '')
    return env


def source_identity(root=ROOT):
    """Include dirty and untracked nonignored content, not just the last commit."""
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE)
    if Path(git('rev-parse', '--show-toplevel').decode().strip()).resolve() != root.resolve():
        raise OSError('The check root must be the Git checkout root, not a nested directory')
    head = git('rev-parse', 'HEAD').decode().strip()
    paths = sorted(set(git('ls-files', '-z', '--cached', '--others', '--exclude-standard').split(b'\0')) - {b''})
    digest = hashlib.sha256()
    for raw in paths:
        path = root / os.fsdecode(raw)
        digest.update(raw + b'\0')
        if path.is_symlink():
            digest.update(b'link:' + os.fsencode(os.readlink(path)))
        elif path.is_file():
            with path.open('rb') as stream:
                digest.update(hashlib.file_digest(stream, 'sha256').digest())
        else:
            digest.update(b'missing')
    return {'head': head, 'sourceSha256': digest.hexdigest(), 'fileCount': len(paths),
            'dirty': bool(git('status', '--porcelain', '--untracked-files=normal').strip())}


def prerequisites(profile, root=ROOT):
    env = environment(root)
    checks = []
    def record(name, ok, fix):
        checks.append({'name': name, 'status': 'passed' if ok else 'blocked', 'hint': '' if ok else fix})
    def probe(name, command, fix, expected=None):
        observation = ''
        try:
            result = subprocess.run(command, env=env, capture_output=True, text=True, errors='replace', timeout=15)
            ok = result.returncode == 0 and (expected is None or expected in result.stdout + result.stderr)
            if ok:
                observation = (result.stdout + result.stderr).strip().split('\n')[0]
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        record(name, ok, fix)
        if observation:
            checks[-1]['observation'] = observation
    record('Python >= 3.11', sys.version_info >= (3, 11), 'Use Python 3.11 or newer.')
    probe('Git checkout', ['git', '-C', str(root), 'rev-parse', '--show-toplevel'], 'Install Git and use this checkout.')
    probe('contract validators', [sys.executable, '-c', 'import yaml, jsonschema, openapi_spec_validator'],
          'Install scripts/requirements-review.txt into this Python or .local/python.')
    if profile in ('frontend', 'ingestion'):
        probe('Node.js', ['node', '--version'], 'Install Node.js supported by frontend/package.json.')
        probe('Node repository access', ['node', '-e', "require('node:fs').realpathSync(process.argv[1])", str(root / 'scripts/test_scene_package.mjs')],
              'Check repository access. If the agent sandbox denies access, request permission to run this profile outside it.')
    if profile == 'ingestion':
        record('frontend dependencies', (root / 'frontend/node_modules/vite/bin/vite.js').is_file(), 'Run npm --prefix frontend ci.')
        record('tested backend jar', (root / BACKEND_JAR).is_file(),
               'Run scripts/check_java.py --module ruoyi-admin --package for this source first.')
    if profile == 'frontend':
        record('npm', shutil.which('npm.cmd' if os.name == 'nt' else 'npm') is not None, 'Install npm with Node.js.')
    if profile == 'ingestion':
        record('Windows ingestion runtime', os.name == 'nt', 'The existing ingestion acceptance script requires Windows.')
        pg = root / '.local/postgresql17/pgsql/bin'
        probe('PostgreSQL 17', [str(pg / 'postgres.exe'), '--version'], 'Provision PostgreSQL 17 under .local/postgresql17/pgsql.', ' 17.')
        record('PostgreSQL utilities', all((pg / (name + '.exe')).is_file() for name in ('initdb', 'pg_ctl', 'createdb')),
               'Provision the complete PostgreSQL 17 distribution.')
        java = Path(env.get('JAVA_HOME', 'missing')) / 'bin/java.exe'
        probe('local Java 21', [str(java), '-version'], 'Provision JDK 21 under .local/java21/jdk*/.', 'version "21.')
        probe('Maven', ['mvn.cmd', '-version'], 'Install Maven and add mvn.cmd to PATH.')
        probe('Redis', ['redis-server', '--version'], 'Install Redis and add redis-server to PATH.')
        probe('ingestion Python dependencies', [sys.executable, '-c', 'import psycopg; from playwright.sync_api import sync_playwright'],
              'Install psycopg and Playwright into this Python or .local/python.')
        edge_paths = [Path(os.environ.get(key, 'missing')) / 'Microsoft/Edge/Application/msedge.exe'
                      for key in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')]
        record('Microsoft Edge', any(p.is_file() for p in edge_paths), 'Install Microsoft Edge; tests use channel=msedge.')
    return checks


@dataclass
class Step:
    name: str
    command: list
    cwd: Path
    timeout: int = 180
    evidence: Path | None = None


def stop_tree(process):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=30)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=15)


def run_step(step, directory, env, process_callback=None, progress_stream=None):
    log = directory / (step.name + '.log')
    result = {'name': step.name, 'command': [str(arg) for arg in step.command], 'cwd': str(step.cwd),
              'startedAt': utc_now(), 'log': str(log), 'timeoutSeconds': step.timeout, 'status': 'failed', 'exitCode': None}
    started = time.monotonic()
    process = None
    try:
        with log.open('wb') as output:
            process = subprocess.Popen(result['command'], cwd=step.cwd, env=env, stdout=output, stderr=subprocess.STDOUT,
                                       start_new_session=os.name != 'nt')
            if process_callback:
                process_callback(process)
            while True:
                remaining = step.timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(result['command'], step.timeout)
                try:
                    result['exitCode'] = process.wait(timeout=min(30, remaining))
                    break
                except subprocess.TimeoutExpired:
                    print(f'RUNNING {step.name}: {int(time.monotonic() - started)}s; log={log}',
                          file=progress_stream or sys.stdout, flush=True)
        if result['exitCode'] == 0:
            result['status'] = 'passed'
            if step.evidence:
                result['evidence'] = str(step.evidence)
                report = json.loads(step.evidence.read_text(encoding='utf-8'))
                if (not isinstance(report, dict) or report.get('passed') is not True
                        or not isinstance(report.get('checks'), list) or not report['checks']
                        or any(not isinstance(c, dict) or c.get('passed') is not True for c in report['checks'])):
                    raise ValueError('Expected a nonempty, entirely passing evidence report.')
                result['checks'] = len(report['checks'])
        else:
            result['reason'] = 'Command failed; inspect this run log.'
    except subprocess.TimeoutExpired:
        result.update(status='blocked', reason='Timed out; completion has not been verified.')
    except KeyboardInterrupt:
        result.update(status='blocked', reason='Interrupted; completion has not been verified.')
    except OSError as exc:
        result.update(status='blocked' if process is None else 'failed', reason=str(exc))
    except (ValueError, KeyError, TypeError) as exc:
        result.update(status='failed', reason='Invalid evidence: ' + str(exc))
    finally:
        if process is not None and process.poll() is None:
            stop_tree(process)
        if process_callback:
            process_callback(None)
        result['durationSeconds'] = round(time.monotonic() - started, 3)
    return result


def make_steps(profile, directory, root=ROOT):
    evidence = directory / 'evidence'
    evidence.mkdir()
    steps = [Step('harness-tests', [sys.executable, '-m', 'unittest', 'discover', '-s', str(root / 'scripts'), '-p', 'test_harness.py'], root),
             Step('review-tool-tests', [sys.executable, '-m', 'unittest', 'discover', '-s', str(root / 'scripts'), '-p', 'test_review.py'], root),
             Step('symphony-routing-tests', [sys.executable, '-m', 'unittest', 'discover', '-s', str(root / 'scripts'),
                                               '-p', 'test_symphony_codex_adapter.py'], root),
             Step('symphony-publish-tests', [sys.executable, '-m', 'unittest', 'discover', '-s', str(Path(__file__).parent),
                                               '-p', 'test_symphony_publish.py'], root),
             Step('execution-control-tests', [sys.executable, '-m', 'unittest', 'discover',
                  '-s', str(Path(__file__).parent), '-p', 'test_frontend_control.py'], root),
             Step('task-control-tests', [sys.executable, '-m', 'unittest', 'discover',
                  '-s', str(Path(__file__).parent), '-p', 'test_symphony_task.py'], root),
             Step('workspace-migration-tests', [sys.executable, '-m', 'unittest', 'discover',
                                               '-s', str(Path(__file__).parent),
                                               '-p', 'test_migrate_symphony_workspaces.py'], root),
             Step('environment-lock-tests', [sys.executable, '-m', 'unittest', 'discover',
                                             '-s', str(Path(__file__).parent),
                                             '-p', 'test_symphony_environment_lock.py'], root),
             Step('contracts-and-links', [sys.executable, root / 'scripts/verify_design.py', '--report-dir', evidence], root,
                  evidence=evidence / 'validation-contracts.json')]
    if profile in ('frontend', 'ingestion'):
        steps.append(Step('scene-package', ['node', '--test', root / 'scripts/test_scene_package.mjs'], root))
    if profile == 'frontend':
        steps.append(Step('frontend-build', [sys.executable, Path(__file__).with_name('frontend_control.py'),
                                            'build', '--root', root], root, 900))
    if profile == 'ingestion':
        # The jar is the already tested artifact from check_java.py --package; this profile neither builds nor replaces it.
        steps.append(Step('ingestion', [sys.executable, root / 'scripts/verify_ingestion.py', '--report-dir', evidence,
                                        '--backend-jar', root / BACKEND_JAR], root, 600,
                          evidence / 'validation-ingestion.json'))
    return steps


def cleanup_ingestion(directory, root=ROOT):
    """Recover only PostgreSQL clusters created inside this exact run after interruption."""
    failures = []
    for data in (directory / 'evidence').glob('ingestion-check-*/pgdata'):
        if not data.resolve().is_relative_to(directory.resolve()) or not (data / 'postmaster.pid').exists():
            continue
        try:
            result = subprocess.run([str(root / '.local/postgresql17/pgsql/bin/pg_ctl.exe'), '-D', str(data), '-m', 'fast', '-w', 'stop'],
                                    capture_output=True, timeout=45)
            if result.returncode:
                failures.append(str(data))
        except (OSError, subprocess.TimeoutExpired):
            failures.append(str(data))
    return failures


def execute_steps(steps, directory, env, retry_reason=None):
    results = []
    for step in steps:
        if results and results[-1]['status'] != 'passed':
            results.append({'name': step.name, 'status': 'skipped', 'reason': 'A previous step did not pass.'})
            continue
        print('RUN ' + step.name, flush=True)
        if step.name == 'frontend-build':
            from frontend_control import Blocked, operate
            try:
                result = {'name': step.name, **operate(step.cwd, env=env, timeout=step.timeout, retry_reason=retry_reason)}
                result['name'] = step.name
            except (Blocked, OSError, subprocess.SubprocessError) as exc:
                result = {'name': step.name, 'status': 'blocked', 'reason': str(exc)}
        else:
            result = run_step(step, directory, env)
        results.append(result)
        print(result['status'].upper() + ' ' + step.name, flush=True)
    return results


def overall_status(results):
    statuses = {r['status'] for r in results}
    if 'failed' in statuses:
        return 'failed'
    return 'passed' if statuses == {'passed'} else 'blocked'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('doctor', 'check'))
    parser.add_argument('--profile', choices=PROFILES, default='quick')
    parser.add_argument('--root', type=Path, default=ROOT, help='Explicit checkout for centrally installed tooling')
    parser.add_argument('--retry-reason', help='Explicit repaired condition for a held frontend attempt')
    args = parser.parse_args(argv)
    if args.retry_reason is not None and not args.retry_reason.strip():
        parser.error('--retry-reason must describe a repaired condition')
    root = args.root.resolve()
    base = root / '.local/harness'
    base.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-'), dir=base))
    report = {'schemaVersion': 1, 'action': args.action, 'profile': args.profile, 'startedAt': utc_now(),
              'status': 'blocked', 'steps': [], 'limitations': [
                  'Only this profile and source fingerprint are covered. Frontend build reuse verifies inputs and output; other checks run fresh.',
                  'No Docker/LAN deployment, client loading or production verification.',
                  'Doctor checks prerequisites, not application behavior; quick does not execute the application.']}
    try:
        report['sourceBefore'] = source_identity(root)
        report['prerequisites'] = prerequisites(args.profile, root)
        for item in report['prerequisites']:
            print(item['status'].upper() + ' ' + item['name'] + (': ' + item['hint'] if item['hint'] else ''), flush=True)
        report['status'] = overall_status(report['prerequisites'])
        if args.action == 'check' and report['status'] == 'passed':
            report['status'] = 'blocked'  # A prepared or interrupted profile is never a passing run.
            steps = make_steps(args.profile, directory, root)
            report['steps'] = execute_steps(steps, directory, environment(root), retry_reason=args.retry_reason)
            report['status'] = overall_status(report['steps'])
        elif args.action == 'check':
            report['steps'] = [{'name': 'profile', 'status': 'skipped', 'reason': 'Prerequisites are blocked.'}]
    except (OSError, subprocess.SubprocessError, KeyboardInterrupt) as exc:
        report.update(status='blocked', reason=type(exc).__name__ + ': ' + str(exc))
    finally:
        if args.profile == 'ingestion':
            leftovers = cleanup_ingestion(directory, root)
            if leftovers:
                report.update(status='blocked', cleanupRequired=leftovers)
        try:
            report['sourceAfter'] = source_identity(root)
            report['sourceUnchanged'] = report.get('sourceBefore') == report['sourceAfter']
            if not report['sourceUnchanged']:
                report['reason'] = 'Source changed during this run; rerun against the final source.'
                if report['status'] == 'passed':
                    report['status'] = 'blocked'
        except (OSError, subprocess.SubprocessError) as exc:
            report.update(status='blocked', reason='Cannot verify source identity: ' + type(exc).__name__)
        report['finishedAt'] = utc_now()
        output = directory / 'report.json'
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(report['status'].upper() + ': ' + str(output), flush=True)
    return EXIT_CODES[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
