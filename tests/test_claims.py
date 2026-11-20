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
