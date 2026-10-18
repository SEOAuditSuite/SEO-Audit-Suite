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
DIAGNOSTIC_PARENT = 'a1a73548532b1aa8b001123dee0b0850c880700d'
BRANCH = 'review/c3c-security-validation-20261017'
MANIFEST = ROOT / 'validation/c3c/source-manifest.json'
SUPPORT = {'.github/workflows/python-check.yml',
           '.github/workflows/c3c-security-validation.yml',
           'validation/c3c/source-manifest.json', 'validation/c3c/run.py'}
RESULTS = []
OWNED_NONCES = set()
OWNED_IMAGES = set()
sys.path.insert(0,str(ROOT))
from validation.c3c import policy_attachment as sandbox_attachment


def command(args, timeout=60, cwd=ROOT, capture=False, data=None):
    if args[:2] in (['docker','create'],['docker','run']):remember_container(args[2:])
    if args[:3]==['docker','volume','create']:
        name=args[-1];match=re.fullmatch(r'c3c-([a-f0-9]{32})-ipc',name)
        if not match or 'seo.c3c.job='+match[1] not in args or 'seo.c3c.managed=true' not in args:raise RuntimeError('Invalid volume ownership intent')
        require_absent_object('volume',name)
        OWNED_NONCES.add(match[1]);save_ownership()
    image_reference=None
    if args[:2]==['docker','build']:
        image_reference=args[args.index('-t')+1]
        require_absent_image(image_reference)
    elif args[:2]==['docker','pull']:
        reference=args[-1]
        if not image_exists(reference):image_reference=reference
    if image_reference:remember_image(image_reference)
    result = subprocess.run(args, cwd=cwd, input=data, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=None, timeout=timeout, check=True)
    return result.stdout if capture else ''


def safety():
    manifest = json.loads(MANIFEST.read_text())
    candidate=json.loads((ROOT/'validation/c3c/candidate-manifest.json').read_text())
    assert candidate['parent']==DIAGNOSTIC_PARENT
    assert set(candidate['sha256'])==set(candidate['changed_paths'])-{'validation/c3c/candidate-manifest.json'}
    for name,digest in candidate['sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
    sandbox_attachment.verify_package()
    corrections = json.loads((ROOT/'validation/c3c/compatibility-corrections.json').read_text())
    assert set(corrections)=={'deployment/c3c/native_runner.py','deployment/c3c/supervisor.py'}
    assert manifest['baseline'] == BASE
    paths = manifest['aggregate_changed_files']
    assert len(paths) == len(set(paths)) == 48
    for name, digest in manifest['source_sha256'].items():
        data = command(['git', 'show', BASE + ':' + name], capture=True).encode() if name in SUPPORT else (ROOT/name).read_bytes()
        if name in corrections:
            correction=corrections[name]
            assert correction['before']==digest
            assert hashlib.sha256(data).hexdigest()==correction['after'], name
            assert hashlib.sha256(data.replace(b",'--log-opt','compress=false'",b'')).hexdigest()==digest, name
        else:
            assert hashlib.sha256(data).hexdigest() == digest, name
    workflow = (ROOT/'.github/workflows/c3c-security-validation.yml').read_text()
    generic = (ROOT/'.github/workflows/python-check.yml').read_text()
    assert 'fetch-depth: 10' in workflow
    assert workflow.index('--prepare-job') < workflow.index('780s python -u validation/c3c/run.py --execute') < workflow.index('--cleanup-job')
    assert "if: always()" in workflow and '--cleanup' in workflow
    assert '--replace' not in workflow and 'sudo -n -- /usr/bin/python3 -I' in workflow
    checks = {
        'exact_branch_push_only': 'branches: ['+BRANCH+']' in workflow and workflow.count('  push:') == 1 and not any(x in workflow for x in ('workflow_dispatch', 'pull_request', 'schedule:')),
        'standard_ubuntu_only': workflow.count('runs-on: ubuntu-24.04') == 1 and 'container:' not in workflow,
        'read_only_permissions': 'permissions:\n  contents: read\n' in workflow and workflow.count('permissions:') == 1,
        'bounded_runtime': 'timeout-minutes: 20' in workflow and '780s' in workflow,
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
        assert command(['git', 'rev-parse', 'HEAD^'], capture=True).strip() == DIAGNOSTIC_PARENT
        assert event_before() == DIAGNOSTIC_PARENT
        assert command(['git','merge-base','--is-ancestor',BASE,'HEAD'],capture=True)==''
        assert command(['git','ls-remote','https://github.com/SEOAuditSuite/SEO-Audit-Suite.git','refs/heads/main'],capture=True).split()[0]==BASE
        diagnostic_changes = set(command(['git', 'diff', '--name-only', 'HEAD^', 'HEAD'], capture=True).splitlines())
        candidate=json.loads((ROOT/'validation/c3c/candidate-manifest.json').read_text())
        assert diagnostic_changes == set(candidate['changed_paths'])
        changed = set(command(['git', 'diff', '--name-only', BASE, 'HEAD'], capture=True).splitlines())
        assert changed == set(paths) | SUPPORT | set(candidate['cumulative_support_paths']), sorted(changed)
        event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
        assert event['repository']['private'] is False, 'Public free-runner eligibility changed'
        assert event['repository']['full_name'] == 'SEOAuditSuite/SEO-Audit-Suite'
    print('PASS: 128 source hashes with two explicitly verified logging-only corrections; 11 workflow safety checks', flush=True)


def event_before():return json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())['before']


def ownership_path():
    job=os.environ.get('C3C_POLICY_JOB')
    if not job:return None
    sandbox_attachment.state_directory(job)
    return Path(os.environ['RUNNER_TEMP'])/('c3c-owned-'+job+'.json')


def save_ownership():
    path=ownership_path()
    if path is None:return
    if path.is_symlink():raise RuntimeError('Unsafe job ownership receipt')
    with path.open('w') as stream:json.dump(dict(nonces=sorted(OWNED_NONCES),images=sorted(OWNED_IMAGES)),stream)
    path.chmod(0o600)


def remember_container(args):
    name=args[args.index('--name')+1]
    match=re.fullmatch(r'c3c-([a-f0-9]{32})-(worker|broker)',name)
    if not match or 'seo.c3c.job='+match[1] not in args or 'seo.c3c.managed=true' not in args:raise RuntimeError('Invalid job ownership intent')
    if ownership_path() is not None:
        require_absent_object('container',name)
    # UUID identity is recorded before create, including failed/timed-out creation.
    OWNED_NONCES.add(match[1]);save_ownership()


def image_exists(reference):
    return not object_absent('image',reference)


def object_absent(kind,reference):
    with tempfile.TemporaryFile() as errors:
        result=subprocess.run(['docker',kind,'inspect',reference],stdout=subprocess.DEVNULL,stderr=errors,timeout=10)
        errors.seek(0);error=errors.read(4097).decode(errors='replace')
    if result.returncode==0:return False
    expected={'image':'No such image:','container':'No such container:','volume':'No such volume:'}[kind]
    # Docker container inspect reports "No such container"; generic object errors are also documented.
    if result.returncode==1 and len(error)<=4096 and (expected+' '+reference in error or 'No such object: '+reference in error):return True
    raise RuntimeError('Ownership inventory failed; absence not demonstrated')


def require_absent_object(kind,reference):
    if not object_absent(kind,reference):raise RuntimeError('Refuse to adopt pre-existing '+kind)


def require_absent_image(reference):
    if image_exists(reference):raise RuntimeError('Refuse to overwrite a pre-existing validation image tag')


def remember_image(reference):
    if not re.fullmatch(r'(?:c3c-(?:resource-fixture|worker|broker):local|python:3.12-slim|mcr\.microsoft\.com/playwright(?:/python)?@sha256:[a-f0-9]{64})',reference):raise RuntimeError('Unreviewed image reference')
    OWNED_IMAGES.add(reference);save_ownership()


def stage(name, operation):
    try:
        evidence = operation()
        record = {'stage': name, 'status': 'PASS', 'evidence': evidence}
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        record = {'stage': name, 'status': 'NOT VERIFIED', 'error': type(exc).__name__}
    except sandbox_attachment.Blocked as exc:
        record = {'stage':name,'status':'NOT VERIFIED','detail':sanitize(str(exc),1024)}
    except ImageUnavailable as exc:
        record = {'stage': name, 'status': 'NOT VERIFIED', 'error': type(exc).__name__, 'detail': str(exc)}
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


def sanitize(value, limit=4096):
    from validation.c3c.sandbox_probe import sanitize as redact
    if isinstance(value, bytes): value=value.decode('utf-8',errors='replace')
    return redact(value,limit)[:limit]


def diagnostic_runtime():
    from deployment.c3c.supervisor import Runtime
    class DiagnosticRuntime(Runtime):
        def call(self, args, *, data=None, cleanup=False):
            if args[0]=='create':remember_container(args[1:])
            # Mirror the preserved runtime budgets/environment; only add evidence.
            remaining = 10 if cleanup else min(15, self.deadline-time.monotonic())
            if remaining <= 0: raise TimeoutError('Whole-operation deadline reached')
            if not args or args[0] not in ('create', 'start', 'inspect', 'logs', 'rm', 'ps','volume'):
                raise ValueError('Unexpected diagnostic Docker operation')
            record = {'command': [sanitize(str(x), 256) for x in ['docker', *args]], 'cleanup': cleanup}
            with tempfile.TemporaryFile() as errors:
                try:
                    result = subprocess.run(['docker', *args], input=data, stdout=subprocess.PIPE, stderr=errors,
                                            timeout=remaining, env={k:v for k,v in os.environ.items() if k in ('PATH','HOME')})
                    record['exit_code'] = result.returncode
                except subprocess.TimeoutExpired:
                    record.update(exit_code=None, error='TimeoutExpired')
                    raise
                finally:
                    errors.seek(0)
                    raw = errors.read(4097)
                    record.update(stderr=sanitize(raw[:4096]), stderr_truncated=len(raw)>4096)
                    print('DOCKER_DIAGNOSTIC '+json.dumps(record), flush=True)
            if len(result.stdout)>1024*1024: raise RuntimeError('Unexpected runtime response size')
            if result.returncode: raise RuntimeError('Runtime command failed; see bounded DOCKER_DIAGNOSTIC evidence')
            return result.stdout
    return DiagnosticRuntime


def resources(image, work):
    from deployment.c3c import native_runner
    original = native_runner.Runtime
    native_runner.Runtime = diagnostic_runtime()
    try:
        summary = native_runner.run(image, work/'native-resources')
    finally:
        native_runner.Runtime = original
    rows = summary['resource_fixtures']
    for row in rows:
        print('RESOURCE_EVIDENCE '+json.dumps(row), flush=True)
    assert len(rows) == 4 and all(r['status'] == 'PASS' and r['cleanup_confirmed'] for r in rows)
    return {'fixtures': [{k: r[k] for k in ('mode', 'status', 'cleanup_confirmed')} for r in rows], 'image': image}


# Validation-only ceiling. Production Limits().pids remains 64 and is not accepted.
VALIDATION_BROWSER_TASKS = 128
PID_BUDGET_PROBE = r'''import errno,json,os,signal
from pathlib import Path
root=Path('/sys/fs/cgroup')
def event():return int(dict(line.split() for line in (root/'pids.events').read_text().splitlines())['max'])
assert os.getuid()==10001 and os.getgid()==10001
assert (root/'pids.max').read_text().strip()=='128'
before=event();children=[];denial=None;read_fd,write_fd=os.pipe()
try:
    for _ in range(128):
        try:pid=os.fork()
        except OSError as exc:denial=exc.errno;break
        if pid==0:
            try:
                os.close(write_fd);os.read(read_fd,1)
            finally:os._exit(0)
        children.append(pid)
    current=int((root/'pids.current').read_text());delta=event()-before
    assert denial==errno.EAGAIN and current==128 and delta>0
finally:
    os.close(write_fd);os.close(read_fd)
    for pid in children:
        try:os.kill(pid,signal.SIGKILL)
        except ProcessLookupError:pass
    for pid in children:os.waitpid(pid,0)
assert int((root/'pids.current').read_text())==1
print(json.dumps(dict(status='PASS',pids_max=128,at_denial=current,event_delta=delta,errno=denial,owned_children_reaped=True)))
'''


def native_pid_budget(image):
    """Separate sequential synthetic container: never consumes the browser budget.

    Default Docker AppArmor/seccomp remain enforced here. Reviewed custom browser
    policies are attached only by native_browser, whose entrypoint is unchanged.
    """
    nonce=uuid.uuid4().hex;name='c3c-'+nonce+'-worker';created=False
    args=browser_options(image,nonce)
    args[-1:]=['-c',PID_BUDGET_PROBE]
    try:
        command(['docker',*args],timeout=15);created=True
        info=json.loads(command(['docker','inspect',name],capture=True))[0]
        from deployment.c3c.supervisor import verify_container
        from deployment.c3c.policy import Limits
        verify_container(info,Limits(pids=VALIDATION_BROWSER_TASKS))
        assert not any(info['HostConfig'].get(key) for key in ('CapAdd','Binds','Devices','VolumesFrom'))
        assert info.get('AppArmorProfile')=='docker-default'
        assert info['HostConfig'].get('SecurityOpt')==['no-new-privileges=true']
        raw=command(['docker','start','--attach',name],capture=True,timeout=15)
        assert len(raw)<=1024
        record=json.loads(raw)
        assert record.get('status')=='PASS' and record.get('pids_max')==VALIDATION_BROWSER_TASKS
        assert record.get('at_denial')==VALIDATION_BROWSER_TASKS and record.get('errno')==11
        assert type(record.get('event_delta')) is int and record['event_delta']>0
        assert record.get('owned_children_reaped') is True
        return record
    finally:
        if created or nonce in OWNED_NONCES:command(['docker','rm','--force',name],timeout=15)
        assert not command(['docker','ps','-aq','--filter','label=seo.c3c.job='+nonce],capture=True).strip()


def reaper(image):
    from deployment.c3c.reaper import reap
    from deployment.c3c.supervisor import LABEL
    nonce = uuid.uuid4().hex; name = 'c3c-'+nonce+'-worker'
    created=False
    try:
        command(['docker', 'run', '-d', '--name', name, '--label', LABEL+'='+nonce,
                 '--label', 'seo.c3c.managed=true', '--label', 'seo.c3c.expires='+str(int(time.time())-1),
                 '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges=true',
                 '--memory', '32m', '--memory-swap', '32m', '--pids-limit', '8', '--cpus', '.20',
                 '--user', '10001:10001', image, 'python', '-c', 'import time; time.sleep(60)'])
        created=True
        base_runtime=diagnostic_runtime()(60)
        class ScopedReaper:
            def call(self,args,**kwargs):
                if args[0]=='ps':args=[*args,'--filter','label='+LABEL+'='+nonce]
                return base_runtime.call(args,**kwargs)
        removed = reap(runtime=ScopedReaper())
        assert nonce in removed
        assert not command(['docker', 'ps', '-aq', '--filter', 'label='+LABEL+'='+nonce], capture=True).strip()
        return {'expired_owned_container_removed': True, 'zero_owned_survivors': True,
                'scope': 'real external reaper invocation; supervisor crash and active cancellation remain separate'}
    finally:
        if created or nonce in OWNED_NONCES:subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=15)


def regression(work):
    wheels = work/'wheels'; wheels.mkdir()
    lock = ROOT/'deployment/c3c/requirements.linux.lock'
    command([sys.executable, '-m', 'pip', '--isolated', 'download', '--no-deps', '--only-binary=:all:',
             '--require-hashes', '--index-url', 'https://pypi.org/simple', '--dest', str(wheels), '-r', str(lock)], timeout=300)
    command([sys.executable, '-m', 'pip', '--isolated', 'install', '--no-index', '--find-links', str(wheels),
             '--require-hashes', '--only-binary=:all:', '-r', str(lock)], timeout=180)
    command([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], timeout=180)
    return {'suite': 'full unchanged engineering suite; raw unittest totals and skips above', 'wheels': str(wheels)}


class ImageUnavailable(RuntimeError):
    pass


def image_preflight():
    from validation.c3c import image_candidate
    inputs=json.loads(image_candidate.INPUTS.read_text())
    try:
        rows=image_candidate.verify_remote_images(inputs)
    except (image_candidate.Blocked,OSError) as exc:
        raise ImageUnavailable('Reviewed seed/donor preflight blocked: '+str(exc)) from None
    return {'digest_reference':inputs['seed_image'], 'browser_digest_reference':inputs['browser_image'],
            'registry_evidence':rows,'scope':'Availability only; actual build and sandbox remain mandatory'}


def integrated_build(work, digest):
    from deployment.c3c.prepare_build import prepare, verify_wheels
    from validation.c3c import image_candidate
    assert re.fullmatch(r'[^@ ]+@sha256:[a-f0-9]{64}', digest)
    inputs=json.loads(image_candidate.INPUTS.read_text())
    assert digest==inputs['seed_image']
    for reference in (digest,inputs['browser_image']):
        command(['docker','pull','--platform','linux/amd64',reference],timeout=180)
    source = work/'verified-source'; source.mkdir()
    manifest = json.loads(MANIFEST.read_text())
    corrections=json.loads((ROOT/'validation/c3c/compatibility-corrections.json').read_text())
    for name,record in corrections.items(): manifest['source_sha256'][name]=record['after']
    for name in manifest['source_sha256']:
        dest = source/name; dest.parent.mkdir(parents=True, exist_ok=True)
        if name in SUPPORT:
            dest.write_bytes(subprocess.check_output(['git', 'show', BASE+':'+name], cwd=ROOT))
        else:
            shutil.copyfile(ROOT/name, dest)
    corrected_manifest=work/'corrected-source-manifest.json'
    corrected_manifest.write_text(json.dumps(manifest))
    sanitized=prepare(source,corrected_manifest,work/'sanitized-context')
    # Donor browser paths and exact SDK versions are checked by the offline recipe.
    image_candidate.prepare(sanitized,work/'wheels',work/'context')
    context=work/'context'
    verify_wheels(context/'wheelhouse', context/'deployment/c3c/requirements.linux.lock')
    ids = {}
    for target in ('worker', 'broker'):
        tagname = 'c3c-'+target+':local'
        command(['docker', 'build', '--network=none', '--platform', 'linux/amd64', '--build-arg', 'BASE_IMAGE='+digest,'--build-arg','BROWSER_IMAGE='+inputs['browser_image'],
                 '-f', str(context/'Dockerfile.candidate'), '--target', target, '-t', tagname, str(context)], timeout=240)
        ids[target] = command(['docker', 'image', 'inspect', '--format', '{{.Id}}', tagname], capture=True).strip()
    return {'base_digest': digest, 'immutable_image_ids': ids,
            'browser_donor':inputs['browser_image'], 'scope':'Candidate images built; sandbox and broker runtime acceptance remain separate'}


def browser_options(image,nonce):
    return ['create','--name','c3c-'+nonce+'-worker','--label','seo.c3c.managed=true',
            '--label','seo.c3c.job='+nonce,'--label','seo.c3c.expires='+str(int(time.time()+60)),
            '--user','10001:10001','--read-only','--cap-drop','ALL',
            '--security-opt','no-new-privileges=true','--memory','1536m','--memory-swap','1536m',
            '--cpus','1.0','--pids-limit',str(VALIDATION_BROWSER_TASKS),'--ulimit','nofile=256:256','--ulimit','core=0:0',
            '--ipc','private','--network','none','--tmpfs','/tmp:rw,nosuid,nodev,size=256m,mode=1777',
            '--log-driver','local','--log-opt','max-size=10m','--log-opt','max-file=1','--log-opt','compress=false',
            '--env','HOME=/tmp','--env','PYTHONDONTWRITEBYTECODE=1',
            '--entrypoint','python',image,'/app/validation/c3c/sandbox_probe.py']


def native_browser(image):
    from deployment.c3c.supervisor import image_id
    image_id(image);nonce=uuid.uuid4().hex;name='c3c-'+nonce+'-worker'
    host_policy=sandbox_attachment.readonly_preflight()
    worker_args=sandbox_attachment.attach_worker(browser_options(image,nonce),host_policy)
    created=False
    try:
        command(['docker',*worker_args],timeout=15)
        created=True
        details=json.loads(command(['docker','inspect',name],capture=True))[0]
        print('C3C_POLICY_ATTACHMENT '+json.dumps(sandbox_attachment.verify_container(details,host_policy)),flush=True)
        host=details['HostConfig']
        print('NATIVE_BROWSER_CONTAINER '+sanitize(json.dumps(dict(
            user=details['Config']['User'],apparmor_profile=details.get('AppArmorProfile'),
            security_opt=host.get('SecurityOpt'),cap_drop=host.get('CapDrop'),
            readonly=host.get('ReadonlyRootfs'),pids_limit=host.get('PidsLimit'),
            memory=host.get('Memory'),nano_cpus=host.get('NanoCpus'),ipc=host.get('IpcMode'),
            network=host.get('NetworkMode')))),flush=True)
        with tempfile.TemporaryFile() as log:
            timed_out=False;result=None
            try:
                sandbox_attachment.require_ready(host_policy)
                result=subprocess.run(['docker','start','--attach',name],stdout=log,stderr=subprocess.STDOUT,timeout=40)
            except subprocess.TimeoutExpired:
                timed_out=True
            finally:
                log.seek(0);raw=log.read(32769)
                print('NATIVE_BROWSER_EVIDENCE '+sanitize(raw[:32768],32768),flush=True)
                state=json.loads(command(['docker','inspect','--format','{{json .State}}',name],capture=True))
                print('NATIVE_BROWSER_EXIT '+sanitize(json.dumps(dict(
                    docker_attach_exit=result.returncode if result else None,attach_timeout=timed_out,
                    container_exit=state.get('ExitCode') if not state.get('Running') else None,
                    running=state.get('Running'),oom_killed=state.get('OOMKilled'),
                    engine_error=state.get('Error'),
                    note='Container exit is distinct from Chromium exit reported by Playwright'))),flush=True)
            assert not timed_out and len(raw)<=32768 and result.returncode==0,'Native browser probe did not pass'
            gates=browser_evidence(raw)
        return {'status':'PASS','gates':gates,'scope':'Pinned non-root sandbox and synthetic original secure_context; separate denial-only broker IPC gate; broker-backed network rendering/mTLS NOT VERIFIED'}
    finally:
        if created or nonce in OWNED_NONCES:command(['docker','rm','--force',name],timeout=15)
        assert not command(['docker','ps','-aq','--filter','label=seo.c3c.job='+nonce],capture=True).strip()


def browser_evidence(raw):
    records=[];namespaces=[]
    for line in raw.decode('utf-8',errors='replace').splitlines():
        if line.startswith('C3C_BROWSER_DIAGNOSTIC '):records.append(json.loads(line.split(' ',1)[1]))
        if line.startswith('C3C_NAMESPACE_DIAGNOSTIC '):namespaces.append(json.loads(line.split(' ',1)[1]))
    expected=['setns_invalid_fd','mount_null_target','outer_chroot','unshare_zero','unshare_mount_namespace','user_namespace_chain','full_namespace_chain']
    assert len(namespaces)==1 and namespaces[0]['status']=='PASS'
    rows=namespaces[0]['checks']
    assert [r['stage'] for r in rows]==expected and all(r['status']=='PASS' for r in rows)
    for kind,status in [('launch','STARTED'),('sandbox_page','PASS'),('synthetic_dom','PASS')]:
        assert any(r.get('kind')==kind and r.get('status')==status for r in records),'Missing positive '+kind+' evidence'
    final=[r for r in records if r.get('kind')=='task_resources' and r.get('phase')=='acceptance_complete' and r.get('status')=='PASS']
    assert len(final)==1,'Missing final task-budget acceptance evidence'
    counters=final[0]['evidence']['cgroup']
    assert counters.get('pids.max')==str(VALIDATION_BROWSER_TASKS)
    assert counters.get('pids.events')=={'max':'0'},'Positive browser workload hit the PID controller'
    peak=counters.get('pids.peak','')
    assert isinstance(peak,str) and peak.isdigit() and 0<int(peak)<=VALIDATION_BROWSER_TASKS,'Missing/invalid task peak'
    print('C3C_BROWSER_TASK_HEADROOM '+json.dumps(dict(ceiling=VALIDATION_BROWSER_TASKS,observed_peak=int(peak),unused_tasks=VALIDATION_BROWSER_TASKS-int(peak),scope='One synthetic run, not production calibration')),flush=True)
    return {name:'PASS' for name in ('negative_security_controls','namespace_prerequisites','chromium_secure_startup','chromium_sandbox_page','synthetic_dom_rendering','bounded_task_budget')}


IPC_PROBE = '''import json,socket,os
from safe_http import SafeSession,TransportError
assert os.getuid()==10001
def exchange(payload):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
        connection.settimeout(5);connection.connect('/run/seo-broker/broker.sock')
        connection.sendall(json.dumps(payload).encode()+b'\\n')
        with connection.makefile('rb') as stream:raw=stream.readline(4097)
    assert len(raw)<=4096 and raw.endswith(b'\\n')
    return json.loads(raw)
request=dict(url='http://127.0.0.1/',headers={},max_bytes=1024,seconds=2)
assert exchange(request).get('ok') is False
assert exchange(dict(request,method='POST')).get('ok') is False
try:
    SafeSession().get('http://127.0.0.1/',timeout=2,max_bytes=1024)
except TransportError:pass
else:raise AssertionError('Private target unexpectedly accepted')
print(json.dumps(dict(status='PASS',uid=os.getuid(),actual_unix_exchange=True,private_destination_denied=True,non_get_schema_denied=True,worker_socket_bridge_fails_closed=True)))
'''


def ipc_options(image,nonce,broker=False):
    from deployment.c3c.supervisor import options
    from deployment.c3c.policy import Limits
    args=options('c3c-'+nonce+('-broker' if broker else '-worker'),nonce,image,Limits(),broker)
    # A denial-only synthetic fixture needs no outbound network. Resource,
    # identity, IPC mount and privilege controls remain the production values.
    args[args.index('--network')+1]='none'
    if not broker:
        args[-1:-1]=['--entrypoint','python']
        args+=['-c',IPC_PROBE]
    return args


def native_broker_ipc(ids):
    nonce=uuid.uuid4().hex;volume='c3c-'+nonce+'-ipc'
    names=['c3c-'+nonce+'-broker','c3c-'+nonce+'-worker']
    created=[];volume_created=False
    try:
        command(['docker','volume','create','--driver','local','--opt','type=tmpfs',
                 '--opt','device=tmpfs','--opt','o=size=1m,uid=10001,gid=10001,mode=0700',
                 '--label','seo.c3c.job='+nonce,'--label','seo.c3c.managed=true',volume],timeout=15)
        volume_created=True
        for name,image,broker in [(names[0],ids['broker'],True),(names[1],ids['worker'],False)]:
            command(['docker',*ipc_options(image,nonce,broker)],timeout=15);created.append(name)
            info=json.loads(command(['docker','inspect',name],capture=True))[0]
            h=info['HostConfig'];memory=(256 if broker else 1536)*1024*1024
            assert h['Memory']==h['MemorySwap']==memory and h['PidsLimit']==(16 if broker else 64)
            assert h['NanoCpus']==int((.25 if broker else 1.0)*1e9) and h['NetworkMode']=='none'
            assert h['ReadonlyRootfs'] and not h['Privileged'] and h['IpcMode']=='private'
            assert info['Config']['User']=='10001:10001' and 'ALL' in h['CapDrop']
            assert 'no-new-privileges=true' in h['SecurityOpt']
            mount=next(m for m in info['Mounts'] if m['Destination']=='/run/seo-broker')
            assert mount['Name']==volume and mount['RW'] is broker
        command(['docker','start',names[0]],timeout=15)
        for _ in range(15):
            ready=subprocess.run(['docker','exec',names[0],'test','-S','/run/seo-broker/broker.sock'],capture_output=True,timeout=3)
            if ready.returncode==0:break
            time.sleep(.1)
        else:raise RuntimeError('Native broker socket not ready')
        with tempfile.TemporaryFile() as log:
            result=subprocess.run(['docker','start','--attach',names[1]],stdout=log,stderr=subprocess.STDOUT,timeout=20)
            log.seek(0);raw=log.read(32769)
            print('NATIVE_BROKER_IPC_EVIDENCE '+sanitize(raw[:32768],32768),flush=True)
            assert len(raw)<=32768 and result.returncode==0,'Native broker IPC fixture failed'
            outcome=json.loads(raw)
            assert outcome['status']=='PASS' and outcome['actual_unix_exchange'] is True
        return {'status':'PASS','scope':'Real container-to-container Unix IPC and worker bridge denial; positive HTTP/rendering, firewall and mTLS remain NOT VERIFIED'}
    finally:
        for name in reversed(created):command(['docker','rm','--force',name],timeout=15)
        if volume_created:command(['docker','volume','rm',volume],timeout=15)
        assert not command(['docker','ps','-aq','--filter','label=seo.c3c.job='+nonce],capture=True).strip()
        assert not command(['docker','volume','ls','-q','--filter','label=seo.c3c.job='+nonce],capture=True).strip()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--safety', action='store_true'); parser.add_argument('--execute', action='store_true');parser.add_argument('--cleanup',action='store_true')
    args = parser.parse_args()
    if args.cleanup:
        # Cleanup cannot depend on remote main remaining unchanged mid-job.
        assert os.environ.get('GITHUB_ACTIONS')=='true'
        assert os.environ.get('GITHUB_REPOSITORY')=='SEOAuditSuite/SEO-Audit-Suite'
        assert os.environ.get('GITHUB_REF')=='refs/heads/'+BRANCH and os.environ.get('GITHUB_RUN_ATTEMPT')=='1'
        assert os.environ.get('C3C_POLICY_JOB')==os.environ['GITHUB_RUN_ID']+'-1'
        print('C3C_JOB_CLEANUP '+json.dumps(final_cleanup()),flush=True);return 0
    safety()
    if not args.execute: return 0
    assert os.environ.get('GITHUB_ACTIONS') == 'true', 'Native execution is restricted to the approved disposable runner'
    sys.path.insert(0, str(ROOT))
    with tempfile.TemporaryDirectory(prefix='c3c-validation-') as temporary:
        work = Path(temporary)
        docker = stage('docker_cgroup_v2_preflight', docker_preflight)
        host_policy=stage('sandbox_policy_host_preflight',sandbox_attachment.require_host_preflight)
        preflight = stage('candidate_image_preflight',image_preflight) if docker['status']=='PASS' and host_policy['status']=='PASS' else None
        budget_check=None
        if preflight and preflight['status']=='PASS':
            built = stage('isolated_resource_fixture_image', lambda: resource_image(work))
            if built['status'] == 'PASS':
                image = built['evidence'][0]
                resource_check=stage('native_cgroup_memory_pid_cpu_storage', lambda: resources(image, work))
                if resource_check['status']=='PASS':budget_check=stage('native_validation_128_task_enforcement',lambda:native_pid_budget(image))
                stage('native_expiry_reaper', lambda: reaper(image))
        if preflight and preflight['status']=='PASS' and budget_check and budget_check['status']=='PASS':
            reg = stage('locked_full_regression', lambda: regression(work))
            if reg['status']=='PASS':
                integrated=stage('candidate_integrated_image_builds',lambda:integrated_build(work,preflight['evidence']['digest_reference']))
                if integrated['status']=='PASS':
                    browser=stage('native_candidate_browser_sandbox',lambda:native_browser(integrated['evidence']['immutable_image_ids']['worker']))
                    if browser['status']=='PASS':stage('native_container_broker_ipc',lambda:native_broker_ipc(integrated['evidence']['immutable_image_ids']))
        stage('real_signed_unix_api',unix_api)
        if not preflight or preflight['status']!='PASS':
            print('STOP: Required image preflight not passed. No integrated pull/build, dependency change or incompatible substitution.', flush=True)
        survivors = stage('final_zero_managed_survivors', lambda: final_cleanup())
        if host_policy['status']=='PASS':stage('global_docker_policy_preserved',lambda:sandbox_attachment.verify_defaults(host_policy['evidence']))
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
    path=ownership_path()
    if path and path.exists():
        if path.is_symlink():raise RuntimeError('Unsafe ownership receipt')
        saved=json.loads(path.read_text())
        for nonce in saved['nonces']:
            if not re.fullmatch('[a-f0-9]{32}',nonce):raise RuntimeError('Invalid cleanup nonce')
            OWNED_NONCES.add(nonce)
        for reference in saved['images']:remember_image(reference)
    removed=0
    for nonce in sorted(OWNED_NONCES):
        filters=['--filter','label=seo.c3c.managed=true','--filter','label=seo.c3c.job='+nonce]
        ids=command(['docker','ps','-aq',*filters],capture=True).split()
        if ids:
            rows=json.loads(command(['docker','inspect',*ids],capture=True))
            for row in rows:
                labels=row['Config'].get('Labels',{})
                if row['Name'] not in ('/c3c-'+nonce+'-worker','/c3c-'+nonce+'-broker') or labels.get('seo.c3c.job')!=nonce or labels.get('seo.c3c.managed')!='true':raise RuntimeError('Container cleanup ownership conflict')
            command(['docker','rm','-f',*ids],timeout=30);removed+=len(ids)
        volumes=command(['docker','volume','ls','-q',*filters],capture=True).split()
        if any(name!='c3c-'+nonce+'-ipc' for name in volumes):raise RuntimeError('Volume cleanup ownership conflict')
        if volumes:command(['docker','volume','rm',*volumes],timeout=30);removed+=len(volumes)
        assert not command(['docker','ps','-aq',*filters],capture=True).strip()
        assert not command(['docker','volume','ls','-q',*filters],capture=True).strip()
    for reference in sorted(OWNED_IMAGES):
        if image_exists(reference):command(['docker','image','rm',reference],timeout=30)
    if path:path.unlink(missing_ok=True)
    return dict(zero_job_owned_containers=True,zero_job_owned_volumes=True,job_owned_image_references_removed=True,forced_cleanup_was_needed=bool(removed),scope='Only recorded job nonces and previously absent image references; no global prune')


if __name__ == '__main__':
    raise SystemExit(main())
