"""The five source clients against recorded fixtures (synthetic ones say so in their file name)."""
from pathlib import Path
import tempfile
import unittest
import urllib.parse

from research import arxiv, cache, crossref, http, openalex, records, semantic_scholar, unpaywall  # noqa: E402

from . import fakes  # noqa: E402

S2_HOST, OA_HOST, AX_HOST, CR_HOST, UP_HOST = ('api.semanticscholar.org', 'api.openalex.org', 'export.arxiv.org',
                                               'api.crossref.org', 'api.unpaywall.org')
WAKEFIELD = '10.1016/s0140-6736(97)11096-0'


class SourceCase(unittest.TestCase):
    module = None

    def setUp(self):
        self.transport = fakes.FakeTransport()
        self.clock = fakes.FakeClock()
        self.web = http.Http(transport=self.transport, clock=self.clock, sleep=self.clock.sleep)
        self.credentials = fakes.FakeCredentials()

    def source(self, secrets=None, store=None):
        if secrets is not None:
            self.credentials = fakes.FakeCredentials(secrets)
        return self.module.Source(http=self.web, credentials=self.credentials, cache=store)

    def params(self, index=-1):
        return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.transport.urls()[index]).query))


class SemanticScholarTests(SourceCase):
    module = semantic_scholar

    def test_lookup_by_arxiv_id(self):
        self.transport.add(S2_HOST, '/graph/v1/paper/ARXIV:1706.03762', ('semantic_scholar', 'lookup_arxiv'))
        paper = self.source().paper('arXiv:1706.03762v3')
        self.assertEqual(paper['title'], 'Attention is All you Need')
        self.assertEqual(paper['doi'], '10.48550/arxiv.1706.03762')
        self.assertEqual(paper['arxiv_id'], '1706.03762')
        self.assertEqual(paper['s2_id'], '204e3073870fae3d05bcbc2f6a8e263d9b72e776')
        self.assertEqual(paper['venue'], 'Neural Information Processing Systems')
        self.assertEqual(paper['authors'][0], 'Ashish Vaswani')
        self.assertEqual(paper['citation_count'], 203887)
        self.assertEqual(paper['year'], 2017)
        self.assertEqual(paper['oa_url'], 'https://arxiv.org/pdf/1706.03762')
        self.assertIsNone(paper['retracted'])
        self.assertEqual(paper['sources'], ['semantic_scholar'])
        self.assertNotIn('x-api-key', self.transport.requests[0]['headers'])

    def test_missing_doi_is_none_and_match_finds_by_title(self):
        self.transport.add(S2_HOST, '/graph/v1/paper/DOI:10.1038/nature14539', ('semantic_scholar', 'lookup_doi_lecun'))
        self.transport.add(S2_HOST, '/graph/v1/paper/search/match', ('semantic_scholar', 'match_title'))
        source = self.source()
        self.assertIsNone(source.paper('10.1038/nature14539'))
        match = source.match('Attention Is All You Need')
        self.assertEqual(match['arxiv_id'], '1706.03762')
        self.assertEqual(self.params()['query'], 'Attention Is All You Need')

    def test_search_with_year_and_key_header(self):
        self.transport.add(S2_HOST, '/graph/v1/paper/search', ('semantic_scholar', 'search_attention_2017'))
        papers = self.source(fakes.SECRETS).search('attention is all you need', year_from=2017, year_to=2017, limit=3)
        self.assertEqual(len(papers), 3)
        self.assertEqual(papers[0]['title'], 'Attention is All you Need')
        self.assertEqual(self.params()['year'], '2017')
        self.assertEqual(self.params()['limit'], '3')
        self.assertEqual(self.transport.requests[0]['headers']['x-api-key'], fakes.SECRETS['semantic_scholar'])

    def test_year_ranges(self):
        self.assertEqual(semantic_scholar._year_param(2015, 2020), '2015-2020')
        self.assertEqual(semantic_scholar._year_param(2015, None), '2015-')
        self.assertEqual(semantic_scholar._year_param(None, 2020), '-2020')
        self.assertIsNone(semantic_scholar._year_param(None, None))

    def test_citations_and_references(self):
        self.transport.add(S2_HOST, '/graph/v1/paper/ARXIV:1706.03762/citations', ('semantic_scholar', 'citations'))
        self.transport.add(S2_HOST, '/graph/v1/paper/ARXIV:1706.03762/references', ('semantic_scholar', 'references'))
        source = self.source()
        citing = source.citations('1706.03762', 'citations', limit=2)
        self.assertEqual([p['doi'] for p in citing], ['10.1016/j.rcim.2026.103375', '10.1016/j.rcim.2026.103392'])
        cited = source.citations('1706.03762', 'references', limit=2)
        self.assertEqual(cited[0]['title'], 'A Deep Reinforced Model for Abstractive Summarization')
        self.assertEqual(cited[1]['arxiv_id'], '1705.03122')
        with self.assertRaises(ValueError):
            source.citations('1706.03762', 'sideways')

    def test_openalex_ids_and_other_verbs_are_refused(self):
        source = self.source()
        with self.assertRaises(ValueError):
            source.paper('openalex:W2626778328')
        with self.assertRaisesRegex(ValueError, 'Semantic Scholar cannot give BibTeX.'):
            source.bibtex('10.1038/nature14539')
        self.assertFalse(source.can_lookup('openalex:W1'))
        self.assertTrue(source.can_lookup('s2:abc'))

    def test_shared_pool_429_becomes_rate_limited(self):
        self.transport.add(S2_HOST, '/graph/v1/paper/ARXIV:1706.03762', ('semantic_scholar', 'error_429_shared_pool'))
        with self.assertRaises(http.RateLimited):
            self.source().paper('1706.03762')
        self.assertEqual(len(self.transport.requests), 3)


class OpenAlexTests(SourceCase):
    module = openalex

    def test_lookup_rebuilds_inverted_abstract(self):
        self.transport.add(OA_HOST, '/works/doi:10.48550/arxiv.1706.03762', ('openalex', 'lookup_arxiv_doi_vaswani'))
        paper = self.source().paper('arXiv:1706.03762')
        self.assertEqual(paper['openalex_id'], 'W2626778328')
        self.assertEqual(paper['title'], 'Attention Is All You Need')
        self.assertTrue(paper['abstract'].startswith('The dominant sequence transduction models are based on complex'))
        self.assertEqual(paper['doi'], '10.48550/arxiv.1706.03762')
        self.assertEqual(paper['citation_count'], 151778)
        self.assertIs(paper['retracted'], False)
        self.assertEqual(paper['oa_url'], 'https://arxiv.org/pdf/1706.03762')
        self.assertEqual(paper['authors'][0], 'Ashish Vaswani')
        self.assertIn('select', self.params())

    def test_abstract_rebuild(self):
        self.assertEqual(openalex.abstract({'world': [1], 'Hello': [0], 'again': [3, 2]}), 'Hello world again again')
        self.assertIsNone(openalex.abstract(None))
        self.assertIsNone(openalex.abstract({}))

    def test_retracted_work(self):
        self.transport.add(OA_HOST, '/works/doi:' + WAKEFIELD, ('openalex', 'lookup_doi_wakefield'))
        paper = self.source().paper('https://doi.org/10.1016/S0140-6736(97)11096-0')
        self.assertIs(paper['retracted'], True)
        self.assertEqual(paper['venue'], 'The Lancet')
        self.assertIsNone(paper['oa_url'])

    def test_key_goes_in_authorization_header_only(self):
        self.transport.add(OA_HOST, '/works/doi:' + WAKEFIELD, ('openalex', 'lookup_doi_wakefield'))
        self.source(fakes.SECRETS).paper(WAKEFIELD)
        sent = self.transport.requests[0]
        self.assertEqual(sent['headers']['Authorization'], 'Bearer ' + fakes.SECRETS['openalex'])
        self.assertNotIn(fakes.SECRETS['openalex'], sent['url'])

    def test_search_synthetic(self):
        self.transport.add(OA_HOST, '/works', ('openalex', 'search_synthetic'), params={'search': 'attention'})
        papers = self.source().search('attention', year_from=2017, year_to=2017, limit=2)
        self.assertEqual([p['openalex_id'] for p in papers], ['W2626778328', 'W2963403868'])
        self.assertEqual(self.params()['filter'], 'publication_year:2017-2017')
        self.assertEqual(self.params()['per_page'], '2')
        self.assertEqual(openalex._year_filter(2015, None), 'publication_year:>2014')
        self.assertEqual(openalex._year_filter(None, 2015), 'publication_year:<2016')

    def test_keyless_search_on_spent_budget_is_rate_limited_without_body(self):
        self.transport.add(OA_HOST, '/works', ('openalex', 'error_429_daily_budget'))
        with self.assertRaises(http.RateLimited) as caught:
            self.source().search('attention')
        self.assertEqual(caught.exception.retry_after_s, 1433)
        self.assertNotIn('api-keys', str(caught.exception))

    def test_citations_from_doi_resolve_the_work_id_first(self):
        self.transport.add(OA_HOST, '/works/doi:10.48550/arxiv.1706.03762', ('openalex', 'referenced_works_synthetic'))
        self.transport.add(OA_HOST, '/works', ('openalex', 'cites_synthetic'), params={'filter': 'cites:W2626778328'})
        papers = self.source().citations('10.48550/arXiv.1706.03762', 'citations', limit=2)
        self.assertEqual([p['doi'] for p in papers], ['10.9999/synthetic-cites-1', '10.9999/synthetic-cites-2'])

    def test_references_list_referenced_works(self):
        self.transport.add(OA_HOST, '/works/W2626778328', ('openalex', 'referenced_works_synthetic'))
        self.transport.add(OA_HOST, '/works', ('openalex', 'references_list_synthetic'),
                           params={'filter': 'openalex:W2964308564|W2130942839'})
        papers = self.source().citations('openalex:W2626778328', 'references', limit=10)
        self.assertEqual([p['arxiv_id'] for p in papers], ['1409.0473', '1409.3215'])

    def test_fulltext_link(self):
        self.transport.add(OA_HOST, '/works/doi:10.48550/arxiv.1706.03762', ('openalex', 'lookup_arxiv_doi_vaswani'))
        link = self.source().fulltext('1706.03762')
        self.assertEqual(link['oa_url'], 'https://arxiv.org/pdf/1706.03762')

    def test_optional_key_status(self):
        source = self.source()
        self.assertEqual(source.status(), {'source': 'openalex', 'configured': False, 'required': False,
                                           'state': 'unchecked', 'detail': None})
        self.transport.add(OA_HOST, '/works/doi:10.1038/nature14539', ('openalex', 'lookup_doi_wakefield'))
        self.assertEqual(source.status(test=True)['state'], 'ready')


class ArxivTests(SourceCase):
    module = arxiv

    def test_lookup_reads_atom_and_strips_version(self):
        self.transport.add(AX_HOST, '/api/query', ('arxiv', 'lookup_1706.03762'), params={'id_list': '1706.03762'})
        paper = self.source().paper('arXiv:1706.03762v7')
        self.assertEqual(paper['arxiv_id'], '1706.03762')
        self.assertEqual(paper['title'], 'Attention Is All You Need')
        self.assertEqual(paper['year'], 2017)
        self.assertEqual(len(paper['authors']), 8)
        self.assertEqual(paper['authors'][-1], 'Illia Polosukhin')
        self.assertEqual(paper['url'], 'https://arxiv.org/abs/1706.03762')
        self.assertEqual(paper['oa_url'], 'https://arxiv.org/pdf/1706.03762')
        self.assertIsNone(paper['doi'])
        self.assertTrue(paper['abstract'].startswith('The dominant'))

    def test_unknown_id_is_none_and_error_entry_is_ignored(self):
        self.transport.add(AX_HOST, '/api/query', ('arxiv', 'lookup_nonexistent'), params={'id_list': '2999.99999'})
        self.assertIsNone(self.source().paper('2999.99999'))
        self.assertEqual(arxiv._entries(fakes.fixture('arxiv', 'lookup_malformed')[2].decode()), [])

    def test_malformed_request_is_bad_response(self):
        self.transport.add(AX_HOST, '/api/query', ('arxiv', 'lookup_malformed'))
        with self.assertRaises(http.BadResponse):
            self.source().paper('1706.00001')

    def test_search_query_is_encoded_and_dated(self):
        self.transport.add(AX_HOST, '/api/query', ('arxiv', 'search_title_2017'))
        papers = self.source().search('"attention is all you need" [x]', year_from=2017, year_to=2017, limit=3)
        self.assertEqual(papers[0]['arxiv_id'], '1706.03762')
        query = self.params()['search_query']
        self.assertEqual(query, 'all:attention AND all:is AND all:all AND all:you AND all:need AND all:x AND '
                                'submittedDate:[201701010000 TO 201712312359]')
        raw = self.transport.urls()[0]
        self.assertNotIn('[', raw)
        self.assertNotIn('"', raw)

    def test_bibtex_year_is_the_v1_year(self):
        self.transport.add('arxiv.org', '/bibtex/1706.03762', ('arxiv', 'bibtex_1706.03762'))
        self.transport.add(AX_HOST, '/api/query', ('arxiv', 'lookup_1706.03762'))
        text = self.source().bibtex('1706.03762v2')
        self.assertIn('year={2017}', text)
        self.assertNotIn('2023}', text)
        self.assertTrue(text.startswith('@misc{'))

    def test_fulltext_is_the_pdf_link(self):
        self.transport.add(AX_HOST, '/api/query', ('arxiv', 'lookup_1706.03762'))
        self.assertEqual(self.source().fulltext('1706.03762'),
                         {'oa_url': 'https://arxiv.org/pdf/1706.03762', 'license': None,
                          'version': 'submittedVersion', 'host_type': 'repository'})

    def test_doctype_is_refused(self):
        with self.assertRaises(http.BadResponse):
            arxiv._entries('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><feed/>')

    def test_status_without_credentials_is_configured(self):
        self.assertEqual(self.source().status()['configured'], True)


class CrossrefTests(SourceCase):
    module = crossref

    def test_lookup(self):
        self.transport.add(CR_HOST, '/works/10.1038/nature14539', ('crossref', 'lookup_lecun'))
        paper = self.source().paper('https://doi.org/10.1038/NATURE14539')
        self.assertEqual(paper['title'], 'Deep learning')
        self.assertEqual(paper['authors'], ['Yann LeCun', 'Yoshua Bengio', 'Geoffrey Hinton'])
        self.assertEqual(paper['year'], 2015)
        self.assertEqual(paper['venue'], 'Nature')
        self.assertEqual(paper['citation_count'], 79568)
        self.assertEqual(paper['url'], 'https://doi.org/10.1038/nature14539')
        self.assertIsNone(paper['retracted'])
        self.assertNotIn('mailto', self.params())

    def test_retraction_only_from_retraction_type(self):
        self.transport.add(CR_HOST, '/works/' + WAKEFIELD, ('crossref', 'lookup_wakefield_retracted'))
        paper = self.source().paper(WAKEFIELD)
        self.assertIs(paper['retracted'], True)
        self.assertTrue(paper['title'].startswith('RETRACTED:'))
        self.assertIsNone(crossref.retracted({'updated-by': [{'type': 'correction'}, {'type': 'erratum'}]}))
        self.assertIs(crossref.retracted({'updated-by': [{'type': 'Retraction'}]}), True)
        notices = fakes.fixture('crossref', 'retraction_notices_for_wakefield')
        import json
        for item in json.loads(notices[2])['message']['items']:
            self.assertIsNone(crossref.record(item)['retracted'])   # a notice is not itself retracted

    def test_datacite_doi_is_not_found(self):
        self.transport.add(CR_HOST, '/works/10.48550/arxiv.1706.03762', ('crossref', 'lookup_arxiv_datacite_doi'))
        source = self.source()
        self.assertIsNone(source._not_found_is_none(lambda: source._paper('doi', '10.48550/arxiv.1706.03762')))
        self.assertFalse(source.can_lookup('10.48550/arXiv.1706.03762'))   # parse_id makes it an arXiv ID

    def test_search_uses_list_pool_and_polite_mailto(self):
        self.transport.add(CR_HOST, '/works', ('crossref', 'search_bibliographic_2015'))
        papers = self.source(fakes.SECRETS).search('deep learning LeCun', year_from=2015, year_to=2015, limit=2)
        self.assertEqual(papers[0]['doi'], '10.1038/nature14539')
        params = self.params()
        self.assertEqual(params['filter'], 'from-pub-date:2015,until-pub-date:2015')
        self.assertEqual(params['mailto'], fakes.SECRETS['crossref_email'])
        self.assertEqual(params['rows'], '2')
        self.assertIn('updated-by', params['select'])

    def test_list_queries_wait_one_second(self):
        self.transport.add(CR_HOST, '/works', ('crossref', 'search_bibliographic_2015'))
        source = self.source()
        source.search('a')
        source.search('b')
        self.assertEqual(self.clock.sleeps, [1.0])

    def test_bibtex_transform(self):
        self.transport.add(CR_HOST, '/works/10.1038/nature14539/transform/application/x-bibtex',
                           ('crossref', 'bibtex_transform_lecun'))
        text = self.source().bibtex('10.1038/nature14539')
        self.assertTrue(text.startswith('@article{LeCun_2015,'))

    def test_bibtex_that_is_not_bibtex(self):
        self.transport.add(CR_HOST, '/works/10.1038/nature14539/transform/application/x-bibtex',
                           fakes.reply(200, text='<html>no</html>'))
        with self.assertRaises(http.BadResponse):
            self.source().bibtex('10.1038/nature14539')


class UnpaywallTests(SourceCase):
    module = unpaywall

    def test_requires_email(self):
        source = self.source()
        with self.assertRaises(http.NotConfigured):
            source.fulltext('10.1038/nature14539')
        self.assertEqual(self.transport.requests, [])
        self.assertEqual(source.status()['state'], 'needs_key')

    def test_fulltext_green(self):
        self.transport.add(UP_HOST, '/v2/10.1038/nature14539', ('unpaywall', 'lookup_lecun'))
        link = self.source(fakes.SECRETS).fulltext('10.1038/nature14539')
        self.assertTrue(link['oa_url'].startswith('https://'))
        self.assertEqual(link['host_type'], 'repository')
        self.assertEqual(link['license'], 'other-oa')
        self.assertEqual(self.params()['email'], fakes.SECRETS['unpaywall_email'])

    def test_closed_and_unknown(self):
        self.transport.add(UP_HOST, '/v2/' + WAKEFIELD, ('unpaywall', 'lookup_wakefield'))
        self.transport.add(UP_HOST, '/v2/10.9999/does-not-exist-0b', ('unpaywall', 'lookup_unknown'))
        source = self.source(fakes.SECRETS)
        self.assertIsNone(source.fulltext(WAKEFIELD))
        self.assertIsNone(source.fulltext('10.9999/does-not-exist-0b'))

    def test_paper_record(self):
        self.transport.add(UP_HOST, '/v2/10.1038/nature14539', ('unpaywall', 'lookup_lecun'))
        paper = self.source(fakes.SECRETS).paper('10.1038/nature14539')
        self.assertEqual(paper['title'], 'Deep learning')
        self.assertEqual(paper['venue'], 'Nature')
        self.assertTrue(paper['oa_url'].startswith('https://'))


class CacheThroughSourceTests(SourceCase):
    module = crossref

    def test_second_lookup_comes_from_cache_and_holds_no_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = cache.Cache(Path(tmp) / 'research-cache')
            self.transport.add(CR_HOST, '/works/10.1038/nature14539', ('crossref', 'lookup_lecun'))
            source = self.source(fakes.SECRETS, store)
            first = source.paper('10.1038/nature14539')
            self.assertEqual(source.paper('doi:10.1038/NATURE14539'), first)
            self.assertEqual(len(self.transport.requests), 1)
            self.assertEqual(store.hits, {'crossref': 1})
            for path in Path(tmp).rglob('*'):
                if path.is_file():
                    text = path.read_text(encoding='utf-8')
                    for secret in fakes.SECRETS.values():
                        self.assertNotIn(secret, text)

    def test_status_reports_keychain_errors(self):
        self.credentials = fakes.FakeCredentials(broken=True)
        row = crossref.Source(http=self.web, credentials=self.credentials, cache=None).status()
        self.assertEqual(row['state'], 'error')
        self.assertIn('Keychain', row['detail'])

    def test_status_test_call_maps_errors(self):
        self.transport.add(CR_HOST, '/works/10.1038/nature14539', fakes.reply(503, {'message': 'upstream words'}))
        row = self.source().status(test=True)
        self.assertEqual(row['state'], 'error')
        self.assertNotIn('upstream', row['detail'])


class ModuleShapeTests(unittest.TestCase):
    def test_each_source_declares_the_contract_attributes(self):
        for module in (semantic_scholar, openalex, arxiv, crossref, unpaywall):
            source = module.Source
            with self.subTest(source=source.name):
                self.assertEqual(source.hosts, http.HOSTS[source.name])
                self.assertEqual(source.title, http.TITLES[source.name])
                self.assertIn(source.credential_kind, ('api_key', 'email', None))
                self.assertTrue(source.help_url.startswith('https://'))
                self.assertTrue(set(source.capabilities) <= {'search', 'paper', 'citations', 'fulltext', 'bibtex',
                                                             'retraction'})
                self.assertTrue(records.parse_id(source.test_id)[0] in source.id_kinds)
        self.assertFalse(openalex.Source.required)
        self.assertTrue(unpaywall.Source.required)
        self.assertEqual(crossref.Source.credential, 'crossref_email')


if __name__ == '__main__':
    unittest.main()
