"""The deterministic citation checker (research/tools.md, "Citation checker"), with fake lookups only."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))

from research import citations


def record(title, *, authors=(), year=None, doi=None, arxiv_id=None, retracted=False, source='crossref', abstract=None):
    return {'v': 1, 'title': title, 'authors': list(authors), 'year': year, 'venue': None, 'doi': doi,
            'arxiv_id': arxiv_id, 's2_id': None, 'openalex_id': None, 'abstract': abstract, 'citation_count': None,
            'url': None, 'oa_url': None, 'retracted': retracted, 'sources': [source]}


VASWANI = record('Attention Is All You Need', authors=['Ashish Vaswani', 'Noam Shazeer'], year=2017,
                 doi='10.48550/arxiv.1706.03762', arxiv_id='1706.03762', source='arxiv')
LECUN = record('Deep learning', authors=['Yann LeCun', 'Yoshua Bengio', 'Geoffrey Hinton'], year=2015,
               doi='10.1038/nature14539')
WAKEFIELD = record('RETRACTED: Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive '
                   'developmental disorder in children', authors=['A.J Wakefield'], year=1998,
                   doi='10.1016/s0140-6736(97)11096-0', retracted=True)


class FakeLookup:
    """`lookup(source, verb, value)`: papers by id per source, search lists per source, skips per source."""

    def __init__(self, papers=None, searches=None, skip=None):
        self.papers = papers or {}      # (source, id) -> record
        self.searches = searches or {}  # source -> [records]
        self.skip = skip or {}          # source -> reason
        self.calls = []

    def __call__(self, source, verb, value):
        self.calls.append((source, verb, value))
        if source in self.skip:
            raise citations.Skipped(self.skip[source])
        if verb == 'paper':
            return self.papers.get((source, value))
        if verb == 'search':
            return list(self.searches.get(source, []))
        raise AssertionError(verb)


def one(report):
    return report['references'][0]


class NormalizeTests(unittest.TestCase):
    def test_raw_line_doi_title_and_year(self):
        ref = citations.normalize_reference({'raw': 'LeCun, Y., Bengio, Y. & Hinton, G. (2015). Deep learning. '
                                                    'Nature 521, 436–444. https://doi.org/10.1038/NATURE14539.'})
        self.assertEqual(ref['doi'], '10.1038/nature14539')
        self.assertEqual(ref['year'], 2015)
        self.assertEqual(ref['title'], 'Deep learning')
        self.assertEqual(ref['first_author'], None)

    def test_raw_line_quoted_title_and_arxiv(self):
        ref = citations.normalize_reference({'raw': 'A. Vaswani et al., “Attention is all you need,” '
                                                    'arXiv:1706.03762v5, 2017.'})
        self.assertEqual(ref['title'], 'Attention is all you need')
        self.assertEqual(ref['arxiv_id'], '1706.03762')
        self.assertEqual(ref['year'], 2017)

    def test_raw_line_longest_sentence_is_the_title(self):
        ref = citations.normalize_reference({'raw': 'Vaswani A, Shazeer N. Attention is all you need for sequence '
                                                    'transduction. NeurIPS. 2017'})
        self.assertEqual(ref['title'], 'Attention is all you need for sequence transduction')

    def test_given_fields_win_and_doi_prefixes_are_stripped(self):
        ref = citations.normalize_reference({'title': 'Deep learning', 'doi': 'https://doi.org/10.1038/Nature14539',
                                             'authors': ['LeCun, Yann'], 'year': '2015', 'raw': 'ignored 1999'})
        self.assertEqual((ref['title'], ref['doi'], ref['year'], ref['first_author']),
                         ('Deep learning', '10.1038/nature14539', 2015, 'lecun'))

    def test_surname_ignores_case_and_diacritics(self):
        self.assertEqual(citations.surname('José Álvarez'), 'alvarez')
        self.assertEqual(citations.surname('Álvarez, J.'), 'alvarez')
        self.assertEqual(citations.surname('A. Vaswani'), 'vaswani')
        self.assertEqual(citations.surname('A.J Wakefield'), 'wakefield')

    def test_title_similarity_strips_retracted_prefix(self):
        self.assertGreaterEqual(citations.similarity('RETRACTED: Deep learning', 'Deep Learning.'), 0.99)


class CheckTests(unittest.TestCase):
    def test_doi_found_in_crossref_is_verified(self):
        lookup = FakeLookup(papers={('crossref', '10.1038/nature14539'): LECUN})
        report = citations.check([{'title': 'Deep learning', 'authors': ['Yann LeCun'], 'year': 2015,
                                   'doi': '10.1038/nature14539'}], lookup, now=0)
        ref = one(report)
        self.assertEqual((ref['status'], ref['fields'], ref['source']), ('verified', [], 'crossref'))
        self.assertEqual(ref['match']['doi'], '10.1038/nature14539')
        self.assertEqual(report['summary'], {'verified': 1, 'mismatch': 0, 'not_found': 0, 'retracted': 0, 'unchecked': 0})
        self.assertEqual(report['v'], 1)
        self.assertEqual(report['checked_at'], '1970-01-01T00:00:00.000Z')
        self.assertEqual(lookup.calls, [('crossref', 'paper', '10.1038/nature14539')])

    def test_doi_falls_back_to_openalex(self):
        lookup = FakeLookup(papers={('openalex', '10.48550/arxiv.1706.03762'): dict(VASWANI, sources=['openalex'])})
        ref = one(citations.check([{'doi': '10.48550/arXiv.1706.03762'}], lookup, now=0))
        self.assertEqual((ref['status'], ref['source']), ('verified', 'openalex'))
        self.assertIsNone(ref['similarity'])

    def test_exact_doi_with_wrong_year_is_a_mismatch(self):
        lookup = FakeLookup(papers={('crossref', '10.1038/nature14539'): LECUN})
        ref = one(citations.check([{'title': 'Deep learning', 'year': 2019, 'doi': '10.1038/nature14539'}], lookup, now=0))
        self.assertEqual((ref['status'], ref['fields']), ('mismatch', ['year']))

    def test_year_within_one_is_accepted(self):
        lookup = FakeLookup(papers={('crossref', '10.1038/nature14539'): LECUN})
        ref = one(citations.check([{'title': 'Deep learning', 'year': 2016, 'doi': '10.1038/nature14539'}], lookup, now=0))
        self.assertEqual(ref['status'], 'verified')

    def test_exact_id_with_other_title_and_author_is_a_mismatch(self):
        lookup = FakeLookup(papers={('crossref', '10.1038/nature14539'): LECUN})
        ref = one(citations.check([{'title': 'Shallow networks for everyone', 'authors': ['Smith, J.'],
                                    'doi': '10.1038/nature14539'}], lookup, now=0))
        self.assertEqual((ref['status'], ref['fields']), ('mismatch', ['title', 'authors']))

    def test_arxiv_id_goes_to_arxiv_then_semantic_scholar(self):
        lookup = FakeLookup(papers={('semantic_scholar', 'arXiv:1706.03762'): dict(VASWANI, sources=['semantic_scholar'])},
                            skip={'arxiv': 'rate_limited'})
        ref = one(citations.check([{'title': 'Attention is All you Need', 'authors': ['A. Vaswani'], 'year': 2017,
                                    'arxiv_id': '1706.03762v7'}], lookup, now=0))
        self.assertEqual((ref['status'], ref['source']), ('verified', 'semantic_scholar'))
        self.assertEqual([c[0] for c in lookup.calls], ['arxiv', 'semantic_scholar'])

    def test_title_search_keeps_the_most_similar_candidate(self):
        lookup = FakeLookup(searches={
            'semantic_scholar': [record('Attention in neural networks', year=2016, source='semantic_scholar'),
                                 dict(VASWANI, sources=['semantic_scholar'])],
            'openalex': [record('Attention is all you need (comment)', year=2018, source='openalex')]})
        ref = one(citations.check([{'title': 'Attention is all you need', 'authors': ['Vaswani'], 'year': 2017}],
                                  lookup, now=0))
        self.assertEqual((ref['status'], ref['source']), ('verified', 'semantic_scholar'))
        self.assertEqual(ref['match']['title'], 'Attention Is All You Need')
        self.assertGreaterEqual(ref['similarity'], 0.99)
        self.assertEqual([c[:2] for c in lookup.calls], [('semantic_scholar', 'search'), ('openalex', 'search')])

    def test_close_title_below_threshold_is_a_mismatch(self):
        lookup = FakeLookup(searches={'semantic_scholar': [record('Attention is all you need in speech',
                                                                  year=2021, source='semantic_scholar')]})
        ref = one(citations.check([{'title': 'Attention is all you need', 'year': 2021}], lookup, now=0))
        self.assertEqual(ref['status'], 'mismatch')
        self.assertEqual(ref['fields'], ['title'])
        self.assertTrue(0.75 <= ref['similarity'] < 0.90)

    def test_wrong_first_author_on_a_title_match_is_a_mismatch(self):
        lookup = FakeLookup(searches={'openalex': [dict(LECUN, sources=['openalex'])]})
        ref = one(citations.check([{'title': 'Deep Learning', 'authors': ['Goodfellow, Ian'], 'year': 2015}], lookup, now=0))
        self.assertEqual((ref['status'], ref['fields']), ('mismatch', ['authors']))

    def test_title_match_with_a_different_doi_is_a_mismatch(self):
        lookup = FakeLookup(searches={'openalex': [dict(LECUN, sources=['openalex'])]})
        ref = one(citations.check([{'title': 'Deep learning', 'doi': '10.9999/made.up'}], lookup, now=0))
        self.assertEqual((ref['status'], ref['fields']), ('mismatch', ['doi']))
        self.assertEqual([c[:2] for c in lookup.calls][:2], [('crossref', 'paper'), ('openalex', 'paper')])

    def test_nothing_similar_is_not_found(self):
        lookup = FakeLookup(searches={'semantic_scholar': [record('Graph kernels', source='semantic_scholar')]})
        ref = one(citations.check([{'title': 'A paper that does not exist about quantum llamas'}], lookup, now=0))
        self.assertEqual((ref['status'], ref['match']), ('not_found', None))
        self.assertEqual(ref['fields'], [])

    def test_retracted_overrides_everything(self):
        lookup = FakeLookup(papers={('crossref', '10.1016/s0140-6736(97)11096-0'): WAKEFIELD})
        report = citations.check([{'title': 'Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive '
                                            'developmental disorder in children', 'year': 1998,
                                   'authors': ['Wakefield, A. J.'], 'doi': '10.1016/S0140-6736(97)11096-0'}], lookup, now=0)
        self.assertEqual(one(report)['status'], 'retracted')
        self.assertEqual(report['summary']['retracted'], 1)

    def test_every_source_skipped_is_unchecked_with_reason(self):
        lookup = FakeLookup(skip={'semantic_scholar': 'not_configured', 'openalex': 'denied'})
        ref = one(citations.check([{'title': 'Deep learning'}], lookup, now=0))
        self.assertEqual(ref['status'], 'unchecked')
        self.assertEqual(ref['reason'], 'semantic_scholar: not_configured, openalex: denied')
        self.assertIsNone(ref['match'])

    def test_one_source_answering_not_found_is_enough(self):
        lookup = FakeLookup(skip={'openalex': 'rate_limited'})
        ref = one(citations.check([{'title': 'Deep learning'}], lookup, now=0))
        self.assertEqual(ref['status'], 'not_found')

    def test_doi_not_found_falls_back_to_title_search(self):
        lookup = FakeLookup(searches={'semantic_scholar': [dict(LECUN, sources=['semantic_scholar'])]})
        ref = one(citations.check([{'title': 'Deep learning', 'doi': '10.1038/nature14539'}], lookup, now=0))
        self.assertEqual((ref['status'], ref['source']), ('verified', 'semantic_scholar'))

    def test_a_reference_with_nothing_to_check_is_unchecked(self):
        ref = one(citations.check([{'raw': '???'}], FakeLookup(), now=0))
        self.assertEqual(ref['status'], 'unchecked')

    def test_lookup_failures_of_any_kind_become_skips(self):
        def broken(source, verb, value):
            raise RuntimeError('boom with secret-ish upstream text')
        ref = one(citations.check([{'title': 'Deep learning'}], broken, now=0))
        self.assertEqual(ref['status'], 'unchecked')
        self.assertNotIn('boom', ref['reason'])

    def test_report_keeps_input_index_and_drops_abstracts(self):
        lookup = FakeLookup(papers={('crossref', '10.1038/nature14539'): dict(LECUN, abstract='x' * 4000)})
        report = citations.check([{'title': 'Deep learning', 'doi': '10.1038/nature14539'},
                                  {'title': 'Nothing at all here'}], lookup, now=0)
        self.assertEqual([r['index'] for r in report['references']], [0, 1])
        self.assertEqual(report['references'][0]['input'], {'title': 'Deep learning', 'doi': '10.1038/nature14539'})
        self.assertNotIn('abstract', report['references'][0]['match'])

    def test_bad_arguments_are_refused(self):
        for bad in (None, [], [{}] * 201, ['text'], [{'title': 5}], [{'year': 'soon', 'title': 'x'}]):
            with self.assertRaises(ValueError):
                citations.check(bad, FakeLookup(), now=0)


class SourceLookupTests(unittest.TestCase):
    class NotFound(ValueError):
        code = 'not_found'

    class Limited(ValueError):
        code = 'rate_limited'

    def test_maps_sources_denials_and_errors(self):
        test = self

        class Source:
            def __init__(self, name):
                self.name = name

            def paper(self, identifier):
                if self.name == 'crossref':
                    raise test.NotFound('gone')
                return LECUN

            def search(self, query, *, year_from=None, year_to=None, limit=10):
                raise test.Limited('slow down')
        allowed = {'crossref': True, 'openalex': True, 'semantic_scholar': True, 'arxiv': False}
        lookup = citations.source_lookup({n: Source(n) for n in allowed}, lambda source: allowed[source])
        self.assertIsNone(lookup('crossref', 'paper', '10.1/x'))
        self.assertEqual(lookup('openalex', 'paper', '10.1/x'), LECUN)
        with self.assertRaisesRegex(citations.Skipped, 'denied'):
            lookup('arxiv', 'paper', 'arXiv:1706.03762')
        with self.assertRaisesRegex(citations.Skipped, 'rate_limited'):
            lookup('semantic_scholar', 'search', 'Deep learning')
        with self.assertRaisesRegex(citations.Skipped, 'not_configured'):
            lookup('unpaywall', 'paper', '10.1/x')


if __name__ == '__main__':
    unittest.main()
