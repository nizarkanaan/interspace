"""End to end: a new task's Orchestrator proposes a mixed team, the user approves, both members run in parallel.

Everything is real except the two CLIs: the backend `Application` with its scheduler, scope engine, audit log,
provider registry, runtimes, MCP bridge, task workspaces and merge all run as in the app, against the fake
`claude` and `codex` CLIs in `tests/runtime/fixtures/` and a disposable repository. No model call, no sign-in.

The flow (orchestration.md): New task -> Orchestrator session on Claude (routing.orchestrator) -> `propose_team`
(a Claude implementer with write access, a Codex reviewer with read access, both the routing defaults) -> the
user approves -> both children run at once in their own clones -> the implementer's edit lands on its
`interspace/task-…` branch, the reviewer's write is refused -> `wait_for` returns both reports wrapped as
untrusted content -> the Orchestrator synthesises -> Review changes merges the implementer's branch into a branch
that is not checked out.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
sys.path.insert(0, str(ROOT / 'tests'))

import service  # noqa: E402  (puts pilot/ on the path)
import codex_auth  # noqa: E402
from runtime import claude, codex  # noqa: E402
from agent_fakes import wait_for  # noqa: E402

FIXTURES = ROOT / 'tests' / 'runtime' / 'fixtures'
GIT = ['git', '-c', 'user.name=T', '-c', 'user.email=t@example.invalid']
TEAM = {'summary': 'Change the greeting and review the change.',
        'members': [{'role': 'implementer', 'brief': 'Make main.py print 2.'},
                    {'role': 'reviewer', 'brief': 'Review main.py for problems.'}]}


def claude_result(inp, out):
    usage = {'input_tokens': inp, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'output_tokens': out}
    return {'emit': {'type': 'result', 'subtype': 'success', 'is_error': False, 'session_id': 's1', 'num_turns': 1,
                     'usage': usage, 'modelUsage': {'$MODEL': {'inputTokens': inp, 'outputTokens': out,
                                                               'cacheReadInputTokens': 0, 'cacheCreationInputTokens': 0,
                                                               'costUSD': 0.01}}}}


def claude_text(text):
    return {'emit': {'type': 'assistant', 'parent_tool_use_id': None, 'session_id': 's1',
                     'message': {'id': 'msg_' + str(abs(hash(text))), 'role': 'assistant', 'model': '$MODEL',
                                 'content': [{'type': 'text', 'text': text}]}}}


def bridged(name, arguments, tool_use_id):
    """The CLI asks permission for an Interspace tool, then calls it over MCP (the real bridge)."""
    return [{'ask': {'tool_name': 'mcp__interspace__' + name, 'input': arguments, 'tool_use_id': tool_use_id,
                     'no_result': True}},
            {'mcp_call': {'name': name, 'arguments': arguments, 'tool_use_id': tool_use_id}}]


def codex_item(kind, item):
    return {'notify': 'item/' + kind, 'params': {'threadId': '$thread', 'turnId': '$turn', 'item': item}}


class EndToEndTeamTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(os.path.realpath(tmp.name))
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        subprocess.run(GIT + ['init', '-q', '-b', 'main', str(self.repo)], check=True)
        (self.repo / 'README.md').write_text('# Sample\n')
        (self.repo / 'main.py').write_text('print(1)\n')
        subprocess.run(GIT + ['-C', str(self.repo), 'add', '.'], check=True)
        subprocess.run(GIT + ['-C', str(self.repo), 'commit', '-qm', 'base'], check=True)
        subprocess.run(GIT + ['-C', str(self.repo), 'branch', 'integration'], check=True)  # Not checked out.
        self.marks = self.root / 'marks'
        self.marks.mkdir()
        self.claude_log = self.root / 'claude.jsonl'
        self.codex_log = self.root / 'codex.jsonl'
        self.write_scenarios()
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        self.claude_bin = self.wrapper(bin_dir / 'claude', FIXTURES / 'claude' / 'fake_claude.py',
                                       self.root / 'claude.json', self.claude_log)
        self.codex_bin = self.wrapper(bin_dir / 'codex', FIXTURES / 'codex' / 'fake_app_server.py',
                                      self.root / 'codex.json', self.codex_log)
        for patcher in (mock.patch.object(claude, 'find_claude', lambda: str(self.claude_bin)),
                        mock.patch.object(codex, 'find_binary', lambda: str(self.codex_bin))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(codex_auth.cancel_all)
        self.messages = []
        self.app = service.Application(self.root / 'data', emit=self.messages.append, interrupt_grace_s=0.5)
        self.addCleanup(self.app.scheduler.shutdown, 10)

    @staticmethod
    def wrapper(path, script, scenario, log):
        path.write_text('#!/bin/sh\nexec %s %s %s %s "$@"\n' % tuple(
            shlex.quote(str(p)) for p in (sys.executable, script, scenario, log)))
        path.chmod(0o755)
        return path

    def write_scenarios(self):
        implementer_started, reviewer_started = str(self.marks / 'implementer'), str(self.marks / 'reviewer')
        orchestrator = [
            {'init': {}},
            claude_text('I will ask a small team to do this.'),
            *bridged('propose_team', TEAM, 'toolu_propose'),
            *bridged('wait_for', {'team_id': '$team_id', 'timeout_s': 60}, 'toolu_wait'),
            claude_text('Synthesis: the implementer changed main.py; the reviewer could only read.'),
            claude_result(400, 60)]
        implementer = [
            {'init': {}},
            {'touch': implementer_started},
            {'wait_file': reviewer_started},  # Both members must be running at once.
            # Interspace's own edit tool, served by the bridge (Claude Code's Edit is never offered).
            {'ask': {'tool_name': 'mcp__interspace__edit_file', 'tool_use_id': 'toolu_edit', 'mcp': True,
                     'input': {'file_path': 'main.py', 'old_string': 'print(1)', 'new_string': 'print(2)'}}},
            claude_text('Implemented: main.py now prints 2.'),
            claude_result(300, 40)]
        (self.root / 'claude.json').write_text(json.dumps({'by_prompt': [
            {'contains': 'You are the Orchestrator', 'turns': [orchestrator]},
            {'contains': 'edit them with the Interspace tools', 'turns': [implementer]}]}))
        change = {'path': '$cwd/main.py', 'kind': {'type': 'update', 'move_path': None},
                  'diff': '@@ -1 +1 @@\n-print(1)\n+print(3)\n'}
        reviewer = [
            {'touch': reviewer_started},
            {'wait_file': implementer_started},
            codex_item('started', {'type': 'fileChange', 'id': 'f1', 'changes': [change], 'status': 'inProgress'}),
            {'request': 'item/fileChange/requestApproval',
             'params': {'threadId': '$thread', 'turnId': '$turn', 'itemId': 'f1', 'startedAtMs': 1}},
            codex_item('completed', {'type': 'fileChange', 'id': 'f1', 'changes': [change], 'status': 'declined'}),
            codex_item('started', {'type': 'agentMessage', 'id': 'm1', 'text': ''}),
            codex_item('completed', {'type': 'agentMessage', 'id': 'm1',
                                     'text': 'Review: main.py looks fine. I could not change files.'}),
            {'notify': 'thread/tokenUsage/updated', 'params': {'threadId': '$thread', 'turnId': '$turn', 'tokenUsage': {
                'total': {'totalTokens': 700, 'inputTokens': 500, 'cachedInputTokens': 0, 'cacheWriteInputTokens': 0,
                          'outputTokens': 200, 'reasoningOutputTokens': 0},
                'last': {'totalTokens': 700, 'inputTokens': 500, 'cachedInputTokens': 0, 'cacheWriteInputTokens': 0,
                         'outputTokens': 200, 'reasoningOutputTokens': 0},
                'modelContextWindow': 100000}}},
            {'complete': 'completed'}]
        (self.root / 'codex.json').write_text(json.dumps({'turns': [reviewer]}))

    # -- helpers --------------------------------------------------------------------------------------

    def call(self, method, params):
        return self.app.handle(method, params)

    def events(self, task_id, kind=None):
        found = self.call('task_events', {'task_id': task_id, 'after_seq': 0, 'limit': 1000})['events']
        return [e for e in found if kind is None or e['kind'] == kind]

    def state(self, task_id):
        with self.app.lock:
            return self.app.store.task(task_id)['agent'].get('state')

    def logged(self, path):
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo)] + list(args), capture_output=True, text=True,
                              check=True).stdout

    # -- the run ---------------------------------------------------------------------------------------

    def test_orchestrator_team_runs_in_parallel_and_merges(self):
        project_id = self.call('add_project', {'path': str(self.repo)})['project_id']
        task_id = self.call('agent_create', {'project_id': project_id, 'title': 'Print 2'})['task_id']
        with self.app.lock:
            parent = self.app.store.task(task_id)
            self.assertEqual((parent['role'], parent['provider']), ('orchestrator', 'claude'))  # routing.orchestrator
        scope = self.call('scope_get', {'task_id': task_id})
        self.call('scope_approve', {'task_id': task_id, 'scope_version': scope['scope']['version'],
                                    'scope_digest': scope['scope_digest']})
        self.call('agent_message', {'task_id': task_id, 'text': 'Make main.py print 2 and have it reviewed.'})

        wait_for(lambda: self.events(task_id, 'team_proposed'), timeout=20, message='team proposed')
        proposal = self.events(task_id, 'team_proposed')[0]['data']
        self.assertEqual(self.state(task_id), 'paused_team')
        self.assertEqual([(m['role'], m['provider'], m['access'], m['default']) for m in proposal['members']],
                         [('implementer', 'claude', 'write', True), ('reviewer', 'codex', 'read', True)])
        self.assertEqual(self.call('team_answer', {'task_id': task_id, 'team_id': proposal['team_id'],
                                                   'decision': 'approve'}), {'status': 'approved'})
        wait_for(lambda: self.state(task_id) in ('idle', 'failed'), timeout=60, message='orchestrator done')
        self.assertEqual(self.state(task_id), 'idle', self.events(task_id, 'error'))

        with self.app.lock:
            children = {t['role']: t for t in self.app.store.agent_tasks() if t.get('parent_task_id') == task_id}
        implementer, reviewer = children['implementer'], children['reviewer']
        rows = {row['id']: row for row in self.app.public()['tasks']}
        self.assertEqual((rows[task_id]['role'], rows[task_id]['parent_task_id']), ('orchestrator', None))
        self.assertEqual({rows[c['id']]['parent_task_id'] for c in children.values()}, {task_id})
        self.assertEqual(rows[implementer['id']]['role'], 'implementer')
        self.assertEqual((implementer['provider'], implementer['access'], self.state(implementer['id'])),
                         ('claude', 'write', 'idle'))
        self.assertEqual((reviewer['provider'], reviewer['access'], self.state(reviewer['id'])), ('codex', 'read', 'idle'))

        # The Orchestrator ran on Claude with its added instructions, read-only, with only the bridge tools.
        launches = [e['launch'] for e in self.logged(self.claude_log) if 'launch' in e and e['launch'][0] == '-p']
        prompts = [dict(zip(a, a[1:]))['--system-prompt'] for a in launches]
        self.assertEqual(len(prompts), 2)
        orchestrator_prompt = next(p for p in prompts if 'You are the Orchestrator' in p)
        self.assertIn('read-only', orchestrator_prompt)
        self.assertIn('- reviewer: codex, model default', orchestrator_prompt)
        implementer_prompt = next(p for p in prompts if 'You are the Orchestrator' not in p)
        self.assertIn('edit_file', implementer_prompt)
        # The reviewer ran Codex in the read-only sandbox, with read-only developer instructions.
        start = next(e['in']['params'] for e in self.logged(self.codex_log)
                     if 'in' in e and e['in'].get('method') == 'thread/start')
        self.assertEqual(start['permissions'], 'interspace-read')
        self.assertIn('read-only', start['developerInstructions'])
        self.assertNotIn('Orchestrator', start['developerInstructions'])

        # Both members ran at once: each waited for the other's start mark, so neither timed out.
        self.assertFalse([e for e in self.logged(self.claude_log) + self.logged(self.codex_log) if 'timeout' in e])

        # The implementer's edit is committed on its own branch; the user's checkout is untouched.
        branch = implementer['agent']['workspaces'][project_id]['target_branch']
        self.assertEqual(branch, 'interspace/task-' + implementer['id'][:8])
        self.assertEqual(self.git('show', branch + ':main.py'), 'print(2)\n')
        self.assertEqual((self.repo / 'main.py').read_text(), 'print(1)\n')
        self.assertEqual(self.git('rev-parse', '--abbrev-ref', 'HEAD').strip(), 'main')
        edit = [e['data'] for e in self.events(implementer['id'], 'tool_call') if e['data']['tool'] == 'edit_file']
        self.assertEqual(edit[0]['decision']['decision'], 'allow')

        # The reviewer's write was refused by the read-only scope, and Codex was told to decline it.
        refused = [e['data'] for e in self.events(reviewer['id'], 'tool_call') if e['data']['category'] == 'file_write']
        self.assertEqual(refused[0]['decision']['decision'], 'deny')
        replies = [e['in'] for e in self.logged(self.codex_log) if 'in' in e and 'method' not in e['in']]
        self.assertIn({'decision': 'decline'}, [r.get('result') for r in replies])
        reviewer_branch = reviewer['agent']['workspaces'][project_id]['target_branch']
        self.assertEqual(self.git('show', reviewer_branch + ':main.py'), 'print(1)\n')

        # Reports came back to the Orchestrator wrapped as untrusted content; it then synthesised.
        replies = [e['mcp_reply'] for e in self.logged(self.claude_log) if 'mcp_reply' in e]
        waited = replies[-1]['content'][0]['text']
        self.assertTrue(waited.startswith('<untrusted-content>'))
        self.assertIn('Implemented: main.py now prints 2.', waited)
        self.assertIn('Review: main.py looks fine.', waited)
        finished = {e['data']['member_id']: e['data'] for e in self.events(task_id, 'subagent_finished')}
        self.assertEqual(finished[implementer['member_id']]['diff_summary']['files'][0]['path'], 'main.py')
        last = [e['data']['text'] for e in self.events(task_id, 'message') if e['data']['role'] == 'assistant'][-1]
        self.assertTrue(last.startswith('Synthesis:'))

        # One budget: every run is charged to the root task, by its own provider's rule.
        with self.app.lock:
            entries = [e for e in self.app.state['usage'] if e.get('task_id') == task_id]
        # A child's entry names it as `source_task_id`; the root's own entries leave it out.
        charged = sorted((e['provider'], e.get('source_task_id', task_id), e['charge_kind'], e['charge'])
                         for e in entries)
        self.assertEqual(charged, sorted([('claude', task_id, 'reported', 460),
                                          ('claude', implementer['id'], 'reported', 340),
                                          ('codex', reviewer['id'], 'reported', 700)]))
        self.assertEqual(self.call('state', {})['task']['tokens']['used'], 1500)

        # Review changes, then Merge into the branch that is not checked out.
        summary = self.call('review_summary', {'task_id': implementer['id']})
        self.assertEqual([f['path'] for f in summary['files']], ['main.py'])
        merged = self.call('review_merge', {'task_id': implementer['id'], 'into': 'integration',
                                            'expected_head': summary['head_commit']})
        self.assertEqual(merged['status'], 'merged', merged)
        self.assertEqual(self.git('show', 'integration:main.py'), 'print(2)\n')
        self.assertEqual(self.git('show', 'main:main.py'), 'print(1)\n')
        self.assertEqual((self.repo / 'main.py').read_text(), 'print(1)\n')


if __name__ == '__main__':
    unittest.main()
