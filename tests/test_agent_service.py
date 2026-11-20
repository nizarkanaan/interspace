"""Service wiring for agentic tasks: stdin routing, agent and scope methods, sign-in beside agent tasks, and the
agent-mode task and budget changes. Fakes only: no provider, no network, no Keychain."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
sys.path.insert(0, str(ROOT / 'tests'))

import service  # Puts pilot/ on the path for projects.
import budget
import projects
import scheduler
import tasks
import routing
from agent_fakes import FakeAudit, FakeRuntime, FakeScope, wait_for, wait_interrupt

class Output:
    def __init__(self):
        self.messages = []
        self.lock = threading.Lock()

    def __call__(self, message):
        json.dumps(message)  # Everything emitted must be a JSON line.
        with self.lock:
            self.messages.append(message)

    def of_type(self, kind):
        with self.lock:
            return [m for m in self.messages if m.get('type') == kind]

    def reply(self, identity):
        with self.lock:
            return next((m for m in self.messages if m.get('id') == identity and 'type' not in m), None)


class StubApp:
    def __init__(self, emit):
        self.calls = []
        self.block = threading.Event()
        self.block.set()

    def handle(self, method, params):
        self.calls.append(method)
        if method == 'slow':
            self.block.wait(5)
        if method == 'boom':
            raise RuntimeError('internal detail')
        return {'method': method}


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.out = Output()
        self.app = StubApp(self.out)
        self.router = service.Router(self.app, self.out)
        self.addCleanup(self.router.close, 5)

    def test_legacy_requests_keep_order_and_errors(self):
        for index, method in enumerate(['a', 'b', 'boom', 'c']):
            self.assertEqual(self.router.route(json.dumps({'id': index, 'method': method})), 'legacy')
        self.router.route('not json\n')
        self.router.route('[1]\n')
        wait_for(lambda: len(self.out.messages) == 6)
        self.assertEqual(self.app.calls, ['a', 'b', 'boom', 'c'])
        self.assertEqual([m.get('id') for m in self.out.messages], [0, 1, 2, 3, None, None])
        self.assertEqual(self.out.messages[2]['error'], 'Request failed. Check the project folder and try again.')
        self.assertEqual(self.out.messages[5]['error'], 'Request must be an object')

    def test_agent_requests_do_not_wait_behind_legacy(self):
        self.app.block.clear()
        self.router.route(json.dumps({'id': 'slow', 'method': 'slow'}))
        wait_for(lambda: 'slow' in self.app.calls)
        self.assertEqual(self.router.route(json.dumps({'id': 'e', 'method': 'task_events'})), 'agent')
        self.assertEqual(self.router.route(json.dumps({'id': 'm', 'method': 'agent_message'})), 'agent')
        wait_for(lambda: all(self.out.reply(i) for i in ('e', 'm')))
        self.assertIsNone(self.out.reply('slow'))
        self.app.block.set()
        wait_for(lambda: self.out.reply('slow') is not None)

    def test_former_bridge_lines_are_ordinary_requests(self):
        for line in ({'keychain_reply': 'kc-1', 'ok': True}, {'bridge_hello': {'keychain': 1}}):
            self.assertEqual(self.router.route(json.dumps(line)), 'legacy')
        wait_for(lambda: len(self.app.calls) == 2)
        self.assertEqual(self.app.calls, [None, None])

    def test_serve_reads_until_end_of_input(self):
        closed = threading.Event()
        lines = [json.dumps({'id': 1, 'method': 'a'}) + '\n', json.dumps({'id': 2, 'method': 'b'}) + '\n']
        self.router.serve(iter(lines), closed)
        wait_for(lambda: self.out.reply(2) is not None)
        self.assertEqual(self.app.calls, ['a', 'b'])


class FakeProvider:
    def status(self):
        return {'ready': True, 'message': 'fake'}

    def sign_in(self, cancel, emit):
        cancel.wait(5)


class ApplicationCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        git = ['git', '-c', 'user.name=T', '-c', 'user.email=t@example.invalid']
        subprocess.run(git + ['init', '-q', '-b', 'main', str(self.repo)], check=True)
        (self.repo / 'main.py').write_text('print(1)\n')
        subprocess.run(git + ['-C', str(self.repo), 'add', '.'], check=True)
        subprocess.run(git + ['-C', str(self.repo), 'commit', '-qm', 'base'], check=True)
        self.scope = FakeScope()
        self.audit = FakeAudit()
        self.runtime = FakeRuntime()

    def open(self, data=None):
        self.out = Output()
        app = service.Application(data or self.root / 'data', provider=FakeProvider(), emit=self.out,
                                  scope_api=self.scope, audit_api=self.audit, runtime_factory=lambda task_id: self.runtime,
                                  interrupt_grace_s=0.2)
        self.addCleanup(app.scheduler.shutdown, 5)
        return app

    def add_project(self, app):
        project = projects.new_project(self.repo)
        with app.lock:
            app.state['projects'][project['id']] = project
            app.state['selected_project_id'] = project['id']
        return project['id']

    def create(self, app, project_id, approve=True):
        created = app.handle('agent_create', {'project_id': project_id, 'title': 'Fix it', 'scope': None})
        if approve:
            scope = app.handle('scope_get', {'task_id': created['task_id']})
            app.handle('scope_approve', {'task_id': created['task_id'], 'scope_version': scope['scope']['version'],
                                         'scope_digest': scope['scope_digest']})
        return created['task_id']

    def agent_state(self, app, task_id):
        with app.lock:
            return app.store.task(task_id)['agent']['state']


class AgentMethodTests(ApplicationCase):
    def test_create_approve_message_and_replay(self):
        app = self.open()
        project_id = self.add_project(app)
        created = app.handle('agent_create', {'project_id': project_id, 'title': 'Fix it', 'scope': None})
        task_id = created['task_id']
        scope = app.handle('scope_get', {'task_id': task_id})
        self.assertEqual(scope['scope_digest'], created['scope_digest'])
        self.assertIsNone(scope['scope_approval'])
        self.assertEqual((scope['scope']['task_id'], scope['scope']['version']), (task_id, 1))
        with self.assertRaisesRegex(ValueError, 'Approve'):
            app.handle('agent_message', {'task_id': task_id, 'text': 'go', 'client_id': 'c1'})
        with self.assertRaisesRegex(ValueError, 'changed'):
            app.handle('scope_approve', {'task_id': task_id, 'scope_version': 1, 'scope_digest': 'sha256:other'})
        app.handle('scope_approve', {'task_id': task_id, 'scope_version': 1, 'scope_digest': created['scope_digest']})
        self.assertEqual(app.handle('agent_message', {'task_id': task_id, 'text': 'go', 'client_id': 'c1'}),
                         {'state': 'starting', 'position': None})
        wait_for(lambda: self.agent_state(app, task_id) == 'idle')
        streamed = [m['event'] for m in self.out.of_type('event') if m['event']['task_id'] == task_id]
        self.assertEqual([e['seq'] for e in streamed], list(range(1, len(streamed) + 1)))
        replay = app.handle('task_events', {'task_id': task_id, 'after_seq': 0})
        self.assertEqual(replay['events'], streamed)
        self.assertTrue(replay['complete'])
        diff = [e for e in streamed if e['kind'] == 'diff'][0]['data']
        branch = diff['workspace']['branch']
        self.assertEqual(branch, 'interspace/task-' + task_id[:8])
        self.assertEqual(subprocess.run(['git', '-C', str(self.repo), 'rev-parse', '--abbrev-ref', 'HEAD'],
                                        capture_output=True, text=True).stdout.strip(), 'main')
        self.assertEqual(subprocess.run(['git', '-C', str(self.repo), 'show-ref', '--verify', '--quiet', 'refs/heads/' + branch]).returncode, 0)
        public = app.handle('state', {})
        self.assertEqual(public['scheduler']['max_running'], 4)
        self.assertEqual(public['task']['agent']['state'], 'idle')
        self.assertTrue(public['task']['agent']['scope_approved'])
        self.assertEqual([t['status'] for t in public['tasks'] if t['id'] == task_id], ['idle'])
        kinds = [r['kind'] for r in self.audit.records]
        self.assertEqual(kinds[:2], ['scope', 'scope'])
        self.assertEqual(self.scope.validated_with[0], [project_id])
        with self.assertRaisesRegex(ValueError, 'not registered'):
            app.handle('agent_create', {'project_id': project_id, 'title': 'X',
                                        'scope': dict(scope['scope'], projects=[{'project_id': 'ghost'}])})

    def test_scope_update_invalidates_approval_and_checks_base_version(self):
        app = self.open()
        task_id = self.create(app, self.add_project(app))
        scope = app.handle('scope_get', {'task_id': task_id})['scope']
        with self.assertRaisesRegex(ValueError, 'changed'):
            app.handle('scope_update', {'task_id': task_id, 'base_version': 0, 'scope': scope})
        edited = dict(scope, web_search='allow', limits={'token_budget': 90000, 'time_limit_s': 600})
        updated = app.handle('scope_update', {'task_id': task_id, 'base_version': 1, 'scope': edited})
        self.assertEqual(updated['scope']['version'], 2)
        current = app.handle('scope_get', {'task_id': task_id})
        self.assertIsNone(current['scope_approval'])
        with app.lock:
            self.assertEqual(app.store.task(task_id)['token_budget'], 90000)
        changes = [m['event']['data']['change'] for m in self.out.of_type('event') if m['event']['kind'] == 'scope']
        self.assertEqual(changes, ['edited', 'approved', 'edited'])
        with self.assertRaisesRegex(ValueError, 'Approve'):
            app.handle('agent_message', {'task_id': task_id, 'text': 'go', 'client_id': None})

    def test_scope_changes_fail_closed_when_audit_fails(self):
        app = self.open()
        project_id = self.add_project(app)
        self.audit.fail = True
        with self.assertRaisesRegex(ValueError, 'audit'):
            app.handle('agent_create', {'project_id': project_id, 'title': 'X', 'scope': None})
        self.assertEqual([t for t in app.state['projects'][project_id]['tasks']], [])

    def test_legacy_cancel_leaves_agent_tasks_alone_and_agent_cancel_stops_one(self):
        self.runtime.script = wait_interrupt(honor=True)
        app = self.open()
        task_id = self.create(app, self.add_project(app))
        app.handle('agent_message', {'task_id': task_id, 'text': 'go', 'client_id': None})
        wait_for(lambda: self.agent_state(app, task_id) == 'running')
        self.assertEqual(app.handle('cancel', {}), {'cancellation_requested': False})
        time.sleep(0.05)
        self.assertEqual(self.agent_state(app, task_id), 'running')
        self.assertEqual(app.handle('agent_cancel', {'task_id': task_id}), {'cancellation_requested': True})
        wait_for(lambda: self.agent_state(app, task_id) == 'cancelled')
        self.assertEqual(app.handle('agent_cancel', {'task_id': task_id}), {'cancellation_requested': False})

    def test_old_task_flows_are_gone(self):
        app = self.open()
        task_id = self.create(app, self.add_project(app))
        for method in ('chat', 'start_review', 'start_plan', 'start_change', 'update_task', 'create_task'):
            with self.assertRaisesRegex(ValueError, 'Unknown method'):
                app.handle(method, {'project_id': app.state['selected_project_id'], 'task_id': task_id, 'text': 'x'})

    def test_sign_in_runs_beside_agent_tasks_without_taking_a_slot(self):
        self.runtime.script = wait_interrupt(honor=True)
        app = self.open()
        project_id = self.add_project(app)
        app.handle('scheduler_settings', {'max_running': 1})
        self.assertEqual(app.state['scheduler_settings'], {'max_running': 1})
        busy = self.create(app, project_id)
        app.handle('agent_message', {'task_id': busy, 'text': 'go', 'client_id': None})
        wait_for(lambda: self.agent_state(app, busy) == 'running')
        app.handle('sign_in', {})  # The fake sign-in waits for cancel.
        self.assertEqual(app.state['active'], 'Signing in')
        self.assertNotIn('legacy_active', app.handle('state', {})['scheduler'])
        app.handle('cancel', {})
        app.wait()
        self.assertIsNone(app.state['active'])
        self.assertEqual(self.agent_state(app, busy), 'running')  # Stop ends the sign-in only.
        app.handle('agent_cancel', {'task_id': busy})
        wait_for(lambda: self.agent_state(app, busy) == 'cancelled')

    def test_restart_interrupts_unfinished_agent_task(self):
        self.runtime.script = wait_interrupt(honor=True)
        data = self.root / 'data'
        app = self.open(data)
        task_id = self.create(app, self.add_project(app))
        app.handle('agent_message', {'task_id': task_id, 'text': 'go', 'client_id': None})
        wait_for(lambda: self.agent_state(app, task_id) == 'running')
        app.persist()
        saved = json.loads((data / 'state.json').read_text())
        app.scheduler._stop_watch.set()  # Simulate a crash: the old process just disappears.
        before = app.events.last_seq(task_id)
        reopened = self.open_again(data, saved)
        self.assertEqual(self.agent_state(reopened, task_id), 'interrupted')
        events = reopened.handle('task_events', {'task_id': task_id, 'after_seq': before})['events']
        self.assertEqual([(e['seq'], e['kind'], e['data']['state']) for e in events], [(before + 1, 'status', 'interrupted')])
        usage = [e for e in reopened.state['usage'] if e.get('task_id') == task_id]
        self.assertEqual([e['charge_kind'] for e in usage], ['estimated'], 'an open reservation is charged its estimate')
        app.handle('agent_cancel', {'task_id': task_id})

    def open_again(self, data, saved):
        copy_root = self.root / 'data2'
        copy_root.mkdir()
        (copy_root / 'state.json').write_text(json.dumps(saved))
        import shutil
        shutil.copytree(str(data / 'tasks'), str(copy_root / 'tasks'))
        return self.open(copy_root)

    def test_events_and_blob_methods_validate_task(self):
        app = self.open()
        with self.assertRaisesRegex(ValueError, 'Unknown task'):
            app.handle('task_events', {'task_id': 'nope', 'after_seq': 0})
        task_id = self.create(app, self.add_project(app))
        with self.assertRaises(ValueError):
            app.handle('task_blob', {'task_id': task_id, 'blob_id': '../../state.json'})
        with self.assertRaises(ValueError):
            app.handle('scheduler_settings', {'max_running': 99})


class DecideOptionTests(ApplicationCase):
    def test_application_passes_its_data_directory_as_app_data(self):
        def script(session, text, ctx):
            ctx.authorize({'category': 'command', 'argv': ['ls'], 'command': None, 'cwd': '.', 'sandbox': 'workspace',
                           'network': False}, 'c1')
            return {'status': 'completed', 'usage': None, 'error': None}
        self.runtime.script = script
        app = self.open()
        task_id = self.create(app, self.add_project(app))
        app.handle('agent_message', {'task_id': task_id, 'text': 'go', 'client_id': None})
        wait_for(lambda: self.agent_state(app, task_id) == 'idle')
        self.assertEqual(self.scope.decide_options[0]['app_data'], str(app.storage))


class AgentModeTests(unittest.TestCase):
    def test_agent_task_shape(self):
        with self.assertRaisesRegex(ValueError, 'project'):
            tasks.create('A', project_id=None)
        task = tasks.create('A', project_id='p1')
        self.assertEqual(task['mode'], 'agent')
        self.assertEqual(task['agent']['state'], None)
        self.assertIs(tasks.validate(task, task['id']), task)
        task['agent']['state'] = 'flying'
        with self.assertRaises(ValueError):
            tasks.validate(task, task['id'])
        with self.assertRaisesRegex(ValueError, 'mode'):
            tasks.validate_mode('chaos')
        legacy = tasks.imported('B')
        self.assertNotIn('agent', legacy)
        self.assertIs(tasks.validate(legacy, legacy['id']), legacy)  # Earlier modes still load.


class RuntimeWiringTests(ApplicationCase):
    """Without an injected factory the service asks 2A's `runtime.make_factory(app)`, else fails closed."""

    def open_default(self, module):
        saved = sys.modules.get('runtime', 'missing')
        sys.modules['runtime'] = module  # None makes `import runtime` raise ImportError.

        def restore():
            if saved == 'missing':
                sys.modules.pop('runtime', None)
            else:
                sys.modules['runtime'] = saved
        self.addCleanup(restore)
        self.out = Output()
        app = service.Application(self.root / 'data', provider=FakeProvider(), emit=self.out, scope_api=self.scope,
                                  audit_api=self.audit, interrupt_grace_s=0.2)
        self.addCleanup(app.scheduler.shutdown, 5)
        return app

    def test_runtime_module_factory_is_used(self):
        module = types.ModuleType('runtime')
        made = []

        def make_factory(app):
            made.append(app)
            return lambda task_id: self.runtime
        module.make_factory = make_factory
        app = self.open_default(module)
        self.assertEqual(made, [app])
        project_id = self.add_project(app)
        task_id = self.create(app, project_id)
        app.handle('agent_message', {'task_id': task_id, 'text': 'go', 'client_id': 'c1'})
        wait_for(lambda: self.agent_state(app, task_id) == 'idle')
        self.assertEqual(self.runtime.turns, [(task_id, 'go')])

    def test_missing_module_falls_back_to_no_runtime(self):
        for module in (None, types.ModuleType('runtime')):  # Absent, or present without make_factory.
            app = self.open_default(module)
            project_id = self.add_project(app)
            task_id = self.create(app, project_id)
            app.handle('agent_message', {'task_id': task_id, 'text': 'go', 'client_id': 'c1'})
            wait_for(lambda: self.agent_state(app, task_id) == 'failed')
            errors = [m['event']['data'] for m in self.out.of_type('event')
                      if m['event']['task_id'] == task_id and m['event']['kind'] == 'error']
            self.assertEqual([e['code'] for e in errors], ['runtime_unavailable'])
            app.scheduler.shutdown(5)

    def test_broken_factory_builder_fails_closed(self):
        module = types.ModuleType('runtime')

        def make_factory(app):
            raise RuntimeError('codex binary missing')
        module.make_factory = make_factory
        app = self.open_default(module)
        project_id = self.add_project(app)
        task_id = self.create(app, project_id)
        app.handle('agent_message', {'task_id': task_id, 'text': 'go', 'client_id': 'c1'})
        wait_for(lambda: self.agent_state(app, task_id) == 'failed')


class ApplyAnswerAdapterTests(unittest.TestCase):
    def test_delegates_to_scope_apply_answer(self):
        module = types.SimpleNamespace(apply_answer=mock.Mock(return_value={'run': True}))
        adapter = service.ScopeAdapter(module)
        self.assertEqual(adapter.apply_answer({'v': 1}, None, {'ask_id': 'a'}, {'decision': 'deny'}, now=5.0), {'run': True})
        module.apply_answer.assert_called_once_with({'v': 1}, None, {'ask_id': 'a'}, {'decision': 'deny'}, now=5.0)
        with self.assertRaisesRegex(ValueError, 'scope engine'):
            service.ScopeAdapter(None).apply_answer({}, None, {}, {}, now=0)


class AgentProviderTests(ApplicationCase):
    """The runtime choice (`provider`, from the registry) and optional model are stored on the agent task row.
    New tasks are Orchestrator tasks and follow `routing.orchestrator` unless the request names a provider."""

    def create(self, app, project_id, **extra):
        task_id = app.handle('agent_create', dict({'project_id': project_id, 'title': 'Fix it', 'scope': None},
                                                  **extra))['task_id']
        with app.lock:
            return app.store.task(task_id)

    def test_defaults_follow_the_orchestrator_routing(self):
        app = self.open()
        project_id = self.add_project(app)
        task = self.create(app, project_id)
        self.assertEqual((task['role'], task['provider'], task['model']), ('orchestrator', 'claude', None))
        public = app.handle('state', {})
        self.assertEqual([t['provider'] for t in public['tasks'] if t['id'] == task['id']], ['claude'])
        self.assertEqual((public['task']['agent']['provider'], public['task']['agent']['model']), ('claude', None))
        routing_doc = routing.default()
        routing_doc['orchestrator'] = {'provider': 'codex', 'model': 'gpt-test-1'}
        app.handle('routing_update', {'routing': routing_doc})
        task = self.create(app, project_id)
        self.assertEqual((task['role'], task['provider'], task['model']), ('orchestrator', 'codex', 'gpt-test-1'))

    def test_explicit_provider_and_model_override_the_routing(self):
        app = self.open()
        project_id = self.add_project(app)
        routing_doc = routing.default()
        routing_doc['orchestrator'] = {'provider': 'codex', 'model': 'gpt-test-1'}
        app.handle('routing_update', {'routing': routing_doc})
        task = self.create(app, project_id, provider='claude', model=' claude-opus-5-5 ')
        self.assertEqual((task['provider'], task['model']), ('claude', 'claude-opus-5-5'))
        # Another provider without a model gets that provider's own default, not the routing model.
        task = self.create(app, project_id, provider='claude')
        self.assertEqual((task['provider'], task['model']), ('claude', None))
        task = self.create(app, project_id, model='')
        self.assertEqual((task['provider'], task['model']), ('codex', None))

    def test_invalid_provider_or_model_is_refused_before_anything_is_saved(self):
        app = self.open()
        project_id = self.add_project(app)
        for extra in ({'provider': 'gpt'}, {'provider': None}, {'model': 7}, {'model': 'x' * 65},
                      {'model': 'bad model'}, {'model': 'claude-sonnet'}, {'provider': 'codex', 'model': 'a/b'},
                      {'provider': 'codex', 'model': 'x' * 65}):
            with self.assertRaisesRegex(ValueError, 'provider|model'):
                app.handle('agent_create', dict({'project_id': project_id, 'title': 'Fix it', 'scope': None}, **extra))
        with app.lock:
            self.assertEqual(list(app.state['projects'][project_id].get('tasks', {})), [])
        self.assertEqual(self.audit.records, [])

    def test_saved_rows_are_validated(self):
        task = tasks.create('A', project_id='p1')
        self.assertEqual((task['provider'], task['model']), ('claude', None))
        del task['provider'], task['model']
        tasks.validate(task, task['id'])  # Agent tasks saved before providers existed ran on Codex.
        self.assertEqual(tasks.provider(task), 'codex')
        for bad in ({'provider': 'other'}, {'model': 5}, {'model': 'a b'}):
            broken = dict(task, **bad)
            with self.assertRaises(ValueError):
                tasks.validate(broken, task['id'])
        legacy = tasks.imported('B')
        self.assertNotIn('provider', legacy)
        with self.assertRaises(ValueError):
            tasks.create('C', project_id='p1', provider='other')
        with self.assertRaises(ValueError):
            tasks.create('C', project_id='p1', provider='claude', model='gpt-5')
        self.assertFalse(hasattr(tasks, 'PROVIDERS'))  # The registry is the only provider list.
        self.assertFalse(hasattr(tasks, 'MODEL'))


class CodexHomeTests(ApplicationCase):
    def test_default_codex_auth_uses_the_app_owned_home(self):
        app = service.Application(self.root / 'data2', emit=Output(), scope_api=self.scope, audit_api=self.audit,
                                  runtime_factory=lambda task_id: self.runtime)
        self.addCleanup(app.scheduler.shutdown, 5)
        self.assertEqual(app.provider.codex_home, (self.root / 'data2' / 'codex-home').resolve())

    def test_stale_provider_status_is_not_kept_across_restarts(self):
        app = self.open()
        with app.lock:
            app.state['provider_status'] = {'codex': {'provider': 'codex', 'state': 'signed_in', 'account': 'x',
                                                      'detail': ''}}
            app.persist()
        app.scheduler.shutdown(5)
        again = self.open()
        self.assertEqual(again.handle('state', {})['provider_status'], {})


class ProviderBudgetTests(unittest.TestCase):
    def test_provider_aware_charge_and_ledger_fields(self):
        usage = {'input_tokens': 100, 'output_tokens': 20, 'cache_read_input_tokens': 5}
        self.assertEqual(budget.charge(usage), 120)
        self.assertEqual(budget.charge(usage, 'codex'), 120)
        self.assertIsNone(budget.charge(usage, 'claude'), 'the Claude rule arrives with 2B')
        self.assertEqual(budget.estimate_turn(0), budget.AGENT_TURN_ALLOWANCE)
        self.assertEqual(budget.estimate_turn(10), budget.AGENT_TURN_ALLOWANCE + 4)
        state, task = {'usage': []}, {'id': 't', 'token_budget': 100000}
        entry_id = budget.reserve(state, task, role='Agent', prompt='hello', project_id='p', estimate=30002,
                                  provider='codex', turn_id='u1', call_kind='agent_turn')
        entry = state['usage'][0]
        self.assertEqual((entry['estimate'], entry['provider'], entry['charge_rule'], entry['turn_id'], entry['call_kind']),
                         (30002, 'codex', 'codex.input+output', 'u1', 'agent_turn'))
        budget.settle(state, entry_id, {'input_tokens': 10, 'output_tokens': 5}, 'completed')
        self.assertEqual((entry['charge_kind'], entry['charge']), ('reported', 15))
        claude = budget.reserve(state, task, role='Agent', prompt='x', project_id='p', estimate=1000, provider='claude', turn_id='u2')
        budget.settle(state, claude, {'input_tokens': 10, 'output_tokens': 5}, 'completed')
        self.assertEqual((state['usage'][1]['charge_kind'], state['usage'][1]['charge']), ('estimated', 1000))
        with self.assertRaises(ValueError):
            budget.reserve(state, task, role='Agent', prompt='x', project_id='p', estimate=1, provider='other')
        legacy = budget.reserve(state, task, role='Researcher', prompt='p', project_id='p')
        self.assertNotIn('provider', next(e for e in state['usage'] if e['id'] == legacy))
        self.assertEqual(budget.ledger(state, 't', 100000)['used'], 1015)


class ResearchTaskServiceTests(unittest.TestCase):
    """research/tasks.md: `agent_create` with `project_id: null`, the Research collection and its selection."""

    def setUp(self):
        import scope
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.scope = scope
        self.app = self.open()

    def open(self):
        app = service.Application(self.root / 'data', scope_api=self.scope, audit_api=FakeAudit(),
                                  runtime_factory=lambda task_id: FakeRuntime(), interrupt_grace_s=0.2)
        self.addCleanup(app.scheduler.shutdown, 5)
        return app

    def repo(self, name):
        repo = self.root / name
        repo.mkdir()
        git = ['git', '-c', 'user.name=T', '-c', 'user.email=t@example.invalid']
        subprocess.run(git + ['init', '-q', str(repo)], check=True)
        (repo / 'README.md').write_text('# Repo\n')
        subprocess.run(git + ['-C', str(repo), 'add', '.'], check=True)
        subprocess.run(git + ['-C', str(repo), 'commit', '-q', '-m', 'base'], check=True)
        return self.app.handle('add_project', {'path': str(repo)})['project_id']

    def test_a_research_task_needs_the_research_kind(self):
        with self.assertRaisesRegex(ValueError, 'Unknown project'):
            self.app.handle('agent_create', {'project_id': None, 'title': 'x'})
        with self.assertRaisesRegex(ValueError, 'Unknown task kind'):
            self.app.handle('agent_create', {'project_id': None, 'kind': 'other', 'title': 'x'})

    def test_research_tasks_live_in_the_research_collection_and_survive_a_restart(self):
        created = self.app.handle('agent_create', {'project_id': None, 'kind': 'research', 'title': 'Related work'})
        task_id = created['task_id']
        with self.app.lock:
            task = self.app.state['research']['tasks'][task_id]
            self.assertEqual((task['kind'], task['agent']['project_id']), ('research', None))
            self.assertEqual(task['scope']['projects'], [])
            self.assertEqual(task['scope']['research'], {'sources': {}})  # No research module in this build.
            self.assertEqual(self.app.store.task(task_id)['id'], task_id)
        public = self.app.handle('state', {})
        self.assertEqual((public['project_id'], public['project'], public['task_id']), (None, 'Research', task_id))
        self.assertEqual(public['research'], {'selected': True, 'task_count': 1})
        self.assertEqual([(r['id'], r['kind']) for r in public['tasks']], [(task_id, 'research')])
        self.assertEqual(public['task']['agent']['project_id'], None)
        # Leaving and coming back to the Research entry, and choosing no task.
        project_id = self.repo('repo')
        self.assertEqual(self.app.handle('switch_project', {'project_id': project_id})['research']['selected'], False)
        back = self.app.handle('switch_project', {'project_id': None, 'research': True})
        self.assertEqual((back['project_id'], back['task_id']), (None, task_id))
        self.assertIsNone(self.app.handle('select_task', {'project_id': None, 'task_id': None})['task_id'])
        self.assertEqual(self.app.handle('select_task', {'project_id': None, 'task_id': task_id})['task_id'], task_id)
        with self.assertRaises(ValueError):
            self.app.handle('select_task', {'project_id': None, 'task_id': 'nope'})
        self.app.scheduler.shutdown(5)
        again = self.open()
        self.assertEqual(again.handle('state', {})['task_id'], task_id)
        with again.lock:
            self.assertEqual(again.store.task(task_id)['kind'], 'research')

    def test_a_proposed_scope_with_project_files_is_refused(self):
        project_id = self.repo('repo2')
        document = self.scope.project_default(project_id)
        with self.assertRaisesRegex(ValueError, 'no project files'):
            self.app.handle('agent_create', {'project_id': None, 'kind': 'research', 'title': 'x', 'scope': document})

    def test_damaged_research_state_is_replaced_on_load(self):
        with self.app.lock:
            self.app.state['research'] = 'damaged'
            self.assertEqual(service.research_state(self.app.state),
                             {'tasks': {}, 'selected_task_id': None, 'selected': False})

    def test_usable_sources_come_from_the_research_module(self):
        class Source:
            def __init__(self, name, configured, required):
                self.name, self.required, self.configured = name, required, configured

            def status(self, test=False):
                if self.name == 'broken':
                    raise RuntimeError('no')
                return {'configured': self.configured}
        module = types.ModuleType('research')
        module.sources = lambda app: [Source('crossref', False, False), Source('unpaywall', False, True),
                                      Source('openalex', True, False), Source('broken', False, True)]
        with mock.patch.dict(sys.modules, {'research': module}):
            self.assertEqual(self.app.research_sources_usable(),
                             {'crossref': True, 'unpaywall': False, 'openalex': True, 'broken': False})
            created = self.app.handle('agent_create', {'project_id': None, 'kind': 'research', 'title': 'R'})
        with self.app.lock:
            sources = self.app.store.task(created['task_id'])['scope']['research']['sources']
        self.assertEqual(sources, {'crossref': 'allow', 'unpaywall': 'off', 'openalex': 'allow', 'broken': 'off'})
        with self.assertRaisesRegex(ValueError, 'not in this build'):
            self.app.research_dispatch(None, 'research_search', {})


if __name__ == '__main__':
    unittest.main()
