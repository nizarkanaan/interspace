"""The Orchestrator: team proposals, approval, mixed-provider child runs, budgets, cancel and restart.

Fake runtimes only: nothing starts a provider, signs in or touches the network.
"""
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

import orchestrator
import scheduler
import tasks
from agent_fakes import FakeAudit, FakeRuntime, FakeScope, FakeWorkspaces, MemoryStore, default_script, wait_for

CODEX_USAGE = {'input_tokens': 1000, 'output_tokens': 200}
CLAUDE_USAGE = {'input_tokens': 100, 'cache_creation_input_tokens': 300, 'cache_read_input_tokens': 2000,
                'output_tokens': 50}


def child_script(usage, gate=None, barrier=None, report=None):
    def script(session, text, ctx):
        if barrier is not None:
            barrier.wait()
        if gate is not None:
            gate.wait(5)
        ctx.emit('message', {'role': 'assistant', 'text': report or ('Report: ' + text), 'final': True}, item_id='m1')
        return {'status': 'completed', 'usage': dict(usage), 'error': None}
    return script


class OrchestratorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.results = []
        self.tool_errors = []

    def make(self, parent_script, codex=None, claude=None, max_running=4):
        self.scope = FakeScope()
        self.audit = FakeAudit()
        self.store = MemoryStore(self.scope)
        self.store.add_project('p1')
        self.events = scheduler.EventLog(self.root / 'tasks', forward=lambda e: None)
        self.codex = FakeRuntime(codex or child_script(CODEX_USAGE))
        self.claude = FakeRuntime(claude or child_script(CLAUDE_USAGE))
        self.claude.name = 'claude'
        self.orch_runtime = FakeRuntime(parent_script)
        self.orch_runtime.name = 'claude'

        def factory(task_id):
            task = self.store.task(task_id)
            if task.get('role') == 'orchestrator':
                return self.orch_runtime
            return self.claude if task.get('provider') == 'claude' else self.codex
        self.sched = scheduler.Scheduler(
            max_running=max_running, runtime_factory=factory, policy=self.scope, audit=self.audit, events=self.events,
            budget_gate=scheduler.BudgetGate(self.store), locks=scheduler.Locks(), clock=time.time, tasks=self.store,
            workspaces=FakeWorkspaces(self.root / 'workspaces'), interrupt_grace_s=0.2, tick_s=0.01)
        self.addCleanup(self.sched.shutdown, 5)
        return self.sched

    def parent(self, token_budget=250000):
        task = self.store.add_task('parent', 'p1', token_budget=token_budget)
        task.update(role='orchestrator', provider='claude')
        return task

    def state(self, task_id):
        return self.store.task(task_id)['agent']['state']

    def wait_state(self, task_id, *states, timeout=5.0):
        wait_for(lambda: self.state(task_id) in states, timeout=timeout, message=task_id + ' in ' + repr(states))

    def events_of(self, task_id, kind=None):
        found = self.events.read(task_id, 0, 1000)['events']
        return [e for e in found if kind is None or e['kind'] == kind]

    def proposal(self):
        wait_for(lambda: self.events_of('parent', 'team_proposed'), message='team_proposed')
        return self.events_of('parent', 'team_proposed')[-1]['data']

    def children(self):
        return [t for t in self.store.agent_tasks() if t.get('parent_task_id') == 'parent']

    def member_task(self, member_id):
        return next(t for t in self.children() if t['member_id'] == member_id)


TEAM = {'summary': 'Research the parser, then fix it.',
        'members': [{'role': 'researcher', 'brief': 'Find where dates are parsed.'},
                    {'role': 'implementer', 'brief': 'Fix the ISO date parsing.'}]}


def orchestrating(results, team=TEAM, wait=True, then=None):
    """A parent turn that proposes `team`, waits for every member and records each tool result."""
    def script(session, text, ctx):
        proposed = ctx.orchestrate('propose_team', team)
        results.append(proposed)
        if proposed.get('status') in ('approved', 'changed') and wait:
            results.append(ctx.orchestrate('wait_for', {'team_id': proposed['team_id'], 'timeout_s': 10}))
            if then:
                then(ctx, proposed)
        ctx.emit('message', {'role': 'assistant', 'text': 'Summary.', 'final': True}, item_id='m1')
        return {'status': 'completed', 'usage': dict(CLAUDE_USAGE), 'error': None}
    return script


class ProposalTests(OrchestratorCase):
    def test_mixed_team_runs_in_parallel_after_approval(self):
        barrier = threading.Barrier(2, timeout=5)  # Fails unless both children run at once.
        self.make(orchestrating(self.results), codex=child_script(CODEX_USAGE, barrier=barrier),
                  claude=child_script(CLAUDE_USAGE, barrier=barrier))
        self.parent()
        self.sched.submit('parent', 'p1', 'Fix the parser', None)
        proposal = self.proposal()
        self.wait_state('parent', 'paused_team')
        self.assertEqual(self.children(), [])  # Nothing is created before approval.
        self.assertEqual([(m['member_id'], m['role'], m['provider'], m['model'], m['access'], m['default'])
                          for m in proposal['members']],
                         [('m1', 'researcher', 'codex', None, 'read', True),
                          ('m2', 'implementer', 'claude', 'claude-sonnet-5-5', 'write', True)])
        self.assertEqual(proposal['budget'], {'used': 0, 'budget': 250000})
        self.assertEqual(self.sched.orchestrator.answer({'task_id': 'parent', 'team_id': proposal['team_id'],
                                                         'decision': 'approve'}), {'status': 'approved'})
        self.wait_state('parent', 'idle')
        approved, waited = self.results
        self.assertEqual(approved['status'], 'approved')
        self.assertEqual([(m['member_id'], m['provider']) for m in approved['members']], [('m1', 'codex'), ('m2', 'claude')])
        self.assertFalse(waited['timed_out'])
        reports = {m['member_id']: m for m in waited['members']}
        self.assertEqual(reports['m1']['state'], 'idle')
        self.assertTrue(reports['m1']['report'].startswith('<untrusted-content>\nReport: Find where dates'))
        self.assertTrue(reports['m2']['report'].endswith('</untrusted-content>'))
        self.assertEqual(reports['m2']['diff_summary'], {'branch': 'interspace/task-' + self.member_task('m2')['id'][:8],
                                                         'files': []})
        kinds = [e['kind'] for e in self.events_of('parent')]
        for kind in ('team_proposed', 'team_answered', 'subagent_started', 'subagent_status', 'subagent_finished'):
            self.assertIn(kind, kinds)
        self.assertLess(kinds.index('team_answered'), kinds.index('subagent_started'))
        statuses = [e['data']['state'] for e in self.events_of('parent', 'status')]
        self.assertIn('paused_team', statuses)
        started = self.events_of('parent', 'subagent_started')
        self.assertEqual(sorted((e['data']['member_id'], e['data']['provider'], e['data']['access']) for e in started),
                         [('m1', 'codex', 'read'), ('m2', 'claude', 'write')])
        finished = {e['data']['member_id']: e['data'] for e in self.events_of('parent', 'subagent_finished')}
        self.assertEqual(finished['m1']['report_excerpt'], 'Report: Find where dates are parsed.')
        researcher = self.member_task('m1')
        self.assertEqual({k: researcher[k] for k in ('parent_task_id', 'role', 'brief', 'provider', 'access', 'member_id')},
                         {'parent_task_id': 'parent', 'role': 'researcher', 'brief': 'Find where dates are parsed.',
                          'provider': 'codex', 'access': 'read', 'member_id': 'm1'})
        self.assertEqual(researcher['team_id'], proposal['team_id'])
        self.assertEqual(researcher['scope_approval']['team_id'], proposal['team_id'])
        self.assertEqual(researcher['scope_approval']['scope_digest'], self.scope.digest(researcher['scope']))
        self.assertEqual(self.codex.turns, [(researcher['id'], 'Find where dates are parsed.')])
        approvals = [r for r in self.audit.records if r['kind'] == 'scope' and r['rule'] == 'team.approve']
        self.assertEqual(sorted(r['task_id'] for r in approvals), sorted(t['id'] for t in self.children()))
        # Only the write member's workspace is committed before publishing; read runs and the Orchestrator are not.
        self.assertEqual(self.sched.workspaces.committed, ['interspace/task-' + self.member_task('m2')['id'][:8]])

    def test_orchestration_calls_are_tool_cards_with_the_orchestrate_category(self):
        self.make(orchestrating(self.results))
        self.parent()
        self.sched.submit('parent', 'p1', 'Fix it', None)
        self.sched.orchestrator.answer({'task_id': 'parent', 'team_id': self.proposal()['team_id'], 'decision': 'approve'})
        self.wait_state('parent', 'idle')
        calls = self.events_of('parent', 'tool_call')
        self.assertEqual([(c['data']['tool'], c['data']['category']) for c in calls],
                         [('propose_team', 'orchestrate'), ('wait_for', 'orchestrate')])
        results = self.events_of('parent', 'tool_result')
        self.assertEqual([r['data']['status'] for r in results], ['ok', 'ok'])
        self.assertEqual([r['item_id'] for r in results], [c['item_id'] for c in calls])

    def test_declined_team_starts_nothing(self):
        self.make(orchestrating(self.results))
        self.parent()
        self.sched.submit('parent', 'p1', 'Fix it', None)
        team_id = self.proposal()['team_id']
        self.assertEqual(self.sched.orchestrator.answer({'task_id': 'parent', 'team_id': team_id, 'decision': 'decline',
                                                         'note': 'Just answer directly.'}), {'status': 'declined'})
        self.wait_state('parent', 'idle')
        self.assertEqual(self.results, [{'ok': True, 'status': 'declined', 'note': 'Just answer directly.'}])
        self.assertEqual(self.children(), [])
        answered = self.events_of('parent', 'team_answered')[0]['data']
        self.assertEqual((answered['decision'], answered['members'], answered['note']), ('decline', [], 'Just answer directly.'))
        self.assertEqual([r['decision'] for r in self.audit.records if r['kind'] == 'answer'], ['deny'])
        with self.assertRaisesRegex(ValueError, 'no longer open'):
            self.sched.orchestrator.answer({'task_id': 'parent', 'team_id': team_id, 'decision': 'approve'})

    def test_edited_team_is_validated_again_and_returned_as_changed(self):
        self.make(orchestrating(self.results))
        self.parent()
        self.sched.submit('parent', 'p1', 'Fix it', None)
        team_id = self.proposal()['team_id']
        answer = self.sched.orchestrator.answer
        bad = [[{'member_id': 'm9'}], [{'member_id': 'm1', 'role': 'tester'}], [], [{'member_id': 'm1'}, {'member_id': 'm1'}],
               [{'member_id': 'm1', 'provider': 'gemini'}], [{'member_id': 'm1', 'access': 'admin'}],
               [{'member_id': 'm1', 'model': 'not-a-claude-model', 'provider': 'claude'}]]
        for members in bad:
            with self.assertRaises(ValueError, msg=repr(members)):
                answer({'task_id': 'parent', 'team_id': team_id, 'decision': 'approve', 'members': members})
        self.assertEqual(self.children(), [])
        self.assertEqual(self.state('parent'), 'paused_team')
        edited = [{'member_id': 'm2', 'role': 'implementer', 'provider': 'codex', 'brief': 'Fix it carefully.'}]
        self.assertEqual(answer({'task_id': 'parent', 'team_id': team_id, 'decision': 'approve', 'members': edited}),
                         {'status': 'changed'})
        self.wait_state('parent', 'idle')
        changed = self.results[0]
        self.assertEqual(changed['status'], 'changed')
        self.assertEqual([(m['member_id'], m['provider'], m['access']) for m in changed['members']], [('m2', 'codex', 'write')])
        (child,) = self.children()
        self.assertEqual((child['provider'], child['brief'], child['model']), ('codex', 'Fix it carefully.', None))
        self.assertEqual(self.codex.turns, [(child['id'], 'Fix it carefully.')])
        self.assertEqual(self.claude.turns, [])

    def test_invalid_proposals_are_refused_before_the_user_sees_them(self):
        def script(session, text, ctx):
            for arguments in ({'summary': 'x', 'members': []},
                              {'summary': 'x', 'members': [{'role': 'researcher', 'brief': 'b'}] * 13},
                              {'summary': 'x', 'members': [{'role': 'orchestrator', 'brief': 'b'}]},
                              {'summary': '', 'members': [{'role': 'researcher', 'brief': 'b'}]},
                              {'summary': 'x', 'members': [{'role': 'researcher', 'brief': ''}]},
                              {'summary': 'x', 'members': [{'role': 'researcher', 'brief': 'b', 'provider': 'claude'}]},
                              {'summary': 'x', 'members': [{'role': 'researcher', 'brief': 'b', 'provider': 'nope'}],
                               'reason_for_overrides': 'r'}):
                self.results.append(ctx.orchestrate('propose_team', arguments))
            self.results.append(ctx.orchestrate('team_status', {'team_id': 'missing'}))
            return default_script(session, text, ctx)
        self.make(script)
        self.parent()
        self.sched.submit('parent', 'p1', 'x', None)
        self.wait_state('parent', 'idle')
        self.assertEqual(len(self.results), 8)
        self.assertTrue(all(r['ok'] is False and r['error']['code'] == 'invalid_request' for r in self.results))
        self.assertIn('reason_for_overrides', self.results[5]['error']['message'])
        self.assertEqual(self.events_of('parent', 'team_proposed'), [])
        self.assertNotIn('paused_team', [e['data']['state'] for e in self.events_of('parent', 'status')])

    def test_override_with_reason_is_shown_as_not_default(self):
        team = {'summary': 'Review', 'reason_for_overrides': 'Claude knows this codebase.',
                'members': [{'role': 'reviewer', 'brief': 'Review.', 'provider': 'claude'},
                            {'role': 'writer', 'brief': 'Write.', 'access': 'write'}]}
        self.make(orchestrating(self.results, team=team, wait=False))
        self.parent()
        self.sched.submit('parent', 'p1', 'x', None)
        members = self.proposal()['members']
        self.assertEqual([(m['provider'], m['access'], m['default'], m.get('reason')) for m in members],
                         [('claude', 'read', False, 'Claude knows this codebase.'), ('claude', 'write', True, None)])
        self.sched.orchestrator.answer({'task_id': 'parent', 'team_id': self.proposal()['team_id'], 'decision': 'decline'})
        self.wait_state('parent', 'idle')


class DefaultsTests(unittest.TestCase):
    def table(self, **extra):
        table = orchestrator.registry()
        providers = dict(table['providers'])
        providers.update(extra)
        check = table['check_model']
        return dict(table, providers=providers,
                    check_model=lambda name, model: model if name in extra else check(name, model))

    def test_routing_defaults_and_access_defaults(self):
        table = orchestrator.registry()
        routing = orchestrator.routing_defaults({}, table)
        self.assertEqual(routing, orchestrator.DEFAULT_ROUTING)
        _, members = orchestrator.normalize_team(
            {'summary': 's', 'members': [{'role': r, 'brief': 'b'} for r in tasks.TEAM_ROLES]}, routing, table)
        self.assertEqual([(m['role'], m['provider'], m['access']) for m in members],
                         [('researcher', 'codex', 'read'), ('implementer', 'claude', 'write'),
                          ('reviewer', 'codex', 'read'), ('tester', 'claude', 'write'), ('writer', 'claude', 'read')])

    def test_user_routing_is_used_and_invalid_routing_falls_back(self):
        table = orchestrator.registry()
        custom = json.loads(json.dumps(orchestrator.DEFAULT_ROUTING))
        custom['roles']['researcher'] = {'provider': 'claude', 'model': 'claude-haiku-5-5'}
        routing = orchestrator.routing_defaults({'routing': custom}, table)
        _, (member,) = orchestrator.normalize_team({'summary': 's', 'members': [{'role': 'researcher', 'brief': 'b'}]},
                                                   routing, table)
        self.assertEqual((member['provider'], member['model'], member['default']), ('claude', 'claude-haiku-5-5', True))
        custom['roles']['researcher'] = {'provider': 'nope', 'model': None}
        self.assertEqual(orchestrator.routing_defaults({'routing': custom}, table), orchestrator.DEFAULT_ROUTING)

    def test_write_on_a_provider_without_write_is_refused(self):
        reader = {'name': 'reader', 'title': 'Reader', 'models': (), 'default_model': None,
                  'capabilities': {'write': False, 'web_search': True, 'approvals': False}}
        table = self.table(reader=reader)
        routing = orchestrator.DEFAULT_ROUTING
        for member in ({'role': 'implementer', 'brief': 'b', 'provider': 'reader'},
                       {'role': 'reviewer', 'brief': 'b', 'provider': 'reader', 'access': 'write'}):
            with self.assertRaisesRegex(ValueError, 'cannot write'):
                orchestrator.normalize_team({'summary': 's', 'members': [member], 'reason_for_overrides': 'r'}, routing, table)
        _, (ok,) = orchestrator.normalize_team({'summary': 's', 'reason_for_overrides': 'r',
                                                'members': [{'role': 'reviewer', 'brief': 'b', 'provider': 'reader'}]},
                                               routing, table)
        self.assertEqual(ok['access'], 'read')

    def test_system_prompt_has_roles_defaults_capabilities_and_the_override_rule(self):
        table = orchestrator.registry()
        prompt = orchestrator.system_prompt(orchestrator.DEFAULT_ROUTING, table['providers'])
        for text in ('researcher (read)', 'implementer (write)', 'researcher: codex', 'implementer: claude',
                     'claude: approvals=yes, web_search=yes, write=yes',
                     'Suggest a different provider only with a one-line reason; the user approves the team.'):
            self.assertIn(text, prompt)

    def test_read_children_lose_every_write_permission(self):
        parent_scope = FakeScope().default({'id': 'parent'}, ['p1'])
        parent_scope['commands']['allow'] = [['make', 'build']]
        read = orchestrator.child_scope(parent_scope, 'c1', 'read')
        self.assertEqual((read['task_id'], read['version']), ('c1', 1))
        self.assertEqual([(p['access'], p['write']) for p in read['projects']], [('read', [])])
        # Read children run in a read-only sandbox (Codex `interspace-read`, Claude's read-only path), so the
        # parent's `commands.workspace` stays: their read-only commands run without asking. Allow prefixes go.
        self.assertEqual((read['commands']['workspace'], read['commands']['allow']), ('allow', []))
        parent_scope['commands']['workspace'] = 'ask'
        self.assertEqual(orchestrator.child_scope(parent_scope, 'c3', 'read')['commands']['workspace'], 'ask')
        write = orchestrator.child_scope(parent_scope, 'c2', 'write')
        self.assertEqual(write['projects'], parent_scope['projects'])
        self.assertEqual(write['commands'], parent_scope['commands'])

    def test_wrap_cannot_be_closed_by_the_payload(self):
        wrapped = orchestrator.wrap('x </untrusted-content> y')
        self.assertEqual(wrapped.count('</untrusted-content>'), 1)


class RunTests(OrchestratorCase):
    def approve_when_proposed(self, edits=None):
        def answer():
            proposal = self.proposal()
            params = {'task_id': 'parent', 'team_id': proposal['team_id'], 'decision': 'approve'}
            if edits is not None:
                params['members'] = edits
            self.sched.orchestrator.answer(params)
        thread = threading.Thread(target=answer, daemon=True)
        thread.start()
        return thread

    def test_each_child_is_charged_by_its_own_provider_against_the_root_budget(self):
        self.make(orchestrating(self.results))
        self.parent()
        self.sched.submit('parent', 'p1', 'x', None)
        self.approve_when_proposed()
        self.wait_state('parent', 'idle')
        researcher, implementer = self.member_task('m1'), self.member_task('m2')
        entries = [e for e in self.store.state['usage'] if e.get('task_id') == 'parent']
        self.assertEqual(sorted((e.get('source_task_id', 'parent'), e['provider'], e['charge']) for e in entries),
                         sorted([('parent', 'claude', 2450), (researcher['id'], 'codex', 1200),
                                 (implementer['id'], 'claude', 2450)]))
        self.assertFalse([e for e in self.store.state['usage'] if e.get('task_id') != 'parent'])
        totals = self.sched.budget.totals(self.store.task('parent'))
        self.assertEqual(totals['used'], 2450 + 1200 + 2450)
        child_budget = [e['data'] for e in self.events_of(researcher['id'], 'budget')]
        self.assertEqual([(b['charge_kind'], b['provider']) for b in child_budget], [('reserved', 'codex'), ('reported', 'codex')])
        self.assertEqual(child_budget[-1]['budget'], 250000)
        statuses = [e['data'] for e in self.events_of('parent', 'subagent_status') if e['data']['task_id'] == researcher['id']]
        self.assertEqual(statuses[-1]['tokens_used'], 1200)

    def test_a_sibling_continues_when_one_child_runs_out_of_budget(self):
        gate = threading.Event()
        team = {'summary': 's', 'members': [{'role': 'researcher', 'brief': 'one'}, {'role': 'reviewer', 'brief': 'two'},
                                            {'role': 'writer', 'brief': 'three', 'provider': 'codex'}],
                'reason_for_overrides': 'Codex writes short notes.'}
        # Parent reserves 30,000 + its message; two children of 30,000 fit in 95,000, the third does not.
        self.make(orchestrating(self.results, team=team), codex=child_script(CODEX_USAGE, gate=gate))
        self.parent(token_budget=95000)
        self.sched.submit('parent', 'p1', 'x', None)
        self.approve_when_proposed()
        wait_for(lambda: len(self.children()) == 3 and sum(self.state(t['id']) == 'budget_exhausted'
                                                            for t in self.children()) == 1, message='one exhausted')
        gate.set()
        self.wait_state('parent', 'idle')
        states = sorted(self.state(t['id']) for t in self.children())
        self.assertEqual(states, ['budget_exhausted', 'idle', 'idle'])
        waited = self.results[1]
        self.assertEqual(sorted(m['state'] for m in waited['members']), ['budget_exhausted', 'idle', 'idle'])

    def test_children_run_while_the_parent_waits_even_with_one_slot(self):
        self.make(orchestrating(self.results), max_running=1)
        self.parent()
        self.sched.submit('parent', 'p1', 'x', None)
        self.approve_when_proposed()
        self.wait_state('parent', 'idle')
        self.assertFalse(self.results[1]['timed_out'])
        self.assertEqual(sorted(self.state(t['id']) for t in self.children()), ['idle', 'idle'])

    def test_a_resuming_parent_waits_for_a_free_slot_ahead_of_the_queue(self):
        gate = threading.Event()
        seen = []
        order = []

        def watch(ctx, label):
            seen.append(self.sched._running_count())
            order.append(label)

        def parent_script(session, text, ctx):
            proposed = ctx.orchestrate('propose_team', TEAM)
            watch(ctx, 'parent resumed')
            waited = ctx.orchestrate('wait_for', {'team_id': proposed['team_id'], 'timeout_s': 10})
            watch(ctx, 'parent resumed')
            self.results.append(waited)
            ctx.emit('message', {'role': 'assistant', 'text': 'Summary.', 'final': True}, item_id='m1')
            return {'status': 'completed', 'usage': dict(CLAUDE_USAGE), 'error': None}

        def child(usage):
            def script(session, text, ctx):
                watch(ctx, 'child ' + ctx.role)
                gate.wait(5)
                return child_script(usage)(session, text, ctx)
            return script
        self.make(parent_script, codex=child(CODEX_USAGE), claude=child(CLAUDE_USAGE), max_running=1)
        self.parent()
        self.sched.submit('parent', 'p1', 'x', None)
        self.approve_when_proposed()
        wait_for(lambda: order, message='first child running')
        time.sleep(0.2)  # The parent has had time to resume if it (wrongly) took a slot.
        self.assertEqual(order, ['child researcher'])
        gate.set()
        self.wait_state('parent', 'idle')
        # The parent resumed before the queued implementer started, and never shared the single slot.
        self.assertEqual(order, ['child researcher', 'parent resumed', 'child implementer', 'parent resumed'])
        self.assertEqual(seen, [1, 1, 1, 1])
        self.assertFalse(self.results[0]['timed_out'])

    def test_read_members_are_refused_writes_and_escalation_without_asking(self):
        decisions = {}

        def researcher(session, text, ctx):
            for name, request in (
                    ('write', {'category': 'file_write', 'project_id': 'p1', 'paths': ['a.py']}),
                    ('escalated', {'category': 'command', 'argv': ['make'], 'command': None, 'cwd': '.',
                                   'sandbox': 'escalated', 'network': False, 'project_id': 'p1'}),
                    ('read', {'category': 'file_read', 'project_id': 'p1', 'paths': ['a.py']}),
                    ('command', {'category': 'command', 'argv': ['ls'], 'command': None, 'cwd': '.',
                                 'sandbox': 'workspace', 'network': False, 'project_id': 'p1'})):
                decisions[name] = ctx.authorize(request, 'call_' + name)
            return child_script(CODEX_USAGE)(session, text, ctx)
        self.make(orchestrating(self.results), codex=researcher)
        self.parent()
        self.sched.submit('parent', 'p1', 'x', None)
        self.approve_when_proposed()
        self.wait_state('parent', 'idle')
        self.assertEqual({k: (v['decision'], v['rule']) for k, v in decisions.items()},
                         {'write': ('deny', 'access.read'), 'escalated': ('deny', 'access.read'),
                          'read': ('allow', decisions['read']['rule']), 'command': ('allow', decisions['command']['rule'])})
        self.assertEqual(self.events_of(self.member_task('m1')['id'], 'ask'), [])
        audited = [r for r in self.audit.records if r['kind'] == 'decision' and r['rule'] == 'access.read']
        self.assertEqual(sorted(r['call_id'] for r in audited), ['call_escalated', 'call_write'])

    def test_snapshot_groups_children_under_their_task(self):
        gate = threading.Event()
        self.make(orchestrating(self.results), codex=child_script(CODEX_USAGE, gate=gate),
                  claude=child_script(CLAUDE_USAGE, gate=gate), max_running=2)
        self.parent()
        self.sched.submit('parent', 'p1', 'x', None)
        self.approve_when_proposed()
        wait_for(lambda: len(self.sched.snapshot()['running']) == 3, message='three running')
        running = {r['task_id']: r for r in self.sched.snapshot()['running']}
        self.assertEqual((running['parent']['parent_task_id'], running['parent']['role'], running['parent']['provider']),
                         (None, 'orchestrator', 'claude'))
        researcher = self.member_task('m1')
        self.assertEqual((running[researcher['id']]['parent_task_id'], running[researcher['id']]['role'],
                          running[researcher['id']]['provider']), ('parent', 'researcher', 'codex'))
        gate.set()
        self.wait_state('parent', 'idle')

    def test_orchestrator_sessions_get_tools_and_read_access_children_do_not(self):
        seen = {}

        def child(session, text, ctx):
            seen[ctx.task_id] = (ctx.tools(), ctx.access, ctx.role, ctx.instructions)
            with self.assertRaisesRegex(ValueError, 'Unknown tool'):
                ctx.orchestrate('team_status', {'team_id': 'x'})
            return default_script(session, text, ctx)

        def parent(session, text, ctx):
            seen['parent'] = ([t['name'] for t in ctx.tools()], ctx.access, ctx.role, ctx.instructions)
            return orchestrating(self.results)(session, text, ctx)
        self.make(parent, codex=child, claude=child)
        self.parent()
        self.sched.submit('parent', 'p1', 'x', None)
        self.approve_when_proposed()
        self.wait_state('parent', 'idle')
        names, access, role, instructions = seen['parent']
        self.assertEqual((names, access, role), (['propose_team', 'team_status', 'wait_for', 'message_member'], 'read',
                                                 'orchestrator'))
        self.assertIn(orchestrator.OVERRIDE_RULE, instructions)
        self.assertEqual(seen[self.member_task('m1')['id']], ([], 'read', 'researcher', None))
        self.assertEqual(seen[self.member_task('m2')['id']], ([], 'write', 'implementer', None))

    def test_message_member_and_team_status(self):
        def then(ctx, proposed):
            team_id = proposed['team_id']
            self.results.append(ctx.orchestrate('message_member', {'team_id': team_id, 'member_id': 'm1', 'text': 'More detail.'}))
            self.results.append(ctx.orchestrate('wait_for', {'team_id': team_id, 'member_ids': ['m1'], 'timeout_s': 10}))
            self.results.append(ctx.orchestrate('team_status', {'team_id': team_id}))
            self.results.append(ctx.orchestrate('message_member', {'team_id': team_id, 'member_id': 'm7', 'text': 'x'}))
            self.results.append(ctx.orchestrate('wait_for', {'team_id': team_id, 'timeout_s': 0}))
        self.make(orchestrating(self.results, then=then))
        self.parent()
        self.sched.submit('parent', 'p1', 'x', None)
        self.approve_when_proposed()
        self.wait_state('parent', 'idle')
        _, _, messaged, waited, status, unknown, bad_wait = self.results
        self.assertEqual(messaged, {'ok': True, 'state': 'starting'})
        researcher = self.member_task('m1')
        self.assertEqual(self.codex.turns[-1], (researcher['id'], 'More detail.'))
        self.assertIn('Report: More detail.', waited['members'][0]['report'])
        self.assertEqual([(m['member_id'], m['state'], m['tokens_used']) for m in status['members']],
                         [('m1', 'idle', 2400), ('m2', 'idle', 2450)])
        self.assertEqual((unknown['ok'], bad_wait['ok']), (False, False))


class CancelAndRestartTests(OrchestratorCase):
    def test_cancelling_the_parent_cancels_running_and_queued_children(self):
        def stuck(session, text, ctx):
            if not session.interrupted.wait(10):
                raise AssertionError('child was never stopped')
            return {'status': 'cancelled', 'usage': None, 'error': None}
        team = {'summary': 's', 'members': [{'role': 'researcher', 'brief': 'a'}, {'role': 'reviewer', 'brief': 'b'},
                                            {'role': 'implementer', 'brief': 'c'}]}
        self.make(orchestrating(self.results, team=team), codex=stuck, claude=stuck, max_running=2)
        self.parent()
        self.sched.submit('parent', 'p1', 'x', None)
        self.sched.orchestrator.answer({'task_id': 'parent', 'team_id': self.proposal()['team_id'], 'decision': 'approve'})
        wait_for(lambda: len(self.children()) == 3 and any(self.state(t['id']) == 'queued' for t in self.children()),
                 message='a queued child')
        self.assertTrue(self.sched.cancel('parent'))
        self.wait_state('parent', 'cancelled')
        for child in self.children():
            self.wait_state(child['id'], 'cancelled')
        self.assertEqual(self.results[1]['error']['code'], 'cancelled')

    def test_cancelling_during_approval_starts_no_child(self):
        self.make(orchestrating(self.results))
        self.parent()
        self.sched.submit('parent', 'p1', 'x', None)
        team_id = self.proposal()['team_id']
        self.wait_state('parent', 'paused_team')
        self.sched.cancel('parent')
        self.wait_state('parent', 'cancelled')
        self.assertEqual(self.children(), [])
        self.assertEqual(self.store.task('parent')['agent']['teams'][team_id]['status'], 'cancelled')
        with self.assertRaisesRegex(ValueError, 'no longer open'):
            self.sched.orchestrator.answer({'task_id': 'parent', 'team_id': team_id, 'decision': 'approve'})

    def test_restart_interrupts_an_open_proposal(self):
        self.make(orchestrating(self.results))
        self.parent()
        self.sched.submit('parent', 'p1', 'x', None)
        team_id = self.proposal()['team_id']
        self.wait_state('parent', 'paused_team')
        # Simulate the app quitting mid-proposal: the saved state is reloaded by a fresh backend.
        saved = json.loads(json.dumps(self.store.state))
        store = MemoryStore(self.scope)
        store.state = saved
        changed = scheduler.recover(store, scheduler.EventLog(self.root / 'tasks2', forward=lambda e: None))
        self.assertEqual(changed, ['parent'])
        parent = store.task('parent')
        self.assertEqual((parent['agent']['state'], parent['agent']['teams'][team_id]['status']),
                         ('interrupted', 'interrupted'))
        self.assertFalse([t for t in store.agent_tasks() if t.get('parent_task_id')])


class MethodTests(unittest.TestCase):
    def test_team_answer_is_registered_for_the_service(self):
        import service
        self.assertIs(service.extension_methods(['orchestrator'])['team_answer'], orchestrator.team_answer)

        class App:
            class scheduler:
                class orchestrator:
                    @staticmethod
                    def answer(params):
                        return {'status': 'declined', 'seen': params}
        self.assertEqual(orchestrator.team_answer(App, {'x': 1}), {'status': 'declined', 'seen': {'x': 1}})


if __name__ == '__main__':
    unittest.main()
