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

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / 'app' / 'backend') not in sys.path:
    # Appended, not prepended: under discovery `spaces` must stay the tests/spaces package.
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
        self.app_calls = []
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

    def app_tool(self, name, arguments, call_id):
        with self.lock:
            self.app_calls.append((name, arguments, call_id))
        return {'ok': True, 'result': {'title': 'Reading log'}}

    def report_usage(self, usage):
        pass

    def kinds(self):
        return [kind for kind, _, _ in self.events]


class FakeBridge:
    """Stands in for 2A's `mcp_bridge.start(tools)`: a token-checked unix socket the fake CLI calls.

    Like the real bridge, it runs each call through the bound turn's `ctx.app_tool` with its own call_id.
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
                reply = self.ctx.app_tool(call['name'], call['arguments'], 'mcp_' + 'a' * 32)
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
            ctx.tool_list = [{'name': 'notion_page_get', 'app': 'notion', 'effect': 'read', 'input_schema': {}}]
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

    def test_no_connector_tools_no_bridge(self):
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

    def test_read_only_denies_writes_before_authorize(self):
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
        _, ctx, outcome = self.turn({'turns': [steps]})
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

    def test_read_only_switch_is_one_constant(self):
        self.assertTrue(claude.READ_ONLY)
        self.assertEqual(claude.READ_ONLY_RULE, 'provider.claude_readonly')
        ctx = FakeContext(self.root)
        original = claude.READ_ONLY
        claude.READ_ONLY = False
        self.addCleanup(setattr, claude, 'READ_ONLY', original)
        steps = [INIT, self.ask('Edit', {'file_path': 'a.py', 'old_string': 'a', 'new_string': 'b'}), result()]
        _, ctx, outcome = self.turn({'turns': [steps]}, ctx=ctx)
        self.assertEqual(outcome['status'], 'completed', outcome)
        self.assertEqual(ctx.authorized, [({'category': 'file_write', 'project_id': 'p1', 'paths': ['a.py']}, 'toolu_1')])

    def test_unknown_tool_is_denied(self):
        steps = [INIT, self.ask('WebFetch', {'url': 'https://example.com'}), result()]
        _, ctx, outcome = self.turn({'turns': [steps]})
        self.assertEqual(outcome['status'], 'failed')
        self.assertEqual(outcome['error']['code'], 'runtime_protocol')
        self.assertEqual(ctx.authorized, [])

    def test_connector_tool_runs_through_app_tool(self):
        steps = [INIT, self.ask('mcp__interspace__notion_page_get', {'ref': 'notion:page:n1'}, 'toolu_7', no_result=True),
                 {'mcp_call': {'name': 'notion_page_get', 'arguments': {'ref': 'notion:page:n1'}, 'tool_use_id': 'toolu_7'}},
                 assistant_text('ok'), result()]
        _, ctx, outcome = self.turn({'turns': [steps]}, bridge=True)
        self.assertEqual(outcome['status'], 'completed', outcome)
        self.assertEqual(ctx.authorized, [])  # app_tool authorizes connector calls itself.
        self.assertEqual(ctx.app_calls, [('notion_page_get', {'ref': 'notion:page:n1'}, 'mcp_' + 'a' * 32)])
        self.assertEqual(self.answers()[0]['behavior'], 'allow')
        self.assertEqual(ctx.kinds(), ['message'])  # RunContext.app_tool emits connector events.
        replies = [e['mcp_reply'] for e in self.entries() if 'mcp_reply' in e]
        self.assertEqual(replies, [{'ok': True, 'result': {'title': 'Reading log'}}])

    def test_connector_call_without_permission_prompt_fails_turn(self):
        # app_tool still authorized the call itself; the unanswered tool_result then fails the turn.
        steps = [INIT, {'mcp_call': {'name': 'notion_page_get', 'arguments': {'ref': 'notion:page:n1'},
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
                         {'permissionMode': 'bypassPermissions'}, {'mcp_servers': [{'name': 'github', 'status': 'connected'}]}):
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
