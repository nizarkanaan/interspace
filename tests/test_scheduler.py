"""Scheduler, locks, event log and run context, with a fake runtime (no provider is started)."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
sys.path.insert(0, str(ROOT / 'tests'))

import scheduler
from agent_fakes import (FakeAudit, FakeRuntime, FakeScope, FakeWorkspaces, MemoryStore,
                         default_script, wait_for, wait_interrupt)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class SchedulerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def make(self, max_running=4, script=default_script, grace=0.2, monotonic=None, policy=None):
        self.scope = FakeScope()
        self.audit = FakeAudit()
        self.store = MemoryStore(self.scope)
        self.store.add_project('p1')
        self.store.add_project('p2')
        self.emitted = []
        self.events = scheduler.EventLog(self.root / 'tasks', forward=self.emitted.append)
        self.runtime = FakeRuntime(script)
        self.locks = scheduler.Locks()
        self.workspaces = FakeWorkspaces(self.root / 'workspaces')
        self.sched = scheduler.Scheduler(
            max_running=max_running, runtime_factory=lambda task_id: self.runtime, policy=policy(self.scope) if policy else self.scope,
            audit=self.audit, events=self.events, budget_gate=scheduler.BudgetGate(self.store), locks=self.locks,
            clock=time.time, tasks=self.store, workspaces=self.workspaces,
            interrupt_grace_s=grace,
            decide_options={'app_data': str(self.root / 'data')},
            monotonic=monotonic or time.monotonic, tick_s=0.01)
        self.addCleanup(self.sched.shutdown, 5)
        return self.sched

    def task(self, task_id, project_id='p1', **kwargs):
        return self.store.add_task(task_id, project_id, **kwargs)

    def state(self, task_id):
        return self.store.task(task_id)['agent']['state']

    def wait_state(self, task_id, *states):
        wait_for(lambda: self.state(task_id) in states, message=task_id + ' in ' + repr(states))

    def kinds(self, task_id):
        return [e['kind'] for e in self.events.read(task_id, 0, 1000)['events']]

    def statuses(self, task_id):
        return [e['data']['state'] for e in self.events.read(task_id, 0, 1000)['events'] if e['kind'] == 'status']


class ConcurrencyTests(SchedulerCase):
    def test_several_tasks_run_at_once(self):
        barrier = threading.Barrier(3, timeout=5)
        release = threading.Event()

        def script(session, text, ctx):
            barrier.wait()  # Fails unless all three turns are in flight together.
            release.wait(5)
            return default_script(session, text, ctx)
        self.make(script=script)
        for name in ('a', 'b', 'c'):
            self.task(name)
            self.assertEqual(self.sched.submit(name, 'p1', 'go ' + name, 'c-' + name)['state'], 'starting')
        wait_for(lambda: all(self.state(n) == 'running' for n in 'abc'))
        snapshot = self.sched.snapshot()
        self.assertEqual(sorted(r['task_id'] for r in snapshot['running']), ['a', 'b', 'c'])
        self.assertEqual(snapshot['queued'], [])
        self.assertEqual(snapshot['max_running'], 4)
        release.set()
        for name in 'abc':
            self.wait_state(name, 'idle')
        self.assertEqual(self.sched.snapshot()['running'], [])

    def test_tasks_beyond_max_running_queue_fifo(self):
        gates = {n: threading.Event() for n in 'abcd'}

        def script(session, text, ctx):
            gates[ctx.task_id].wait(5)
            return default_script(session, text, ctx)
        self.make(max_running=2, script=script)
        for n in 'abcd':
            self.task(n)
        results = [self.sched.submit(n, 'p1', 'x', None) for n in 'abcd']
        self.assertEqual([r['state'] for r in results], ['starting', 'starting', 'queued', 'queued'])
        self.assertEqual([r['position'] for r in results], [None, None, 1, 2])
        self.assertEqual([(q['task_id'], q['position']) for q in self.sched.snapshot()['queued']], [('c', 1), ('d', 2)])
        self.assertEqual(self.statuses('c'), ['queued'])
        gates['b'].set()
        self.wait_state('c', 'running')
        self.assertEqual(self.state('d'), 'queued')
        self.assertEqual(self.sched.snapshot()['queued'][0]['position'], 1)
        for n in 'acd':
            gates[n].set()
        for n in 'abcd':
            self.wait_state(n, 'idle')

    def test_snapshot_has_no_legacy_slot(self):
        self.make(max_running=1)
        self.assertEqual(self.sched.snapshot(), {'max_running': 1, 'running': [], 'queued': []})
        self.assertFalse(hasattr(self.sched, 'legacy_slot_free'))

    def test_submit_requires_current_approval_and_one_turn_at_a_time(self):
        gate = threading.Event()

        def script(session, text, ctx):
            gate.wait(5)
            return default_script(session, text, ctx)
        self.make(script=script)
        self.task('a', approve=False)
        with self.assertRaisesRegex(ValueError, 'Approve'):
            self.sched.submit('a', 'p1', 'x', None)
        self.assertEqual(self.events.read('a', 0)['events'], [])
        self.task('b')
        self.store.task('b')['scope']['web_search'] = 'allow'  # An edit after approval invalidates it.
        with self.assertRaisesRegex(ValueError, 'Approve'):
            self.sched.submit('b', 'p1', 'x', None)
        self.task('c')
        self.sched.submit('c', 'p1', 'x', None)
        with self.assertRaisesRegex(ValueError, 'already working'):
            self.sched.submit('c', 'p1', 'y', None)
        gate.set()
        self.wait_state('c', 'idle')
        self.sched.submit('c', 'p1', 'second turn', None)
        self.wait_state('c', 'idle')
        wait_for(lambda: len(self.runtime.turns) == 2)
        self.assertEqual(len(self.runtime.sessions), 1, 'an idle task reuses its runtime session')

    def test_set_max_running_validates_and_starts_queued_work(self):
        gate = threading.Event()

        def script(session, text, ctx):
            gate.wait(5)
            return default_script(session, text, ctx)
        self.make(max_running=1, script=script)
        for bad in (0, 17, '2', True):
            with self.assertRaises(ValueError):
                self.sched.set_max_running(bad)
        self.task('a')
        self.task('b')
        self.sched.submit('a', 'p1', 'x', None)
        self.assertEqual(self.sched.submit('b', 'p1', 'x', None)['state'], 'queued')
        self.sched.set_max_running(2)
        self.wait_state('b', 'running')
        gate.set()
        self.wait_state('a', 'idle')
        self.wait_state('b', 'idle')


class LockTests(SchedulerCase):
    def test_fifo_timeout_cancel_and_one_lock_per_task(self):
        locks = scheduler.Locks()
        never = threading.Event()
        locks.acquire('project:p1', 't1', never)
        self.assertEqual(locks.holders(), {'project:p1': 't1'})
        with self.assertRaisesRegex(ValueError, 'one lock'):
            locks.acquire('app:x', 't1', never)
        order = []

        def waiter(name):
            locks.acquire('project:p1', name, never)
            order.append(name)
            locks.release('project:p1', name)
        threads = []
        for name in ('t2', 't3', 't4'):
            thread = threading.Thread(target=waiter, args=(name,))
            thread.start()
            threads.append(thread)
            wait_for(lambda: len(locks.waiting('project:p1')) == len(threads))
        with self.assertRaises(scheduler.LockTimeout):
            locks.acquire('project:p1', 't5', never, timeout_s=0.05)
        cancel = threading.Event()
        errors = []

        def cancelled():
            try:
                locks.acquire('project:p1', 't6', cancel)
            except scheduler.Cancelled as error:
                errors.append(error)
        thread = threading.Thread(target=cancelled)
        thread.start()
        wait_for(lambda: 't6' in locks.waiting('project:p1'))
        started = time.monotonic()
        cancel.set()
        thread.join(2)
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(len(errors), 1)
        locks.release('project:p1', 't1')
        for thread in threads:
            thread.join(2)
        self.assertEqual(order, ['t2', 't3', 't4'])
        self.assertEqual(locks.holders(), {})
        with self.assertRaises(ValueError):
            locks.release('project:p1', 't1')

class CancelTests(SchedulerCase):
    def test_cancel_queued_task(self):
        gate = threading.Event()

        def script(session, text, ctx):
            gate.wait(5)
            return default_script(session, text, ctx)
        self.make(max_running=1, script=script)
        self.task('a')
        self.task('b')
        self.sched.submit('a', 'p1', 'x', None)
        self.sched.submit('b', 'p1', 'x', None)
        self.assertTrue(self.sched.cancel('b'))
        self.assertEqual(self.state('b'), 'cancelled')
        self.assertEqual(self.sched.snapshot()['queued'], [])
        self.assertFalse(self.sched.cancel('b'))
        gate.set()
        self.wait_state('a', 'idle')
        self.assertEqual([t for t, _ in self.runtime.turns], ['a'])

    def test_cancel_running_interrupts_turn(self):
        self.make(script=wait_interrupt(honor=True))
        self.task('a')
        self.sched.submit('a', 'p1', 'x', None)
        self.wait_state('a', 'running')
        self.assertTrue(self.sched.cancel('a'))
        self.wait_state('a', 'cancelled')
        session = self.runtime.sessions[0]
        self.assertTrue(session.interrupted.is_set())
        self.assertFalse(session.killed.is_set())
        self.assertIn('cancelling', self.statuses('a'))
        budget = [e['data'] for e in self.events.read('a', 0)['events'] if e['kind'] == 'budget']
        self.assertEqual([b['charge_kind'] for b in budget], ['reserved', 'estimated'])

    def test_cancel_kills_turn_that_ignores_interrupt(self):
        self.make(script=wait_interrupt(honor=False), grace=0.1)
        self.task('a')
        self.sched.submit('a', 'p1', 'x', None)
        self.wait_state('a', 'running')
        self.sched.cancel('a')
        self.wait_state('a', 'cancelled')
        session = self.runtime.sessions[0]
        self.assertTrue(session.interrupted.is_set())
        self.assertTrue(session.killed.is_set())

    def test_cancel_paused_ask_closes_ask(self):
        decisions = []

        def script(session, text, ctx):
            decisions.append(ctx.authorize({'category': 'command', 'argv': ['ls']}, 'c1'))
            return {'status': 'cancelled', 'usage': None, 'error': None}
        self.make(script=script)
        self.task('a', rules={'command': 'ask'})
        self.sched.submit('a', 'p1', 'x', None)
        self.wait_state('a', 'paused_ask')
        self.sched.cancel('a')
        self.wait_state('a', 'cancelled')
        self.assertEqual(decisions[0]['decision'], 'deny')
        answers = [e['data'] for e in self.events.read('a', 0)['events'] if e['kind'] == 'answer']
        self.assertEqual(answers[0]['decision'], 'cancelled')
        self.assertIn('cancelled', [r['decision'] for r in self.audit.records if r['kind'] == 'answer'])

    def test_shutdown_interrupts_everything(self):
        self.make(max_running=1, script=wait_interrupt(honor=True))
        self.task('a')
        self.task('b')
        self.sched.submit('a', 'p1', 'x', None)
        self.sched.submit('b', 'p1', 'x', None)
        self.wait_state('a', 'running')
        self.sched.shutdown(5)
        self.assertEqual(self.state('a'), 'interrupted')
        self.assertEqual(self.state('b'), 'interrupted')
        with self.assertRaises(ValueError):
            self.sched.submit('a', 'p1', 'x', None)


class EventTests(SchedulerCase):
    def test_turn_events_are_ordered_and_persisted_before_forwarding(self):
        seen_on_disk = []

        def forward(event):
            lines = (self.root / 'tasks' / event['task_id'] / 'events.jsonl').read_text().splitlines()
            seen_on_disk.append(json.loads(lines[-1])['seq'] == event['seq'])
        self.make()
        self.events.forward = forward
        self.task('a')
        self.sched.submit('a', 'p1', 'hello', 'client-1')
        self.wait_state('a', 'idle')
        events = self.events.read('a', 0)['events']
        self.assertEqual([e['seq'] for e in events], list(range(1, len(events) + 1)))
        self.assertTrue(all(seen_on_disk) and seen_on_disk)
        self.assertEqual(self.kinds('a'), ['status', 'message', 'budget', 'status', 'message', 'budget', 'diff', 'status'])
        self.assertEqual(self.statuses('a'), ['starting', 'running', 'idle'])
        user = events[1]
        self.assertEqual(user['data'], {'role': 'user', 'text': 'hello', 'final': True, 'client_id': 'client-1'})
        turn = user['turn_id']
        self.assertTrue(turn)
        for event in events:
            self.assertEqual(event['v'], 1)
            self.assertEqual(event['project_id'], 'p1')
            self.assertTrue(event['at'].endswith('Z'))
            if event['kind'] == 'status':
                self.assertIsNone(event['turn_id'])
            else:
                self.assertEqual(event['turn_id'], turn)
        diff = [e for e in events if e['kind'] == 'diff'][0]['data']
        self.assertTrue(diff['cumulative'])
        self.assertIsNone(diff['call_id'])
        reported = [e for e in events if e['kind'] == 'budget'][-1]['data']
        self.assertEqual((reported['charge_kind'], reported['tokens'], reported['used'], reported['reserved']), ('reported', 1200, 1200, 0))

    def test_replay_after_restart_continues_sequence(self):
        log = scheduler.EventLog(self.root / 'tasks', forward=lambda e: None)
        for index in range(5):
            log.append('t', 'p', 'message', {'role': 'assistant', 'text': str(index), 'final': True}, turn_id='u1', item_id='m')
        with (self.root / 'tasks/t/events.jsonl').open('a') as handle:
            handle.write('{"v":1,"seq":6,"kind":')  # A crash mid-write leaves a partial line.
        reopened = scheduler.EventLog(self.root / 'tasks', forward=lambda e: None)
        self.assertEqual(reopened.last_seq('t'), 5)
        event = reopened.append('t', 'p', 'status', {'state': 'idle', 'detail': '', 'queue_position': None, 'reason': None})
        self.assertEqual(event['seq'], 6)
        page = reopened.read('t', 2, limit=2)
        self.assertEqual([e['seq'] for e in page['events']], [3, 4])
        self.assertEqual(page['last_seq'], 6)
        self.assertFalse(page['complete'])
        tail = reopened.read('t', 4)
        self.assertEqual([e['seq'] for e in tail['events']], [5, 6])
        self.assertTrue(tail['complete'])
        self.assertEqual(reopened.read('missing', 0), {'events': [], 'last_seq': 0, 'complete': True})
        for bad in (-1, 'x', True):
            with self.assertRaises(ValueError):
                reopened.read('t', bad)
        with self.assertRaises(ValueError):
            reopened.read('t', 0, limit=1001)
        with self.assertRaises(ValueError):
            reopened.read('../escape', 0)

    def test_large_event_is_cut_and_blob_is_readable(self):
        log = scheduler.EventLog(self.root / 'tasks', forward=lambda e: None)
        text = 'x' * 200000
        event = log.append('t', 'p', 'message', {'role': 'assistant', 'text': text, 'final': True})
        self.assertLessEqual(len(json.dumps(event).encode()), scheduler.MAX_EVENT_BYTES)
        self.assertTrue(event['data']['truncated'])
        blob = log.blob('t', event['data']['blob_id'])
        self.assertEqual(blob['text'], text)
        with self.assertRaises(ValueError):
            log.blob('t', '../events.jsonl')

    def test_recovery_marks_unfinished_tasks_interrupted(self):
        self.make()
        for name, state in (('a', 'running'), ('b', 'paused_ask'), ('c', 'idle'), ('d', 'queued'), ('e', 'cancelled')):
            self.task(name)['agent']['state'] = state
        changed = scheduler.recover(self.store, self.events)
        self.assertEqual(sorted(changed), ['a', 'b', 'd'])
        self.assertEqual([self.state(n) for n in 'abcde'], ['interrupted', 'interrupted', 'idle', 'interrupted', 'cancelled'])
        self.assertEqual(self.statuses('a'), ['interrupted'])
        self.assertEqual(self.statuses('c'), [])

    def test_runtime_may_only_emit_its_own_kinds(self):
        errors = []

        def script(session, text, ctx):
            for kind, data in (('status', {'state': 'idle'}), ('budget', {}), ('message', {'role': 'user', 'text': 'x'})):
                try:
                    ctx.emit(kind, data)
                except ValueError as error:
                    errors.append(kind)
            ctx.emit('tool_output_delta', {'call_id': 'c1', 'stream': 'stdout', 'text': 'ok'}, item_id='c1')
            return {'status': 'completed', 'usage': None, 'error': None}
        self.make(script=script)
        self.task('a')
        self.sched.submit('a', 'p1', 'x', None)
        self.wait_state('a', 'idle')
        self.assertEqual(errors, ['status', 'budget', 'message'])
        self.assertIn('tool_output_delta', self.kinds('a'))


class BudgetTests(SchedulerCase):
    def test_concurrent_turns_keep_ledgers_separate_and_consistent(self):
        def script(session, text, ctx):
            time.sleep(0.01)
            return {'status': 'completed', 'usage': {'input_tokens': 900, 'output_tokens': 100}, 'error': None}
        self.make(script=script)
        names = ['t%d' % i for i in range(8)]
        for name in names:
            self.task(name)
        for name in names:
            self.sched.submit(name, 'p1', 'x', None)
        for name in names:
            self.wait_state(name, 'idle')
        for name in names:
            self.sched.submit(name, 'p1', 'again', None)
        for name in names:
            wait_for(lambda: self.state(name) == 'idle' and len([e for e in self.store.state['usage'] if e['task_id'] == name and e['charge_kind'] == 'reported']) == 2)
        for name in names:
            entries = [e for e in self.store.state['usage'] if e['task_id'] == name]
            self.assertEqual(len(entries), 2)
            for entry in entries:
                self.assertEqual((entry['provider'], entry['charge_rule'], entry['call_kind'], entry['charge']),
                                 ('codex', 'codex.input+output', 'agent_turn', 1000))
                self.assertTrue(entry['turn_id'])
        self.assertEqual(len(self.store.state['usage']), 16)

    def test_turn_that_cannot_fit_never_starts(self):
        self.make()
        self.task('a', token_budget=1000)
        self.sched.submit('a', 'p1', 'x', None)
        self.wait_state('a', 'budget_exhausted')
        self.assertEqual(self.runtime.turns, [])
        self.assertEqual(self.store.state['usage'], [])
        errors = [e['data'] for e in self.events.read('a', 0)['events'] if e['kind'] == 'error']
        self.assertEqual(errors[0]['code'], 'budget_exhausted')
        self.assertFalse(errors[0]['recoverable'])

    def test_mid_turn_usage_beyond_budget_interrupts(self):
        def script(session, text, ctx):
            ctx.report_usage({'input_tokens': 10000, 'output_tokens': 10})
            self.assertFalse(session.interrupted.is_set())
            ctx.report_usage({'input_tokens': 60000, 'output_tokens': 1000})
            session.interrupted.wait(5)
            return {'status': 'cancelled', 'usage': {'input_tokens': 61000, 'output_tokens': 1000}, 'error': None}
        self.make(script=script)
        self.task('a', token_budget=60000)
        self.sched.submit('a', 'p1', 'x', None)
        self.wait_state('a', 'budget_exhausted')
        self.assertTrue(self.runtime.sessions[0].interrupted.is_set())
        last = [e['data'] for e in self.events.read('a', 0)['events'] if e['kind'] == 'budget'][-1]
        self.assertEqual((last['charge_kind'], last['used'], last['overshoot']), ('reported', 62000, 2000))
        self.assertEqual(self.workspaces.published, ['interspace/task-a'], 'work is kept and published')


class TimeLimitTests(SchedulerCase):
    def test_active_time_limit_cancels_turn(self):
        clock = Clock()

        def script(session, text, ctx):
            clock.now += 61
            session.interrupted.wait(5)
            return {'status': 'cancelled', 'usage': None, 'error': None}
        self.make(script=script, monotonic=clock)
        self.task('a', time_limit_s=60)
        self.sched.submit('a', 'p1', 'x', None)
        self.wait_state('a', 'time_limit')
        errors = [e['data']['code'] for e in self.events.read('a', 0)['events'] if e['kind'] == 'error']
        self.assertEqual(errors, ['time_limit'])
        self.assertGreaterEqual(self.store.task('a')['agent']['active_s'], 60)

    def test_paused_time_does_not_count(self):
        clock = Clock()

        def script(session, text, ctx):
            ctx.authorize({'category': 'command', 'argv': ['ls']}, 'c1')
            return {'status': 'completed', 'usage': None, 'error': None}
        self.make(script=script, monotonic=clock)
        self.task('a', time_limit_s=60, rules={'command': 'ask'})
        self.sched.submit('a', 'p1', 'x', None)
        self.wait_state('a', 'paused_ask')
        clock.now += 1000
        time.sleep(0.05)
        self.assertEqual(self.state('a'), 'paused_ask')
        ask = [e for e in self.events.read('a', 0)['events'] if e['kind'] == 'ask'][-1]['data']
        self.sched.answer('a', ask['ask_id'], 'allow_once', request_digest=ask['request_digest'])
        self.wait_state('a', 'idle')
        self.assertLess(self.store.task('a')['agent']['active_s'], 60)


class AuthorizeTests(SchedulerCase):
    def run_one(self, rules, request, answer=None, **answer_args):
        decisions = []

        def script(session, text, ctx):
            decisions.append(ctx.authorize(request, 'call-9'))
            return {'status': 'completed', 'usage': None, 'error': None}
        self.make(script=script)
        self.task('a', rules=rules)
        self.sched.submit('a', 'p1', 'x', None)
        if answer:
            self.wait_state('a', 'paused_ask')
            ask = [e for e in self.events.read('a', 0)['events'] if e['kind'] == 'ask'][-1]['data']
            answer(ask)
        self.wait_state('a', 'idle')
        return decisions[0]

    def test_allow_and_deny_are_audited_before_returning(self):
        decision = self.run_one({'command': 'allow'}, {'category': 'command', 'argv': ['ls']})
        self.assertEqual(decision['decision'], 'allow')
        record = [r for r in self.audit.records if r['kind'] == 'decision'][0]
        self.assertEqual((record['actor'], record['task_id'], record['call_id'], record['decision'], record['v']),
                         ('agent', 'a', 'call-9', 'allow', 1))
        self.assertIn('p1', self.scope.calls[0][1], 'decide gets the task workspace roots')
        decision = self.run_one({'command': 'deny'}, {'category': 'command', 'argv': ['ls']})
        self.assertEqual(decision['decision'], 'deny')

    def test_policy_failure_and_audit_failure_fail_closed(self):
        self.make()
        decisions = []

        def script(session, text, ctx):
            self.scope.fail = True
            decisions.append(ctx.authorize({'category': 'command', 'argv': ['ls']}, 'c1'))
            self.scope.fail = False
            self.audit.fail = True
            decisions.append(ctx.authorize({'category': 'command', 'argv': ['ls']}, 'c2'))
            self.audit.fail = False
            return {'status': 'completed', 'usage': None, 'error': None}
        self.runtime.script = script
        self.task('a')
        self.sched.submit('a', 'p1', 'x', None)
        self.wait_state('a', 'idle')
        self.assertEqual([(d['decision'], d['rule']) for d in decisions], [('deny', 'policy.failed'), ('deny', 'audit.failed')])
        codes = [e['data']['code'] for e in self.events.read('a', 0)['events'] if e['kind'] == 'error']
        self.assertEqual(codes, ['policy_failed', 'audit_failed'])

    def test_allow_once_answer_binds_request_digest(self):
        def answer(ask):
            with self.assertRaisesRegex(ValueError, 'changed'):
                self.sched.answer('a', ask['ask_id'], 'allow_once', request_digest='sha256:other')
            with self.assertRaisesRegex(ValueError, 'not offered'):
                self.sched.answer('a', ask['ask_id'], 'text', request_digest=ask['request_digest'])
            with self.assertRaisesRegex(ValueError, 'no longer open'):
                self.sched.answer('a', 'nope', 'allow_once', request_digest=ask['request_digest'])
            self.sched.answer('a', ask['ask_id'], 'allow_once', request_digest=ask['request_digest'])
        decision = self.run_one({'command': 'ask'}, {'category': 'command', 'argv': ['ls']}, answer)
        self.assertEqual((decision['decision'], decision['rule']), ('allow', 'ask.allow_once'))
        kinds = self.kinds('a')
        self.assertLess(kinds.index('ask'), kinds.index('answer'))
        self.assertIn('paused_ask', self.statuses('a'))
        answer_event = [e for e in self.events.read('a', 0)['events'] if e['kind'] == 'answer'][0]
        self.assertIsNone(answer_event['turn_id'])
        self.assertEqual(answer_event['item_id'], [e for e in self.events.read('a', 0)['events'] if e['kind'] == 'ask'][0]['item_id'])

    def test_add_to_scope_amends_and_reapproves(self):
        def answer(ask):
            with self.assertRaisesRegex(ValueError, 'scope'):
                self.sched.answer('a', ask['ask_id'], 'add_to_scope', request_digest=ask['request_digest'], scope_digest='sha256:bad')
            self.sched.answer('a', ask['ask_id'], 'add_to_scope', request_digest=ask['request_digest'],
                              scope_digest=ask['patched_scope_digest'])
        decision = self.run_one({'command': 'ask'}, {'category': 'command', 'argv': ['make']}, answer)
        self.assertEqual((decision['decision'], decision['rule']), ('allow', 'ask.add_to_scope'))
        task = self.store.task('a')
        self.assertEqual(task['scope']['version'], 2)
        self.assertEqual(task['scope']['fake_rules']['command'], 'allow')
        self.assertEqual(task['scope_approval']['scope_digest'], self.scope.digest(task['scope']))
        self.assertEqual(task['scope_approval']['scope_version'], 2)
        scope_events = [e['data'] for e in self.events.read('a', 0)['events'] if e['kind'] == 'scope']
        self.assertEqual(scope_events[-1]['change'], 'amended')
        answer_event = [e['data'] for e in self.events.read('a', 0)['events'] if e['kind'] == 'answer'][0]
        self.assertEqual(answer_event['scope_version'], 2)

    def test_deny_answer_and_scope_edit_pause(self):
        decision = self.run_one({'command': 'ask'}, {'category': 'command', 'argv': ['ls']},
                                lambda ask: self.sched.answer('a', ask['ask_id'], 'deny', request_digest=ask['request_digest']))
        self.assertEqual((decision['decision'], decision['rule']), ('deny', 'ask.deny'))

    def test_unapproved_scope_pauses_task_until_approval(self):
        decisions = []

        def script(session, text, ctx):
            task = self.store.task('a')
            with self.store.lock:
                task['scope']['version'] += 1
                task['scope_approval'] = None
            self.sched.scope_changed('a')
            decisions.append(ctx.authorize({'category': 'command', 'argv': ['ls']}, 'c1'))
            return {'status': 'completed', 'usage': None, 'error': None}
        self.make(script=script)
        self.task('a')
        self.sched.submit('a', 'p1', 'x', None)
        self.wait_state('a', 'paused_scope')
        self.assertNotIn('ask', self.kinds('a'))
        task = self.store.task('a')
        with self.store.lock:
            task['scope_approval'] = {'v': 1, 'scope_version': 2, 'scope_digest': self.scope.digest(task['scope']),
                                      'approved_at': 'x', 'by': 'user'}
        self.sched.scope_changed('a')
        self.wait_state('a', 'idle')
        self.assertEqual(decisions[0]['decision'], 'allow')

    def test_decide_gets_options(self):
        def script(session, text, ctx):
            ctx.authorize({'category': 'command', 'argv': ['ls']}, 'c0')
            return {'status': 'completed', 'usage': None, 'error': None}
        self.make(script=script)
        self.task('a')
        self.sched.submit('a', 'p1', 'x', None)
        self.wait_state('a', 'idle')
        self.assertEqual(self.scope.decide_options[0]['app_data'], str(self.root / 'data'))


class FailureTests(SchedulerCase):
    def test_runtime_crash_fails_task_and_frees_slot(self):
        def script(session, text, ctx):
            raise RuntimeError('provider exploded with secret details')
        self.make(max_running=1, script=script)
        self.task('a')
        self.task('b')
        self.sched.submit('a', 'p1', 'x', None)
        self.wait_state('a', 'failed')
        error = [e['data'] for e in self.events.read('a', 0)['events'] if e['kind'] == 'error'][0]
        self.assertEqual(error['code'], 'runtime_exited')
        self.assertNotIn('secret', error['message'])
        self.runtime.script = default_script
        self.sched.submit('b', 'p1', 'x', None)
        self.wait_state('b', 'idle')
        self.sched.submit('a', 'p1', 'again', None)  # A terminal task continues with a new turn.
        self.wait_state('a', 'idle')

    def test_workspace_failure_fails_before_runtime(self):
        self.make()
        self.workspaces.fail = True
        self.task('a')
        self.sched.submit('a', 'p1', 'x', None)
        self.wait_state('a', 'failed')
        self.assertEqual(self.runtime.turns, [])
        self.assertEqual(self.store.state['usage'], [])
        error = [e['data'] for e in self.events.read('a', 0)['events'] if e['kind'] == 'error'][0]
        self.assertEqual(error['code'], 'workspace_failed')


@unittest.skipUnless(scheduler.shutil_which('git'), 'git is required')
class RuntimeSupportTests(SchedulerCase):
    """Wave 2A: the answer path through scope.apply_answer, RunContext.tools/observed and runtime failures."""

    def ask_and_answer(self, decision, policy=None, **answer_args):
        decisions = []

        def script(session, text, ctx):
            decisions.append(ctx.authorize({'category': 'command', 'argv': ['ls']}, 'call-1'))
            return {'status': 'completed', 'usage': None, 'error': None}
        self.make(script=script, policy=policy)
        self.task('a', rules={'command': 'ask'})
        self.sched.submit('a', 'p1', 'x', None)
        self.wait_state('a', 'paused_ask')
        ask = [e for e in self.events.read('a', 0)['events'] if e['kind'] == 'ask'][-1]['data']
        if decision == 'add_to_scope':
            answer_args.setdefault('scope_digest', ask['patched_scope_digest'])
        self.sched.answer('a', ask['ask_id'], decision, request_digest=ask['request_digest'], **answer_args)
        self.wait_state('a', 'idle')
        return decisions[0], ask

    def test_every_answer_goes_through_apply_answer(self):
        for decision, rule in (('allow_once', 'ask.allow_once'), ('deny', 'ask.deny'), ('add_to_scope', 'ask.add_to_scope')):
            with self.subTest(decision=decision):
                final, ask = self.ask_and_answer(decision)
                self.assertEqual(final['rule'], rule)
                stored, answer = self.scope.answers[-1]
                self.assertEqual((stored['ask_id'], answer['decision'], answer['request_digest']),
                                 (ask['ask_id'], decision, ask['request_digest']))

    def test_apply_answer_is_found_on_a_wrapped_scope_module(self):
        class Adapter:  # Like service.ScopeAdapter: the scope functions, plus the module itself.
            def __init__(self, module):
                self.module = module

            def __getattr__(self, name):
                if name == 'apply_answer':
                    raise AttributeError(name)
                return getattr(self.module, name)
        final, _ = self.ask_and_answer('add_to_scope', policy=Adapter)
        self.assertEqual(final['rule'], 'ask.add_to_scope')
        self.assertEqual(self.store.task('a')['scope']['version'], 2)
        self.assertTrue(self.scope.answers)

    def test_allow_once_is_refused_when_the_scope_was_edited(self):
        def script(session, text, ctx):
            return {'status': 'completed', 'usage': None, 'error': None}
        decisions = []

        def asking(session, text, ctx):
            decisions.append(ctx.authorize({'category': 'command', 'argv': ['ls']}, 'call-1'))
            return script(session, text, ctx)
        self.make(script=asking)
        self.task('a', rules={'command': 'ask'})
        self.sched.submit('a', 'p1', 'x', None)
        self.wait_state('a', 'paused_ask')
        ask = [e for e in self.events.read('a', 0)['events'] if e['kind'] == 'ask'][-1]['data']
        with self.store.lock:
            self.store.task('a')['scope']['limits']['time_limit_s'] = 120  # Edited, not re-approved.
        with self.assertRaisesRegex(ValueError, 'approve'):
            self.sched.answer('a', ask['ask_id'], 'allow_once', request_digest=ask['request_digest'])
        self.sched.cancel('a')
        self.wait_state('a', 'cancelled')

    def test_plain_agent_tasks_get_no_tools_and_orchestrate_refuses(self):
        seen = []

        def script(session, text, ctx):
            seen.append((ctx.tools(), ctx.access, ctx.role, ctx.instructions))
            with self.assertRaisesRegex(ValueError, 'Unknown tool'):
                ctx.orchestrate('propose_team', {})
            for name in ('propose_team', 'research_search'):
                with self.assertRaisesRegex(ValueError, 'Unknown tool'):
                    ctx.call_tool(name, {})
            seen.append('refused')
            return default_script(session, text, ctx)
        self.make(script=script)
        self.task('a')
        self.sched.submit('a', 'p1', 'x', None)
        self.wait_state('a', 'idle')
        self.assertEqual(seen, [([], 'write', None, None), 'refused'])
        self.assertNotIn('tool_call', self.kinds('a'))

    def test_observed_actions_are_audited_as_provider_sandbox(self):
        seen = []

        def script(session, text, ctx):
            seen.append(ctx.observed({'category': 'web_search', 'query': 'dates'}, 'w1'))
            return default_script(session, text, ctx)
        self.make(script=script)
        self.task('a', rules={'web_search': 'deny'})
        self.sched.submit('a', 'p1', 'x', None)
        self.wait_state('a', 'idle')
        self.assertEqual((seen[0]['decision'], seen[0]['rule'], seen[0]['scope_version']), ('allow', 'provider.sandbox', 1))
        record = [r for r in self.audit.records if r['kind'] == 'decision'][0]
        self.assertEqual((record['rule'], record['call_id'], record['detail']), ('provider.sandbox', 'w1', {'after_the_fact': True}))
        self.assertEqual(self.scope.calls, [])  # Never decided, never asked.
        self.assertNotIn('ask', self.kinds('a'))

    def test_observed_with_a_failing_audit_reports_an_error(self):
        def script(session, text, ctx):
            ctx.observed({'category': 'web_search', 'query': 'q'}, 'w1')
            return default_script(session, text, ctx)
        self.make(script=script)
        self.audit.fail = True
        self.task('a')
        self.sched.submit('a', 'p1', 'x', None)
        self.wait_state('a', 'idle')
        errors = [e['data'] for e in self.events.read('a', 0)['events'] if e['kind'] == 'error']
        self.assertEqual(errors[0]['code'], 'audit_failed')

    def test_runtime_failure_shows_its_code_and_message(self):
        from runtime import RuntimeFailure
        self.make()
        self.runtime.open = lambda ctx: (_ for _ in ()).throw(RuntimeFailure('runtime_unavailable', 'Sign in to Codex first.'))
        self.task('a')
        self.sched.submit('a', 'p1', 'x', None)
        self.wait_state('a', 'failed')
        errors = [e['data'] for e in self.events.read('a', 0)['events'] if e['kind'] == 'error']
        self.assertEqual((errors[-1]['code'], errors[-1]['message']), ('runtime_unavailable', 'Sign in to Codex first.'))
        self.assertEqual(self.store.task('a')['agent']['reason'], 'runtime_unavailable')

    def test_failed_turn_closes_the_session_and_the_next_turn_opens_a_new_one(self):
        results = iter([{'status': 'failed', 'usage': None, 'error': {'code': 'runtime_protocol', 'message': 'Bad message.'}},
                        {'status': 'completed', 'usage': None, 'error': None}])
        self.make(script=lambda session, text, ctx: next(results))
        self.task('a')
        self.sched.submit('a', 'p1', 'x', None)
        self.wait_state('a', 'failed')
        self.assertTrue(self.runtime.sessions[0].closed)
        with self.store.lock:
            self.store.task('a')['agent']['state'] = 'idle'
        self.sched.submit('a', 'p1', 'y', None)
        self.wait_state('a', 'idle')
        self.assertEqual(len(self.runtime.sessions), 2)

    def test_model_comes_from_the_task(self):
        seen = []
        self.make(script=lambda session, text, ctx: seen.append(ctx.model) or default_script(session, text, ctx))
        self.task('a')['model'] = 'gpt-6.1-sol'
        self.task('b')
        for name in 'ab':
            self.sched.submit(name, 'p1', 'x', None)
            self.wait_state(name, 'idle')
        self.assertEqual(seen, ['gpt-6.1-sol', None])


class WorkspaceTests(unittest.TestCase):
    def test_clone_publish_and_cumulative_diff_never_touch_user_checkout(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            repo = root / 'repo'
            repo.mkdir()
            git = ['git', '-c', 'user.name=T', '-c', 'user.email=t@example.invalid']
            subprocess.run(git + ['init', '-q', '-b', 'main', str(repo)], check=True)
            (repo / 'a.py').write_text('one\n')
            subprocess.run(git + ['-C', str(repo), 'add', '.'], check=True)
            subprocess.run(git + ['-C', str(repo), 'commit', '-qm', 'base'], check=True)
            clones = scheduler.Workspaces(root / 'workspaces')
            info = clones.prepare('a' * 32, 'p1', str(repo))
            work = Path(info['path'])
            self.assertEqual(info['branch'], 'interspace/task-aaaaaaaa')
            remotes = subprocess.run(['git', '-C', str(work), 'remote'], capture_output=True, text=True).stdout
            self.assertEqual(remotes.strip(), '')
            self.assertEqual(clones.prepare('a' * 32, 'p1', str(repo))['path'], info['path'])
            (work / 'a.py').write_text('two\n')
            (work / 'b.py').write_text('new\n')
            diff = clones.diff(info)
            self.assertEqual(sorted((f['path'], f['change']) for f in diff['files']), [('a.py', 'modify'), ('b.py', 'add')])
            self.assertIn('+two', diff['patch'])
            subprocess.run(git + ['-C', str(work), 'commit', '-qam', 'agent'], check=True)
            subprocess.run(git + ['-C', str(repo), 'branch', 'interspace/task-aaaaaaaa'], check=True)  # Not ours.
            published = clones.publish(info, str(repo))
            self.assertEqual(published, 'interspace/task-aaaaaaaa-2')
            self.assertEqual(clones.publish(info, str(repo)), published, 'the chosen name is kept')
            head = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True, text=True).stdout
            self.assertEqual(head.strip(), 'main')
            self.assertEqual((repo / 'a.py').read_text(), 'one\n')
            log = subprocess.run(['git', '-C', str(repo), 'log', '--format=%s', published], capture_output=True, text=True).stdout
            self.assertEqual(log.split(), ['agent', 'base'])


    def test_commit_records_the_agent_changes_on_the_task_branch_only(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            repo = root / 'repo'
            repo.mkdir()
            git = ['git', '-c', 'user.name=T', '-c', 'user.email=t@example.invalid']
            subprocess.run(git + ['init', '-q', '-b', 'main', str(repo)], check=True)
            (repo / 'a.py').write_text('one\n')
            subprocess.run(git + ['-C', str(repo), 'add', '.'], check=True)
            subprocess.run(git + ['-C', str(repo), 'commit', '-qm', 'base'], check=True)
            clones = scheduler.Workspaces(root / 'workspaces')
            info = clones.prepare('b' * 32, 'p1', str(repo))
            work = Path(info['path'])
            self.assertIsNone(clones.commit(info, 'Interspace task turn u1'), 'nothing to commit')
            (work / 'a.py').write_text('two\n')
            (work / 'c.py').write_text('new\n')
            for scratch in ('.interspace/tmp/x', '.claude/settings.json'):
                (work / scratch).parent.mkdir(parents=True, exist_ok=True)
                (work / scratch).write_text('scratch\n')
            commit = clones.commit(info, 'Interspace task turn u1')
            self.assertRegex(commit, r'^[0-9a-f]{40}$')
            files = subprocess.run(['git', '-C', str(work), 'show', '--format=%s%n%b', '--name-only', commit],
                                   capture_output=True, text=True).stdout.split()
            self.assertEqual(files, ['Interspace', 'task', 'turn', 'u1', 'a.py', 'c.py'])  # No trailers, no scratch.
            published = clones.publish(info, str(repo))
            shown = subprocess.run(['git', '-C', str(repo), 'show', published + ':a.py'], capture_output=True, text=True)
            self.assertEqual(shown.stdout, 'two\n')
            self.assertEqual((repo / 'a.py').read_text(), 'one\n')
            self.assertEqual(clones.diff(info)['files'][0]['path'], 'a.py')



class WorkspaceSafetyTests(unittest.TestCase):
    """Interspace runs git unsandboxed in a clone the agent can write: agent-written git metadata never runs code,
    never redirects a commit into another repository, and publishing never drops a commit the user added."""

    def setUp(self):
        import subprocess
        self.run_git = lambda *args, **kw: subprocess.run(list(args), capture_output=True, text=True, **kw)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git = ['git', '-c', 'user.name=T', '-c', 'user.email=t@example.invalid']
        subprocess.run(self.git + ['init', '-q', '-b', 'main', str(self.repo)], check=True)
        (self.repo / 'a.py').write_text('one\n')
        subprocess.run(self.git + ['-C', str(self.repo), 'add', '.'], check=True)
        subprocess.run(self.git + ['-C', str(self.repo), 'commit', '-qm', 'base'], check=True)
        self.clones = scheduler.Workspaces(self.root / 'workspaces')
        self.info = self.clones.prepare('c' * 32, 'p1', str(self.repo))
        self.work = Path(self.info['path'])

    def head(self, ref='main'):
        return self.run_git('git', '-C', str(self.repo), 'rev-parse', ref).stdout.strip()

    def test_agent_written_git_config_never_runs_a_command(self):
        marker = self.root / 'ran'
        script = self.root / 'evil.sh'
        script.write_text('#!/bin/sh\necho ran >> "%s"\ncat\n' % marker)
        script.chmod(0o755)
        with (self.work / '.git' / 'config').open('a') as handle:
            handle.write('[core]\n\tfsmonitor = %s\n[filter "x"]\n\tclean = %s\n\trequired = true\n'
                         '[diff]\n\texternal = %s\n[alias]\n\tstatus = !%s\n' % (script, script, script, script))
        (self.work / '.gitattributes').write_text('* filter=x\n')
        (self.work / 'a.py').write_text('two\n')
        commit = self.clones.commit(self.info, 'Interspace task turn u1')
        self.clones.diff(self.info)
        self.clones.publish(self.info, str(self.repo))
        self.assertFalse(marker.exists(), 'a command from the agent-written git config ran')
        self.assertRegex(commit, r'^[0-9a-f]{40}$')
        self.assertEqual(self.clones.prepare('c' * 32, 'p1', str(self.repo))['base_commit'], self.info['base_commit'])

    def test_a_redirected_git_directory_is_refused(self):
        before = self.head()
        real = self.work / '.git'
        real.rename(self.work / 'moved-git')
        for redirect in ('file', 'symlink'):
            if redirect == 'file':
                (self.work / '.git').write_text('gitdir: %s\n' % (self.repo / '.git'))
            else:
                (self.work / '.git').unlink()
                (self.work / '.git').symlink_to(self.repo / '.git')
            (self.work / 'a.py').write_text('agent ' + redirect + '\n')
            with self.assertRaises(ValueError):
                self.clones.commit(self.info, 'Interspace task turn u1')
            with self.assertRaises(ValueError):
                self.clones.diff(self.info)
            self.assertEqual(self.head(), before)
            self.assertEqual(self.run_git('git', '-C', str(self.repo), 'status', '--porcelain').stdout, '')
        (self.work / '.git').unlink()
        (self.work / 'moved-git').rename(real)
        (real / 'commondir').write_text(str(self.repo / '.git') + '\n')
        with self.assertRaises(ValueError):
            self.clones.commit(self.info, 'Interspace task turn u1')
        self.assertEqual(self.head(), before)

    def test_publish_never_drops_a_commit_the_user_added_on_the_task_branch(self):
        (self.work / 'a.py').write_text('two\n')
        self.clones.commit(self.info, 'Interspace task turn u1')
        published = self.clones.publish(self.info, str(self.repo))
        self.assertEqual(published, 'interspace/task-cccccccc')
        (self.work / 'b.py').write_text('more\n')
        self.clones.commit(self.info, 'Interspace task turn u2')
        self.assertEqual(self.clones.publish(self.info, str(self.repo)), published, 'a fast-forward keeps the name')
        # The user adds a commit on the task branch in their own repository (here through a worktree).
        side = self.root / 'side'
        self.run_git(*self.git, '-C', str(self.repo), 'worktree', 'add', '-q', str(side), published, check=True)
        (side / 'user.txt').write_text('mine\n')
        self.run_git(*self.git, '-C', str(side), 'add', '.', check=True)
        self.run_git(*self.git, '-C', str(side), 'commit', '-qm', 'user fix', check=True)
        self.run_git('git', '-C', str(self.repo), 'worktree', 'remove', str(side), check=True)
        user_head = self.head(published)
        (self.work / 'c.py').write_text('later\n')
        self.clones.commit(self.info, 'Interspace task turn u3')
        moved = self.clones.publish(self.info, str(self.repo))
        self.assertEqual(self.head(published), user_head, 'the user commit is still on the branch')
        self.assertEqual(moved, 'interspace/task-cccccccc-2')
        self.assertEqual(self.info['target_branch'], moved)
        log = self.run_git('git', '-C', str(self.repo), 'log', '--format=%s', moved).stdout.split('\n')
        self.assertIn('Interspace task turn u3', log)

if __name__ == '__main__':
    unittest.main()
