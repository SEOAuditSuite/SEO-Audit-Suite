"""Native Windows Job enforcement gate; never substitutes mock results.

Run in an isolated Python 3.12 project. All stress runs use the real supervisor,
small fixtures, finite deadlines and owned Jobs. No websites or credentials.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import browser_supervision as bs
from validation_host import atomic_json,read_marker,HostGuard,LOW_PROFILE


def worker(mode):
    request=json.load(sys.stdin)  # Never perform stress work before Job assignment.
    marker=Path(request['marker'])
    atomic_json(marker,dict(stage='stdin_released',pid=os.getpid()))
    if mode=='processes':
        children=[]
        try:
            for _ in range(6):
                children.append(subprocess.Popen([sys.executable,'-c','import time; time.sleep(15)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
            atomic_json(marker,dict(stage='unexpected_process_creation_success',count=len(children)))
        except OSError as exc:
            atomic_json(marker,dict(stage='creation_refused',winerror=exc.winerror,count=len(children)))
        time.sleep(0.5)
    elif mode=='memory':
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.VirtualAlloc.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_ulong,ctypes.c_ulong]
        api.VirtualAlloc.restype=ctypes.c_void_p
        # Reserve+commit request exceeds the 128 MiB fixture Job; no data is touched.
        address=api.VirtualAlloc(None,160*1024*1024,0x3000,4)
        atomic_json(marker,dict(stage='commit_attempt',requested_bytes=160*1024*1024,
            allocated=bool(address),winerror=ctypes.get_last_error()))
        if address:
            api.VirtualFree.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_ulong]
            api.VirtualFree(address,0,0x8000)
        time.sleep(0.5)
    elif mode=='cpu':
        # One busy Python thread, never multiple saturating child processes.
        atomic_json(marker,dict(stage='cpu_window_started',pid=os.getpid()))
        started=time.monotonic();cpu_started=time.process_time()
        while time.monotonic()-started<2:
            pass
        atomic_json(marker,dict(stage='cpu_window_complete',pid=os.getpid(),
            wall_seconds=time.monotonic()-started,cpu_seconds=time.process_time()-cpu_started))
    print('worker-complete',flush=True)


def exercise_worker(output,name,mode,policy,guard,runs,supervisor=None):
    supervisor=supervisor or bs.run_worker
    marker=output/(name+'-marker.json')
    started=time.monotonic()
    result=supervisor([sys.executable,str(Path(__file__).resolve()),'--worker',mode],json.dumps(dict(marker=str(marker))),15,limits=policy)
    data=dict(reason=result.reason,cleanup_confirmed=result.cleanup_confirmed,diagnostics=result.diagnostics,
        elapsed_seconds=round(time.monotonic()-started,6),configured=dict(processes=policy.processes,memory_mib=policy.memory_mib,cpu_percent=policy.cpu_percent))
    data['stdout_bytes']=len(result.output.encode('utf-8'))
    data['marker_diagnostics']=read_marker(marker)
    data['marker']=data['marker_diagnostics']['value']
    # Persist supervisor reason/returncode/cleanup even if diagnostic marker is missing.
    atomic_json(output/(name+'-worker.json'),data);runs[name]=data
    print(name+': reason='+str(result.reason)+'; marker='+data['marker_diagnostics']['state']+
          '; cleanup='+str(result.cleanup_confirmed),flush=True)
    if not result.cleanup_confirmed:raise RuntimeError('NOT VERIFIED: owned Job cleanup unconfirmed; stop validation')
    guard.preflight('after '+name)
    time.sleep(1)
    return data


def run(output):
    output.mkdir(parents=True,exist_ok=True)
    checks=[];runs={};error='';status='NOT VERIFIED';guard=None
    def check(name,value):
        checks.append(dict(name=name,status='passed' if value else 'failed'))
        print(name+': '+checks[-1]['status'],flush=True)
        atomic_json(output/'progress.json',dict(checks=checks))
        if not value:raise RuntimeError('NOT VERIFIED: '+name+'; remaining native fixtures were not run')
    def exercise(name,mode,policy):
        return exercise_worker(output,name,mode,policy,guard,runs)
    def resource(data):return ((data['diagnostics'].get('cleanup') or {}).get('after') or {}).get('resources') or {}
    def cleaned(data):
        cleanup=data['diagnostics'].get('cleanup') or {};after=cleanup.get('after') or {}
        return data['cleanup_confirmed'] and after.get('membership_complete') is True and after.get('active_processes')==0 and after.get('pids')==[]
    sentinel=None
    try:
        if os.name!='nt':raise RuntimeError('Native Windows required; no enforcement checks executed.')
        if sys.version_info[:2]!=(3,12):raise RuntimeError('Python 3.12 required.')
        guard=HostGuard(output/'host-telemetry.jsonl');guard.preflight('before native fixtures')
        # Independent harmless process must survive every owned-job cleanup.
        sentinel=subprocess.Popen([getattr(sys,'_base_executable',sys.executable),'-I','-c','import time; time.sleep(300)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=bs._worker_environment())
        normal=exercise('low-resource','normal',bs.JobLimits(**LOW_PROFILE));r=resource(normal)
        check('Low-resource native limits queried and verified',r.get('verified') is True)
        check('Normal worker starts successfully under low-resource profile',normal['reason']=='' and normal['marker'] is not None)
        check('Low-resource worker Job empty after cleanup',cleaned(normal))
        count=exercise('process-limit','processes',bs.JobLimits(4,128,25));r=resource(count)
        check('Native active-process cap read back as four',r.get('verified') is True and r.get('process_limit')==4)
        check('Real creation attempt triggers active-process-limit notification',count['reason']=='resource_limit' and 'active_process_limit' in r.get('limit_events',[]))
        check('Process-limit worker tree cleanup confirmed',cleaned(count))
        memory=exercise('memory-limit','memory',bs.JobLimits(16,128,25));r=resource(memory)
        check('Native aggregate commit cap read back as 128 MiB',r.get('verified') is True and r.get('committed_memory_limit_bytes')==128*1024*1024)
        check('Real oversized commit triggers Job memory-limit notification',memory['reason']=='resource_limit' and 'job_memory_limit' in r.get('limit_events',[]))
        check('Job peak committed memory stays within cap',0<r.get('peak_job_memory_bytes',0)<=128*1024*1024)
        check('Memory-limit worker tree cleanup confirmed',cleaned(memory))
        if (os.cpu_count() or 1)>8:
            raise RuntimeError('NOT VERIFIED: low-resource CPU fixture supports at most eight logical processors; no unsafe load expansion')
        reference=exercise('cpu-reference','cpu',bs.JobLimits(16,128,10))
        limited=exercise('cpu-limited','cpu',bs.JobLimits(16,128,2))
        a,b=resource(reference),resource(limited)
        check('Native CPU reference hard cap configured at ten percent',a.get('verified') is True and a.get('cpu_rate_percent')==10)
        check('Native CPU hard cap configured at two percent',b.get('verified') is True and b.get('cpu_rate_percent')==2 and b.get('cpu_flags')==5)
        reference_window=reference.get('marker') or {};limited_window=limited.get('marker') or {}
        good=reference_window.get('stage')==limited_window.get('stage')=='cpu_window_complete'
        def window_rate(value):
            wall=value.get('wall_seconds',0);cpu=value.get('cpu_seconds',0)
            return cpu/wall if 1.9<=wall<=4 and 0<cpu<=wall*1.05 else 0
        demand=window_rate(reference_window);used=window_rate(limited_window)
        quota=(os.cpu_count() or 1)*0.02
        check('Measured CPU reference demand exceeds two-percent quota',good and demand>quota*1.5)
        check('Measured native CPU throttling in equal bounded windows',reference['reason']==limited['reason']=='' and good and demand>quota*1.5 and 0<used<demand*0.70 and used<=quota*1.5)
        check('Both CPU worker Jobs empty after cleanup',cleaned(reference) and cleaned(limited))
        check('Unrelated sentinel process remains alive',sentinel.poll() is None)
        status='passed' if all(c['status']=='passed' for c in checks) else 'failed'
    except (Exception,KeyboardInterrupt) as exc:
        error=type(exc).__name__+': '+str(exc)
        print('NOT VERIFIED: '+error,flush=True)
        (output/'native-error.log').write_text(traceback.format_exc(),encoding='utf-8')
    finally:
        sentinel_cleanup=True
        if sentinel is not None:
            try:
                sentinel.terminate()
                try:sentinel.wait(timeout=5)
                except subprocess.TimeoutExpired:sentinel.kill();sentinel.wait(timeout=5)
                sentinel_cleanup=sentinel.poll() is not None
            except (OSError,subprocess.TimeoutExpired):sentinel_cleanup=False
        if not sentinel_cleanup:
            status='NOT VERIFIED';error+=' Unrelated test sentinel cleanup could not be confirmed.'
        record=dict(status=status,error=error,executed_checks=len(checks),passed_checks=sum(c['status']=='passed' for c in checks),
            checks=checks,runs=runs,sentinel_cleanup_confirmed=sentinel_cleanup,logical_processors=os.cpu_count(),python=sys.version,validation_mode='low-resource',profile=LOW_PROFILE,
            source_sha256={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [ROOT/'browser_supervision.py',ROOT/'tests/validation_host.py',Path(__file__).resolve()]})
        atomic_json(output/'native-results.json',record)
        (output/'Native-Windows-Report.md').write_text('# C3B Native Windows Job Validation\n\nStatus: '+status+'\n\n'+error+'\n\n'
            +'Low-resource fixtures: one CPU thread, 2-second measurement windows, 15-second worker deadlines; 128 MiB fixture commit cap. Actual enforcement and owned-job cleanup only; not whole-app or physical-RAM isolation. '
            +'A failed/inconclusive CPU calibration or missing limit notification is not acceptance.\n',encoding='utf-8')
    return 0 if status=='passed' else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);parser.add_argument('--worker')
    args=parser.parse_args()
    if args.worker:worker(args.worker)
    elif args.output:sys.exit(run(args.output.resolve()))
    else:parser.error('--output is required')
