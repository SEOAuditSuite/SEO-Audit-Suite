"""Phase A corrections: presentation scope and head-only extraction."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from comparison_view import readable_value, readable_rows
from common import html_report, overall_scores
from rendering_diagnostics import snapshot, compare_snapshots, unavailable
from test_regressions import fixture_page, discovery
from test_rendering_diagnostics import result, BASE
from test_rendering_integration import delivery
from client_workflow import delivery_files

ROOT = Path(__file__).resolve().parents[1]


def image_crawl(browser=False):
    pages = [fixture_page(), fixture_page('/second')]
    for p, count in zip(pages, (11, 59)):
        p.images = [dict(src=BASE+f'image-{i % 7}.png', alt='Descriptive text') for i in range(count)]
        p.browser_rendered = browser
    return dict(pages=pages, errors=[], browser_used=browser, browser_error='')


class HeadOnlyTests(unittest.TestCase):
    def test_head_only_retains_metadata_but_not_main_text(self):
        s = snapshot('<html><head><title>Only title</title><meta name="description" content="Description"></head></html>', BASE)
        self.assertEqual(s['fields']['Title']['values'], ['Only title'])
        self.assertEqual(s['fields']['Meta description']['values'], ['Description'])
        self.assertEqual(s['fields']['Main textual content']['values'], [])

    def test_title_fragment_not_body_and_body_fragment_retained(self):
        for html in ('<title>Only title</title>', '<head><title>Only title</title></head>'):
            self.assertEqual(snapshot(html, BASE)['fields']['Main textual content']['count'], 0)
        s = snapshot('<title>Title</title><h1>Heading</h1><p>Actual body</p>', BASE)
        self.assertEqual(s['fields']['Main textual content']['values'], ['Heading Actual body'])

    def test_empty_body_and_main_priority_preserved(self):
        self.assertEqual(snapshot('<head><title>Title</title></head><body></body>', BASE)['fields']['Main textual content']['count'], 0)
        s = snapshot('<body>Outside<main><h1>Inside</h1></main></body>', BASE)
        self.assertEqual(s['fields']['Main textual content']['values'], ['Inside'])


class ComparisonPresentationTests(unittest.TestCase):
    def test_readable_rows_preserve_original_counts_duplicates_and_states(self):
        original = result()['rows']; before = copy.deepcopy(original)
        rows = readable_rows(original)
        self.assertEqual(original, before)
        self.assertEqual([r['Change'] for r in rows], [r['Change'] for r in original])
        links = next(r for r in rows if r['Element'] == 'Internal links')
        self.assertIn('→ https://', links['Raw'])
        self.assertNotIn('"anchor":', links['Raw'])
        self.assertEqual(links['Raw'].count('Keep link →'), 2)
        self.assertIn('observed entries', links['Raw'])

    def test_truncation_empty_text_and_unavailable_are_explicit(self):
        self.assertIn('extraction truncated', readable_value(json.dumps(dict(values=['x'], count=201, truncated=True))))
        self.assertIn('excerpt shortened', readable_value(json.dumps(dict(values=['x'], count=1, characters=3000, excerpt_shortened=True))))
        self.assertIn('None observed', readable_value('{"values": [], "count": 0}'))
        self.assertEqual(readable_rows(unavailable(BASE, 'Unavailable')['rows']), [])
        self.assertIn('could not be formatted', readable_value('invalid'))

    def test_optional_html_and_pdf_preserve_machine_evidence(self):
        r = result(); before = copy.deepcopy(r)
        r['rows'][0]['Raw'] = json.dumps(dict(values=['<script>alert(1)</script>'], count=1))
        files = delivery_files(delivery(include_rendering=True, rendering_result=r))
        html = files['client-report.html'].decode()
        self.assertIn('&lt;script&gt;', html); self.assertNotIn('<script>', html)
        self.assertIn('Keep link', html); self.assertNotIn('&quot;anchor&quot;:', html)
        self.assertEqual(json.loads(files['evidence.json'])['rendering_diagnostics'], r)
        self.assertTrue(files['client-report.pdf'].startswith(b'%PDF'))
        self.assertEqual(r['rows'][1:], before['rows'][1:])

    def test_meta_screen_readable_table_and_structured_evidence(self):
        app = AppTest.from_file(str(ROOT/'pages/6_Meta_Canonical.py'), default_timeout=20).run()
        app.text_input[0].set_value(BASE)
        r = result()
        with patch('rendering_diagnostics.compare_url', return_value=r):
            app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertIn('observed entries', app.dataframe[0].value.iloc[0]['Raw'])
        self.assertEqual(app.session_state['rendering_comparison'], r)
        self.assertTrue(any(e.label == 'Structured comparison evidence' for e in app.expander))

    def test_workspace_uses_readable_view_without_changing_saved_pack(self):
        d = delivery(include_rendering=True, rendering_result=result())
        app = AppTest.from_file(str(ROOT/'pages/23_Client_Workspace.py'), default_timeout=20).run()
        app.text_input[0].set_value(BASE)
        with patch('client_workflow.build_delivery', return_value=d):
            app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertIn('observed entries', app.dataframe[0].value.iloc[0]['Raw'])
        self.assertEqual(app.session_state['client_delivery'], d)


class CompleteAuditPresentationTests(unittest.TestCase):
    def test_crawled_pages_scroll_region_preserves_all_table_evidence(self):
        from bs4 import BeautifulSoup
        html = html_report(BASE, image_crawl(), [])
        soup = BeautifulSoup(html, 'html.parser')
        region = soup.select_one('.table-scroll')
        self.assertIsNotNone(region)
        self.assertEqual(region.get('role'), 'region')
        self.assertEqual(region.get('tabindex'), '0')
        self.assertEqual(soup.find(id=region['aria-labelledby']).get_text(), 'Crawled Pages')
        self.assertEqual(len(region.select('th')), 8)
        self.assertEqual(len(region.select('td')), 16)
        self.assertEqual([row.select('td')[-1].get_text() for row in region.select('tr')[1:]],
                         ['Organization', 'Organization'])
        self.assertIn('.table-scroll{max-width:100%;overflow-x:auto}', html)
        self.assertNotIn('overflow-x:hidden', html)

    def test_complete_html_version_image_scopes_and_escaping(self):
        crawl = image_crawl(); before = copy.deepcopy(crawl); scores = overall_scores(crawl['pages'])
        crawl['pages'][0].final_url = BASE+'?unsafe=<script>'
        html = html_report(BASE, crawl, [], scores)
        self.assertIn('V6.1.1 (development)', html); self.assertNotIn('Pro V5', html)
        for text in ('Crawl-wide image elements: <strong>70', 'Crawl-wide unique image URLs: <strong>7', 'First-page non-empty ALT coverage: <strong>11/11', 'HTTP HTML fallback'):
            self.assertIn(text, html)
        self.assertIn('&lt;script&gt;', html); self.assertNotIn('<script>', html)
        self.assertEqual(overall_scores(crawl['pages']), scores)
        self.assertEqual(crawl['pages'][0].images, before['pages'][0].images)

    def test_complete_screen_scopes_and_version(self):
        app = AppTest.from_file(str(ROOT/'pages/0_Complete_Audit.py'), default_timeout=20).run()
        self.assertIn('V6.1.1 (development)', app.title[0].value)
        app.text_input[0].set_value(BASE)
        with patch('common.crawl_site', return_value=image_crawl()), patch('common.get_robots_sitemap', return_value=discovery()):
            app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any('11/11 first-page' in e.value for e in app.success))
        self.assertTrue(any('Crawl-wide image elements: **70**' in e.value for e in app.markdown))

    def test_image_screen_reports_fallback_and_first_page(self):
        app = AppTest.from_file(str(ROOT/'pages/7_Image_SEO.py'), default_timeout=20).run()
        app.text_input[0].set_value(BASE)
        with patch('common.crawl_site', return_value=image_crawl()):
            app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].label, 'First-page image elements')
        self.assertEqual(app.metric[0].value, '11')
        self.assertTrue(any('HTTP HTML fallback' in e.value for e in app.caption))

    def test_empty_images_not_presented_as_full_coverage(self):
        crawl = image_crawl()
        for p in crawl['pages']: p.images = []
        self.assertIn('N/A (no image elements)', html_report(BASE, crawl, []))


if __name__ == '__main__':
    unittest.main()
