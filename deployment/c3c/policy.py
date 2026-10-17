"""C3C admission policy. Authentication is not URL destination authorization."""
import hashlib
import hmac
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Limits:
    # Calibration starting points, not hardware-independent accepted defaults.
    seconds: int = 180
    memory_mib: int = 1536
    broker_memory_mib: int = 256
    pids: int = 64
    cpu: float = 1.0
    temporary_mib: int = 256
    output_bytes: int = 8 * 1024 * 1024

    def __post_init__(self):
        bounds = dict(seconds=(10,600), memory_mib=(512,4096),
                      broker_memory_mib=(128,512), pids=(16,128),
                      temporary_mib=(32,512), output_bytes=(1024,8*1024*1024))
        for key,(low,high) in bounds.items():
            value=getattr(self,key)
            if type(value) is not int or not low<=value<=high:
                raise ValueError('Invalid operation budget: '+key)
        if type(self.cpu) not in (int,float) or not math.isfinite(self.cpu) or not .1<=self.cpu<=2:
            raise ValueError('Invalid CPU budget')


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def authorize(envelope, key, principal, now=None):
    """Verify controller signature, short expiry and owner. Caller consumes nonce once.

    A trusted authenticated gateway must supply principal; never accept it from
    an unauthenticated client header. This helper does not implement an IdP.
    """
    now=time.time() if now is None else now
    if not isinstance(key,bytes) or len(key)<32:
        raise ValueError('A dedicated signing key of at least 32 bytes is required')
    if not isinstance(envelope,dict) or set(envelope)!={'job','signature'}:
        raise ValueError('Invalid envelope')
    job=envelope['job']
    if not isinstance(job,dict) or set(job)!={'owner','nonce','expires','url','pages'}:
        raise ValueError('Invalid job schema')
    expected=hmac.new(key,canonical(job),hashlib.sha256).hexdigest()
    if not isinstance(envelope['signature'],str) or not hmac.compare_digest(expected,envelope['signature']):
        raise ValueError('Invalid job signature')
    if not isinstance(principal,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',principal) or job['owner']!=principal:
        raise ValueError('Job owner mismatch')
    if not isinstance(job['nonce'],str) or not re.fullmatch(r'[a-f0-9]{32}',job['nonce']):
        raise ValueError('Invalid one-use nonce')
    if type(job['expires']) not in (int,float) or not math.isfinite(job['expires']) or not now<job['expires']<=now+300:
        raise ValueError('Expired or excessive job lifetime')
    if type(job['pages']) is not int or not 1<=job['pages']<=10:
        raise ValueError('Page limit outside controlled initial scope')
    p=urlsplit(job['url'])
    if p.scheme not in ('http','https') or not p.hostname or p.username is not None or p.password is not None:
        raise ValueError('Invalid audit URL')
    if p.port not in (None,80,443):
        raise ValueError('Only public web ports are enabled in this deployment profile')
    if len(job['url'])>4096:
        raise ValueError('Audit URL too long')
    return dict(job)


def owned_result(state,nonce,principal):
    """Private-controller retrieval helper; principal must be authenticated first."""
    if not isinstance(nonce,str) or not re.fullmatch('[a-f0-9]{32}',nonce):
        raise ValueError('Invalid result identifier')
    path=Path(state)/(nonce+'-result.json')
    if path.is_symlink() or path.stat().st_size>8*1024*1024:
        raise ValueError('Invalid stored result')
    value=json.loads(path.read_bytes())
    if not isinstance(principal,str) or not principal or value.get('owner')!=principal:
        raise ValueError('Result owner mismatch')
    return value
