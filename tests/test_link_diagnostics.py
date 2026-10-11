import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import (_extract_page, parse_html, crawl_site, check_urls, fetch,
                    _guard_browser_route, overall_scores, crawl_page_browser, html_report)
from link_diagnostics import (analyze_links, crawl_status_cache, url_key,
                              validate_fetch_url, classify_status)
from client_workflow import build_delivery, delivery_files

BASE = 'https://example.test'


def page(path='/', links=(), status=200, final=None, chain=()):
    html = '<h1>Example</h1><title>Test</title>' + ''.join(f'<a href="{u}">{a}</a>' for u, a in links)
    p = _extract_page(parse_html(html), BASE + path, BASE + (final or path), status, 10)
    p.redirect_chain = list(chain)
    return p


def crawl(pages):
    return dict(pages=pages, errors=[], browser_used=False)


class LinkDiagnosticsTests(unittest.TestCase):
    def test_occurrences_and_unique_sources_and_score_compatibility(self):
        a = page(links=[('/target', 'A'), ('/target', 'A'), ('/target', 'B')])
        b = page('/other', [('/target', 'C')])
        self.assertEqual(len(a.internal_links), 2)  # historical list remains deduplicated
        score = overall_scores([a])
        a_single = page(links=[('/target', 'A'), ('/target', 'B')])
        self.assertEqual(score, overall_scores([a_single]))
        report = analyze_links(crawl([a, b]))
        target = next(r for r in report['inventory'] if r['URL'] == BASE + '/target')
        self.assertEqual(target['Observed link occurrences'], 4)
        self.assertEqual(target['Unique referring pages'], 2)
        self.assertEqual(sum(e['Occurrences'] for e in report['edges']), 4)

    def test_self_links_do_not_count_as_other_referring_pages(self):
        report = analyze_links(crawl([page('/self', [('/self', 'Self')])]))
        self.assertEqual(report['inventory'][0]['Unique referring pages'], 0)
        self.assertEqual(report['inventory'][0]['Observed link occurrences'], 1)

    def test_redirect_alias_prevents_false_unlinked_flag(self):
        root = page(links=[('/old', 'Old')])
        target = page('/old', final='/new', chain=[{'url': BASE + '/old', 'status': 301}])
        r = analyze_links(crawl([root, target]))
        self.assertNotIn(BASE + '/new', r['no_observed_inlinks'])
        self.assertEqual(r['aliases'][BASE + '/old'], BASE + '/new')
        self.assertEqual(r['edges'][0]['Requested status'], 301)
        self.assertEqual(r['edges'][0]['Status'], 200)
        self.assertEqual(r['edges'][0]['Final URL'], BASE + '/new')

    def test_unverified_final_url_change_is_not_redirect_alias(self):
        r = analyze_links(crawl([page(links=[('/old', 'Old')]), page('/old', final='/new')]))
        self.assertNotIn(BASE + '/old', r['aliases'])

    def test_intermediate_redirect_cache_and_duplicate_sources(self):
        p = page('/old', [('/target', 'T')], final='/new', chain=[
            {'url': BASE + '/old', 'status': 301}, {'url': BASE + '/middle', 'status': 302}])
        c = crawl([p, page('/new', [('/target', 'T')])])
        cache = crawl_status_cache(c)
        self.assertEqual(cache[BASE + '/middle']['requested_status'], 302)
        self.assertEqual(cache[BASE + '/new']['redirect_hops'], 0)
        row = next(r for r in analyze_links(c)['inventory'] if r['URL'] == BASE + '/target')
        self.assertEqual(row['Observed link occurrences'], 1)
        self.assertEqual(row['Unique referring pages'], 1)

    def test_cyclic_aliases_do_not_loop(self):
        a = page('/a', final='/b', chain=[{'url': BASE+'/a', 'status': 301}])
        b = page('/b', final='/a', chain=[{'url': BASE+'/b', 'status': 301}])
        self.assertIsInstance(analyze_links(crawl([a, b]))['inventory'], list)

    def test_legacy_occurrences_unknown_and_exports_compatible(self):
        p = page(links=[('/target', 'T')]); p.link_occurrences = None
        c = crawl([p])
        r = analyze_links(c)
        target = next(x for x in r['inventory'] if x['URL'] == BASE+'/target')
        self.assertIsNone(target['Observed link occurrences'])
        self.assertIn('legacy', r['coverage_note'])
        discovery = {'robots': {'status': 200, 'text': ''}, 'sitemap': {'status': 200, 'text': '<urlset/>'}, 'errors': []}
        delivery = build_delivery(BASE, crawl=c, discovery=discovery)
        files = delivery_files(delivery)
        self.assertTrue(files['client-report.pdf'].startswith(b'%PDF'))
        for name in ['client-report.html', 'evidence.json', 'issue-log.csv', 'page-inventory.csv', 'keyword-map.csv', 'ai-handoff.md', 'internal-link-evidence.csv', 'internal-link-inventory.csv']:
            self.assertIn(name, files)
        self.assertIsNone(json.loads(files['evidence.json'])['crawl_coverage'])
        self.assertIn(b'coverage/depth unavailable', files['client-report.html'])

    def test_identity_keeps_slash_case_query_encoding_and_port(self):
        self.assertEqual(url_key('HTTPS://EXAMPLE.TEST#x'), BASE+'/')
        for left, right in [('/a','/a/'),('/A','/a'),('/a?x=1','/a?x=2'),('/a%2Fb','/a/b')]:
            self.assertNotEqual(url_key(BASE+left), url_key(BASE+right))
        self.assertNotEqual(url_key(BASE+'/'), url_key(BASE+':8443/'))


class CrawlEvidenceTests(unittest.TestCase):
    def run_fixture(self, fixture, limit=10):
        with patch('common.crawl_page_requests', side_effect=lambda url, **kw: fixture[url]) as loader:
            result = crawl_site(BASE+'/', limit=limit, prefer_browser=False)
        return result, loader

    def test_depth_and_complete_observed_graph(self):
        fixture = {BASE+'/':page(links=[('/a','A'),('/b','B')]),
                   BASE+'/a':page('/a',[('/c','C')]), BASE+'/b':page('/b',[('/c','C')]), BASE+'/c':page('/c')}
        c, loader = self.run_fixture(fixture)
        self.assertEqual([p.crawl_depth for p in c['pages']], [0,1,1,2])
        self.assertEqual(c['coverage']['discovered_depths'][BASE+'/c'], 2)
        self.assertEqual(c['coverage']['stop_reason'], 'queue_exhausted')
        self.assertTrue(c['coverage']['observed_graph_complete'])
        self.assertFalse(c['coverage']['full_site_complete'])
        self.assertEqual(loader.call_count, 4)

    def test_truncation_and_unfetched_target_status(self):
        c, _ = self.run_fixture({BASE+'/':page(links=[('/a','A')])}, limit=1)
        self.assertEqual(c['coverage']['requested_limit'], 1)
        self.assertEqual(c['coverage']['remaining_queue'], [BASE+'/a'])
        self.assertEqual(c['coverage']['stop_reason'], 'page_limit')
        self.assertFalse(c['coverage']['observed_graph_complete'])
        self.assertEqual(analyze_links(c)['edges'][0]['Classification'], 'not checked')

    def test_discovery_cap_is_explicit(self):
        c, _ = self.run_fixture({BASE+'/':page(links=[('/p'+str(i), str(i)) for i in range(20)])}, limit=1)
        self.assertGreater(c['coverage']['skipped_discoveries'], 0)
        self.assertLessEqual(len(c['coverage']['discovered_depths']), 8)

    def test_broken_target_retained_and_reused_without_fetch(self):
        fixture = {BASE+'/':page(links=[('/gone','Gone')]), BASE+'/gone':page('/gone',status=404)}
        c, _ = self.run_fixture(fixture)
        self.assertEqual(c['coverage']['stop_reason'], 'queue_exhausted_with_errors')
        self.assertEqual(c['coverage']['pages_inspected'], 1)
        self.assertEqual(c['coverage']['attempted_urls'], 2)
        with patch('common.fetch') as network:
            rows = check_urls([BASE+'/gone'], cached=crawl_status_cache(c))
        network.assert_not_called()
        edge = analyze_links(c, rows)['edges'][0]
        self.assertEqual((edge['Source'], edge['Target'], edge['Status'], edge['Final URL']),
                         (BASE+'/', BASE+'/gone', 404, BASE+'/gone'))
        self.assertEqual(edge['Classification'], 'broken')

    def test_known_final_target_not_crawled_twice(self):
        fixture = {BASE+'/':page(links=[('/old','Old'),('/new','New')]),
                   BASE+'/old':page('/old',final='/new',chain=[{'url':BASE+'/old','status':301}])}
        c, loader = self.run_fixture(fixture)
        self.assertEqual(loader.call_count, 2)
        inventory = analyze_links(c)['inventory']
        row = next(r for r in inventory if r['URL'] == BASE+'/new')
        self.assertEqual(row['Observed seed-relative depth'], 1)
        self.assertEqual(row['Unique referring pages'], 1)
        self.assertEqual(c['coverage']['remaining_queue'], [])

    def test_failure_does_not_become_broken_or_complete(self):
        with patch('common.crawl_page_requests', side_effect=RuntimeError('https://user:secret@example.test/?token=secret')):
            c = crawl_site(BASE, prefer_browser=False)
        self.assertEqual(c['status_checks'][0]['classification'], 'error')
        self.assertNotIn('secret', str(c['errors']))
        self.assertFalse(c['coverage']['observed_graph_complete'])

    def test_empty_invalid_and_extreme_limits(self):
        for url, limit in [('',1),(BASE,0),(BASE,501)]:
            with self.assertRaises(ValueError): crawl_site(url,limit=limit,prefer_browser=False)

    def test_http_status_uncertainty(self):
        self.assertEqual(classify_status(404),'broken')
        self.assertEqual(classify_status(410),'broken')
        for status in [301,403,429,500,503]: self.assertEqual(classify_status(status),'review')
        for status in [None,0]: self.assertEqual(classify_status(status),'unknown')


class FetchGuardTests(unittest.TestCase):
    def test_rejects_private_literal_credentials_and_ambiguous_urls(self):
        for url in ['file:///etc/passwd','http://127.0.0.1','http://10.0.0.1',
                    'http://169.254.169.254','http://[::1]','http://[::ffff:127.0.0.1]',
                    'http://localhost.','http://a.local','http://2130706433','http://0177.0.0.1',
                    'http://0x7f.0.0.1','http://user:password@example.test','http://example.test\\@127.0.0.1',
                    'http://example.test\n/','http://example.test:99999']:
            with self.subTest(url=url), self.assertRaises(ValueError): validate_fetch_url(url)
        self.assertEqual(validate_fetch_url(BASE+'/a/?x=1'), BASE+'/a/?x=1')

    def test_redirect_to_private_is_not_requested(self):
        response = Mock(status_code=302, url=BASE, headers={'Location':'http://127.0.0.1/private'})
        with patch('common.requests.Session.get',return_value=response) as get:
            with self.assertRaises(ValueError): fetch(BASE)
        self.assertEqual(get.call_count, 1)
        self.assertFalse(get.call_args.kwargs['allow_redirects'])
        response.close.assert_called_once()

    def test_response_limit_and_close(self):
        response = Mock(status_code=200, url=BASE, headers={})
        response.iter_content.return_value = [b'x' * (5 * 1024 * 1024 + 1)]
        with patch('common.requests.Session.get',return_value=response):
            with self.assertRaises(ValueError): fetch(BASE)
        response.close.assert_called_once()

    def test_redirect_history_and_body_retained(self):
        a = Mock(status_code=301, url=BASE+'/old', headers={'Location':'/new'})
        b = Mock(status_code=200, url=BASE+'/new', headers={})
        b.iter_content.return_value = [b'hello']
        with patch('common.requests.Session.get',side_effect=[a,b]): result = fetch(BASE+'/old')
        self.assertEqual(result.history,[a])
        self.assertEqual(result._content,b'hello')

    def test_browser_route_blocks_private_and_allows_public_syntax(self):
        blocked = Mock(); blocked.request.url = 'http://192.168.1.1/image.png'
        _guard_browser_route(blocked)
        blocked.abort.assert_called_once(); blocked.continue_.assert_not_called()
        allowed = Mock(); allowed.request.url = BASE+'/image.png'
        _guard_browser_route(allowed)
        allowed.continue_.assert_called_once()

    def test_cache_deduplicates_status_requests(self):
        response = Mock(status_code=200,url=BASE+'/target',history=[])
        with patch('common.fetch',return_value=response) as network:
            rows = check_urls([BASE+'/target',BASE+'/target#fragment'])
        self.assertEqual(network.call_count,1)
        self.assertEqual(len(rows),1)


class PhaseOneUITests(unittest.TestCase):
    def test_internal_link_screen_action_and_empty_result(self):
        from streamlit.testing.v1 import AppTest
        root = Path(__file__).resolve().parents[1]
        for fixture in [crawl([page(links=[('/a','A'),('/a','A')])]), crawl([])]:
            app = AppTest.from_file(str(root/'pages/10_Internal_Links.py')).run()
            app.text_input[0].set_value(BASE)
            with patch('common.crawl_site', return_value=fixture): app.button[0].click().run()
            self.assertFalse(app.exception)
            if fixture['pages']:
                self.assertEqual(app.metric[0].value, '2')
                self.assertTrue(app.dataframe)

    def test_broken_link_screen_action_reuses_crawl(self):
        from streamlit.testing.v1 import AppTest
        root = Path(__file__).resolve().parents[1]
        fixture = crawl([page(links=[('/gone','Gone')])])
        fixture['status_checks'] = [dict(url=BASE+'/gone',status=404,requested_status=404,
            final_url=BASE+'/gone',redirect_hops=0,redirect_chain=[],classification='broken',error='')]
        app = AppTest.from_file(str(root/'pages/1_Broken_Links.py')).run()
        app.text_input[0].set_value(BASE)
        with patch('common.crawl_site',return_value=fixture), patch('common.fetch') as fetch_mock:
            app.button[0].click().run()
        fetch_mock.assert_not_called()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[2].value,'1')

    def test_report_includes_broken_link_and_coverage(self):
        fixture = crawl([page(links=[('/gone','Gone')])])
        fixture['status_checks'] = [dict(url=BASE+'/gone',status=404,requested_status=404,
            final_url=BASE+'/gone',redirect_hops=0,redirect_chain=[],classification='broken',error='')]
        fixture['coverage'] = dict(seed_url=BASE+'/', requested_limit=1,pages_inspected=1,
            attempted_urls=2,remaining_queue=[],skipped_discoveries=0,stop_reason='queue_exhausted_with_errors')
        discovery = {'robots':{'status':200,'text':''},'sitemap':{'status':200,'text':'<urlset/>'},'errors':[]}
        delivery = build_delivery(BASE,crawl=fixture,discovery=discovery)
        issue = next(i for i in delivery['issues'] if i['Finding']=='Observed broken internal link')
        self.assertEqual(issue['URL'],BASE+'/')
        self.assertIn('404',issue['Evidence'])
        files = delivery_files(delivery)
        self.assertIn(b'queue_exhausted_with_errors',files['client-report.html'])
        self.assertIn(b'Observed broken internal link',files['client-report.html'])
        self.assertIn(b'https://example.test/gone',files['internal-link-evidence.csv'])


class BrowserEvidenceTests(unittest.TestCase):
    def fake_page(self, final, response):
        browser_page = Mock()
        browser_page.url = final
        browser_page.goto.return_value = response
        browser_page.content.return_value = '<h1>Example</h1><a href="/target">Target</a>'
        browser_page.locator.return_value.evaluate_all.return_value = []
        return browser_page

    def test_browser_redirect_chain_capture_with_controlled_api_fixture(self):
        previous = SimpleNamespace(url=BASE+'/old', redirected_from=None,
                                   response=lambda: SimpleNamespace(status=301))
        response = SimpleNamespace(url=BASE+'/new',status=200,
                                   request=SimpleNamespace(redirected_from=previous))
        browser_page = self.fake_page(BASE+'/new',response)
        with patch('common.extract_aeo_question_answers_browser',return_value=[]):
            p = crawl_page_browser(browser_page,BASE+'/old')
        self.assertEqual(p.redirect_chain,[{'url':BASE+'/old','status':301}])
        self.assertEqual(p.status,200)
        self.assertTrue(p.browser_rendered)

    def test_client_navigation_is_not_http_redirect_evidence(self):
        response = SimpleNamespace(url=BASE+'/old',status=200,
                                   request=SimpleNamespace(redirected_from=None))
        browser_page = self.fake_page(BASE+'/new',response)
        with patch('common.extract_aeo_question_answers_browser',return_value=[]):
            p = crawl_page_browser(browser_page,BASE+'/old')
        self.assertEqual(p.status,0)
        self.assertEqual(p.redirect_chain,[])

    def test_browser_launch_failure_falls_back_and_retains_coverage(self):
        with patch('common._launch_browser',side_effect=RuntimeError('unavailable')), patch('common.crawl_page_requests',return_value=page()):
            c = crawl_site(BASE,limit=1,prefer_browser=True)
        self.assertFalse(c['browser_used'])
        self.assertTrue(c['browser_error'])
        self.assertEqual(c['coverage']['pages_inspected'],1)

    def test_complete_audit_html_has_coverage_and_honest_render_mode(self):
        text = html_report(BASE,crawl([page()]),[])
        self.assertIn('coverage/depth unavailable',text)
        self.assertIn('HTTP HTML fallback',text)
        self.assertNotIn('Browser-rendered pages audited',text)


class CrossHostScopeTests(unittest.TestCase):
    def foreign(self):
        p = page('/away', final='/landing', chain=[{'url':BASE+'/away','status':302}])
        p.final_url = 'https://partner.test/landing'
        p.internal_links = [{'url':'https://partner.test/child','anchor':'Foreign child'}]
        p.link_occurrences = [dict(p.internal_links[0],internal=True)]
        return p

    def test_cross_host_page_excluded_but_redirect_evidence_preserved(self):
        root = page(links=[('/away','Partner'),('/local','Local')])
        fixture = {BASE+'/':root, BASE+'/away':self.foreign(), BASE+'/local':page('/local')}
        with patch('common.crawl_page_requests', side_effect=lambda u, **kw: fixture[u]) as loader:
            c = crawl_site(BASE+'/',limit=2,prefer_browser=False)
        self.assertEqual([p.final_url for p in c['pages']],[BASE+'/',BASE+'/local'])
        self.assertEqual(loader.call_count,3)
        self.assertEqual(c['coverage']['pages_inspected'],2)
        self.assertEqual(c['coverage']['attempted_urls'],3)
        self.assertEqual(len(c['coverage']['out_of_scope_redirects']),1)
        r = analyze_links(c)
        self.assertFalse(any('partner.test' in row['URL'] for row in r['inventory']))
        edge = next(e for e in r['edges'] if e['Target']==BASE+'/away')
        self.assertTrue(edge['Internal'])
        self.assertTrue(edge['Redirect leaves audit scope'])
        self.assertFalse(edge['Destination in audit scope'])
        self.assertEqual(edge['Final URL'],'https://partner.test/landing')
        self.assertEqual(edge['Requested status'],302)

    def test_legacy_foreign_page_does_not_contribute_links_or_depth(self):
        c = crawl([page(links=[('/away','Partner')]),self.foreign()])
        r = analyze_links(c,include_external=True)
        self.assertEqual(len(r['edges']),1)
        self.assertEqual([x['URL'] for x in r['inventory']],[BASE+'/'])
        self.assertEqual(r['no_observed_inlinks'],[])

    def test_seed_redirect_establishes_explicit_final_hostname(self):
        seed = page(final='/',chain=[{'url':BASE+'/','status':301}])
        seed.final_url = 'https://www.example.test/'
        seed.internal_links = [{'url':'https://www.example.test/child','anchor':'Child'}]
        seed.link_occurrences = [dict(seed.internal_links[0],internal=True)]
        child = page('/child'); child.url=child.final_url='https://www.example.test/child'
        with patch('common.crawl_page_requests',side_effect=[seed,child]):
            c = crawl_site(BASE+'/',limit=2,prefer_browser=False)
        self.assertEqual(c['coverage']['audit_hostname'],'www.example.test')
        r=analyze_links(c)
        target=next(x for x in r['inventory'] if x['URL']==child.final_url)
        self.assertEqual(target['Observed seed-relative depth'],1)
        self.assertEqual(target['Unique referring pages'],1)
        self.assertIn('www.example.test',r['coverage_note'])

    def test_external_status_check_does_not_pollute_internal_inventory(self):
        c = crawl([page(links=[('/away','A')])])
        checks=[dict(url=BASE+'/away',status=200,requested_status=302,
            final_url='https://partner.test/',redirect_hops=1,redirect_chain=[{'url':BASE+'/away','status':302}],classification='working',error='')]
        r=analyze_links(c,checks)
        self.assertEqual([x['URL'] for x in r['inventory']],[BASE+'/'])
        self.assertTrue(r['edges'][0]['Redirect leaves audit scope'])


if __name__ == '__main__': unittest.main()
