"""Key safety and a whole research task without a project (research/tasks.md "Key safety").

Everything is real except the `claude` CLI (the fake in tests/runtime/fixtures/) and the research sources: a fake
`research` module stands in for stream 1B with fake credentials (set through a fake Keychain channel), fake HTTP and
a fake cache. Its sources really read the keys and put them in their (fake) requests, so the test is not vacuous.
No network, no Keychain, no model call.

The flow: a Research question with no project -> scope from research_default -> approve -> the Orchestrator (Claude)
calls research_search, research_bibtex and verify_citations through the real MCP bridge -> final answer -> the
report and the verified BibTeX are saved in app data. Then no key or email may appear in state.json, any task's
events, the audit log, the messages to the UI, tool results or the cache files.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
sys.path.insert(0, str(ROOT / 'tests'))

import service  # noqa: E402  (puts pilot/ on the path)
import codex_auth  # noqa: E402
from research import citations  # noqa: E402
from runtime import claude, codex  # noqa: E402
from agent_fakes import wait_for  # noqa: E402
import test_e2e_team as e2e  # noqa: E402  (a module, so its test class is not collected twice)
from test_e2e_team import bridged, claude_result, claude_text  # noqa: E402

SECRETS = {'semantic_scholar': 'S2-FAKE-KEY-7f3a9c1e5b', 'openalex': 'OA-FAKE-KEY-c4d2e8a6f0',
           'crossref_email': 'fake.crossref.contact@example.invalid',
           'unpaywall_email': 'fake.unpaywall.contact@example.invalid'}
CREDENTIAL = {'semantic_scholar': 'semantic_scholar', 'openalex': 'openalex', 'crossref': 'crossref_email',
              'unpaywall': 'unpaywall_email', 'arxiv': None}
LECUN = {'v': 1, 'title': 'Deep learning', 'authors': ['Yann LeCun'], 'year': 2015, 'venue': 'Nature',
         'doi': '10.1038/nature14539', 'arxiv_id': None, 's2_id': None, 'openalex_id': None, 'abstract': None,
         'citation_count': 1, 'url': 'https://doi.org/10.1038/nature14539', 'oa_url': None, 'retracted': False,
         'sources': ['crossref']}
REFERENCES = [{'title': 'Deep learning', 'doi': '10.1038/nature14539', 'year': 2015},
              {'raw': 'Nobody, A. (2031). A paper that was never written about quantum llamas.'}]


class FakeChannel:
    """The Keychain pipe: `keychain` write/read messages answered from memory."""

    def __init__(self):
        self.items = {}

    def request(self, message):
        if message['op'] == 'write':
            self.items[message['account']] = message['secret']
            return {'type': 'keychain_reply', 'id': message['id'], 'ok': True}
        if message['account'] not in self.items:
            return {'type': 'keychain_reply', 'id': message['id'], 'ok': False, 'error': 'not_found'}
        return {'type': 'keychain_reply', 'id': message['id'], 'ok': True, 'secret': self.items[message['account']]}


class FakeCredentials:
    def __init__(self, channel):
        self.channel = channel

    def set(self, account, secret):
        self.channel.request({'type': 'keychain', 'id': 'kc-1', 'op': 'write', 'account': account, 'secret': secret})

    def get(self, account):
        reply = self.channel.request({'type': 'keychain', 'id': 'kc-2', 'op': 'read', 'account': account})
        return reply.get('secret')


class FakeSource:
    def __init__(self, name, credentials, http, cache_dir):
        self.name = name
        self.required = name == 'unpaywall'
        self.credentials = credentials
        self.http = http
        self.cache_dir = cache_dir

    def _call(self, what):
        account = CREDENTIAL[self.name]
        secret = self.credentials.get(account) if account else None
        self.http.append({'host': self.name + '.example', 'path': what, 'auth': secret})  # The key goes out here only.
        body = json.dumps({'source': self.name, 'what': what})
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / (hashlib.sha256((self.name + what).encode()).hexdigest() + '.json')).write_text(body)

    def status(self, test=False):
        account = CREDENTIAL[self.name]
        return {'source': self.name, 'configured': bool(account and self.credentials.get(account)),
                'required': self.required, 'state': 'ready', 'detail': ''}

    def search(self, query, *, limit=10, **kwargs):
        self._call('search')
        return [dict(LECUN, sources=[self.name])]

    def paper(self, identifier):
        self._call('paper')
        return dict(LECUN, sources=[self.name]) if identifier.lower() == '10.1038/nature14539' else None

    def bibtex(self, identifier):
        self._call('bibtex')
        return '@article{LeCun_2015, title={Deep learning}, year={2015}, doi={10.1038/nature14539}}'


def fake_research_module(storage_of, http):
    """The 1B `research` package shape: `sources(app)` and `dispatch(app, ctx, name, arguments)`."""
    channel = FakeChannel()
    credentials = FakeCredentials(channel)
    module = types.ModuleType('research')
    module.__path__ = [str(ROOT / 'app/backend/research')]
    module.citations = citations
    module.credentials = credentials

    def sources(app):
        return [FakeSource(name, credentials, http, Path(app.storage) / 'research-cache') for name in CREDENTIAL]

    def dispatch(app, ctx, name, arguments):
        by_name = {s.name: s for s in sources(app)}

        def allowed(source):
            return ctx.authorize({'category': 'research', 'source': source, 'tool': name})['decision'] == 'allow'
        if name == 'verify_citations':
            return citations.check(arguments['references'], citations.source_lookup(by_name, allowed))
        if name == 'research_bibtex':
            entries = []
            for identifier in arguments['ids']:
                text = by_name['crossref'].bibtex(identifier) if allowed('crossref') else None
                entries.append({'id': identifier, 'bibtex': text, 'error': None if text else 'skipped'})
            return {'entries': entries}
        searched, skipped, papers = [], [], []
        for source in ('semantic_scholar', 'openalex', 'crossref'):
            if not allowed(source):
                skipped.append({'source': source, 'reason': 'denied'})
                continue
            searched.append(source)
            papers += by_name[source].search(arguments['query'])
        return {'papers': papers[:1], 'searched': searched, 'skipped': skipped}
    module.sources = sources
    module.dispatch = dispatch
    return module


class ResearchKeySafetyTests(e2e.EndToEndTeamTests):
    """Reuses the end-to-end setup (fake CLIs, real Application) with a research scenario."""

    def setUp(self):
        self.http = []
        self.module = fake_research_module(None, self.http)
        patcher = mock.patch.dict(sys.modules, {'research': self.module})
        patcher.start()
        self.addCleanup(patcher.stop)
        for account, secret in SECRETS.items():
            self.module.credentials.set(account, secret)
        super().setUp()

    def write_scenarios(self):
        orchestrator = [
            {'init': {}},
            *bridged('research_search', {'query': 'deep learning review', 'limit': 5}, 'toolu_search'),
            *bridged('research_bibtex', {'ids': ['10.1038/nature14539']}, 'toolu_bib'),
            *bridged('verify_citations', {'references': REFERENCES}, 'toolu_verify'),
            claude_text('# Related work\n\nDeep learning [1]. One reference could not be verified.'),
            claude_result(300, 50)]
        (self.root / 'claude.json').write_text(json.dumps({'by_prompt': [
            {'contains': 'You are the Orchestrator', 'turns': [orchestrator]}]}))
        (self.root / 'codex.json').write_text(json.dumps({'turns': []}))

    def test_orchestrator_team_runs_in_parallel_and_merges(self):
        pass  # The project flow is covered in test_e2e_team; this class runs the research flow below.

    def test_a_research_task_runs_without_a_project_and_no_key_leaks(self):
        default = self.call('scope_default', {'project_id': None, 'kind': 'research'})['scope']
        self.assertEqual(default['projects'], [])
        self.assertEqual(default['research']['sources'], {'semantic_scholar': 'allow', 'openalex': 'allow',
                                                          'crossref': 'allow', 'unpaywall': 'allow', 'arxiv': 'allow'})
        created = self.call('agent_create', {'project_id': None, 'kind': 'research', 'title': 'Related work'})
        task_id = created['task_id']
        state = self.call('state', {})
        self.assertEqual((state['project_id'], state['project'], state['task_id']), (None, 'Research', task_id))
        self.assertEqual(state['research'], {'selected': True, 'task_count': 1})
        self.assertEqual(state['tasks'][0]['kind'], 'research')
        self.assertEqual(state['task']['agent']['kind'], 'research')
        scope = self.call('scope_get', {'task_id': task_id})
        self.call('scope_approve', {'task_id': task_id, 'scope_version': scope['scope']['version'],
                                    'scope_digest': scope['scope_digest']})
        self.call('agent_message', {'task_id': task_id, 'text': 'Related work on deep learning, with references.'})
        wait_for(lambda: self.state(task_id) in ('idle', 'failed'), timeout=30, message='research task done')
        self.assertEqual(self.state(task_id), 'idle', self.events(task_id, 'error'))

        # No clone, no branch: the session ran in its scratch folder with no built-in tools.
        data = self.root / 'data'
        self.assertFalse((data / 'workspaces').exists() and any((data / 'workspaces').iterdir()))
        launch = next(e for e in self.logged(self.claude_log) if 'launch' in e and e['launch'][0] == '-p')
        self.assertEqual(launch['cwd'], str(data / 'research-runs' / task_id))
        self.assertEqual(dict(zip(launch['launch'], launch['launch'][1:]))['--tools'], '')

        # Research calls ran through the real bridge, as untrusted content, and were decided per source.
        replies = [e['mcp_reply']['content'][0]['text'] for e in self.logged(self.claude_log) if 'mcp_reply' in e]
        self.assertEqual(len(replies), 3)
        self.assertTrue(all(r.startswith('<untrusted-content>') for r in replies))
        report = self.events(task_id, 'citation_report')[0]['data']
        self.assertEqual(report['summary'], {'verified': 1, 'mismatch': 0, 'not_found': 1, 'retracted': 0,
                                             'unchecked': 0})
        usage = self.events(task_id, 'research_usage')
        self.assertTrue(usage)
        wait_for(lambda: sum(self.events(task_id, 'research_usage')[-1]['data']['calls'].values()) == len(self.http),
                 message='final usage')

        # Outputs in app data, listed by task_outputs.
        outputs = self.call('task_outputs', {'task_id': task_id})['outputs']
        self.assertEqual([o['name'] for o in outputs], ['report.md', 'references.bib'])
        folder = data / 'tasks' / task_id / 'outputs'
        self.assertIn('Deep learning [1]', (folder / 'report.md').read_text())
        bib = (folder / 'references.bib').read_text()
        self.assertIn('@article{LeCun_2015', bib)
        self.assertIn('% Left out, not found: Nobody, A. (2031).', bib)

        # The keys were used, but only by the (fake) source clients' requests.
        self.assertTrue({r['auth'] for r in self.http} >= {SECRETS['semantic_scholar'], SECRETS['crossref_email']})
        places = {'state.json': (data / 'state.json').read_text(),
                  'stdout': json.dumps(self.messages, ensure_ascii=False),
                  'tool results': json.dumps(replies, ensure_ascii=False)}
        for path in sorted(data.rglob('*')):
            if path.is_file() and not path.is_symlink() and 'codex-home' not in path.parts:
                places[str(path.relative_to(data))] = path.read_text(errors='replace')
        self.assertTrue(any(name.startswith('audit') for name in places), list(places))
        self.assertTrue(any(name.endswith('events.jsonl') for name in places))
        self.assertTrue(any(name.startswith('research-cache') for name in places))
        for secret in SECRETS.values():
            for name, text in places.items():
                self.assertNotIn(secret, text, name)
        # Audit records name the source and tool, never the query.
        audit_text = ''.join(t for n, t in places.items() if n.startswith('audit'))
        self.assertIn('"category":"research"', audit_text.replace(' ', ''))
        self.assertNotIn('deep learning review', audit_text)


if __name__ == '__main__':
    unittest.main()
