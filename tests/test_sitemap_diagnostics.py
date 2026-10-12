import gzip
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sitemap_diagnostics import parse_sitemap_document, discover_sitemap_inventory, analyze_sitemap_candidates, sitemap_scope_validator
from test_link_diagnostics import page, crawl, BASE


def xml(urls, kind='urlset'):
    entry = 'url' if kind == 'urlset' else 'sitemap'
    return ('<' + kind + '>' + ''.join(f'<{entry}><loc>{u}</loc></{entry}>' for u in urls) + '</' + kind + '>').encode()


def collect(urls):
    return discover_sitemap_inventory(BASE, discovery={'sitemap':dict(status=200, url=BASE+'/sitemap.xml', text=xml(urls).decode())})


class ParserTests(unittest.TestCase):
    def test_namespaced_page_entries_ignore_image_loc(self):
        raw = b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"><url><loc>https://example.test/a</loc><image:image><image:loc>https://example.test/photo</image:loc></image:image></url></urlset>'
        self.assertEqual(parse_sitemap_document(raw)['urls'], ['https://example.test/a'])

    def test_index_typed_separately(self):
        self.assertEqual(parse_sitemap_document(xml([BASE+'/child.xml'], 'sitemapindex'))['kind'], 'sitemapindex')

    def test_gzip_and_decoded_limit(self):
        raw = gzip.compress(xml([BASE+'/a']))
        self.assertEqual(len(parse_sitemap_document(raw)['urls']), 1)
        with self.assertRaises(ValueError): parse_sitemap_document(raw, 20)

    def test_reject_malformed_and_wrong_root(self):
        for raw in [b'<urlset>', b'<html/>', b'<urlset xmlns="https://evil.test"/>', b'<urlset><url><loc>a</loc><loc>b</loc></url></urlset>', b'<urlset><url><loc><x/></loc></url></urlset>']:
            with self.subTest(raw=raw), self.assertRaises((ValueError, __import__('lxml.etree', fromlist=['XMLSyntaxError']).XMLSyntaxError)): parse_sitemap_document(raw)

    def test_dtd_utf8_and_utf16_rejected(self):
        text = '<!DOCTYPE urlset [<!ENTITY x "https://example.test/a">]><urlset><url><loc>&x;</loc></url></urlset>'
        for encoding in ['utf-8', 'utf-16']:
            with self.subTest(encoding=encoding), self.assertRaises(ValueError): parse_sitemap_document(text.encode(encoding))

    def test_external_entity_is_never_loaded(self):
        with self.assertRaises(ValueError):
            parse_sitemap_document(b'<!DOCTYPE urlset SYSTEM "file:///etc/passwd"><urlset/>')


class InventoryTests(unittest.TestCase):
    def fetcher(self, mapping, calls):
        def fetch(url, timeout, url_validator):
            calls.append(url)
            final, raw = mapping[url] if isinstance(mapping[url], tuple) else (url, mapping[url])
            url_validator(final)
            return SimpleNamespace(url=final, content=raw, status_code=200)
        return fetch

    def test_recursive_index_cycle_duplicate_provenance(self):
        calls = []
        mapping = {BASE+'/sitemap.xml': xml([BASE+'/child.xml', BASE+'/two.xml'], 'sitemapindex'),
                   BASE+'/child.xml': xml([BASE+'/nested.xml', BASE+'/sitemap.xml'], 'sitemapindex'),
                   BASE+'/nested.xml': xml([BASE+'/a']), BASE+'/two.xml': xml([BASE+'/a'])}
        out = discover_sitemap_inventory(BASE, fetcher=self.fetcher(mapping, calls))
        self.assertTrue(out['complete'])
        self.assertEqual(len(out['inventory']), 1)
        self.assertEqual(len(out['inventory'][0]['Sitemaps']), 2)
        self.assertEqual(len(calls), 4)

    def test_all_robots_directives_and_explicit_root(self):
        calls=[]
        mapping={BASE+'/sitemap.xml':xml([]),BASE+'/custom.xml':xml([BASE+'/a']),BASE+'/second.xml':xml([BASE+'/b']),BASE+'/explicit.xml':xml([BASE+'/c'])}
        out=discover_sitemap_inventory(BASE, {'robots':dict(status=200,url=BASE+'/robots.txt',text='Sitemap: '+BASE+'/custom.xml\nSITEMAP: '+BASE+'/second.xml')},BASE+'/explicit.xml',fetcher=self.fetcher(mapping,calls))
        self.assertEqual(len(out['inventory']),3)

    def test_depth_limit(self):
        calls=[]
        out=discover_sitemap_inventory(BASE, limits={'depth':1}, fetcher=self.fetcher({BASE+'/sitemap.xml':xml([BASE+'/a.xml'],'sitemapindex'),BASE+'/a.xml':xml([BASE+'/b.xml'],'sitemapindex')},calls))
        self.assertFalse(out['complete']); self.assertEqual(len(calls),2)

    def test_document_and_queue_limits(self):
        calls=[]
        out=discover_sitemap_inventory(BASE,limits={'documents':1}, fetcher=self.fetcher({BASE+'/sitemap.xml':xml([BASE+'/a.xml',BASE+'/b.xml'],'sitemapindex')},calls))
        self.assertFalse(out['complete']);self.assertEqual(len(calls),1)
        self.assertTrue(out['warnings'])

    def test_page_limit_and_conservative_identity(self):
        out=discover_sitemap_inventory(BASE, {'sitemap':dict(status=200,text=xml([BASE+'/a',BASE+'/a/',BASE+'/A',BASE+'/a?x=1']).decode())}, limits={'pages':2})
        self.assertEqual([r['URL'] for r in out['inventory']],[BASE+'/a',BASE+'/a/']);self.assertFalse(out['complete'])

    def test_total_byte_limit_stops_fetches(self):
        calls=[]; root=xml([BASE+'/a.xml',BASE+'/b.xml'],'sitemapindex')
        out=discover_sitemap_inventory(BASE, limits={'total_bytes':len(root)+1},fetcher=self.fetcher({BASE+'/sitemap.xml':root,BASE+'/a.xml':xml([BASE+'/a'])},calls))
        self.assertFalse(out['complete']);self.assertEqual(len(calls),2)

    def test_invalid_page_urls_and_relative_locs_excluded(self):
        out=collect(['/relative','https://127.0.0.1/a','https://user:secret@example.test/a',BASE+'/valid'])
        self.assertEqual(len(out['inventory']),1);self.assertEqual(len(out['excluded']),3)
        self.assertNotIn('secret', str(out))

    def test_cached_original_bytes_support_utf16_and_gzip(self):
        import base64
        for content in [xml([BASE+'/a']).decode().encode('utf-16'), gzip.compress(xml([BASE+'/a']))]:
            cached = {'sitemap':dict(status=200, text='unused', content_base64=base64.b64encode(content).decode())}
            fetcher = Mock(side_effect=AssertionError('Cache must avoid a duplicate request'))
            out = discover_sitemap_inventory(BASE, cached, fetcher=fetcher)
            self.assertTrue(out['complete']); self.assertEqual(len(out['inventory']),1)
            fetcher.assert_not_called()

    def test_cross_host_child_not_requested(self):
        calls=[]
        out=discover_sitemap_inventory(BASE,fetcher=self.fetcher({BASE+'/sitemap.xml':xml(['https://other.test/a.xml'],'sitemapindex')},calls))
        self.assertEqual(calls,[BASE+'/sitemap.xml']);self.assertFalse(out['complete'])

    def test_cross_host_final_rejected_and_cached_redirect_rejected(self):
        for cached in [True,False]:
            out=discover_sitemap_inventory(BASE, discovery={'sitemap':dict(status=200,url='https://other.test/map',text='<urlset/>')} if cached else None,fetcher=self.fetcher({BASE+'/sitemap.xml':('https://other.test/map',xml([]))},[]))
            self.assertFalse(out['complete']);self.assertEqual(out['inventory'],[])

    def test_cached_foreign_intermediate_redirect_is_rejected(self):
        cache = {'sitemap': dict(status=200, url=BASE+'/sitemap.xml', text='<urlset/>',
            redirect_chain=[dict(url='https://other.test/redirect', status=302)])}
        out = discover_sitemap_inventory(BASE, cache)
        self.assertFalse(out['complete']); self.assertFalse(out['inventory'])
        self.assertIn('hostname', out['documents'][0]['Error'])

    def test_non_200_document_is_error(self):
        out=discover_sitemap_inventory(BASE,fetcher=lambda *a,**kw:SimpleNamespace(url=BASE+'/sitemap.xml',content=b'',status_code=404))
        self.assertEqual(out['documents'][0]['Status'],404);self.assertFalse(out['complete'])

    def test_elapsed_budget_and_invalid_limits(self):
        with patch('sitemap_diagnostics.time.monotonic',side_effect=[0,100]):
            out=discover_sitemap_inventory(BASE,fetcher=Mock())
        self.assertFalse(out['complete']);self.assertEqual(out['documents'],[])
        for limits in [{'pages':0},{'documents':21},{'seconds':float('nan')},{'pages':1.5},{'unknown':1},{'pages':True}]:
            with self.assertRaises(ValueError): discover_sitemap_inventory(BASE,limits=limits)

    def test_root_queue_is_bounded_and_warns(self):
        calls = []
        roots = [BASE + '/root' + str(i) + '.xml' for i in range(50)]
        cached = {'robots': dict(status=200, text='\n'.join('Sitemap: ' + u for u in roots))}
        out = discover_sitemap_inventory(BASE, cached, limits={'documents': 2},
            fetcher=self.fetcher({u: xml([]) for u in roots[:2]}, calls))
        self.assertEqual(len(calls), 2)
        self.assertLessEqual(out['remaining_documents'], 2)
        self.assertTrue(any('root queue' in w for w in out['warnings']))

    def test_malformed_documents_consume_aggregate_budget(self):
        root = xml([BASE + '/bad.xml', BASE + '/next.xml'], 'sitemapindex')
        bad = b'<urlset>'
        calls = []
        out = discover_sitemap_inventory(BASE, limits={'total_bytes':len(root) + len(bad)},
            fetcher=self.fetcher({BASE+'/sitemap.xml':root, BASE+'/bad.xml':bad,
                                  BASE+'/next.xml':xml([])}, calls))
        self.assertEqual(out['decoded_bytes'], len(root) + len(bad))
        self.assertEqual(len(calls), 2)
        self.assertTrue(any('Total decoded' in w for w in out['warnings']))
        self.assertFalse(out['complete'])

    def test_aggregate_gzip_budget_rejects_before_xml_parse(self):
        root = xml([BASE+'/large.xml'], 'sitemapindex')
        calls = []
        with patch('sitemap_diagnostics._parse_xml', wraps=__import__('sitemap_diagnostics')._parse_xml) as parser:
            out = discover_sitemap_inventory(BASE, limits={'total_bytes':len(root)+8},
                fetcher=self.fetcher({BASE+'/sitemap.xml':root, BASE+'/large.xml':gzip.compress(xml([BASE+'/a']))},calls))
        self.assertEqual(parser.call_count, 1)
        self.assertEqual(out['decoded_bytes'], len(root))
        self.assertFalse(out['complete'])
        self.assertIn('Total decoded', out['documents'][-1]['Error'])

    def test_deep_xml_and_oversized_loc_rejected(self):
        for raw in [b'<urlset>'+b'<x>'*300+b'</x>'*300+b'</urlset>',
                    xml([BASE+'/'+'a'*8192])]:
            with self.subTest(raw_size=len(raw)), self.assertRaises(Exception):
                parse_sitemap_document(raw)

    def test_scope_validator_blocks_private_and_cross_host(self):
        guard=sitemap_scope_validator(BASE)
        guard(BASE+'/a')
        for target in ['http://127.0.0.1/a','https://elsewhere.test/a']:
            with self.assertRaises(ValueError):guard(target)


class ComparisonTests(unittest.TestCase):
    def fixture(self):
        c=crawl([page(links=[('/old','Old'),('/old','Old'),('/self','Self')]),page('/new'),page('/self',links=[('/self','Self')])])
        c['coverage']=dict(seed_url=BASE+'/',audit_hostname='example.test',requested_limit=3,pages_inspected=3,attempted_urls=3,remaining_queue=[BASE+'/later'],skipped_discoveries=0,stop_reason='page_limit',full_site_complete=False)
        c['status_checks']=[dict(url=BASE+'/old',final_url=BASE+'/new',status=200,requested_status=301,redirect_hops=1,redirect_chain=[dict(url=BASE+'/old',status=301)])]
        return c

    def rows(self,c,urls):
        return {r['URL']:r for r in analyze_sitemap_candidates(c,collect(urls))['rows']}

    def test_counts_aliases_depth_and_seed(self):
        rows=self.rows(self.fixture(),[BASE+'/',BASE+'/old',BASE+'/new',BASE+'/unseen'])
        self.assertEqual(rows[BASE+'/new']['Unique_referring_pages'],1)
        self.assertEqual(rows[BASE+'/new']['Observed_link_occurrences'],2)
        self.assertEqual(rows[BASE+'/new']['Depth'],1)
        self.assertEqual(rows[BASE+'/old']['Final_URL'],BASE+'/new')
        self.assertEqual(rows[BASE+'/']['Classification'],'Navigation seed')
        self.assertTrue(rows[BASE+'/unseen']['Classification'].startswith('Potential orphan'))
        self.assertIsNone(rows[BASE+'/unseen']['Status'])

    def test_self_link_does_not_hide_candidate_when_not_linked_elsewhere(self):
        c=self.fixture();c['pages'][0]=page()
        rows=self.rows(c,[BASE+'/self'])
        self.assertEqual(rows[BASE+'/self']['Unique_referring_pages'],0)
        self.assertTrue(rows[BASE+'/self']['Classification'].startswith('Potential orphan'))

    def test_legacy_empty_or_failed_graph_is_unknown(self):
        for c in [crawl([]),crawl([page()]),dict(self.fixture(),pages=[page(status=500)])]:
            r=analyze_sitemap_candidates(c,collect([BASE+'/a']))
            self.assertFalse(r['comparison_available']);self.assertEqual(r['candidate_count'],0)
            self.assertIsNone(r['rows'][0]['Unique_referring_pages'])

    def test_cross_host_redirect_and_foreign_loc(self):
        c=self.fixture();c['status_checks'].append(dict(url=BASE+'/away',final_url='https://other.test/a',status=200,redirect_hops=1))
        rows=self.rows(c,[BASE+'/away','https://other.test/a'])
        self.assertTrue(all(r['Classification']=='Outside audit hostname' for r in rows.values()))

    def test_conflicting_and_cyclic_aliases_unresolved(self):
        c=self.fixture();c['status_checks'].append(dict(url=BASE+'/old',final_url=BASE+'/different',status=200,redirect_hops=1))
        rows=self.rows(c,[BASE+'/old',BASE+'/new',BASE+'/different'])
        self.assertTrue(all(r['Classification']=='Unresolved redirect evidence' for r in rows.values()))
        c=self.fixture();c['status_checks'] += [dict(url=BASE+'/a',final_url=BASE+'/b',status=200,redirect_hops=1),dict(url=BASE+'/b',final_url=BASE+'/a',status=200,redirect_hops=1)]
        self.assertEqual(self.rows(c,[BASE+'/a'])[BASE+'/a']['Classification'],'Unresolved redirect evidence')

    def test_no_network_during_comparison_and_canonical_not_union(self):
        c=self.fixture();c['pages'][1].canonical=BASE+'/unseen'
        with patch('sitemap_diagnostics.fetch',side_effect=AssertionError('Network prohibited')):
            rows=self.rows(c,[BASE+'/unseen',BASE+'/new'])
        self.assertTrue(rows[BASE+'/unseen']['Classification'].startswith('Potential orphan'))
        self.assertEqual(rows[BASE+'/new']['Canonical_hint'],BASE+'/unseen')

    def test_invalid_canonical_remains_reviewable(self):
        c = self.fixture(); c['pages'][1].canonical = 'https://example.test:99999/canonical'
        self.assertIn('Invalid', self.rows(c, [BASE+'/new'])[BASE+'/new']['Canonical_review'])

    def test_known_unavailable_review_separate(self):
        c=self.fixture();c['status_checks'].append(dict(url=BASE+'/gone',final_url=BASE+'/gone',status=404,redirect_hops=0))
        self.assertEqual(self.rows(c,[BASE+'/gone'])[BASE+'/gone']['Classification'],'Observed unavailable; review separately')

    def test_missing_or_empty_sitemap_is_not_a_clean_zero(self):
        c = self.fixture()
        for inv in [collect([]), discover_sitemap_inventory(BASE,fetcher=Mock(side_effect=ValueError('unavailable')))]:
            result = analyze_sitemap_candidates(c, inv)
            self.assertFalse(result['comparison_available'])

    def test_failed_alias_has_unresolved_evidence(self):
        c = self.fixture()
        c['status_checks'] = [dict(url=BASE+'/old', final_url=BASE+'/new', status=500, redirect_hops=1)]
        rows = self.rows(c, [BASE+'/old', BASE+'/new'])
        self.assertTrue(all(r['Classification']=='Unresolved redirect evidence' for r in rows.values()))
        self.assertTrue(all(r['Unique_referring_pages'] is None for r in rows.values()))

    def test_seed_redirect_and_www_boundary_preserved(self):
        from common import _extract_page, parse_html
        final = 'https://www.example.test/'
        seed = _extract_page(parse_html('<a href="/linked">Link</a>'), BASE+'/', final,200,0)
        seed.redirect_chain = [dict(url=BASE+'/', status=301)]
        c = self.fixture(); c['pages']=[seed]; c['status_checks']=[]
        c['coverage'].update(audit_hostname='www.example.test')
        inv=discover_sitemap_inventory(final, {'sitemap':dict(status=200,text=xml([BASE+'/', final,final+'linked',BASE+'/else']).decode())})
        rows={r['URL']:r for r in analyze_sitemap_candidates(c, inv)['rows']}
        self.assertEqual(rows[BASE+'/']['Classification'],'Navigation seed')
        self.assertEqual(rows[final+'linked']['Classification'],'Observed internally linked')
        self.assertEqual(rows[BASE+'/else']['Classification'],'Outside audit hostname')
        self.assertIsNone(rows[BASE+'/else']['Unique_referring_pages'])

    def test_incomplete_coverage_kept_in_evidence(self):
        c=self.fixture();result=analyze_sitemap_candidates(c,collect([BASE+'/unseen']))
        self.assertIn('page_limit',result['scope_note']);self.assertEqual(result['navigation_coverage'],c['coverage'])
        self.assertIn('not proof',result['scope_note'])

if __name__=='__main__':unittest.main()
