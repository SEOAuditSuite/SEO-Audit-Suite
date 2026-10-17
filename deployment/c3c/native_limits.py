"""Small genuine enforcement fixtures; ONLY run in explicitly capped test containers.

An OOM kill is external evidence, not an in-process PASS. The independent runner
must record exit state, cgroup events and cleanup. Never run on an uncapped host.
"""
import argparse
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import time

CGROUP=Path('/sys/fs/cgroup')


def preflight():
    if os.getuid()==0 or not Path('/.dockerenv').exists():
        raise RuntimeError('Non-root isolated fixture container required')
    memory=(CGROUP/'memory.max').read_text().strip()
    pids=(CGROUP/'pids.max').read_text().strip()
    quota,period=(CGROUP/'cpu.max').read_text().split()
    swap=(CGROUP/'memory.swap.max').read_text().strip()
    if memory=='max' or not 32*1024*1024<=int(memory)<=128*1024*1024:
        raise RuntimeError('Fixture memory ceiling must be 32-128 MiB')
    if pids=='max' or not 4<=int(pids)<=8 or quota=='max' or int(quota)/int(period)>.25 or swap!='0':
        raise RuntimeError('Fixture PID/CPU/swap limits missing or too large')
    return dict(memory=int(memory),pids=int(pids),quota=int(quota)/int(period))


def run(mode):
    policy=preflight()
    print(json.dumps(dict(stage='started',mode=mode,limits=policy)),flush=True)
    if mode=='memory':
        # Touch committed pages until the small real cgroup ceiling intervenes.
        blocks=[]
        for _ in range(policy['memory']//(4*1024*1024)+2):
            blocks.append(bytearray(4*1024*1024))
        raise RuntimeError('Memory ceiling did not intervene')
    if mode=='processes':
        children=[];refused=False
        try:
            for _ in range(12):
                try:children.append(subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(5)']))
                except OSError as exc:
                    refused=exc.errno==errno.EAGAIN;break
        finally:
            for child in children:
                child.kill();child.wait(timeout=2)
        if not refused:raise RuntimeError('PID ceiling was not observed')
        print(json.dumps(dict(stage='pid_creation_refused',children=len(children),
                              events=(CGROUP/'pids.events').read_text())),flush=True)
    if mode=='cpu':
        started=time.monotonic();cpu=time.process_time()
        before=(CGROUP/'cpu.stat').read_text()
        while time.monotonic()-started<2:pass
        after=(CGROUP/'cpu.stat').read_text()
        print(json.dumps(dict(stage='cpu_measurement',wall=time.monotonic()-started,
                              cpu=time.process_time()-cpu,before=before,after=after)),flush=True)
    if mode=='storage':
        available=os.statvfs('/tmp')
        if available.f_blocks*available.f_frsize>16*1024*1024:
            raise RuntimeError('Fixture tmpfs must be at most 16 MiB')
        refused=False
        try:
            with open('/tmp/bounded-fixture','wb',buffering=0) as stream:
                for _ in range(18):stream.write(b'x'*1024*1024)
        except OSError as exc:refused=exc.errno==errno.ENOSPC
        finally:Path('/tmp/bounded-fixture').unlink(missing_ok=True)
        if not refused:raise RuntimeError('Storage ceiling was not observed')
        print(json.dumps(dict(stage='storage_refused')),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--inside-capped-test-job',action='store_true')
    parser.add_argument('--mode',choices=['processes','memory','cpu','storage'],required=True);args=parser.parse_args()
    if not args.inside_capped_test_job:raise SystemExit('Explicit capped test-job context required')
    run(args.mode)
