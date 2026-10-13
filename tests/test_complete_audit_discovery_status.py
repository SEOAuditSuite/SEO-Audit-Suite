"""Complete Audit must report observed discovery status, not hardcoded success."""
from pathlib import Path
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup
from streamlit.testing.v1 import AppTest
from common import html_report
from test_stabilization import image_crawl

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://example.test/'
LABELS = {'robots': 'robots.txt', 'sitemap': 'sitemap.xml'}


class DiscoveryStatusTests(unittest.TestCase):
    def run_audit(self, discovery):
        app = AppTest.from_file(str(ROOT/'pages/0_Complete_Audit.py'), default_timeout=20).run()
        app.text_input[0].set_value(BASE)
        with patch('common.crawl_site', return_value=image_crawl()), \
             patch('common.get_robots_sitemap', return_value=discovery), \
             patch('common.html_report', wraps=html_report) as report:
            app.button[0].click().run()
        self.assertFalse(app.exception)
        findings = {row[1]: row[2] for row in report.call_args.args[2]}
        return app, findings, html_report(*report.call_args.args, **report.call_args.kwargs)

    def test_200_is_pass_and_excluded_from_high_findings_and_html(self):
        discovery = dict(errors=[], **{key: dict(status=200) for key in LABELS})
        app, findings, html = self.run_audit(discovery)
        cards = BeautifulSoup(html, 'html.parser').select('.finding')
        for label in LABELS.values():
            self.assertTrue(any(f'PASS — **{label}** — HTTP 200' in e.value for e in app.success))
            self.assertNotIn(label, findings)
            self.assertFalse(any(label in card.get_text() for card in cards))
            self.assertFalse(any(label in e.value for e in app.warning))

    def test_non_200_uses_actual_status_in_screen_and_report_findings(self):
        app, findings, html = self.run_audit(dict(robots=dict(status=503), sitemap=dict(status=404), errors=[]))
        cards = BeautifulSoup(html, 'html.parser').select('.finding')
        for label, status in [('robots.txt',503), ('sitemap.xml',404)]:
            self.assertEqual(findings[label], f'HTTP {status}')
            card = next(card for card in cards if label in card.get_text())
            self.assertEqual(card.select_one('.detail').get_text(), f'HTTP {status}')
            self.assertEqual(card.select_one('.priority').get_text(), 'HIGH')
            self.assertTrue(any(f'REVIEW — **{label}** — HTTP {status}' in e.value for e in app.warning))
        self.assertFalse(any('HTTP 200' in e.value for e in app.warning))

    def test_unavailable_and_unknown_response_status_are_explicit(self):
        app, findings, _ = self.run_audit(dict(robots=None, sitemap=dict(status=None), errors=[]))
        for label in LABELS.values():
            self.assertEqual(findings[label], 'Unavailable — HTTP status unknown')
            self.assertFalse(any(label in e.value for e in app.success))

    def test_fetch_errors_do_not_invent_status_or_expose_exception_details(self):
        app, findings, _ = self.run_audit(dict(robots=None, sitemap=None,
            errors=[('/robots.txt','secret-token'),('/sitemap.xml','secret-token')]))
        for label in LABELS.values():
            self.assertEqual(findings[label], 'Unavailable — fetch failed or blocked; HTTP status unknown')
        self.assertNotIn('secret-token', '\n'.join(e.value for e in app.warning))
        self.assertFalse(any('HTTP 200' in e.value for e in app.warning))


if __name__ == '__main__':
    unittest.main()
