"""Browser end-to-end backend for research: the real service.Router and Application (scheduler, orchestrator, scope
engine, audit log, research sources and tool dispatch, citation checker, outputs, Keychain and save-panel bridge)
over the JSON-lines protocol the Swift shell carries.

Fakes, and only these:
- the agent runtimes, chosen per task and role (no provider CLI, model call or sign-in);
- the research HTTP transport, which answers from the recorded fixtures in tests/research/fixtures/ (no network);
- the Swift side of the bridge, played by tests/research-e2e-ui.mjs: it sends `bridge_hello`, keeps a fake Keychain
  and answers `keychain` and `save_panel` lines on stdin, so nothing here holds a key.

Run by tests/research-e2e-ui.mjs as `python3 research_backend.py <scratch root>`. Stdin lines `#release` (project
team) and `#release-research` (research team) let waiting subagents finish once the browser has seen them running
at once; every other line goes to the router.
"""
import json
from pathlib import Path
import subprocess
import sys
import threading
import urllib.parse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'app/backend'))
sys.path.insert(0, str(ROOT / 'tests'))
import service  # noqa: E402  (first: it puts pilot/ on the path for projects)
import projects  # noqa: E402
from research import http as research_http  # noqa: E402
from agent_fakes import FakeRuntime  # noqa: E402

FIXTURES = ROOT / 'tests/research/fixtures'
ROUTING = {'v': 1, 'orchestrator': {'provider': 'claude', 'model': None},
           'roles': {'researcher': {'provider': 'codex', 'model': None},
                     'implementer': {'provider': 'claude', 'model': None},
                     'reviewer': {'provider': 'codex', 'model': None},
                     'tester': {'provider': 'claude', 'model': None},
                     'writer': {'provider': 'claude', 'model': None},
                     'citation_checker': {'provider': 'codex', 'model': None}}}
GIT = ['git', '-c', 'user.name=T', '-c', 'user.email=t@example.invalid', '-c', 'core.hooksPath=/dev/null']

# The references the demo checks: one of each citation report status the fixtures can produce.
REFERENCES = [
    {'title': 'Attention Is All You Need', 'authors': ['Ashish Vaswani'], 'year': 2017, 'arxiv_id': '1706.03762'},
    {'title': 'Deep learning', 'authors': ['Yann LeCun'], 'year': 2012, 'doi': '10.1038/nature14539'},
    {'title': 'Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive developmental disorder in '
              'children', 'authors': ['A.J. Wakefield'], 'year': 1998, 'doi': '10.1016/S0140-6736(97)11096-0'},
    {'title': 'A synthetic survey of imaginary retrieval transformers', 'authors': ['Jane Placeholder'], 'year': 2020},
]

root = Path(sys.argv[1]).resolve()
out_lock = threading.Lock()
release = threading.Event()
release_research = threading.Event()


def emit(message):
    line = json.dumps(message)
    with out_lock:
        sys.stdout.write(line + '\n')
        sys.stdout.flush()


def git(*args, cwd):
    return subprocess.run(GIT + ['-C', str(cwd)] + list(args), check=True, capture_output=True, text=True)


# Fake research HTTP ---------------------------------------------------------------------------------------------

def _fixture(source, name):
    data = json.loads((FIXTURES / source / (name + '.json')).read_text(encoding='utf-8'))
    body = json.dumps(data['body']).encode('utf-8') if data.get('body') is not None else (data.get('text') or '').encode('utf-8')
    return data['status'], dict(data.get('headers') or {}), body


NOT_FOUND = (404, {'content-type': 'application/json'}, b'{"error": "not found"}')


class FixtureTransport:
    """Answers research GETs from the recorded fixtures, by host and path; anything else is a 404, which the source
    clients read as "not found". Records every URL so the browser test can show nothing left the machine."""

    def __init__(self):
        self.urls = []
        self.lock = threading.Lock()

    def send(self, method, url, headers, timeout_s):
        with self.lock:
            self.urls.append(url)
        parts = urllib.parse.urlsplit(url)
        host, path = parts.hostname, urllib.parse.unquote(parts.path)
        query = dict(urllib.parse.parse_qsl(parts.query))
        if host == 'export.arxiv.org' and path == '/api/query':
            ids = query.get('id_list', '')
            if ids.startswith('1706.03762'):
                return _fixture('arxiv', 'lookup_1706.03762v1' if ids.endswith('v1') else 'lookup_1706.03762')
            if ids:
                return _fixture('arxiv', 'lookup_nonexistent')
            return _fixture('arxiv', 'search_title_2017')
        if host == 'arxiv.org' and path.startswith('/bibtex/1706.03762'):
            return _fixture('arxiv', 'bibtex_1706.03762')
        if host == 'api.semanticscholar.org':
            if path == '/graph/v1/paper/search':
                return _fixture('semantic_scholar', 'search_attention_2017')
            if path == '/graph/v1/paper/search/match':
                if 'attention is all you need' in query.get('query', '').lower():
                    return _fixture('semantic_scholar', 'match_title')
                return NOT_FOUND
            if path.endswith('/citations'):
                return _fixture('semantic_scholar', 'citations')
            if path.endswith('/references'):
                return _fixture('semantic_scholar', 'references')
            if path.upper() == '/GRAPH/V1/PAPER/ARXIV:1706.03762':
                return _fixture('semantic_scholar', 'lookup_arxiv')
            return NOT_FOUND
        if host == 'api.openalex.org':
            if path == '/works':
                return _fixture('openalex', 'search_synthetic')
            if path.lower() == '/works/doi:10.48550/arxiv.1706.03762':
                return _fixture('openalex', 'lookup_arxiv_doi_vaswani')
            if path.lower() == '/works/doi:10.1016/s0140-6736(97)11096-0':
                return _fixture('openalex', 'lookup_doi_wakefield')
            return NOT_FOUND
        if host == 'api.crossref.org':
            lowered = path.lower()
            if lowered == '/works':
                if query.get('filter', '').startswith('updates:'):
                    return _fixture('crossref', 'retraction_notices_for_wakefield')
                return _fixture('crossref', 'search_bibliographic_2015')
            if lowered == '/works/10.1038/nature14539/transform/application/x-bibtex':
                return _fixture('crossref', 'bibtex_transform_lecun')
            if lowered == '/works/10.1038/nature14539':
                return _fixture('crossref', 'lookup_lecun')
            if lowered == '/works/10.1016/s0140-6736(97)11096-0':
                return _fixture('crossref', 'lookup_wakefield_retracted')
            return NOT_FOUND
        if host == 'api.unpaywall.org':
            lowered = path.lower()
            if lowered == '/v2/10.1038/nature14539':
                return _fixture('unpaywall', 'lookup_lecun')
            if lowered == '/v2/10.1016/s0140-6736(97)11096-0':
                return _fixture('unpaywall', 'lookup_wakefield')
            return _fixture('unpaywall', 'lookup_unknown')
        return NOT_FOUND


transport = FixtureTransport()


# A disposable repository for the project task: `main` is checked out.
repo = root / 'repo'
repo.mkdir()
subprocess.run(GIT + ['init', '-q', '-b', 'main', str(repo)], check=True)
(repo / 'parser.py').write_text('def parse(x):\n    return x\n')
git('add', '.', cwd=repo)
git('commit', '-qm', 'base', cwd=repo)


class Provider:
    def status(self):
        return {'ready': True, 'message': 'End-to-end harness (fake runtimes)'}

    def sign_in(self, cancel, emit):
        pass


# Fake runtimes ----------------------------------------------------------------------------------------------------

def say(ctx, text, suffix=''):
    ctx.emit('message', {'role': 'assistant', 'text': text, 'final': True}, item_id='m' + suffix + '-' + ctx.turn_id[:10])


def done(tokens=900):
    return {'status': 'completed', 'usage': {'input_tokens': tokens, 'output_tokens': 100}, 'error': None}


REPORT = """# Attention-based sequence models: a short review

Transformers replaced recurrence with **self-attention** [Vaswani et al., 2017](https://arxiv.org/abs/1706.03762).
Earlier deep learning surveys framed the field (LeCun, Bengio and Hinton).

## Findings
- Self-attention trains in parallel and scales with data.
- Follow-up work cites the original paper widely.

## How the references were checked
- Vaswani et al. (2017): verified by the citation checker.
- LeCun et al.: the year given (2012) differs from the published record (2015).
- Wakefield et al. (1998): retracted; not cited as evidence.
- "A synthetic survey of imaginary retrieval transformers": not found in any source, so it is not cited.

## References
1. Vaswani, A. et al. (2017). Attention is all you need. arXiv:1706.03762
2. LeCun, Y., Bengio, Y. and Hinton, G. (2015). Deep learning. Nature. doi:10.1038/nature14539
"""


def literature_review(ctx, text):
    say(ctx, 'I will search the research sources first.', 'a')
    ctx.call_tool('research_search', {'query': 'attention is all you need transformer', 'limit': 6})
    ctx.call_tool('research_citations', {'id': 'arXiv:1706.03762', 'direction': 'references', 'limit': 2})
    proposed = ctx.call_tool('propose_team', {
        'summary': 'Read the key papers, then check every reference before I write the review.',
        'members': [{'role': 'researcher', 'brief': 'Read the transformer paper and find open-access copies.'},
                    {'role': 'citation_checker', 'brief': 'Check every reference with the citation checker.'}]})
    if proposed.get('status') not in ('approved', 'changed'):
        say(ctx, 'The team was not approved, so I stopped.', 'b')
        return done()
    ctx.call_tool('wait_for', {'team_id': proposed['team_id'], 'timeout_s': 90})
    ctx.call_tool('save_report', {'markdown': REPORT})  # Only a saved report becomes report.md.
    say(ctx, REPORT, 'c')
    return done()


def verify_references(ctx, text):
    lines = [line.strip() for line in text.split('References:', 1)[-1].splitlines() if line.strip()]
    say(ctx, 'Checking %d references with the citation checker.' % len(lines), 'a')
    report = ctx.call_tool('verify_citations', {'references': [{'raw': line} for line in lines]})
    summary = report.get('summary') or {}
    checked = ('# Reference check\n\n' + '\n'.join('- %s: %s' % (k.replace('_', ' '), summary.get(k, 0))
                                                   for k in ('verified', 'mismatch', 'not_found', 'retracted', 'unchecked'))
               + '\n\nOnly the references marked verified matched a published record.\n\n## References\n'
               + '\n'.join('%d. %s' % (i + 1, line) for i, line in enumerate(lines)))
    ctx.call_tool('save_report', {'markdown': checked})
    say(ctx, checked, 'b')
    return done()


def coding(ctx, text):
    say(ctx, 'I will propose a team for: ' + text, 'a')
    proposed = ctx.call_tool('propose_team', {
        'summary': 'Map the parser, then add input validation.',
        'members': [{'role': 'researcher', 'brief': 'Map where parse() is called.'},
                    {'role': 'implementer', 'brief': 'Add input validation to parse().'}]})
    if proposed.get('status') in ('approved', 'changed'):
        waited = ctx.call_tool('wait_for', {'team_id': proposed['team_id'], 'timeout_s': 60})
        states = ', '.join(m['member_id'] + ' ' + m['state'] for m in waited.get('members', []))
        say(ctx, 'Team finished: ' + states, 'b')
    return done()


def orchestrator_turn(session, text, ctx):
    if not ctx.research_only:
        return coding(ctx, text)
    if 'References:' in text:
        return verify_references(ctx, text)
    return literature_review(ctx, text)


def research_child(ctx):
    item = 'c-' + ctx.turn_id[:10]
    ctx.emit('message_delta', {'role': 'assistant', 'text_delta': ctx.role.replace('_', ' ').capitalize() + ' started'},
             item_id=item)
    if not release_research.wait(90):
        return {'status': 'failed', 'usage': None, 'error': {'code': 'harness', 'message': 'Never released'}}
    if ctx.role == 'citation_checker':
        report = ctx.call_tool('verify_citations', {'references': REFERENCES})
        summary = report.get('summary') or {}
        ctx.emit('message', {'role': 'assistant', 'final': True, 'text': 'Checked %d references: %d verified.' % (
            len(report.get('references') or []), summary.get('verified', 0))}, item_id=item)
    else:
        ctx.call_tool('research_paper', {'id': 'arXiv:1706.03762'})
        ctx.call_tool('research_fulltext', {'id': '10.1038/nature14539'})
        ctx.emit('message', {'role': 'assistant', 'final': True,
                             'text': 'Read <i>Attention Is All You Need</i>; an open copy of the LeCun survey exists.'},
                 item_id=item)
    return done(400)


def coding_child(ctx):
    item = 'c-' + ctx.turn_id[:10]
    ctx.emit('message_delta', {'role': 'assistant', 'text_delta': ctx.role.capitalize() + ' started'}, item_id=item)
    if not release.wait(60):
        return {'status': 'failed', 'usage': None, 'error': {'code': 'harness', 'message': 'Never released'}}
    if ctx.role == 'implementer':
        work = Path(ctx.primary_workspace)
        (work / 'parser.py').write_text('def parse(x):\n    if x is None:\n        raise ValueError("no input")\n'
                                        '    return x\n')
        git('commit', '-qam', 'Validate parse() input', cwd=work)
        ctx.emit('message', {'role': 'assistant', 'text': 'Added validation to parse().', 'final': True}, item_id=item)
    else:
        ctx.emit('message', {'role': 'assistant', 'text': 'parse() is called from cli.py only.', 'final': True},
                 item_id=item)
    return done(400)


def child_turn(session, text, ctx):
    return research_child(ctx) if ctx.research_only else coding_child(ctx)


orchestrator_runtime = FakeRuntime(orchestrator_turn)
child_runtimes = {'codex': FakeRuntime(child_turn), 'claude': FakeRuntime(child_turn)}
child_runtimes['claude'].name = 'claude'
app = None


def runtime_for(task_id):
    task = app.store.task(task_id)
    if task.get('role') == 'orchestrator':
        orchestrator_runtime.name = task.get('provider') or 'claude'
        return orchestrator_runtime
    return child_runtimes['claude' if task.get('provider') == 'claude' else 'codex']


app = service.Application(root / 'data', provider=Provider(), emit=emit, runtime_factory=runtime_for,
                          interrupt_grace_s=0.5)
# The research sources reach the fixtures, never the network; rate-limit waits are skipped.
app.http = research_http.Http(transport, sleep=lambda seconds: None)
project = projects.new_project(repo)
with app.lock:
    app.state['projects'][project['id']] = project
    app.state['selected_project_id'] = project['id']
    app.state['routing'] = json.loads(json.dumps(ROUTING))
    # The browser checks the full team and subagent cards, which the default Simple conversation folds.
    app.state['display'] = {'detail': 'detailed'}
    app.persist()

PROVIDERS = [
    {'name': 'claude', 'title': 'Claude', 'models': ['claude-sonnet-5-5', 'claude-opus-5-5', 'claude-haiku-5-5'],
     'default_model': 'claude-sonnet-5-5', 'capabilities': {'write': True, 'web_search': True, 'approvals': True}},
    {'name': 'codex', 'title': 'Codex', 'models': [], 'default_model': None,
     'capabilities': {'write': True, 'web_search': True, 'approvals': True}}]


# Settings and New task read providers_list; the real one would run each provider CLI's status check.
def providers_list(app_, params):
    return {'providers': PROVIDERS,
            'status': [{'provider': p['name'], 'state': 'signed_in', 'account': 'Harness', 'detail': ''} for p in PROVIDERS],
            'routing': app_.state.get('routing') or ROUTING}


def harness_urls(app_, params):
    """Test-only: every research URL the fake transport answered, so the browser can check hosts and secrets."""
    with transport.lock:
        return {'urls': list(transport.urls)}


app.extensions['providers_list'] = providers_list
app.extensions['harness_urls'] = harness_urls
router = service.Router(app, emit)
for line in sys.stdin:
    if line.strip() == '#release':
        release.set()
        continue
    if line.strip() == '#release-research':
        release_research.set()
        continue
    router.route(line)
release.set()
release_research.set()
router.close(5)
app.scheduler.shutdown(5)
