"""research/__init__.py: registry, scope filter, authorization per source call, the five tools, limits, key safety."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

import research  # noqa: E402
from research import http  # noqa: E402

from . import fakes  # noqa: E402

S2_HOST, OA_HOST, AX_HOST, CR_HOST, UP_HOST = ('api.semanticscholar.org', 'api.openalex.org', 'export.arxiv.org',
                                               'api.crossref.org', 'api.unpaywall.org')
ALL_ALLOW = {'research': {'sources': {name: 'allow' for name in research.SOURCES}}}


class FakeContext:
    def __init__(self, scope=ALL_ALLOW, deny=()):
        self.scope = scope
        self.deny = set(deny)
        self.requests = []

    def authorize(self, request):
        self.requests.append(dict(request))
        return {'decision': 'deny' if request['source'] in self.deny else 'allow'}


class DispatchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.transport = fakes.FakeTransport()
        self.clock = fakes.FakeClock()
        self.app = types.SimpleNamespace(
            storage=Path(self.tmp.name),
            http=http.Http(transport=self.transport, clock=self.clock, sleep=self.clock.sleep),
            research_credentials=fakes.FakeCredentials(fakes.SECRETS))
        self.ctx = FakeContext()

    def call(self, name, arguments, ctx=None):
        result = research.dispatch(self.app, ctx or self.ctx, name, arguments)
        json.dumps(result)   # always plain JSON
        return result


class RegistryTests(DispatchCase):
    def test_sources_in_contract_order_built_once(self):
        built = research.sources(self.app)
        self.assertEqual([s.name for s in built], list(research.SOURCES))
        self.assertIs(research.sources(self.app)[0], built[0])
        self.assertIs(built[0].http, self.app.http)
        self.assertEqual(built[0].cache.root, self.app.storage / 'research-cache')

    def test_enabled_reads_scope_research_sources(self):
        self.assertEqual(research.enabled({}), [])
        self.assertEqual(research.enabled(None), [])
        self.assertEqual(research.enabled({'research': {'sources': {'arxiv': 'ask', 'crossref': 'off',
                                                                    'openalex': 'allow', 'bogus': 'allow'}}}),
                         ['openalex', 'arxiv'])

    def test_parse_id_is_exported(self):
        self.assertEqual(research.parse_id('arXiv:1706.03762v2'), ('arxiv', '1706.03762'))

    def test_unknown_tool_and_bad_arguments_fail_the_call(self):
        cases = [('research_nope', {}), ('research_search', {}), ('research_search', {'query': ''}),
                 ('research_search', {'query': 'x' * 501}), ('research_search', {'query': 'x', 'limit': 51}),
                 ('research_search', {'query': 'x', 'limit': True}), ('research_search', {'query': 'x', 'sources': ['x']}),
                 ('research_search', {'query': 'x', 'year_from': 2020, 'year_to': 2010}),
                 ('research_search', {'query': 'x', 'extra': 1}), ('research_paper', {'id': 'nope'}),
                 ('research_citations', {'id': '10.1234/x', 'direction': 'up'}),
                 ('research_citations', {'id': '10.1234/x', 'direction': 'citations', 'limit': 101}),
                 ('research_bibtex', {'ids': []}), ('research_bibtex', {'ids': ['x'] * 101}),
                 ('verify_citations', {'references': []}), ('research_search', 'not a dict')]
        for name, arguments in cases:
            with self.subTest(name=name, arguments=arguments):
                with self.assertRaises(ValueError):
                    self.call(name, arguments)
        self.assertEqual(self.transport.requests, [])
        self.assertEqual(self.ctx.requests, [])


class SearchTests(DispatchCase):
    def add_search_routes(self):
        self.transport.add(S2_HOST, '/graph/v1/paper/search', ('semantic_scholar', 'search_attention_2017'))
        self.transport.add(OA_HOST, '/works', ('openalex', 'search_synthetic'))
        self.transport.add(AX_HOST, '/api/query', ('arxiv', 'search_title_2017'))
        self.transport.add(CR_HOST, '/works', ('crossref', 'search_bibliographic_2015'))

    def test_merges_across_sources_and_authorizes_each(self):
        self.add_search_routes()
        result = self.call('research_search', {'query': 'attention is all you need', 'limit': 10})
        self.assertEqual(result['searched'], ['semantic_scholar', 'openalex', 'arxiv', 'crossref'])
        self.assertEqual(result['skipped'], [])
        vaswani = [p for p in result['papers'] if p['arxiv_id'] == '1706.03762']
        self.assertEqual(len(vaswani), 1)
        self.assertEqual(vaswani[0]['sources'], ['openalex', 'semantic_scholar', 'arxiv'])
        self.assertEqual(result['papers'][0]['arxiv_id'], '1706.03762')
        self.assertLessEqual(len(result['papers']), 10)
        self.assertEqual(self.ctx.requests, [{'category': 'research', 'source': s, 'tool': 'research_search'}
                                             for s in ('semantic_scholar', 'openalex', 'arxiv', 'crossref')])

    def test_off_denied_unsupported_and_failed_sources_are_skipped(self):
        self.transport.add(S2_HOST, '/graph/v1/paper/search', ('semantic_scholar', 'error_429_shared_pool'))
        self.transport.add(AX_HOST, '/api/query', ('arxiv', 'search_title_2017'))
        scope = {'research': {'sources': {'semantic_scholar': 'allow', 'openalex': 'ask', 'arxiv': 'allow',
                                          'unpaywall': 'allow'}}}
        ctx = FakeContext(scope, deny={'openalex'})
        result = self.call('research_search', {'query': 'attention', 'sources': ['unpaywall', 'arxiv', 'crossref',
                                                                                 'openalex', 'semantic_scholar']}, ctx)
        self.assertEqual(result['searched'], ['arxiv'])
        self.assertEqual(result['skipped'], [{'source': 'semantic_scholar', 'reason': 'rate_limited'},
                                             {'source': 'openalex', 'reason': 'denied'},
                                             {'source': 'crossref', 'reason': 'off'},
                                             {'source': 'unpaywall', 'reason': 'unsupported'}])
        self.assertEqual([r['source'] for r in ctx.requests], ['semantic_scholar', 'openalex', 'arxiv'])
        self.assertEqual(result['papers'][0]['arxiv_id'], '1706.03762')

    def test_limit_cuts_merged_list(self):
        self.add_search_routes()
        result = self.call('research_search', {'query': 'attention', 'limit': 2})
        self.assertEqual(len(result['papers']), 2)

    def test_result_is_capped_at_64_kb(self):
        many = [{'paperId': str(i), 'title': 'Paper %d %s' % (i, 'x' * 900), 'year': 2000 + i % 20,
                 'abstract': 'y' * 4000, 'authors': [{'name': 'A%d' % i}]} for i in range(50)]
        self.transport.add(S2_HOST, '/graph/v1/paper/search', fakes.reply(body={'data': many}))
        result = self.call('research_search', {'query': 'x', 'sources': ['semantic_scholar'], 'limit': 50})
        self.assertTrue(result['truncated'])
        self.assertLessEqual(len(json.dumps(result).encode('utf-8')), research.RESULT_LIMIT)
        self.assertGreater(len(result['papers']), 5)


class PaperTests(DispatchCase):
    def test_doi_merges_every_source_that_can_look_it_up(self):
        doi = '10.1038/nature14539'
        self.transport.add(S2_HOST, '/graph/v1/paper/DOI:' + doi, ('semantic_scholar', 'lookup_doi_lecun'))
        self.transport.add(S2_HOST, '/graph/v1/paper/search/match',
                           fakes.reply(body={'data': [{'paperId': 'p1', 'title': 'Deep learning', 'year': 2015,
                                                       'externalIds': {'DOI': '10.1038/NATURE14539'},
                                                       'abstract': 's2 abstract'}]}))
        self.transport.add(OA_HOST, '/works/doi:' + doi, fakes.reply(body={
            'id': 'https://openalex.org/W1', 'doi': 'https://doi.org/' + doi, 'display_name': 'Deep learning',
            'publication_year': 2015, 'is_retracted': False}))
        self.transport.add(CR_HOST, '/works/' + doi, ('crossref', 'lookup_lecun'))
        self.transport.add(UP_HOST, '/v2/' + doi, ('unpaywall', 'lookup_lecun'))
        result = self.call('research_paper', {'id': 'https://doi.org/10.1038/nature14539'})
        paper = result['paper']
        self.assertEqual(paper['title'], 'Deep learning')
        self.assertEqual(paper['citation_count'], 79568)
        self.assertEqual(paper['openalex_id'], 'W1')
        self.assertEqual(paper['s2_id'], 'p1')       # from the title-match fallback
        self.assertTrue(paper['oa_url'].startswith('https://'))
        self.assertEqual(result['sources'], ['crossref', 'openalex', 'semantic_scholar', 'unpaywall'])
        self.assertNotIn('arxiv', [r['source'] for r in self.ctx.requests])

    def test_nothing_found(self):
        self.transport.add(AX_HOST, '/api/query', ('arxiv', 'lookup_nonexistent'))
        self.transport.add(S2_HOST, '/graph/v1/paper/ARXIV:2999.99999', ('semantic_scholar', 'lookup_nonexistent'))
        self.transport.add(OA_HOST, '/works/doi:10.48550/arxiv.2999.99999', fakes.reply(404, {}))
        result = self.call('research_paper', {'id': '2999.99999'})
        self.assertEqual(result, {'paper': None, 'sources': [], 'skipped': []})


class CitationsTests(DispatchCase):
    def test_semantic_scholar_first(self):
        self.transport.add(S2_HOST, '/graph/v1/paper/ARXIV:1706.03762/references', ('semantic_scholar', 'references'))
        result = self.call('research_citations', {'id': 'arXiv:1706.03762', 'direction': 'references', 'limit': 2})
        self.assertEqual(result['source'], 'semantic_scholar')
        self.assertEqual(len(result['papers']), 2)

    def test_openalex_fallback_when_semantic_scholar_fails(self):
        self.transport.add(S2_HOST, '/graph/v1/paper/ARXIV:1706.03762/citations', ('semantic_scholar', 'error_429_shared_pool'))
        self.transport.add(OA_HOST, '/works/doi:10.48550/arxiv.1706.03762', ('openalex', 'referenced_works_synthetic'))
        self.transport.add(OA_HOST, '/works', ('openalex', 'cites_synthetic'))
        result = self.call('research_citations', {'id': '1706.03762', 'direction': 'citations'})
        self.assertEqual(result['source'], 'openalex')
        self.assertEqual(result['skipped'], [{'source': 'semantic_scholar', 'reason': 'rate_limited'}])
        self.assertEqual(len(result['papers']), 2)

    def test_no_source_can_answer(self):
        ctx = FakeContext({'research': {'sources': {'arxiv': 'allow'}}})
        result = self.call('research_citations', {'id': '1706.03762', 'direction': 'citations'}, ctx)
        self.assertEqual(result['papers'], [])
        self.assertIsNone(result['source'])
        self.assertEqual(result['skipped'], [{'source': 'semantic_scholar', 'reason': 'off'},
                                             {'source': 'openalex', 'reason': 'off'}])


class FulltextTests(DispatchCase):
    def test_doi_from_unpaywall(self):
        self.transport.add(UP_HOST, '/v2/10.1038/nature14539', ('unpaywall', 'lookup_lecun'))
        result = self.call('research_fulltext', {'id': '10.1038/nature14539'})
        self.assertEqual(result['source'], 'unpaywall')
        self.assertTrue(result['oa_url'].startswith('https://'))
        self.assertEqual(set(result), {'oa_url', 'license', 'version', 'host_type', 'source', 'skipped'})

    def test_unpaywall_without_email_falls_back_to_openalex(self):
        self.app.research_credentials = fakes.FakeCredentials({})
        self.transport.add(OA_HOST, '/works/doi:10.1016/s0140-6736(97)11096-0', ('openalex', 'lookup_doi_wakefield'))
        result = self.call('research_fulltext', {'id': '10.1016/S0140-6736(97)11096-0'})
        self.assertEqual(result['oa_url'], None)
        self.assertEqual(result['skipped'], [{'source': 'unpaywall', 'reason': 'not_configured'}])

    def test_arxiv_id_from_arxiv(self):
        self.transport.add(AX_HOST, '/api/query', ('arxiv', 'lookup_1706.03762'))
        result = self.call('research_fulltext', {'id': 'arXiv:1706.03762'})
        self.assertEqual(result['oa_url'], 'https://arxiv.org/pdf/1706.03762')
        self.assertEqual(result['source'], 'arxiv')


class BibtexTests(DispatchCase):
    def test_entries_per_id(self):
        self.transport.add(CR_HOST, '/works/10.1038/nature14539/transform/application/x-bibtex',
                           ('crossref', 'bibtex_transform_lecun'))
        self.transport.add('arxiv.org', '/bibtex/1706.03762', ('arxiv', 'bibtex_1706.03762'))
        self.transport.add(AX_HOST, '/api/query', ('arxiv', 'lookup_1706.03762'))
        self.transport.add(CR_HOST, '/works/10.9999/missing/transform/application/x-bibtex', fakes.reply(404, text='x'))
        result = self.call('research_bibtex', {'ids': ['10.1038/nature14539', 'https://doi.org/10.48550/arXiv.1706.03762',
                                                       'openalex:W1', '10.9999/missing', 'junk']})
        entries = result['entries']
        self.assertTrue(entries[0]['bibtex'].startswith('@article{LeCun_2015'))
        self.assertIsNone(entries[0]['error'])
        self.assertIn('year={2017}', entries[1]['bibtex'])
        self.assertEqual([e['error'] for e in entries[2:]], ['unsupported', 'not_found', 'invalid_id'])
        self.assertEqual([e['id'] for e in entries][0], '10.1038/nature14539')
        # One authorization per source per call.
        self.assertEqual([r['source'] for r in self.ctx.requests], ['crossref', 'arxiv'])

    def test_denied_source(self):
        ctx = FakeContext(deny={'crossref'})
        result = self.call('research_bibtex', {'ids': ['10.1038/nature14539']}, ctx)
        self.assertEqual(result['entries'], [{'id': '10.1038/nature14539', 'bibtex': None, 'error': 'denied'}])


class VerifyTests(DispatchCase):
    def test_not_available_until_the_checker_exists(self):
        with mock.patch.object(research, '_citations_module', return_value=None):
            with self.assertRaisesRegex(ValueError, 'Citation checking is not available yet.'):
                self.call('verify_citations', {'references': [{'title': 'X'}]})

    def test_checker_gets_a_lookup_that_authorizes(self):
        self.transport.add(CR_HOST, '/works/10.1038/nature14539', ('crossref', 'lookup_lecun'))
        seen = {}

        def check(references, lookup):
            seen['paper'] = lookup.paper('crossref', '10.1038/nature14539')
            with self.assertRaises(research.Skipped) as caught:
                lookup.search('openalex', 'deep learning')
            seen['reason'] = caught.exception.reason
            return {'v': 1, 'summary': {}, 'references': [{'index': 0}]}

        ctx = FakeContext(deny={'openalex'})
        with mock.patch.object(research, '_citations_module', return_value=types.SimpleNamespace(check=check)):
            report = self.call('verify_citations', {'references': [{'doi': '10.1038/nature14539'}]}, ctx)
        self.assertEqual(report['references'], [{'index': 0}])
        self.assertEqual(seen['paper']['title'], 'Deep learning')
        self.assertEqual(seen['reason'], 'denied')
        self.assertEqual([(r['source'], r['tool']) for r in ctx.requests],
                         [('crossref', 'verify_citations'), ('openalex', 'verify_citations')])


class KeySafetyTests(DispatchCase):
    """No key or email leaves except in its documented field, and none reaches a result or the cache."""

    def test_identity_only_in_documented_fields(self):
        doi = '10.1038/nature14539'
        self.transport.add(S2_HOST, '/graph/v1/paper/search', ('semantic_scholar', 'search_attention_2017'))
        self.transport.add(OA_HOST, '/works', ('openalex', 'search_synthetic'))
        self.transport.add(AX_HOST, '/api/query', ('arxiv', 'search_title_2017'))
        self.transport.add(CR_HOST, '/works', ('crossref', 'search_bibliographic_2015'))
        self.transport.add(CR_HOST, '/works/' + doi, ('crossref', 'lookup_lecun'))
        self.transport.add(CR_HOST, '/works/%s/transform/application/x-bibtex' % doi, ('crossref', 'bibtex_transform_lecun'))
        self.transport.add(S2_HOST, '/graph/v1/paper/DOI:' + doi, ('semantic_scholar', 'lookup_doi_lecun'))
        self.transport.add(S2_HOST, '/graph/v1/paper/search/match', ('semantic_scholar', 'match_title'))
        self.transport.add(OA_HOST, '/works/doi:' + doi, ('openalex', 'lookup_doi_wakefield'))
        self.transport.add(UP_HOST, '/v2/' + doi, ('unpaywall', 'lookup_lecun'))
        results = [self.call('research_search', {'query': 'attention'}),
                   self.call('research_paper', {'id': doi}),
                   self.call('research_fulltext', {'id': doi}),
                   self.call('research_bibtex', {'ids': [doi]})]
        allowed = {
            'semantic_scholar': lambda r: r['headers'].get('x-api-key'),
            'openalex': lambda r: r['headers'].get('Authorization', '')[len('Bearer '):],
            'crossref_email': lambda r: dict(_query(r['url'])).get('mailto'),
            'unpaywall_email': lambda r: dict(_query(r['url'])).get('email'),
        }
        for request in self.transport.requests:
            for account, secret in fakes.SECRETS.items():
                carriers = []
                if secret in request['url']:
                    carriers.append('url')
                carriers += ['header:' + k for k, v in request['headers'].items() if secret in v]
                if not carriers:
                    continue
                with self.subTest(url=request['url'], account=account):
                    self.assertEqual(allowed[account](request), secret)
                    self.assertEqual(len(carriers), 1)
            self.assertEqual(request['headers']['User-Agent'], http.USER_AGENT)
        text = json.dumps(results)
        for secret in fakes.SECRETS.values():
            self.assertNotIn(secret, text)
        for path in self.app.storage.rglob('*'):
            if path.is_file():
                content = path.read_text(encoding='utf-8')
                for secret in fakes.SECRETS.values():
                    self.assertNotIn(secret, content)
        hosts = {_host(r['url']) for r in self.transport.requests}
        self.assertTrue(hosts <= {h for hs in http.HOSTS.values() for h in hs})


def _query(url):
    import urllib.parse
    return urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)


def _host(url):
    import urllib.parse
    return urllib.parse.urlsplit(url).hostname


if __name__ == '__main__':
    unittest.main()
