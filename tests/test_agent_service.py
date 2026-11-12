"""Service wiring for agentic tasks: stdin routing, the Keychain bridge, agent and scope methods, Spaces
requests, the legacy slot, and the agent-mode task and budget changes. Fakes only: no provider, no
network, no Keychain."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
sys.path.insert(0, str(ROOT / 'tests'))

import service  # Puts pilot/ on the path for projects.
import budget
import projects
import scheduler
import tasks
from agent_fakes import FakeAudit, FakeRuntime, FakeScope, wait_for, wait_interrupt

SECRET = 'canary-secret-value-7f3a'


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
        self.bridge = service.KeychainBridge(emit, timeout_s=2)
        self.block = threading.Event()
        self.block.set()

    def handle(self, method, params):
        self.calls.append(method)
        if method == 'slow':
            self.block.wait(5)
        if method == 'spaces_secret':
            return {'has_secret': service.BridgeCredentials(self.bridge, 'notion').get() is not None}
        if method == 'boom':
            raise RuntimeError('internal detail')
        return {'method': method}


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.out = Output()
        self.app = StubApp(self.out)
        self.router = service.Router(self.app, self.out)
        self.addCleanup(self.router.close, 5)

    def test_keychain_replies_never_reach_request_handling_or_output(self):
        self.assertEqual(self.router.route(json.dumps({'keychain_reply': 'kc-unknown', 'ok': True, 'secret': SECRET})), 'keychain')
        self.assertEqual(self.router.route(json.dumps({'keychain_reply': 'kc-x', 'method': 'state', 'id': 1, 'secret': SECRET})), 'keychain')
        time.sleep(0.05)
        self.assertEqual(self.app.calls, [])
        self.assertNotIn(SECRET, json.dumps(self.out.messages))

    def test_bridge_hello_only_as_first_line(self):
        self.assertEqual(self.router.route(json.dumps({'bridge_hello': {'keychain': 1, 'open_url': 1}})), 'hello')
        self.assertEqual(self.app.bridge.capabilities, {'keychain': True, 'open_url': True})
        other = service.Router(StubApp(self.out), self.out)
        self.addCleanup(other.close, 5)
        other.route(json.dumps({'id': 1, 'method': 'state'}))
        self.assertEqual(other.route(json.dumps({'bridge_hello': {'keychain': 1}})), 'hello')
        self.assertEqual(other.app.bridge.capabilities, {}, 'a late hello (for example from a confused sender) is ignored')

    def test_legacy_requests_keep_order_and_errors(self):
        for index, method in enumerate(['a', 'b', 'boom', 'c']):
            self.assertEqual(self.router.route(json.dumps({'id': index, 'method': method})), 'legacy')
        self.router.route('not json\n')
        self.router.route('[1]\n')
        wait_for(lambda: len(self.out.messages) == 6)
        self.assertEqual(self.app.calls, ['a', 'b', 'boom', 'c'])
        self.assertEqual([m.get('id') for m in self.out.messages], [0, 1, 2, 3, None, None])
        self.assertEqual(self.out.messages[2]['error'], 'Request failed. Check repository and provider access.')
        self.assertEqual(self.out.messages[5]['error'], 'Request must be an object')

    def test_spaces_and_agent_requests_do_not_wait_behind_legacy(self):
        self.app.block.clear()
        self.router.route(json.dumps({'id': 'slow', 'method': 'slow'}))
        wait_for(lambda: 'slow' in self.app.calls)
        self.assertEqual(self.router.route(json.dumps({'id': 's', 'method': 'spaces_status'})), 'spaces')
        self.assertEqual(self.router.route(json.dumps({'id': 'e', 'method': 'task_events'})), 'agent')
        self.assertEqual(self.router.route(json.dumps({'id': 'm', 'method': 'agent_message'})), 'agent')
        wait_for(lambda: all(self.out.reply(i) for i in ('s', 'e', 'm')))
        self.assertIsNone(self.out.reply('slow'))
        self.app.block.set()
        wait_for(lambda: self.out.reply('slow') is not None)

    def test_credentials_call_inside_a_request_reads_its_reply_from_the_reader_thread(self):
        self.router.route(json.dumps({'bridge_hello': {'keychain': 1, 'open_url': 1}}))
        self.router.route(json.dumps({'id': 'q', 'method': 'spaces_secret'}))
        wait_for(lambda: self.out.of_type('keychain'))
        request = self.out.of_type('keychain')[0]
        self.assertEqual((request['op'], request['account']), ('read', 'notion'))
        self.assertNotIn('secret', request)
        self.router.route(json.dumps({'keychain_reply': request['id'], 'ok': True, 'secret': json.dumps({'token': SECRET})}))
        wait_for(lambda: self.out.reply('q') is not None)
        self.assertEqual(self.out.reply('q'), {'id': 'q', 'result': {'has_secret': True}})
        self.assertNotIn(SECRET, json.dumps(self.out.messages))

    def test_serve_reads_until_end_of_input(self):
        closed = threading.Event()
        lines = [json.dumps({'id': 1, 'method': 'a'}) + '\n', json.dumps({'keychain_reply': 'kc-1', 'ok': False}) + '\n']
        self.router.serve(iter(lines), closed)
        wait_for(lambda: self.out.reply(1) is not None)
        self.assertEqual(self.app.calls, ['a'])


class BridgeTests(unittest.TestCase):
    def test_nothing_is_sent_before_hello(self):
        out = Output()
        bridge = service.KeychainBridge(out, timeout_s=1)
        started = time.monotonic()
        with self.assertRaises(service.CredentialStoreUnavailable):
            service.BridgeCredentials(bridge, 'github').get()
        self.assertLess(time.monotonic() - started, 0.5)
        with self.assertRaises(ValueError):
            bridge.open_url('https://github.com/login/device')
        self.assertEqual(out.messages, [])

    def test_replies_timeouts_and_open_url(self):
        out = Output()
        bridge = service.KeychainBridge(out, timeout_s=0.1)
        bridge.hello({'keychain': 1, 'open_url': 1})
        with self.assertRaises(service.CredentialStoreUnavailable):
            service.BridgeCredentials(bridge, 'github').get()
        self.assertFalse(bridge.reply({'keychain_reply': out.of_type('keychain')[0]['id'], 'ok': True}), 'late reply is dropped')
        with self.assertRaises(ValueError):
            bridge.keychain('read', 'other-app')
        bridge.timeout_s = 2
        credentials = service.BridgeCredentials(bridge, 'github')

        def answer(reply):
            wait_for(lambda: len(out.of_type('keychain')) > answer.count)
            message = out.of_type('keychain')[-1]
            answer.count += 1
            bridge.reply(dict(reply, keychain_reply=message['id']))
        answer.count = 1
        for reply, call, expected in (({'ok': False, 'error': 'not_found'}, credentials.get, None),
                                      ({'ok': True}, lambda: credentials.set({'token': SECRET}), None),
                                      ({'ok': True}, credentials.delete, None)):
            thread = threading.Thread(target=answer, args=(reply,))
            thread.start()
            self.assertEqual(call(), expected)
            thread.join(2)
        write = out.of_type('keychain')[2]
        self.assertEqual((write['op'], json.loads(write['secret'])), ('write', {'token': SECRET}))
        thread = threading.Thread(target=answer, args=({'ok': False, 'error': 'denied'},))
        thread.start()
        with self.assertRaisesRegex(service.CredentialStoreUnavailable, 'refused'):
            credentials.get()
        thread.join(2)
        for bad in ('http://example.com', 'javascript:alert(1)', 'file:///etc/passwd', None):
            with self.assertRaises(ValueError):
                bridge.open_url(bad)
        bridge.open_url('https://github.com/login/device')
        self.assertEqual(out.of_type('open_url'), [{'type': 'open_url', 'url': 'https://github.com/login/device'}])


class FakeSpacesConnector:
    def __init__(self, name):
        self.app = name
        self.writes = []

    def status(self):
        return {'v': 1, 'app': self.app, 'state': 'signed_in', 'account': {'label': 'me', 'id': '1'}, 'granted': [],
                'detail': '', 'checked_at': '2026-11-12T00:00:00.000Z'}

    def browse(self, parent=None, cursor=None, limit=50):
        return {'v': 1, 'items': [], 'next_cursor': None}

    def write(self, action, ref, params, key):
        self.writes.append((action, ref, params, key))
        return {'v': 1, 'ok': True, 'action': action, 'ref': ref, 'result_ref': ref, 'url': None, 'version': None,
                'replayed': False, 'summary': 'Done.'}

    def changes(self, cursor=None, limit=100):
        if cursor is None:
            return {'v': 1, 'items': [], 'cursor': 'c1', 'complete': True}
        return {'v': 1, 'items': [{'ref': self.app + ':page:x', 'change': 'updated', 'at': 'x', 'title': 'X'}],
                'cursor': 'c2', 'complete': True}


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
        self.connectors = {}

    def open(self, data=None):
        self.out = Output()
        factory = lambda name: self.connectors.setdefault(name, FakeSpacesConnector(name))
        app = service.Application(data or self.root / 'data', provider=FakeProvider(), emit=self.out,
                                  scope_api=self.scope, audit_api=self.audit, runtime_factory=lambda task_id: self.runtime,
                                  connector_factory=factory, interrupt_grace_s=0.2)
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

    def test_agent_task_refuses_legacy_flows(self):
        app = self.open()
        task_id = self.create(app, self.add_project(app))
        for method in ('chat', 'start_review', 'start_plan', 'start_change'):
            with self.assertRaisesRegex(ValueError, 'Agent tasks'):
                app.handle(method, {'project_id': app.state['selected_project_id'], 'task_id': task_id, 'text': 'x'})
        with self.assertRaisesRegex(ValueError, 'scope'):
            app.handle('update_task', {'project_id': app.state['selected_project_id'], 'task_id': task_id, 'token_budget': 5})
        with self.assertRaisesRegex(ValueError, 'agent_create'):
            app.handle('create_task', {'project_id': app.state['selected_project_id'], 'title': 'x', 'mode': 'agent'})

    def test_legacy_interaction_needs_a_free_slot_and_frees_it(self):
        self.runtime.script = wait_interrupt(honor=True)
        app = self.open()
        project_id = self.add_project(app)
        app.handle('scheduler_settings', {'max_running': 1})
        self.assertEqual(app.state['scheduler_settings'], {'max_running': 1})
        busy = self.create(app, project_id)
        app.handle('agent_message', {'task_id': busy, 'text': 'go', 'client_id': None})
        wait_for(lambda: self.agent_state(app, busy) == 'running')
        with self.assertRaisesRegex(ValueError, 'slots'):
            app.handle('sign_in', {})
        self.assertIsNone(app.state['active'])
        app.handle('agent_cancel', {'task_id': busy})
        wait_for(lambda: self.agent_state(app, busy) == 'cancelled')
        app.handle('sign_in', {})  # The legacy slot is free again; the fake sign-in waits for cancel.
        self.assertEqual(app.state['active'], 'Signing in')
        queued = self.create(app, project_id)
        self.assertEqual(app.handle('agent_message', {'task_id': queued, 'text': 'go', 'client_id': None})['state'], 'queued')
        self.assertTrue(app.handle('state', {})['scheduler']['legacy_active'])
        app.handle('cancel', {})
        wait_for(lambda: self.agent_state(app, queued) == 'running')
        app.handle('agent_cancel', {'task_id': queued})
        wait_for(lambda: self.agent_state(app, queued) == 'cancelled')

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
            ctx.authorize({'category': 'command', 'argv': ['ls']}, 'c1')
            return {'status': 'completed', 'usage': None, 'error': None}
        self.runtime.script = script
        app = self.open()
        task_id = self.create(app, self.add_project(app))
        app.handle('agent_message', {'task_id': task_id, 'text': 'go', 'client_id': None})
        wait_for(lambda: self.agent_state(app, task_id) == 'idle')
        self.assertEqual(self.scope.decide_options[0]['app_data'], str(app.storage))


class SpacesMethodTests(ApplicationCase):
    def test_status_write_and_changes(self):
        app = self.open()
        status = app.handle('spaces_status', {})
        self.assertEqual([s['app'] for s in status['apps']], ['notion', 'github', 'gdrive', 'zotero'])
        self.assertEqual(app.handle('state', {})['spaces']['apps']['github']['state'], 'signed_in')
        with self.assertRaisesRegex(ValueError, 'Unknown app'):
            app.handle('spaces_browse', {'app': 'dropbox'})
        result = app.handle('spaces_write', {'app': 'notion', 'action': 'notion.page.append', 'ref': 'notion:page:n1',
                                             'params': {'markdown': 'hi'}, 'idempotency_key': 'k1'})
        self.assertTrue(result['ok'])
        records = [r for r in self.audit.records if r['kind'] == 'user_write']
        self.assertEqual([(r['actor'], r['outcome'], r['idempotency_key']) for r in records], [('user', 'succeeded', 'k1')])
        self.assertEqual(app.locks.holders(), {})
        self.audit.fail = True  # The write already happened; its result is still returned, never re-sent.
        self.assertTrue(app.handle('spaces_write', {'app': 'notion', 'action': 'notion.page.append', 'ref': 'notion:page:n1',
                                                    'params': {}, 'idempotency_key': 'k2'})['ok'])
        self.assertEqual(len(self.connectors['notion'].writes), 2)
        self.audit.fail = False
        self.assertEqual(app.handle('spaces_changes', {})['apps']['notion'], [])
        self.assertEqual(len(app.handle('spaces_changes', {})['apps']['notion']), 1)

    def test_without_connectors_spaces_report_unavailable(self):
        app = self.open()
        app.spaces.factory = lambda name: (_ for _ in ()).throw(ValueError('Connected apps are not available in this build yet.'))
        app.spaces._connectors = {}
        status = app.handle('spaces_status', {})
        self.assertEqual({s['state'] for s in status['apps']}, {'unavailable'})


class AgentModeTests(unittest.TestCase):
    def test_agent_task_shape(self):
        with self.assertRaisesRegex(ValueError, 'project'):
            tasks.create('A', mode='agent')
        task = tasks.create('A', mode='agent', project_id='p1')
        self.assertEqual(task['agent']['state'], None)
        self.assertIs(tasks.validate(task, task['id']), task)
        task['agent']['state'] = 'flying'
        with self.assertRaises(ValueError):
            tasks.validate(task, task['id'])
        with self.assertRaisesRegex(ValueError, 'agent'):
            tasks.validate_mode('chaos')
        legacy = tasks.create('B')
        self.assertNotIn('agent', legacy)


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
                                  audit_api=self.audit, connector_factory=lambda name: FakeSpacesConnector(name),
                                  interrupt_grace_s=0.2)
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


class AgentProviderTests(ApplicationCase):
    """The runtime choice (`provider`: codex or claude) and optional model are stored on the agent task row."""

    def test_defaults_to_codex_without_a_model(self):
        app = self.open()
        project_id = self.add_project(app)
        task_id = app.handle('agent_create', {'project_id': project_id, 'title': 'Fix it', 'scope': None})['task_id']
        with app.lock:
            task = app.store.task(task_id)
        self.assertEqual((task['provider'], task['model']), ('codex', None))
        public = app.handle('state', {})
        self.assertEqual([t['provider'] for t in public['tasks'] if t['id'] == task_id], ['codex'])
        self.assertEqual((public['task']['agent']['provider'], public['task']['agent']['model']), ('codex', None))

    def test_claude_and_model_are_stored(self):
        app = self.open()
        project_id = self.add_project(app)
        task_id = app.handle('agent_create', {'project_id': project_id, 'title': 'Fix it', 'scope': None,
                                              'provider': 'claude', 'model': ' claude-opus-5-5 '})['task_id']
        with app.lock:
            task = app.store.task(task_id)
        self.assertEqual((task['provider'], task['model']), ('claude', 'claude-opus-5-5'))
        self.assertEqual([t['provider'] for t in app.handle('state', {})['tasks'] if t['id'] == task_id], ['claude'])

    def test_invalid_provider_or_model_is_refused_before_anything_is_saved(self):
        app = self.open()
        project_id = self.add_project(app)
        for extra in ({'provider': 'gpt'}, {'provider': None}, {'model': 7}, {'model': 'x' * 129},
                      {'model': 'bad model'}, {'model': '--yolo'}):
            with self.assertRaisesRegex(ValueError, 'runtime|model'):
                app.handle('agent_create', dict({'project_id': project_id, 'title': 'Fix it', 'scope': None}, **extra))
        with app.lock:
            self.assertEqual(list(app.state['projects'][project_id].get('tasks', {})), [])
        self.assertEqual(self.audit.records, [])
        self.assertEqual(app.handle('agent_create', {'project_id': project_id, 'title': 'X', 'scope': None,
                                                     'model': ''})['task_id'] != '', True, 'empty model means default')

    def test_saved_rows_are_validated(self):
        task = tasks.create('A', mode='agent', project_id='p1')
        self.assertEqual((task['provider'], task['model']), ('codex', None))
        del task['provider'], task['model']
        tasks.validate(task, task['id'])  # Agent tasks saved before Wave 2 run on Codex.
        self.assertEqual(tasks.provider(task), 'codex')
        for bad in ({'provider': 'other'}, {'model': 5}):
            broken = dict(task, **bad)
            with self.assertRaises(ValueError):
                tasks.validate(broken, task['id'])
        legacy = tasks.create('B')
        self.assertNotIn('provider', legacy)
        with self.assertRaises(ValueError):
            tasks.create('C', provider='claude')  # Only agent tasks choose a runtime.


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


if __name__ == '__main__':
    unittest.main()
