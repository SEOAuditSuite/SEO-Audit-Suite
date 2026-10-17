"""Serial bounded native fixtures on a disposable approved Linux Docker host.

No execution unless --execute is supplied. This runner does not certify network,
identity, Chromium compatibility or whole-host isolation.
"""
import argparse
import json
from pathlib import Path
import shutil
import time
import uuid

from deployment.c3c.supervisor import Runtime,image_id,LABEL


def counters(raw):
    return {k:int(v) for k,v in (line.split() for line in raw.splitlines())}


def judge(mode,state,logs):
    rows=[json.loads(line) for line in logs.splitlines() if line.startswith('{')]
    if not rows or rows[0].get('stage')!='started':return False
    if mode=='memory':return state.get('OOMKilled') is True and state.get('ExitCode')==137
    if state.get('ExitCode')!=0:return False
    last=rows[-1]
    if mode=='processes':return last.get('stage')=='pid_creation_refused' and counters(last['events']).get('max',0)>0
    if mode=='storage':return last.get('stage')=='storage_refused'
    if mode=='cpu':
        if last.get('stage')!='cpu_measurement':return False
        a,b=counters(last['before']),counters(last['after'])
        return (1.9<=last['wall']<=5 and 0<last['cpu']/last['wall']<=.30
                and b.get('nr_throttled',0)>a.get('nr_throttled',0)
                and b.get('throttled_usec',0)>a.get('throttled_usec',0))
    return False


def run(image,output):
    image_id(image);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    results=[]
    for mode in ('processes','memory','cpu','storage'):
        nonce=uuid.uuid4().hex;name='c3c-'+nonce+'-worker';runtime=Runtime(15)
        record=dict(mode=mode,status='NOT VERIFIED',cleanup_confirmed=False)
        created=False
        try:
            args=['create','--name',name,'--label',LABEL+'='+nonce,
                  '--label','seo.c3c.managed=true','--label','seo.c3c.expires='+str(int(time.time()+15)),
                  '--network','none','--user','10001:10001','--read-only','--cap-drop','ALL',
                  '--security-opt','no-new-privileges=true','--memory','64m','--memory-swap','64m',
                  '--pids-limit','8','--cpus','0.20','--log-driver','local',
                  '--log-opt','max-size=1m','--log-opt','max-file=1','--log-opt','compress=false',
                  '--tmpfs','/tmp:rw,nosuid,nodev,size=8m,mode=1777',
                  '--entrypoint','python',image,'-m','deployment.c3c.native_limits',
                  '--inside-capped-test-job','--mode',mode]
            runtime.call(args);created=True
            runtime.call(['start',name])
            while True:
                info=json.loads(runtime.call(['inspect',name]))[0]
                if info['State']['Running'] is False:break
                time.sleep(.1)
            logs=runtime.call(['logs',name]).decode('utf-8',errors='replace')
            record.update(state=info['State'],host_config=info['HostConfig'],logs=logs,
                          status='PASS' if judge(mode,info['State'],logs) else 'FAIL')
        except Exception as exc:record['error_type']=type(exc).__name__
        finally:
            try:
                if created:runtime.call(['rm','--force',name],cleanup=True)
                left=runtime.call(['ps','--all','--quiet','--filter','label='+LABEL+'='+nonce],cleanup=True)
                record['cleanup_confirmed']=not left.strip()
            except Exception:pass
            if not record['cleanup_confirmed']:record['status']='NOT VERIFIED'
            (output/(mode+'.json')).write_text(json.dumps(record,indent=2),encoding='utf-8')
            results.append(record)
        if record['status']!='PASS':break
        time.sleep(2)
    summary=dict(status='NOT VERIFIED',resource_fixtures=results,
                 note='Native resources only. Network, authentication, real Chromium and watchdog acceptance remain separate.')
    (output/'Summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true')
    parser.add_argument('--worker-image');parser.add_argument('--output',type=Path);args=parser.parse_args()
    if not args.execute:raise SystemExit('NOT VERIFIED: no native fixtures executed. Review ACCEPTANCE.md first.')
    if not shutil.which('docker'):raise SystemExit('NOT VERIFIED: Docker unavailable; no native fixtures executed')
    if not args.worker_image or not args.output:parser.error('--worker-image and --output required')
    print(json.dumps(run(args.worker_image,args.output)))
