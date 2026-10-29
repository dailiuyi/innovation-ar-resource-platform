"""Run selected Java module tests, rejecting zero-test or skipped-test delivery."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def test_counts(files):
    counts = dict(tests=0, failures=0, errors=0, skipped=0)
    for file in files:
        suite = ET.parse(file).getroot()
        for key in counts:
            counts[key] += int(suite.get(key, 0))
    return counts


def main():
    global ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module', required=True, help='Affected reactor module, e.g. ruoyi-framework')
    parser.add_argument('--tests', help='Optional Surefire test class selector')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--package', action='store_true', help='Run clean package (same tests) and record ruoyi-admin.jar path and SHA-256')
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    ROOT = args.root.resolve()
    if not re.fullmatch(r'ruoyi-[a-z]+', args.module) or not (ROOT / 'backend' / args.module / 'pom.xml').is_file():
        parser.error('Unknown module')
    if args.package and args.module != 'ruoyi-admin':
        parser.error('--package requires --module ruoyi-admin')
    evidence = ROOT / '.local/java-check' / uuid.uuid4().hex[:12]
    evidence.mkdir(parents=True)
    env = dict(os.environ)
    java = next((ROOT / '.local/java21').glob('jdk*/bin/java.exe'), None)
    if java:
        env['JAVA_HOME'] = str(java.parent.parent)
        env['PATH'] = str(java.parent) + os.pathsep + env.get('PATH', '')
    mvn = shutil.which('mvn.cmd' if os.name == 'nt' else 'mvn')
    if not mvn:
        print('Maven missing: provision the Java-capable execution image')
        raise SystemExit(2)
    command = [mvn, '-f', str(ROOT / 'backend/pom.xml'), '-pl', args.module, '-am',
               '-Dmaven.repo.local=' + str(ROOT / '.local/m2'), 'clean', 'package' if args.package else 'test', '-B', '-ntp']
    if args.offline:
        command.append('-o')
    if args.tests:
        command += ['-Dtest=' + args.tests, '-Dsurefire.failIfNoSpecifiedTests=false']
    before = time.time()
    with (evidence / 'maven.log').open('wb') as log:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=log)
    files = [p for p in (ROOT / 'backend').glob('*/target/surefire-reports/TEST-*.xml')
             if p.stat().st_mtime >= before]
    counts = test_counts(files)
    passed = result.returncode == 0 and counts['tests'] > 0 and not any(counts[k] for k in ('failures', 'errors', 'skipped'))
    log_text = (evidence / 'maven.log').read_text(encoding='utf-8', errors='replace').lower()
    environment_failure = result.returncode != 0 and any(message in log_text for message in (
        'could not transfer artifact', 'could not resolve dependencies', 'pluginresolutionexception',
        'unknown host', 'network is unreachable', 'permission denied', 'access is denied',
        'no space left on device', 'java_home environment variable is not defined correctly'))
    status = 'passed' if passed else ('blocked' if environment_failure else 'failed')
    report = {'status': status, 'module': args.module, 'command': command,
              'exitCode': result.returncode, **counts, 'seconds': round(time.time() - before, 2),
              'scope': 'Java tests only; HTTP/database/session revocation not established'}
    if args.package and passed:
        jar = ROOT / 'backend/ruoyi-admin/target/ruoyi-admin.jar'
        digest = hashlib.sha256()
        with jar.open('rb') as stream:
            for block in iter(lambda: stream.read(1 << 20), b''):
                digest.update(block)
        report['jar'] = {'path': str(jar), 'sha256': digest.hexdigest()}
    (evidence / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    print('Evidence: ' + str(evidence))
    raise SystemExit({'passed': 0, 'failed': 1, 'blocked': 2}[status])


if __name__ == '__main__':
    main()
