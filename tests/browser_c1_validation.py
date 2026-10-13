"""Explicit Chrome bridge checks: production C1 transport, controlled loopback fixture.

Test-only mocks allow the fixture's loopback IP. No production bypass is added.
Run separately; a missing Chrome produces blocked/zero checks, never success.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
import rendering_diagnostics as rd
from test_http_link_integration import ControlledSite, FixtureHandler


def chrome(p, launch_args=None):
    return p.chromium.launch(channel='chrome', headless=True, args=launch_args or [])


def main(output):
    output.mkdir(parents=True, exist_ok=True)
    checks=[]; evidence={};status='blocked';error=''
    def check(name,ok):checks.append(dict(name=name,status='passed' if ok else 'failed'))
    def respond(handler):
        handler.server.observed_requests.append((handler.headers.get('Host',''), handler.path))
        bodies={
            '/':('text/html', '<!doctype html><title>Raw C1</title><main><h1>Raw heading</h1><a href="/keep">Keep</a></main><script src="/app.js"></script>'),
            '/app.js':('text/javascript', "document.title='Rendered C1';fetch('/api').then(r=>r.json()).then(d=>document.querySelector('main').innerHTML=d.html);fetch('http://127.0.0.1:1/forbidden').catch(()=>{});"),
            '/api':('application/json', json.dumps({'html':'<h1>Rendered heading</h1><h2>Section</h2><a href="/keep">Keep</a><a href="/added">Added</a>'})),
        }
        kind,body=bodies.get(handler.path,('text/plain','Unexpected request'))
        data=body.encode();handler.send_response(200);handler.send_header('Content-Type',kind);handler.send_header('Content-Length',str(len(data)));handler.end_headers();handler.wfile.write(data)
    try:
        from playwright.sync_api import sync_playwright
        # Establish availability before recording any pass.
        with sync_playwright() as p:
            browser=chrome(p);evidence['browser_version']=browser.version;browser.close()
        with patch.object(FixtureHandler,'do_GET',respond),ControlledSite() as site,patch.object(rd,'_launch_browser',chrome):
            result=rd._compare_page(site.base+'/')
            evidence['comparison']=result;evidence['observed_requests']=site.server.observed_requests
            check('Production pinned transport supports browser replay',result['comparison_available'])
            raw=result.get('raw') or {};rendered=result.get('rendered') or {}
            rf=raw.get('fields',{});df=rendered.get('fields',{})
            check('Raw and JavaScript title evidence preserved',rf.get('Title',{}).get('values')==['Raw C1'] and df.get('Title',{}).get('values')==['Rendered C1'])
            check('Same-origin fetch renders headings',df.get('H1',{}).get('values')==['Rendered heading'] and df.get('H2',{}).get('count')==1)
            check('Rendered internal link evidence preserved',df.get('Internal links',{}).get('count')==2)
            observed=[path for _,path in site.server.observed_requests]
            check('Only allowed fixture resources requested',set(observed)=={'/','/app.js','/api'} and len(observed)==3)
        status='passed' if all(c['status']=='passed' for c in checks) else 'failed'
    except Exception as exc:
        error=type(exc).__name__+': '+str(exc)
        status='failed' if checks else 'blocked'
    evidence.update(status=status,error=error,checks=checks,executed_checks=len(checks),passed_checks=sum(c['status']=='passed' for c in checks),
        source_sha256={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.rglob('*.py') if '.venv' not in p.parts})
    (output/'browser-results.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    (output/'Browser-Validation-Report.md').write_text('# C1 Chrome Transport Bridge Validation\n\n'
        +f'Status: {status}. Executed: {len(checks)}. Passed: {evidence["passed_checks"]}.\n\n'
        +'Controlled fixtures only. Does not certify normal-browser isolation or public deployment.\n\n'
        +'\n'.join('- '+c['name']+': '+c['status'] for c in checks)+'\n'+error,encoding='utf-8')
    print(f'Status: {status}; executed: {len(checks)}; passed: {evidence["passed_checks"]}')
    return 0 if status=='passed' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    sys.exit(main(parser.parse_args().output))
