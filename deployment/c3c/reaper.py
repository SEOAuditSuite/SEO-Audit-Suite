"""External timer entrypoint: remove expired owned jobs after supervisor failure."""
import json
import re
import time
from deployment.c3c.supervisor import Runtime,LABEL


def reap(runtime=None,now=None):
    runtime=runtime or Runtime(60)
    now=time.time() if now is None else now
    ids=runtime.call(['ps','--all','--quiet','--filter','label=seo.c3c.managed=true']).decode().split()
    removed=[]
    for ident in ids:
        if not re.fullmatch('[a-f0-9]{12,64}',ident):raise RuntimeError('Invalid owned container ID')
        info=json.loads(runtime.call(['inspect',ident]))[0]
        labels=info.get('Config',{}).get('Labels',{})
        nonce=labels.get(LABEL,'')
        if not re.fullmatch('[a-f0-9]{32}',nonce) or info.get('Name') not in ('/c3c-'+nonce+'-worker','/c3c-'+nonce+'-broker'):
            raise RuntimeError('Ownership mismatch; refuse removal')
        expiry=labels.get('seo.c3c.expires','')
        if not expiry.isdigit():raise RuntimeError('Missing owned job expiry')
        if float(expiry)>now:continue
        runtime.call(['rm','--force',ident],cleanup=True)
        removed.append(nonce)
    for nonce in set(removed):
        if runtime.call(['ps','--all','--quiet','--filter','label='+LABEL+'='+nonce],cleanup=True).strip():
            raise RuntimeError('Expired owned job survivors remain')
        # Volume removal cannot affect another nonce; failure is observable.
        volume='c3c-'+nonce+'-ipc'
        owned=runtime.call(['volume','ls','--quiet','--filter','label='+LABEL+'='+nonce],cleanup=True).decode().split()
        if volume in owned:runtime.call(['volume','rm',volume],cleanup=True)
    return removed


if __name__=='__main__':print(json.dumps(dict(removed=reap())))
