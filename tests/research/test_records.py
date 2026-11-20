"""research/records.py: identifiers, the normalized record, titles and merging."""
import unittest

from research import records  # noqa: E402


class IdentifierTests(unittest.TestCase):
    def test_parse_id_forms(self):
        cases = {
            '10.1038/nature14539': ('doi', '10.1038/nature14539'),
            'https://doi.org/10.1038/NATURE14539': ('doi', '10.1038/nature14539'),
            'http://dx.doi.org/10.1038/nature14539': ('doi', '10.1038/nature14539'),
            'doi:10.1016/S0140-6736(97)11096-0': ('doi', '10.1016/s0140-6736(97)11096-0'),
            ' DOI: 10.1038/nature14539 ': ('doi', '10.1038/nature14539'),
            '10.48550/arXiv.1706.03762': ('arxiv', '1706.03762'),
            'https://doi.org/10.48550/arxiv.1706.03762v2': ('arxiv', '1706.03762'),
            'arXiv:1706.03762': ('arxiv', '1706.03762'),
            'arxiv:1706.03762v5': ('arxiv', '1706.03762'),
            '1706.03762': ('arxiv', '1706.03762'),
            '2101.00001v12': ('arxiv', '2101.00001'),
            'arXiv:hep-th/9901001v2': ('arxiv', 'hep-th/9901001'),
            'https://arxiv.org/abs/1706.03762v7': ('arxiv', '1706.03762'),
            's2:204e3073870fae3d05bcbc2f6a8e263d9b72e776': ('s2', '204e3073870fae3d05bcbc2f6a8e263d9b72e776'),
            's2:CorpusId:13756489': ('s2', 'CorpusId:13756489'),
            'openalex:W2626778328': ('openalex', 'W2626778328'),
            'openalex:w2626778328': ('openalex', 'W2626778328'),
            'https://openalex.org/W2626778328': ('openalex', 'W2626778328'),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(records.parse_id(text), expected)

    def test_parse_id_refuses_junk(self):
        for text in ('', 'not-an-id', '10.1/', 'hep-th/9901001', 's2:', 's2:has space', 'openalex:A123',
                     '10.1038/nat\x00ure', 'x' * 600, None, 12):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    records.parse_id(text)

    def test_normalize_doi_and_arxiv(self):
        self.assertEqual(records.normalize_doi('https://doi.org/10.1016/S0140-6736(97)11096-0'),
                         '10.1016/s0140-6736(97)11096-0')
        self.assertIsNone(records.normalize_doi('nope'))
        self.assertIsNone(records.normalize_doi(None))
        self.assertEqual(records.normalize_arxiv('1706.03762v7'), '1706.03762')
        self.assertEqual(records.arxiv_from_doi('10.48550/arxiv.1706.03762'), '1706.03762')
        self.assertIsNone(records.arxiv_from_doi('10.1038/nature14539'))


class RecordTests(unittest.TestCase):
    def test_make_fills_every_field_and_derives_arxiv_from_doi(self):
        record = records.make('openalex', title='  Attention\nIs All\tYou Need ', doi='https://doi.org/10.48550/ARXIV.1706.03762')
        self.assertEqual(set(record), set(records.FIELDS))
        self.assertEqual(record['v'], 1)
        self.assertEqual(record['title'], 'Attention Is All You Need')
        self.assertEqual(record['doi'], '10.48550/arxiv.1706.03762')
        self.assertEqual(record['arxiv_id'], '1706.03762')
        self.assertEqual(record['authors'], [])
        self.assertIsNone(record['retracted'])
        self.assertEqual(record['sources'], ['openalex'])

    def test_text_limits_and_control_characters(self):
        record = records.make('crossref', title='a\x00b' + 'x' * 2000, abstract='y' * 5000,
                              authors=['A\x07 B', '', None, 'C'])
        self.assertEqual(len(record['title']), 1000)
        self.assertTrue(record['title'].endswith('…'))
        self.assertTrue(record['title'].startswith('abx'))
        self.assertEqual(len(record['abstract']), 4000)
        self.assertEqual(record['authors'], ['A B', 'C'])

    def test_links_must_be_https(self):
        record = records.make('openalex', url='http://arxiv.org/abs/1', oa_url='javascript:alert(1)')
        self.assertIsNone(record['url'])
        self.assertIsNone(record['oa_url'])
        self.assertEqual(records.make('arxiv', url='https://arxiv.org/abs/1')['url'], 'https://arxiv.org/abs/1')

    def test_year_and_count_validation(self):
        record = records.make('crossref', year='2015', citation_count=-3)
        self.assertEqual(record['year'], 2015)
        self.assertIsNone(record['citation_count'])
        self.assertIsNone(records.make('crossref', year=True)['year'])


class TitleTests(unittest.TestCase):
    def test_source_formatting_markup_is_removed_but_other_angle_brackets_stay(self):
        self.assertEqual(records.clean_text('Hubble constant to 1 km s <sup>−1</sup> Mpc<SUB>0</SUB> <jats:italic>H</jats:italic>'),
                         'Hubble constant to 1 km s −1 Mpc0 H')
        self.assertEqual(records.clean_text('p < 0.05 and <img src=x onerror=1>'), 'p < 0.05 and <img src=x onerror=1>')

    def test_normalize_title(self):
        self.assertEqual(records.normalize_title('Attention is All you Need'), 'attention is all you need')
        self.assertEqual(records.normalize_title('RETRACTED: Ileal-lymphoid  hyperplasia.'), 'ileal lymphoid hyperplasia')
        self.assertEqual(records.normalize_title('Café Über'), 'cafe uber')
        self.assertEqual(records.normalize_title(None), '')

    def test_title_similarity(self):
        self.assertEqual(records.title_similarity('Attention is All you Need', 'Attention Is All You Need.'), 1.0)
        self.assertLess(records.title_similarity('Deep learning', 'Attention is all you need'), 0.5)
        self.assertEqual(records.title_similarity('', ''), 0.0)


def rec(source, **fields):
    return records.make(source, **fields)


class MergeTests(unittest.TestCase):
    def test_same_doi_merges_with_source_priority(self):
        merged = records.merge([
            rec('semantic_scholar', title='Deep Learning', doi='10.1038/NATURE14539', year=2015, citation_count=5,
                s2_id='abc', abstract='s2 abstract'),
            rec('crossref', title='Deep learning', doi='10.1038/nature14539', year=2015, citation_count=79568,
                venue='Nature', authors=['Yann LeCun']),
            rec('openalex', title='Deep learning', doi='10.1038/nature14539', year=2015, openalex_id='W1',
                abstract='oa abstract', retracted=False),
        ])
        self.assertEqual(len(merged), 1)
        paper = merged[0]
        self.assertEqual(paper['title'], 'Deep learning')
        self.assertEqual(paper['citation_count'], 79568)
        self.assertEqual(paper['abstract'], 'oa abstract')
        self.assertEqual(paper['s2_id'], 'abc')
        self.assertEqual(paper['openalex_id'], 'W1')
        self.assertEqual(paper['authors'], ['Yann LeCun'])
        self.assertIs(paper['retracted'], False)
        self.assertEqual(paper['sources'], ['crossref', 'openalex', 'semantic_scholar'])

    def test_arxiv_id_merges_preprint_and_venue_record(self):
        merged = records.merge([
            rec('arxiv', title='Attention Is All You Need', arxiv_id='1706.03762v7', year=2017,
                oa_url='https://arxiv.org/pdf/1706.03762'),
            rec('semantic_scholar', title='Attention is All you Need', doi='10.48550/arXiv.1706.03762', year=2017,
                venue='NeurIPS'),
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['venue'], 'NeurIPS')
        self.assertEqual(merged[0]['sources'], ['semantic_scholar', 'arxiv'])

    def test_title_and_year_within_one(self):
        merged = records.merge([rec('crossref', title='A Study of Things', year=2019),
                                rec('arxiv', title='A study of things.', year=2018),
                                rec('arxiv', title='A study of things', year=2015)])
        self.assertEqual(len(merged), 2)

    def test_different_dois_never_merge_on_title(self):
        merged = records.merge([rec('crossref', title='Deep learning', year=2015, doi='10.1234/a'),
                                rec('crossref', title='Deep learning', year=2015, doi='10.1234/b')])
        self.assertEqual(len(merged), 2)

    def test_retracted_true_wins_from_any_source(self):
        merged = records.merge([rec('crossref', title='X', doi='10.1234/x', retracted=None),
                                rec('openalex', title='X', doi='10.1234/x', retracted=True)])
        self.assertIs(merged[0]['retracted'], True)
        merged = records.merge([rec('crossref', title='X', doi='10.1234/x', retracted=True),
                                rec('openalex', title='X', doi='10.1234/x', retracted=False)])
        self.assertIs(merged[0]['retracted'], True)

    def test_oa_url_prefers_unpaywall_then_arxiv(self):
        merged = records.merge([
            rec('openalex', title='X', doi='10.1234/x', oa_url='https://openalex.example/x.pdf'),
            rec('unpaywall', title='X', doi='10.1234/x', oa_url='https://repo.example/x.pdf'),
        ])
        self.assertEqual(merged[0]['oa_url'], 'https://repo.example/x.pdf')

    def test_a_bridging_record_joins_two_groups_and_order_is_first_seen(self):
        merged = records.merge([
            rec('crossref', title='Other', year=2000, doi='10.1234/other'),
            rec('openalex', title='Paper', doi='10.1234/p', year=2020),
            rec('arxiv', title='Paper preprint title', arxiv_id='2001.00001', year=2020),
            rec('semantic_scholar', title='Paper', doi='10.1234/p', arxiv_id='2001.00001', year=2020),
        ])
        self.assertEqual([m['title'] for m in merged], ['Other', 'Paper'])
        self.assertEqual(merged[1]['arxiv_id'], '2001.00001')

    def test_merge_does_not_change_inputs(self):
        first = rec('crossref', title='X', doi='10.1234/x')
        records.merge([first, rec('openalex', title='X', doi='10.1234/x', openalex_id='W1')])
        self.assertIsNone(first['openalex_id'])
        self.assertEqual(first['sources'], ['crossref'])


if __name__ == '__main__':
    unittest.main()
