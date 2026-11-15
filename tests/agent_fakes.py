"""Fakes for scheduler and service tests: runtime, scope engine, audit, workspaces and connectors.

They stand in for 2A (runtime), 1E (scope.py, audit.py) and 1A (spaces) until those merge.
Nothing here starts a provider, touches the network or the Keychain.
"""
import copy
import hashlib
import json
import threading
import time


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def wait_for(predicate, timeout=5.0, message='condition'):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError('Timed out waiting for ' + message)


class FakeScope:
    """Implements the scope.py functions the scheduler and service call.

    `decide` reads `scope['fake_rules'][category]`: 'allow' (default), 'deny' or 'ask'.
    """
    def __init__(self):
        self.fail = False
        self.calls = []
        self.decide_options = []
        self.validated_with = []

    def digest(self, scope):
        return 'sha256:' + hashlib.sha256(canonical(scope)).hexdigest()

    def request_digest(self, request):
        return 'sha256:' + hashlib.sha256(canonical(request)).hexdigest()

    def validate(self, document, *, project_ids=None):
        self.validated_with.append(project_ids)
        if project_ids is not None and any(p.get('project_id') not in project_ids for p in document.get('projects', [])):
            raise ValueError('A project in the scope is not registered.')
        if not isinstance(document, dict) or not isinstance(document.get('version'), int):
            raise ValueError('Scope is invalid.')
        limits = document.get('limits', {})
        if not isinstance(limits.get('token_budget'), int) or not isinstance(limits.get('time_limit_s'), int):
            raise ValueError('Scope limits are invalid.')
        return document

    def default(self, task, project_ids):
        return {'v': 1, 'task_id': task['id'], 'version': 1,
                'projects': [{'project_id': p, 'access': 'write', 'read': ['**'], 'write': ['**'], 'deny': []}
                             for p in project_ids],
                'commands': {'workspace': 'allow', 'allow': [], 'deny': []},
                'network': {'default': 'ask', 'allow_hosts': [], 'deny_hosts': []},
                'apps': [], 'web_search': 'ask',
                'limits': {'token_budget': task.get('token_budget') or 250000, 'time_limit_s': 3600}}

    def merge_patch(self, scope, patch):
        merged = copy.deepcopy(scope)
        for key, value in patch.items():
            if isinstance(value, list):
                merged.setdefault(key, [])
                merged[key] += [v for v in value if v not in merged[key]]
            elif isinstance(value, dict):
                merged[key] = dict(merged.get(key, {}), **value)
            else:
                merged[key] = value
        return merged

    def apply_answer(self, document, approval, ask, answer, *, now):
        """Mirrors scope.apply_answer's checks (scope.py), with this fake's digest and merge."""
        self.answers = getattr(self, 'answers', []) + [(copy.deepcopy(ask), dict(answer))]
        if answer.get('ask_id') != ask.get('ask_id') or answer.get('request_digest') != ask.get('request_digest'):
            raise ValueError('The answer does not match the open question.')
        decision = answer.get('decision')
        if decision in ('deny', 'cancelled', 'text'):
            return {'scope': document, 'approval': approval, 'run': False, 'change': None}
        if decision not in ask.get('options', ()):
            raise ValueError('That answer was not offered for this question.')
        if decision == 'allow_once':
            if not approval or approval.get('scope_digest') != self.digest(document):
                raise ValueError('The task scope changed; approve it again before answering.')
            return {'scope': document, 'approval': approval, 'run': True, 'change': None}
        if not ask.get('scope_patch') or answer.get('scope_digest') != ask.get('patched_scope_digest'):
            raise ValueError('The scope change does not match the one that was shown.')
        amended = self.merge_patch(document, ask['scope_patch'])
        amended['version'] = document['version'] + 1
        if self.digest(amended) != ask['patched_scope_digest']:
            raise ValueError('The task scope changed since the question was asked; review it again.')
        return {'scope': amended, 'approval': {'v': 1, 'scope_version': amended['version'],
                                               'scope_digest': self.digest(amended), 'approved_at': 'now', 'by': 'user'},
                'run': True, 'change': 'amended'}

    def decide(self, scope, approval, request, *, workspace_roots, now, home=None, app_data=None, temp_roots=()):
        self.calls.append((copy.deepcopy(request), dict(workspace_roots)))
        self.decide_options.append({'home': home, 'app_data': app_data, 'temp_roots': temp_roots})
        if self.fail:
            raise RuntimeError('policy engine broke')
        base = {'scope_version': scope['version'], 'scope_digest': self.digest(scope), 'reason': ''}
        if not approval or approval.get('scope_digest') != self.digest(scope):
            return dict(base, decision='ask', rule='approval.missing', ask={
                'reason': 'scope_unapproved', 'title': 'Approve the scope', 'detail': '', 'options': [],
                'scope_patch': None, 'patched_scope_digest': None, 'request_digest': self.request_digest(request)})
        rule = scope.get('fake_rules', {}).get(request.get('category'), 'allow')
        if rule in ('allow', 'deny'):
            return dict(base, decision=rule, rule='fake.' + rule, ask=None)
        patch = {'fake_rules': {request['category']: 'allow'}}
        patched = self.merge_patch(scope, patch)
        patched['version'] = scope['version'] + 1
        return dict(base, decision='ask', rule='fake.ask', ask={
            'reason': 'outside_scope', 'title': 'Allow ' + request['category'] + '?', 'detail': 'Outside scope.',
            'options': ['allow_once', 'add_to_scope', 'deny'], 'scope_patch': patch,
            'patched_scope_digest': self.digest(patched), 'request_digest': self.request_digest(request)})


class FakeAudit:
    def __init__(self):
        self.records = []
        self.fail = False
        self.lock = threading.Lock()

    FIELDS = ('actor', 'kind', 'task_id', 'project_id', 'turn_id', 'call_id', 'request', 'decision', 'rule',
              'scope_version', 'scope_digest', 'outcome', 'idempotency_key', 'detail')

    def append(self, record):
        """Mirrors audit.AuditLog's validation: the log fills v/id/at/prev itself."""
        unknown = set(record) - set(self.FIELDS) - {'v'}
        if unknown:
            raise ValueError('The audit record has unknown fields: ' + ', '.join(sorted(unknown)))
        if record['kind'] in ('action', 'user_write') and record.get('outcome') not in ('succeeded', 'failed', 'outcome_unknown', 'cancelled'):
            raise ValueError('Action records need a known outcome.')
        if record['kind'] == 'scope' and record.get('request') is not None:
            raise ValueError('Scope records carry no request.')
        if self.fail:
            raise OSError('disk full')
        with self.lock:
            self.records.append(copy.deepcopy(record))


class FakeSession:
    def __init__(self, runtime, ctx):
        self.runtime = runtime
        self.ctx = ctx
        self.interrupted = threading.Event()
        self.killed = threading.Event()
        self.closed = False

    def run_turn(self, text, ctx):
        self.runtime.turns.append((ctx.task_id, text))
        return self.runtime.script(self, text, ctx)

    def interrupt(self):
        self.interrupted.set()

    def kill(self):
        self.killed.set()

    def close(self):
        self.closed = True


def default_script(session, text, ctx):
    ctx.emit('message', {'role': 'assistant', 'text': 'Done: ' + text, 'final': True}, item_id='m1')
    return {'status': 'completed', 'usage': {'input_tokens': 1000, 'output_tokens': 200}, 'error': None}


class FakeRuntime:
    name = 'codex'

    def __init__(self, script=default_script):
        self.script = script
        self.sessions = []
        self.turns = []
        self.fail_open = False

    def open(self, ctx):
        if self.fail_open:
            raise RuntimeError('no runtime')
        session = FakeSession(self, ctx)
        self.sessions.append(session)
        return session


def wait_interrupt(honor=True):
    """A turn that blocks until interrupted (or, when honor is False, until killed)."""
    def script(session, text, ctx):
        flag = session.interrupted if honor else session.killed
        if not flag.wait(10):
            raise AssertionError('turn was never stopped')
        return {'status': 'cancelled', 'usage': None, 'error': None}
    return script


class FakeWorkspaces:
    def __init__(self, root):
        self.root = root
        self.prepared = []
        self.published = []
        self.fail = False

    def prepare(self, task_id, project_id, source_path):
        if self.fail:
            raise OSError('clone failed')
        self.prepared.append((task_id, project_id))
        return {'path': str(self.root / task_id / project_id), 'branch': 'interspace/task-' + task_id[:8],
                'base_commit': 'b6bd066', 'target_branch': None}

    def publish(self, info, source_path):
        self.published.append(info['branch'])
        return info['branch']

    def diff(self, info):
        return {'files': [], 'patch': ''}


class FakeConnector:
    """A connector whose write can be held open to create lock contention."""
    app = 'notion'

    def __init__(self):
        self.gate = None
        self.active = 0
        self.max_active = 0
        self.writes = []
        self.lock = threading.Lock()
        self.fail_with = None

    def search(self, query, kinds=None, cursor=None, limit=25):
        return {'v': 1, 'items': [], 'next_cursor': None}

    def browse(self, parent=None, cursor=None, limit=50):
        return {'v': 1, 'items': [{'ref': 'notion:page:child', 'kind': 'page', 'title': 'Child', 'parent': parent,
                                   'url': None, 'updated_at': None, 'has_children': False, 'meta': {}}],
                'next_cursor': None}

    def read(self, ref, cursor=None):
        return {'v': 1, 'ref': ref, 'title': 'Page', 'format': 'markdown', 'text': 'hello', 'truncated': False,
                'next_cursor': None, 'version': None, 'url': None, 'meta': {}}

    def write(self, action, ref, params, idempotency_key):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.gate is not None:
                self.gate.wait(10)
            if self.fail_with is not None:
                raise self.fail_with
            with self.lock:
                self.writes.append((action, ref, idempotency_key))
            return {'v': 1, 'ok': True, 'action': action, 'ref': ref, 'result_ref': ref, 'url': None,
                    'version': None, 'replayed': False, 'summary': 'Appended.'}
        finally:
            with self.lock:
                self.active -= 1


def notion_tools(connector):
    """Two descriptors, shaped like spaces.base.tools output."""
    return {
        'notion_browse': {'v': 1, 'name': 'notion_browse', 'app': 'notion', 'title': 'Browse', 'description': '',
                          'input_schema': {}, 'effect': 'read', 'action': None, 'ref_param': 'parent'},
        'notion_read': {'v': 1, 'name': 'notion_read', 'app': 'notion', 'title': 'Read', 'description': '',
                        'input_schema': {}, 'effect': 'read', 'action': None, 'ref_param': 'ref'},
        'notion_page_append': {'v': 1, 'name': 'notion_page_append', 'app': 'notion', 'title': 'Append to page',
                               'description': '', 'input_schema': {}, 'effect': 'update',
                               'action': 'notion.page.append', 'ref_param': 'ref'},
    }


class MemoryStore:
    """The task store interface the scheduler needs, backed by a dict."""
    def __init__(self, scope_api):
        self.lock = threading.RLock()
        self.state = {'usage': [], 'projects': {}}
        self.scope_api = scope_api
        self.changes = 0

    def add_project(self, project_id, source_path='/tmp/repo'):
        self.state['projects'][project_id] = {'id': project_id, 'source_path': source_path, 'tasks': {}}

    def add_task(self, task_id, project_id, token_budget=250000, time_limit_s=3600, rules=None, approve=True):
        task = {'id': task_id, 'title': 'T', 'mode': 'agent', 'token_budget': token_budget,
                'agent': {'project_id': project_id, 'state': None, 'turns': 0, 'active_s': 0.0, 'workspaces': {}}}
        scope = self.scope_api.default(task, [project_id])
        scope['limits'] = {'token_budget': token_budget, 'time_limit_s': time_limit_s}
        if rules:
            scope['fake_rules'] = rules
        task['scope'] = scope
        task['scope_approval'] = None
        if approve:
            task['scope_approval'] = {'v': 1, 'scope_version': 1, 'scope_digest': self.scope_api.digest(scope),
                                      'approved_at': '2026-11-12T00:00:00.000Z', 'by': 'user'}
        self.state['projects'][project_id]['tasks'][task_id] = task
        return task

    def task(self, task_id):
        for project in self.state['projects'].values():
            if task_id in project['tasks']:
                return project['tasks'][task_id]
        raise ValueError('Unknown task.')

    def project(self, project_id):
        return self.state['projects'].get(project_id)

    def agent_tasks(self):
        for project in self.state['projects'].values():
            for task in project['tasks'].values():
                yield task

    def changed(self, task_id=None):
        self.changes += 1
