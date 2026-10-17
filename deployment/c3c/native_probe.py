"""Infrastructure probes run INSIDE a test job, never in the developer host.

Socket attempts bypass C1/Playwright. Connection failure alone is not full proof;
pair results with reachable controlled canaries and firewall/packet evidence.
"""
import argparse
import ipaddress
import json
import os
import socket
import time

TARGETS=('127.0.0.1','::1','10.0.0.1','172.16.0.1','192.168.0.1',
         '169.254.169.254','100.100.100.200','fd00:ec2::254','fe80::1')


def probe(targets=TARGETS):
    rows=[]
    for target in targets:
        address=ipaddress.ip_address(target)
        family=socket.AF_INET6 if address.version==6 else socket.AF_INET
        row=dict(destination=target,port=80,connected=False)
        try:
            with socket.socket(family,socket.SOCK_STREAM) as sock:
                sock.settimeout(.25);sock.connect((target,80));row['connected']=True
        except OSError as exc:row['error_type']=type(exc).__name__
        rows.append(row)
    return dict(status='failed' if any(r['connected'] for r in rows) else 'NOT VERIFIED',
                note='No connections is inconclusive without canary reachability and independent packet evidence',
                uid=os.getuid(),results=rows)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--inside-isolated-job',action='store_true');args=parser.parse_args()
    if not args.inside_isolated_job:raise SystemExit('Explicit isolated test-job context required')
    print(json.dumps(probe()))
