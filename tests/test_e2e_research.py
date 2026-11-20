"""End to end: the research workflow in the backend, with the real modules (research/tasks.md, tools.md).

Real: the `Application`, scheduler, Orchestrator, scope engine, audit log, provider registry, runtimes, MCP bridge,
research registry and dispatch, the five source clients with their HTTP client (allowlist, rate limiter, error
mapping), response cache, citation checker, credentials, outputs and the task workspaces and merge.

Fake: the `claude` and `codex` CLIs (tests/runtime/fixtures/), the network under `research.http.Http` (a transport
answering from the recorded fixtures in tests/research/fixtures/), and Swift (a fake bridge channel that answers the
`keychain` and `save_panel` lines the backend writes). A socket guard refuses every Internet connection, so nothing
here can reach the network. No model call, no sign-in, no Keychain.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
sys.path.insert(0, str(ROOT / 'tests'))

import service  # noqa: E402  (puts pilot/ on the path)
import codex_auth  # noqa: E402
import research  # noqa: E402
from research import http as research_http  # noqa: E402
from runtime import claude, codex  # noqa: E402
from agent_fakes import wait_for  # noqa: E402
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location('research_test_fakes', str(ROOT / 'tests/research/fakes.py'))
research_fakes = importlib.util.module_from_spec(_spec)  # tests/research/fakes.py (the name `research` is the backend's)
_spec.loader.exec_module(research_fakes)
from test_e2e_team import GIT, bridged, claude_result, claude_text, codex_item  # noqa: E402

FIXTURES = ROOT / 'tests' / 'runtime' / 'fixtures'
S2, OA, AX, AXW, CR, UP = ('api.semanticscholar.org', 'api.openalex.org', 'export.arxiv.org', 'arxiv.org',
                           'api.crossref.org', 'api.unpaywall.org')
LECUN = '10.1038/nature14539'
WAKEFIELD = '10.1016/s0140-6736(97)11096-0'
QUERY = 'attention is all you need transformers'   # A distinctive string: it must never reach the audit log.

# Fake keys and emails for every account, set through Settings like the user would (fake, distinctive strings).
SECRETS = {'semantic_scholar': 'S2-E2E-fake-key-4b7d1c9e', 'openalex': 'OA-E2E-fake-key-8e2a6f31',
           'crossref': 'e2e.crossref.contact@example.invalid', 'unpaywall': 'e2e.unpaywall.contact@example.invalid'}

# The reference list the Orchestrator checks: a real fixture paper, a wrong year, an invented one, a retracted one.
REFERENCES = [
    {'title': 'Deep learning', 'authors': ['Yann LeCun', 'Yoshua Bengio', 'Geoffrey Hinton'], 'year': 2015,
     'doi': LECUN},
    {'title': 'Attention Is All You Need', 'authors': ['Ashish Vaswani'], 'year': 2012, 'arxiv_id': '1706.03762'},
    {'title': 'Quantum llamas reason about citation graphs in the deep ocean', 'authors': ['A. Nobody'],
     'year': 2031},
    {'title': 'Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive developmental disorder in '
              'children', 'authors': ['A J Wakefield'], 'year': 1998, 'doi': WAKEFIELD}]
TEAM = {'summary': 'Read further and check the references.',
        'members': [{'role': 'researcher', 'brief': 'Find follow-up work on transformer attention.'},
                    {'role': 'citation_checker', 'brief': 'Check the LeCun reference before it is cited.'}]}
WRITE_TEAM = {'summary': 'Write the report into a file.',
              'members': [{'role': 'implementer', 'brief': 'Write report.md.'}]}
REPORT = ('# Related work\n\nTransformers replaced recurrence with self-attention [1] and build on the deep learning '
          'methods surveyed in [2].\n\n## References\n\n1. Vaswani, A. et al. (2017). Attention is all you need. '
          'arXiv:1706.03762\n2. LeCun, Y., Bengio, Y. and Hinton, G. (2015). Deep learning. Nature. '
          'doi:10.1038/nature14539\n')


def guarded_connect(original):
    """Refuse every Internet connection; Unix sockets (the MCP bridge) still work."""
    def connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError('Network access in a test: %r' % (address,))
        return original(self, address)
    return connect


class FixtureTransport(research_fakes.FakeTransport):
    """The recorded fixtures by host and path. An address without a fixture answers 404 and is remembered."""

    def __init__(self):
        super().__init__()
        self.unmatched = []
        self.lock = threading.Lock()
        add = self.add
        add(S2, '/graph/v1/paper/search/match', ('semantic_scholar', 'match_title'))
        add(S2, '/graph/v1/paper/search', ('semantic_scholar', 'search_attention_2017'))
        add(S2, '/graph/v1/paper/ARXIV:1706.03762/references', ('semantic_scholar', 'references'))
        add(S2, '/graph/v1/paper/ARXIV:1706.03762/citations', ('semantic_scholar', 'citations'))
        add(S2, '/graph/v1/paper/ARXIV:1706.03762', ('semantic_scholar', 'lookup_arxiv'))
        add(S2, '/graph/v1/paper/DOI:' + LECUN, ('semantic_scholar', 'lookup_doi_lecun'))
        add(OA, '/works', ('openalex', 'search_synthetic'))
        add(OA, '/works/doi:10.48550/arxiv.1706.03762', ('openalex', 'lookup_arxiv_doi_vaswani'))
        add(OA, '/works/doi:' + WAKEFIELD, ('openalex', 'lookup_doi_wakefield'))
        add(AX, '/api/query', ('arxiv', 'lookup_1706.03762'), params={'id_list': '1706.03762'})
        add(AX, '/api/query', ('arxiv', 'search_title_2017'))
        add(AXW, '/bibtex/1706.03762', ('arxiv', 'bibtex_1706.03762'))
        add(CR, '/works', ('crossref', 'search_bibliographic_2015'))
        add(CR, '/works/' + LECUN + '/transform/application/x-bibtex', ('crossref', 'bibtex_transform_lecun'))
        add(CR, '/works/' + LECUN, ('crossref', 'lookup_lecun'))
        add(CR, '/works/' + WAKEFIELD, ('crossref', 'lookup_wakefield_retracted'))
        add(UP, '/v2/' + LECUN, ('unpaywall', 'lookup_lecun'))
        add(UP, '/v2/' + WAKEFIELD, ('unpaywall', 'lookup_wakefield'))

    def send(self, method, url, headers, timeout_s):
        with self.lock:
            try:
                return super().send(method, url, headers, timeout_s)
            except AssertionError:
                self.unmatched.append(url)
                return research_fakes.reply(404, {'error': 'no fixture'})

    def hosts(self):
        return [request['url'].split('/')[2] for request in self.requests]


class FakeSwift:
    """The Swift side of the bridge: Keychain items in memory and a save panel that copies into a folder."""

    def __init__(self, saved):
        self.items = {}
        self.saved = saved
        self.app = None
        self.ui = []        # Every message the backend wrote that Swift would forward to the WebView.
        self.to_swift = []  # Keychain and save-panel lines, which Swift consumes and never forwards.

    def emit(self, message):
        kind = message.get('type') if isinstance(message, dict) else None
        if kind == 'keychain':
            self.to_swift.append(message)
            reply = {'type': 'keychain_reply', 'id': message['id'], 'ok': True}
            if message['op'] == 'write':
                self.items[message['account']] = message['secret']
            elif message['op'] == 'delete':
                self.items.pop(message['account'], None)
            elif message['account'] in self.items:
                reply['secret'] = self.items[message['account']]
            else:
                reply = {'type': 'keychain_reply', 'id': message['id'], 'ok': False, 'error': 'not_found'}
            self.app.bridge.deliver(reply)
        elif kind == 'save_panel':
            self.to_swift.append(message)
            target = self.saved / message['suggested_name']
            shutil.copyfile(message['path'], str(target))
            self.app.bridge.deliver({'type': 'save_panel_reply', 'id': message['id'], 'ok': True})
        else:
            self.ui.append(json.loads(json.dumps(message)))


class ResearchEndToEnd(unittest.TestCase):
    def setUp(self):
        for patcher in (mock.patch.object(socket.socket, 'connect', guarded_connect(socket.socket.connect)),
                        mock.patch.object(socket, 'create_connection',
                                          mock.Mock(side_effect=AssertionError('Network access in a test'))),
                        mock.patch.object(research_http.UrllibTransport, 'send',
                                          mock.Mock(side_effect=AssertionError('Network access in a test')))):
            patcher.start()
            self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(os.path.realpath(tmp.name))
        self.data = self.root / 'data'
        self.marks = self.root / 'marks'
        self.marks.mkdir()
        self.saved = self.root / 'saved'
        self.saved.mkdir()
        self.claude_log = self.root / 'claude.jsonl'
        self.codex_log = self.root / 'codex.jsonl'
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
        (self.root / 'codex.json').write_text(json.dumps({'turns': []}))
        self.transport = FixtureTransport()
        self.clock = research_fakes.FakeClock()
        self.swift = FakeSwift(self.saved)
        self.start_app()
        for source, value in SECRETS.items():
            row = self.call('research_credential_set', {'source': source, 'value': value})
            self.assertTrue(row['configured'], row)
            self.assertNotIn(value, json.dumps(row))

    def start_app(self):
        self.app = service.Application(self.data, emit=self.swift.emit, interrupt_grace_s=0.5)
        self.swift.app = self.app
        self.app.bridge.deliver({'type': 'bridge_hello', 'keychain': 1, 'save_panel': 1})
        # The real HTTP client, with the fixture transport in place of urllib and a clock only its sleeps advance.
        self.app.http = research_http.Http(transport=self.transport, clock=self.clock, sleep=self.clock.sleep)
        self.lock_keys = []
        acquire = self.app.locks.acquire

        def spy(key, task_id, *args, **kwargs):
            self.lock_keys.append((key, task_id))
            return acquire(key, task_id, *args, **kwargs)
        self.app.locks.acquire = spy
        self.addCleanup(self.app.scheduler.shutdown, 10)

    @staticmethod
    def wrapper(path, script, scenario, log):
        import shlex
        path.write_text('#!/bin/sh\nexec %s %s %s %s "$@"\n' % tuple(
            shlex.quote(str(p)) for p in (sys.executable, script, scenario, log)))
        path.chmod(0o755)
        return path

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

    def children(self, task_id):
        with self.app.lock:
            return {t['role']: t for t in self.app.store.agent_tasks() if t.get('parent_task_id') == task_id}

    def approve_scope(self, task_id):
        scope = self.call('scope_get', {'task_id': task_id})
        self.call('scope_approve', {'task_id': task_id, 'scope_version': scope['scope']['version'],
                                    'scope_digest': scope['scope_digest']})

    def research_results(self, task_id, tool=None):
        """{call_id: (tool_call data, parsed tool_result output)} for the task's research calls."""
        calls = {e['data']['call_id']: e['data'] for e in self.events(task_id, 'tool_call')
                 if e['data'].get('category') == 'research' and (tool is None or e['data']['tool'] == tool)}
        found = []
        for event in self.events(task_id, 'tool_result'):
            data = event['data']
            if data['call_id'] in calls:
                found.append((calls[data['call_id']], data, json.loads(data['output']['text'])))
        return found

    def audit_records(self):
        records = []
        for path in sorted((self.data / 'audit').rglob('*')):
            if path.is_file():
                for line in path.read_text().splitlines():
                    if line.strip():
                        records.append(json.loads(line))
        return records

    def mcp_replies(self, log):
        return [e['mcp_reply']['content'][0]['text'] for e in self.logged(log) if 'mcp_reply' in e]

    def assert_no_secrets(self, used=tuple(SECRETS)):
        """research/tasks.md "Key safety": no key or email in state, events, audit, UI messages, tool results or
        the cache. The `used` ones did go out, but only on the fixture transport's requests (not vacuous)."""
        sent = urllib.parse.unquote(json.dumps(self.transport.requests))
        for name in used:
            self.assertIn(SECRETS[name], sent)
        self.assertTrue(self.swift.ui)
        places = {'stdout to the UI': json.dumps(self.swift.ui, ensure_ascii=False),
                  'tool results (Claude)': json.dumps(self.mcp_replies(self.claude_log), ensure_ascii=False),
                  'tool results (Codex)': json.dumps(self.mcp_replies(self.codex_log), ensure_ascii=False),
                  'fake CLI logs': self.claude_log.read_text() + (self.codex_log.read_text()
                                                                    if self.codex_log.exists() else '')}
        for path in sorted(self.data.rglob('*')):
            if path.is_file() and not path.is_symlink() and 'codex-home' not in path.parts:
                places[str(path.relative_to(self.data))] = path.read_text(errors='replace')
        self.assertIn('state.json', places)
        self.assertTrue(any(name.startswith('audit') for name in places))
        self.assertTrue(any(name.endswith('events.jsonl') for name in places))
        self.assertTrue(any(name.startswith('research-cache') for name in places))
        for value in SECRETS.values():
            for form in {value, urllib.parse.quote(value), urllib.parse.quote_plus(value), value.split('@')[0]}:
                for name, text in places.items():
                    self.assertNotIn(form, text, name)
        # Only Swift saw them, on the Keychain write lines it consumes.
        self.assertEqual({m['account'] for m in self.swift.to_swift if m.get('op') == 'write'},
                         {'semantic_scholar', 'openalex', 'crossref_email', 'unpaywall_email'})

    def assert_no_project_work(self):
        self.assertFalse((self.data / 'workspaces').exists() and any((self.data / 'workspaces').iterdir()))
        self.assertEqual(self.lock_keys, [])

    # -- 1. a research task with no project ----------------------------------------------------------------

    def research_scenarios(self):
        researcher_started, checker_started = str(self.marks / 'researcher'), str(self.marks / 'checker')
        orchestrator = [
            {'init': {}},
            claude_text('I will search, read and snowball first.'),
            *bridged('research_search', {'query': QUERY, 'limit': 10}, 'toolu_search'),
            *bridged('research_paper', {'id': 'arXiv:1706.03762'}, 'toolu_paper'),
            *bridged('research_citations', {'id': 'arXiv:1706.03762', 'direction': 'references', 'limit': 5},
                     'toolu_refs'),
            *bridged('research_fulltext', {'id': LECUN}, 'toolu_fulltext'),
            *bridged('research_bibtex', {'ids': [LECUN, 'arXiv:1706.03762']}, 'toolu_bibtex'),
            *bridged('propose_team', WRITE_TEAM, 'toolu_write_team'),
            *bridged('propose_team', TEAM, 'toolu_team'),
            *bridged('wait_for', {'team_id': '$team_id', 'timeout_s': 60}, 'toolu_wait'),
            *bridged('verify_citations', {'references': REFERENCES}, 'toolu_verify'),
            *bridged('save_report', {'markdown': REPORT}, 'toolu_save'),  # Only a saved report becomes report.md.
            claude_text(REPORT),
            claude_result(500, 80)]
        (self.root / 'claude.json').write_text(json.dumps({'by_prompt': [
            {'contains': 'You are the Orchestrator', 'turns': [orchestrator]}]}))
        usage = {'notify': 'thread/tokenUsage/updated', 'params': {'threadId': '$thread', 'turnId': '$turn', 'tokenUsage': {
            'total': {'totalTokens': 300, 'inputTokens': 200, 'cachedInputTokens': 0, 'cacheWriteInputTokens': 0,
                      'outputTokens': 100, 'reasoningOutputTokens': 0},
            'last': {'totalTokens': 300, 'inputTokens': 200, 'cachedInputTokens': 0, 'cacheWriteInputTokens': 0,
                     'outputTokens': 100, 'reasoningOutputTokens': 0},
            'modelContextWindow': 100000}}}

        def member(started, other, call, text):
            return [{'touch': started}, {'wait_file': other},  # Both members run at once.
                    {'mcp_call': call},
                    codex_item('started', {'type': 'agentMessage', 'id': 'm1', 'text': ''}),
                    codex_item('completed', {'type': 'agentMessage', 'id': 'm1', 'text': text}),
                    usage, {'complete': 'completed'}]
        researcher = member(researcher_started, checker_started,
                            {'name': 'research_search', 'id': 'mcp1',
                             'arguments': {'query': 'transformer attention follow-up', 'sources': ['arxiv'], 'limit': 3}},
                            'Researcher: arXiv lists the transformer paper and its follow-ups.')
        checker = member(checker_started, researcher_started,
                         {'name': 'verify_citations', 'id': 'mcp1',
                          'arguments': {'references': [REFERENCES[0]]}},
                         'Citation checker: the LeCun reference is verified.')
        (self.root / 'codex.json').write_text(json.dumps({'by_input': [
            {'contains': 'follow-up work on transformer attention', 'turns': [researcher]},
            {'contains': 'Check the LeCun reference', 'turns': [checker]}]}))

    def test_research_task_without_a_project_end_to_end(self):
        self.research_scenarios()
        default = self.call('scope_default', {'project_id': None, 'kind': 'research'})['scope']
        self.assertEqual(default['projects'], [])
        self.assertEqual(default['research']['sources'], {name: 'allow' for name in research.SOURCES})
        task_id = self.call('agent_create', {'project_id': None, 'kind': 'research', 'title': 'Related work'})['task_id']
        self.approve_scope(task_id)
        self.call('agent_message', {'task_id': task_id, 'text': 'Related work on transformer attention.'})

        wait_for(lambda: self.events(task_id, 'team_proposed'), timeout=30, message='team proposed')
        proposal = self.events(task_id, 'team_proposed')[0]['data']
        self.assertEqual([(m['role'], m['provider'], m['access']) for m in proposal['members']],
                         [('researcher', 'codex', 'read'), ('citation_checker', 'codex', 'read')])
        self.call('team_answer', {'task_id': task_id, 'team_id': proposal['team_id'], 'decision': 'approve'})
        wait_for(lambda: self.state(task_id) in ('idle', 'failed'), timeout=60, message='research task done')
        self.assertEqual(self.state(task_id), 'idle', self.events(task_id, 'error'))

        # The Orchestrator's research calls, decided per source and merged.
        search = self.research_results(task_id, 'research_search')[0]
        self.assertEqual(search[0]['input'], {'tool': 'research_search', 'query': QUERY})
        result = search[2]
        self.assertEqual(result['searched'], ['semantic_scholar', 'openalex', 'arxiv', 'crossref'])
        self.assertEqual(result['skipped'], [])
        vaswani = [p for p in result['papers'] if p['arxiv_id'] == '1706.03762']
        self.assertEqual(len(vaswani), 1)  # De-duplicated across sources.
        self.assertGreaterEqual(len(vaswani[0]['sources']), 2)
        paper = self.research_results(task_id, 'research_paper')[0][2]
        self.assertEqual(paper['paper']['arxiv_id'], '1706.03762')
        self.assertGreaterEqual(len(paper['sources']), 2)
        refs = self.research_results(task_id, 'research_citations')[0][2]
        self.assertEqual(refs['source'], 'semantic_scholar')
        self.assertTrue(refs['papers'])
        fulltext = self.research_results(task_id, 'research_fulltext')[0][2]
        self.assertEqual(fulltext['source'], 'unpaywall')
        self.assertTrue(fulltext['oa_url'].startswith('https://'))
        fetched = self.research_results(task_id, 'research_bibtex')[0][2]
        self.assertEqual([(e['id'], e['error']) for e in fetched['entries']],
                         [(LECUN, None), ('arXiv:1706.03762', None)])
        replies = self.mcp_replies(self.claude_log)
        self.assertTrue(all(r.startswith('<untrusted-content>') for r in replies
                            if 'papers' in r or 'references' in r))

        # The write member was refused before the user saw it; only the read team was proposed.
        write_reply = next(e['mcp_reply'] for e in self.logged(self.claude_log)
                           if 'mcp_reply' in e and 'no project to write to' in e['mcp_reply']['content'][0]['text'])
        self.assertTrue(write_reply.get('isError'))
        self.assertEqual(len(self.events(task_id, 'team_proposed')), 1)

        # Both members ran (at once: each waited for the other's start mark) and called research tools.
        children = self.children(task_id)
        self.assertEqual(set(children), {'researcher', 'citation_checker'})
        for child in children.values():
            self.assertEqual((child['provider'], child['access'], child['kind'] if 'kind' in child else 'research',
                              self.state(child['id'])), ('codex', 'read', 'research', 'idle'))
            self.assertIsNone(child['agent']['project_id'])
        self.assertFalse([e for e in self.logged(self.codex_log) if 'timeout' in e])
        searched = self.research_results(children['researcher']['id'], 'research_search')[0][2]
        self.assertEqual(searched['searched'], ['arxiv'])
        checked = self.research_results(children['citation_checker']['id'], 'verify_citations')[0][2]
        self.assertEqual(checked['summary']['verified'], 1)
        self.assertEqual(len(self.events(children['citation_checker']['id'], 'citation_report')), 1)
        codex_replies = self.mcp_replies(self.codex_log)
        self.assertEqual(len(codex_replies), 2)
        self.assertTrue(all(r.startswith('<untrusted-content>') for r in codex_replies))
        starts = [e['in']['params'] for e in self.logged(self.codex_log)
                  if 'in' in e and e['in'].get('method') == 'thread/start']
        self.assertEqual({s['permissions'] for s in starts}, {'interspace-read'})
        self.assertEqual({s['cwd'] for s in starts}, {str(self.data / 'research-runs' / c['id'])
                                                     for c in children.values()})

        # The citation check: verified, mismatch (year), not found and retracted.
        report = self.events(task_id, 'citation_report')[-1]['data']
        self.assertEqual(report['summary'], {'verified': 1, 'mismatch': 1, 'not_found': 1, 'retracted': 1,
                                             'unchecked': 0})
        statuses = [(r['index'], r['status']) for r in report['references']]
        self.assertEqual(statuses, [(0, 'verified'), (1, 'mismatch'), (2, 'not_found'), (3, 'retracted')])
        self.assertEqual(report['references'][1]['fields'], ['year'])

        # Outputs: the report and BibTeX with only the verified and (marked) mismatch entries.
        outputs = self.events(task_id, 'outputs')[-1]['data']['outputs']
        self.assertEqual([o['name'] for o in outputs], ['report.md', 'references.bib'])
        listed = self.call('task_outputs', {'task_id': task_id})['outputs']
        self.assertEqual([(o['name'], o['kind']) for o in listed], [('report.md', 'report'), ('references.bib', 'bibtex')])
        self.assertEqual(self.call('task_output_read', {'task_id': task_id, 'name': 'report.md'})['text'], REPORT)
        bib = self.call('task_output_read', {'task_id': task_id, 'name': 'references.bib'})['text']
        self.assertIn('Verified: 1. Mismatch: 1', bib)
        self.assertIn('% mismatch (year): Attention Is All You Need', bib)
        self.assertIn('% Left out, not found: Quantum llamas', bib)
        self.assertIn('% Left out, retracted: Ileal-lymphoid-nodular hyperplasia', bib)
        entries = [line for line in bib.splitlines() if line.startswith('@')]
        self.assertEqual(len(entries), 2, bib)
        self.assertIn('10.1038/nature14539', bib.lower())
        self.assertIn('1706.03762', bib)
        self.assertNotIn('Wakefield', '\n'.join(l for l in bib.splitlines() if not l.startswith('%')))
        self.assertEqual(self.call('task_output_save', {'task_id': task_id, 'name': 'references.bib'}), {'saved': True})
        self.assertEqual((self.saved / 'related-work.bib').read_text(), bib)

        # Call counts per source, never money: the last research_usage event matches research_usage.
        counted = self.call('research_usage', {'task_id': task_id})
        self.assertEqual(set(counted), {'calls', 'cached'})
        self.assertTrue(all(isinstance(n, int) for n in counted['calls'].values()))
        # `calls` are the requests that went out; `cached` the answers the cache gave instead (the checker's second
        # look at the LeCun DOI, after the citation_checker member's).
        sent = {}
        for request in self.transport.requests:
            source = next(name for name, hosts in research_http.HOSTS.items() if request['url'].split('/')[2] in hosts)
            sent[source] = sent.get(source, 0) + 1
        self.assertEqual({k: v for k, v in counted['calls'].items() if v}, sent)
        self.assertGreaterEqual(counted['cached']['crossref'], 1)
        wait_for(lambda: self.events(task_id, 'research_usage')[-1]['data']
                 == {key: {k: v for k, v in counted[key].items() if v} for key in ('calls', 'cached')},
                 message='final research_usage event')
        self.assertNotIn('cost', json.dumps(counted).lower())

        # Audit: a decision and an action record per source call, naming source and tool, never the query.
        research_records = [r for r in self.audit_records() if (r.get('request') or {}).get('category') == 'research']
        kinds = {r['kind'] for r in research_records}
        self.assertEqual(kinds, {'decision', 'action'})
        for record in research_records:
            self.assertEqual(set(record['request']), {'category', 'source', 'tool'})
        audit_text = json.dumps(self.audit_records())
        self.assertNotIn(QUERY, audit_text)
        self.assertNotIn('transformer attention follow-up', audit_text)
        self.assertNotIn('Quantum llamas', audit_text)

        self.assert_no_project_work()
        self.assertEqual(self.transport.unmatched, [])
        self.assert_no_secrets()

    def test_a_members_citation_check_does_not_replace_the_orchestrators(self):
        team = {'summary': 'Double-check one reference.',
                'members': [{'role': 'citation_checker', 'brief': 'Check the LeCun reference before it is cited.'}]}
        orchestrator = [
            {'init': {}},
            *bridged('verify_citations', {'references': REFERENCES}, 'toolu_verify'),
            *bridged('propose_team', team, 'toolu_team'),
            *bridged('wait_for', {'team_id': '$team_id', 'timeout_s': 60}, 'toolu_wait'),
            *bridged('save_report', {'markdown': REPORT}, 'toolu_save'),
            claude_text(REPORT),
            claude_result(300, 50)]
        (self.root / 'claude.json').write_text(json.dumps({'by_prompt': [
            {'contains': 'You are the Orchestrator', 'turns': [orchestrator]}]}))
        checker = [{'mcp_call': {'name': 'verify_citations', 'id': 'mcp1', 'arguments': {'references': [REFERENCES[0]]}}},
                   codex_item('completed', {'type': 'agentMessage', 'id': 'm1', 'text': 'Verified.'}),
                   {'complete': 'completed'}]
        (self.root / 'codex.json').write_text(json.dumps({'turns': [checker]}))
        task_id = self.call('agent_create', {'project_id': None, 'kind': 'research', 'title': 'Order'})['task_id']
        self.approve_scope(task_id)
        self.call('agent_message', {'task_id': task_id, 'text': 'Check my references.'})
        wait_for(lambda: self.events(task_id, 'team_proposed'), timeout=30, message='team proposed')
        proposal = self.events(task_id, 'team_proposed')[0]['data']
        self.call('team_answer', {'task_id': task_id, 'team_id': proposal['team_id'], 'decision': 'approve'})
        wait_for(lambda: self.state(task_id) in ('idle', 'failed'), timeout=60, message='task done')
        self.assertEqual(self.state(task_id), 'idle', self.events(task_id, 'error'))
        bib = self.call('task_output_read', {'task_id': task_id, 'name': 'references.bib'})['text']
        self.assertIn('Verified: 1. Mismatch: 1', bib)  # The Orchestrator's four references, not the member's one.
        self.assertIn('% Left out, retracted:', bib)
        self.assertEqual(len([line for line in bib.splitlines() if line.startswith('@')]), 2, bib)

    # -- 2. ask and off sources ----------------------------------------------------------------------------

    def test_ask_source_pauses_and_add_to_scope_continues_off_source_is_never_called(self):
        orchestrator = [
            {'init': {}},
            *bridged('research_search', {'query': QUERY, 'limit': 5}, 'toolu_search'),
            *bridged('research_search', {'query': QUERY + ' again', 'limit': 5}, 'toolu_search2'),
            claude_text('Searched twice.'),
            claude_result(100, 20)]
        (self.root / 'claude.json').write_text(json.dumps({'by_prompt': [
            {'contains': 'You are the Orchestrator', 'turns': [orchestrator]}]}))
        task_id = self.call('agent_create', {'project_id': None, 'kind': 'research', 'title': 'Ask and off'})['task_id']
        scope = self.call('scope_get', {'task_id': task_id})['scope']
        scope['research']['sources'].update(openalex='ask', crossref='off')
        self.call('scope_update', {'task_id': task_id, 'base_version': scope['version'], 'scope': scope})
        self.approve_scope(task_id)
        self.call('agent_message', {'task_id': task_id, 'text': 'Search for transformers.'})

        wait_for(lambda: self.events(task_id, 'ask'), timeout=30, message='ask')
        ask = self.events(task_id, 'ask')[0]['data']
        self.assertEqual(ask['request'], {'category': 'research', 'source': 'openalex', 'tool': 'research_search'})
        self.assertEqual(self.state(task_id), 'paused_ask')
        self.assertNotIn(OA, self.transport.hosts())  # Nothing went to OpenAlex before the answer.
        self.call('agent_answer', {'task_id': task_id, 'ask_id': ask['ask_id'], 'decision': 'add_to_scope',
                                   'scope_digest': ask['patched_scope_digest'], 'request_digest': ask['request_digest']})
        wait_for(lambda: self.state(task_id) in ('idle', 'failed'), timeout=30, message='task done')
        self.assertEqual(self.state(task_id), 'idle', self.events(task_id, 'error'))

        first, second = [r[2] for r in self.research_results(task_id, 'research_search')]
        self.assertEqual(first['searched'], ['semantic_scholar', 'openalex', 'arxiv'])
        self.assertIn({'source': 'crossref', 'reason': 'off'}, first['skipped'])
        self.assertIn({'source': 'crossref', 'reason': 'off'}, second['skipped'])
        self.assertEqual(len(self.events(task_id, 'ask')), 1)  # Added to scope: the second search did not ask.
        self.assertEqual(self.call('scope_get', {'task_id': task_id})['scope']['research']['sources']['openalex'], 'allow')
        self.assertNotIn(CR, self.transport.hosts())  # The off source was never called.
        research_records = [r for r in self.audit_records() if (r.get('request') or {}).get('category') == 'research']
        self.assertFalse([r for r in research_records if r['request']['source'] == 'crossref'])
        self.assertEqual([r['decision'] for r in research_records
                          if r['kind'] == 'decision' and r['request']['source'] == 'openalex'], ['ask', 'allow'])
        self.assert_no_project_work()
        self.assert_no_secrets(used=('semantic_scholar', 'openalex'))

    # -- 3. a project task still codes ---------------------------------------------------------------------

    def test_project_task_codes_while_a_researcher_reads(self):
        repo = self.root / 'repo'
        repo.mkdir()
        subprocess.run(GIT + ['init', '-q', '-b', 'main', str(repo)], check=True)
        (repo / 'README.md').write_text('# Sample\n')
        (repo / 'main.py').write_text('print(1)\n')
        subprocess.run(GIT + ['-C', str(repo), 'add', '.'], check=True)
        subprocess.run(GIT + ['-C', str(repo), 'commit', '-qm', 'base'], check=True)
        subprocess.run(GIT + ['-C', str(repo), 'branch', 'integration'], check=True)
        implementer_started, researcher_started = str(self.marks / 'implementer'), str(self.marks / 'researcher')
        team = {'summary': 'Implement and look up the method.',
                'members': [{'role': 'implementer', 'brief': 'Make main.py print 2.'},
                            {'role': 'researcher', 'brief': 'Find the transformer paper for the docs.'}]}
        orchestrator = [
            {'init': {}},
            *bridged('propose_team', team, 'toolu_team'),
            *bridged('wait_for', {'team_id': '$team_id', 'timeout_s': 60}, 'toolu_wait'),
            claude_text('Synthesis: main.py prints 2; the researcher found the paper.'),
            claude_result(300, 40)]
        implementer = [
            {'init': {}}, {'touch': implementer_started}, {'wait_file': researcher_started},
            {'ask': {'tool_name': 'mcp__interspace__edit_file', 'tool_use_id': 'toolu_edit', 'mcp': True,
                     'input': {'file_path': 'main.py', 'old_string': 'print(1)', 'new_string': 'print(2)'}}},
            claude_text('Implemented: main.py now prints 2.'),
            claude_result(200, 30)]
        (self.root / 'claude.json').write_text(json.dumps({'by_prompt': [
            {'contains': 'You are the Orchestrator', 'turns': [orchestrator]},
            {'contains': 'edit them with the Interspace tools', 'turns': [implementer]}]}))
        researcher = [
            {'touch': researcher_started}, {'wait_file': implementer_started},
            {'mcp_call': {'name': 'research_search', 'id': 'mcp1',
                          'arguments': {'query': 'attention is all you need', 'sources': ['semantic_scholar']}}},
            codex_item('completed', {'type': 'agentMessage', 'id': 'm1', 'text': 'Researcher: found arXiv:1706.03762.'}),
            {'complete': 'completed'}]
        (self.root / 'codex.json').write_text(json.dumps({'turns': [researcher]}))

        project_id = self.call('add_project', {'path': str(repo)})['project_id']
        task_id = self.call('agent_create', {'project_id': project_id, 'title': 'Print 2'})['task_id']
        scope = self.call('scope_get', {'task_id': task_id})['scope']
        self.assertEqual(scope['research']['sources'], {name: 'allow' for name in research.SOURCES})
        self.approve_scope(task_id)
        self.call('agent_message', {'task_id': task_id, 'text': 'Make main.py print 2; cite the method.'})
        wait_for(lambda: self.events(task_id, 'team_proposed'), timeout=30, message='team proposed')
        proposal = self.events(task_id, 'team_proposed')[0]['data']
        self.call('team_answer', {'task_id': task_id, 'team_id': proposal['team_id'], 'decision': 'approve'})
        wait_for(lambda: self.state(task_id) in ('idle', 'failed'), timeout=60, message='project task done')
        self.assertEqual(self.state(task_id), 'idle', self.events(task_id, 'error'))

        children = self.children(task_id)
        implementer_task, researcher_task = children['implementer'], children['researcher']
        self.assertEqual(self.state(implementer_task['id']), 'idle')
        self.assertEqual(self.state(researcher_task['id']), 'idle')
        self.assertFalse([e for e in self.logged(self.claude_log) + self.logged(self.codex_log) if 'timeout' in e])
        found = self.research_results(researcher_task['id'], 'research_search')[0][2]
        self.assertEqual(found['searched'], ['semantic_scholar'])
        self.assertTrue(found['papers'])
        branch = implementer_task['agent']['workspaces'][project_id]['target_branch']
        show = subprocess.run(['git', '-C', str(repo), 'show', branch + ':main.py'], capture_output=True, text=True)
        self.assertEqual(show.stdout, 'print(2)\n')
        self.assertEqual((repo / 'main.py').read_text(), 'print(1)\n')
        self.assertFalse(self.call('task_outputs', {'task_id': task_id})['outputs'])  # Project tasks: no auto outputs.

        summary = self.call('review_summary', {'task_id': implementer_task['id']})
        self.assertEqual([f['path'] for f in summary['files']], ['main.py'])
        merged = self.call('review_merge', {'task_id': implementer_task['id'], 'into': 'integration',
                                            'expected_head': summary['head_commit']})
        self.assertEqual(merged['status'], 'merged', merged)
        show = subprocess.run(['git', '-C', str(repo), 'show', 'integration:main.py'], capture_output=True, text=True)
        self.assertEqual(show.stdout, 'print(2)\n')
        self.assert_no_secrets(used=('semantic_scholar',))

    # -- 5. restart mid-run --------------------------------------------------------------------------------

    def test_restart_mid_run_interrupts_the_research_task_and_nothing_resumes(self):
        orchestrator = [
            {'init': {}},
            *bridged('research_search', {'query': QUERY, 'limit': 5}, 'toolu_search'),
            {'hang': True}]
        (self.root / 'claude.json').write_text(json.dumps({'by_prompt': [
            {'contains': 'You are the Orchestrator', 'turns': [orchestrator]}]}))
        task_id = self.call('agent_create', {'project_id': None, 'kind': 'research', 'title': 'Restart'})['task_id']
        self.approve_scope(task_id)
        self.call('agent_message', {'task_id': task_id, 'text': 'Search, then wait.'})
        wait_for(lambda: self.research_results(task_id, 'research_search'), timeout=30, message='search result')
        wait_for(lambda: json.loads((self.data / 'state.json').read_text())['research']['tasks'][task_id]['agent']
                 .get('state') == 'running', message='running state saved')
        crashed = (self.data / 'state.json').read_text()  # What a crash would leave on disk.
        launches = len([e for e in self.logged(self.claude_log) if 'launch' in e and e['launch'][0] == '-p'])

        self.app.scheduler.shutdown(10)
        (self.data / 'state.json').write_text(crashed)
        self.start_app()
        self.assertEqual(self.state(task_id), 'interrupted')
        row = next(r for r in self.call('state', {})['research']['tasks'] if r['id'] == task_id)
        self.assertEqual(row['kind'], 'research')
        time.sleep(0.5)
        self.assertEqual(len([e for e in self.logged(self.claude_log) if 'launch' in e and e['launch'][0] == '-p']),
                         launches)  # Nothing resumed.
        self.assertEqual(self.state(task_id), 'interrupted')
        self.assertFalse(self.app.scheduler.snapshot().get('running'))
        self.assert_no_secrets(used=('semantic_scholar', 'openalex', 'crossref'))


if __name__ == '__main__':
    unittest.main()
