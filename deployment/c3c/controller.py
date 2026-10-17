"""Private authenticated Unix-socket API. No Docker authority in this service."""
import argparse
import base64
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import re
import socketserver
import sqlite3
import socket
import threading
import time

from deployment.c3c.authentication import authenticate,Denied,load_keys
from deployment.c3c.policy import authorize
from deployment.c3c.store import Store,Busy,Missing

MAX_INPUT=16384


class API:
    def __init__(self,store,keys):self.store=store;self.keys=keys
    def dispatch(self,method,path,headers,body,now=None):
        now=time.time() if now is None else now
        if len(body)>MAX_INPUT:return 413,{},b''
        try:
            owner=authenticate(self.keys,self.store,method,path,body,headers,now)
            response_headers={'Content-Type':'application/json','Cache-Control':'no-store',
                              'X-Content-Type-Options':'nosniff'}
            if method=='POST' and path=='/v1/jobs':
                envelope=json.loads(body)
                authorize(envelope,self.keys[owner],owner,now)
                ident=self.store.admit(envelope,now)
                return 202,response_headers,json.dumps(dict(id=ident,status='queued')).encode()
            match=re.fullmatch(r'/v1/jobs/([a-f0-9]{32})(?:/artifacts/([a-z0-9-]+\.(?:html|json|csv|md|pdf)))?',path)
            if not match:raise Missing()
            ident,name=match.groups()
            if method=='DELETE' and name is None:
                row=self.store.cancel(ident,owner)
                return 202,response_headers,json.dumps(dict(id=ident,status=row['status'])).encode()
            if method!='GET' or body:raise Missing()
            row=self.store.read(ident,owner);result=json.loads(row['result']) if row['result'] else {}
            if name:
                if row['status'] not in ('completed','incomplete','cancelled'):raise Missing()
                value=result.get('files',{}).get(name)
                if value is None:raise Missing()
                data=base64.b64decode(value,validate=True)
                response_headers.update({'Content-Type':'application/octet-stream',
                    'Content-Disposition':'attachment; filename="'+name+'"',
                    'Content-Security-Policy':"sandbox; default-src 'none'"})
                return 200,response_headers,data
            data=dict(id=ident,status=row['status'],cancel_requested=bool(row['cancel']),
                      cleanup_confirmed=result.get('cleanup_confirmed'),
                      reason=result.get('reason'),artifacts=sorted(result.get('files',{})))
            return 200,response_headers,json.dumps(data).encode()
        except Denied:return 401,{'Content-Type':'application/json'},b'{"error":"Authentication rejected"}'
        except Missing:return 404,{'Content-Type':'application/json'},b'{"error":"Not available"}'
        except Busy:return 429,{'Retry-After':'30'},b'{"error":"Admission or request capacity unavailable"}'
        except (ValueError,TypeError,KeyError):return 400,{},b'{"error":"Invalid request"}'
        except sqlite3.Error:return 503,{},b'{"error":"Storage unavailable; no audit result inferred"}'


class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.0'
    def log_message(self,*args):pass  # No tokens, URLs, bodies or owner credentials in access logs.
    def handle_one_request(self):
        def abort():
            try:self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:pass
        timer=threading.Timer(5,abort);timer.daemon=True;timer.start()
        self.connection.settimeout(5)
        try:super().handle_one_request()
        except (TimeoutError,OSError):self.close_connection=True
        finally:timer.cancel();self.close_connection=True
    def do_request(self):
        # Reject ambiguous framing; no chunked upload or duplicate auth headers.
        headers=self.headers
        bad=bool(headers.get('Transfer-Encoding')) or any(len(headers.get_all(k,[]))>1 for k in
             ('Content-Length','X-SEO-Owner','X-SEO-Time','X-SEO-Nonce','X-SEO-Signature'))
        length=headers.get('Content-Length','0')
        if bad or not re.fullmatch('[0-9]{1,6}',length):self.send_error(400);return
        if int(length)>MAX_INPUT:self.send_error(413);return
        body=self.rfile.read(int(length))
        if len(body)!=int(length):self.send_error(400);return
        code,extra,data=self.server.api.dispatch(self.command,self.path,headers,body)
        self.send_response(code)
        for key,value in extra.items():self.send_header(key,value)
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    do_GET=do_POST=do_DELETE=do_request


class Server(socketserver.UnixStreamServer):
    request_queue_size=4


def main():
    parser=argparse.ArgumentParser()
    for flag in ('socket','database','keys'):parser.add_argument('--'+flag,required=True,type=Path)
    args=parser.parse_args()
    if args.socket.exists():raise SystemExit('Existing socket; refuse overwrite')
    if args.socket.parent.is_symlink() or args.socket.parent.stat().st_mode & 0o007:
        raise SystemExit('Restricted Unix socket directory required')
    os.umask(0o007)
    api=API(Store(args.database),load_keys(args.keys))
    try:
        with Server(str(args.socket),Handler) as server:
            os.chmod(args.socket,0o660);server.api=api;server.serve_forever(poll_interval=.2)
    finally:args.socket.unlink(missing_ok=True)


if __name__=='__main__':main()
