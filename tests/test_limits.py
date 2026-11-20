"""Provider usage-limit readings (docs/superpowers/specs/2026-11-20-usage-limits-design.md)."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
sys.path.insert(1, str(ROOT / 'tests'))

import limits  # noqa: E402
from test_research_tasks import ResearchCase, answering  # noqa: E402


class ReaderTests(unittest.TestCase):
    def test_codex_windows_keep_only_what_codex_reported(self):
        windows = limits.codex({'rateLimits': {
            'primary': {'usedPercent': 42.04, 'windowDurationMins': 300, 'resetsAt': 1795200000},
            'secondary': {'usedPercent': 18, 'windowDurationMins': 10080},
            'other': {'usedPercent': 5}}})
        self.assertEqual(windows[0]['label'], '5-hour limit')
        self.assertEqual(windows[0]['used_percent'], 42.0)
        self.assertTrue(windows[0]['resets_at'].startswith('2026-11-'))
        self.assertEqual(windows[1], {'label': 'Weekly limit', 'used_percent': 18.0})

    def test_codex_bad_values_are_dropped(self):
        self.assertEqual(limits.codex({'rateLimits': {'primary': {'usedPercent': 140}, 'secondary': 'x'}}), [])
        self.assertEqual(limits.codex({'rateLimits': {'primary': {'usedPercent': True}}}), [])
        self.assertEqual(limits.codex('nope'), [])
        self.assertEqual(limits.codex({'rateLimits': {'primary': {'usedPercent': 3}}})[0]['label'], 'Short-term limit')

    def test_claude_status_type_utilization_and_reset(self):
        [w] = limits.claude({'status': 'allowed_warning', 'rateLimitType': 'five_hour', 'utilization': 0.85,
                             'resetsAt': 1795200000})
        self.assertEqual((w['label'], w['status'], w['used_percent']), ('5-hour limit', 'allowed_warning', 85.0))
        [w] = limits.claude({'status': 'allowed'})
        self.assertEqual(w, {'label': 'Usage limit', 'status': 'allowed'})
        self.assertEqual(limits.claude({'status': 'maybe'}), [])
        self.assertEqual(limits.claude({'status': 'rejected', 'utilization': 63})[0]['used_percent'], 63.0)

    def test_merge_keeps_the_newest_window_per_label(self):
        first = limits.merge(None, [{'label': '5-hour limit', 'used_percent': 10.0}], 't1')
        second = limits.merge(first, [{'label': '5-hour limit', 'used_percent': 20.0},
                                      {'label': 'Weekly limit', 'used_percent': 5.0}], 't2')
        self.assertEqual(second, {'at': 't2', 'windows': [{'label': '5-hour limit', 'used_percent': 20.0},
                                                         {'label': 'Weekly limit', 'used_percent': 5.0}]})
        self.assertEqual(limits.public({'provider_limits': {'claude': second, 'other': second, 'codex': 'x'}}),
                         {'claude': second})


class SchedulerTests(ResearchCase):
    def test_a_sessions_reading_is_stored_for_its_provider(self):
        def parent(session, text, ctx):
            ctx.report_limits({'status': 'allowed', 'rateLimitType': 'seven_day', 'utilization': 0.2})
            ctx.report_limits({'status': 'nonsense'})
            return answering(self.results, [])(session, text, ctx)
        self.make(parent)
        self.store.add_research_task('r1')
        self.run_task()
        stored = self.store.state['provider_limits']
        self.assertEqual(list(stored), ['claude'])  # The parent runtime is Claude in these tests.
        self.assertEqual(stored['claude']['windows'], [{'label': 'Weekly limit', 'status': 'allowed', 'used_percent': 20.0}])
        self.assertTrue(stored['claude']['at'])


if __name__ == '__main__':
    unittest.main()
