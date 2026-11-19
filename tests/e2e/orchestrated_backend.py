"""Browser end-to-end backend: the real service.Router and Application (scheduler, orchestrator, scope engine,
audit log, git workspaces, review and merge) over the JSON-lines protocol the Swift shell carries.

Only the agent runtimes are fakes, chosen per task role: no provider CLI, model call, sign-in or network.
Run by tests/e2e-ui.mjs as `python3 orchestrated_backend.py <scratch root>`; the repository it creates is
disposable. A stdin line `#release` lets the waiting subagents finish (the browser first checks that both are
running at once); every other line goes to the router.

The Orchestrator runs on Claude through routing.orchestrator: agent_create omits the provider, as the UI does.
"""
import json
from pathlib import Path
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'app/backend'))
sys.path.insert(0, str(ROOT / 'tests'))
import service  # noqa: E402  (first: it puts pilot/ on the path for projects)
import projects  # noqa: E402
from agent_fakes import FakeRuntime  # noqa: E402

ORCHESTRATOR = 'claude'
ROLES = ('researcher', 'implementer', 'reviewer', 'tester', 'writer')
ROUTING = {'v': 1, 'orchestrator': {'provider': ORCHESTRATOR, 'model': None},
           'roles': {'researcher': {'provider': 'codex', 'model': None},
                     'implementer': {'provider': 'claude', 'model': None},
                     'reviewer': {'provider': 'codex', 'model': None},
                     'tester': {'provider': 'claude', 'model': None},
                     'writer': {'provider': 'claude', 'model': None}}}
GIT = ['git', '-c', 'user.name=T', '-c', 'user.email=t@example.invalid', '-c', 'core.hooksPath=/dev/null']

root = Path(sys.argv[1]).resolve()
out_lock = threading.Lock()
release = threading.Event()


def emit(message):
    line = json.dumps(message)
    with out_lock:
        sys.stdout.write(line + '\n')
        sys.stdout.flush()


def git(*args, cwd):
    return subprocess.run(GIT + ['-C', str(cwd)] + list(args), check=True, capture_output=True, text=True)


# A disposable repository: `main` is checked out, `release` is the non-checked-out merge target.
repo = root / 'repo'
repo.mkdir()
subprocess.run(GIT + ['init', '-q', '-b', 'main', str(repo)], check=True)
(repo / 'parser.py').write_text('def parse(x):\n    return x\n')
git('add', '.', cwd=repo)
git('commit', '-qm', 'base', cwd=repo)
git('branch', 'release', cwd=repo)


class Provider:
    def status(self):
        return {'ready': True, 'message': 'End-to-end harness (fake runtimes)'}

    def sign_in(self, cancel, emit):
        pass


def orchestrator_turn(session, text, ctx):
    ctx.emit('message', {'role': 'assistant', 'text': 'I will propose a team for: ' + text, 'final': True},
             item_id='o-' + ctx.turn_id[:10])
    proposed = ctx.orchestrate('propose_team', {
        'summary': 'Map the parser, then add input validation.',
        'members': [{'role': 'researcher', 'brief': 'Map where parse() is called.'},
                    {'role': 'implementer', 'brief': 'Add input validation to parse().', 'provider': 'codex'}],
        'reason_for_overrides': 'Codex <b>already</b> mapped this module'})
    if proposed.get('status') in ('approved', 'changed'):
        waited = ctx.orchestrate('wait_for', {'team_id': proposed['team_id'], 'timeout_s': 60})
        states = ', '.join(m['member_id'] + ' ' + m['state'] for m in waited.get('members', []))
        ctx.emit('message', {'role': 'assistant', 'text': 'Team finished: ' + states, 'final': True},
                 item_id='o2-' + ctx.turn_id[:10])
    return {'status': 'completed', 'usage': {'input_tokens': 900, 'output_tokens': 100}, 'error': None}


def child_turn(session, text, ctx):
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
        ctx.emit('message', {'role': 'assistant', 'text': 'parse() is called from <i>cli.py</i> only.', 'final': True},
                 item_id=item)
    return {'status': 'completed', 'usage': {'input_tokens': 400, 'output_tokens': 50}, 'error': None}


orchestrator_runtime = FakeRuntime(orchestrator_turn)
child_runtimes = {'codex': FakeRuntime(child_turn), 'claude': FakeRuntime(child_turn)}
child_runtimes['claude'].name = 'claude'
app = None


def runtime_for(task_id):
    task = app.store.task(task_id)
    if task.get('role') == 'orchestrator':
        orchestrator_runtime.name = task.get('provider') or ORCHESTRATOR
        return orchestrator_runtime
    return child_runtimes['claude' if task.get('provider') == 'claude' else 'codex']


app = service.Application(root / 'data', provider=Provider(), emit=emit, runtime_factory=runtime_for,
                          interrupt_grace_s=0.5)
project = projects.new_project(repo)
with app.lock:
    app.state['projects'][project['id']] = project
    app.state['selected_project_id'] = project['id']
    app.state['routing'] = json.loads(json.dumps(ROUTING))
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


app.extensions['providers_list'] = providers_list
router = service.Router(app, emit)
for line in sys.stdin:
    if line.strip() == '#release':
        release.set()
        continue
    router.route(line)
release.set()
router.close(5)
app.scheduler.shutdown(5)
