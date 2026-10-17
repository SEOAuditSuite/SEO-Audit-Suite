"""External single-job agent; controller has no runtime socket or runtime access."""
import argparse
import json
import os
from pathlib import Path
import time

from deployment.c3c.authentication import load_keys
from deployment.c3c.policy import authorize,Limits
from deployment.c3c.store import Store
from deployment.c3c.supervisor import Runtime,execute,image_id


class Cancelled(RuntimeError):pass


class CancellableRuntime(Runtime):
    def __init__(self,seconds,cancelled):
        self.cancelled=cancelled
        super().__init__(seconds)
    @property
    def deadline(self):
        try:cancel=self.cancelled()
        except Exception:raise Cancelled('Cancellation state unavailable; fail closed') from None
        if cancel:raise Cancelled('Owner cancelled operation')
        return self._deadline
    @deadline.setter
    def deadline(self,value):self._deadline=value


class Agent:
    def __init__(self,store,keys,state,worker_image,broker_image,executor=execute,limits=None):
        self.store=store;self.keys=keys;self.state=Path(state)
        self.worker_image=image_id(worker_image);self.broker_image=image_id(broker_image)
        self.executor=executor;self.limits=limits or Limits()
    def tick(self,now=None):
        row=self.store.claim()
        if row is None:return False
        ident=row['id']
        result=dict(status='incomplete',http_status=None,cleanup_confirmed=True,files={})
        try:
            envelope=json.loads(row['envelope'])
            job=authorize(envelope,self.keys[row['owner']],row['owner'],now)
            if job['nonce']!=ident:raise ValueError('Queued identity mismatch')
            if self.store.cancelled(ident):raise Cancelled('Cancelled before launch')
        except Exception:
            result['reason']='Queued admission expired, invalid or cancelled; no worker launched'
        else:
            try:
                runtime=CancellableRuntime(self.limits.seconds,lambda:self.store.cancelled(ident))
                result=self.executor(job,self.worker_image,self.broker_image,self.state,limits=self.limits,runtime=runtime)
            except Exception:
                # An unexpected supervisor escape cannot prove cleanup.
                result=dict(status='NOT VERIFIED',http_status=None,cleanup_confirmed=False,files={},
                            reason='Supervisor failed without verified cleanup')
        self.store.finish(ident,result)
        return True


def reconcile(store,state,runtime=None):
    runtime=runtime or Runtime(15)
    if runtime.call(['ps','--all','--quiet','--filter','label=seo.c3c.managed=true']).strip():
        raise RuntimeError('Owned containers remain; do not clear quarantine')
    if runtime.call(['volume','ls','--quiet','--filter','label=seo.c3c.job']).strip():
        raise RuntimeError('Owned IPC volumes remain; do not clear quarantine')
    # This is operational reconciliation, not a claim of kernel/process isolation.
    store.clear_quarantine()
    (Path(state)/'ADMISSION-BLOCKED').unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser()
    for flag in ('database','keys','state'):parser.add_argument('--'+flag,required=True,type=Path)
    parser.add_argument('--worker-image',required=True);parser.add_argument('--broker-image',required=True)
    parser.add_argument('--once',action='store_true');parser.add_argument('--reconcile',action='store_true')
    args=parser.parse_args();os.umask(0o007)
    store=Store(args.database)
    if args.reconcile:reconcile(store,args.state);return
    store.reconcile_startup()
    agent=Agent(store,load_keys(args.keys),args.state,args.worker_image,args.broker_image)
    while True:
        worked=agent.tick()
        if args.once:return
        if not worked:time.sleep(.5)


if __name__=='__main__':main()
