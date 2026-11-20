"""The research corpus merge, verdict rules, limits and backfill (2026-11-20-task-corpus-design.md)."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))

from research import corpus

LECUN = {'title': 'Deep learning', 'authors': ['Yann LeCun'], 'year': 2015, 'venue': 'Nature',
         'doi': '10.1038/nature14539', 'sources': ['crossref']}
LECUN_S2 = dict(LECUN, venue=None, citation_count=79568, oa_url='https://example.org/lecun.pdf',
                sources=['semantic_scholar'])
VASWANI = {'title': 'Attention Is All You Need', 'authors': ['Ashish Vaswani'], 'year': 2017,
           'arxiv_id': '1706.03762', 'sources': ['arxiv']}


def found(member='Researcher', query='deep learning', tool='research_search', at='2026-11-20T10:00:00Z'):
    return {'tool': tool, 'query': query, 'member': member, 'at': at}


def row(status, given, match=None, fields=(), source='crossref'):
    return {'status': status, 'input': given, 'match': match, 'fields': list(fields), 'source': source}


class MergeTests(unittest.TestCase):
    def test_duplicates_across_sources_and_members_merge_into_one_paper(self):
        c = corpus.empty()
        self.assertTrue(corpus.add_papers(c, [LECUN, VASWANI], found()))
        self.assertTrue(corpus.add_papers(c, [LECUN_S2], found('Citation checker', 'lecun')))
        self.assertEqual(len(c['papers']), 2)
        lecun = c['papers'][0]
        self.assertEqual(lecun['paper']['venue'], 'Nature')
        self.assertEqual(lecun['paper']['citation_count'], 79568)
        self.assertEqual(lecun['paper']['sources'], ['crossref', 'semantic_scholar'])
        self.assertEqual([f['member'] for f in lecun['found']], ['Researcher', 'Citation checker'])
        self.assertIsNone(lecun['check'])

    def test_the_same_finding_is_kept_once_and_nothing_changes(self):
        c = corpus.empty()
        corpus.add_papers(c, [LECUN], found())
        self.assertFalse(corpus.add_papers(c, [LECUN], found(at='2026-11-20T11:00:00Z')))
        self.assertEqual(len(c['papers'][0]['found']), 1)

    def test_records_without_title_doi_or_arxiv_and_non_records_are_skipped(self):
        c = corpus.empty()
        self.assertFalse(corpus.add_papers(c, [{'authors': ['X']}, 'text', None], found()))
        self.assertEqual(c['papers'], [])

    def test_found_entries_stop_at_twenty(self):
        c = corpus.empty()
        for i in range(25):
            corpus.add_papers(c, [LECUN], found(query='q%d' % i))
        self.assertEqual(len(c['papers'][0]['found']), corpus.MAX_FOUND)

    def test_a_full_corpus_drops_new_papers_but_still_updates_existing_ones(self):
        c = corpus.empty()
        corpus.add_papers(c, [LECUN], found())
        old = corpus.MAX_PAPERS
        corpus.MAX_PAPERS = 1
        try:
            corpus.add_papers(c, [VASWANI, LECUN_S2], found('Reviewer'))
            corpus.add_report(c, [row('verified', {'doi': LECUN['doi']}, LECUN)], 'orchestrator', 'Orchestrator', 't')
        finally:
            corpus.MAX_PAPERS = old
        self.assertTrue(c['full'])
        self.assertEqual(len(c['papers']), 1)
        self.assertEqual(len(c['papers'][0]['found']), 3)
        self.assertEqual(c['papers'][0]['check']['status'], 'verified')


class VerdictTests(unittest.TestCase):
    def test_verified_attaches_to_the_matched_paper(self):
        c = corpus.empty()
        corpus.add_papers(c, [LECUN], found())
        corpus.add_report(c, [row('verified', {'title': 'Deep learning', 'doi': '10.1038/NATURE14539'}, LECUN)],
                          'orchestrator', 'Orchestrator', 't1')
        self.assertEqual(len(c['papers']), 1)
        self.assertEqual(c['papers'][0]['check']['status'], 'verified')
        self.assertEqual(c['papers'][0]['check']['by'], 'orchestrator')

    def test_a_mismatch_goes_to_unverified_and_its_match_is_only_closest(self):
        c = corpus.empty()
        given = {'title': 'Deep learning', 'authors': ['Yann LeCun'], 'year': 2012}
        corpus.add_report(c, [row('mismatch', given, LECUN, ['year'])], 'orchestrator', 'Orchestrator', 't1')
        self.assertEqual(c['papers'], [])
        [item] = c['unverified']
        self.assertEqual((item['status'], item['fields'], item['reference']['year']), ('mismatch', ['year'], 2012))
        self.assertEqual(item['closest']['year'], 2015)

    def test_not_found_and_unchecked_have_no_closest(self):
        c = corpus.empty()
        corpus.add_report(c, [row('not_found', {'title': 'Imaginary transformers'}),
                              row('unchecked', {'raw': 'Smith 2020, a paper'}, LECUN)], 'member', 'Checker', 't')
        self.assertEqual([u['status'] for u in c['unverified']], ['not_found', 'unchecked'])
        self.assertTrue(all(u['closest'] is None for u in c['unverified']))

    def test_a_later_verification_removes_the_unverified_entry(self):
        c = corpus.empty()
        given = {'doi': LECUN['doi']}
        corpus.add_report(c, [row('unchecked', given)], 'member', 'Checker', 't1')
        corpus.add_report(c, [row('verified', given, LECUN)], 'member', 'Checker', 't2')
        self.assertEqual(c['unverified'], [])
        self.assertEqual(c['papers'][0]['check']['status'], 'verified')

    def test_a_confirmed_verdict_is_never_downgraded(self):
        c = corpus.empty()
        given = {'doi': LECUN['doi']}
        corpus.add_report(c, [row('verified', given, LECUN)], 'member', 'Checker', 't1')
        corpus.add_report(c, [row('unchecked', given), row('not_found', given)], 'orchestrator', 'Orchestrator', 't2')
        self.assertEqual(c['unverified'], [])
        self.assertEqual(c['papers'][0]['check']['status'], 'verified')

    def test_the_orchestrators_check_beats_a_members(self):
        c = corpus.empty()
        retracted = dict(LECUN, retracted=True)
        corpus.add_report(c, [row('retracted', {'doi': LECUN['doi']}, retracted)], 'orchestrator', 'Orchestrator', 't1')
        corpus.add_report(c, [row('verified', {'doi': LECUN['doi']}, LECUN)], 'member', 'Checker', 't2')
        self.assertEqual(c['papers'][0]['check']['status'], 'retracted')
        given = {'title': 'Imaginary'}
        corpus.add_report(c, [row('not_found', given)], 'orchestrator', 'Orchestrator', 't3')
        corpus.add_report(c, [row('unchecked', given)], 'member', 'Checker', 't4')
        self.assertEqual(c['unverified'][0]['status'], 'not_found')
        corpus.add_report(c, [row('unchecked', given)], 'orchestrator', 'Orchestrator', 't5')
        self.assertEqual(c['unverified'][0]['status'], 'unchecked')


class RebuildTests(unittest.TestCase):
    def events(self, *items):
        return [dict(e, seq=i + 1) for i, e in enumerate(items)]

    def test_rebuild_reads_results_and_reports_and_counts_unreadable_ones(self):
        root = self.events(
            {'kind': 'tool_call', 'at': '2026-11-20T10:00:00Z',
             'data': {'call_id': 'a', 'category': 'research', 'tool': 'research_search',
                      'input': {'tool': 'research_search', 'query': 'deep learning'}}},
            {'kind': 'tool_result', 'at': '2026-11-20T10:00:01Z',
             'data': {'call_id': 'a', 'status': 'ok', 'output': {'text': json.dumps({'papers': [LECUN]}),
                                                                 'truncated': False}}},
            {'kind': 'tool_call', 'at': '2026-11-20T10:00:02Z',
             'data': {'call_id': 'b', 'category': 'research', 'tool': 'research_search', 'input': {'query': 'x'}}},
            {'kind': 'tool_result', 'at': '2026-11-20T10:00:03Z',
             'data': {'call_id': 'b', 'status': 'ok', 'output': {'text': '{"papers": [', 'truncated': True}}},
            {'kind': 'citation_report', 'at': '2026-11-20T10:00:09Z',
             'data': {'references': [row('verified', {'doi': LECUN['doi']}, LECUN)]}})
        child = self.events(
            {'kind': 'tool_call', 'at': '2026-11-20T10:00:04Z',
             'data': {'call_id': 'c', 'category': 'research', 'tool': 'research_paper',
                      'input': {'id': 'arXiv:1706.03762'}}},
            {'kind': 'tool_result', 'at': '2026-11-20T10:00:05Z',
             'data': {'call_id': 'c', 'status': 'ok', 'output': {'text': json.dumps({'paper': VASWANI})}}},
            {'kind': 'citation_report', 'at': '2026-11-20T10:00:06Z',
             'data': {'references': [row('unchecked', {'doi': LECUN['doi']})]}})
        c, incomplete = corpus.rebuild([('Orchestrator', root), ('Researcher', child)])
        self.assertEqual(incomplete, 1)
        self.assertEqual([p['paper']['title'] for p in c['papers']], ['Deep learning', 'Attention Is All You Need'])
        self.assertEqual(c['papers'][1]['found'][0]['member'], 'Researcher')
        self.assertEqual(c['papers'][1]['found'][0]['query'], 'arXiv:1706.03762')
        self.assertEqual(c['papers'][0]['check']['status'], 'verified')
        self.assertEqual(c['unverified'], [])  # The member's unchecked row came first; the Orchestrator verified.

    def test_rebuild_of_nothing_is_empty(self):
        self.assertEqual(corpus.rebuild([('Orchestrator', [])]), (corpus.empty(), 0))
        self.assertIsNone(corpus.load({'v': 9}))



class ViewTests(unittest.TestCase):
    def corpus(self):
        c = corpus.empty()
        corpus.add_papers(c, [LECUN, VASWANI, dict(LECUN, title='Unrelated wireless energy', doi='10.5555/e')], found())
        corpus.add_report(c, [row('verified', {'doi': LECUN['doi']}, LECUN),
                              row('not_found', {'title': 'Imaginary transformers'})], 'orchestrator', 'Orchestrator', 't')
        return c

    def test_unchecked_lists_papers_the_checker_never_confirmed_with_their_numbers(self):
        out = corpus.view(self.corpus(), {'status': 'unchecked'})
        self.assertEqual(out['counts'], {'papers': 3, 'checked': 1, 'unchecked': 2, 'unverified': 1})
        self.assertEqual([(p['n'], p['title'], p['verdict']) for p in out['papers']],
                         [(2, 'Attention Is All You Need', 'unchecked'), (3, 'Unrelated wireless energy', 'unchecked')])
        self.assertEqual(out['papers'][0]['arxiv_id'], '1706.03762')
        self.assertNotIn('abstract', out['papers'][0])

    def test_checked_query_unverified_and_paging(self):
        c = self.corpus()
        self.assertEqual([p['n'] for p in corpus.view(c, {'status': 'checked'})['papers']], [1])
        self.assertEqual([p['n'] for p in corpus.view(c, {'query': 'ATTENTION vaswani'})['papers']], [2])
        unverified = corpus.view(c, {'status': 'unverified'})
        self.assertEqual(unverified['references'][0]['status'], 'not_found')
        first = corpus.view(c, {'limit': 2})
        self.assertEqual((len(first['papers']), first['next_offset']), (2, 2))
        self.assertEqual([p['n'] for p in corpus.view(c, {'limit': 2, 'offset': 2})['papers']], [3])

    def test_bad_arguments_are_refused(self):
        for bad in ({'status': 'some'}, {'limit': 0}, {'limit': 201}, {'offset': -1}, {'query': 5}, {'colour': 1}):
            with self.assertRaises(ValueError):
                corpus.view(self.corpus(), bad)



if __name__ == '__main__':
    unittest.main()
