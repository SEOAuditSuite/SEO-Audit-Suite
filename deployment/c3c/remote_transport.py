"""Container-only safe_http overlay; original source files are never edited.

Installed as /app/safe_http.py; original C1 transport is /app/c1_transport.py.
Missing broker fails closed. Redirect handling remains in existing audit modules.
"""
import base64
import json
import math
import socket
import time

from requests import Response
from requests.structures import CaseInsensitiveDict
from c1_transport import TransportError, _target, _public_address, resolve_addresses

SOCKET='/run/seo-broker/broker.sock'


class SafeSession:
    trust_env=False
    def __init__(self,*,max_total_bytes=None):
        self.max_total_bytes=max_total_bytes
        self.decoded_bytes=0

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def close(self):pass

    def get(self,url,*,headers=None,timeout=20,allow_redirects=False,stream=True,deadline=None,max_bytes=5*1024*1024):
        if allow_redirects or type(max_bytes) is not int or not 1<=max_bytes<=5*1024*1024:
            raise TransportError('Invalid remote GET policy')
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:
            raise TransportError('Invalid remote GET timeout')
        if deadline is not None and (type(deadline) not in (int,float) or not math.isfinite(deadline)):
            raise TransportError('Invalid remote deadline')
        if self.max_total_bytes is not None:
            max_bytes=min(max_bytes,self.max_total_bytes-self.decoded_bytes)
        if max_bytes<1:raise TransportError('Session decoded byte budget exceeded')
        seconds=min(timeout,30,deadline-time.monotonic() if deadline is not None else 30)
        if seconds<=0:raise TransportError('Remote deadline exceeded')
        allocation=max_bytes
        try:
            request=dict(url=url,headers=headers or {},max_bytes=max_bytes,seconds=seconds)
            raw=json.dumps(request,separators=(',',':')).encode()+b'\n'
            if len(raw)>16384:raise ValueError('Request too large')
            end=time.monotonic()+seconds
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
                conn.settimeout(seconds);conn.connect(SOCKET);conn.sendall(raw)
                with conn.makefile('rb') as source:
                    # Kernel timeout alone is not a total deadline. The broker C1
                    # operation and external job supervisor also enforce deadlines.
                    line=source.readline(7*1024*1024+1)
            if time.monotonic()>end or len(line)>7*1024*1024 or not line.endswith(b'\n'):
                raise ValueError('Invalid response size/deadline')
            data=json.loads(line)
            if data.get('ok') is not True:raise ValueError('Broker unavailable')
            body=base64.b64decode(data['body'],validate=True)
            if len(body)>max_bytes or type(data['status']) is not int or not 100<=data['status']<=599:
                raise ValueError('Invalid response')
            out=Response();out.url=data['url'];out.status_code=data['status']
            out.headers=CaseInsensitiveDict(data['headers']);out.encoding=data.get('encoding')
            out._content=body;out._content_consumed=True;out.history=[]
            self.decoded_bytes+=len(body)
            return out
        except Exception:
            self.decoded_bytes+=allocation
            raise TransportError('HTTP broker blocked, unavailable or deadline exceeded') from None
