import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rendering_diagnostics as rd

BASE = 'https://example.test/'
RAW = '''<!doctype html><html><head><title>Raw title</title>
<meta name="description" content="Raw description"><link rel="canonical" href="/raw/">
<meta name="robots" content="noindex, follow"></head><body><nav>Navigation</nav>
<main><h1>Original heading</h1><h2>Keep</h2><h2>Remove</h2><p>Original body.</p>
<a href="/kept/">Keep link</a><a href="/kept/">Keep link</a><a href="/removed">Remove link</a></main></body></html>'''
DOM = '''<html><head><title>Rendered title</title><meta name="description" content="Rendered description">
<link rel="canonical" href="/final/"><meta name="robots" content="index, follow"></head><body>
<main><h1>New heading</h1><h2>Keep</h2><h2>Added</h2><p>New body.</p>
<a href="/kept/">Keep link</a><a href="/added?x=1">New link</a></main></body></html>'''


def result():
    raw, dom = rd.snapshot(RAW, BASE), rd.snapshot(DOM, BASE)
    r = rd.unavailable(BASE, '')
    r.update(status='Compared (limited snapshot)', comparison_available=True, raw=raw, rendered=dom,
             rows=rd.compare_snapshots(raw, dom), warnings=[], final_url=BASE, browser_url=BASE)
    return r


class SnapshotTests(unittest.TestCase):
    def rows(self, raw=RAW, dom=DOM):
        return {r['Element']: r for r in rd.compare_snapshots(rd.snapshot(raw, BASE), rd.snapshot(dom, BASE))}

    def test_metadata_and_canonical_changed(self):
        r = self.rows()
        for name in ['Title', 'Meta description', 'Canonical']:
            self.assertEqual(r[name]['Change'], 'Changed')
        self.assertIn('/final/', r['Canonical']['Added'])

    def test_added_removed_and_unchanged(self):
        r = self.rows('<h1>Present</h1>', '<h2>New</h2>')
        self.assertEqual(r['H1']['Change'], 'Removed')
        self.assertEqual(r['H2']['Change'], 'Added')
        self.assertEqual(r['Canonical']['Change'], 'Unchanged in snapshot')

    def test_duplicate_headings_preserved(self):
        r = self.rows('<h2>A</h2><h2>A</h2>', '<h2>A</h2>')['H2']
        self.assertEqual(json.loads(r['Removed']), ['A'])

    def test_heading_reorder_is_changed_without_invented_pairing(self):
        r = self.rows('<h1>A</h1><h1>B</h1>', '<h1>B</h1><h1>A</h1>')['H1']
        self.assertEqual(r['Change'], 'Changed'); self.assertEqual(r['Added'], '[]')

    def test_link_occurrences_and_anchor_changes(self):
        r = self.rows()['Internal links']
        removed = [json.loads(x) for x in json.loads(r['Removed'])]
        self.assertEqual(len(removed), 2)
        self.assertTrue(any(x['url'] == BASE+'kept/' for x in removed))
        r = self.rows('<a href="/a">Old</a>', '<a href="/a" rel="nofollow">New</a>')['Internal links']
        self.assertEqual(r['Change'], 'Changed'); self.assertIn('nofollow', r['Added'])

    def test_link_identity_scope_base_and_credentials(self):
        s = rd.snapshot('<base href="/dir/"><a href="a/">A</a><a href="a">B</a><a href="a?q=1">C</a>'
                        '<a href="https://partner.test/a">External</a><a href="https://u:secret@example.test/a">Bad</a>', BASE)
        links = s['fields']['Internal links']['values']
        self.assertEqual(len(links), 3); self.assertIn('/dir/a/', links[0]); self.assertNotIn('secret', str(s))

    def test_generic_bot_and_shared_http_directives(self):
        s = rd.snapshot('<meta name="robots" content="none"><meta name="googlebot" content="noindex">', BASE, {'x-robots-tag':'noindex'})
        self.assertEqual(s['fields']['Indexability directives']['count'], 3)
        self.assertIn('shared response', str(s))

    def test_main_text_heuristic_excludes_navigation_scripts_hidden(self):
        s = rd.snapshot('<body><nav>Not main</nav><main><p>Visible words</p><p hidden>Hidden</p><script>code()</script></main></body>', BASE)
        self.assertEqual(s['fields']['Main textual content']['values'], ['Visible words'])
        self.assertEqual(s['content_region'], 'main')

    def test_long_text_difference_beyond_excerpt_detected(self):
        r = self.rows('<main>'+'a'*3000+'old</main>', '<main>'+'a'*3000+'new</main>')['Main textual content']
        self.assertEqual(r['Change'], 'Changed')
        self.assertEqual(json.loads(r['Raw'])['values'], json.loads(r['Rendered'])['values'])
        self.assertTrue(json.loads(r['Raw'])['excerpt_shortened'])

    def test_extraction_limit_not_false_unchanged(self):
        r = self.rows('<h1>A</h1>'*201, '<h1>A</h1>'*201)['H1']
        self.assertEqual(r['Change'], 'Not assessed (extraction limit)')
        self.assertEqual(len(json.loads(r['Raw'])['values']), 200)

    def test_dom_byte_limit(self):
        with self.assertRaises(ValueError): rd.snapshot('x'*(rd.LIMITS['resource_bytes']+1), BASE)

    def test_explicit_http_charset_used(self):
        s=rd.snapshot('<title>Caf\u00e9</title>'.encode('iso-8859-1'),BASE,{'content-type':'text/html; charset=iso-8859-1'})
        self.assertEqual(s['fields']['Title']['values'], ['Caf\u00e9'])

    def test_failure_never_becomes_removed_elements(self):
        r = rd.unavailable(BASE, 'Browser missing')
        self.assertFalse(r['comparison_available']); self.assertEqual(r['rows'], [])


class TransportTests(unittest.TestCase):
    def response(self, code=200, body=b'<html/>', headers=None, url=BASE):
        r = Mock(status_code=code, url=url, headers=headers or {'Content-Type':'text/html'})
        r.__enter__ = Mock(return_value=r); r.__exit__ = Mock(return_value=False)
        r.iter_content.return_value = [body]
        return r

    def transport(self):
        t = rd.BoundedTransport(BASE); t.session.close(); t.session = Mock(); return t

    def test_redirect_each_hop_and_identity(self):
        t = self.transport(); t.session.get.side_effect = [self.response(302, headers={'Location':'/final/'}), self.response(url=BASE+'final/')]
        with patch.object(rd, 'public_dns') as dns: r = t.get(BASE)
        self.assertEqual(r['url'], BASE+'final/'); self.assertEqual(len(r['redirects']), 1); self.assertEqual(dns.call_count, 0); self.assertEqual(t.session.get.call_count, 2)
        self.assertFalse(t.session.get.call_args.kwargs['allow_redirects'])

    def test_cross_host_redirect_stopped_before_second_request(self):
        t = self.transport(); t.session.get.return_value = self.response(302, headers={'Location':'https://partner.test/'})
        with patch.object(rd, 'public_dns'), self.assertRaises(ValueError): t.get(BASE)
        self.assertEqual(t.session.get.call_count, 1)

    def test_private_mixed_dns_rejected(self):
        rows = [(None,None,None,None,('93.184.216.34',443)), (None,None,None,None,('127.0.0.1',443))]
        with patch.object(rd.socket, 'getaddrinfo', return_value=rows), self.assertRaises(ValueError): rd.public_dns(BASE)

    def test_request_limit(self):
        t=self.transport(); t.requests=rd.LIMITS['requests']
        with self.assertRaises(ValueError): t.get(BASE)
        t.session.get.assert_not_called()

    def test_aggregate_byte_limit(self):
        t=self.transport(); t.bytes=rd.LIMITS['total_bytes']-1; t.session.get.return_value=self.response(body=b'xx')
        with patch.object(rd, 'public_dns'), self.assertRaises(ValueError): t.get(BASE)

    def test_single_response_limit(self):
        t=self.transport(); t.session.get.return_value=self.response(body=b'x'*(rd.LIMITS['resource_bytes']+1))
        with patch.object(rd, 'public_dns'), self.assertRaises(ValueError): t.get(BASE)

    def test_deadline(self):
        t=self.transport(); t.started -= rd.LIMITS['network_seconds']+1
        with self.assertRaises(ValueError): t.get(BASE)
        t.session.get.assert_not_called()

    def test_proxy_and_netrc_not_inherited(self):
        t=rd.BoundedTransport(BASE)
        try: self.assertFalse(t.session.trust_env)
        finally: t.close()

    def test_invalid_urls_do_not_start_worker(self):
        for url in ['http://127.0.0.1/', 'http://localhost/', 'https://u:secret@example.test/', 'file:///etc/passwd', 'http://2130706433/']:
            with self.subTest(url=url), patch.object(rd.subprocess, 'Popen') as process:
                r=rd.compare_url(url); process.assert_not_called(); self.assertFalse(r['comparison_available']);self.assertNotIn('secret',str(r))

    def test_worker_failure_reported(self):
        with patch.object(rd.subprocess, 'Popen') as process, patch('browser_supervision.WindowsJob'):
            process.return_value.communicate.return_value=('invalid',None);process.return_value.returncode=1
            self.assertFalse(rd.compare_url(BASE)['comparison_available'])

    def test_worker_timeout_kills_process_group(self):
        import browser_supervision as bs
        with patch.object(bs.os, 'name', 'posix'), patch.object(bs.subprocess, 'Popen') as process, patch.object(bs.os, 'killpg', create=True) as kill, patch.object(bs.signal, 'SIGKILL', 9, create=True), patch.object(bs, '_group_empty', return_value=True), patch.object(bs, '_host_group', return_value=None):
            process.return_value.pid=123
            process.return_value.communicate.side_effect=[subprocess.TimeoutExpired('worker',45),('',None)]
            result=bs.run_worker(['worker'],'{}',45)
            kill.assert_called_once(); self.assertEqual(result.reason,'execution_deadline')
            # A root-group mock alone cannot confirm detached browser descendants.
            self.assertFalse(result.cleanup_confirmed)

    def test_windows_timeout_requests_process_tree_cleanup(self):
        import browser_supervision as bs
        from browser_supervision import WorkerResult
        # The platform-specific Job Object path is tested by supervisor tests.
        with patch.object(bs, 'run_worker', return_value=WorkerResult(reason='execution_deadline', cleanup_confirmed=True)) as worker:
            r=rd.compare_url(BASE)
        self.assertEqual(worker.call_args.args[2],45)
        self.assertFalse(r['comparison_available']); self.assertNotIn('cleanup could not', str(r['warnings']))


class RouteTests(unittest.TestCase):
    def route(self, url=BASE, kind='document', method='GET'):
        route=Mock();route.request=SimpleNamespace(url=url,resource_type=kind,method=method,frame=SimpleNamespace(parent_frame=None));return route

    def broker(self):
        initial=dict(url=BASE,status=200,body=RAW.encode(),headers={'content-type':'text/html'},redirects=[])
        return rd.ReplayRoutes(initial,Mock())

    def test_document_is_same_bytes_and_never_direct_network(self):
        b=self.broker();r=self.route();b.handle(r)
        self.assertEqual(r.fulfill.call_args.kwargs['body'],RAW.encode());r.continue_.assert_not_called();b.transport.get.assert_not_called()
        self.assertIn("worker-src 'none'",r.fulfill.call_args.kwargs['headers']['content-security-policy'])

    def test_dangerous_requests_blocked(self):
        for url,kind,method in [('https://other.test/a','script','GET'),('http://127.0.0.1/','fetch','GET'),(BASE,'xhr','POST'),(BASE,'image','GET'),(BASE,'websocket','GET')]:
            b=self.broker();r=self.route(url,kind,method);b.handle(r)
            r.abort.assert_called_once();r.continue_.assert_not_called();b.transport.get.assert_not_called()

    def test_second_navigation_is_not_replayed_as_original(self):
        b=self.broker();b.handle(self.route());r=self.route(BASE+'other');b.handle(r)
        r.abort.assert_called_once();self.assertTrue(b.navigation_blocked)

    def test_cross_origin_client_navigation_invalidates_pair(self):
        b=self.broker();b.handle(self.route());r=self.route('https://foreign.test/');b.handle(r)
        self.assertTrue(b.navigation_blocked);r.abort.assert_called_once()

    def test_subresource_redirect_not_replayed_with_wrong_base(self):
        b=self.broker();b.transport.get.return_value=dict(status=200,headers={},body=b'code()',redirects=[{'url':BASE,'status':302}])
        r=self.route(BASE+'app.js','script');b.handle(r);r.abort.assert_called_once()

    def test_allowed_script_is_brokered(self):
        b=self.broker();b.transport.get.return_value=dict(status=200,headers={'content-type':'text/javascript'},body=b'code()',redirects=[])
        r=self.route(BASE+'app.js','script');b.handle(r);b.transport.get.assert_called_once_with(BASE+'app.js');r.fulfill.assert_called_once()

    def test_request_budget_blocks_without_fetch(self):
        b=self.broker();b.attempts=40;r=self.route(BASE+'app.js','script');b.handle(r);r.abort.assert_called_once();b.transport.get.assert_not_called()


class CaptureTests(unittest.TestCase):
    def capture(self, html=DOM, page_url=BASE, failure=None, event=None, content_type='text/html', status=200):
        initial=dict(url=BASE,status=status,body=RAW.encode(),headers={'content-type':content_type},redirects=[])
        transport=SimpleNamespace(get=Mock(return_value=initial),requests=1,bytes=len(RAW.encode()))
        browser=Mock(version='controlled-browser-api');page=browser.new_context.return_value.new_page.return_value
        page.content.return_value=html;page.url=page_url;page.evaluate.return_value=0
        if event:page.on.side_effect=lambda name,cb:cb(Mock()) if name==event else None
        with patch('playwright.sync_api.sync_playwright'),patch.object(rd,'_launch_browser',return_value=browser,side_effect=failure):
            out=rd._compare_page(BASE,transport)
        return out,browser

    def test_paired_capture_api_and_secure_context_options(self):
        out,browser=self.capture();self.assertTrue(out['comparison_available']);self.assertEqual(len(out['rows']),8)
        self.assertIn('raw_html_sha256',out);self.assertIn('rendered_dom_sha256',out)
        config=browser.new_context.call_args.kwargs
        self.assertFalse(config['ignore_https_errors']);self.assertEqual(config['service_workers'],'block');self.assertFalse(config['accept_downloads'])
        browser.close.assert_called_once()

    def test_launch_failure_keeps_raw_evidence_without_false_comparison(self):
        out,_=self.capture(failure=RuntimeError('sensitive details must not leak'))
        self.assertFalse(out['comparison_available']);self.assertIsNotNone(out['raw']);self.assertEqual(out['rows'],[])
        self.assertIn('Browser launch failed',str(out['warnings']));self.assertNotIn('sensitive',str(out))

    def test_capture_rejects_oversized_dom(self):
        out,browser=self.capture(html='x'*(rd.LIMITS['resource_bytes']+1))
        self.assertFalse(out['comparison_available']);browser.close.assert_called_once()

    def test_url_change_is_not_a_valid_pair(self):
        out,_=self.capture(page_url=BASE+'changed');self.assertFalse(out['comparison_available']);self.assertEqual(out['rows'],[])

    def test_non_html_and_http_errors_not_compared(self):
        for kwargs in [dict(content_type='application/json'),dict(status=404)]:
            out,browser=self.capture(**kwargs);self.assertFalse(out['comparison_available']);browser.new_context.assert_not_called()

    def test_script_error_warning(self):
        out,_=self.capture(event='pageerror');self.assertTrue(any('Script execution errors' in x for x in out['warnings']))

    def test_pending_request_warning(self):
        out,_=self.capture(event='request');self.assertTrue(any('pending' in x for x in out['warnings']))

    def test_initial_noindex_remains_caution_even_when_removed(self):
        out,_=self.capture();self.assertTrue(any('Raw noindex' in x for x in out['warnings']))


if __name__ == '__main__': unittest.main()
