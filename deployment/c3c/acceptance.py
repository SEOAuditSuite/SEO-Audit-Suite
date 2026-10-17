"""One evidence-producing Linux acceptance entrypoint; unsupported is NOT VERIFIED.

Does not install packages, change firewall rules, expose ports or build/deploy.
Native resource fixtures require explicit --native and reviewed local image ID.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import time
import zipfile


def preflight():
    result=dict(platform=platform.platform(),python=sys.version,docker=shutil.which('docker'),
                unix_socket='NOT VERIFIED',native_enforcement='NOT VERIFIED')
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM):pass
        result['unix_socket']='available (creation only; not end-to-end acceptance)'
    except OSError as exc:result['unix_socket']='NOT VERIFIED: '+type(exc).__name__
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--native',action='store_true');parser.add_argument('--worker-image')
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[2]
    record=dict(status='NOT VERIFIED',preflight=preflight(),started_utc=time.time(),stages={})
    exit_code=2  # Explicit incomplete acceptance; never a success exit for unrun gates.
    try:
        with (out/'Regression.log').open('w') as log:
            run=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=root,
                               stdout=log,stderr=subprocess.STDOUT,timeout=180)
        # The raw log retains skipped/native blockers; rc==0 is not all gates PASS.
        record['stages']['regression']=dict(returncode=run.returncode,log='Regression.log')
        if run.returncode:record['status']='FAIL';exit_code=1
        if args.native:
            if run.returncode:record['stages']['native']='NOT VERIFIED: regression failed; native stage not started'
            elif not record['preflight']['docker']:record['stages']['native']='NOT VERIFIED: Docker unavailable'
            elif not args.worker_image:record['stages']['native']='NOT VERIFIED: reviewed image ID required'
            else:
                from deployment.c3c.native_runner import run as native_run
                record['stages']['native']=native_run(args.worker_image,out/'Native-Resources')
        else:record['stages']['native']='NOT VERIFIED: native execution not requested'
        record['remaining_gates']=['mTLS gateway and real signed API over Unix socket',
            'independent IPv4/IPv6/metadata canaries and packet/firewall evidence',
            'real Chromium through socket broker, redirects and partial rendering',
            'native cancellation, supervisor crash/reaper and zero-owned-survivor evidence',
            'quotas, credential/filesystem boundaries and calibrated host headroom']
    except Exception as exc:record['error_type']=type(exc).__name__
    finally:
        (out/'Acceptance.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        (out/'Acceptance-Report.md').write_text('# Linux Security Acceptance\n\nStatus: '+record['status']+'\n\n'
            'Review Acceptance.json and raw logs. Successful deterministic/resource stages do not certify '
            'network isolation, gateway authorization, native cancellation or Chromium compatibility. '
            'Complete INTEGRATION.md before requesting acceptance. No deployment was performed.\n',encoding='utf-8')
        hashes={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file()}
        (out/'SHA256SUMS.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
        archive=out.with_name(out.name+'-Evidence.zip')
        if archive.exists():raise RuntimeError('Refusing existing evidence ZIP')
        with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as zipped:
            for p in sorted(out.rglob('*')):
                if p.is_file():zipped.write(p,p.relative_to(out))
        print(archive)
    return exit_code


if __name__=='__main__':raise SystemExit(main())
