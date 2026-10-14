"""Explicit Windows/Chrome C2A checks; absent browser means blocked, zero passes."""
import argparse
import base64
import hashlib
import faulthandler
import time
import traceback
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch
from urllib.parse import urlsplit

if __name__=='__main__':
    print('C2A harness process started',flush=True)

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import browser_isolation as bi
import common
from link_diagnostics import analyze_links
from client_workflow import build_delivery, delivery_files
from test_regressions import discovery
from test_http_link_integration import ControlledSite, FixtureHandler


def main(output):
    output.mkdir(parents=True,exist_ok=True);checks=[];evidence={};status='blocked';error=''
    started=time.monotonic();history=[]
    def stage(name):
        entry=dict(stage=name,elapsed_seconds=round(time.monotonic()-started,3))
        history.append(entry)
        print(f"C2A stage: {name} ({entry['elapsed_seconds']}s)",flush=True)
        (output/'progress.json').write_text(json.dumps(dict(status='running',stage=name,history=history,
            checks=checks,executed_checks=len(checks),passed_checks=sum(x['status']=='passed' for x in checks)),indent=2),encoding='utf-8')
    def check(name,ok):
        checks.append(dict(name=name,status='passed' if ok else 'failed'))
        stage('Check: '+name+' = '+checks[-1]['status'])
    stack=(output/'thread-stacks.log').open('w',encoding='utf-8')
    faulthandler.dump_traceback_later(30,repeat=True,file=stack)
    stage('Harness initialized; secure browser probe starting')
    original=FixtureHandler.do_GET
    def respond(h):
        port=h.server.server_port;path=urlsplit(h.path).path
        bodies={
            '/app.js':('text/javascript', """document.title='C2A rendered';
fetch('/api').then(r=>r.json()).then(d=>{document.body.insertAdjacentHTML('beforeend',d.html)});
fetch('http://127.0.0.1:1/forbidden').catch(()=>{});
fetch('http://private.example.test:PORT/forbidden').catch(()=>{});
fetch('http://mixed.example.test:PORT/forbidden').catch(()=>{});
fetch('/post',{method:'POST'}).catch(()=>{});
fetch('/redirect-resource').catch(()=>{});
fetch('/attachment').catch(()=>{});
try { new WebSocket('ws://127.0.0.1:1/forbidden'); } catch(e) {}
try { new Worker('/worker.js'); } catch(e) {}
try { window.open('/popup'); } catch(e) {}
""".replace('PORT',str(port))),
            '/cdn.js':('text/javascript', "window.__publicCDN = true;"),
            '/api':('application/json',json.dumps(dict(html='<h2>JavaScript content</h2><a href="/js-only">JS link</a>'))),
            '/js-only':('text/html','<title>JS page</title><h1>JavaScript destination</h1>'),
            '/attachment':('text/plain','Synthetic attachment'),
            '/root-image.png':('image/png',base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD0sAAAAASUVORK5CYII=')),
        }
        if path=='/':
            bodies['/']=('text/html', '<!doctype html><title>C2A raw</title><h1>Controlled audit</h1>'+
                '<a href="/old">Target</a>'*3+'<a href="/a">Section</a><a href="/gone">Missing</a><a href="/away">Partner</a>'+
                '<img src="/root-image.png" alt="Fixture"><iframe src="/frame"></iframe>'+
                '<script src="http://private.example.test:'+str(port)+'/forbidden"></script><script src="http://mixed.example.test:'+str(port)+'/forbidden"></script>'+
                '<script src="/app.js"></script><script src="http://partner.example.test:'+str(port)+'/cdn.js"></script>')
        if path=='/redirect-resource':
            h.server.observed_requests.append((h.headers.get('Host',''),h.path));h.send_response(302)
            h.send_header('Location','http://127.0.0.1:1/forbidden');h.send_header('Content-Length','0');h.end_headers();return
        if path not in bodies:return original(h)
        h.server.observed_requests.append((h.headers.get('Host',''),h.path));kind,body=bodies[path]
        data=body if isinstance(body,bytes) else body.encode();h.send_response(200)
        h.send_header('Content-Type',kind);h.send_header('Content-Length',str(len(data)))
        if path=='/attachment':h.send_header('Content-Disposition','attachment; filename=fixture.txt')
        h.end_headers();h.wfile.write(data)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=bi.launch_browser(p);evidence['browser_version']=browser.version;stage('Secure browser probe launched');browser.close();stage('Secure browser probe closed')
        stage('Controlled server starting')
        with patch.object(FixtureHandler,'do_GET',respond),ControlledSite() as site:
            stage('Controlled server running')
            dns=socket.getaddrinfo
            def resolve(host,*a,**kw):
                if host=='private.example.test':return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('10.0.0.1',site.server.server_port))]
                if host=='mixed.example.test':return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',site.server.server_port)),(socket.AF_INET,socket.SOCK_STREAM,6,'',('10.0.0.1',site.server.server_port))]
                return dns(host,*a,**kw)
            with patch('socket.getaddrinfo',side_effect=resolve):
                captured=[];loader=common.crawl_page_browser
                def inspect(page,url,**kw):
                    stage('Page extraction starting: '+urlsplit(url).path)
                    audit=loader(page,url,**kw)
                    stage('Page extraction completed: '+urlsplit(url).path)
                    if url.rstrip('/')==site.base:captured.append(page.evaluate('window.__publicCDN === true'))
                    return audit
                route_handler=bi.GetBroker.handle
                def traced_route(b,route):
                    stage('Route starting: '+route.request.resource_type+' '+urlsplit(route.request.url).path)
                    try:return route_handler(b,route)
                    finally:stage('Route completed: '+route.request.resource_type+' '+urlsplit(route.request.url).path)
                stage('Normal crawler starting')
                with patch.object(common,'crawl_page_browser',side_effect=inspect),patch.object(bi.GetBroker,'handle',traced_route):
                    crawl=common.crawl_site(site.base+'/',limit=10)
                stage('Normal crawler completed')
            links=analyze_links(crawl);security=crawl.get('browser_security',{});evidence['crawl_security']=security;evidence['coverage']=crawl['coverage'];evidence['requests']=site.server.observed_requests
            pages=crawl['pages'];root=next((p for p in pages if p.final_url==site.base+'/'),None)
            check('Normal crawler uses real browser',crawl['browser_used'] and not crawl['browser_error'])
            check('JavaScript title rendered',root is not None and root.title=='C2A rendered')
            check('JavaScript heading and internal link captured',root is not None and 'JavaScript content' in root.h2 and any('/js-only' in x['url'] for x in root.internal_links))
            check('Public cross-host CDN script executed',captured==[True])
            check('Image evidence preserved',root is not None and any('/root-image.png' in x['src'] for x in root.images))
            target=next((x for x in links['inventory'] if x['URL']==site.base+'/target'),{})
            check('Phase 1 occurrences and unique referring pages preserved',target.get('Observed link occurrences')==5 and target.get('Unique referring pages')==2)
            check('Redirect alias and depth preserved',target.get('Observed seed-relative depth')==1 and any(p.url==site.base+'/old' and p.redirect_chain[0]['status']==301 for p in pages))
            deep=next((p for p in pages if p.final_url==site.base+'/deep'),None)
            check('Depth two preserved',deep is not None and deep.crawl_depth==2)
            check('Cross-host final excluded from graph',not any('partner.example.test' in p.final_url for p in pages) and bool(crawl['coverage']['out_of_scope_redirects']))
            check('Broken-link source target evidence retained',any(x['Source']==site.base+'/' and x['Target']==site.base+'/gone' and x['Status']==404 for x in links['edges']))
            blocked=security.get('blocked',{})
            check('WebSocket explicitly blocked',blocked.get('WebSocket blocked',0)>0)
            check('Non-GET explicitly blocked',blocked.get('Non-GET request blocked',0)>0)
            check('Redirected subresource not replayed',any('Redirected subresource' in reason for reason in blocked))
            check('Attachment download blocked',blocked.get('Download response blocked',0)>0)
            observed=[path for _,path in site.server.observed_requests]
            check('Private mixed DNS frame popup worker and POST targets not fetched',not any(urlsplit(p).path in ['/forbidden','/frame','/popup','/worker.js','/post'] for p in observed))
            check('Restricted render explicit and graph incomplete',security.get('partial_render') and not crawl['coverage']['observed_graph_complete'])
            check('Blocked requests remain unknown in resource evidence',any(x['status'] is None for x in security.get('resources',[])))
            stage('Truncated crawl starting')
            truncated=common.crawl_site(site.base+'/',limit=1)
            stage('Truncated crawl completed')
            check('Page limit and remaining queue evidence preserved',truncated['coverage']['stop_reason']=='page_limit' and bool(truncated['coverage']['remaining_queue']))
            stage('Report generation starting')
            pack=build_delivery(site.base,crawl=crawl,discovery=discovery());files=delivery_files(pack)
            check('Nine default exports retained',len(files)==9)
            check('Client report warns partial rendering',b'Browser rendering is partial' in files['client-report.html'])
            (output/'client-report.html').write_bytes(files['client-report.html']);(output/'client-report.pdf').write_bytes(files['client-report.pdf'])
            (output/'complete-audit.html').write_text(common.html_report(site.base,crawl,[]),encoding='utf-8')
            stage('Report browser starting')
            with sync_playwright() as p:
                browser=bi.launch_browser(p)
                stage('Report browser launched')
                try:
                    for name,width,height in [('desktop',1440,900),('mobile',360,800)]:
                        stage(name+' report viewport starting')
                        context=browser.new_context(viewport=dict(width=width,height=height),service_workers='block',accept_downloads=False)
                        page=context.new_page();page.goto((output/'client-report.html').resolve().as_uri())
                        check(name+' partial-render warning readable in report',page.locator('body').inner_text().find('Browser rendering is partial')>=0)
                        check(name+' report no horizontal page overflow',page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                        page.get_by_text('Browser rendering is partial',exact=False).first.scroll_into_view_if_needed()
                        page.screenshot(path=str(output/(name+'-partial-client.png')),full_page=False)
                        page.goto((output/'complete-audit.html').resolve().as_uri());page.get_by_role('heading',name='Site Coverage',exact=True).scroll_into_view_if_needed()
                        check(name+' Complete Audit no horizontal page overflow',page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                        page.screenshot(path=str(output/(name+'-partial-complete.png')),full_page=False);context.close()
                finally:
                    stage('Report browser closing')
                    browser.close()
                    stage('Report browser closed')
        stage('Controlled server closed')
        status='passed' if all(c['status']=='passed' for c in checks) else 'failed'
    except Exception as exc:
        error=type(exc).__name__+': '+str(exc);status='failed' if checks else 'blocked'
        traceback.print_exc()
        stage('Harness exception: '+type(exc).__name__)
    faulthandler.cancel_dump_traceback_later();stack.close()
    evidence.update(history=history,status=status,error=error,checks=checks,executed_checks=len(checks),passed_checks=sum(x['status']=='passed' for x in checks),
        source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.rglob('*.py') if '.venv' not in p.parts})
    (output/'browser-results.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    (output/'Browser-Validation-Report.md').write_text('# C2A Browser Validation\n\nStatus: '+status+'\n\n'+error+'\n\n'+'\n'.join('- '+x['name']+': '+x['status'] for x in checks)+'\n\nApplication/fixture observations only; no OS egress containment certification. Review four additional screenshots.',encoding='utf-8')
    (output/'progress.json').write_text(json.dumps(dict(status=status,history=history,executed_checks=len(checks),passed_checks=evidence['passed_checks']),indent=2),encoding='utf-8')
    print(f'Status: {status}; executed: {len(checks)}; passed: {evidence["passed_checks"]}')
    return 0 if status=='passed' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    sys.exit(main(parser.parse_args().output))
