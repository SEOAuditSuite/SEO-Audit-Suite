import ast
import json
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import client_workflow as cw
from test_regressions import fixture_page, discovery
from test_rendering_diagnostics import BASE, result
from test_sitemap_diagnostics import collect
from rendering_diagnostics import unavailable


def delivery(**kwargs):
    return cw.build_delivery(BASE, crawl={'pages':[fixture_page()], 'errors':[], 'browser_used':False}, discovery=discovery(), **kwargs)


class DeliveryTests(unittest.TestCase):
    def test_disabled_never_invokes_diagnostic(self):
        with patch.object(cw,'compare_url') as compare: d=delivery()
        compare.assert_not_called();self.assertNotIn('rendering_diagnostics',d['evidence']);self.assertEqual(len(cw.delivery_files(d)),9)

    def test_enabled_scores_crawl_phase2_unchanged(self):
        inv=collect([BASE+'unlinked']);a=delivery(include_sitemaps=True,sitemap_inventory=inv)
        b=delivery(include_sitemaps=True,sitemap_inventory=inv,include_rendering=True,rendering_result=result())
        for key in ['audit','plan','issues','inventory']:self.assertEqual(a[key],b[key])
        for key in ['sitemap_diagnostics','internal_link_diagnostics','crawl_coverage']:self.assertEqual(a['evidence'][key],b['evidence'][key])
        self.assertEqual(a['model']['scorecards'],b['model']['scorecards'])

    def test_client_first_page_only(self):
        with patch.object(cw,'compare_url',return_value=result()) as compare:delivery(include_rendering=True)
        compare.assert_called_once_with(BASE)

    def test_csv_json_html_pdf_and_escaping(self):
        r=result();r['warnings']=['<script>alert(1)</script>'];d=delivery(include_rendering=True,rendering_result=r);files=cw.delivery_files(d)
        self.assertEqual(len(files),10);html=files['client-report.html'].decode()
        self.assertIn('Raw HTML / Rendered DOM Comparison',html);self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>',html)
        self.assertIn(b'Changed',files['rendering-comparison.csv']);self.assertTrue(files['client-report.pdf'].startswith(b'%PDF'))
        self.assertEqual(json.loads(files['evidence.json'])['rendering_diagnostics'],r)

    def test_unavailable_export_is_not_empty_success(self):
        d=delivery(include_rendering=True,rendering_result=unavailable(BASE,'Browser unavailable'));f=cw.delivery_files(d)
        self.assertIn(b'Not assessed',f['rendering-comparison.csv']);self.assertIn(b'Browser unavailable',f['client-report.html'])
        self.assertNotIn(b'Unchanged in snapshot',f['rendering-comparison.csv'])

    def test_client_workspace_checkbox_and_snapshot_retained(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'pages/23_Client_Workspace.py')).run()
        app.text_input[0].set_value(BASE);app.checkbox[1].check()
        with patch.object(cw,'crawl_site',return_value={'pages':[fixture_page()],'errors':[],'browser_used':False}),patch.object(cw,'get_robots_sitemap',return_value=discovery()),patch.object(cw,'compare_url',return_value=result()):
            app.button[0].click().run()
        self.assertFalse(app.exception);self.assertIn('rendering_diagnostics',app.session_state['client_delivery']['evidence'])
        before=app.session_state['client_zip'];app.run();self.assertEqual(app.session_state['client_zip'],before)

    def test_standalone_optional_screen(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'pages/6_Meta_Canonical.py')).run();app.text_input[0].set_value(BASE)
        with patch('rendering_diagnostics.compare_url',return_value=result()):app.button[0].click().run()
        self.assertFalse(app.exception);self.assertEqual(app.session_state['rendering_comparison']['status'],'Compared (limited snapshot)')


class ControlledHTTPTests(unittest.TestCase):
    def test_bounded_real_http_preserves_redirect_evidence(self):
        from test_http_link_integration import ControlledSite
        from rendering_diagnostics import BoundedTransport
        with ControlledSite() as site, patch('rendering_diagnostics.public_dns'):
            t=BoundedTransport(site.base+'/old')
            try:
                r=t.get(site.base+'/old');self.assertEqual(r['url'],site.base+'/target')
                self.assertEqual(r['redirects'][0]['status'],301);self.assertEqual(t.requests,2)
                self.assertIn(b'Target',r['body'])
            finally:t.close()

    def test_real_http_cross_origin_target_never_requested(self):
        from test_http_link_integration import ControlledSite
        from rendering_diagnostics import BoundedTransport
        with ControlledSite() as site, patch('rendering_diagnostics.public_dns'):
            t=BoundedTransport(site.base+'/away')
            try:
                with self.assertRaises(ValueError):t.get(site.base+'/away')
                self.assertEqual(len(site.server.observed_requests),1)
            finally:t.close()


if __name__ == '__main__':unittest.main()
