"""One-job anonymous GET broker over a private Unix socket, outside browser netns.

No service credential, unrestricted tunnel, automatic redirect or inherited proxy.
Host firewall enforcement remains mandatory and is independently tested.
"""
import base64
import json
import os
from pathlib import Path
import socketserver
import time
from urllib.parse import urlsplit

from safe_http import SafeSession

MAX_REQUEST=16384
MAX_BODY=5*1024*1024
SOCKET='/run/seo-broker/broker.sock'


class Broker(socketserver.UnixStreamServer):
    # Serial by design: one outstanding request and one session per operation.
    request_queue_size=2
    def __init__(self,path,handler,session=None,seconds=180):
        self.session=session or SafeSession(max_total_bytes=100*1024*1024)
        self.deadline=time.monotonic()+seconds
        self.requests=0
        super().__init__(path,handler)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(10)
        try:
            raw=self.rfile.readline(MAX_REQUEST+1)
            if len(raw)>MAX_REQUEST or not raw.endswith(b'\n'):
                raise ValueError('Request framing/size rejected')
            req=json.loads(raw)
            if not isinstance(req,dict) or set(req)!={'url','headers','max_bytes','seconds'}:
                raise ValueError('Only bounded anonymous GET requests are supported')
            if self.server.requests>=500 or time.monotonic()>=self.server.deadline:
                raise ValueError('Operation budget exhausted')
            self.server.requests+=1
            p=urlsplit(req['url'])
            if p.scheme not in ('http','https') or p.port not in (None,80,443) or p.username is not None or p.password is not None:
                raise ValueError('Destination scheme, port or credentials rejected')
            size=req['max_bytes'];seconds=req['seconds'];headers=req['headers']
            if type(size) is not int or not 1<=size<=MAX_BODY:
                raise ValueError('Invalid body budget')
            if type(seconds) not in (int,float) or not 0<seconds<=30:
                raise ValueError('Invalid time budget')
            if not isinstance(headers,dict) or len(headers)>8 or any(not isinstance(k,str) or not isinstance(v,str) for k,v in headers.items()):
                raise ValueError('Invalid headers')
            # C1 owns DNS validation, numeric-IP connection and hostname TLS.
            with self.server.session.get(req['url'],headers=headers,max_bytes=size,
                    timeout=min(5,seconds),deadline=min(self.server.deadline,time.monotonic()+seconds),
                    allow_redirects=False) as response:
                out=dict(ok=True,url=response.url,status=response.status_code,
                         headers=dict(response.headers),encoding=response.encoding,
                         body=base64.b64encode(response.content).decode())
        except Exception:
            # Never disclose query strings, resolver data or local exception text.
            out=dict(ok=False,error='HTTP request blocked, unavailable or operation budget exhausted')
        try:self.wfile.write(json.dumps(out,separators=(',',':')).encode()+b'\n')
        except OSError:pass


def main():
    path=Path(SOCKET)
    if path.exists():raise SystemExit('Refusing existing broker socket')
    with Broker(str(path),Handler) as server:
        os.chmod(path,0o600)
        server.serve_forever(poll_interval=.2)


if __name__=='__main__':main()
