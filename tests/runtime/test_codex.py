"""The Codex app-server runtime against a scripted fake app-server process. No real Codex, model or network."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'app/backend'))
sys.path.insert(0, str(ROOT / 'tests'))

import runtime  # noqa: E402
from runtime import codex, mcp_bridge  # noqa: E402

FAKE = Path(__file__).resolve().parent / 'fixtures' / 'codex' / 'fake_app_server.py'
TOOLS = [{'v': 1, 'name': 'example_read', 'title': 'Read', 'description': 'Read an item.',
          'input_schema': {'type': 'object'}, 'effect': 'read'}]


def started(item):
    return {'notify': 'item/started', 'params': {'threadId': '$thread', 'turnId': '$turn', 'item': item}}


def completed(item):
    return {'notify': 'item/completed', 'params': {'threadId': '$thread', 'turnId': '$turn', 'item': item}}


def command_item(item_id, command, cwd, status='inProgress', **extra):
    item = {'type': 'commandExecution', 'id': item_id, 'command': "/bin/zsh -lc '%s'" % command, 'cwd': cwd,
            'status': status, 'commandActions': [], 'aggregatedOutput': None, 'exitCode': None, 'durationMs': None}
    item.update(extra)
    return item


def command_approval(item_id, command, cwd, **extra):
    params = {'kind': 'command', 'threadId': '$thread', 'turnId': '$turn', 'itemId': item_id,
              'startedAtMs': 1, 'environmentId': 'local', 'command': "/bin/zsh -lc '%s'" % command, 'cwd': cwd,
              'availableDecisions': ['accept', 'cancel']}
    params.update(extra)
    return {'request': 'item/commandExecution/requestApproval', 'params': params}


def file_item(item_id, changes, status='inProgress'):
    return {'type': 'fileChange', 'id': item_id, 'changes': changes, 'status': status}


def usage(total_in, total_out, turn='$turn'):
    total = {'totalTokens': total_in + total_out, 'inputTokens': total_in, 'cachedInputTokens': total_in // 2,
             'cacheWriteInputTokens': 0, 'outputTokens': total_out, 'reasoningOutputTokens': 0}
    return {'notify': 'thread/tokenUsage/updated', 'params': {'threadId': '$thread', 'turnId': turn,
                                                              'tokenUsage': {'total': total, 'last': total,
                                                                             'modelContextWindow': 1000}}}


class FakeContext:
    def __init__(self, workspace, rules=None, scope=None, project_id='p1', workspaces=None):
        self.task_id = 'task1'
        self.turn_id = 'u1'
        self.project_ids = [project_id]
        self.workspaces = workspaces or {project_id: workspace}
        self.primary_workspace = workspace
        self.scope = scope or {'web_search': 'ask'}
        self.model = None
        self.cancel = threading.Event()
        self.rules = rules or {}
        self.events = []
        self.requests = []
        self.observations = []
        self.usages = []
        self.tool_calls = []
        self.tool_list = list(TOOLS)

    def tools(self):
        return list(self.tool_list)

    def authorize(self, request, call_id):
        self.requests.append((request, call_id))
        decision = self.rules.get(request['category'], 'allow')
        return {'decision': decision, 'rule': 'test.' + decision, 'reason': '', 'scope_version': 1, 'scope_digest': 'sha256:x'}

    def observed(self, request, call_id):
        self.observations.append((request, call_id))
        return {'decision': 'allow', 'rule': 'provider.sandbox', 'reason': '', 'scope_version': 1, 'scope_digest': 'sha256:x'}

    def emit(self, kind, data, *, turn_id=None, item_id=None):
        self.events.append((kind, data, item_id))

    def call_tool(self, name, arguments):  # The bridge's entry point (research Wave 1C).
        self.tool_calls.append((name, arguments, None))
        return {'ok': True, 'result': {}}

    def report_usage(self, value):
        self.usages.append(value)

    def report_limits(self, raw):
        self.limits = getattr(self, 'limits', []) + [raw]

    def kinds(self):
        return [kind for kind, _, _ in self.events]

    def of(self, kind):
        return [data for k, data, _ in self.events if k == kind]


class CodexCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(os.path.realpath(self.tmp.name))
        self.data = self.root / 'data'
        self.workspace = self.data / 'workspaces' / 'task1' / 'p1'
        self.workspace.mkdir(parents=True)
        (self.data / 'workspaces' / 'task2' / 'p1').mkdir(parents=True)
        (self.data / 'tasks').mkdir()
        (self.data / 'state.json').write_text('{}')
        self.home = self.root / 'home'
        self.home.mkdir()
        self.log = self.root / 'log.jsonl'
        self.sock_dir = tempfile.mkdtemp(dir='/tmp')
        self.addCleanup(lambda: os.path.isdir(self.sock_dir) and os.rmdir(self.sock_dir))

    def runtime(self, scenario, environ=None):
        path = self.root / 'scenario.json'
        path.write_text(json.dumps(scenario))
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(self.home), 'SECRET_TOKEN': 'shh'}
        env.update(environ or {})
        return codex.CodexRuntime(command=[sys.executable, str(FAKE), str(path), str(self.log)],
                                  codex_home=self.data / 'codex-home', app_data=self.data, socket_dir=self.sock_dir,
                                  environ=env, start_timeout_s=10)

    def ctx(self, **kwargs):
        return FakeContext(str(self.workspace), **kwargs)

    def open(self, scenario, ctx=None, **kwargs):
        ctx = ctx or self.ctx()
        session = self.runtime(scenario, **kwargs).open(ctx)
        self.addCleanup(session.close)
        return session, ctx

    def logged(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def sent(self, method=None):
        found = [e['in'] for e in self.logged() if 'in' in e]
        return [m for m in found if method is None or m.get('method') == method]

    def replies(self):
        return [m for m in self.sent() if 'method' not in m]


class LaunchTests(CodexCase):
    def test_launch_is_sandboxed_isolated_and_never_bypassed(self):
        session, ctx = self.open({})
        launch = self.logged()[0]
        argv = launch['argv']
        self.assertEqual(argv[0], 'app-server')
        overrides = dict(argv[i + 1].split('=', 1) for i in range(1, len(argv), 2) if argv[i] == '-c')
        self.assertEqual(overrides['default_permissions'], '"interspace-task"')
        profile = overrides['permissions.interspace-task']
        self.assertIn('"extends"=":workspace"', profile)
        self.assertIn('"network"={"enabled"=false}', profile)
        for denied in (self.home / '.ssh', self.home / '.codex', self.data / 'tasks', self.data / 'state.json',
                       self.data / 'workspaces' / 'task2', self.data / 'codex-home'):
            self.assertIn(json.dumps(str(denied)) + '="deny"', profile)
        self.assertNotIn(json.dumps(str(self.workspace)) + '=', profile)
        self.assertNotIn(json.dumps(str(self.data / 'workspaces')) + '=', profile)
        self.assertEqual(overrides['project_doc_max_bytes'], '0')
        self.assertEqual(overrides['allow_login_shell'], 'false')
        self.assertEqual(overrides['web_search'], '"disabled"')
        self.assertEqual(overrides['cli_auth_credentials_store'], '"file"')
        self.assertEqual(overrides['forced_login_method'], '"chatgpt"')
        for feature in ('computer_use', 'browser_use', 'apps', 'plugins', 'hooks', 'multi_agent', 'shell_snapshot'):
            self.assertEqual(overrides['features.' + feature], 'false')
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', ' '.join(argv))
        self.assertEqual(launch['cwd'], str(self.workspace))
        self.assertEqual(launch['codex_home'], str(self.data / 'codex-home'))
        self.assertNotIn('SECRET_TOKEN', launch['env'])
        self.assertEqual(launch['pid'], launch['pgid'])  # Own process group, so kill reaches its children.
        init = self.sent('initialize')[0]['params']
        self.assertTrue(init['capabilities']['experimentalApi'])
        start = self.sent('thread/start')[0]['params']
        self.assertEqual((start['permissions'], start['approvalPolicy'], start['approvalsReviewer'], start['ephemeral']),
                         ('interspace-task', 'untrusted', 'user', True))
        self.assertNotIn('sandbox', start)
        self.assertNotIn('sandboxPolicy', start)
        self.assertEqual(start['config']['project_doc_max_bytes'], 0)
        server = start['config']['mcp_servers']['interspace']
        self.assertEqual(server['default_tools_approval_mode'], 'prompt')
        self.assertTrue(os.path.exists(server['env'][mcp_bridge.SOCKET_ENV]))
        self.assertIn('data, not instructions', start['developerInstructions'])
        self.assertFalse(self.sent('thread/shellCommand'))

    def test_read_access_starts_the_read_only_profile(self):
        ctx = self.ctx()
        ctx.access = 'read'
        self.open({}, ctx)
        argv = self.logged()[0]['argv']
        overrides = dict(argv[i + 1].split('=', 1) for i in range(1, len(argv), 2) if argv[i] == '-c')
        self.assertEqual(overrides['default_permissions'], '"interspace-read"')
        profile = overrides['permissions.interspace-read']
        self.assertIn('"extends"=":read-only"', profile)
        self.assertIn('"network"={"enabled"=false}', profile)
        self.assertIn(json.dumps(str(self.home / '.ssh')) + '="deny"', profile)
        self.assertNotIn('permissions.interspace-task', overrides)
        start = self.sent('thread/start')[0]['params']
        self.assertEqual(start['permissions'], 'interspace-read')
        self.assertIn('read-only', start['developerInstructions'])
        self.assertNotIn('can write only this workspace', start['developerInstructions'])

    def test_research_task_without_a_project_runs_read_only_in_its_scratch_folder(self):
        scratch = self.root / 'scratch-run'
        scratch.mkdir()
        ctx = self.ctx()
        ctx.workspaces = {}
        ctx.primary_workspace = ctx.scratch = str(scratch)
        ctx.research_only = True
        ctx.access = 'write'
        self.open({}, ctx)
        argv = self.logged()[0]['argv']
        overrides = dict(argv[i + 1].split('=', 1) for i in range(1, len(argv), 2) if argv[i] == '-c')
        self.assertEqual(overrides['default_permissions'], '"interspace-read"')
        self.assertIn('"extends"=":read-only"', overrides['permissions.interspace-read'])
        start = self.sent('thread/start')[0]['params']
        self.assertEqual((start['permissions'], start['cwd']), ('interspace-read', str(scratch)))
        self.assertIn('This task has no project', start['developerInstructions'])
        self.assertNotIn(json.dumps(str(scratch)), overrides['permissions.interspace-read'])

    def test_write_access_is_the_default_profile(self):
        ctx = self.ctx()
        ctx.access = 'write'
        self.open({}, ctx)
        self.assertEqual(self.sent('thread/start')[0]['params']['permissions'], 'interspace-task')

    def test_read_session_refuses_a_thread_on_another_profile(self):
        ctx = self.ctx()
        ctx.access = 'read'
        with self.assertRaises(runtime.RuntimeFailure):
            self.runtime({'thread_start': {'activePermissionProfile': {'id': 'interspace-task',
                                                                        'extends': ':workspace'}}}).open(ctx)

    def test_role_instructions_are_added_to_the_developer_instructions(self):
        ctx = self.ctx()
        ctx.instructions = 'You are the Orchestrator of an Interspace task.'
        self.open({}, ctx)
        text = self.sent('thread/start')[0]['params']['developerInstructions']
        self.assertTrue(text.startswith(codex.SHELL_DEVELOPER_INSTRUCTIONS))
        self.assertTrue(text.endswith('\n\n' + ctx.instructions))

    def test_web_search_and_model_follow_the_context(self):
        ctx = self.ctx(scope={'web_search': 'allow'})
        ctx.model = 'gpt-6.1-sol'
        self.open({}, ctx)
        self.assertIn('web_search="live"', self.logged()[0]['argv'])
        self.assertEqual(self.sent('thread/start')[0]['params']['model'], 'gpt-6.1-sol')

    def test_signed_out_account_is_refused_clearly(self):
        with self.assertRaises(runtime.RuntimeFailure) as caught:
            self.runtime({'account': None}).open(self.ctx())
        self.assertEqual(caught.exception.code, 'runtime_unavailable')
        self.assertIn('Sign in', str(caught.exception))
        self.assertFalse(self.sent('thread/start'))

    def test_thread_without_the_sandbox_profile_fails_closed(self):
        for patch in ({'activePermissionProfile': {'id': ':workspace', 'extends': None}},
                      {'activePermissionProfile': None}, {'approvalPolicy': 'never'},
                      {'approvalsReviewer': 'auto_review'}, {'sandbox': {'type': 'dangerFullAccess'}},
                      {'instructionSources': ['/repo/AGENTS.md']}):
            with self.subTest(patch=patch):
                with self.assertRaises(runtime.RuntimeFailure) as caught:
                    self.runtime({'thread_start': patch}).open(self.ctx())
                self.assertEqual(caught.exception.code, 'runtime_unavailable')

    def test_app_server_that_dies_at_start_is_unavailable(self):
        with self.assertRaises(runtime.RuntimeFailure) as caught:
            self.runtime({'exit_on': 'initialize'}).open(self.ctx())
        self.assertEqual(caught.exception.code, 'runtime_unavailable')

    def test_missing_codex_is_unavailable(self):
        rt = codex.CodexRuntime(codex_home=self.data / 'h', app_data=self.data)
        with mock.patch.object(codex, 'find_binary', return_value=None):
            with self.assertRaises(runtime.RuntimeFailure) as caught:
                rt.open(self.ctx())
        self.assertEqual(caught.exception.code, 'runtime_unavailable')

    def test_missing_workspace_is_refused(self):
        ctx = self.ctx()
        ctx.primary_workspace = str(self.root / 'gone')
        with self.assertRaises(runtime.RuntimeFailure) as caught:
            self.runtime({}).open(ctx)
        self.assertEqual(caught.exception.code, 'workspace_failed')

    def test_bridge_socket_lives_in_denied_app_data(self):
        # The bridge token and socket never sit in the shared temporary folder that every sandboxed command
        # can read: they go to <app data>/run, which the sandbox profile denies.
        path = self.root / 'scenario.json'
        path.write_text(json.dumps({}))
        rt = codex.CodexRuntime(mock.Mock(storage=str(self.data)), command=[sys.executable, str(FAKE), str(path),
                                str(self.log)], environ={'PATH': os.environ.get('PATH', ''), 'HOME': str(self.home)})
        ctx = self.ctx()
        session = rt.open(ctx)
        self.addCleanup(session.close)
        run = os.path.realpath(str(self.data / 'run'))
        self.assertTrue(session.bridge.path.startswith(run + os.sep), session.bridge.path)
        self.assertIn(run, rt.deny_paths(ctx))

    def test_run_dir_falls_back_when_the_socket_path_would_be_too_long(self):
        self.assertEqual(runtime.run_dir(self.data), os.path.realpath(str(self.data / 'run')))
        self.assertEqual(os.stat(str(self.data / 'run')).st_mode & 0o777, 0o700)
        self.assertIsNone(runtime.run_dir(self.root / ('x' * 90)))
        self.assertIsNone(runtime.run_dir(None))

    def test_no_tools_means_no_bridge_and_no_mcp_servers(self):
        ctx = self.ctx()
        ctx.tool_list = []
        session, _ = self.open({'turns': [[{'complete': 'completed'}]]}, ctx)
        self.assertIsNone(session.bridge)
        self.assertNotIn('mcp_servers', self.sent('thread/start')[0]['params']['config'])
        self.assertEqual(session.run_turn('x', ctx)['status'], 'completed')
        session.close()
        self.assertIsNotNone(session.process.poll())

    def test_close_stops_the_process_and_the_bridge(self):
        session, _ = self.open({})
        socket_path = self.sent('thread/start')[0]['params']['config']['mcp_servers']['interspace']['env'][mcp_bridge.SOCKET_ENV]
        session.close()
        self.assertIsNotNone(session.process.poll())
        self.assertFalse(os.path.exists(socket_path))


class TurnTests(CodexCase):
    def test_messages_reasoning_plan_and_usage(self):
        session, ctx = self.open({'turns': [[
            {'notify': 'account/rateLimits/updated', 'params': {'rateLimits': {'primary': {'usedPercent': 98}}}},
            started({'type': 'agentMessage', 'id': 'm1', 'text': ''}),
            {'notify': 'item/agentMessage/delta', 'params': {'threadId': '$thread', 'turnId': '$turn', 'itemId': 'm1', 'delta': 'Hel'}},
            {'notify': 'item/agentMessage/delta', 'params': {'threadId': '$thread', 'turnId': '$turn', 'itemId': 'm1', 'delta': 'lo'}},
            completed({'type': 'agentMessage', 'id': 'm1', 'text': 'Hello'}),
            completed({'type': 'reasoning', 'id': 'r1', 'summary': ['Looked at tests.'], 'content': []}),
            {'notify': 'turn/plan/updated', 'params': {'threadId': '$thread', 'turnId': '$turn', 'explanation': None,
                                                       'plan': [{'step': 'Read', 'status': 'completed'},
                                                                {'step': 'Fix', 'status': 'inProgress'}]}},
            usage(1000, 50), usage(3000, 120),
            {'complete': 'completed'}],
            [usage(5000, 200), {'complete': 'completed'}]]})
        result = session.run_turn('Say hello', ctx)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['usage']['input_tokens'], 3000)
        self.assertEqual(ctx.limits, [{'rateLimits': {'primary': {'usedPercent': 98}}}])  # Forwarded, never an event.
        self.assertEqual(result['usage']['output_tokens'], 120)
        self.assertEqual([u['input_tokens'] for u in ctx.usages], [1000, 3000])
        self.assertEqual(ctx.kinds(), ['message_delta', 'message_delta', 'message', 'reasoning', 'plan_update'])
        self.assertEqual(ctx.of('message')[0], {'role': 'assistant', 'text': 'Hello', 'final': True})
        self.assertEqual(ctx.of('plan_update')[0]['steps'][1], {'text': 'Fix', 'status': 'in_progress'})
        self.assertEqual(self.sent('turn/start')[0]['params']['input'][0]['text'], 'Say hello')
        second = session.run_turn('Again', ctx)
        self.assertEqual((second['usage']['input_tokens'], second['usage']['output_tokens']), (2000, 80))

    def test_effort_is_sent_only_when_chosen(self):
        for effort, wanted in (('xhigh', {'effort': 'xhigh'}), (None, {}), ('', {})):
            with self.subTest(effort=effort):
                ctx = self.ctx()
                ctx.effort = effort
                session, ctx = self.open({}, ctx)
                self.assertEqual(session.run_turn('Hi', ctx)['status'], 'completed')
                params = self.sent('turn/start')[-1]['params']
                self.assertEqual({k: v for k, v in params.items() if k == 'effort'}, wanted)

    EFFORT_MESSAGE = ('This Codex model does not support the chosen effort. '
                      'Choose another in Settings \u2192 Providers.')

    def test_refused_effort_fails_the_turn_once_with_a_clear_message(self):
        ctx = self.ctx()
        ctx.effort = 'turbo'
        session, ctx = self.open({'effort_refused': True}, ctx)
        result = session.run_turn('Hi', ctx)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error'], {'code': 'runtime_unavailable', 'message': self.EFFORT_MESSAGE})
        self.assertEqual(len(self.sent('turn/start')), 1)  # Never retried.

    def test_turn_failed_for_an_unlisted_effort_is_mapped_the_same_way(self):
        # The shape the real CLI sends: turn/start is accepted, then the turn fails with codexErrorInfo "other".
        raw = ('{"type":"error","error":{"message":"Invalid response.create payload: Invalid value: \'turbo\'. '
               'Supported values are: \'low\', \'medium\'.","type":"invalid_request_error"},"status":400}')
        ctx = self.ctx()
        ctx.effort = 'turbo'
        session, ctx = self.open({'turns': [[{'complete': 'failed', 'error': {
            'message': raw, 'codexErrorInfo': 'other'}}]]}, ctx)
        result = session.run_turn('Hi', ctx)
        self.assertEqual(result['error'], {'code': 'runtime_unavailable', 'message': self.EFFORT_MESSAGE})
        self.assertEqual(len(self.sent('turn/start')), 1)

    def test_other_failed_turn_without_effort_keeps_its_generic_message(self):
        session, ctx = self.open({'turns': [[{'complete': 'failed', 'error': {
            'message': 'Invalid value: x. Supported values are: y', 'codexErrorInfo': 'other'}}]]})
        self.assertEqual(session.run_turn('Hi', ctx)['error']['message'], 'The Codex turn failed. Try again.')

    def test_command_approval_runs_through_authorize(self):
        ws = str(self.workspace)
        session, ctx = self.open({'turns': [[
            started(command_item('c1', 'ls -a', ws)),
            command_approval('c1', 'ls -a', ws, proposedExecpolicyAmendment=['ls', '-a']),
            {'notify': 'item/commandExecution/outputDelta', 'params': {'threadId': '$thread', 'turnId': '$turn', 'itemId': 'c1', 'delta': 'a\n'}},
            completed(command_item('c1', 'ls -a', ws, status='completed', aggregatedOutput='a\n', exitCode=0, durationMs=7)),
            {'complete': 'completed'}]]})
        session.run_turn('list', ctx)
        request, call_id = ctx.requests[0]
        self.assertEqual(call_id, 'c1')
        self.assertEqual(request, {'category': 'command', 'argv': None, 'command': 'ls -a', 'cwd': '.',
                                   'sandbox': 'workspace', 'network': False, 'project_id': 'p1'})
        self.assertEqual(self.replies()[0]['result'], {'decision': 'accept'})
        self.assertEqual(ctx.kinds(), ['tool_call', 'tool_output_delta', 'tool_result'])
        call = ctx.of('tool_call')[0]
        self.assertEqual((call['category'], call['tool'], call['title']), ('command', 'shell', 'ls -a'))
        self.assertEqual(call['decision']['rule'], 'test.allow')
        result = ctx.of('tool_result')[0]
        self.assertEqual((result['status'], result['exit_code'], result['duration_ms'], result['output']['text']),
                         ('ok', 0, 7, 'a\n'))

    def test_denied_command_is_declined_never_amended(self):
        ws = str(self.workspace)
        session, ctx = self.open({'turns': [[
            started(command_item('c1', 'curl https://x', ws)),
            command_approval('c1', 'curl https://x', ws, additionalPermissions={'network': {'enabled': True}, 'fileSystem': None}),
            completed(command_item('c1', 'curl https://x', ws, status='declined')),
            {'complete': 'completed'}]]}, ctx=self.ctx(rules={'command': 'deny'}))
        session.run_turn('fetch', ctx)
        request = ctx.requests[0][0]
        self.assertEqual((request['sandbox'], request['network']), ('workspace', True))
        self.assertEqual(self.replies()[0]['result'], {'decision': 'decline'})
        self.assertEqual(ctx.of('tool_result')[0]['status'], 'denied')
        for reply in self.replies():
            self.assertNotIn('acceptForSession', json.dumps(reply))
            self.assertNotIn('Amendment', json.dumps(reply))

    def test_extra_file_system_access_is_an_escalation(self):
        ws = str(self.workspace)
        session, ctx = self.open({'turns': [[
            started(command_item('c1', 'make install', ws)),
            command_approval('c1', 'make install', ws, additionalPermissions={'network': None, 'fileSystem': {'write': ['/usr/local']}}),
            {'complete': 'completed'}]]})
        session.run_turn('x', ctx)
        self.assertEqual((ctx.requests[0][0]['sandbox'], ctx.requests[0][0]['network']), ('escalated', False))

    def test_command_outside_the_workspace_keeps_an_absolute_cwd(self):
        session, ctx = self.open({'turns': [[
            started(command_item('c1', 'ls', '/etc')), command_approval('c1', 'ls', '/etc'),
            {'complete': 'completed'}]]})
        session.run_turn('x', ctx)
        self.assertEqual(ctx.requests[0][0]['cwd'], os.path.realpath('/etc'))

    def test_network_approval_becomes_a_network_request(self):
        ws = str(self.workspace)
        session, ctx = self.open({'turns': [[
            started(command_item('c1', 'pip install x', ws)),
            command_approval('c1', 'pip install x', ws, networkApprovalContext={'host': 'PyPI.org', 'protocol': 'https'}),
            {'complete': 'completed'}]]})
        session.run_turn('x', ctx)
        self.assertEqual(ctx.requests[0][0], {'category': 'network', 'host': 'pypi.org', 'port': None, 'via': 'command'})
        self.assertEqual(ctx.of('tool_call')[0]['category'], 'network')

    def test_file_change_paths_come_from_the_started_item(self):
        ws = str(self.workspace)
        change = {'path': ws + '/src/a.py', 'kind': {'type': 'update', 'move_path': None},
                  'diff': '@@ -1 +1,2 @@\n-x\n+y\n+z\n'}
        session, ctx = self.open({'turns': [[
            started(file_item('f1', [change])),
            {'request': 'item/fileChange/requestApproval', 'params': {'threadId': '$thread', 'turnId': '$turn',
                                                                     'itemId': 'f1', 'startedAtMs': 1, 'reason': None, 'grantRoot': None}},
            completed(file_item('f1', [change], status='completed')),
            {'complete': 'completed'}]]})
        session.run_turn('edit', ctx)
        self.assertEqual(ctx.requests[0], ({'category': 'file_write', 'project_id': 'p1', 'paths': ['src/a.py']}, 'f1'))
        self.assertEqual(self.replies()[0]['result'], {'decision': 'accept'})
        self.assertEqual(ctx.kinds(), ['tool_call', 'diff', 'tool_result'])
        diff = ctx.of('diff')[0]
        self.assertEqual(diff['files'], [{'path': 'src/a.py', 'change': 'modify', 'old_path': None, 'additions': 2,
                                          'deletions': 1, 'binary': False}])
        self.assertFalse(diff['cumulative'])
        self.assertTrue(diff['patch'].startswith('diff --git a/src/a.py b/src/a.py\n'))

    def test_file_change_outside_is_judged_with_absolute_paths(self):
        outside = str(self.root / 'escape.txt')
        change = {'path': outside, 'kind': {'type': 'add'}, 'diff': 'x\n'}
        session, ctx = self.open({'turns': [[
            started(file_item('f1', [change])),
            {'request': 'item/fileChange/requestApproval', 'params': {'threadId': '$thread', 'turnId': '$turn', 'itemId': 'f1', 'startedAtMs': 1}},
            completed(file_item('f1', [change], status='declined')),
            {'complete': 'completed'}]]}, ctx=self.ctx(rules={'file_write': 'deny'}))
        session.run_turn('edit', ctx)
        self.assertEqual(ctx.requests[0][0]['paths'], [outside])
        self.assertEqual(self.replies()[0]['result'], {'decision': 'decline'})
        self.assertNotIn('diff', ctx.kinds())
        self.assertEqual(ctx.of('tool_result')[0]['status'], 'denied')

    def test_file_approval_without_a_known_item_is_declined(self):
        session, ctx = self.open({'turns': [[
            {'request': 'item/fileChange/requestApproval', 'params': {'threadId': '$thread', 'turnId': '$turn', 'itemId': 'zz', 'startedAtMs': 1}},
            {'complete': 'completed'}]]})
        session.run_turn('edit', ctx)
        self.assertEqual(ctx.requests, [])
        self.assertEqual(self.replies()[0]['result'], {'decision': 'decline'})

    def test_actions_reported_after_the_fact_are_observed(self):
        ws = str(self.workspace)
        session, ctx = self.open({'turns': [[
            completed(command_item('c9', 'git status', ws, status='completed', aggregatedOutput='clean', exitCode=0)),
            completed({'type': 'webSearch', 'id': 'w1', 'query': 'python dates'}),
            {'complete': 'completed'}]]})
        session.run_turn('x', ctx)
        self.assertEqual([r['category'] for r, _ in ctx.observations], ['command', 'web_search'])
        self.assertEqual(ctx.requests, [])
        self.assertEqual([c['decision']['rule'] for c in ctx.of('tool_call')], ['provider.sandbox', 'provider.sandbox'])

    def test_approved_step_without_completion_is_closed_at_turn_end(self):
        ws = str(self.workspace)
        session, ctx = self.open({'turns': [[
            started(command_item('c1', 'echo x > ../e', ws)), command_approval('c1', 'echo x > ../e', ws),
            {'complete': 'completed'}]]})
        session.run_turn('x', ctx)
        result = ctx.of('tool_result')[0]
        self.assertEqual((result['call_id'], result['status']), ('c1', 'error'))

    def test_mcp_approvals(self):
        def elicitation(server, tool, kind='mcp_tool_call'):
            return {'request': 'mcpServer/elicitation/request', 'params': {
                'threadId': '$thread', 'turnId': '$turn', 'serverName': server, 'mode': 'form',
                '_meta': {'codex_approval_kind': kind, 'tool_name': tool, 'tool_params': {'q': 1}},
                'message': 'Allow?', 'requestedSchema': {'type': 'object', 'properties': {}}}}
        mcp_item = {'type': 'mcpToolCall', 'id': 'x1', 'server': 'other', 'tool': 'lookup', 'status': 'inProgress', 'arguments': {}}
        session, ctx = self.open({'turns': [[
            elicitation('interspace', 'example_read'),
            completed({'type': 'mcpToolCall', 'id': 'i1', 'server': 'interspace', 'tool': 'example_read',
                       'status': 'completed', 'arguments': {}, 'result': {'content': []}}),
            elicitation('interspace', 'not_a_tool'),
            started(mcp_item), elicitation('other', 'lookup'),
            completed(dict(mcp_item, status='failed', error={'message': 'user rejected MCP tool call'})),
            elicitation('other', 'x', kind=None),
            {'complete': 'completed'}]]}, ctx=self.ctx(rules={'mcp': 'deny'}))
        session.run_turn('x', ctx)
        actions = [r['result']['action'] for r in self.replies()]
        self.assertEqual(actions, ['accept', 'decline', 'decline', 'decline'])
        self.assertEqual(ctx.requests, [({'category': 'mcp', 'server': 'other', 'tool': 'lookup'}, 'x1')])
        self.assertEqual([c['call_id'] for c in ctx.of('tool_call')], ['x1'])  # Interspace's own server emits nothing here.
        self.assertEqual(ctx.of('tool_result')[0]['status'], 'error')

    def test_other_server_requests_fail_closed(self):
        session, ctx = self.open({'turns': [[
            {'request': 'item/permissions/requestApproval', 'params': {'threadId': '$thread', 'turnId': '$turn', 'itemId': 'p',
                                                                      'permissions': {'network': {'enabled': True}}}},
            {'request': 'item/tool/call', 'params': {'threadId': '$thread', 'turnId': '$turn', 'callId': 'd', 'tool': 'x', 'arguments': {}}},
            {'request': 'item/tool/requestUserInput', 'params': {}},
            {'request': 'account/chatgptAuthTokens/refresh', 'params': {}},
            {'request': 'execCommandApproval', 'params': {}},
            {'request': 'currentTime/read', 'params': {}},
            {'complete': 'completed'}]]})
        session.run_turn('x', ctx)
        replies = self.replies()
        self.assertEqual(replies[0]['result'], {'permissions': {}, 'scope': 'turn'})
        self.assertFalse(replies[1]['result']['success'])
        self.assertTrue(all('error' in r for r in replies[2:5]))
        self.assertIsInstance(replies[5]['result']['currentTimeAt'], int)
        self.assertEqual(ctx.events, [])

    def test_failed_turn_maps_codex_errors(self):
        session, ctx = self.open({'turns': [[
            {'notify': 'error', 'params': {'error': {'message': 'model x unsupported', 'codexErrorInfo': 'modelNotFound'},
                                           'willRetry': False, 'threadId': '$thread', 'turnId': '$turn'}},
            {'complete': 'failed', 'error': {'message': 'model x unsupported', 'codexErrorInfo': 'modelNotFound'}}],
            [{'complete': 'failed', 'error': {'message': 'boom', 'codexErrorInfo': 'other'}}]]})
        result = session.run_turn('x', ctx)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error']['code'], 'runtime_unavailable')
        self.assertNotIn('model x', result['error']['message'])
        self.assertEqual(session.run_turn('y', ctx)['error']['code'], 'runtime_exited')

    def test_late_messages_of_another_turn_are_ignored(self):
        session, ctx = self.open({'turns': [[
            {'notify': 'item/agentMessage/delta', 'params': {'threadId': '$thread', 'turnId': 'turn-0', 'itemId': 'm', 'delta': 'old'}},
            {'notify': 'turn/completed', 'params': {'threadId': '$thread', 'turn': {'id': 'turn-0', 'status': 'interrupted'}}},
            {'complete': 'completed'}]]})
        self.assertEqual(session.run_turn('x', ctx)['status'], 'completed')
        self.assertEqual(ctx.events, [])

    def test_mcp_bridge_routes_to_this_turns_context(self):
        session, ctx = self.open({'turns': [[{'sleep': 0.5}, {'complete': 'completed'}]]})
        bridge = session.bridge
        self.assertEqual(bridge.tool_names(), ['example_read'])
        seen = []
        original = bridge._call
        bridge._call = lambda params: seen.append(bridge._ctx) or original(params)
        thread = threading.Thread(target=session.run_turn, args=('x', ctx))
        thread.start()
        time.sleep(0.2)
        bridge._call({'name': 'example_read', 'arguments': {'ref': 'r'}})
        thread.join(5)
        self.assertIs(seen[0], ctx)
        self.assertEqual(ctx.tool_calls[0][:2], ('example_read', {'ref': 'r'}))
        self.assertIsNone(bridge._ctx)  # Unbound between turns.


class StopTests(CodexCase):
    def test_interrupt_ends_the_turn_as_cancelled_and_keeps_usage(self):
        session, ctx = self.open({'turns': [[usage(500, 10), {'wait_interrupt': True}, {'complete': 'interrupted'}]]})
        thread_result = {}
        thread = threading.Thread(target=lambda: thread_result.update(session.run_turn('x', ctx)))
        thread.start()
        deadline = time.monotonic() + 5
        while not ctx.usages and time.monotonic() < deadline:
            time.sleep(0.01)
        session.interrupt()
        thread.join(5)
        self.assertEqual(thread_result['status'], 'cancelled')
        self.assertEqual(thread_result['usage']['input_tokens'], 500)
        self.assertEqual(self.sent('turn/interrupt')[0]['params'], {'threadId': 'thr-0001', 'turnId': 'turn-1'})

    def test_interrupt_before_the_turn_starts_is_sent_once_it_has_an_id(self):
        session, ctx = self.open({'turns': [[{'wait_interrupt': True}, {'complete': 'interrupted'}]]})
        session.interrupt()
        self.assertEqual(session.run_turn('x', ctx)['status'], 'cancelled')

    def test_kill_stops_the_process_group(self):
        session, ctx = self.open({'turns': [[{'sleep': 30}]]})
        result = {}
        thread = threading.Thread(target=lambda: result.update(session.run_turn('x', ctx)))
        thread.start()
        time.sleep(0.3)
        session.kill()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result['status'], 'cancelled')
        self.assertIsNotNone(session.process.poll())

    def test_process_exit_mid_turn_is_a_runtime_failure(self):
        session, ctx = self.open({'turns': [[{'exit': 1}]]})
        with self.assertRaises(runtime.RuntimeFailure) as caught:
            session.run_turn('x', ctx)
        self.assertEqual(caught.exception.code, 'runtime_exited')
        with self.assertRaises(runtime.RuntimeFailure):
            session.run_turn('again', ctx)


class ProtocolTests(CodexCase):
    def check(self, steps):
        session, ctx = self.open({'turns': [steps + [{'sleep': 5}]]})
        result = session.run_turn('x', ctx)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error']['code'], 'runtime_protocol')
        self.assertIsNotNone(session.process.poll())  # The session was killed.

    def test_garbage_line(self):
        self.check([{'raw': 'this is not json'}])

    def test_non_object(self):
        self.check([{'raw': '[1,2,3]'}])

    def test_item_without_id(self):
        self.check([started({'type': 'agentMessage', 'text': ''})])

    def test_bad_usage(self):
        self.check([{'notify': 'thread/tokenUsage/updated', 'params': {'threadId': '$thread', 'turnId': '$turn',
                                                                       'tokenUsage': {'total': {'inputTokens': -1}}}}])

    def test_bad_plan_status(self):
        self.check([{'notify': 'turn/plan/updated', 'params': {'threadId': '$thread', 'turnId': '$turn',
                                                               'plan': [{'step': 'x', 'status': 'weird'}]}}])

    def test_approval_without_item(self):
        self.check([{'request': 'item/commandExecution/requestApproval', 'params': {'threadId': '$thread', 'turnId': '$turn'}}])

    def test_unknown_notifications_are_tolerated(self):
        session, ctx = self.open({'turns': [[{'notify': 'remoteControl/status/changed', 'params': {'status': 'disabled'}},
                                             {'notify': 'brand/new/thing', 'params': {}}, {'complete': 'completed'}]]})
        self.assertEqual(session.run_turn('x', ctx)['status'], 'completed')


class FactoryTests(unittest.TestCase):
    class App:
        def __init__(self, rows):
            self.lock = threading.RLock()
            self.storage = Path(tempfile.gettempdir())
            rows = rows
            self.store = type('Store', (), {'task': staticmethod(lambda task_id: rows[task_id])})()

    def test_provider_field_picks_the_runtime(self):
        app = self.App({'a': {'id': 'a'}, 'b': {'id': 'b', 'provider': 'codex'}, 'c': {'id': 'c', 'provider': 'claude'},
                        'd': {'id': 'd', 'provider': 'gemini'}})
        factory = runtime.make_factory(app)
        first = factory('a')
        self.assertIsInstance(first, codex.CodexRuntime)
        self.assertEqual(first.name, 'codex')
        self.assertIs(factory('b'), first)
        self.assertEqual(first.codex_home, app.storage / 'codex-home')
        with mock.patch.dict(sys.modules, {runtime.__name__ + '.claude': None}):
            with self.assertRaisesRegex(ValueError, 'Claude runtime is not in this build'):
                factory('c')
        with self.assertRaisesRegex(ValueError, 'unknown agent provider'):
            factory('d')

    def test_registered_provider_is_built_from_its_registry_record(self):
        from runtime import registry
        module = type(sys)('fake_later_runtime')

        class LaterRuntime:
            name = 'later'

            def __init__(self, app):
                self.app = app
        module.LaterRuntime = LaterRuntime
        registry.register(dict(registry.get('codex'), name='later', title='Later',
                               runtime='fake_later_runtime:LaterRuntime'))
        self.addCleanup(registry.unregister, 'later')
        app = self.App({'l': {'id': 'l', 'provider': 'later'}})
        with mock.patch.dict(sys.modules, {'fake_later_runtime': module}):
            made = runtime.make_factory(app)('l')
        self.assertIsInstance(made, LaterRuntime)
        self.assertIs(made.app, app)
        self.assertFalse(hasattr(runtime, 'PROVIDERS'))  # The registry is the only provider list.

    def test_claude_runtime_is_imported_when_present(self):
        made = []

        class ClaudeRuntime:
            name = 'claude'

            def __init__(self, app):
                made.append(app)
        module = type(sys)('claude')
        module.ClaudeRuntime = ClaudeRuntime
        app = self.App({'c': {'id': 'c', 'provider': 'claude'}})
        with mock.patch.dict(sys.modules, {runtime.__name__ + '.claude': module}):
            result = runtime.make_factory(app)('c')
        self.assertEqual((result.name, made), ('claude', [app]))

class UnwrapTests(unittest.TestCase):
    def test_unwrap_shell(self):
        self.assertEqual(codex.unwrap_shell("/bin/zsh -lc 'ls -a'"), 'ls -a')
        self.assertEqual(codex.unwrap_shell('bash -c "a && b"'), 'a && b')
        self.assertEqual(codex.unwrap_shell('python3 -c "x"'), 'python3 -c "x"')
        self.assertEqual(codex.unwrap_shell("unbalanced 'quote"), "unbalanced 'quote")

    def test_toml_values(self):
        self.assertEqual(codex._toml({'a': True, 'b': {'c': 'd"e'}, 'n': 0}), '{"a"=true, "b"={"c"="d\\"e"}, "n"=0}')


if __name__ == '__main__':
    unittest.main()
