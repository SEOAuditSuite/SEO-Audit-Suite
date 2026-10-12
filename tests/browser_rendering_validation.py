"""Explicit real-Chrome validation, separate from the automated regression suite.

Run: python tests/browser_rendering_validation.py --output PATH
No external sites are contacted: controlled resources are fulfilled from memory.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
import rendering_diagnostics as rd
from test_rendering_diagnostics import BASE, RAW, DOM
from test_rendering_integration import delivery
from client_workflow import delivery_files
from common import parse_html


class FixtureTransport:
    def __init__(self, mode='normal'):
        self.mode=mode;self.requests=0;self.bytes=0;self.urls=[]

    def get(self, url):
        self.requests+=1;self.urls.append(url)
        headers={'content-type':'text/html; charset=utf-8', 'x-robots-tag':'follow'}
        body=RAW.replace('</body>','<script src="/app.js"></script></body>')
        if url == BASE+'app.js':
            headers={'content-type':'text/javascript'}
            body="""document.title='Rendered title';
document.querySelector('meta[name=description]').content='Rendered description';
document.querySelector('link[rel=canonical]').href='/final/';
document.querySelector('meta[name=robots]').content='index, follow';
fetch('/api').then(r=>r.json()).then(d=>{ document.querySelector('main').innerHTML=d.html; });"""
            if self.mode=='restricted':
                body+="fetch('https://foreign.test/private').catch(()=>{});fetch('/post',{method:'POST'}).catch(()=>{});"
            elif self.mode=='navigate':body="location.href='https://foreign.test/';"
            elif self.mode=='error':body="throw new Error('controlled failure');"
            elif self.mode=='oversize':body="document.body.innerHTML='x'.repeat(2*1024*1024+1);"
            elif self.mode=='hang':body='while(true) {}'
        elif url == BASE+'api':
            headers={'content-type':'application/json'}
            body=json.dumps({'html':parse_html(DOM).find('main').decode_contents()})
        elif url != BASE:
            raise AssertionError('Unexpected resource request: '+url)
        raw=body.encode();self.bytes+=len(raw)
        return dict(url=url,status=200,headers=headers,body=raw,redirects=[])


def chrome(p, args=None):
    return p.chromium.launch(channel='chrome',headless=True,args=args or [])


def run_fixture(mode='normal'):
    transport=FixtureTransport(mode)
    with patch.object(rd,'_launch_browser',side_effect=chrome):
        result=rd._compare_page(BASE,transport)
    return result,transport


def main(output):
    output.mkdir(parents=True,exist_ok=True)
    checks=[];evidence={};status='blocked';error=''
    def check(name, condition):
        checks.append(dict(name=name,status='passed' if condition else 'failed'))
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b=chrome(p);evidence['browser_version']=b.version;b.close()
        result,transport=run_fixture();evidence['normal']=result
        check('Paired raw and real DOM comparison available',result['comparison_available'])
        if not result['comparison_available']:
            raise RuntimeError('Controlled comparison did not complete: '+'; '.join(result['warnings']))
        rows={r['Element']:r for r in result['rows']}
        for name in rd.FIELDS:
            check(name+' change observed',rows[name]['Change']=='Changed')
        check('Raw title retained from shared response',result['raw']['fields']['Title']['values']==['Raw title'])
        check('Same-origin script and asynchronous API fulfilled',transport.urls==[BASE,BASE+'app.js',BASE+'api'])
        check('Duplicate incoming anchor occurrence removed',len(json.loads(rows['Internal links']['Removed']))==2)
        check('Raw noindex warning retained',any('noindex' in w for w in result['warnings']))
        restricted,t=run_fixture('restricted');evidence['restricted']=restricted
        check('Restricted resources visibly limit evidence',any('blocked' in w for w in restricted['warnings']))
        check('Cross-origin and POST requests never reach transport',all(u in [BASE,BASE+'app.js',BASE+'api'] for u in t.urls))
        navigation,_=run_fixture('navigate');evidence['navigation']=navigation
        check('Client navigation not compared as missing content',not navigation['comparison_available'] and not navigation['rows'])
        broken,_=run_fixture('error');evidence['script_error']=broken
        check('Script errors produce incomplete-evidence warning',any('Script execution errors' in w for w in broken['warnings']))
        oversized,_=run_fixture('oversize');evidence['oversize']=oversized
        check('Oversized rendered DOM is not assessed',not oversized['comparison_available'])
        # Exercise the production process-tree deadline against a real looping renderer.
        original=rd.subprocess.Popen
        def looping_worker(command, **kwargs):
            if command[-1:] == ['--worker']:
                command=[sys.executable,str(Path(__file__).resolve()),'--hang-worker']
            return original(command,**kwargs)
        start=time.monotonic()
        with patch.object(rd.subprocess,'Popen',side_effect=looping_worker),patch.dict(rd.LIMITS,wall_seconds=5):
            timed=rd.compare_url(BASE)
        evidence['deadline']=timed
        check('Isolated hanging renderer deadline enforced',not timed['comparison_available'] and 'deadline' in ' '.join(timed['warnings']) and time.monotonic()-start<16)
        check('Process tree cleanup confirmed',not any('cleanup could not' in w for w in timed['warnings']))
        pack=delivery(include_rendering=True,rendering_result=result)
        files=delivery_files(pack)
        for name,data in files.items():(output/name).write_bytes(data)
        evidence['report_sha256']=hashlib.sha256(files['client-report.html']).hexdigest()
        with sync_playwright() as p:
            browser=chrome(p)
            try:
                for name,width,height in [('desktop',1440,900),('mobile',360,800)]:
                    context=browser.new_context(viewport={'width':width,'height':height},service_workers='block')
                    context.route('**/*',lambda route:route.fulfill(content_type='text/html',body=files['client-report.html']) if route.request.url=='https://report.example.test/' else route.abort())
                    page=context.new_page();page.goto('https://report.example.test/',wait_until='load')
                    check(name+' report section present',page.locator('#rendering-comparison').count()==1)
                    check(name+' eight field summaries',page.locator('#rendering-comparison article').count()==8)
                    check(name+' no horizontal overflow',page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                    check(name+' warning readable in report',page.locator('#rendering-comparison').inner_text().find('Raw noindex')>=0)
                    page.screenshot(path=str(output/(name+'-top.png')),full_page=False)
                    page.locator('#rendering-comparison').scroll_into_view_if_needed()
                    page.screenshot(path=str(output/(name+'-comparison.png')),full_page=False)
                    page.evaluate('window.scrollTo(0,document.body.scrollHeight)')
                    page.screenshot(path=str(output/(name+'-bottom.png')),full_page=False)
                    context.close()
            finally:browser.close()
        status='passed' if all(c['status']=='passed' for c in checks) else 'failed'
    except Exception as exc:
        status='failed' if checks else 'blocked';error=type(exc).__name__+': '+str(exc)
    evidence.update(status=status,checks=checks,error=error,executed_checks=len(checks),
                    passed_checks=sum(c['status']=='passed' for c in checks),
                    source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in ROOT.rglob('*.py') if '.venv' not in p.parts})
    (output/'browser-results.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    (output/'Browser-Validation-Report.md').write_text('# Phase 3 Windows Chrome Validation\n\n'
        +f"Status: **{status}**\n\nExecuted checks: {len(checks)}; passed: {evidence['passed_checks']}.\n\n"
        +('Error: '+error+'\n\n' if error else '')
        +'This run uses controlled in-memory responses, not a live client site. Unexecuted checks are not passed. '
        +'Review the six normal viewport screenshots manually before acceptance.\n\n'
        +'\n'.join('- '+c['name']+': '+c['status'] for c in checks),encoding='utf-8')
    print(f"Status: {status}; executed: {len(checks)}; passed: {evidence['passed_checks']}")
    return 0 if status=='passed' else 1


if __name__=='__main__':
    if sys.argv[1:]==['--hang-worker']:
        json.load(sys.stdin)
        print(json.dumps(run_fixture('hang')[0]))
    else:
        parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
        sys.exit(main(parser.parse_args().output))
