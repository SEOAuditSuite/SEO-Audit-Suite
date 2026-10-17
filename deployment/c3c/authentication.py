"""Per-owner HMAC request authentication on a private TLS-protected control API."""
import hashlib
import hmac
import json
from pathlib import Path
import re
import time

from deployment.c3c.policy import canonical

OWNER=re.compile(r'[A-Za-z0-9_-]{1,64}')
NONCE=re.compile(r'[a-f0-9]{32}')


class Denied(ValueError):pass


def load_keys(path):
    path=Path(path)
    if path.is_symlink() or path.stat().st_mode & 0o027 or path.stat().st_size>8192:
        raise Denied('Restricted key file required')
    data=json.loads(path.read_bytes())
    if not isinstance(data,dict) or not 1<=len(data)<=32:raise Denied('Invalid key configuration')
    keys={}
    for owner,value in data.items():
        if not OWNER.fullmatch(owner) or not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value):
            raise Denied('Invalid owner key')
        keys[owner]=bytes.fromhex(value)
    if len(set(keys.values()))!=len(keys):raise Denied('Owner keys must be independent')
    return keys


def signature(key,method,path,body,owner,timestamp,nonce):
    payload=dict(method=method,path=path,body_sha256=hashlib.sha256(body).hexdigest(),
                 owner=owner,timestamp=timestamp,nonce=nonce)
    return hmac.new(key,canonical(payload),hashlib.sha256).hexdigest()


def authenticate(keys,store,method,path,body,headers,now=None):
    now=time.time() if now is None else now
    try:
        owner=headers['X-SEO-Owner'];stamp=headers['X-SEO-Time'];nonce=headers['X-SEO-Nonce']
        supplied=headers['X-SEO-Signature']
        if not OWNER.fullmatch(owner) or owner not in keys or not NONCE.fullmatch(nonce):raise Denied()
        if not re.fullmatch('[0-9]{1,12}',stamp) or not now-60<=int(stamp)<=now+10:raise Denied()
        expected=signature(keys[owner],method,path,body,owner,stamp,nonce)
        if not isinstance(supplied,str) or not hmac.compare_digest(expected,supplied):raise Denied()
        store.consume_request(owner,nonce,now)
        return owner
    except (KeyError,TypeError,ValueError):
        raise Denied('Request authentication rejected') from None
