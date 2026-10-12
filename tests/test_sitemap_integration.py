import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_sitemap_diagnostics as fixtures
from test_sitemap_diagnostics import collect, xml
from test_regressions import discovery
from test_http_link_integration import ControlledSite, FixtureHandler
from sitemap_diagnostics import discover_sitemap_inventory, analyze_sitemap_candidates
from common import fetch
from client_workflow import build_delivery, delivery_files
from bs4 import BeautifulSoup


class DeliveryTests(unittest.TestCase):
    def fixture(self):
        c=fixtures.ComparisonTests().fixture()
        return c, collect(['https://example.test/new','https://example.test/unseen'])

    def test_opt_in_and_no_change_to_scores_or_default_exports(self):
        c, inv=self.fixture()
        original=build_delivery('https://example.test',crawl=c,discovery=discovery())
        enabled=build_delivery('https://example.test',crawl=c,discovery=discovery(),include_sitemaps=True,sitemap_inventory=inv)
        self.assertEqual(original['model']['scorecards'],enabled['model']['scorecards'])
        self.assertEqual(original['audit'],enabled['audit'])
        self.assertNotIn('sitemap_diagnostics',original['evidence'])
        self.assertNotIn('sitemap-candidate-evidence.csv',delivery_files(original,include_pdf=False))
        self.assertEqual(c['coverage']['pages_inspected'],3)

    def test_html_pdf_csv_evidence_and_escaped_labels(self):
        c,inv=self.fixture();inv['warnings'].append('<script>alert(1)</script>')
        delivery=build_delivery('https://example.test',crawl=c,discovery=discovery(),include_sitemaps=True,sitemap_inventory=inv)
        files=delivery_files(delivery)
        html=files['client-report.html'].decode()
        self.assertIn('Sitemap-Based Candidate Review',html)
        self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>',html)
        self.assertIn('Potential orphan candidate (limited evidence)',html)
        self.assertTrue(files['client-report.pdf'].startswith(b'%PDF'))
        self.assertIn(b'unseen',files['sitemap-candidate-evidence.csv'])
        self.assertIn(b'sitemap_diagnostics',files['evidence.json'])
        self.assertIn('sitemap-documents.csv',files);self.assertIn('sitemap-exclusions.csv',files)

    def test_report_examples_capped_and_unknown_not_zero(self):
        c,inv=self.fixture();inv=collect(['https://example.test/p'+str(i) for i in range(20)])
        c.pop('coverage')
        d=build_delivery('https://example.test',crawl=c,discovery=discovery(),include_sitemaps=True,sitemap_inventory=inv)
        soup=BeautifulSoup(delivery_files(d,include_pdf=False)['client-report.html'],'html.parser')
        section=soup.find('h2',string='Sitemap-Based Candidate Review').parent
        self.assertEqual(len(section.find_all('article')),10)
        self.assertIn('not assessed',section.get_text())
        self.assertEqual(len(d['evidence']['sitemap_diagnostics']['rows']),20)

    def test_long_url_report_remains_generatable(self):
        c,_=self.fixture();inv=collect(['https://example.test/'+ 'a'*4000])
        d=build_delivery('https://example.test',crawl=c,discovery=discovery(),include_sitemaps=True,sitemap_inventory=inv)
        self.assertTrue(delivery_files(d)['client-report.pdf'].startswith(b'%PDF'))

    def test_client_workspace_opt_in_render(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'pages/23_Client_Workspace.py')).run()
        self.assertFalse(app.exception)
        app.text_input[0].set_value('https://example.test')
        app.checkbox[0].check()
        c,inv=self.fixture()
        with patch('client_workflow.crawl_site',return_value=c),patch('client_workflow.get_robots_sitemap',return_value=discovery()),patch('client_workflow.discover_sitemap_inventory',return_value=inv):
            app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertIn('sitemap_diagnostics',app.session_state['client_delivery']['evidence'])

    def test_sitemap_screen_controlled_comparison(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'pages/2_Sitemap_Robots.py')).run()
        app.text_input[0].set_value('https://example.test');app.checkbox[0].check()
        c,inv=self.fixture()
        with patch('common.crawl_site',return_value=c),patch('common.get_robots_sitemap',return_value=discovery()),patch('sitemap_diagnostics.discover_sitemap_inventory',return_value=inv):
            app.button[0].click().run()
        self.assertFalse(app.exception);self.assertFalse(app.error)
        self.assertTrue(any('Potential orphan' in m.label for m in app.metric))


class ControlledSitemapHTTPTests(unittest.TestCase):
    def test_real_http_inventory_never_seeds_navigation(self):
        original=FixtureHandler.do_GET
        def sitemap_request(handler):
            if handler.path=='/sitemap.xml':
                host='http://'+handler.headers['Host']
                raw=xml([host+'/target',host+'/unlinked',host+'/away'])
                handler.server.observed_requests.append((handler.headers['Host'],handler.path))
                handler.send_response(200);handler.send_header('Content-Length',str(len(raw)));handler.end_headers();handler.wfile.write(raw)
            else:original(handler)
        with patch.object(FixtureHandler,'do_GET',sitemap_request), ControlledSite() as site:
            crawl=site.run(limit=1)
            before=len(site.server.observed_requests)
            inv=discover_sitemap_inventory(site.base)
            result=analyze_sitemap_candidates(crawl,inv)
            self.assertEqual(len(site.server.observed_requests),before+1)
            self.assertFalse(any(path=='/unlinked' for _,path in site.server.observed_requests))
            target=next(r for r in result['rows'] if r['URL']==site.base+'/target')
            self.assertTrue(target['Classification'].startswith('Potential orphan')) # /old alias is not verified in a truncated crawl
            self.assertIn('page_limit',result['scope_note'])

    def test_real_redirect_off_host_is_stopped_before_request(self):
        with ControlledSite() as site:
            inv=discover_sitemap_inventory(site.base,sitemap_url=site.base+'/away')
            self.assertFalse(inv['complete'])
            self.assertFalse(any(host.startswith('partner.') for host,_ in site.server.observed_requests))

    def test_optional_fetch_guard_blocks_intermediate_host(self):
        from test_link_diagnostics import BASE
        from types import SimpleNamespace
        from unittest.mock import Mock
        response=Mock(status_code=302,url=BASE+'/map',headers={'Location':'https://other.test/intermediate'})
        with patch('common.requests.Session') as session:
            session.return_value.__enter__.return_value.get.return_value=response
            with self.assertRaises(ValueError):fetch(BASE+'/map',url_validator=__import__('sitemap_diagnostics').sitemap_scope_validator(BASE))
            self.assertEqual(session.return_value.__enter__.return_value.get.call_count,1)

if __name__=='__main__':unittest.main()
