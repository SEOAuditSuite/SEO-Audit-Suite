"""Real HTTP tests on controlled pages; DNS mapping exists only inside this harness."""
import os
import socket
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import crawl_site, check_urls
from link_diagnostics import analyze_links, crawl_status_cache


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        host = self.headers.get('Host', '')
        path = urlsplit(self.path).path
        self.server.observed_requests.append((host, self.path))
        status, headers = 200, {}
        if host.startswith('partner.example.test:'):
            body = '<h1>External partner</h1><a href="/external-child">Must not enter the graph</a>'
        elif path == '/':
            body = ('<h1>Controlled audit fixture</h1>' + '<a href="/old">Target</a>' * 3 +
                    '<a href="/a">Section</a><a href="/gone">Missing page</a><a href="/away">Partner redirect</a>')
        elif path == '/old':
            status, headers, body = 301, {'Location':'/target'}, ''
        elif path == '/target':
            body = '<h1>Target</h1><a href="/target">Self link</a>'
        elif path == '/a':
            body = '<h1>Section</h1><a href="/target">Target</a><a href="/deep">Deep page</a>'
        elif path == '/deep':
            body = '<h1>Deep page</h1><p>Controlled depth-two content.</p>'
        elif path == '/away':
            status, headers, body = 302, {'Location':f'http://partner.example.test:{self.server.server_port}/landing'}, ''
        else:
            status, body = 404, '<h1>Not found</h1>'
        html = ('<!doctype html><html lang="en"><head><title>Controlled test page</title>'
                '<meta name="description" content="Synthetic fixture, not a real client result."></head><body>' + body + '</body></html>').encode()
        self.send_response(status)
        for k,v in headers.items(): self.send_header(k,v)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Content-Length',str(len(html)))
        self.end_headers()
        self.wfile.write(html)


class ControlledSite:
    def __enter__(self):
        self.server=ThreadingHTTPServer(('127.0.0.1',0),FixtureHandler)
        self.server.observed_requests=[]
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base=f'http://audit.example.test:{self.server.server_port}'
        original=socket.getaddrinfo
        def resolve(host,*args,**kwargs):
            if host in ('audit.example.test','partner.example.test'):
                host='127.0.0.1'
            return original(host,*args,**kwargs)
        self.dns=patch('socket.getaddrinfo',side_effect=resolve)
        self.env=patch.dict(os.environ,{'NO_PROXY':'*','no_proxy':'*'})
        self.public = patch('safe_http._public_address', side_effect=lambda value: value == '127.0.0.1')
        self.public.start(); self.dns.start(); self.env.start()
        return self

    def __exit__(self,*args):
        self.public.stop(); self.dns.stop(); self.env.stop()
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def run(self,limit=10):
        return crawl_site(self.base+'/',limit=limit,timeout=5000,prefer_browser=False)


class ControlledHTTPTests(unittest.TestCase):
    def test_real_http_counting_aliases_depth_scope_and_status_cache(self):
        with ControlledSite() as site:
            c=site.run()
            r=analyze_links(c)
            target=next(x for x in r['inventory'] if x['URL']==site.base+'/target')
            self.assertEqual(target['Observed link occurrences'],5)
            self.assertEqual(target['Unique referring pages'],2)
            self.assertEqual(target['Observed seed-relative depth'],1)
            deep=next(x for x in r['inventory'] if x['URL']==site.base+'/deep')
            self.assertEqual(deep['Observed seed-relative depth'],2)
            self.assertEqual(c['coverage']['pages_inspected'],4)
            self.assertEqual(c['coverage']['attempted_urls'],6)
            self.assertEqual(c['coverage']['stop_reason'],'queue_exhausted_with_errors')
            self.assertFalse(c['coverage']['full_site_complete'])
            self.assertEqual(len(c['coverage']['out_of_scope_redirects']),1)
            self.assertFalse(any('partner.example.test' in p.final_url for p in c['pages']))
            self.assertFalse(any('/external-child' in p for _,p in site.server.observed_requests))
            n=len(site.server.observed_requests)
            checks=check_urls([site.base+'/gone',site.base+'/old',site.base+'/target'],cached=crawl_status_cache(c))
            self.assertEqual(len(site.server.observed_requests),n)
            self.assertEqual(checks[0]['status'],404)
            gone=next(e for e in r['edges'] if e['Target']==site.base+'/gone')
            self.assertEqual(gone['Source'],site.base+'/')
            self.assertEqual(gone['Status'],404)
            self.assertEqual(gone['Final URL'],site.base+'/gone')
            away=next(e for e in r['edges'] if e['Target']==site.base+'/away')
            self.assertTrue(away['Redirect leaves audit scope'])
            self.assertEqual(away['Requested status'],302)

    def test_real_http_truncation_retains_unchecked_targets(self):
        with ControlledSite() as site:
            c=site.run(limit=2)
            self.assertEqual(c['coverage']['pages_inspected'],2)
            self.assertEqual(c['coverage']['stop_reason'],'page_limit')
            self.assertTrue(c['coverage']['remaining_queue'])
            self.assertFalse(c['coverage']['observed_graph_complete'])
            gone=next(e for e in analyze_links(c)['edges'] if e['Target']==site.base+'/gone')
            self.assertEqual(gone['Classification'],'not checked')


if __name__=='__main__':unittest.main()
