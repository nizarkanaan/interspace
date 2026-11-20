"""Two-agent evidence table (docs/superpowers/specs/2026-11-20-evidence-table-design.md)."""
import csv
import io
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))

from research import evidence  # noqa: E402

PAPERS = [{'title': 'Fallback across operators', 'year': 2020, 'doi': '10.5555/a',
           'abstract': 'We studied 1,200 emergency calls in 40 outages. Fallback succeeded in most of them.'},
          {'title': 'Recovery timing', 'year': 2021, 'doi': '10.5555/b', 'abstract': 'A simulation of recovery timing.'}]
COLS = evidence.columns([{'name': 'Sample size', 'instruction': 'How many calls.', 'numeric': True},
                         {'name': 'Study design', 'instruction': 'The kind of study.'}])


def table():
    t = evidence.start(COLS, PAPERS, 't0')
    for row in t['rows']:
        evidence.attach(row, None, COLS)
    return t


class ModelTests(unittest.TestCase):
    def test_columns_are_checked_and_get_unique_ids(self):
        cols = evidence.columns([{'name': 'Method', 'instruction': 'x'}, {'name': 'Method', 'instruction': 'y'}])
        self.assertEqual([c['id'] for c in cols], ['method', 'method-2'])
        for bad in ([], [{'name': '', 'instruction': 'x'}], [{'name': 'a', 'instruction': 'x'}] * 11, 'x'):
            with self.assertRaises(ValueError):
                evidence.columns(bad)

    def test_rows_come_from_cited_references_or_checked_papers(self):
        report = ('# R\n\nText [1] [2].\n\n## References\n\n1. A (2020). Fallback across operators. doi:10.5555/a\n'
                  '2. B (2021). Recovery timing in networks of many kinds. doi:10.5555/b\n3. Unknown.\n')
        corpus = {'papers': [{'paper': PAPERS[0], 'check': {'status': 'verified'}}, {'paper': PAPERS[1], 'check': None}]}
        self.assertEqual([p['title'] for p in evidence.rows_from('cited', report, corpus)],
                         ['Fallback across operators', 'Recovery timing'])
        self.assertEqual([p['title'] for p in evidence.rows_from('checked', None, corpus)], ['Fallback across operators'])
        with self.assertRaisesRegex(ValueError, 'Save a report first'):
            evidence.rows_from('cited', None, corpus)

    def test_each_provider_fills_its_own_values_with_quotes_from_the_source(self):
        t = table()
        out = evidence.record(t, 'claude', [
            {'row': 'r1', 'column': 'sample-size', 'value': '1,200', 'quote': 'We studied 1,200 emergency calls'},
            {'row': 'r1', 'column': 'study-design', 'value': 'Field study', 'quote': 'made up words'},
            {'row': 'r2', 'column': 'sample-size', 'value': 'not reported'},
            {'row': 'r9', 'column': 'x', 'value': 'v', 'quote': 'q'}], 't1')
        self.assertEqual(out['recorded'], 2)
        self.assertEqual([r['error'] for r in out['rejected']], ['The quote is not in the source text.', 'Unknown row or column.'])
        again = evidence.record(t, 'claude', [{'row': 'r1', 'column': 'sample-size', 'value': '1200', 'quote': '1,200'}], 't2')
        self.assertEqual(again['rejected'][0]['error'], 'You already filled this cell.')
        self.assertEqual(evidence.pending_rows(t, 'claude'), ['r1', 'r2'])  # Still missing cells in both rows.
        self.assertEqual(evidence.pending(t, 'claude', ['r1'])['rows'][0]['missing'], ['study-design'])

    def test_comparison_agree_check_disagree_not_reported_and_resolve(self):
        t = table()
        evidence.record(t, 'claude', [
            {'row': 'r1', 'column': 'sample-size', 'value': '1,200 ', 'quote': '1,200'},
            {'row': 'r1', 'column': 'study-design', 'value': 'Field study', 'quote': 'We studied'},
            {'row': 'r2', 'column': 'sample-size', 'value': 'Not reported'},
            {'row': 'r2', 'column': 'study-design', 'value': 'Simulation', 'quote': 'A simulation'}], 't1')
        evidence.record(t, 'codex', [
            {'row': 'r1', 'column': 'sample-size', 'value': '1200', 'quote': '1,200 emergency calls'},
            {'row': 'r1', 'column': 'study-design', 'value': 'Observational', 'quote': 'We studied'},
            {'row': 'r2', 'column': 'sample-size', 'value': 'not reported'},
            {'row': 'r2', 'column': 'study-design', 'value': 'simulation.', 'quote': 'simulation'}], 't2')
        cells = {(r['id'], c): v['status'] for r in evidence.public(t)['table']['rows'] for c, v in r['cells'].items()}
        self.assertEqual(cells, {('r1', 'sample-size'): 'check', ('r1', 'study-design'): 'disagree',
                                 ('r2', 'sample-size'): 'not_reported', ('r2', 'study-design'): 'agree'})
        evidence.resolve(t, 'r1', 'study-design', 'Field study (observational)', 't3')
        counts = evidence.counts(t)
        self.assertEqual((counts['resolved'], counts['disagree'], counts['check']), (1, 0, 1))
        rows = list(csv.reader(io.StringIO(evidence.to_csv(t))))
        self.assertEqual(rows[0], ['Paper', 'Sample size', 'Study design', 'Sample size status', 'Study design status'])
        self.assertEqual(rows[1], ['Fallback across operators (2020)', '1,200', 'Field study (observational)', 'check', 'resolved'])
        self.assertEqual(rows[2][1:3], ['Not reported', 'Simulation'])

    def test_csv_neutralises_formulas(self):
        t = table()
        evidence.resolve(t, 'r1', 'study-design', '=HYPERLINK("x")', 't')
        self.assertEqual(list(csv.reader(io.StringIO(evidence.to_csv(t))))[1][2], '\'=HYPERLINK("x")')


if __name__ == '__main__':
    unittest.main()
