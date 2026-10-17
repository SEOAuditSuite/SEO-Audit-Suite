"""Signing client for the private API; TLS and optional mTLS, no implicit proxies."""
import argparse
import hashlib
import hmac
import json
from pathlib import Path
import time
import uuid

import requests

from deployment.c3c.authentication import signature
from deployment.c3c.policy import canonical


def headers(key,owner,method,path,body,now=None,nonce=None):
    stamp=str(int(time.time() if now is None else now));nonce=nonce or uuid.uuid4().hex
    return {'X-SEO-Owner':owner,'X-SEO-Time':stamp,'X-SEO-Nonce':nonce,
            'X-SEO-Signature':signature(key,method,path,body,owner,stamp,nonce),
            'Content-Type':'application/json'}


def envelope(key,owner,url,pages=5,now=None,nonce=None):
    job=dict(owner=owner,url=url,pages=pages,expires=int(time.time() if now is None else now)+300,
             nonce=nonce or uuid.uuid4().hex)
    return dict(job=job,signature=hmac.new(key,canonical(job),hashlib.sha256).hexdigest())


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--endpoint',required=True);parser.add_argument('--owner',required=True)
    parser.add_argument('--key',type=Path,required=True);parser.add_argument('--ca',type=Path,required=True)
    parser.add_argument('--cert',type=Path,required=True);parser.add_argument('--cert-key',type=Path,required=True)
    parser.add_argument('--job');parser.add_argument('--artifact');parser.add_argument('--cancel',action='store_true')
    parser.add_argument('--url');parser.add_argument('--pages',type=int,default=5);parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if not args.endpoint.startswith('https://'):parser.error('HTTPS endpoint required')
    if args.key.is_symlink() or args.key.stat().st_mode & 0o077:parser.error('Mode-0600 owner key required')
    key=bytes.fromhex(args.key.read_text().strip())
    if len(key)!=32:parser.error('32-byte owner key required')
    path='/v1/jobs';method='POST';body=b''
    if args.url:body=json.dumps(envelope(key,args.owner,args.url,args.pages)).encode()
    elif args.job:
        path+='/'+args.job;method='DELETE' if args.cancel else 'GET'
        if args.artifact:path+='/artifacts/'+args.artifact
    else:parser.error('--url or --job required')
    with requests.Session() as session:
        session.trust_env=False
        response=session.request(method,args.endpoint.rstrip('/')+path,data=body,
            headers=headers(key,args.owner,method,path,body),verify=str(args.ca),
            cert=(str(args.cert),str(args.cert_key)),timeout=(5,15),allow_redirects=False,stream=True)
        response.raise_for_status();out=bytearray()
        for chunk in response.iter_content(65536):
            out.extend(chunk)
            if len(out)>8*1024*1024:raise RuntimeError('Response exceeds client budget')
        if args.output:
            with args.output.open('xb') as stream:stream.write(out)
        else:print(out.decode())


if __name__=='__main__':main()
