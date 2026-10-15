"""Controlled Chrome checks through the production C2B parent/worker boundary.

Loopback DNS permission is confined to this explicit test worker. Production
workers have no fixture flag, injected transport or network-policy relaxation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time
import uuid
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import browser_supervision as bs
import common
from client_workflow import build_delivery,delivery_files
from link_diagnostics import analyze_links,coverage_note
from test_http_link_integration import ControlledSite,FixtureHandler
from test_regressions import discovery


HARD_DEADLINE_SECONDS=10
HANG_NAVIGATION_MS=30000  # Real default navigation budget; outer deadline must win.
LOOP_MARKER='C2B_INFINITE_SCRIPT_STARTED'


def hard_deadline_observed(crawl, diagnostics, events):
    elapsed=diagnostics.get('elapsed_seconds',0)
    return (crawl['coverage']['stop_reason']=='execution_deadline'
        and diagnostics.get('stop_reason')=='execution_deadline'
        and diagnostics.get('deadline_seconds')==HARD_DEADLINE_SECONDS
        and HARD_DEADLINE_SECONDS-0.25<=elapsed<=HARD_DEADLINE_SECONDS+13
        and any(e['stage']=='infinite_script_started' for e in events)
        and any(e['stage']=='navigation_started' and e.get('timeout_ms')==HANG_NAVIGATION_MS for e in events))


def timeout_tree_observed(crawl, diagnostics, events):
    cleanup=diagnostics.get('cleanup') or {}
    before=cleanup.get('before') or {};after=cleanup.get('after') or {}
    launched=next((e for e in events if e['stage']=='secure_browser_started'),{})
    return (crawl.get('browser_supervision',{}).get('cleanup_confirmed') is True
        and cleanup.get('confirmed') is True and cleanup.get('method')=='windows_job'
        and before.get('membership_complete') is True and before.get('active_processes',0)>=3
        and diagnostics.get('worker_pid') in before.get('pids',[])
        and isinstance(launched.get('driver_pid'),int) and launched['driver_pid'] in before.get('pids',[])
        and after.get('available') is True and after.get('active_processes')==0
        and after.get('membership_complete') is True and after.get('pids')==[])


def fixture_worker(mode, events_path):
    request=json.load(sys.stdin)  # Job assigned before this gate opens.
    events=[];started=time.monotonic()
    def event(stage,**data):
        if len(events)>=64:return
        events.append(dict(stage=stage,worker_pid=os.getpid(),elapsed_seconds=round(time.monotonic()-started,6),**data))
        pending=events_path.with_suffix('.pending')
        pending.write_text(json.dumps(events,indent=2),encoding='utf-8');pending.replace(events_path)
    event('stdin_released')
    original=socket.getaddrinfo
    def dns(host,*a,**k):
        if host in ('audit.example.test','partner.example.test'):host='127.0.0.1'
        return original(host,*a,**k)
    launch=common._launch_browser
    def browser(p,*a,**k):
        b=launch(p,*a,**k)
        event('secure_browser_started',browser_version=b.version,driver_pid=p._impl_obj._connection._transport._proc.pid)
        if mode=='close-hang': b.close=lambda:time.sleep(60)
        return b
    def save(crawl):
        common._write_crawl_checkpoint(request['checkpoint'],crawl)
        if mode=='crash' and crawl['pages']:os._exit(7)
    loader=common.crawl_page_browser;observed=set()
    def navigate(page,url,**kw):
        if id(page) not in observed:
            observed.add(id(page))
            page.on('console',lambda message:event('infinite_script_started') if message.text==LOOP_MARKER else None)
        event('navigation_started',path=urlsplit(url).path,timeout_ms=kw.get('timeout'))
        try:return loader(page,url,**kw)
        except Exception as exc:event('navigation_failed',error_type=type(exc).__name__);raise
    with patch('socket.getaddrinfo',side_effect=dns),patch('safe_http._public_address',side_effect=lambda ip:ip=='127.0.0.1'),patch.object(common,'_launch_browser',side_effect=browser),patch.object(common,'crawl_page_browser',side_effect=navigate):
        common._crawl_site_local(request['url'],request['limit'],request['timeout'],True,save)
    print('crawl-complete',flush=True)


def main(output):
    output.mkdir(parents=True,exist_ok=True);checks=[];record={};status='blocked';error=''
    worker_runs=[];record['worker_runs']=worker_runs
    def check(name,value):
        checks.append(dict(name=name,status='passed' if value else 'failed'))
        print(name+': '+checks[-1]['status'],flush=True)
        (output/'progress.json').write_text(json.dumps(dict(checks=checks),indent=2),encoding='utf-8')
    original=FixtureHandler.do_GET
    def respond(h):
        path=urlsplit(h.path).path
        if path=='/hang':
            body=('<title>Hostile script</title><script>console.log("'+LOOP_MARKER+'");while(true){}</script>').encode()
        elif path=='/':
            body=(b'<title>Raw C2B</title><h1>Root</h1><a href="/old">Old</a><a href="/old">Old</a>'
                b'<a href="/a">Section</a><a href="/gone">Missing</a><a href="/away">Partner</a>'
                b'<script>document.title="Rendered C2B";document.body.insertAdjacentHTML("beforeend",\'<h2>JS heading</h2><a href="/js">JS link</a>\')</script>')
        elif path=='/js':body=b'<title>JS destination</title><h1>JS destination</h1>'
        else:return original(h)
        h.server.observed_requests.append((h.headers.get('Host',''),h.path))
        h.send_response(200);h.send_header('Content-Type','text/html');h.send_header('Content-Length',str(len(body)));h.end_headers();h.wfile.write(body)
    raw_popen=bs.subprocess.Popen
    def crawl(mode,url,limit=10,seconds=45,navigation_ms=5000):
        events_path=output/('worker-'+mode+'-'+uuid.uuid4().hex[:8]+'.json')
        diagnostic={};runner=bs.run_worker
        def popen(command,**kw):
            if command[-1:]==['--crawl-worker']:
                command=[sys.executable,str(Path(__file__).resolve()),'--fixture-worker',mode,str(events_path)]
            return raw_popen(command,**kw)
        def capture(*args,**kw):
            result=runner(*args,**kw);diagnostic.update(result.diagnostics);return result
        print(f'C2B case {mode} {urlsplit(url).path}: wall={seconds}s navigation={navigation_ms}ms',flush=True)
        with patch.object(bs.subprocess,'Popen',side_effect=popen),patch.object(bs,'run_worker',side_effect=capture):
            result=common.crawl_site(url,limit=limit,timeout=navigation_ms,wall_seconds=seconds)
        events=json.loads(events_path.read_text(encoding='utf-8')) if events_path.exists() else []
        entry=dict(mode=mode,path=urlsplit(url).path,navigation_ms=navigation_ms,wall_seconds=seconds,supervisor=diagnostic,events=events)
        worker_runs.append(entry)
        (output/'worker-diagnostics.json').write_text(json.dumps(worker_runs,indent=2),encoding='utf-8')
        print('C2B worker result: '+json.dumps(diagnostic),flush=True)
        return result
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=common._launch_browser(p);record['browser_version']=browser.version;browser.close()
        print('Secure Chrome available; production supervisor checks starting',flush=True)
        with patch.object(FixtureHandler,'do_GET',respond),ControlledSite() as site:
            normal=crawl('normal',site.base+'/');record['normal']=common._crawl_wire(normal)
            pages=normal['pages'];root=next((p for p in pages if p.crawl_depth==0),None)
            links=analyze_links(normal)
            target=next((r for r in links['inventory'] if r['URL']==site.base+'/target'),{})
            check('Supervised crawler renders JavaScript',normal['browser_used'] and not normal['browser_error'] and root is not None and root.title=='Rendered C2B')
            check('Rendered heading and internal link retained',root is not None and 'JS heading' in root.h2 and any(x['url']==site.base+'/js' for x in root.internal_links))
            check('Occurrences unique sources aliases retained',target.get('Observed link occurrences')==4 and target.get('Unique referring pages')==2)
            check('Depth and cross-host scope retained',any(p.crawl_depth==2 for p in pages) and bool(normal['coverage']['out_of_scope_redirects']) and not any('partner.' in p.final_url for p in pages))
            check('Broken source target status evidence retained',any(x['Target']==site.base+'/gone' and x['Status']==404 for x in links['edges']))
            check('Normal worker cleanup confirmed',not normal.get('browser_supervision') and normal['coverage']['stop_reason']=='queue_exhausted_with_errors')
            short=crawl('normal',site.base+'/',limit=1)
            check('Page-limit remaining queue retained',short['coverage']['stop_reason']=='page_limit' and bool(short['coverage']['remaining_queue']))
            hang=crawl('normal',site.base+'/hang',seconds=HARD_DEADLINE_SECONDS,navigation_ms=HANG_NAVIGATION_MS);record['hang']=common._crawl_wire(hang)
            hang_run=worker_runs[-1]
            check('Infinite JavaScript hits hard deadline',hard_deadline_observed(hang,hang_run['supervisor'],hang_run['events']))
            check('Timed-out URL status remains unknown',hang['status_checks'] and hang['status_checks'][-1]['status'] is None and not hang['coverage']['observed_graph_complete'])
            check('Timeout Chrome driver tree cleanup confirmed',timeout_tree_observed(hang,hang_run['supervisor'],hang_run['events']))
            crash=crawl('crash',site.base+'/');record['crash']=common._crawl_wire(crash)
            check('Crash retains completed page evidence',crash['coverage']['stop_reason']=='worker_crashed' and len(crash['pages'])==1 and crash['pages'][0].title=='Rendered C2B')
            check('Crash remaining queue and partial coverage honest',bool(crash['coverage']['remaining_queue']) and not crash['coverage']['observed_graph_complete'] and 'incomplete' in coverage_note(crash))
            check('Crash Chrome driver tree cleanup confirmed',crash.get('browser_supervision',{}).get('cleanup_confirmed') is True)
            close=crawl('close-hang',site.base+'/',limit=1,seconds=10);record['close_hang']=common._crawl_wire(close)
            check('Hung browser close is bounded with pages retained',close['coverage']['stop_reason']=='execution_deadline' and len(close['pages'])==1)
            check('Hung-close tree cleanup confirmed',close.get('browser_supervision',{}).get('cleanup_confirmed') is True)
            # Interrupt the parent after its owned worker has actually launched Chrome.
            cleaned=[];cleanup=bs.cleanup_tree;interrupt_ready=[]
            def interrupt_popen(command,**kw):
                if command[-1:]==['--crawl-worker']:
                    command=[sys.executable,str(Path(__file__).resolve()),'--fixture-worker','normal',str(output/'worker-interruption.json')]
                    process=raw_popen(command,**kw);communicate=process.communicate
                    def interrupt(input=None,timeout=None):
                        if input is None:return communicate(timeout=timeout)
                        request=json.loads(input);process.stdin.write(input);process.stdin.close();process.stdin=None
                        end=time.monotonic()+7
                        while time.monotonic()<end:
                            try:
                                if json.loads(Path(request['checkpoint']).read_text())['browser_used']:
                                    interrupt_ready.append(True);raise KeyboardInterrupt
                            except (OSError,ValueError,KeyError):pass
                            time.sleep(0.05)
                        raise RuntimeError('Interrupted Chrome fixture did not launch; check unexecuted')
                    process.communicate=interrupt
                    return process
                return raw_popen(command,**kw)
            def cleanup_record(process,job=None):
                result=cleanup(process,job);cleaned.append(result);return result
            interrupted=False
            with patch.object(bs.subprocess,'Popen',side_effect=interrupt_popen),patch.object(bs,'cleanup_tree',side_effect=cleanup_record):
                try:common.crawl_site(site.base+'/hang',wall_seconds=20)
                except KeyboardInterrupt:interrupted=True
            check('Parent interruption propagates after real Chrome launch',interrupted and interrupt_ready==[True])
            check('Interrupted Chrome driver tree cleanup confirmed',cleaned==[True])
            files=delivery_files(build_delivery(site.base,crawl=crash,discovery=discovery()))
            check('Nine default exports preserved for partial crawl',len(files)==9)
            check('Partial-crawl report and evidence carry lifecycle warning',b'Browser execution stopped' in files['client-report.html'] and 'browser_supervision' in json.loads(files['evidence.json']))
            (output/'client-report.html').write_bytes(files['client-report.html'])
            (output/'client-report.pdf').write_bytes(files['client-report.pdf'])
            (output/'complete-audit.html').write_text(common.html_report(site.base,crash,[]),encoding='utf-8')
        with sync_playwright() as p:
            browser=common._launch_browser(p)
            try:
                for width,label in [(1440,'desktop'),(360,'mobile')]:
                    context=browser.new_context(viewport=dict(width=width,height=900),accept_downloads=False)
                    try:
                        page=context.new_page()
                        # Offline report inspection: no subresource or remote requests.
                        context.route('**/*',lambda route:route.abort())
                        for name in ['client-report','complete-audit']:
                            page.set_content((output/(name+'.html')).read_text(encoding='utf-8'))
                            overflow=page.evaluate('document.documentElement.scrollWidth > window.innerWidth + 1')
                            check(label+' '+name+' no horizontal overflow',not overflow)
                            page.screenshot(path=str(output/(label+'-'+name+'.png')),full_page=False)
                    finally:context.close()
            finally:browser.close()
        status='passed' if checks and all(x['status']=='passed' for x in checks) else 'failed'
    except Exception as exc:
        error=type(exc).__name__+': '+str(exc);status='failed' if checks else 'blocked'
    record.update(status=status,error=error,checks=checks,executed_checks=len(checks),passed_checks=sum(x['status']=='passed' for x in checks),
        source_sha256={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.rglob('*.py') if '.venv' not in p.parts})
    (output/'browser-results.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    (output/'Browser-Validation-Report.md').write_text('# C2B Chrome Lifecycle Validation\n\n'+f'Status: {status}. Executed: {len(checks)}. Passed: {record["passed_checks"]}.\n\n'+error+'\n\n'
        +'Controlled test worker only. Review four normal viewport report screenshots. C3 containment is not certified.\n\n'+'\n'.join('- '+x['name']+': '+x['status'] for x in checks),encoding='utf-8')
    print(f'Status: {status}; executed: {len(checks)}; passed: {record["passed_checks"]}',flush=True)
    return 0 if status=='passed' else 1


if __name__=='__main__':
    if sys.argv[1:2]==['--fixture-worker']:fixture_worker(sys.argv[2],Path(sys.argv[3]))
    else:
        parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
        sys.exit(main(parser.parse_args().output))
