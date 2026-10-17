"""One logs-only validation attempt; does not install services or certify deployment."""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
BASE = '36c98ecd4537cc421e0ffe08321f62a10b0bed36'
BRANCH = 'review/c3c-security-validation-20261017'
MANIFEST = ROOT / 'validation/c3c/source-manifest.json'
SUPPORT = {'.github/workflows/python-check.yml',
           '.github/workflows/c3c-security-validation.yml',
           'validation/c3c/source-manifest.json', 'validation/c3c/run.py'}
RESULTS = []


def command(args, timeout=60, cwd=ROOT, capture=False, data=None):
    result = subprocess.run(args, cwd=cwd, input=data, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=None, timeout=timeout, check=True)
    return result.stdout if capture else ''


def safety():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest['baseline'] == BASE
    paths = manifest['aggregate_changed_files']
    assert len(paths) == len(set(paths)) == 48
    for name, digest in manifest['source_sha256'].items():
        data = command(['git', 'show', BASE + ':' + name], capture=True).encode() if name in SUPPORT else (ROOT/name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, name
    workflow = (ROOT/'.github/workflows/c3c-security-validation.yml').read_text()
    generic = (ROOT/'.github/workflows/python-check.yml').read_text()
    checks = {
        'exact_branch_push_only': 'branches: ['+BRANCH+']' in workflow and workflow.count('  push:') == 1 and not any(x in workflow for x in ('workflow_dispatch', 'pull_request', 'schedule:')),
        'standard_ubuntu_only': workflow.count('runs-on: ubuntu-24.04') == 1 and 'container:' not in workflow,
        'read_only_permissions': 'permissions:\n  contents: read\n' in workflow and workflow.count('permissions:') == 1,
        'bounded_runtime': 'timeout-minutes: 20' in workflow and '1050s' in workflow,
        'no_persistent_uploads': not any(x in workflow.lower() for x in ('upload-artifact', 'actions/cache', 'cache:', 'cache-to', 'push: true', 'snapshot:', 'packages:')),
        'no_production_secrets': not re.search(r'secrets\s*[.\[]', workflow),
        'no_persisted_credentials': 'persist-credentials: false' in workflow,
        'no_retries_or_matrix': 'github.run_attempt == 1' in workflow and 'matrix:' not in workflow and 'continue-on-error' not in workflow,
        'generic_workflow_excluded': 'branches-ignore: ['+BRANCH+']' in generic,
        'synthetic_native_fixtures': '--inside-capped-test-job' in (ROOT/'deployment/c3c/native_runner.py').read_text() and 'example.test' in Path(__file__).read_text(),
        'engineering_manifest_exact': set(paths) == set(manifest['c3b_preserved_files']) | set(manifest['c3c_preview_preserved']) | set(manifest['integration_added_files']),
    }
    print(json.dumps({'safety_checks': checks}, indent=2), flush=True)
    assert all(checks.values()), 'Workflow safety check failed'
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        assert os.environ['GITHUB_REF'] == 'refs/heads/'+BRANCH
        assert os.environ['GITHUB_RUN_ATTEMPT'] == '1'
        assert command(['git', 'rev-parse', 'HEAD^'], capture=True).strip() == BASE
        changed = set(command(['git', 'diff', '--name-only', BASE, 'HEAD'], capture=True).splitlines())
        assert changed == set(paths) | SUPPORT, sorted(changed)
        event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
        assert event['repository']['private'] is False, 'Public free-runner eligibility changed'
        assert event['repository']['full_name'] == 'SEOAuditSuite/SEO-Audit-Suite'
    print('PASS: 128 source hashes, exact 48-file engineering manifest, 11 workflow safety checks', flush=True)


def stage(name, operation):
    try:
        evidence = operation()
        record = {'stage': name, 'status': 'PASS', 'evidence': evidence}
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        record = {'stage': name, 'status': 'NOT VERIFIED', 'error': type(exc).__name__}
    except Exception as exc:
        record = {'stage': name, 'status': 'FAIL', 'error': type(exc).__name__, 'detail': str(exc)[:500]}
    RESULTS.append(record)
    print('C3C_RESULT '+json.dumps(record), flush=True)
    return record


def unix_api():
    sys.path.insert(0, str(ROOT))
    from deployment.c3c import controller, authentication, policy
    from deployment.c3c.store import Store
    import hmac
    class Connection(http.client.HTTPConnection):
        def connect(self):
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect(self.unix_path)
    with tempfile.TemporaryDirectory(prefix='c3c-api-') as directory:
        os.chmod(directory, 0o700)
        path = str(Path(directory)/'api.sock')
        keys = {owner: secrets.token_bytes(32) for owner in ('alice', 'bob')}
        with controller.Server(path, controller.Handler) as server:
            server.api = controller.API(Store(Path(directory)/'queue.sqlite'), keys)
            thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
            thread.start()
            def request(method, route, body=b'', owner='alice', headers=None):
                if headers is None:
                    stamp, nonce = str(int(time.time())), uuid.uuid4().hex
                    headers = {'X-SEO-Owner': owner, 'X-SEO-Time': stamp, 'X-SEO-Nonce': nonce,
                               'X-SEO-Signature': authentication.signature(keys[owner], method, route, body, owner, stamp, nonce)}
                conn = Connection('localhost', timeout=5); conn.unix_path = path
                try:
                    conn.request(method, route, body=body, headers=headers)
                    response = conn.getresponse()
                    return response.status, response.read(), headers
                finally:
                    conn.close()
            try:
                job = dict(owner='alice', url='https://example.test/', pages=1,
                           expires=int(time.time())+60, nonce=uuid.uuid4().hex)
                envelope = dict(job=job, signature=hmac.new(keys['alice'], policy.canonical(job), hashlib.sha256).hexdigest())
                code, raw, auth = request('POST', '/v1/jobs', json.dumps(envelope).encode())
                assert code == 202, code
                route = '/v1/jobs/'+json.loads(raw)['id']
                assert request('GET', route)[0] == 200
                assert request('GET', route, owner='bob')[0] == 404
                assert request('GET', route, headers={})[0] == 401
                assert request('POST', '/v1/jobs', json.dumps(envelope).encode(), headers=auth)[0] == 401
                assert request('DELETE', route, owner='bob')[0] == 404
                code, raw, _ = request('DELETE', route)
                assert code == 202 and json.loads(raw)['status'] == 'cancelled'
                return {'real_unix_http_checks': 7, 'keys': 'ephemeral synthetic keys; never printed',
                        'scope': 'signed admission/status/replay/owner denial/queued cancellation; no agent execution or mTLS claim'}
            finally:
                server.shutdown(); thread.join(timeout=2)


def docker_preflight():
    data = json.loads(command(['docker', 'info', '--format', '{{json .}}'], capture=True))
    assert data['OSType'] == 'linux' and data['CgroupVersion'] == '2'
    assert any('seccomp' in x for x in data['SecurityOptions'])
    return {k: data.get(k) for k in ('ServerVersion', 'OSType', 'CgroupVersion', 'SecurityOptions', 'MemTotal')}


def resource_image(work):
    tag = 'python:3.12-slim'
    command(['docker', 'pull', '--platform', 'linux/amd64', tag], timeout=180)
    digest = json.loads(command(['docker', 'image', 'inspect', tag], capture=True))[0]['RepoDigests'][0]
    assert re.fullmatch(r'[^@ ]+@sha256:[a-f0-9]{64}', digest)
    context = work/'fixture'; context.mkdir()
    shutil.copyfile(ROOT/'deployment/c3c/native_limits.py', context/'native_limits.py')
    (context/'Dockerfile').write_text('FROM '+digest+'\nWORKDIR /app\nCOPY native_limits.py /app/deployment/c3c/native_limits.py\nUSER 10001:10001\n')
    command(['docker', 'build', '--network=none', '-t', 'c3c-resource-fixture:local', str(context)], timeout=120)
    ident = command(['docker', 'image', 'inspect', '--format', '{{.Id}}', 'c3c-resource-fixture:local'], capture=True).strip()
    return ident, digest


def resources(image, work):
    from deployment.c3c.native_runner import run
    summary = run(image, work/'native-resources')
    rows = summary['resource_fixtures']
    for row in rows:
        print('RESOURCE_EVIDENCE '+json.dumps(row), flush=True)
    assert len(rows) == 4 and all(r['status'] == 'PASS' and r['cleanup_confirmed'] for r in rows)
    return {'fixtures': [{k: r[k] for k in ('mode', 'status', 'cleanup_confirmed')} for r in rows], 'image': image}


def reaper(image):
    from deployment.c3c.reaper import reap
    from deployment.c3c.supervisor import LABEL
    nonce = uuid.uuid4().hex; name = 'c3c-'+nonce+'-worker'
    try:
        command(['docker', 'run', '-d', '--name', name, '--label', LABEL+'='+nonce,
                 '--label', 'seo.c3c.managed=true', '--label', 'seo.c3c.expires='+str(int(time.time())-1),
                 '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges=true',
                 '--memory', '32m', '--memory-swap', '32m', '--pids-limit', '8', '--cpus', '.20',
                 '--user', '10001:10001', image, 'python', '-c', 'import time; time.sleep(60)'])
        removed = reap()
        assert nonce in removed
        assert not command(['docker', 'ps', '-aq', '--filter', 'label='+LABEL+'='+nonce], capture=True).strip()
        return {'expired_owned_container_removed': True, 'zero_owned_survivors': True,
                'scope': 'real external reaper invocation; supervisor crash and active cancellation remain separate'}
    finally:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=15)


def regression(work):
    wheels = work/'wheels'; wheels.mkdir()
    lock = ROOT/'deployment/c3c/requirements.linux.lock'
    command([sys.executable, '-m', 'pip', '--isolated', 'download', '--no-deps', '--only-binary=:all:',
             '--require-hashes', '--index-url', 'https://pypi.org/simple', '--dest', str(wheels), '-r', str(lock)], timeout=300)
    command([sys.executable, '-m', 'pip', '--isolated', 'install', '--no-index', '--find-links', str(wheels),
             '--require-hashes', '--only-binary=:all:', '-r', str(lock)], timeout=180)
    command([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], timeout=180)
    return {'suite': 'full unchanged engineering suite; raw unittest totals and skips above', 'wheels': str(wheels)}


def integrated_build(work):
    from deployment.c3c.prepare_build import prepare, verify_wheels
    tag = 'mcr.microsoft.com/playwright/python:v1.64.0-noble'
    command(['docker', 'pull', '--platform', 'linux/amd64', tag], timeout=180)
    digest = json.loads(command(['docker', 'image', 'inspect', tag], capture=True))[0]['RepoDigests'][0]
    assert re.fullmatch(r'[^@ ]+@sha256:[a-f0-9]{64}', digest)
    source = work/'verified-source'; source.mkdir()
    manifest = json.loads(MANIFEST.read_text())
    for name in manifest['source_sha256']:
        dest = source/name; dest.parent.mkdir(parents=True, exist_ok=True)
        if name in SUPPORT:
            dest.write_bytes(subprocess.check_output(['git', 'show', BASE+':'+name], cwd=ROOT))
        else:
            shutil.copyfile(ROOT/name, dest)
    context = prepare(source, MANIFEST, work/'context')
    for wheel in (work/'wheels').iterdir(): shutil.copyfile(wheel, context/'wheelhouse'/wheel.name)
    verify_wheels(context/'wheelhouse', context/'deployment/c3c/requirements.linux.lock')
    ids = {}
    for target in ('worker', 'broker'):
        tagname = 'c3c-'+target+':local'
        command(['docker', 'build', '--network=none', '--platform', 'linux/amd64', '--build-arg', 'BASE_IMAGE='+digest,
                 '-f', str(context/'deployment/c3c/Dockerfile.integrated'), '--target', target, '-t', tagname, str(context)], timeout=240)
        ids[target] = command(['docker', 'image', 'inspect', '--format', '{{.Id}}', tagname], capture=True).strip()
    return {'base_digest': digest, 'immutable_image_ids': ids,
            'scope': 'unchanged integrated images built; sandbox/browser/broker runtime acceptance remains separate'}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--safety', action='store_true'); parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(); safety()
    if not args.execute: return 0
    assert os.environ.get('GITHUB_ACTIONS') == 'true', 'Native execution is restricted to the approved disposable runner'
    stage('real_signed_unix_api', unix_api)
    with tempfile.TemporaryDirectory(prefix='c3c-validation-') as temporary:
        work = Path(temporary)
        docker = stage('docker_cgroup_v2_preflight', docker_preflight)
        if docker['status'] == 'PASS':
            built = stage('isolated_resource_fixture_image', lambda: resource_image(work))
            if built['status'] == 'PASS':
                image = built['evidence'][0]
                stage('native_cgroup_memory_pid_cpu_storage', lambda: resources(image, work))
                stage('native_expiry_reaper', lambda: reaper(image))
        reg = stage('locked_full_regression', lambda: regression(work))
        if reg['status'] == 'PASS' and docker['status'] == 'PASS':
            stage('unchanged_integrated_image_builds', lambda: integrated_build(work))
        survivors = stage('final_zero_managed_survivors', lambda: final_cleanup())
    remaining = ['real non-root Chromium sandbox through broker', 'mTLS gateway',
                 'reachable IPv4/IPv6/metadata canaries and packet/firewall evidence',
                 'active native cancellation and supervisor-crash cleanup',
                 'filesystem/credential quotas and calibrated host headroom', 'separate C3B Windows acceptance']
    summary = {'status': 'FAIL' if any(x['status']=='FAIL' for x in RESULTS) else 'NOT VERIFIED',
               'stages': RESULTS, 'remaining_not_verified': remaining,
               'deployment': 'HOLD', 'uploads': 'none; logs only'}
    print('C3C_FINAL '+json.dumps(summary, indent=2), flush=True)
    return 1 if summary['status'] == 'FAIL' else 2


def final_cleanup():
    ids = command(['docker', 'ps', '-aq', '--filter', 'label=seo.c3c.managed=true'], capture=True).split()
    if ids: command(['docker', 'rm', '-f', *ids], timeout=30)
    remaining = command(['docker', 'ps', '-aq', '--filter', 'label=seo.c3c.managed=true'], capture=True).strip()
    assert not remaining
    return {'zero_managed_containers': True, 'forced_cleanup_was_needed': bool(ids)}


if __name__ == '__main__':
    raise SystemExit(main())
