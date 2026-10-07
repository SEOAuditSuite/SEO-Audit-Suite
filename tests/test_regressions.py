import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import _extract_page, parse_html, get_robots_sitemap, has_parsed_schema
from robots_rules import evaluate_robots
from v6_intelligence import analyze_ai_crawlers, calculate_geo
from client_workflow import build_delivery, delivery_files, parse_keyword_csv, csv_bytes


def fixture_page(path='/', title='Example Services'):
    html = f'''<html lang="en"><head><title>{title}</title></head><body>
    <h1>Example services</h1><p>Advice about our services and contact options.</p>
    <script type="application/ld+json">{{"@type":"Organization","name":"Example"}}</script>
    <a href="/about">About</a><img src="/service.png"></body></html>'''
    return _extract_page(parse_html(html), 'https://example.test'+path, 'https://example.test'+path, 200, 20)


def discovery(text='', code=200):
    return {'robots': {'status': code, 'text': text}, 'sitemap': {'status': 200, 'text': '<urlset/>'}, 'errors': []}


class RobotsTests(unittest.TestCase):
    def check(self, text, url, blocked, bot='OAI-SearchBot'):
        self.assertEqual(evaluate_robots(text, bot, 'https://example.test'+url)['blocked'], blocked)

    def test_wildcard_fallback(self):
        self.check('User-agent: *\nDisallow: /', '/services', True)

    def test_specific_group_overrides_wildcard(self):
        self.check('User-agent: *\nDisallow: /\nUser-agent: OAI-SearchBot\nAllow: /', '/services', False)

    def test_longest_exception(self):
        self.check('User-agent: *\nDisallow: /\nAllow: /public/', '/public/info', False)
        self.check('User-agent: *\nDisallow: /\nAllow: /public/', '/private', True)

    def test_tie_allows(self):
        self.check('User-agent: *\nDisallow: /a\nAllow: /a', '/a', False)

    def test_repeated_groups_merge(self):
        self.check('User-agent: OAI-SearchBot\nDisallow: /\nUser-agent: OAI-SearchBot\nAllow: /public', '/public', False)

    def test_patterns_and_query(self):
        self.check('User-agent: *\nDisallow: /*.pdf$', '/file.pdf', True)
        self.check('User-agent: *\nDisallow: /*.pdf$', '/file.pdf?download=1', False)
        self.check('User-agent: *\nDisallow: /*?secret=', '/a?secret=yes', True)

    def test_empty_directive_and_case(self):
        self.check('User-agent: *\nDisallow:', '/abc', False)
        self.check('User-agent: *\nDisallow: /Private', '/private', False)

    def test_encoded_paths(self):
        self.check('User-agent: *\nDisallow: /café', '/caf%C3%A9', True)
        self.check('User-agent: *\nDisallow: /foo', '/%66oo', True)
        self.check('User-agent: *\nDisallow: /a/b', '/a%2Fb', False)


class AuditTests(unittest.TestCase):
    def test_jsonld_survives_body_extraction(self):
        page = fixture_page()
        self.assertEqual(page.schema_types, ['Organization'])
        self.assertNotIn('@type', page.body_text)

    def test_malformed_jsonld_preserved(self):
        page = _extract_page(parse_html('<body><script type="application/ld+json">bad json</script></body>'), 'https://example.test', 'https://example.test', 200, 0)
        self.assertTrue(page.schema_blocks[0]['_parse_error'])
        self.assertFalse(has_parsed_schema(page))

    def test_multiple_meta_and_none(self):
        page = _extract_page(parse_html('<meta name="robots" content="index"><meta name="robots" content="none">'), 'https://example.test', 'https://example.test', 200, 0)
        self.assertTrue(page.noindex)

    def test_robots_at_origin(self):
        with patch('common.fetch') as fetch:
            get_robots_sitemap('https://example.test:8443/services/a?x=1')
        self.assertEqual([c.args[0] for c in fetch.call_args_list], ['https://example.test:8443/robots.txt','https://example.test:8443/sitemap.xml'])

    def test_unavailable_is_unknown(self):
        r = analyze_ai_crawlers(fixture_page(), 'https://example.test', discovery('', 503))
        self.assertTrue(all(row['blocked_url'] is None for row in r['bots']))
        self.assertEqual(r['coverage_percent'], 70)

    def test_training_block_does_not_penalize_search(self):
        page = fixture_page()
        clear = analyze_ai_crawlers(page, page.url, discovery())
        training = analyze_ai_crawlers(page, page.url, discovery('User-agent: GPTBot\nDisallow: /'))
        self.assertEqual(clear['score'], training['score'])
        blocked = analyze_ai_crawlers(page, page.url, discovery('User-agent: *\nDisallow: /'))
        self.assertLess(blocked['score'], clear['score'])

    def test_rendering_mode_does_not_add_points(self):
        page = fixture_page()
        a = analyze_ai_crawlers(page, page.url, discovery())
        page.browser_rendered = True
        b = analyze_ai_crawlers(page, page.url, discovery())
        self.assertEqual(a['score'], b['score'])

    def test_geo_does_not_claim_semantic_relevance(self):
        result = calculate_geo({'score': 50}, {'score': 50}, {'score': 50}, fixture_page())
        self.assertNotIn('Content relevance', result['components'])
        self.assertIn('Content length proxy', result['components'])


class DeliveryTests(unittest.TestCase):
    def test_delivery_contains_traceable_issues_and_scope(self):
        crawl = {'pages': [fixture_page(), fixture_page('/about')], 'errors': [], 'browser_used': False}
        result = build_delivery('https://example.test', crawl=crawl, discovery=discovery())
        files = delivery_files(result)
        self.assertTrue(files['client-report.pdf'].startswith(b'%PDF'))
        evidence = json.loads(files['evidence.json'])
        self.assertEqual(len(evidence['pages']), 2)
        self.assertTrue(any(i['Finding'] == 'Repeated title in crawl sample' for i in evidence['issues']))
        self.assertIn(b'HTTP HTML fallback', files['client-report.html'])
        self.assertIn(b'SEO-001', files['client-report.html'])
        self.assertIn('Acceptance', evidence['issues'][0])

    def test_keyword_source_required(self):
        with self.assertRaises(ValueError):
            parse_keyword_csv('Keyword,Volume\nservice,100\n')

    def test_unknown_metrics_remain_unknown(self):
        row = parse_keyword_csv('Keyword,Target URL\nservice,https://example.test\n')[0]
        self.assertEqual(row['Volume'], 'Not verified')
        self.assertIn('not independently verified', row['Confidence'])

    def test_csv_formula_protection(self):
        self.assertIn(b"'=1+1", csv_bytes([{'Keyword': '=1+1'}]))

    def test_html_escapes_client_text(self):
        crawl = {'pages': [fixture_page()], 'errors': [], 'browser_used': False}
        result = build_delivery('https://example.test', client_name='<script>alert(1)</script>', crawl=crawl, discovery=discovery())
        html = delivery_files(result, include_pdf=False)['client-report.html']
        self.assertNotIn(b'<script>alert(1)</script>', html)

if __name__ == '__main__':
    unittest.main()
