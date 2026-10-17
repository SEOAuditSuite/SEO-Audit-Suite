"""Scoped disposable-job policy lifecycle and browser-worker-only attachment."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from validation.c3c.sandbox_policy import policy
from validation.c3c.sandbox_probe import sanitize

AA=Path('/sys/kernel/security/apparmor')
REPO=Path(__file__).resolve().parents[2]
PROPOSAL_HASH='889e6ebecddd34139a02f9c835bdd328881b6a8c30e2dbaaf91d1ab48b1eb33b'


class Blocked(RuntimeError):pass


def verify_package():
    source=policy.ROOT/'proposal-manifest.json'
    if hashlib.sha256(source.read_bytes()).hexdigest()!=PROPOSAL_HASH:raise Blocked('Proposal manifest identity conflict')
    manifest=json.loads(source.read_text())
    for name,digest in manifest['sha256'].items():
        path=REPO/name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise Blocked('Proposal checksum conflict: '+name)
    policy.validate()
    return {name:hashlib.sha256((policy.ROOT/name).read_bytes()).hexdigest()
            for name in ('chromium-amd64.seccomp.json','chromium.apparmor')}


def read(path,limit=65536):
    with Path(path).open('rb') as stream:data=stream.read(limit+1)
    if len(data)>limit:raise Blocked('Host evidence exceeds bound')
    return data.decode().strip()


def command(args,limit=65536,timeout=15):
    """Bound retained output and logs; fixed argument lists, never a shell."""
    with tempfile.TemporaryFile() as out,tempfile.TemporaryFile() as err:
        result=subprocess.run(args,stdout=out,stderr=err,timeout=timeout,check=False)
        out.seek(0);data=out.read(limit+1);err.seek(0);error=err.read(2049)
    if result.returncode or len(data)>limit:
        raise Blocked('Read-only command failed: '+Path(args[0]).name+' exit='+str(result.returncode)+' '+sanitize(error.decode(errors='replace'),1024))
    return data


def loaded_profile(name,aa=AA):
    """Linux securityfs raw_sha256 hashes the entire exported load binary."""
    directory=aa/'policy/profiles'
    entries=list(directory.iterdir())
    if len(entries)>2048:raise Blocked('Profile inventory exceeds bound')
    matches=[]
    for item in entries:
        if item.is_dir() and read(item/'name',512)==name:matches.append(item)
    if len(matches)!=1:raise Blocked('Exact named profile unavailable or ambiguous: '+name)
    entry=matches[0]
    if read(entry/'mode',64)!='enforce':raise Blocked('Required profile is not enforcing: '+name)
    digest=read(entry/'raw_sha256',128)
    if not re.fullmatch('[a-f0-9]{64}',digest):raise Blocked('Kernel raw policy SHA256 unavailable')
    return digest


def compile_host_profile(parser,binary_path=None):
    version=command([parser,'--config-file','/dev/null','--version']).decode(errors='replace')
    if not re.search(r'version\s+([4-9]|[1-9][0-9]+)\.',version):raise Blocked('AppArmor 4 parser required')
    if not Path('/etc/apparmor.d/abi/4.0').is_file():raise Blocked('Host AppArmor ABI 4 import unavailable')
    # Actual host features/imports only. Never substitute offline package features.
    options=[parser,'--config-file','/dev/null','--skip-kernel-load','--skip-cache','--Werror','--jobs','1','--max-jobs','1']
    expanded=command([*options,'--preprocess',str(policy.ROOT/'chromium.apparmor')],limit=2*1024*1024)
    binary=command([*options,'--stdout',str(policy.ROOT/'chromium.apparmor')],limit=4*1024*1024)
    if not binary:raise Blocked('Empty AppArmor binary')
    if binary_path is not None:
        fd=os.open(binary_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(binary)
    return dict(binary_sha256=hashlib.sha256(binary).hexdigest(),expanded_sha256=hashlib.sha256(expanded).hexdigest())


def require_docker(data,endpoint):
    if endpoint!='unix:///var/run/docker.sock':raise Blocked('Local default Docker daemon required')
    if data.get('ServerVersion')!='28.0.4':raise Blocked('Reviewed Docker 28.0.4 required')
    if data.get('OSType')!='linux' or data.get('CgroupVersion')!='2' or data.get('Architecture') not in ('x86_64','amd64'):raise Blocked('Linux amd64 cgroup v2 required')
    options=data.get('SecurityOptions',[])
    if 'name=apparmor' not in options or 'name=seccomp,profile=builtin' not in options:raise Blocked('Global Docker defaults differ from reviewed baseline')
    if any('rootless' in x or 'userns' in x for x in options):raise Blocked('Unreviewed daemon namespace mapping')


def readonly_preflight():
    if os.geteuid()!=0 and os.environ.get('C3C_POLICY_JOB'):
        return privileged_receipt()
    checks={};evidence={}
    def check(name,fn):
        try:evidence[name]=fn();checks[name]='PASS'
        except (OSError,ValueError,Blocked,subprocess.SubprocessError) as exc:
            checks[name]='NOT VERIFIED';evidence[name]=sanitize(type(exc).__name__+': '+str(exc),1024)
    check('package_identity',verify_package)
    def docker():
        if any(os.environ.get(x) for x in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS_VERIFY')):raise Blocked('Docker environment override is not reviewed')
        data=json.loads(command(['docker','info','--format','{{json .}}']))
        endpoint=json.loads(command(['docker','context','inspect','--format','{{json .Endpoints.docker.Host}}']))
        require_docker(data,endpoint)
        return dict(version=data['ServerVersion'],architecture=data['Architecture'],endpoint=endpoint)
    check('docker_local_defaults',docker)
    def cgroups():
        value=set(read('/sys/fs/cgroup/cgroup.controllers',1024).split())
        if not {'cpu','memory','pids'}<=value:raise Blocked('Required cgroup v2 controllers unavailable')
        return sorted(value)
    check('cgroup_controllers',cgroups)
    def features():
        if read('/sys/module/apparmor/parameters/enabled',32)!='Y':raise Blocked('AppArmor disabled')
        if 'userns_create' not in read(AA/'features/namespaces/mask',512).split():raise Blocked('AppArmor user namespace mediation unavailable')
        return 'Kernel advertises userns_create mediation; ABI 4 compilation is a separate gate'
    check('apparmor_features',features)
    def namespaces():
        maximum=int(read('/proc/sys/user/max_user_namespaces',128))
        clone=read('/proc/sys/kernel/unprivileged_userns_clone',32)
        restrict=read('/proc/sys/kernel/apparmor_restrict_unprivileged_userns',32)
        if maximum<=0 or clone!='1' or restrict!='1':raise Blocked('Required namespace configuration/restriction differs')
        return dict(maximum=maximum,unprivileged_clone=clone,apparmor_restriction=restrict)
    check('namespace_restrictions',namespaces)
    def identity():
        parser=shutil.which('apparmor_parser')
        if not parser:raise Blocked('System AppArmor parser unavailable')
        st=Path(parser).stat()
        if st.st_uid!=0 or st.st_mode&0o022:raise Blocked('Untrusted host parser permissions')
        compiled=compile_host_profile(parser)
        if loaded_profile(policy.PROFILE)!=compiled['binary_sha256']:raise Blocked('Loaded profile binary does not match candidate with current host imports/features')
        return compiled
    check('named_enforcing_profile_identity',identity)
    check('docker_default_profile_identity',lambda:loaded_profile('docker-default'))
    return dict(status='PASS' if all(v=='PASS' for v in checks.values()) else 'NOT VERIFIED',
                checks=checks,evidence=evidence,scope='Read-only capability/identity checks; native attachment and enforcement remain separate')


def require_ready(result):
    expected={'package_identity','docker_local_defaults','cgroup_controllers','apparmor_features','namespace_restrictions','named_enforcing_profile_identity','docker_default_profile_identity'}
    if result.get('status')!='PASS' or set(result.get('checks',{}))!=expected or any(v!='PASS' for v in result['checks'].values()):raise Blocked('Sandbox host preflight incomplete; refusing browser creation')
    verify_package()
    identity=result['evidence']['named_enforcing_profile_identity']['binary_sha256']
    if os.geteuid()!=0 and os.environ.get('C3C_POLICY_JOB'):
        current=privileged_receipt()
        if current!=result:raise Blocked('Root-owned policy receipt changed since preflight')
        return identity
    if loaded_profile(policy.PROFILE)!=identity:raise Blocked('Named profile changed since preflight')
    if loaded_profile('docker-default')!=result['evidence']['docker_default_profile_identity']:raise Blocked('Docker global profile changed since preflight')
    return identity


def attach_worker(args,result):
    require_ready(result)
    args=list(args)
    if len(args)<6 or args[0]!='create' or args[-1]!='/app/validation/c3c/sandbox_probe.py' or not re.fullmatch('sha256:[a-f0-9]{64}',args[-2]):raise Blocked('Immutable browser image and original probe required')
    pairs={};switches=[];index=1
    while index<len(args)-2:
        flag=args[index]
        if flag=='--read-only':switches.append(flag);index+=1;continue
        if not flag.startswith('--') or index+1>=len(args)-2:raise Blocked('Unexpected worker argument')
        pairs.setdefault(flag,[]).append(args[index+1]);index+=2
    names=pairs.get('--name',[])
    if len(names)!=1 or not re.fullmatch(r'c3c-[a-f0-9]{32}-worker',names[0]):raise Blocked('Only a synthetic browser worker may receive policies')
    nonce=names[0][4:-7]
    expected={'--name':names,'--user':['10001:10001'],'--network':['none'],'--ipc':['private'],
        '--memory':['1536m'],'--memory-swap':['1536m'],'--cpus':['1.0'],'--pids-limit':['64'],'--cap-drop':['ALL'],
        '--security-opt':['no-new-privileges=true'],'--ulimit':['nofile=256:256','core=0:0'],
        '--tmpfs':['/tmp:rw,nosuid,nodev,size=256m,mode=1777'],'--log-driver':['local'],
        '--log-opt':['max-size=10m','max-file=1','compress=false'],
        '--env':['HOME=/tmp','PYTHONDONTWRITEBYTECODE=1'],'--entrypoint':['python'],
        '--label':pairs.get('--label',[])}
    labels=expected['--label']
    if len(labels)!=3 or labels[:2]!=['seo.c3c.managed=true','seo.c3c.job='+nonce] or not re.fullmatch(r'seo.c3c.expires=[0-9]{10,}',labels[2]):raise Blocked('Worker ownership labels differ')
    if pairs!=expected or switches!=['--read-only']:raise Blocked('Worker bounds/options differ from the exact reviewed configuration')
    index=args.index('--entrypoint')
    return args[:index]+['--security-opt','seccomp='+str(policy.ROOT/'chromium-amd64.seccomp.json'),
        '--security-opt','apparmor='+policy.PROFILE]+args[index:]


def verify_container(details,result):
    require_ready(result)
    h=details['HostConfig'];config=details['Config']
    if config.get('Entrypoint')!=['python'] or config.get('Cmd')!=['/app/validation/c3c/sandbox_probe.py'] or config.get('Image')!=details.get('Image') or not re.fullmatch('sha256:[a-f0-9]{64}',str(details.get('Image'))):raise Blocked('Worker image/entrypoint identity differs')
    expected={'Memory':1536*1024*1024,'MemorySwap':1536*1024*1024,'NanoCpus':1000000000,'PidsLimit':64,
              'NetworkMode':'none','IpcMode':'private','CgroupnsMode':'private','UsernsMode':'','ReadonlyRootfs':True,'Privileged':False,'PidMode':''}
    if any(h.get(k)!=v for k,v in expected.items()) or config.get('User')!='10001:10001':raise Blocked('Effective worker configuration differs')
    if h.get('CapAdd') or h.get('CapDrop')!=['ALL'] or h.get('Binds') or h.get('Devices') or h.get('VolumesFrom'):raise Blocked('Unexpected privilege/device/mount attachment')
    if h.get('Tmpfs')!={'/tmp':'rw,nosuid,nodev,size=256m,mode=1777'}:raise Blocked('Worker temporary storage differs')
    if h.get('LogConfig')!={'Type':'local','Config':{'max-size':'10m','max-file':'1','compress':'false'}}:raise Blocked('Worker logs differ')
    limits={x['Name']:(x['Soft'],x['Hard']) for x in h.get('Ulimits',[])}
    if limits!={'nofile':(256,256),'core':(0,0)}:raise Blocked('Worker ulimits differ')
    if any(m.get('Type')!='tmpfs' or m.get('Destination')!='/tmp' for m in details.get('Mounts',[])):raise Blocked('Unexpected mount')
    opts=h.get('SecurityOpt',[])
    if len(opts)!=3 or 'no-new-privileges=true' not in opts or 'apparmor='+policy.PROFILE not in opts:raise Blocked('Effective security options differ')
    sec=[x[len('seccomp='):] for x in opts if x.startswith('seccomp=')]
    if len(sec)!=1:raise Blocked('Explicit effective seccomp JSON missing')
    try:actual=json.loads(sec[0])
    except ValueError:raise Blocked('Docker inspect must expose loaded seccomp JSON, not merely a path') from None
    if actual!=policy.build() or details.get('AppArmorProfile')!=policy.PROFILE:raise Blocked('Effective policy identity mismatch')
    return dict(status='PASS',profile=policy.PROFILE,seccomp_sha256=verify_package()['chromium-amd64.seccomp.json'],scope='Docker configuration identity; in-container negative tests are separate')


def require_host_preflight():
    result=readonly_preflight()
    print('C3C_SANDBOX_HOST '+json.dumps(result),flush=True)
    if result['status']!='PASS':raise Blocked('Required sandbox host capabilities/identity are NOT VERIFIED')
    return result


def verify_defaults(result):
    if os.geteuid()!=0 and os.environ.get('C3C_POLICY_JOB'):
        require_ready(result)
        return dict(status='PASS',scope='Root-owned receipt and pre-existing profile hashes verified')
    if loaded_profile('docker-default')!=result['evidence']['docker_default_profile_identity']:raise Blocked('Global Docker AppArmor policy changed')
    return dict(status='PASS',scope='Read-only Docker default profile hash comparison; operator-owned named profile left untouched')


def trusted_parser():
    parser=Path('/usr/sbin/apparmor_parser')
    st=parser.stat()
    if st.st_uid!=0 or st.st_mode&0o022:raise Blocked('Untrusted system parser')
    return str(parser)


def inventory():
    """Retain identities privately; never print unrelated profile names."""
    result={}
    for index,p in enumerate((AA/'policy/profiles').iterdir()):
        if index>=2048:raise Blocked('Profile inventory exceeds bound')
        if not p.is_dir():continue
        name=read(p/'name',512)
        if name in result:raise Blocked('Ambiguous profile inventory')
        result[name]=dict(mode=read(p/'mode',64),sha256=read(p/'raw_sha256',128))
        if not re.fullmatch('[a-f0-9]{64}',result[name]['sha256']):raise Blocked('Required binary hash export missing')
    return result


def preserve_profiles(before):
    current=inventory()
    if any(current.get(name)!=record for name,record in before.items()):
        raise Blocked('Pre-existing host policy changed; never repair global policy')


def state_directory(job):
    if not re.fullmatch(r'[1-9][0-9]{0,19}-1',job):raise Blocked('Exact first-attempt job identity required')
    return Path('/run')/('c3c-sandbox-'+job)


def read_state(job):
    directory=state_directory(job);st=directory.lstat()
    if directory.is_symlink() or st.st_uid!=0 or st.st_mode&0o077:raise Blocked('Unsafe ownership receipt directory')
    path=directory/'receipt.json';st=path.lstat()
    if path.is_symlink() or st.st_uid!=0 or st.st_mode&0o077:raise Blocked('Unsafe ownership receipt')
    state=json.loads(read(path,1024*1024))
    if state['job']!=job or state['profile']!=policy.PROFILE:raise Blocked('Policy receipt scope conflict')
    return directory,state


def write_state(directory,state):
    # The directory is exclusive, root-owned and mode 0700; unprivileged code cannot change it.
    path=directory/'receipt.json'
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(state,stream,sort_keys=True)


def prepare_job(job):
    if os.geteuid()!=0:raise Blocked('Host policy administration requires scoped sudo')
    if sys.version_info[:2]!=(3,12) or platform.machine()!='x86_64':raise Blocked('Reviewed system Python and amd64 required')
    verify_package();parser=trusted_parser();before=inventory()
    if policy.PROFILE in before:raise Blocked('Profile collision: never adopt, replace or remove pre-existing policy')
    if 'docker-default' not in before or before['docker-default']['mode']!='enforce':raise Blocked('Enforcing Docker default must already exist')
    # Structural checks happen before the only policy write. Missing named profile is expected here.
    preflight=readonly_preflight()
    required=set(preflight['checks'])-{'named_enforcing_profile_identity'}
    if any(preflight['checks'][name]!='PASS' for name in required):raise Blocked('Structural host preflight incomplete')
    fields=dict(line.split(':',1) for line in read('/proc/self/status').splitlines() if ':' in line)
    if not int(fields['CapEff'].strip(),16)&(1<<33) or not os.access(AA/'.load',os.W_OK):raise Blocked('Policy administration metadata unavailable')
    directory=state_directory(job);directory.mkdir(mode=0o700,exist_ok=False)
    compiled=compile_host_profile(parser,directory/'profile.bin')
    state=dict(job=job,profile=policy.PROFILE,before=before,compiled=compiled,phase='reserved',owned=False)
    write_state(directory,state)
    # --add is deliberately used, never --replace. Binary removal later uses this same private file.
    command([parser,'--config-file','/dev/null','--skip-cache','--add','--binary',str(directory/'profile.bin')])
    state.update(owned=True,phase='loaded');write_state(directory,state)
    return verify_job(job)


def verify_job(job):
    directory,state=read_state(job)
    if state.get('phase')!='loaded' or state.get('owned') is not True:raise Blocked('No successful job-owned policy load receipt')
    if hashlib.sha256((directory/'profile.bin').read_bytes()).hexdigest()!=state['compiled']['binary_sha256']:raise Blocked('Private load binary changed')
    if loaded_profile(policy.PROFILE)!=state['compiled']['binary_sha256']:raise Blocked('Loaded enforcing policy identity conflict')
    preserve_profiles(state['before'])
    result=readonly_preflight()
    require_ready(result)
    if result['evidence']['named_enforcing_profile_identity']!=state['compiled']:raise Blocked('Host imports/features changed since load')
    return result


def cleanup_job(job):
    directory=state_directory(job)
    if not directory.exists():return dict(status='PASS',scope='No job policy receipt exists; nothing removed')
    directory,state=read_state(job)
    current=inventory()
    if state.get('owned') is True:
        if state.get('phase')!='loaded' or current.get(policy.PROFILE)!={'mode':'enforce','sha256':state['compiled']['binary_sha256']}:raise Blocked('Cleanup policy ownership/identity conflict; no removal')
        binary=directory/'profile.bin'
        if binary.is_symlink() or hashlib.sha256(binary.read_bytes()).hexdigest()!=state['compiled']['binary_sha256']:raise Blocked('Cleanup binary conflict')
        # Refuse profile removal while any live container (owned or foreign) uses it.
        ids=command(['docker','ps','-aq'],limit=65536).decode().split()
        if ids:
            containers=json.loads(command(['docker','inspect',*ids],limit=4*1024*1024))
            if any(c.get('AppArmorProfile')==policy.PROFILE for c in containers):raise Blocked('Attached containers remain; no policy removal')
        command([trusted_parser(),'--config-file','/dev/null','--skip-cache','--remove','--binary',str(binary)])
        if policy.PROFILE in inventory():raise Blocked('Owned policy survives removal')
    elif policy.PROFILE in current:
        raise Blocked('Uncertain load ownership; never remove an unreceipted policy')
    preserve_profiles(state['before'])
    # Only our two known files and exclusive directory; never recurse over host paths.
    (directory/'profile.bin').unlink(missing_ok=True)
    (directory/'receipt.json').unlink();directory.rmdir()
    return dict(status='PASS',owned_profile_removed=state.get('owned') is True,preexisting_profiles_preserved=True)


def privileged_receipt():
    job=os.environ['C3C_POLICY_JOB'];state_directory(job)
    raw=command(['sudo','-n','--','/usr/bin/python3','-I',str(Path(__file__).resolve()),'--verify-job',job],limit=16384,timeout=30)
    return json.loads(raw)


def main():
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group()
    for operation in ('prepare','verify','cleanup'):group.add_argument('--'+operation+'-job')
    args=parser.parse_args()
    try:
        selected=next(((name,getattr(args,name+'_job')) for name in ('prepare','verify','cleanup') if getattr(args,name+'_job')),None)
        if selected:
            if os.geteuid()!=0:raise Blocked('Policy lifecycle command requires scoped host administration')
            result={'prepare':prepare_job,'verify':verify_job,'cleanup':cleanup_job}[selected[0]](selected[1])
        else:result=readonly_preflight()
        print(json.dumps(result,sort_keys=True));return 0 if result.get('status')=='PASS' else 2
    except (OSError,ValueError,KeyError,Blocked,subprocess.SubprocessError) as exc:
        print(json.dumps(dict(status='NOT VERIFIED',error=sanitize(str(exc),1024))));return 2


if __name__=='__main__':raise SystemExit(main())
