"""Claude Code runtime adapter, against a fake `claude` CLI (no real CLI, sign-in, model call or network)."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / 'app' / 'backend') not in sys.path:
    # Appended, not prepended, so the tests folder keeps priority under discovery.
    sys.path.append(str(ROOT / 'app' / 'backend'))


def _load_adapter():
    # Under `discover -s tests` the name `runtime` is this test package, so load the adapter by path.
    path = ROOT / 'app' / 'backend' / 'runtime' / 'claude.py'
    spec = importlib.util.spec_from_file_location('interspace_runtime_claude', str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


claude = _load_adapter()

FAKE = Path(__file__).resolve().parent / 'fixtures' / 'claude' / 'fake_claude.py'
MODEL = claude.DEFAULT_MODEL


def assistant_text(text, message_id='msg_1'):
    return {'emit': {'type': 'assistant', 'parent_tool_use_id': None, 'session_id': 's1',
                     'message': {'id': message_id, 'role': 'assistant', 'model': '$MODEL',
                                 'content': [{'type': 'text', 'text': text}]}}}


def model_usage(model='$MODEL', inp=100, out=20, read=1000, create=50):
    return {model: {'inputTokens': inp, 'outputTokens': out, 'cacheReadInputTokens': read,
                    'cacheCreationInputTokens': create, 'costUSD': 0.5, 'webSearchRequests': 0}}


def result(subtype='success', is_error=False, usage=None, **extra):
    message = {'type': 'result', 'subtype': subtype, 'is_error': is_error, 'session_id': 's1', 'num_turns': 1,
               'result': 'done', 'total_cost_usd': 0.5, 'permission_denials': [],
               'usage': {'input_tokens': 100, 'cache_creation_input_tokens': 50, 'cache_read_input_tokens': 1000,
                         'output_tokens': 20},
               'modelUsage': model_usage() if usage is None else usage}
    message.update(extra)
    return {'emit': message}


INIT = {'init': {}}


def simple_turn(text='Hello.'):
    return [INIT, assistant_text(text), result()]


class FakeContext:
    def __init__(self, root, decisions=None, model=None):
        self.task_id = 'task1'
        self.turn_id = 't-1'
        self.project_ids = ['p1', 'p2']
        self.workspaces = {'p1': str(root / 'ws1'), 'p2': str(root / 'ws2')}
        for path in self.workspaces.values():
            os.makedirs(path, exist_ok=True)
        self.primary_workspace = self.workspaces['p1']
        self.scope = {'version': 1}
        self.model = model
        self.cancel = threading.Event()
        self.decisions = decisions or {}
        self.authorized = []
        self.events = []
        self.tool_calls = []
        self.tool_list = []
        self.lock = threading.Lock()

    def tools(self):
        return list(self.tool_list)

    def authorize(self, request, call_id):
        with self.lock:
            self.authorized.append((request, call_id))
        decision = self.decisions.get(request['category'], 'allow')
        return {'decision': decision, 'rule': 'fake.' + decision, 'reason': '', 'scope_version': 1,
                'scope_digest': 'sha256:x'}

    def emit(self, kind, data, *, turn_id=None, item_id=None):
        json.dumps(data)  # Events must be JSON.
        with self.lock:
            self.events.append((kind, data, item_id))

    def call_tool(self, name, arguments, call_id):
        with self.lock:
            self.tool_calls.append((name, arguments, call_id))
        return {'ok': True, 'result': {'title': 'Example item'}}

    def report_usage(self, usage):
        pass

    def kinds(self):
        return [kind for kind, _, _ in self.events]


class FakeBridge:
    """Stands in for 2A's `mcp_bridge.start(tools)`: a token-checked unix socket the fake CLI calls.

    Like the real bridge, it runs each call through the bound turn's `ctx.call_tool` with its own call_id.
    """
    TOKEN = 'tok-' + 'f' * 32

    def __init__(self, root, tools):
        self.path = str(root / 'bridge.sock')
        self.tools = tools
        self.ctx = None
        self.bound = []
        self.stopped = False
        self.server = {'name': 'interspace', 'command': sys.executable, 'args': ['-I', '/fake/mcp_bridge.py'],
                       'env': {'INTERSPACE_MCP_SOCKET': self.path, 'INTERSPACE_MCP_TOKEN': self.TOKEN,
                               'FAKE_TOOLS': ','.join(t['name'] for t in tools)}}
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(self.path)
        self.listener.listen(4)
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            data = b''
            while not data.endswith(b'\n'):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
            call = json.loads(data)
            if call.get('token') != self.TOKEN or self.ctx is None:
                reply = {'ok': False, 'error': {'code': 'invalid_request', 'message': 'not bound'}}
            else:
                reply = self.ctx.call_tool(call['name'], call['arguments'], 'mcp_' + 'a' * 32)
            conn.sendall((json.dumps(reply) + '\n').encode())
            conn.close()

    def bind(self, ctx):
        self.ctx = ctx
        self.bound.append(ctx)

    def unbind(self):
        self.ctx = None

    def stop(self):
        self.stopped = True
        self.listener.close()


class ClaudeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(os.path.realpath(self.tmp.name))
        self.log = self.root / 'log.jsonl'
        self.bridges = []

    def runtime(self, scenario, bridge=False, **options):
        path = self.root / 'scenario.json'
        path.write_text(json.dumps(scenario))
        binary = self.root / 'bin' / 'claude'
        binary.parent.mkdir(exist_ok=True)
        binary.write_text('#!/bin/sh\nexec %s %s %s %s "$@"\n' % tuple(
            shlex.quote(str(p)) for p in (sys.executable, FAKE, path, self.log)))
        binary.chmod(0o755)
        def factory(tools):
            made = FakeBridge(self.root, tools)
            self.bridges.append(made)
            return made
        options['bridge_factory'] = factory
        options.setdefault('interrupt_grace_s', 1.0)
        return claude.ClaudeRuntime(object(), binary=str(binary), **options)

    def entries(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def launches(self):
        return [e for e in self.entries() if 'launch' in e]

    def main_launches(self):
        return [e for e in self.launches() if e['launch'][:2] != ['auth', 'status']]

    def stdin(self):
        return [e['stdin'] for e in self.entries() if 'stdin' in e]

    def answers(self):
        return [e['answer'] for e in self.entries() if 'answer' in e]

    def turn(self, scenario, ctx=None, text='Summarise the notes.', bridge=False, **options):
        ctx = ctx or FakeContext(self.root)
        if bridge:
            ctx.tool_list = [{'name': 'example_get', 'effect': 'read', 'input_schema': {}}]
        runtime = self.runtime(scenario, bridge=bridge, **options)
        session = runtime.open(ctx)
        self.addCleanup(session.close)
        return session, ctx, session.run_turn(text, ctx)


class LaunchTests(ClaudeCase):
    def test_flags_are_explicit_and_never_bypass(self):
        os.environ['ANTHROPIC_API_KEY'] = 'sk-should-never-pass'
        self.addCleanup(os.environ.pop, 'ANTHROPIC_API_KEY', None)
        session, ctx, outcome = self.turn({'turns': [simple_turn()]})
        self.assertEqual(outcome['status'], 'completed', outcome)
        launch = self.main_launches()[0]
        args = launch['launch']
        for flag in ('-p', '--verbose', '--safe-mode', '--strict-mcp-config', '--disable-slash-commands',
                     '--no-session-persistence'):
            self.assertIn(flag, args)
        pairs = {args[i]: args[i + 1] for i in range(len(args) - 1)}
        self.assertEqual(pairs['--input-format'], 'stream-json')
        self.assertEqual(pairs['--output-format'], 'stream-json')
        self.assertEqual(pairs['--model'], 'claude-sonnet-5-5')
        self.assertEqual(pairs['--permission-mode'], 'manual')
        self.assertEqual(pairs['--permission-prompt-tool'], 'stdio')
        self.assertEqual(pairs['--permission-prompts'], 'host')
        self.assertEqual(pairs['--setting-sources'], '')
        self.assertEqual(pairs['--tools'], ','.join(claude.TOOLS))
        self.assertEqual(pairs['--add-dir'], ctx.workspaces['p2'])
        settings = json.loads(pairs['--settings'])
        self.assertTrue(settings['disableAllHooks'])
        self.assertEqual(settings['permissions']['allow'], [])
        self.assertTrue(set(claude.TOOLS) <= set(settings['permissions']['ask']))
        self.assertFalse(settings['sandbox']['autoAllowBashIfSandboxed'])
        self.assertFalse(settings['sandbox']['allowUnsandboxedCommands'])
        joined = ' '.join(args)
        for bad in ('dangerously', 'bypassPermissions', '--bare', 'dontAsk', '--resume', '--continue',
                    '--fallback-model', 'setup-token'):
            self.assertNotIn(bad, joined)
        self.assertNotIn('--mcp-config', args)  # No bridge was given.
        self.assertEqual(launch['cwd'], ctx.primary_workspace)
        self.assertNotEqual(launch['pgid'], os.getpgid(0))  # Own process group.
        for entry in self.launches():
            env = entry['env']
            self.assertNotIn('ANTHROPIC_API_KEY', env)
            # /bin/sh and Python's locale coercion add the extras below; nothing else reaches the CLI.
            shell = {'PWD', 'SHLVL', '_', '__CF_USER_TEXT_ENCODING', 'OLDPWD', 'LC_CTYPE'}
            self.assertTrue(set(env) - shell <= set(claude.ENV_ALLOWLIST), env.keys())
        self.assertEqual(set(claude.child_env()), {k for k in claude.ENV_ALLOWLIST if k in os.environ})

    def test_each_session_gets_its_own_tmpdir_in_the_workspace(self):
        ctx = FakeContext(self.root)
        os.makedirs(os.path.join(ctx.primary_workspace, '.git', 'info'))
        self.turn({'turns': [simple_turn()]}, ctx=ctx)
        tmp = os.path.join(ctx.primary_workspace, '.interspace', 'tmp')
        self.assertEqual(self.main_launches()[0]['env']['TMPDIR'], tmp)
        self.assertTrue(os.path.isdir(tmp))
        exclude = Path(ctx.primary_workspace, '.git', 'info', 'exclude').read_text().splitlines()
        self.assertEqual(exclude.count('/.interspace/'), 1)
        self.turn({'turns': [simple_turn()]}, ctx=ctx)  # A second launch does not repeat the line.
        exclude = Path(ctx.primary_workspace, '.git', 'info', 'exclude').read_text().splitlines()
        self.assertEqual(exclude.count('/.interspace/'), 1)
        # `claude auth status` keeps the user's own TMPDIR.
        auth = [e for e in self.launches() if e['launch'][:2] == ['auth', 'status']][0]
        self.assertNotEqual(auth['env'].get('TMPDIR'), tmp)

    def test_cli_reports_manual_mode_as_default(self):
        _, _, outcome = self.turn({'turns': [simple_turn()]})
        self.assertEqual(outcome['status'], 'completed', outcome)  # The fake reports "default", like 2.1.322.
        self.assertEqual(claude.REPORTED_PERMISSION_MODES, ('manual', 'default'))

    def test_initialize_then_user_message(self):
        self.turn({'turns': [simple_turn()]}, text='Hello there')
        sent = self.stdin()
        self.assertEqual(sent[0]['type'], 'control_request')
        self.assertEqual(sent[0]['request']['subtype'], 'initialize')
        self.assertEqual(sent[1]['type'], 'user')
        self.assertEqual(sent[1]['message'], {'role': 'user', 'content': [{'type': 'text', 'text': 'Hello there'}]})

    def test_model_from_context(self):
        ctx = FakeContext(self.root, model='claude-opus-5-5')
        _, _, outcome = self.turn({'turns': [simple_turn()]}, ctx=ctx)
        self.assertEqual(outcome['status'], 'completed', outcome)
        args = self.main_launches()[0]['launch']
        self.assertEqual(args[args.index('--model') + 1], 'claude-opus-5-5')

    def test_unknown_model_fails_before_launch(self):
        for model in ('sonnet', 'claude-sonnet-4-5', 'gpt-6'):
            self.log.unlink(missing_ok=True)
            ctx = FakeContext(self.root, model=model)
            _, _, outcome = self.turn({'turns': [simple_turn()]}, ctx=ctx)
            self.assertEqual(outcome['status'], 'failed')
            self.assertEqual(outcome['error']['code'], 'runtime_unavailable')
            self.assertEqual(self.main_launches(), [])

    def test_bridge_config_is_the_only_mcp(self):
        session, ctx, outcome = self.turn({'turns': [simple_turn()]}, bridge=True)
        self.assertEqual(outcome['status'], 'completed', outcome)
        args = self.main_launches()[0]['launch']
        path = args[args.index('--mcp-config') + 1]
        self.assertIn('--strict-mcp-config', args)
        self.assertNotIn(FakeBridge.TOKEN, ' '.join(args))  # The token stays out of argv.
        logged = [e for e in self.entries() if 'mcp_config' in e][0]
        self.assertEqual(logged['mode'], '0o600')
        server = logged['mcp_config']['mcpServers']['interspace']
        self.assertEqual(list(logged['mcp_config']['mcpServers']), ['interspace'])
        self.assertEqual(server['type'], 'stdio')
        self.assertEqual(server['args'], ['-I', '/fake/mcp_bridge.py'])
        self.assertEqual(server['env']['INTERSPACE_MCP_TOKEN'], FakeBridge.TOKEN)
        self.assertEqual(self.bridges[0].tools, ctx.tool_list)
        self.assertEqual(self.bridges[0].bound, [ctx])
        self.assertIsNone(self.bridges[0].ctx)  # Unbound after the turn.
        session.close()
        self.assertTrue(self.bridges[0].stopped)
        self.assertFalse(os.path.exists(path))

    def test_no_tools_no_bridge(self):
        _, _, outcome = self.turn({'turns': [simple_turn()]})
        self.assertEqual(outcome['status'], 'completed', outcome)
        self.assertEqual(self.bridges, [])


class AuthTests(ClaudeCase):
    def test_only_claude_ai_subscription_runs(self):
        for method in ('api_key', 'api_key_helper', 'oauth_token', 'third_party', 'none'):
            self.log.unlink(missing_ok=True)
            auth = {'exit': 0, 'stdout': json.dumps({'loggedIn': True, 'authMethod': method, 'email': 'x@y.z'})}
            _, ctx, outcome = self.turn({'auth': auth, 'turns': [simple_turn()]})
            self.assertEqual(outcome['status'], 'failed', method)
            self.assertEqual(outcome['error']['code'], 'runtime_unavailable')
            self.assertIn('Claude subscription', outcome['error']['message'])
            self.assertNotIn('x@y.z', json.dumps(outcome))
            self.assertEqual(self.main_launches(), [])
            self.assertEqual(ctx.events, [])

    def test_signed_out_or_garbled_status_fails(self):
        for auth in ({'exit': 1, 'stdout': json.dumps({'loggedIn': False, 'authMethod': 'none'})},
                     {'exit': 0, 'stdout': 'not json'},
                     {'exit': 0, 'stdout': json.dumps(['claude.ai'])}):
            self.log.unlink(missing_ok=True)
            _, _, outcome = self.turn({'auth': auth, 'turns': [simple_turn()]})
            self.assertEqual(outcome['status'], 'failed')
            self.assertEqual(outcome['error']['code'], 'runtime_unavailable')
            self.assertEqual(self.main_launches(), [])

    def test_auth_is_rechecked_each_turn(self):
        runtime = self.runtime({'turns': [simple_turn(), simple_turn()]})
        ctx = FakeContext(self.root)
        session = runtime.open(ctx)
        self.addCleanup(session.close)
        self.assertEqual(session.run_turn('one', ctx)['status'], 'completed')
        self.assertEqual(session.run_turn('two', ctx)['status'], 'completed')
        auth = [e for e in self.launches() if e['launch'][:2] == ['auth', 'status']]
        self.assertEqual(len(auth), 2)
        self.assertEqual(len(self.main_launches()), 1)  # One process holds the conversation.

    def test_missing_binary(self):
        runtime = claude.ClaudeRuntime(object(), binary=str(self.root / 'nope'))
        ctx = FakeContext(self.root)
        outcome = runtime.open(ctx).run_turn('hi', ctx)
        self.assertEqual(outcome['status'], 'failed')
        self.assertEqual(outcome['error']['code'], 'runtime_unavailable')


class SignInTests(ClaudeCase):
    """`auth_status` and `begin_sign_in` (multi-provider/providers.md): the user's own `claude` login."""

    def status(self, auth):
        binary = self.runtime({'auth': auth}).binary
        with mock.patch.object(claude, 'find_claude', lambda: binary):
            return claude.ClaudeRuntime.auth_status(object())

    def test_signed_in_with_subscription(self):
        status = self.status({'exit': 0, 'stdout': json.dumps({'loggedIn': True, 'authMethod': 'claude.ai',
                                                                'email': 'person@example.com', 'orgId': 'org-1'})})
        self.assertEqual(status, {'provider': 'claude', 'state': 'signed_in', 'account': 'Claude subscription',
                                  'detail': 'Claude Code is signed in with your Claude subscription.'})
        self.assertNotIn('example.com', json.dumps(status))

    def test_signed_out_other_method_and_errors(self):
        self.assertEqual(self.status({'exit': 1, 'stdout': json.dumps({'loggedIn': False})})['state'], 'signed_out')
        self.assertEqual(self.status({'exit': 1, 'stdout': 'Not logged in'})['state'], 'signed_out')
        other = self.status({'exit': 0, 'stdout': json.dumps({'loggedIn': True, 'authMethod': 'api_key'})})
        self.assertEqual(other['state'], 'signed_out')
        self.assertIn('claude auth login', other['detail'])
        self.assertNotIn('api_key', json.dumps(other))
        self.assertEqual(self.status({'exit': 0, 'stdout': 'garbled'})['state'], 'error')

    def test_missing_cli(self):
        with mock.patch.object(claude, 'find_claude', lambda: None):
            self.assertEqual(claude.ClaudeRuntime.auth_status(object())['state'], 'missing_cli')
            with self.assertRaises(ValueError):
                claude.ClaudeRuntime.begin_sign_in(object())

    def test_sign_in_is_a_terminal_instruction(self):
        binary = self.runtime({}).binary
        with mock.patch.object(claude, 'find_claude', lambda: binary):
            started = claude.ClaudeRuntime.begin_sign_in(object())
        self.assertEqual(started['kind'], 'terminal')
        self.assertEqual(started['command'], 'claude auth login')
        self.assertEqual(started['provider'], 'claude')
        self.assertEqual(self.launches(), [])  # Nothing is run for the user.


class TurnTests(ClaudeCase):
    def test_message_events_and_usage(self):
        _, ctx, outcome = self.turn({'turns': [simple_turn('I read the notes.')]})
        self.assertEqual(outcome, {'status': 'completed', 'error': None, 'usage': {
            'input_tokens': 100, 'cache_creation_input_tokens': 50, 'cache_read_input_tokens': 1000,
            'output_tokens': 20}})
        messages = [data for kind, data, _ in ctx.events if kind == 'message']
        self.assertEqual(messages, [{'role': 'assistant', 'text': 'I read the notes.', 'final': True}])
        self.assertNotIn('cost', json.dumps(outcome).lower())

    def test_usage_sums_models_and_falls_back(self):
        self.assertEqual(claude.turn_usage({'modelUsage': {'a': {'inputTokens': 1, 'outputTokens': 2,
                                                                 'cacheReadInputTokens': 3, 'cacheCreationInputTokens': 4},
                                                           'b': {'inputTokens': 10, 'outputTokens': 20,
                                                                 'cacheReadInputTokens': 30, 'cacheCreationInputTokens': 40}}}),
                         {'input_tokens': 11, 'output_tokens': 22, 'cache_read_input_tokens': 33,
                          'cache_creation_input_tokens': 44})
        fallback = {'input_tokens': 1, 'output_tokens': 2, 'cache_read_input_tokens': 3, 'cache_creation_input_tokens': 4}
        self.assertEqual(claude.turn_usage({'usage': dict(fallback, server_tool_use={'web_search_requests': 2})}), fallback)
        for bad in ({}, {'modelUsage': {'a': {'inputTokens': 1}}}, {'modelUsage': {'a': {'inputTokens': -1, 'outputTokens': 2,
                    'cacheReadInputTokens': 3, 'cacheCreationInputTokens': 4}}},
                    {'modelUsage': {'a': {'inputTokens': 1.5, 'outputTokens': 2, 'cacheReadInputTokens': 3,
                                          'cacheCreationInputTokens': 4}}},
                    {'modelUsage': []}, {'usage': {'input_tokens': 1, 'output_tokens': True,
                                                   'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}}):
            self.assertIsNone(claude.turn_usage(bad), bad)

    def test_cumulative_model_usage_is_charged_per_turn(self):
        def totals(inp, out, read, create):
            return model_usage(inp=inp, out=out, read=read, create=create)
        scenario = {'turns': [[INIT, assistant_text('one'), result(usage=totals(80, 40, 1000, 50))],
                              [assistant_text('two'), result(usage=totals(90, 45, 1500, 50))]]}
        ctx = FakeContext(self.root)
        runtime = self.runtime(scenario)
        session = runtime.open(ctx)
        self.addCleanup(session.close)
        first = session.run_turn('one', ctx)
        second = session.run_turn('two', ctx)
        self.assertEqual(first['usage'], {'input_tokens': 80, 'output_tokens': 40, 'cache_read_input_tokens': 1000,
                                          'cache_creation_input_tokens': 50})
        self.assertEqual(second['usage'], {'input_tokens': 10, 'output_tokens': 5, 'cache_read_input_tokens': 500,
                                           'cache_creation_input_tokens': 0})

    def test_turn_usage_takes_the_growth_or_falls_back_to_the_turn(self):
        previous = {'input_tokens': 80, 'output_tokens': 40, 'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}
        message = {'modelUsage': {'m': {'inputTokens': 90, 'outputTokens': 45, 'cacheReadInputTokens': 0,
                                        'cacheCreationInputTokens': 0}},
                   'usage': {'input_tokens': 10, 'output_tokens': 5, 'cache_read_input_tokens': 0,
                             'cache_creation_input_tokens': 0}}
        self.assertEqual(claude.turn_usage(message, previous)['input_tokens'], 10)
        # A total that shrank (a new process the session did not see) falls back to the turn's own usage.
        shrunk = dict(previous, input_tokens=500)
        self.assertEqual(claude.turn_usage(message, shrunk), message['usage'])

    def test_error_result_fails_with_usage(self):
        _, _, outcome = self.turn({'turns': [[INIT, result('error_max_turns', True)]]})
        self.assertEqual(outcome['status'], 'failed')
        self.assertEqual(outcome['error']['code'], 'runtime_exited')
        self.assertEqual(outcome['usage']['output_tokens'], 20)

    def test_other_model_in_usage_fails_closed(self):
        usage = dict(model_usage(), **model_usage('claude-haiku-5-5', 1, 1, 0, 0))
        _, _, outcome = self.turn({'turns': [[INIT, result(usage=usage)]]})
        self.assertEqual(outcome['status'], 'failed')
        self.assertEqual(outcome['error']['code'], 'runtime_protocol')
        self.assertEqual(outcome['usage']['input_tokens'], 101)  # Spent tokens are still reported.

    def test_reasoning_event(self):
        thinking = {'emit': {'type': 'assistant', 'parent_tool_use_id': None, 'session_id': 's1',
                             'message': {'id': 'm', 'role': 'assistant', 'model': '$MODEL',
                                         'content': [{'type': 'thinking', 'thinking': 'Check the notes first.'}]}}}
        _, ctx, outcome = self.turn({'turns': [[INIT, thinking, result()]]})
        self.assertEqual(outcome['status'], 'completed', outcome)
        self.assertIn(('reasoning', {'text': 'Check the notes first.'}), [(k, d) for k, d, _ in ctx.events])

    def test_ignored_and_retry_messages(self):
        steps = [INIT, {'emit': {'type': 'system', 'subtype': 'api_retry', 'attempt': 1}},
                 {'emit': {'type': 'rate_limit_event', 'rate_limit_info': {'status': 'allowed'}}},
                 assistant_text('ok'), result()]
        _, ctx, outcome = self.turn({'turns': [steps]})
        self.assertEqual(outcome['status'], 'completed', outcome)
        self.assertNotIn('rate_limit', json.dumps(ctx.events))

    def test_cancel_before_turn_does_not_launch(self):
        ctx = FakeContext(self.root)
        ctx.cancel.set()
        _, _, outcome = self.turn({'turns': [simple_turn()]}, ctx=ctx)
        self.assertEqual(outcome['status'], 'cancelled')
        self.assertEqual(self.main_launches(), [])

    def test_unknown_control_request_is_refused(self):
        steps = [INIT, {'control': {'subtype': 'request_user_dialog', 'title': 'x'}}, assistant_text('ok'), result()]
        _, _, outcome = self.turn({'turns': [steps]})
        self.assertEqual(outcome['status'], 'completed', outcome)
        answer = [e['control_answer'] for e in self.entries() if 'control_answer' in e][0]
        self.assertEqual(answer['subtype'], 'error')


class PermissionTests(ClaudeCase):
    def ask(self, tool, tool_input, tool_use_id='toolu_1', **extra):
        return {'ask': dict({'tool_name': tool, 'input': tool_input, 'tool_use_id': tool_use_id}, **extra)}

    def test_read_goes_through_authorize(self):
        steps = [INIT, self.ask('Read', {'file_path': 'notes/a.md'}, result='line 1'), assistant_text('ok'), result()]
        _, ctx, outcome = self.turn({'turns': [steps]})
        self.assertEqual(outcome['status'], 'completed', outcome)
        self.assertEqual(ctx.authorized, [({'category': 'file_read', 'project_id': 'p1', 'path': 'notes/a.md'}, 'toolu_1')])
        self.assertEqual(self.answers(), [{'behavior': 'allow', 'updatedInput': {'file_path': 'notes/a.md'}}])
        call = [d for k, d, _ in ctx.events if k == 'tool_call'][0]
        self.assertEqual(call['category'], 'file_read')
        self.assertEqual(call['tool'], 'Read')
        self.assertEqual(call['decision'], {'decision': 'allow', 'rule': 'fake.allow', 'scope_version': 1})
        done = [d for k, d, _ in ctx.events if k == 'tool_result'][0]
        self.assertEqual(done['status'], 'ok')
        self.assertEqual(done['output']['text'], 'line 1')
        self.assertEqual(ctx.kinds(), ['tool_call', 'tool_result', 'message'])

    def test_paths_in_other_workspaces_and_searches(self):
        ctx = FakeContext(self.root)
        other = os.path.join(ctx.workspaces['p2'], 'src', 'x.py')
        steps = [INIT, self.ask('Read', {'file_path': other}, 'toolu_1'),
                 self.ask('Grep', {'pattern': 'def ', 'path': 'src'}, 'toolu_2'),
                 self.ask('Glob', {'pattern': '**/*.md'}, 'toolu_3'),
                 self.ask('WebSearch', {'query': 'python dates'}, 'toolu_4'), result()]
        _, ctx, outcome = self.turn({'turns': [steps]}, ctx=ctx)
        self.assertEqual(outcome['status'], 'completed', outcome)
        self.assertEqual([r for r, _ in ctx.authorized], [
            {'category': 'file_read', 'project_id': 'p2', 'path': other},
            {'category': 'file_read', 'project_id': 'p1', 'path': 'src'},
            {'category': 'file_read', 'project_id': 'p1', 'path': '.'},
            {'category': 'web_search', 'query': 'python dates'}])

    def test_denied_by_policy(self):
        ctx = FakeContext(self.root, decisions={'file_read': 'deny'})
        steps = [INIT, self.ask('Read', {'file_path': 'secret.txt'}), result()]
        _, ctx, outcome = self.turn({'turns': [steps]}, ctx=ctx)
        self.assertEqual(outcome['status'], 'completed', outcome)
        self.assertEqual(self.answers()[0]['behavior'], 'deny')
        results = [d for k, d, _ in ctx.events if k == 'tool_result']
        self.assertEqual([r['status'] for r in results], ['denied'])  # The CLI's own error result is not repeated.

    def test_read_access_denies_writes_before_authorize(self):
        ctx = FakeContext(self.root)
        ctx.access = 'read'
        steps = [INIT, self.ask('Edit', {'file_path': 'a.py', 'old_string': 'a', 'new_string': 'b'}, 'toolu_1'),
                 self.ask('Write', {'file_path': 'b.py', 'content': 'x'}, 'toolu_2'),
                 self.ask('NotebookEdit', {'notebook_path': 'n.ipynb', 'new_source': 'x'}, 'toolu_3'),
                 self.ask('Bash', {'command': 'rm -rf build'}, 'toolu_4'),
                 self.ask('Bash', {'command': 'ls | sh'}, 'toolu_5'),
                 self.ask('Bash', {'command': 'find . -delete'}, 'toolu_6'),
                 self.ask('Bash', {'command': 'git -c core.pager=x log'}, 'toolu_7'),
                 self.ask('Bash', {'command': 'ls', 'run_in_background': True}, 'toolu_8'),
                 self.ask('Bash', {'command': 'ls', 'dangerouslyDisableSandbox': True}, 'toolu_9'),
                 self.ask('Bash', {'command': 'echo hi > out.txt'}, 'toolu_10'),
                 self.ask('Bash', {'command': 'git commit -m x'}, 'toolu_11'),
                 result()]
        _, ctx, outcome = self.turn({'turns': [steps]}, ctx=ctx)
        self.assertEqual(outcome['status'], 'completed', outcome)
        self.assertEqual(ctx.authorized, [])
        self.assertTrue(all(a['behavior'] == 'deny' for a in self.answers()))
        self.assertEqual(len(self.answers()), 11)
        calls = [d for k, d, _ in ctx.events if k == 'tool_call']
        self.assertEqual({c['decision']['rule'] for c in calls}, {'provider.claude_readonly'})
        self.assertEqual(calls[0]['category'], 'file_write')
        self.assertEqual(calls[3]['category'], 'command')
        self.assertEqual([d['status'] for k, d, _ in ctx.events if k == 'tool_result'], ['denied'] * 11)

    def test_read_only_commands_go_through_authorize(self):
        steps = [INIT, self.ask('Bash', {'command': 'ls -la src'}, 'toolu_1'),
                 self.ask('Bash', {'command': 'git log --oneline -5'}, 'toolu_2'),
                 self.ask('Bash', {'command': 'env LC_ALL=C grep -rn todo .'}, 'toolu_3'), result()]
        _, ctx, outcome = self.turn({'turns': [steps]})
        self.assertEqual(outcome['status'], 'completed', outcome)
        self.assertEqual([r for r, _ in ctx.authorized], [
            {'category': 'command', 'argv': ['ls', '-la', 'src'], 'command': None, 'cwd': '.', 'sandbox': 'workspace',
             'network': False, 'project_id': 'p1'},
            {'category': 'command', 'argv': ['git', 'log', '--oneline', '-5'], 'command': None, 'cwd': '.',
             'sandbox': 'workspace', 'network': False, 'project_id': 'p1'},
            {'category': 'command', 'argv': ['env', 'LC_ALL=C', 'grep', '-rn', 'todo', '.'], 'command': None, 'cwd': '.',
             'sandbox': 'workspace', 'network': False, 'project_id': 'p1'}])
        self.assertTrue(all(a['behavior'] == 'allow' for a in self.answers()))

    def test_read_only_switch_forces_read_access(self):
        self.assertFalse(claude.READ_ONLY)
        self.assertEqual(claude.READ_ONLY_RULE, 'provider.claude_readonly')
        original = claude.READ_ONLY
        claude.READ_ONLY = True
        self.addCleanup(setattr, claude, 'READ_ONLY', original)
        steps = [INIT, self.ask('Edit', {'file_path': 'a.py', 'old_string': 'a', 'new_string': 'b'}), result()]
        _, ctx, outcome = self.turn({'turns': [steps]})  # The context asks for write access.
        self.assertEqual(outcome['status'], 'completed', outcome)
        self.assertEqual(ctx.authorized, [])
        self.assertEqual([d['decision']['rule'] for k, d, _ in ctx.events if k == 'tool_call'], ['provider.claude_readonly'])
        prompt = dict(zip(self.main_launches()[0]['launch'], self.main_launches()[0]['launch'][1:]))['--system-prompt']
        self.assertIn('read-only', prompt)

    def test_write_mode_is_the_default(self):
        ctx = FakeContext(self.root)
        self.assertFalse(hasattr(ctx, 'access'))  # Run contexts before 1B's `access` field mean write.
        edit = {'file_path': 'src/a.py', 'old_string': 'a', 'new_string': 'b'}
        normalised = dict(edit, replace_all=False)
        steps = [INIT, self.ask('Edit', edit, 'toolu_1', request_input=normalised),
                 self.ask('Write', {'file_path': os.path.join(ctx.workspaces['p1'], 'new', 'deep', 'b.py'),
                                    'content': 'x'}, 'toolu_2'),
                 self.ask('NotebookEdit', {'notebook_path': 'n.ipynb', 'new_source': 'x'}, 'toolu_3'),
                 self.ask('Write', {'file_path': os.path.join(ctx.workspaces['p2'], 'c.txt'), 'content': 'y'}, 'toolu_4'),
                 self.ask('Bash', {'command': 'echo hi > out.txt'}, 'toolu_5'),
                 result()]
        _, ctx, outcome = self.turn({'turns': [steps]}, ctx=ctx)
        self.assertEqual(outcome['status'], 'completed', outcome)
        ws1, ws2 = ctx.workspaces['p1'], ctx.workspaces['p2']
        self.assertEqual([r for r, _ in ctx.authorized], [
            {'category': 'file_write', 'project_id': 'p1', 'paths': [os.path.join(ws1, 'src', 'a.py')]},
            {'category': 'file_write', 'project_id': 'p1', 'paths': [os.path.join(ws1, 'new', 'deep', 'b.py')]},
            {'category': 'file_write', 'project_id': 'p1', 'paths': [os.path.join(ws1, 'n.ipynb')]},
            {'category': 'file_write', 'project_id': 'p2', 'paths': [os.path.join(ws2, 'c.txt')]},
            {'category': 'command', 'argv': None, 'command': 'echo hi > out.txt', 'cwd': '.', 'sandbox': 'workspace',
             'network': False, 'project_id': 'p1'}])
        answers = self.answers()
        self.assertTrue(all(a['behavior'] == 'allow' for a in answers))
        # The exact input the CLI asked about is echoed back, never the model's tool_use input.
        self.assertEqual(answers[0]['updatedInput'], normalised)
        prompt = dict(zip(self.main_launches()[0]['launch'], self.main_launches()[0]['launch'][1:]))['--system-prompt']
        self.assertIn('edit files', prompt)
        self.assertNotIn('read-only', prompt)

    def test_role_instructions_are_added_to_the_system_prompt(self):
        ctx = FakeContext(self.root)
        ctx.instructions = 'You are the Orchestrator of an Interspace task.\nRoles: researcher (read)'
        _, ctx, outcome = self.turn({'turns': [[INIT, result()]]}, ctx=ctx)
        self.assertEqual(outcome['status'], 'completed', outcome)
        prompt = dict(zip(self.main_launches()[0]['launch'], self.main_launches()[0]['launch'][1:]))['--system-prompt']
        self.assertTrue(prompt.startswith('You are an agent working inside Interspace'))
        self.assertTrue(prompt.endswith('\n\n' + ctx.instructions))

    def test_read_access_from_the_context_keeps_the_session_read_only(self):
        ctx = FakeContext(self.root)
        ctx.access = 'read'
        steps = [INIT, self.ask('Edit', {'file_path': 'a.py', 'old_string': 'a', 'new_string': 'b'}, 'toolu_1'),
                 self.ask('Bash', {'command': 'git status'}, 'toolu_2'), result()]
        _, ctx, outcome = self.turn({'turns': [steps]}, ctx=ctx)
        self.assertEqual(outcome['status'], 'completed', outcome)
        # Only the read-only command reaches the scope; the edit is refused before it.
        self.assertEqual([r['category'] for r, _ in ctx.authorized], ['command'])
        self.assertEqual([d['decision']['rule'] for k, d, _ in ctx.events if k == 'tool_call'][0],
                         'provider.claude_readonly')
        prompt = dict(zip(self.main_launches()[0]['launch'], self.main_launches()[0]['launch'][1:]))['--system-prompt']
        self.assertIn('read-only', prompt)

    def test_file_changes_outside_the_workspace_are_refused_before_authorize(self):
        ctx = FakeContext(self.root)
        ws1 = ctx.workspaces['p1']
        outside = self.root / 'outside'
        outside.mkdir()
        os.symlink(str(outside), os.path.join(ws1, 'link'))
        os.symlink(str(outside / 'target.txt'), os.path.join(ws1, 'dangling.txt'))
        os.makedirs(os.path.join(ws1, '.git', 'info'))
        bad = [str(outside / 'escaped.txt'), '../escaped.txt', 'src/../../escaped.txt', 'link/x.txt',
               'dangling.txt', '.git/config', '.GIT/hooks/pre-commit', 'sub/.git/config', ws1, '/etc/hosts',
               os.path.join(ws1, '.git', 'info', 'exclude')]
        steps = [INIT] + [self.ask('Write', {'file_path': path, 'content': 'x'}, 'toolu_%d' % i)
                          for i, path in enumerate(bad)] + [result()]
        _, ctx, outcome = self.turn({'turns': [steps]}, ctx=ctx)
        self.assertEqual(outcome['status'], 'completed', outcome)
        self.assertEqual(ctx.authorized, [])
        self.assertEqual(len(self.answers()), len(bad))
        self.assertTrue(all(a['behavior'] == 'deny' for a in self.answers()))
        self.assertIn('task workspace', self.answers()[0]['message'])
        calls = [d for k, d, _ in ctx.events if k == 'tool_call']
        self.assertEqual({c['decision']['rule'] for c in calls}, {'provider.claude_workspace'})
        self.assertEqual([d['status'] for k, d, _ in ctx.events if k == 'tool_result'], ['denied'] * len(bad))
        self.assertFalse((outside / 'escaped.txt').exists())

    def test_sandbox_escape_is_refused(self):
        steps = [INIT, self.ask('Bash', {'command': 'ls', 'dangerouslyDisableSandbox': True}, 'toolu_1'), result()]
        _, ctx, outcome = self.turn({'turns': [steps]})
        self.assertEqual(outcome['status'], 'completed', outcome)
        self.assertEqual(ctx.authorized, [])
        self.assertEqual(self.answers()[0]['behavior'], 'deny')
        calls = [d for k, d, _ in ctx.events if k == 'tool_call']
        self.assertEqual(calls[0]['decision']['rule'], 'provider.claude_sandbox')

    def test_policy_denial_of_a_write(self):
        ctx = FakeContext(self.root, decisions={'file_write': 'deny'})
        steps = [INIT, self.ask('Write', {'file_path': 'a.txt', 'content': 'x'}), result()]
        _, ctx, outcome = self.turn({'turns': [steps]}, ctx=ctx)
        self.assertEqual(outcome['status'], 'completed', outcome)
        self.assertEqual(len(ctx.authorized), 1)
        self.assertEqual(self.answers()[0]['behavior'], 'deny')

    def test_access_change_restarts_the_process(self):
        ctx = FakeContext(self.root)
        runtime = self.runtime({'turns': [simple_turn(), simple_turn()]})
        session = runtime.open(ctx)
        self.addCleanup(session.close)
        self.assertEqual(session.run_turn('one', ctx)['status'], 'completed')
        ctx.access = 'read'
        self.assertEqual(session.run_turn('two', ctx)['status'], 'completed')
        self.assertEqual(len(self.main_launches()), 2)

    def test_unknown_tool_is_denied(self):
        steps = [INIT, self.ask('WebFetch', {'url': 'https://example.com'}), result()]
        _, ctx, outcome = self.turn({'turns': [steps]})
        self.assertEqual(outcome['status'], 'failed')
        self.assertEqual(outcome['error']['code'], 'runtime_protocol')
        self.assertEqual(ctx.authorized, [])

    def test_bridge_tool_runs_through_call_tool(self):
        steps = [INIT, self.ask('mcp__interspace__example_get', {'ref': 'item-1'}, 'toolu_7', no_result=True),
                 {'mcp_call': {'name': 'example_get', 'arguments': {'ref': 'item-1'}, 'tool_use_id': 'toolu_7'}},
                 assistant_text('ok'), result()]
        _, ctx, outcome = self.turn({'turns': [steps]}, bridge=True)
        self.assertEqual(outcome['status'], 'completed', outcome)
        self.assertEqual(ctx.authorized, [])  # call_tool authorizes bridge calls itself.
        self.assertEqual(ctx.tool_calls, [('example_get', {'ref': 'item-1'}, 'mcp_' + 'a' * 32)])
        self.assertEqual(self.answers()[0]['behavior'], 'allow')
        self.assertEqual(ctx.kinds(), ['message'])  # RunContext.call_tool emits bridge call events.
        replies = [e['mcp_reply'] for e in self.entries() if 'mcp_reply' in e]
        self.assertEqual(replies, [{'ok': True, 'result': {'title': 'Example item'}}])

    def test_bridge_call_without_permission_prompt_fails_turn(self):
        # call_tool still authorized the call itself; the unanswered tool_result then fails the turn.
        steps = [INIT, {'mcp_call': {'name': 'example_get', 'arguments': {'ref': 'item-1'},
                                     'tool_use_id': 'toolu_x'}}, result()]
        _, ctx, outcome = self.turn({'turns': [steps]}, bridge=True)
        self.assertEqual(outcome['status'], 'failed')
        self.assertEqual(outcome['error']['code'], 'runtime_protocol')


class ProtocolTests(ClaudeCase):
    def assertProtocol(self, steps, bridge=False):
        session, ctx, outcome = self.turn({'turns': [steps]}, bridge=bridge)
        self.assertEqual(outcome['status'], 'failed', outcome)
        self.assertEqual(outcome['error']['code'], 'runtime_protocol')
        pid = self.main_launches()[0]['pid']
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and alive(pid):
            time.sleep(0.02)
        self.assertFalse(alive(pid))
        return ctx

    def test_malformed_lines(self):
        self.assertProtocol([INIT, {'raw': 'not json'}])
        self.log.unlink()
        self.assertProtocol([INIT, {'raw': '[1, 2]'}])
        self.log.unlink()
        self.assertProtocol([INIT, {'emit': {'type': 'mystery'}}])
        self.log.unlink()
        self.assertProtocol([INIT, {'emit': {'type': 'assistant', 'message': 'x'}}])
        self.log.unlink()
        self.assertProtocol([INIT, {'emit': {'type': 'result', 'subtype': 'success'}}])

    def test_init_is_checked(self):
        for override in ({'tools': list(claude.TOOLS) + ['Agent']}, {'model': 'claude-haiku-5-5'},
                         {'permissionMode': 'bypassPermissions'}, {'permissionMode': 'acceptEdits'},
                         {'permissionMode': 'dontAsk'}, {'permissionMode': None}, {'mcp_servers': [{'name': 'other', 'status': 'connected'}]}):
            self.log.unlink(missing_ok=True)
            self.assertProtocol([{'init': override}, assistant_text('x'), result()])

    def test_init_required_before_work(self):
        self.assertProtocol([assistant_text('x'), result()])

    def test_bridge_server_must_connect(self):
        self.assertProtocol([{'init': {'mcp_servers': [{'name': 'interspace', 'status': 'failed'}]}}, result()], bridge=True)

    def test_subagent_and_unexpected_tool_use(self):
        sub = assistant_text('x')
        sub['emit']['parent_tool_use_id'] = 'toolu_9'
        self.assertProtocol([INIT, sub])
        self.log.unlink()
        use = {'emit': {'type': 'assistant', 'parent_tool_use_id': None, 'session_id': 's1',
                        'message': {'id': 'm', 'role': 'assistant', 'model': '$MODEL',
                                    'content': [{'type': 'tool_use', 'id': 't', 'name': 'Agent', 'input': {}}]}}}
        self.assertProtocol([INIT, use])

    def test_tool_result_without_authorization(self):
        self.assertProtocol([INIT, {'emit': {'type': 'user', 'parent_tool_use_id': None, 'session_id': 's1',
                                             'message': {'role': 'user', 'content': [
                                                 {'type': 'tool_result', 'tool_use_id': 'toolu_z', 'content': 'x'}]}}}])

    def test_output_cap(self):
        self.assertProtocol([INIT, {'spam': claude.MAX_TURN_OUTPUT_BYTES + 10000}])

    def test_process_exit_mid_turn(self):
        _, _, outcome = self.turn({'turns': [[INIT, {'exit': 3}]]})
        self.assertEqual(outcome['status'], 'failed')
        self.assertEqual(outcome['error']['code'], 'runtime_exited')
        self.assertIsNone(outcome['usage'])

    def test_initialize_refused(self):
        _, _, outcome = self.turn({'init_fail': True, 'turns': [simple_turn()]})
        self.assertEqual(outcome['status'], 'failed')
        self.assertEqual(outcome['error']['code'], 'runtime_protocol')

    def test_new_process_after_failure(self):
        runtime = self.runtime({'turns': [[INIT, {'raw': 'garbage'}]]})
        ctx = FakeContext(self.root)
        session = runtime.open(ctx)
        self.addCleanup(session.close)
        self.assertEqual(session.run_turn('one', ctx)['error']['code'], 'runtime_protocol')
        self.assertEqual(session.run_turn('two', ctx)['status'], 'failed')  # Fresh process; its turn 0 again fails.
        self.assertEqual(len(self.main_launches()), 2)


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # A zombie is not alive.
        waited, _ = os.waitpid(pid, os.WNOHANG)
        return waited == 0
    except ChildProcessError:
        return True
    return True


class StopTests(ClaudeCase):
    def start(self, steps, **options):
        runtime = self.runtime({'turns': [steps]}, **options)
        ctx = FakeContext(self.root)
        session = runtime.open(ctx)
        self.addCleanup(session.close)
        box = {}
        thread = threading.Thread(target=lambda: box.update(outcome=session.run_turn('go', ctx)))
        thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not any(e.get('stdin', {}).get('type') == 'user' for e in self.entries()):
            time.sleep(0.02)
        time.sleep(0.1)
        return session, ctx, thread, box

    def test_interrupt_ends_turn_with_usage(self):
        session, ctx, thread, box = self.start([INIT, {'wait_interrupt': True}])
        session.interrupt()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(box['outcome']['status'], 'cancelled')
        self.assertEqual(box['outcome']['usage']['input_tokens'], 5)
        sent = [m for m in self.stdin() if m.get('type') == 'control_request']
        self.assertEqual(sent[-1]['request']['subtype'], 'interrupt')

    def test_interrupt_without_result_kills_after_grace(self):
        session, ctx, thread, box = self.start([INIT, {'ignore_interrupt': True}], interrupt_grace_s=0.3)
        session.interrupt()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(box['outcome'], {'status': 'cancelled', 'usage': None, 'error': None})
        pid = self.main_launches()[0]['pid']
        time.sleep(0.3)
        self.assertFalse(alive(pid))

    def test_kill_stops_process_group(self):
        session, ctx, thread, box = self.start([INIT, {'hang': True}])
        pid = self.main_launches()[0]['pid']
        session.kill()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(box['outcome']['status'], 'cancelled')
        time.sleep(0.2)
        self.assertFalse(alive(pid))
        with self.assertRaises(ProcessLookupError):
            os.killpg(pid, 0)

    def test_cancel_event_interrupts(self):
        session, ctx, thread, box = self.start([INIT, {'wait_interrupt': True}])
        ctx.cancel.set()
        thread.join(5)
        self.assertEqual(box['outcome']['status'], 'cancelled')

    def test_close_ends_process(self):
        runtime = self.runtime({'turns': [simple_turn()]})
        ctx = FakeContext(self.root)
        session = runtime.open(ctx)
        session.run_turn('hi', ctx)
        pid = self.main_launches()[0]['pid']
        session.close()
        time.sleep(0.2)
        self.assertFalse(alive(pid))
        session.close()  # Idempotent.
        outcome = session.run_turn('again', ctx)
        self.assertEqual(outcome['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
