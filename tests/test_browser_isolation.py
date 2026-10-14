"""C2A policy/broker security, compatibility and evidence tests; no browser required."""
import ast
import copy
import os
from pathlib import Path
import socket
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from requests import Response
from requests.structures import CaseInsensitiveDict

import browser_isolation as bi
from common import HEADERS, crawl_site, overall_scores, html_report, _guard_browser_route
from link_diagnostics import coverage_note
from client_workflow import build_delivery, delivery_files
from test_regressions import fixture_page, discovery
from test_http_link_integration import ControlledSite

BASE='https://audit.example.test/'


def response(code=200,body=b'hello',headers=None,url=BASE):
    r=Response();r.status_code=code;r.url=url;r._content=body;r._content_consumed=True
    r.headers=CaseInsensitiveDict(headers or {'Content-Type':'text/html'})
    return r


def route(b,url=BASE,kind='script',method='GET',frame=None):
    r=Mock();r.request=SimpleNamespace(url=url,resource_type=kind,method=method,
        frame=frame or SimpleNamespace(page=b.page,parent_frame=None));return r


def broker(**limits):
    b=bi.GetBroker(HEADERS,limits);b.page=object();b.begin_navigation(BASE);return b


class PolicyTests(unittest.TestCase):
    def test_secure_context_tls_workers_downloads_proxy_and_init(self):
        browser=Mock();ctx=bi.secure_context(browser,user_agent='audit',viewport={'width':1440,'height':900})
        opts=browser.new_context.call_args.kwargs
        self.assertFalse(opts['ignore_https_errors']);self.assertFalse(opts['accept_downloads'])
        self.assertEqual(opts['service_workers'],'block');self.assertEqual(opts['permissions'],[])
        self.assertEqual(opts['proxy']['bypass'],'<-loopback>')
        ctx.route_web_socket.assert_called_once();ctx.add_init_script.assert_called_once()
        self.assertIn('WebTransport',ctx.add_init_script.call_args.args[0])
    def test_websocket_popups_downloads_close_and_record(self):
        browser=Mock();seen=[];ctx=bi.secure_context(browser,user_agent='x',viewport={},on_block=seen.append)
        ws=Mock();ctx.route_web_socket.call_args.args[1](ws);ws.close.assert_not_called()
        ws.connect_to_server.assert_not_called();bi.close_blocked_websockets(ctx);ws.close.assert_called_once()
        handler=ctx.on.call_args.args[1];first=Mock();second=Mock();handler(first);handler(second)
        first.close.assert_not_called();second.close.assert_called_once()
        download=Mock();first.on.call_args.args[1](download);download.cancel.assert_called_once()
        self.assertEqual(seen,['WebSocket blocked','Popup blocked','Download blocked'])
    def test_deferred_popup_close_does_not_wait_inside_event_dispatch(self):
        browser=Mock();events=[];ctx=bi.secure_context(browser,user_agent='x',viewport={},on_block=events.append,defer_popup_close=True)
        handler=ctx.on.call_args.args[1];first=Mock();popup=Mock();popup.is_closed.return_value=False
        dispatching=True
        def close():
            if dispatching:raise AssertionError('Reentrant close would wait on queued routing')
        popup.close.side_effect=close
        handler(first);handler(popup)
        popup.close.assert_not_called();self.assertEqual(events,['Popup blocked'])
        b=broker();r=route(b,BASE+'popup',frame=SimpleNamespace(page=popup,parent_frame=None));b.session.get=Mock()
        b.handle(r);r.abort.assert_called_once();b.session.get.assert_not_called()
        dispatching=False;bi.close_blocked_popups(ctx);popup.close.assert_called_once()
        self.assertEqual(ctx._seo_pending_popups,[])
    def test_deferred_closed_popup_is_not_closed_twice(self):
        browser=Mock();ctx=bi.secure_context(browser,user_agent='x',viewport={},defer_popup_close=True)
        handler=ctx.on.call_args.args[1];popup=Mock();popup.is_closed.return_value=True
        handler(Mock());handler(popup);bi.close_blocked_popups(ctx);popup.close.assert_not_called()

    def test_websocket_handler_returns_without_sync_api_or_server_connect(self):
        import asyncio
        browser=Mock();ctx=bi.secure_context(browser,user_agent='x',viewport={})
        ws=Mock();ws.close.side_effect=AssertionError('Sync close inside asyncio callback would deadlock')
        async def dispatch():
            ctx.route_web_socket.call_args.args[1](ws)
        asyncio.run(dispatch())
        ws.close.assert_not_called();ws.connect_to_server.assert_not_called()
        ws.close.side_effect=None;bi.close_blocked_websockets(ctx);ws.close.assert_called_once()
        bi.close_blocked_websockets(ctx);self.assertEqual(ws.close.call_count,1)
    def test_phase_three_has_no_inline_socket_close_override(self):
        import rendering_diagnostics as rd
        tree=ast.parse(Path(rd.__file__).read_text())
        capture=next(n for n in tree.body if getattr(n,'name',None)=='_compare_page')
        self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr=='route_web_socket' for n in ast.walk(capture)))
        self.assertTrue(any(isinstance(n,ast.Name) and n.id=='close_blocked_websockets' for n in ast.walk(capture)))

    def test_launch_never_drops_sandbox_or_inherits_credentials(self):
        p=Mock();p.chromium.launch.side_effect=[RuntimeError('first'),Mock()]
        with patch.dict(os.environ,{'API_KEY':'secret','HTTPS_PROXY':'secret'}):bi.launch_browser(p)
        self.assertEqual(p.chromium.launch.call_count,2)
        for call in p.chromium.launch.call_args_list:
            self.assertTrue(call.kwargs['chromium_sandbox']);self.assertNotIn('API_KEY',call.kwargs['env']);self.assertNotIn('HTTPS_PROXY',call.kwargs['env'])
    def test_launch_failure_no_insecure_fallback(self):
        p=Mock();p.chromium.launch.side_effect=RuntimeError('sensitive')
        with self.assertRaisesRegex(RuntimeError,'Secure browser'):bi.launch_browser(p)
        self.assertEqual(p.chromium.launch.call_count,2)
    def test_legacy_route_is_fail_closed(self):
        r=Mock();_guard_browser_route(r);r.abort.assert_called_once();r.continue_.assert_not_called()


class BrokerTests(unittest.TestCase):
    def test_public_cdn_types_use_c1_fulfill_and_strip_decoded_wire_headers(self):
        for kind in ['script','stylesheet','image','font','xhr','fetch']:
            with self.subTest(kind=kind):
                b=broker();b.session.get=Mock(return_value=response(headers={'Content-Type':'text/javascript','Content-Encoding':'gzip','Content-Length':'999','Set-Cookie':'secret'}))
                url = BASE+'api?token=secret' if kind in ('xhr','fetch') else 'https://cdn.example.test/resource?token=secret'
                r=route(b,url,kind);b.handle(r)
                r.fulfill.assert_called_once();r.abort.assert_not_called();r.continue_.assert_not_called();r.fetch.assert_not_called()
                self.assertFalse(b.session.get.call_args.kwargs['allow_redirects'])
                self.assertEqual(r.fulfill.call_args.kwargs['headers'],{'Content-Type':'text/javascript'})
                self.assertNotIn('secret',str(b.evidence()))
    def test_cross_origin_api_is_not_an_unrestricted_public_get_channel(self):
        for kind in ('xhr','fetch'):
            b=broker();b.session.get=Mock();r=route(b,'https://foreign.example.test/api',kind);b.handle(r)
            r.abort.assert_called_once();b.session.get.assert_not_called()
            self.assertIn('Cross-origin API',b.rows[-1]['result'])
    def test_final_navigation_origin_controls_api_scope(self):
        b=broker();b.session.get=Mock(side_effect=[response(301,headers={'Location':'https://www.audit.example.test/'}),response()])
        b.prepare_navigation(BASE);b.session.get=Mock(return_value=response());r=route(b,'https://www.audit.example.test/api','fetch');b.handle(r)
        r.fulfill.assert_called_once()

    def test_private_schemes_credentials_and_ambiguous_urls_abort_before_fetch(self):
        for url in ['http://127.0.0.1/','http://169.254.169.254/','http://[::1]/','http://2130706433/','file:///secret','ftp://host/','https://u:secret@audit.example.test/']:
            b=broker();b.session.get=Mock();r=route(b,url);b.handle(r)
            r.abort.assert_called_once();b.session.get.assert_not_called();self.assertIsNone(b.rows[0]['status']);self.assertTrue(b.evidence()['partial_render'])
    def test_non_get_frames_popup_worker_media_blocked(self):
        for kind,method,frame in [('fetch','POST',None),('document','GET',SimpleNamespace(page=object(),parent_frame=None)),('document','GET',SimpleNamespace(page=None,parent_frame=object())),('worker','GET',None),('media','GET',None)]:
            b=broker();b.session.get=Mock();r=route(b,BASE,kind,method,frame);b.handle(r)
            r.abort.assert_called_once();b.session.get.assert_not_called()
    def test_prepared_document_consumed_once_and_csp_preserved(self):
        b=broker();b.session.get=Mock(return_value=response(headers={'Content-Type':'text/html','Content-Security-Policy':"script-src 'self'"}))
        b.prepare_navigation(BASE);r=route(b,BASE,'document');b.handle(r)
        self.assertIn("script-src 'self'",r.fulfill.call_args.kwargs['headers']['content-security-policy'])
        self.assertIn("frame-src 'none'",r.fulfill.call_args.kwargs['headers']['content-security-policy'])
        self.assertEqual(b.session.get.call_count,1)
        second=route(b,BASE,'document');b.handle(second);second.abort.assert_called_once()
    def test_browser_idna_default_port_matches_exact_wire_path(self):
        b=broker();b.begin_navigation('https://bücher.example:443/café?x=%2f')
        b.session.get=Mock(return_value=response());b.prepare_navigation('https://bücher.example:443/café?x=%2f')
        r=route(b,'https://xn--bcher-kva.example/caf%C3%A9?x=%2f','document');b.handle(r)
        r.fulfill.assert_called_once()
    def test_navigation_key_does_not_conflate_trailing_slash_or_queries(self):
        self.assertNotEqual(bi._navigation_key(BASE+'a'),bi._navigation_key(BASE+'a/'))
        self.assertNotEqual(bi._navigation_key(BASE+'a?x=1'),bi._navigation_key(BASE+'a?x=2'))
        self.assertNotEqual(bi._navigation_key(BASE+'a?'),bi._navigation_key(BASE+'a'))

    def test_navigation_redirects_are_c1_resolved_with_true_final_base(self):
        b=broker();b.session.get=Mock(side_effect=[response(301,headers={'Location':'/final/'}),response(url=BASE+'final/')])
        final,chain=b.prepare_navigation(BASE);self.assertEqual(final,BASE+'final/');self.assertEqual(chain,[dict(url=BASE,status=301)])
        self.assertEqual(b.session.get.call_count,2)
        r=route(b,final,'document');b.handle(r);self.assertEqual(r.fulfill.call_args.kwargs['status'],200)
        self.assertNotIn('Location',r.fulfill.call_args.kwargs['headers'])
    def test_unsafe_navigation_redirect_stops_before_target(self):
        b=broker();b.session.get=Mock(return_value=response(302,headers={'Location':'http://127.0.0.1/'}))
        with self.assertRaises(ValueError):b.prepare_navigation(BASE)
        self.assertEqual(b.session.get.call_count,1)
    def test_subresource_redirect_never_reaches_native_browser_or_wrong_base(self):
        b=broker();b.session.get=Mock(return_value=response(302,headers={'Location':'http://127.0.0.1/'}))
        r=route(b);b.handle(r);r.abort.assert_called_once();r.fulfill.assert_not_called();self.assertEqual(b.rows[-1]['status'],302)
    def test_download_response_aborts_with_observed_status(self):
        b=broker();b.session.get=Mock(return_value=response(headers={'Content-Disposition':'attachment; filename=x'}));r=route(b);b.handle(r)
        r.abort.assert_called_once();self.assertEqual(b.rows[-1]['status'],200);self.assertIn('Download',b.rows[-1]['result'])
    def test_request_page_byte_deadline_and_total_budget(self):
        for state in ['request','bytes','deadline','crawl']:
            b=broker();b.session.get=Mock()
            if state=='request':b.page_requests=b.limits['page_requests']
            if state=='bytes':b.session.decoded_bytes=b.limits['page_bytes']
            if state=='deadline':b.deadline=time.monotonic()-1
            if state=='crawl':b.requests=b.limits['crawl_requests']
            r=route(b);b.handle(r);r.abort.assert_called_once();b.session.get.assert_not_called()
    def test_unknown_fetch_failure_does_not_fabricate_http_failure(self):
        b=broker();b.session.get=Mock(side_effect=bi.TransportError('private destination'))
        r=route(b);b.handle(r);self.assertIsNone(b.rows[-1]['status']);self.assertNotEqual(b.rows[-1]['status'],404)
    def test_evidence_cap_redaction_and_per_page_counters(self):
        b=broker(evidence_entries=1);b.session.get=Mock(return_value=response())
        b.handle(route(b));b.handle(route(b));self.assertEqual(len(b.rows),1);self.assertTrue(b.evidence()['evidence_truncated'])
        b.record_block('WebSocket blocked');b.begin_navigation(BASE+'second');self.assertFalse(b.current['partial_render']);self.assertTrue(b.evidence()['partial_render'])
    def test_no_unrestricted_network_methods_in_broker(self):
        tree=ast.parse(Path(bi.__file__).read_text());calls={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
        self.assertNotIn('continue_',calls);self.assertNotIn('fetch',calls)


class ControlledTransportTests(unittest.TestCase):
    def test_actual_c1_redirect_chain_and_cached_document(self):
        with ControlledSite() as site:
            b=broker();b.begin_navigation(site.base+'/old');final,chain=b.prepare_navigation(site.base+'/old')
            self.assertEqual(final,site.base+'/target');self.assertEqual(chain[0]['status'],301)
            r=route(b,final,'document');b.handle(r);self.assertEqual(r.fulfill.call_args.kwargs['status'],200)
            self.assertEqual(len(site.server.observed_requests),2);b.close()
    def test_mixed_private_dns_aborts_without_connect(self):
        b=broker()
        rows=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('1.1.1.1',443)),(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))]
        with patch('safe_http.socket.getaddrinfo',return_value=rows),patch('safe_http.socket.socket') as sock:
            r=route(b);b.handle(r);r.abort.assert_called_once();sock.assert_not_called()
    def test_private_redirect_domain_revalidated_after_first_hop(self):
        with ControlledSite() as site:
            b=broker();b.begin_navigation(site.base+'/old');original=b.session.get;calls=[]
            def get(url,**kw):
                calls.append(url)
                if len(calls)==2:raise bi.TransportError('DNS private destination')
                return original(url,**kw)
            b.session.get=get
            with self.assertRaises(bi.TransportError):b.prepare_navigation(site.base+'/old')
            self.assertEqual(len(site.server.observed_requests),1);self.assertEqual(b.rows[-1]['status'],None)


class EvidenceTests(unittest.TestCase):
    def test_partial_render_is_reported_without_changing_scores_or_export_count(self):
        crawl=dict(pages=[fixture_page()],errors=[],browser_used=True)
        scores=overall_scores(crawl['pages']);crawl['browser_security']=dict(partial_render=True,blocked={'blocked':1},resources=[])
        self.assertIn('Browser rendering is partial',coverage_note(crawl))
        d=build_delivery(BASE,crawl=crawl,discovery=discovery());files=delivery_files(d)
        self.assertEqual(len(files),9);self.assertIn('browser_security',d['evidence'])
        self.assertIn(b'Browser rendering is partial',files['client-report.html']);self.assertIn('Browser rendering is partial',html_report(BASE,crawl,[]))
        self.assertEqual(overall_scores(crawl['pages']),scores)


class CrawlerIntegrationTests(unittest.TestCase):
    def test_browser_loader_retains_requested_identity_redirects_depth_and_security(self):
        import common
        b=Mock();b.prepare_navigation.return_value=(BASE+'final/',[dict(url=BASE,status=301)])
        b.evidence.return_value=dict(partial_render=False,resources=[],blocked={})
        browser=Mock();page=browser.new_context.return_value.new_page.return_value;page.evaluate.return_value=0
        p=fixture_page();p.final_url=BASE+'final/';p.internal_links=[]
        with patch('playwright.sync_api.sync_playwright'),patch.object(common,'_launch_browser',return_value=browser),patch.object(bi,'GetBroker',return_value=b),patch.object(common,'crawl_page_browser',return_value=p),patch.object(common.time,'perf_counter',side_effect=[10,10.5]):
            c=crawl_site(BASE,limit=1)
        self.assertTrue(c['browser_used']);self.assertEqual(c['pages'][0].url,BASE)
        self.assertEqual(c['pages'][0].response_ms,500)
        self.assertEqual(c['pages'][0].crawl_depth,0);self.assertEqual(c['status_checks'][0]['requested_status'],301)
        self.assertIn('browser_security',c);browser.close.assert_called_once()
    def test_partial_browser_render_never_claims_observed_graph_complete(self):
        import common
        b=Mock();b.prepare_navigation.return_value=(BASE,[]);b.evidence.return_value=dict(partial_render=True,resources=[],blocked={'restricted':1})
        browser=Mock();browser.new_context.return_value.new_page.return_value.evaluate.return_value=0
        p=fixture_page();p.final_url=BASE;p.internal_links=[]
        with patch('playwright.sync_api.sync_playwright'),patch.object(common,'_launch_browser',return_value=browser),patch.object(bi,'GetBroker',return_value=b),patch.object(common,'crawl_page_browser',return_value=p):
            c=crawl_site(BASE,limit=1)
        self.assertEqual(c['coverage']['stop_reason'],'queue_exhausted');self.assertFalse(c['coverage']['observed_graph_complete'])
        self.assertIn('partial',coverage_note(c))
    def test_browser_launch_failure_uses_only_c1_http_fallback(self):
        import common
        p=fixture_page();p.internal_links=[]
        with patch('playwright.sync_api.sync_playwright'),patch.object(common,'_launch_browser',side_effect=RuntimeError('sandbox')),patch.object(common,'crawl_page_requests',return_value=p) as http:
            c=crawl_site(p.url,limit=1)
        self.assertFalse(c['browser_used']);http.assert_called_once();self.assertNotIn('browser_security',c)
    def test_failed_browser_navigation_unknown_and_no_direct_retry(self):
        import common
        b=Mock();b.prepare_navigation.side_effect=bi.TransportError('blocked');b.evidence.return_value=dict(partial_render=True,resources=[],blocked={'blocked':1})
        browser=Mock()
        with patch('playwright.sync_api.sync_playwright'),patch.object(common,'_launch_browser',return_value=browser),patch.object(bi,'GetBroker',return_value=b),patch.object(common,'crawl_page_requests') as http:
            c=crawl_site(BASE,limit=1)
        self.assertTrue(c['browser_used']);self.assertEqual(c['pages'],[]);self.assertIsNone(c['status_checks'][0]['status']);http.assert_not_called()
    def test_complete_audit_screen_explains_partial_evidence(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'pages/0_Complete_Audit.py'),default_timeout=20).run()
        app.text_input[0].set_value(BASE)
        c=dict(pages=[fixture_page()],errors=[],browser_used=True,browser_error='',browser_security=dict(partial_render=True,resources=[dict(url=BASE,status=None,result='Blocked')],blocked={'Blocked':1}))
        with patch('common.crawl_site',return_value=c),patch('common.get_robots_sitemap',return_value=discovery()):app.button[0].click().run()
        self.assertFalse(app.exception);self.assertTrue(any('Browser rendering is partial' in e.value for e in app.warning))


if __name__=='__main__':unittest.main()
