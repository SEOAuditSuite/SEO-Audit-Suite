"""External, single-operation Docker supervisor for trusted controller invocation.

Never mount the runtime socket in a job or expose this CLI as a network service.
Deploy under a dedicated OS account and external systemd watchdog/reaper.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
try:
    import fcntl
    import resource
except ImportError:  # Importable for Windows policy checks; runtime is Linux-only.
    fcntl=resource=None
import subprocess
import tempfile
import time

from deployment.c3c.policy import Limits,authorize

LABEL='seo.c3c.job'


def image_id(value):
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',value):
        raise ValueError('Locally inspected immutable image ID required')
    return value


def options(name,nonce,image,limits,broker=False):
    memory=limits.broker_memory_mib if broker else limits.memory_mib
    # Sum of both sibling ceilings is the whole-operation upper bound.
    cpu=.25 if broker else limits.cpu
    pids=16 if broker else limits.pids
    out=['create','--name',name,'--label',LABEL+'='+nonce,'--label','seo.c3c.managed=true',
         '--label','seo.c3c.expires='+str(int(time.time()+limits.seconds)),
         '--user','10001:10001','--read-only','--cap-drop','ALL',
         '--security-opt','no-new-privileges=true','--memory',str(memory)+'m',
         '--memory-swap',str(memory)+'m','--cpus',str(cpu),'--pids-limit',str(pids),
         '--ulimit','nofile=256:256','--ulimit','core=0:0','--ipc','private',
         '--log-driver','local','--log-opt','max-size=10m','--log-opt','max-file=1','--log-opt','compress=false',
         '--tmpfs','/tmp:rw,nosuid,nodev,size='+str(limits.temporary_mib if not broker else 16)+'m,mode=1777',
         '--network','seo-c3c-broker' if broker else 'none',
         '--mount','type=volume,src=c3c-'+nonce+'-ipc,dst=/run/seo-broker'+('' if broker else ',readonly'),
         '--env','HOME=/tmp','--env','PYTHONDONTWRITEBYTECODE=1']
    if not broker:out+=['--interactive']
    return out+[image_id(image)]


class Runtime:
    def __init__(self,seconds):self.deadline=time.monotonic()+seconds
    def call(self,args,*,data=None,cleanup=False):
        remaining=10 if cleanup else min(15,self.deadline-time.monotonic())
        if remaining<=0:raise TimeoutError('Whole-operation deadline reached')
        result=subprocess.run(['docker',*args],input=data,capture_output=True,
                              timeout=remaining,env={k:v for k,v in os.environ.items() if k in ('PATH','HOME')})
        if len(result.stdout)>1024*1024:raise RuntimeError('Unexpected runtime response size')
        if result.returncode:raise RuntimeError('Runtime command failed')
        return result.stdout


def verify_container(info,limits,broker=False):
    h=info['HostConfig'];c=info['Config'];mem=(limits.broker_memory_mib if broker else limits.memory_mib)*1024*1024
    required=(h.get('Memory')==mem and h.get('MemorySwap')==mem
              and h.get('PidsLimit')==(16 if broker else limits.pids)
              and h.get('NanoCpus')==int((.25 if broker else limits.cpu)*1e9)
              and h.get('ReadonlyRootfs') is True and c.get('User')=='10001:10001'
              and 'ALL' in [s.upper() for s in h.get('CapDrop',[])]
              and 'no-new-privileges=true' in h.get('SecurityOpt',[])
              and h.get('NetworkMode')==('seo-c3c-broker' if broker else 'none')
              and h.get('Privileged') is False and h.get('PidMode','')==''
              and h.get('IpcMode')=='private')
    if not required:raise RuntimeError('Container control readback mismatch')


def execute(job,worker_image,broker_image,state,limits=None,runtime=None):
    if fcntl is None or resource is None:raise RuntimeError('Linux containment runtime required')
    limits=limits or Limits();state=Path(state)
    if not re.fullmatch('[a-f0-9]{32}',job.get('nonce','')):raise ValueError('Invalid owned nonce')
    if not state.is_dir() or state.is_symlink() or state.stat().st_mode & 0o077:
        raise ValueError('Private existing state directory (0700) required')
    runtime=runtime or Runtime(limits.seconds)
    nonce=job['nonce'];names=['c3c-'+nonce+'-broker','c3c-'+nonce+'-worker']
    # O_EXCL also prevents authenticated replay after process restart.
    with (state/'active.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (state/'ADMISSION-BLOCKED').exists():
            raise RuntimeError('Admission blocked: independent cleanup review required')
        with (state/(nonce+'.used')).open('x'):pass
        record=dict(status='NOT VERIFIED',cleanup_confirmed=False,http_status=None,files={},owner=job.get('owner'))
        created=[];volume=False
        try:
            image_id(worker_image);image_id(broker_image)
            host=json.loads(runtime.call(['info','--format','{{json .}}']))
            if host.get('OSType')!='linux' or host.get('CgroupVersion')!='2':
                raise RuntimeError('Linux with cgroup v2 is required')
            if not any('seccomp' in value for value in host.get('SecurityOptions',[])):
                raise RuntimeError('Host seccomp support required')
            # Operator must supply independently tested firewall evidence. A
            # label alone is not proof; this guard prevents accidental default use.
            net=json.loads(runtime.call(['network','inspect','seo-c3c-broker']))[0]
            if net.get('Labels',{}).get('seo.c3c.egress')!='independently-tested':
                raise RuntimeError('Independently tested broker egress network required')
            runtime.call(['volume','create','--driver','local','--opt','type=tmpfs',
                          '--opt','device=tmpfs','--opt','o=size=1m,uid=10001,gid=10001,mode=0700',
                          '--label',LABEL+'='+nonce,'c3c-'+nonce+'-ipc']);volume=True
            for name,image,is_broker in [(names[0],broker_image,True),(names[1],worker_image,False)]:
                runtime.call(options(name,nonce,image,limits,is_broker));created.append(name)
                info=json.loads(runtime.call(['inspect',name]))[0]
                verify_container(info,limits,is_broker)
            runtime.call(['start',names[0]])
            for _ in range(30):
                try:
                    runtime.call(['exec',names[0],'test','-S','/run/seo-broker/broker.sock']);break
                except RuntimeError:time.sleep(.1)
            else:raise RuntimeError('Broker startup unavailable')
            # Attach stdout to a file: untrusted output must not accumulate in
            # supervisor RAM. Runtime log storage and job output are bounded too.
            # State must live on an independently quota-limited filesystem.
            with tempfile.TemporaryFile(dir=state) as output,tempfile.TemporaryFile(dir=state) as errors:
                def cap_output_files():
                    resource.setrlimit(resource.RLIMIT_FSIZE,(limits.output_bytes,limits.output_bytes))
                process=subprocess.Popen(['docker','start','--attach','--interactive',names[1]],
                    stdin=subprocess.PIPE,stdout=output,stderr=errors,
                    preexec_fn=cap_output_files,
                    env={k:v for k,v in os.environ.items() if k in ('PATH','HOME')})
                try:
                    process.stdin.write(json.dumps(dict(url=job['url'],pages=job['pages'])).encode())
                    process.stdin.close()
                    while process.poll() is None:
                        if time.monotonic()>=runtime.deadline:raise TimeoutError('Whole-operation deadline reached')
                        if output.tell()>limits.output_bytes or errors.tell()>limits.output_bytes:
                            raise RuntimeError('Operation output limit exceeded')
                        time.sleep(.1)
                    if process.returncode:raise RuntimeError('Worker terminated unsuccessfully')
                    output.seek(0);raw=output.read(limits.output_bytes+1)
                    if len(raw)>limits.output_bytes:raise RuntimeError('Operation output limit exceeded')
                    result=json.loads(raw)
                    if result.get('status') not in ('completed','incomplete') or not isinstance(result.get('files'),dict):
                        raise RuntimeError('Invalid audit outcome')
                    for name,value in result['files'].items():
                        if not re.fullmatch(r'[a-z0-9-]+\.(html|json|csv|md|pdf)',name):raise RuntimeError('Invalid artifact name')
                        base64.b64decode(value,validate=True)
                    record.update({k:v for k,v in result.items() if k in ('status','files','coverage','reason','http_status')})
                finally:
                    if process.poll() is None:process.kill()
                    process.wait(timeout=5)
        except (Exception,KeyboardInterrupt) as exc:
            record.update(status='incomplete',reason=type(exc).__name__,files={},http_status=None)
        finally:
            cleanup=True
            for name in reversed(created):
                try:runtime.call(['rm','--force',name],cleanup=True)
                except Exception:cleanup=False
            try:
                survivors=runtime.call(['ps','--all','--quiet','--filter','label='+LABEL+'='+nonce],cleanup=True)
                cleanup=cleanup and not survivors.strip()
            except Exception:cleanup=False
            if volume:
                try:runtime.call(['volume','rm','c3c-'+nonce+'-ipc'],cleanup=True)
                except Exception:cleanup=False
            record['cleanup_confirmed']=cleanup
            if not cleanup:
                record.update(status='NOT VERIFIED',reason='Owned operation cleanup unconfirmed',files={})
                (state/'ADMISSION-BLOCKED').write_text('Independent cleanup review required for '+nonce,encoding='utf-8')
            (state/(nonce+'-result.json')).write_text(json.dumps(record),encoding='utf-8')
        return record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('request','key','principal','worker-image','broker-image','state'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    raw=Path(args.request).read_bytes()
    if len(raw)>16384:raise SystemExit('Oversized signed request')
    keypath=Path(args.key)
    if keypath.is_symlink() or keypath.stat().st_mode & 0o077:raise SystemExit('Private signing key required')
    job=authorize(json.loads(raw),keypath.read_bytes(),args.principal)
    result=execute(job,args.worker_image,args.broker_image,args.state)
    print(json.dumps(dict(status=result['status'],cleanup_confirmed=result['cleanup_confirmed'])))
    raise SystemExit(0 if result['status']=='completed' and result['cleanup_confirmed'] else 1)


if __name__=='__main__':main()
