import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app/backend'), str(ROOT / 'pilot')]

import budget  # noqa: E402


def state_with(task_budget=1000):
    task = {'id': 'task-1', 'token_budget': task_budget}
    return {'usage': []}, task


class BudgetPolicyTests(unittest.TestCase):
    def test_validate_accepts_positive_integers_and_legacy_none(self):
        self.assertEqual(budget.validate(250000), 250000)
        self.assertIsNone(budget.validate(None))
        for bad in (0, -1, 1.5, '100', True, 2 ** 53):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                budget.validate(bad)

    def test_charge_counts_input_plus_output_once(self):
        # Cached input is part of input_tokens; reasoning is part of output_tokens (Codex TokenUsage).
        usage = {'input_tokens': 14632, 'cached_input_tokens': 4000, 'output_tokens': 1132, 'reasoning_output_tokens': 500}
        self.assertEqual(budget.charge(usage), 15764)
        self.assertIsNone(budget.charge(None))
        self.assertIsNone(budget.charge({}))
        self.assertIsNone(budget.charge({'input_tokens': 10}))

    def test_estimate_over_estimates_and_grows_with_prompt(self):
        small, large = budget.estimate('x' * 300, 'Reviewer'), budget.estimate('x' * 30000, 'Reviewer')
        self.assertGreater(large, small)
        self.assertGreaterEqual(small, budget.PROVIDER_OVERHEAD_TOKENS)
        self.assertGreater(budget.estimate('x', 'Orchestrator'), budget.PROVIDER_OVERHEAD_TOKENS)

    def test_exact_fit_is_allowed_and_one_more_token_is_refused(self):
        state, task = state_with(None)
        need = budget.estimate('prompt', 'Researcher')
        task['token_budget'] = need
        entry = budget.reserve(state, task, role='Researcher', prompt='prompt', project_id='p')
        self.assertEqual(budget.ledger(state, 'task-1')['reserved'], need)
        budget.settle(state, entry, None, 'failed')
        state, task = state_with(need - 1)
        with self.assertRaises(budget.Exhausted) as refusal:
            budget.reserve(state, task, role='Researcher', prompt='prompt', project_id='p')
        self.assertEqual(state['usage'], [])
        self.assertIn(format(need - 1, ','), str(refusal.exception))

    def test_refusal_counts_existing_reported_estimated_and_reserved_use(self):
        state, task = state_with(90000)
        first = budget.reserve(state, task, role='Researcher', prompt='a', project_id='p')
        budget.settle(state, first, {'input_tokens': 60000, 'output_tokens': 1000}, 'completed')
        second = budget.reserve(state, task, role='Reviewer', prompt='b', project_id='p')
        totals = budget.ledger(state, 'task-1')
        self.assertEqual(totals['used'], 61000)
        self.assertEqual(totals['reserved'], budget.estimate('b', 'Reviewer'))
        with self.assertRaises(budget.Exhausted):
            budget.reserve(state, task, role='Orchestrator', prompt='c', project_id='p')
        budget.settle(state, second, None, 'cancelled')
        totals = budget.ledger(state, 'task-1')
        self.assertEqual(totals['reserved'], 0)
        self.assertEqual(totals['estimated'], budget.estimate('b', 'Reviewer'))
        self.assertEqual(totals['used'], 61000 + budget.estimate('b', 'Reviewer'))

    def test_overshoot_records_actual_count(self):
        state, task = state_with(None)
        task['token_budget'] = budget.estimate('p', 'Researcher')
        entry = budget.reserve(state, task, role='Researcher', prompt='p', project_id='p')
        budget.settle(state, entry, {'input_tokens': task['token_budget'], 'output_tokens': 50}, 'completed')
        totals = budget.ledger(state, 'task-1', task['token_budget'])
        self.assertEqual(totals['used'], task['token_budget'] + 50)
        self.assertEqual(totals['overshoot'], 50)
        self.assertEqual(state['usage'][0]['charge_kind'], 'reported')

    def test_recover_turns_reservations_into_estimated_charges(self):
        state, task = state_with(100000)
        budget.reserve(state, task, role='Researcher', prompt='p', project_id='p')
        budget.recover(state)
        entry = state['usage'][0]
        self.assertEqual(entry['charge_kind'], 'estimated')
        self.assertEqual(entry['charge'], entry['estimate'])
        self.assertEqual(entry['outcome'], 'interrupted')
        self.assertEqual(budget.ledger(state, 'task-1')['reserved'], 0)

    def test_none_budget_records_but_never_refuses(self):
        state, task = state_with(None)
        for _ in range(3):
            entry = budget.reserve(state, task, role='Researcher', prompt='x' * 100000, project_id='p')
            budget.settle(state, entry, {'input_tokens': 900000, 'output_tokens': 1}, 'completed')
        self.assertEqual(budget.ledger(state, 'task-1')['used'], 2700003)
        self.assertIsNone(budget.ledger(state, 'task-1')['budget'])

    def test_ledger_charges_legacy_entries_from_tokens_and_ignores_other_tasks(self):
        state = {'usage': [
            {'role': 'Orchestrator', 'task_id': 'task-1', 'tokens': {'input_tokens': 10, 'output_tokens': 5}},
            {'role': 'Researcher', 'task_id': 'task-1', 'tokens': None},
            {'role': 'Researcher', 'task_id': 'other', 'tokens': {'input_tokens': 999, 'output_tokens': 1}},
            {'role': 'Orchestrator', 'project_id': 'p', 'tokens': {'input_tokens': 7, 'output_tokens': 7}},
        ]}
        totals = budget.ledger(state, 'task-1', 50)
        self.assertEqual(totals['used'], 15)
        self.assertEqual(totals['unknown'], 1)
        self.assertEqual(totals['remaining'], 35)

    def test_projection_uses_typical_prompt_size_and_minimal_first_call(self):
        state, task = state_with(100000)
        entry = budget.reserve(state, task, role='Orchestrator', prompt='x' * 3000, project_id='p')
        budget.settle(state, entry, {'input_tokens': 15000, 'output_tokens': 500}, 'completed')
        self.assertEqual(budget.typical_prompt_chars(state, 'task-1'), 3000)
        fits = budget.projection(state, task, ['Researcher', 'Orchestrator'])
        self.assertEqual(fits['projected'], 2 * budget.estimate_chars(3000, 'Researcher'))
        self.assertTrue(fits['fits']);self.assertTrue(fits['first_fits'])
        task['token_budget'] = 15500 + budget.estimate_chars(3000, 'Researcher')
        tight = budget.projection(state, task, ['Researcher', 'Orchestrator'])
        self.assertFalse(tight['fits']);self.assertTrue(tight['first_fits'])
        task['token_budget'] = 15500 + budget.estimate_chars(0, 'Researcher') - 1
        self.assertFalse(budget.projection(state, task, ['Researcher'])['first_fits'])
        task['token_budget'] = None
        self.assertIsNone(budget.projection(state, task, ['Researcher']))

    def test_settle_rejects_unknown_or_settled_entries(self):
        state, task = state_with(100000)
        entry = budget.reserve(state, task, role='Researcher', prompt='p', project_id='p')
        budget.settle(state, entry, None, 'failed')
        with self.assertRaises(ValueError):
            budget.settle(state, entry, None, 'failed')
        with self.assertRaises(ValueError):
            budget.settle(state, 'missing', None, 'failed')


    def test_malformed_entries_count_as_unknown_and_never_break_recovery(self):
        state = {'usage': [
            {'task_id': 'task-1', 'charge_kind': 'reserved'},
            {'task_id': 'task-1', 'charge_kind': 'reported', 'charge': 'lots'},
            {'task_id': 'task-1', 'charge_kind': 'estimated', 'charge': -4},
            {'task_id': 'task-1', 'charge_kind': 'reported', 'charge': 7},
            'not an entry',
        ]}
        budget.recover(state)
        totals = budget.ledger(state, 'task-1', 100)
        self.assertEqual(totals['used'], 7)
        self.assertEqual(totals['unknown'], 3)
        self.assertEqual(totals['reserved'], 0)

    def test_release_drops_only_an_unlaunched_reservation(self):
        state, task = state_with(100000)
        entry = budget.reserve(state, task, role='Researcher', prompt='p', project_id='p')
        budget.release(state, entry)
        self.assertEqual(state['usage'], [])
        with self.assertRaises(ValueError):
            budget.release(state, entry)

if __name__ == '__main__':
    unittest.main()
