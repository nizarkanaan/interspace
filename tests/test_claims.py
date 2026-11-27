"""Claim check (docs/superpowers/specs/2026-11-20-claim-check-design.md)."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))

from research import claims  # noqa: E402

REPORT = """# Fallback during outages

Fallback is described in standards [1]. Two operator reports measured it, e.g. in Europe [2, 3]. Timing is rare [4–5].
Unrelated brackets stay text: [x] and [99]. See `code [1]` and [a link](https://example.org).

- A list item cites again [1].

```
not a claim [2]
```

## References

1. Example, A. (2020). Emergency call fallback across mobile operators. doi:10.5555/fb.1
2. Sample, B. (2021). Measuring call recovery after network outages. arXiv:2101.00001
3. Nobody, C. (2031). An invented paper.
4. Author, D. (2019). Recovery timing in mobile networks of several countries.
5. Author, E. (2018). Another source.
"""
CORPUS = {'papers': [
    {'paper': {'title': 'Emergency call fallback across mobile operators', 'doi': '10.5555/fb.1',
               'abstract': 'We find that fallback to another operator succeeded in most outages we measured.'}},
    {'paper': {'title': 'Measuring call recovery after network outages', 'arxiv_id': '2101.00001',
               'abstract': 'Recovery took a median of 40 minutes.'}},
    {'paper': {'title': 'Recovery timing in mobile networks of several countries', 'abstract': None}}]}


class SplitTests(unittest.TestCase):
    def test_claims_follow_reading_order_ranges_and_skip_code_links_and_references(self):
        found = claims.split(REPORT)
        self.assertEqual([c['id'] for c in found], ['1:1', '2:1', '3:1', '4:1', '5:1', '1:2'])
        self.assertEqual(found[1]['sentence'], 'Two operator reports measured it, e.g. in Europe [2, 3].')
        self.assertTrue(found[0]['reference'].startswith('Example, A. (2020)'))
        self.assertEqual(found[5]['sentence'], 'A list item cites again [1].')

    def test_ids_match_the_reader_for_the_ui_fixture_report(self):
        text = ('# Fallback during outages\n\nFallback is described in standards [1]. Two reports measured it [2]. '
                'Recovery timing is rare [1].\n\n## References\n\n1. Example, A. (2020). Emergency call fallback '
                'across mobile operators. doi:10.5555/fb.1\n2. Sample, B. (2021). Measuring call recovery after '
                'outages. arXiv:2101.00001\n')
        self.assertEqual([c['id'] for c in claims.split(text)], ['1:1', '2:1', '1:2'])  # Same as tests/claims-ui.mjs.

    def test_references_come_from_list_items_or_numbered_lines(self):
        self.assertEqual(sorted(claims.references(REPORT)), [1, 2, 3, 4, 5])
        plain = 'Text [2].\n\n## Bibliography\n\n[2] Second entry.\n[7] Seventh.\n'
        self.assertEqual(claims.references(plain), {2: 'Second entry.', 7: 'Seventh.'})
        self.assertEqual(claims.split('No references here [1].'), [])

    def test_each_table_row_is_its_own_sentence(self):
        refs = ''.join('%d. Author %s. (2020). Paper number %d about the topic.\n' % (n, 'ABCDE'[n - 1], n) for n in range(1, 6))
        text = ('# Gains\n\nThe gains are as the authors state them [1].\n'
                '| Ref | Method | Result |\n|:--|---|--:|\n'
                '| [2] | Federated **learning**. Two agents coordinate. | Higher throughput. Lower delay. |\n'
                '| [3] | Transfer \\| reuse | Lower delay, as in [2] |\n'
                '[4], [5] | Constrained methods | Fewer violations | an extra cell [1] |\n'
                'After the table [1].\n\n'
                'a | b [3]\nc | d\n\n'
                '## References\n\n' + refs)
        found = claims.split(text)
        # The reader's numbering: rows in order, cells left to right, a cell past the header's count not shown.
        self.assertEqual([c['id'] for c in found], ['1:1', '2:1', '3:1', '2:2', '4:1', '5:1', '1:2', '3:2'])
        sentences = [c['sentence'] for c in found]
        self.assertEqual(sentences[0], 'The gains are as the authors state them [1].')
        self.assertEqual(sentences[1], '[2] · Federated learning. Two agents coordinate. · Higher throughput. Lower delay.')
        self.assertEqual(sentences[2], '[3] · Transfer | reuse · Lower delay, as in [2]')
        self.assertEqual(sentences[3], sentences[2])
        self.assertEqual(sentences[4], '[4], [5] · Constrained methods · Fewer violations')
        self.assertEqual(sentences[5], sentences[4])
        self.assertEqual(sentences[6], 'After the table [1].')
        self.assertEqual(sentences[7], 'a | b [3] c | d')  # Pipes without a delimiter row are text, as in the reader.

    def test_a_long_table_gives_every_row_its_own_claim(self):
        rows = ''.join('| [%d] | Method %d with a long description of what it does and how | Gain of %d%% over the baseline |\n'
                       % (n, n, n) for n in range(1, 21))
        refs = ''.join('[%d] Author. (2020). Paper number %d about the topic.\n' % (n, n) for n in range(1, 21))
        text = '# Gains\n\n| Ref | Method | Gain |\n|---|---|---|\n' + rows + '\n## References\n' + refs
        found = claims.split(text)
        self.assertEqual([c['id'] for c in found], ['%d:1' % n for n in range(1, 21)])
        self.assertEqual(len({c['sentence'] for c in found}), 20)
        self.assertEqual(found[19]['sentence'], '[20] · Method 20 with a long description of what it does and how · Gain of 20% over the baseline')
        self.assertFalse(any('|' in c['sentence'] or '---' in c['sentence'] or 'Ref' in c['sentence'] for c in found))

    def test_ids_match_the_reader_for_the_table_report_in_reader_ui(self):
        text = ('# Gains as reported\n\nThe gains below are as the authors state them [1].\n\n| Ref | Method | Evaluation | Headline result |\n'
                '|---|---|---|---|\n| [2] | Federated | Simulation | Higher throughput |\n| [3] | Transfer | Simulation | Lower delay, as in [2] |\n'
                '| [4], [5] | Constrained | Testbed | Fewer violations |\n\n## References\n\n'
                + ''.join('%d. Author. (2020). Paper number %d about the topic.\n' % (n, n) for n in range(1, 6)))
        self.assertEqual([c['id'] for c in claims.split(text)], ['1:1', '2:1', '3:1', '2:2', '4:1', '5:1'])  # As tests/reader-ui.mjs.

    def test_a_check_split_before_tables_shows_each_rows_sentence_while_the_report_is_unchanged(self):
        text = ('# Gains\n\n| Ref | Method | Gain |\n|---|---|---|\n| [1] | Federated | Higher |\n| [2] | Transfer | Lower |\n'
                '\n## References\n[1] Author. (2020). Paper one about the topic.\n[2] Author. (2021). Paper two about the topic.\n')
        stored = {'v': claims.V, 'report_sha': claims.report_hash(text), 'started_at': 't0', 'claims': [
            {'id': '1:1', 'n': 1, 'k': 1, 'sentence': '| Ref | Method | Gain | |---|---|---| | [1] | Federated |', 'verdict': 'partly'},
            {'id': '2:1', 'n': 2, 'k': 1, 'sentence': '| Ref | Method | Gain | |---|---|---| | [1] | Federated |', 'verdict': 'supported'}]}
        shown = claims.current_sentences(stored, text)
        self.assertEqual([c['sentence'] for c in shown['claims']], ['[1] · Federated · Higher', '[2] · Transfer · Lower'])
        self.assertEqual([c['verdict'] for c in shown['claims']], ['partly', 'supported'])
        self.assertIn('|---|', stored['claims'][0]['sentence'])  # The stored check is not changed.
        self.assertIs(claims.current_sentences(stored, text + 'x'), stored)  # A changed report keeps the stored sentences.
        moved = dict(stored, claims=stored['claims'][::-1])
        self.assertIs(claims.current_sentences(moved, text), moved)  # So do ids that no longer line up.
        self.assertIsNone(claims.current_sentences(None, text))
        self.assertIs(claims.current_sentences(stored, None), stored)


class CheckTests(unittest.TestCase):
    def started(self):
        return claims.start(REPORT, CORPUS, 't0')

    def test_start_attaches_abstracts_and_marks_claims_without_source_text(self):
        value = self.started()
        by_id = {c['id']: c for c in value['claims']}
        self.assertEqual(by_id['1:1']['status'], 'pending')
        self.assertEqual(by_id['2:1']['paper']['arxiv_id'], '2101.00001')
        for cid in ('3:1', '4:1', '5:1'):
            self.assertEqual((by_id[cid]['status'], by_id[cid]['verdict']), ('judged', 'cannot_tell'))
        self.assertEqual(claims.counts(value), {'claims': 6, 'pending': 3, 'supported': 0, 'partly': 0,
                                                'not_supported': 0, 'cannot_tell': 3})
        batch = claims.pending(value)
        self.assertEqual([c['id'] for c in batch['claims']], ['1:1', '2:1', '1:2'])
        self.assertIn('fallback to another operator', batch['claims'][0]['source']['text'])

    def test_quotes_must_be_in_the_source_and_bad_results_are_rejected_one_by_one(self):
        value = self.started()
        out = claims.record(value, REPORT, [
            {'id': '1:1', 'verdict': 'supported', 'reason': 'The abstract says so.',
             'quote': 'fallback to   another operator SUCCEEDED'},
            {'id': '2:1', 'verdict': 'partly', 'reason': 'Only timing.', 'quote': 'took a median of 5 minutes'},
            {'id': '1:2', 'verdict': 'maybe', 'reason': 'x'},
            {'id': '9:9', 'verdict': 'supported', 'reason': 'x', 'quote': 'x'},
            {'id': '4:1', 'verdict': 'supported', 'reason': 'x', 'quote': 'x'}], 'codex Citation checker', 't1')
        self.assertEqual(out['recorded'], 1)
        self.assertEqual([r['error'] for r in out['rejected']], [
            'The quote is not in the source text.', 'verdict must be supported, partly, not_supported or cannot_tell.',
            'Unknown claim.', 'This claim was already judged.'])
        judged = next(c for c in value['claims'] if c['id'] == '1:1')
        self.assertEqual((judged['verdict'], judged['by']), ('supported', 'codex Citation checker'))
        out = claims.record(value, REPORT, [{'id': '1:2', 'verdict': 'cannot_tell', 'reason': 'Not covered.'}], 'x', 't2')
        self.assertEqual(out['recorded'], 1)
        self.assertNotIn('source', claims.public(value)['claims'][0])

    def test_a_changed_report_refuses_verdicts(self):
        value = self.started()
        with self.assertRaisesRegex(ValueError, 'report changed'):
            claims.record(value, REPORT + '\nMore.', [{'id': '1:1', 'verdict': 'cannot_tell', 'reason': 'x'}], 'x', 't')
        with self.assertRaisesRegex(ValueError, 'limit must be'):
            claims.pending(value, 0)


if __name__ == '__main__':
    unittest.main()
