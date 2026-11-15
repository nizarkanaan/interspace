"""Concurrent agentic tasks: queue, per-task workers, cancel, time limits, locks, events and the run context.

Contract: docs/superpowers/specs/agentic-spaces/scheduler.md and events.md. Runtimes (2A, 2B) implement
`Runtime.open(ctx) -> Session` with `run_turn`, `interrupt`, `kill` and `close`; this module never starts a
provider itself. Every public method is thread-safe and returns quickly; long work runs on task threads.

The task store passed as `tasks` provides: `lock` (the application RLock), `state` (with `usage`),
`task(task_id)`, `project(project_id)`, `agent_tasks()` and `changed(task_id=None)` (persist, then publish
state at a throttled rate). The scheduler holds `tasks.lock` only to read or change shared state, never
across a runtime call or a lock wait.
"""
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

import budget

from timeutil import iso_time

shutil_which = shutil.which

V = 1
MAX_EVENT_BYTES = 64 * 1024
MAX_BLOB_BYTES = 2 * 1024 * 1024
MAX_PATCH_CHARS = 48 * 1024
MAX_MESSAGE_CHARS = 20000
DEFAULT_MAX_RUNNING = 4
MAX_RUNNING_RANGE = (1, 16)
LOCK_TIMEOUT_S = 300
INTERRUPT_GRACE_S = 10  # 0B measured turn/interrupt ending a turn in about 0.1 s; kill the process group after this long.
GIT_TIMEOUT_S = 120

QUEUED = 'queued'
COUNTED = ('starting', 'running', 'waiting_lock')  # Only these count against the time limit.
TERMINAL = ('completed', 'failed', 'cancelled', 'budget_exhausted', 'time_limit', 'interrupted')
RECOVER = ('queued', 'starting', 'running', 'waiting_lock', 'paused_ask', 'paused_scope', 'cancelling')
STATES = ('queued', 'starting', 'running', 'waiting_lock', 'paused_ask', 'paused_scope', 'idle', 'cancelling') + TERMINAL
RUNTIME_KINDS = ('message_delta', 'message', 'reasoning', 'plan_update', 'tool_call', 'tool_output_delta',
                 'tool_result', 'diff')
ANSWERS = ('allow_once', 'add_to_scope', 'deny', 'text')
IDENTIFIER = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
BLOB_ID = re.compile(r'^[0-9a-f]{32}$')


class LockTimeout(ValueError):
    """A lock wait reached its time limit."""


class Cancelled(ValueError):
    """A wait ended because the task was cancelled or stopped."""


def validate_max_running(value):
    if type(value) is not int or not MAX_RUNNING_RANGE[0] <= value <= MAX_RUNNING_RANGE[1]:
        raise ValueError('Parallel tasks must be a whole number from 1 to 16.')
    return value


def _runtime_id(value, name):
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError('Invalid ' + name + ' from the runtime.')
    return value


# ---------------------------------------------------------------------------------------------- locks

class Locks:
    """FIFO in-process locks keyed by `project:<id>` or `app:<ref>`. A task holds at most one at a time."""

    def __init__(self, poll_s=0.05):
        self._cond = threading.Condition()
        self._holders = {}
        self._queues = {}
        self._held_by_task = {}
        self._poll_s = poll_s

    def acquire(self, key, task_id, cancel, timeout_s=LOCK_TIMEOUT_S):
        ticket = (task_id, object())
        deadline = time.monotonic() + timeout_s
        with self._cond:
            if task_id is not None and task_id in self._held_by_task:
                raise ValueError('A task holds at most one lock at a time.')
            queue = self._queues.setdefault(key, [])
            queue.append(ticket)
            try:
                while key in self._holders or queue[0] is not ticket:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled('Stopped while waiting for ' + key + '.')
                    left = deadline - time.monotonic()
                    if left <= 0:
                        raise LockTimeout('Timed out waiting for ' + key + '.')
                    self._cond.wait(min(left, self._poll_s))
            except BaseException:
                queue.remove(ticket)
                if not queue:
                    del self._queues[key]
                self._cond.notify_all()
                raise
            queue.pop(0)
            if not queue:
                del self._queues[key]
            self._holders[key] = task_id
            if task_id is not None:
                self._held_by_task[task_id] = key

    def release(self, key, task_id):
        with self._cond:
            if key not in self._holders or self._holders[key] != task_id:
                raise ValueError('This lock is not held by the task.')
            del self._holders[key]
            self._held_by_task.pop(task_id, None)
            self._cond.notify_all()

    def holders(self):
        with self._cond:
            return dict(self._holders)

    def waiting(self, key):
        with self._cond:
            return [ticket[0] for ticket in self._queues.get(key, [])]

    def wake(self):
        with self._cond:
            self._cond.notify_all()


# ------------------------------------------------------------------------------------------- events

class EventLog:
    """Per-task event files: `<root>/<task_id>/events.jsonl` and `blobs/<blob_id>`.

    An event is appended and flushed before it is forwarded, so a reader can always replay what the UI saw.
    """

    def __init__(self, root, forward, clock=time.time):
        self.root = Path(root)
        self.forward = forward
        self.clock = clock
        self._guard = threading.Lock()
        self._locks = {}
        self._seq = {}

    def _task_dir(self, task_id):
        if not isinstance(task_id, str) or not IDENTIFIER.match(task_id):
            raise ValueError('Unknown task.')
        return self.root / task_id

    def _lock(self, task_id):
        with self._guard:
            return self._locks.setdefault(task_id, threading.RLock())

    def _lines(self, task_id):
        path = self._task_dir(task_id) / 'events.jsonl'
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return []
        events = []
        for line in raw.split(b'\n'):
            try:
                event = json.loads(line.decode('utf-8'))
            except ValueError:
                continue  # A partial last line from a crash mid-write.
            if isinstance(event, dict) and event.get('v') == V and type(event.get('seq')) is int:
                events.append(event)
        return events

    def _last(self, task_id):
        if task_id not in self._seq:
            path = self._task_dir(task_id) / 'events.jsonl'
            if path.exists():
                raw = path.read_bytes()
                if raw and not raw.endswith(b'\n'):
                    # Drop a partial line so the next event starts on its own line.
                    with path.open('r+b') as handle:
                        handle.truncate(raw.rfind(b'\n') + 1)
            events = self._lines(task_id)
            self._seq[task_id] = events[-1]['seq'] if events else 0
        return self._seq[task_id]

    def last_seq(self, task_id):
        with self._lock(task_id):
            return self._last(task_id)

    def append(self, task_id, project_id, kind, data, turn_id=None, item_id=None):
        directory = self._task_dir(task_id)
        with self._lock(task_id):
            seq = self._last(task_id) + 1
            event = {'v': V, 'task_id': task_id, 'project_id': project_id, 'seq': seq, 'at': iso_time(self.clock()),
                     'kind': kind, 'turn_id': turn_id, 'item_id': item_id, 'data': copy.deepcopy(data)}
            event = self._bounded(directory, event)
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / 'events.jsonl').open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(event, ensure_ascii=False, separators=(',', ':')) + '\n')
                handle.flush()
            self._seq[task_id] = seq
            self.forward(event)  # Inside the task lock, so events reach the UI in seq order.
        return event

    def _store_blob(self, directory, text):
        blob_id = uuid.uuid4().hex
        (directory / 'blobs').mkdir(parents=True, exist_ok=True)
        (directory / 'blobs' / blob_id).write_text(text, encoding='utf-8')
        return blob_id

    def _bounded(self, directory, event):
        def size():
            return len(json.dumps(event, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
        if size() <= MAX_EVENT_BYTES:
            return event
        # Move the longest text field (in data or one level down) to a blob, then cut it until the event fits.
        for _ in range(4):
            holder, key = None, None
            longest = -1
            for container in [event['data']] + [v for v in event['data'].values() if isinstance(v, dict)]:
                for name, value in container.items():
                    if isinstance(value, str) and len(value) > longest:
                        holder, key, longest = container, name, len(value)
            if holder is None or longest < 1024:
                break
            text = holder[key]
            holder['blob_id'] = self._store_blob(directory, text)
            holder['truncated'] = True
            while size() > MAX_EVENT_BYTES and len(holder[key]) > 0:
                holder[key] = holder[key][:len(holder[key]) // 2]
            if size() <= MAX_EVENT_BYTES:
                return event
        whole = json.dumps(event['data'], ensure_ascii=False)
        event['data'] = {'truncated': True, 'blob_id': self._store_blob(directory, whole)}
        return event

    def read(self, task_id, after_seq, limit=500):
        if type(after_seq) is not int or after_seq < 0:
            raise ValueError('after_seq must be a whole number of at least 0.')
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('limit must be from 1 to 1000.')
        with self._lock(task_id):
            last = self._last(task_id)
            later = [e for e in self._lines(task_id) if e['seq'] > after_seq]
        return {'events': later[:limit], 'last_seq': last, 'complete': len(later) <= limit}

    def blob(self, task_id, blob_id):
        directory = self._task_dir(task_id)
        if not isinstance(blob_id, str) or not BLOB_ID.match(blob_id):
            raise ValueError('Unknown attachment.')
        try:
            raw = (directory / 'blobs' / blob_id).read_bytes()[:MAX_BLOB_BYTES]
        except FileNotFoundError:
            raise ValueError('Unknown attachment.') from None
        return {'blob_id': blob_id, 'text': raw.decode('utf-8', 'ignore')}


# ------------------------------------------------------------------------------------------- budget

class BudgetGate:
    """The per-task token gate for agent turns, over the shared `state['usage']` ledger. Call under the store lock."""

    def __init__(self, store):
        self.store = store

    def reserve(self, task, text, provider, turn_id):
        return budget.reserve(self.store.state, task, role='Agent', prompt=text, project_id=task['agent']['project_id'],
                              estimate=budget.estimate_turn(len(text)), provider=provider, turn_id=turn_id,
                              call_kind='agent_turn')

    def entry(self, entry_id):
        return next(e for e in self.store.state['usage'] if isinstance(e, dict) and e.get('id') == entry_id)

    def settle(self, entry_id, usage, outcome):
        return budget.settle(self.store.state, entry_id, usage, outcome)

    def release(self, entry_id):
        budget.release(self.store.state, entry_id)

    def totals(self, task):
        return budget.ledger(self.store.state, task['id'], task.get('token_budget'))


# --------------------------------------------------------------------------------------- workspaces

def _git_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_TERMINAL_PROMPT='0', GIT_CONFIG_NOSYSTEM='1')
    return env


class Workspaces:
    """Isolated task clones (scope.md): `<root>/<task_id>/<project_id>`, published back only as the task branch."""

    def __init__(self, root):
        self.root = Path(root)

    @staticmethod
    def _git(args, env=None, check=True):
        # User hooks never run: Interspace's own git calls must not execute repository code.
        command = ['git', '-c', 'core.hooksPath=/dev/null'] + list(args)
        return subprocess.run(command, check=check, capture_output=True, text=True, timeout=GIT_TIMEOUT_S,
                              env=env or _git_env(), stdin=subprocess.DEVNULL)

    def prepare(self, task_id, project_id, source_path):
        if not IDENTIFIER.match(task_id) or not IDENTIFIER.match(project_id):
            raise ValueError('Invalid task or project.')
        path = self.root / task_id / project_id
        branch = 'interspace/task-' + task_id[:8]
        if (path / '.git').is_dir():
            base = self._git(['-C', str(path), 'config', 'interspace.base-commit']).stdout.strip()
            return {'path': str(path), 'branch': branch, 'base_commit': base, 'target_branch': None}
        base = self._git(['-C', str(source_path), 'rev-parse', 'HEAD']).stdout.strip()
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.parent / ('.partial-' + project_id + '-' + uuid.uuid4().hex)
        try:
            self._git(['clone', '--quiet', '--local', '--no-checkout', str(source_path), str(partial)])
            self._git(['-C', str(partial), 'checkout', '--quiet', '-b', branch, base])
            self._git(['-C', str(partial), 'remote', 'remove', 'origin'])
            self._git(['-C', str(partial), 'config', 'interspace.base-commit', base])
            os.rename(str(partial), str(path))  # A half-made clone is never reused.
        finally:
            if partial.exists():
                shutil.rmtree(str(partial), ignore_errors=True)
        return {'path': str(path), 'branch': branch, 'base_commit': base, 'target_branch': None}

    def publish(self, info, source_path):
        """Write only the task's branch into the user's repository. The chosen name is kept in `info`."""
        target = info.get('target_branch')
        if not target:
            target, number = info['branch'], 1
            while self._git(['-C', str(source_path), 'show-ref', '--verify', '--quiet', 'refs/heads/' + target],
                            check=False).returncode == 0:
                number += 1
                target = info['branch'] + '-' + str(number)
            info['target_branch'] = target
        self._git(['-C', str(source_path), 'fetch', '--quiet', '--no-tags', info['path'],
                   '+refs/heads/' + info['branch'] + ':refs/heads/' + target])
        return target

    def diff(self, info):
        """The whole workspace (committed, staged, unstaged and new files) against the base commit."""
        work = info['path']
        git_dir = Path(work) / '.git'
        handle, index = tempfile.mkstemp(prefix='interspace-index-', dir=str(git_dir))
        os.close(handle)
        try:
            shutil.copyfile(str(git_dir / 'index'), index)
            env = dict(_git_env(), GIT_INDEX_FILE=index)  # The agent's own index is never touched.
            self._git(['-C', work, 'add', '--all'], env=env)
            names = self._git(['-C', work, 'diff', '--cached', '--no-renames', '--name-status', info['base_commit']], env=env).stdout
            counts = self._git(['-C', work, 'diff', '--cached', '--no-renames', '--numstat', info['base_commit']], env=env).stdout
            patch = self._git(['-C', work, 'diff', '--cached', '--no-renames', info['base_commit']], env=env).stdout
        finally:
            os.unlink(index)
        changes = {'A': 'add', 'M': 'modify', 'D': 'delete'}
        stats = {}
        for line in counts.splitlines():
            parts = line.split('\t', 2)
            if len(parts) == 3:
                stats[parts[2]] = parts[:2]
        files = []
        for line in names.splitlines():
            parts = line.split('\t')
            if len(parts) != 2:
                continue
            added, deleted = stats.get(parts[1], ['0', '0'])
            binary = added == '-'
            files.append({'path': parts[1], 'change': changes.get(parts[0][:1], 'modify'), 'old_path': None,
                          'additions': 0 if binary else int(added), 'deletions': 0 if binary else int(deleted),
                          'binary': binary})
        return {'files': files, 'patch': patch}


# ---------------------------------------------------------------------------------------- recovery

def recover(store, events):
    """After a restart, unfinished agentic tasks become `interrupted`. Nothing resumes; clones and branches stay."""
    changed = []
    with store.lock:
        for task in store.agent_tasks():
            agent = task.get('agent') if isinstance(task, dict) else None
            if task.get('mode') != 'agent' or not isinstance(agent, dict) or agent.get('state') not in RECOVER:
                continue
            agent.update(state='interrupted', detail='', reason=None)
            events.append(task['id'], agent.get('project_id'), 'status',
                          {'state': 'interrupted', 'detail': 'The app closed while this task was working.',
                           'queue_position': None, 'reason': None})
            changed.append(task['id'])
        if changed:
            store.changed()
    return changed


# ----------------------------------------------------------------------------------- run context

class RunContext:
    """What a runtime may use during a turn. Everything goes through the scheduler's checks."""

    def __init__(self, scheduler, run, task, workspaces):
        self._scheduler = scheduler
        self._run = run
        self.task_id = run.task_id
        self.turn_id = run.turn_id
        self.project_ids = [p.get('project_id') for p in task['scope'].get('projects', [])]
        self.workspaces = {pid: info['path'] for pid, info in workspaces.items()}
        self.primary_workspace = self.workspaces.get(run.project_id) or next(iter(self.workspaces.values()), None)
        self.scope = copy.deepcopy(task['scope'])  # For prompts and display only; decisions read the live scope.
        # A model id from the signed-in account's model list (0B-7), or None for the provider default.
        self.model = task.get('model') if isinstance(task.get('model'), str) and task.get('model') else None
        self.cancel = run.cancel

    def authorize(self, request, call_id):
        return self._scheduler._authorize(self._run, request, _runtime_id(call_id, 'call_id'))

    def emit(self, kind, data, *, turn_id=None, item_id=None):
        if kind not in RUNTIME_KINDS or not isinstance(data, dict):
            raise ValueError('The runtime may not emit this event.')
        if kind == 'message' and data.get('role') != 'assistant':
            raise ValueError('The runtime may only emit assistant messages.')
        if item_id is not None:
            _runtime_id(item_id, 'item_id')
        return self._scheduler._emit(self._run, kind, data, turn_id=turn_id or self.turn_id, item_id=item_id)

    def call_tool(self, name, arguments, call_id):
        """Run one Interspace tool from the MCP bridge. No tools are offered yet, so every name is unknown."""
        _runtime_id(call_id, 'call_id')
        raise ValueError('Unknown tool.')

    def report_usage(self, usage):
        self._scheduler._report_usage(self._run, usage)

    def tools(self):
        """Tool descriptors for the MCP bridge. None yet: runtimes start a bridge only for a non-empty list."""
        return []

    def observed(self, request, call_id):
        """Record an action the provider ran without asking; returns its final decision (`provider.sandbox`)."""
        return self._scheduler._observed(self._run, request, _runtime_id(call_id, 'call_id'))


class _Run:
    def __init__(self, task_id, project_id, text, client_id, turn_id):
        self.task_id = task_id
        self.project_id = project_id
        self.text = text
        self.client_id = client_id
        self.turn_id = turn_id
        self.cancel = threading.Event()
        self.turn_over = threading.Event()
        self.thread = None
        self.session = None
        self.stop_reason = None
        self.started_at = None
        self.counted_since = None
        self.lock_key = None
        self.reservation = None
        self.provider = 'codex'
        self.last_usage = None
        self.workspaces = {}
        self.ask = None
        self.ask_answer = None
        self.ask_lock = threading.Lock()


def _final(decision, rule=None):
    result = {k: decision.get(k) for k in ('decision', 'rule', 'reason', 'scope_version', 'scope_digest')}
    if rule:
        result['rule'] = rule
    return result


# ------------------------------------------------------------------------------------- scheduler

class Scheduler:
    def __init__(self, *, max_running, runtime_factory, policy, audit, events, budget_gate, locks, clock,
                 tasks, workspaces=None, legacy_active=None, interrupt_grace_s=INTERRUPT_GRACE_S,
                 monotonic=time.monotonic, tick_s=0.5, decide_options=None):
        self.max_running = validate_max_running(max_running)
        self.runtime_factory = runtime_factory
        self.policy = policy
        self.audit = audit
        self.events = events
        self.budget = budget_gate
        self.locks = locks
        self.clock = clock
        self.store = tasks
        self.lock = tasks.lock
        self.workspaces = workspaces
        self.legacy_active = legacy_active or (lambda: False)
        self.interrupt_grace_s = interrupt_grace_s
        self.monotonic = monotonic
        # Extra keyword arguments for policy.decide (coordinator ruling): app_data, home, temp_roots.
        self.decide_options = dict(decide_options or {})
        self._cond = threading.Condition(self.lock)
        self._runs = {}
        self._queue = []
        self._sessions = {}
        self._closed = False
        self._stop_watch = threading.Event()
        self._watch = threading.Thread(target=self._watchdog, args=(tick_s,), daemon=True, name='scheduler-watchdog')
        self._watch.start()

    # -- public API ---------------------------------------------------------------------------------

    def submit(self, task_id, project_id, text, client_id):
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_MESSAGE_CHARS:
            raise ValueError('Message must contain 1–20,000 characters.')
        if client_id is not None and (not isinstance(client_id, str) or len(client_id) > 128):
            raise ValueError('Invalid client message reference.')
        with self.lock:
            if self._closed:
                raise ValueError('Interspace is closing; no new work starts.')
            task = self._task(task_id)
            agent = task['agent']
            if agent.get('project_id') != project_id:
                raise ValueError('This task belongs to a different project.')
            if task_id in self._runs or agent.get('state') not in (None, 'idle') + TERMINAL:
                raise ValueError('This task is already working. Wait or stop it first.')
            if not self.approved(task):
                raise ValueError('Approve the task scope before starting.')
            agent['turns'] = agent.get('turns', 0) + 1
            run = _Run(task_id, project_id, text, client_id, 'u%d' % agent['turns'])
            self._runs[task_id] = run
            if not self._queue and self._free_slots() > 0:
                self._start(run)
                return {'task_id': task_id, 'state': 'starting', 'position': None}
            self._queue.append(task_id)
            position = len(self._queue)
            self._set_state(run, 'queued', position=position)
            self._user_message(run)
            return {'task_id': task_id, 'state': 'queued', 'position': position}

    def cancel(self, task_id):
        with self.lock:
            run = self._runs.get(task_id)
            if run is None:
                return False
            if task_id in self._queue:
                self._queue.remove(task_id)
                del self._runs[task_id]
                self._set_state(run, 'cancelled')
                self._renumber()
                return True
        self._stop(run, 'cancel')
        return True

    def answer(self, task_id, ask_id, decision, text=None, scope_digest=None, request_digest=None):
        with self.lock:
            run = self._runs.get(task_id)
            ask = run.ask if run else None
            if ask is None or ask['ask_id'] != ask_id or run.ask_answer is not None:
                raise ValueError('This question is no longer open.')
            if request_digest != ask['request_digest']:
                raise ValueError('The request changed since it was shown. Nothing was allowed.')
            if decision not in ANSWERS or decision not in ask['options']:
                raise ValueError('That answer is not offered for this question.')
            if decision == 'text' and (not isinstance(text, str) or not text.strip() or len(text) > 6000):
                raise ValueError('Reply must contain 1–6,000 characters.')
            task = self._task(task_id)
            self._apply_answer(run, task, ask, decision, scope_digest)
            self._record_answer(run, ask, decision)
            self.events.append(task_id, run.project_id, 'answer',
                               {'ask_id': ask_id, 'decision': decision, 'text': text if decision == 'text' else None,
                                'scope_version': task['scope']['version']}, item_id='ask_' + ask_id)
            run.ask_answer = {'decision': decision, 'text': text}
            self._cond.notify_all()
            self.store.changed(task_id)
        return {'accepted': True}

    def scope_changed(self, task_id):
        with self.lock:
            self._cond.notify_all()

    def set_max_running(self, value):
        with self.lock:
            self.max_running = validate_max_running(value)
        self.pump()
        return self.max_running

    def legacy_slot_free(self):
        """Whether a legacy interaction may start now: it counts as one of the run slots."""
        with self.lock:
            return self.max_running - self._running_count() > 0

    def pump(self):
        with self.lock:
            started = False
            while self._queue and not self._closed and self._free_slots() > 0:
                self._start(self._runs[self._queue.pop(0)])
                started = True
            if started:
                self._renumber()

    def snapshot(self):
        with self.lock:
            running = []
            for run in self._runs.values():
                if run.thread is None:
                    continue
                task = self._task(run.task_id)
                totals = self.budget.totals(task)
                running.append({'task_id': run.task_id, 'project_id': run.project_id, 'state': task['agent']['state'],
                                'started_at': run.started_at, 'tokens': {'used': totals['used'], 'budget': totals['budget']},
                                'lock': run.lock_key})
            queued = [{'task_id': t, 'project_id': self._runs[t].project_id, 'position': i + 1}
                      for i, t in enumerate(self._queue)]
            return {'max_running': self.max_running, 'running': running, 'queued': queued,
                    'legacy_active': bool(self.legacy_active())}

    def shutdown(self, timeout_s=30):
        with self.lock:
            self._closed = True
            for task_id in list(self._queue):
                run = self._runs.pop(task_id)
                self._set_state(run, 'interrupted')
            self._queue = []
            running = list(self._runs.values())
        for run in running:
            self._stop(run, 'shutdown')
        deadline = time.monotonic() + timeout_s
        for run in running:
            if run.thread is not None:
                run.thread.join(max(0, deadline - time.monotonic()))
        with self.lock:
            sessions = list(self._sessions.values())
            self._sessions = {}
        for session in sessions:
            try:
                session.close()
            except Exception:
                pass  # Closing at shutdown is best effort; the process group goes with the backend.
        self._stop_watch.set()

    # -- state and events ---------------------------------------------------------------------------

    def _task(self, task_id):
        task = self.store.task(task_id)
        if task.get('mode') != 'agent' or not isinstance(task.get('agent'), dict):
            raise ValueError('This is not an agent task.')
        return task

    def approved(self, task):
        """Whether the task's live scope has a matching approval (scope.md approval binding)."""
        approval = task.get('scope_approval')
        try:
            digest = self.policy.digest(task['scope'])
        except Exception:
            return False
        return (isinstance(approval, dict) and approval.get('scope_digest') == digest
                and approval.get('scope_version') == task['scope'].get('version'))

    def _running_count(self):
        legacy = 1 if self.legacy_active() else 0
        return legacy + sum(1 for run in self._runs.values() if run.thread is not None)

    def _free_slots(self):
        return self.max_running - self._running_count()

    def _renumber(self):
        for index, task_id in enumerate(self._queue):
            self._set_state(self._runs[task_id], 'queued', position=index + 1)

    def _set_state(self, run, state, detail='', reason=None, position=None):
        with self.lock:
            agent = self._task(run.task_id)['agent']
            now = self.monotonic()
            if run.counted_since is not None:
                agent['active_s'] = agent.get('active_s', 0.0) + (now - run.counted_since)
                run.counted_since = None
            if state in COUNTED:
                run.counted_since = now
            agent.update(state=state, detail=detail, reason=reason)
            self.events.append(run.task_id, run.project_id, 'status',
                               {'state': state, 'detail': detail, 'queue_position': position, 'reason': reason})
            self.store.changed(run.task_id)
            self._cond.notify_all()

    def _emit(self, run, kind, data, turn_id=None, item_id=None):
        return self.events.append(run.task_id, run.project_id, kind, data, turn_id=turn_id, item_id=item_id)

    def _error(self, run, code, message, recoverable, call_id=None):
        self._emit(run, 'error', {'code': code, 'message': message, 'recoverable': recoverable, 'call_id': call_id},
                   turn_id=run.turn_id)

    def _user_message(self, run):
        self._emit(run, 'message', {'role': 'user', 'text': run.text, 'final': True, 'client_id': run.client_id},
                   turn_id=run.turn_id, item_id='user_' + run.turn_id)

    def _emit_budget(self, run, entry):
        with self.lock:
            task = self._task(run.task_id)
            totals = self.budget.totals(task)
            tokens = entry['estimate'] if entry['charge_kind'] == 'reserved' else entry['charge']
            self._emit(run, 'budget', {'charge_kind': entry['charge_kind'], 'tokens': tokens,
                                       'provider': entry.get('provider', 'codex'), 'used': totals['used'],
                                       'reserved': totals['reserved'], 'remaining': totals['remaining'],
                                       'budget': totals['budget'], 'overshoot': totals['overshoot']},
                       turn_id=run.turn_id)

    def _audit(self, run, kind, actor='agent', **fields):
        # audit.AuditLog fills id, at and prev itself, and redacts the request.
        record = {'v': V, 'actor': actor, 'kind': kind,
                  'task_id': run.task_id, 'project_id': run.project_id, 'turn_id': run.turn_id, 'call_id': None,
                  'request': None, 'decision': None, 'rule': None, 'scope_version': None, 'scope_digest': None,
                  'outcome': None, 'idempotency_key': None, 'detail': None}
        record.update(fields)
        self.audit.append(record)

    # -- worker -------------------------------------------------------------------------------------

    def _start(self, run):
        run.started_at = iso_time(self.clock())
        run.thread = threading.Thread(target=self._work, args=(run,), daemon=True, name='task-' + run.task_id[:8])
        was_queued = self._task(run.task_id)['agent'].get('state') == 'queued'
        self._set_state(run, 'starting')
        if not was_queued:
            self._user_message(run)
        run.thread.start()

    def _work(self, run):
        final, reason = 'failed', 'runtime_exited'
        try:
            final, reason = self._turn(run) or ('failed', 'runtime_exited')
        except Exception:
            self._error(run, 'runtime_exited', 'The agent run stopped unexpectedly.', False)
        finally:
            run.turn_over.set()
            with self.lock:
                self._runs.pop(run.task_id, None)
                self._set_state(run, final, reason=reason)
            self.pump()

    def _end_state(self, run):
        """The terminal state for a run that was stopped by the scheduler, or None."""
        if run.stop_reason == 'cancel':
            return 'cancelled', None
        if run.stop_reason == 'shutdown':
            return 'interrupted', None
        if run.stop_reason == 'time_limit':
            self._error(run, 'time_limit', 'The task reached its time limit. Its work is kept.', False)
            return 'time_limit', None
        if run.stop_reason == 'budget':
            self._error(run, 'budget_exhausted', 'The task reached its token budget. Its work is kept.', False)
            return 'budget_exhausted', None
        return None

    def _turn(self, run):
        try:
            self._prepare_workspaces(run)
        except Cancelled:
            return self._end_state(run) or ('cancelled', None)
        except LockTimeout:
            self._error(run, 'lock_timeout', 'Timed out waiting for the project to be free.', False)
            return 'failed', 'lock_timeout'
        except Exception:
            self._error(run, 'workspace_failed', 'Could not create the task workspace. Check the project repository.', False)
            return 'failed', 'workspace_failed'
        try:
            runtime = self.runtime_factory(run.task_id)
            run.provider = getattr(runtime, 'name', 'codex')
        except Exception:
            self._error(run, 'runtime_unavailable', 'The agent runtime is not available.', False)
            return 'failed', 'runtime_unavailable'
        with self.lock:
            task = self._task(run.task_id)
            try:
                run.reservation = self.budget.reserve(task, run.text, run.provider, run.turn_id)
            except budget.Exhausted as error:
                self._error(run, 'budget_exhausted', str(error), False)
                return 'budget_exhausted', None
            self._emit_budget(run, self.budget.entry(run.reservation))
            context = RunContext(self, run, task, run.workspaces)
            if run.cancel.is_set():
                self.budget.release(run.reservation)  # Nothing was launched.
                run.reservation = None
                return self._end_state(run)
            self._set_state(run, 'running')
        status, usage, error = 'crashed', None, None
        try:
            with self.lock:
                session = self._sessions.get(run.task_id)
            if session is None:
                session = runtime.open(context)
                with self.lock:
                    self._sessions[run.task_id] = session
            run.session = session
            if run.cancel.is_set():
                session.interrupt()
            result = session.run_turn(run.text, context)
            if not isinstance(result, dict) or result.get('status') not in ('completed', 'failed', 'cancelled'):
                raise ValueError('Invalid turn result.')
            status, usage, error = result['status'], result.get('usage'), result.get('error')
            if status == 'failed':
                self._drop_session(run.task_id, close=True)  # The next turn starts a fresh session.
        except Exception as failure:
            status = 'crashed'
            if isinstance(failure, ValueError) and isinstance(getattr(failure, 'code', None), str):
                # runtime.RuntimeFailure: a known code and a sentence that is safe to show.
                status, error = 'failed', {'code': failure.code, 'message': str(failure)}
            with self.lock:
                broken = self._sessions.pop(run.task_id, None)
            if broken is not None:
                try:
                    broken.kill()
                except Exception:
                    pass  # The session is already gone; the kill is only a precaution.
        finally:
            run.turn_over.set()
        with self.lock:
            entry = self.budget.settle(run.reservation, usage if usage is not None else run.last_usage,
                                       'cancelled' if run.stop_reason else 'completed' if status == 'completed' else 'failed')
            self._emit_budget(run, entry)
        self._publish(run)
        ended = self._end_state(run)
        if ended:
            return ended
        if status == 'crashed':
            self._error(run, 'runtime_exited', 'The agent session stopped unexpectedly.', False)
            return 'failed', 'runtime_exited'
        if status == 'failed':
            code = error.get('code') if isinstance(error, dict) and isinstance(error.get('code'), str) else 'runtime_exited'
            message = error.get('message') if isinstance(error, dict) and isinstance(error.get('message'), str) else 'The agent turn failed.'
            self._error(run, code[:64], message[:500], False)
            return 'failed', code[:64]
        if status == 'cancelled':
            return 'cancelled', None
        return 'idle', None

    def _drop_session(self, task_id, close):
        with self.lock:
            session = self._sessions.pop(task_id, None)
        if session is not None:
            try:
                session.close() if close else session.kill()
            except Exception:
                pass  # The session is already gone.

    def _prepare_workspaces(self, run):
        with self.lock:
            task = self._task(run.task_id)
            saved = task['agent'].setdefault('workspaces', {})
            wanted = [p.get('project_id') for p in task['scope'].get('projects', [])]
            sources = {}
            for project_id in wanted:
                project = self.store.project(project_id)
                if project is None:
                    raise ValueError('A project in the scope is no longer registered.')
                sources[project_id] = project['source_path']
        for project_id in wanted:
            info = saved.get(project_id)
            if not (info and Path(info['path']).is_dir()):
                info = self._with_lock(run, 'project:' + project_id,
                                       lambda: self.workspaces.prepare(run.task_id, project_id, sources[project_id]))
                with self.lock:
                    saved[project_id] = info
                    self.store.changed(run.task_id)
            run.workspaces[project_id] = info

    def _publish(self, run):
        for project_id, info in run.workspaces.items():
            project = self.store.project(project_id)
            try:
                branch = self._with_lock(run, 'project:' + project_id,
                                         lambda: self.workspaces.publish(info, project['source_path']), cancellable=False)
                change = self.workspaces.diff(info)
            except Exception:
                self._error(run, 'workspace_failed', 'Could not publish the task branch or read its changes.', True)
                continue
            patch, blob = change['patch'], None
            self._emit(run, 'diff', {'call_id': None, 'workspace': {'project_id': project_id, 'branch': branch,
                                                                    'base_commit': info['base_commit']},
                                     'files': change['files'], 'patch': patch[:MAX_PATCH_CHARS],
                                     'truncated': len(patch) > MAX_PATCH_CHARS, 'blob_id': blob, 'cumulative': True},
                       turn_id=run.turn_id)
            with self.lock:
                self.store.changed(run.task_id)

    def _with_lock(self, run, key, action, cancellable=True):
        """Run `action` holding `key`. Shows `waiting_lock` while another holder has it."""
        cancel = run.cancel if cancellable else None
        with self.lock:
            previous = self._task(run.task_id)['agent'].get('state')
            run.lock_key = key
        try:
            try:
                self.locks.acquire(key, run.task_id, cancel, timeout_s=0)
            except LockTimeout:
                self._set_state(run, 'waiting_lock', detail=key)
                self.locks.acquire(key, run.task_id, cancel)
                if not run.cancel.is_set():
                    self._set_state(run, previous)
            try:
                return action()
            finally:
                self.locks.release(key, run.task_id)
        finally:
            run.lock_key = None

    # -- cancel, limits and usage --------------------------------------------------------------------

    def _stop(self, run, reason):
        with self.lock:
            if run.stop_reason is not None or run.turn_over.is_set():
                return
            run.stop_reason = reason
            run.cancel.set()
            if reason == 'cancel':
                self._set_state(run, 'cancelling')
            self._cond.notify_all()
            session = run.session
        self.locks.wake()
        if session is not None:
            try:
                session.interrupt()
            except Exception:
                pass  # The kill below still stops the turn.
        timer = threading.Timer(self.interrupt_grace_s, self._kill, args=(run,))
        timer.daemon = True
        timer.start()

    def _kill(self, run):
        if run.turn_over.is_set() or run.session is None:
            return
        try:
            run.session.kill()
        except Exception:
            pass  # Nothing more can be done from here; the turn ends when the process does.

    def _watchdog(self, tick_s):
        while not self._stop_watch.wait(tick_s):
            over = []
            with self.lock:
                now = self.monotonic()
                for run in list(self._runs.values()):
                    if run.thread is None or run.stop_reason is not None:
                        continue
                    task = self._task(run.task_id)
                    active = task['agent'].get('active_s', 0.0)
                    if run.counted_since is not None:
                        active += now - run.counted_since
                    limit = task['scope'].get('limits', {}).get('time_limit_s')
                    if type(limit) is int and active >= limit:
                        over.append(run)
            for run in over:
                self._stop(run, 'time_limit')

    def _report_usage(self, run, usage):
        """`usage` is the turn's cumulative usage so far, reported after each model request (0B: Codex sends
        `thread/tokenUsage/updated` per request). Over budget, the turn is interrupted."""
        with self.lock:
            run.last_usage = copy.deepcopy(usage)
            amount = budget.charge(usage, run.provider)
            if amount is None or run.reservation is None:
                return
            task = self._task(run.task_id)
            totals = self.budget.totals(task)
            own = self.budget.entry(run.reservation)['estimate']
            over = totals['budget'] is not None and totals['used'] + totals['reserved'] - own + amount > totals['budget']
        if over:
            self._stop(run, 'budget')

    # -- policy -------------------------------------------------------------------------------------

    def _decide(self, run, task, request):
        try:
            decision = self.policy.decide(task['scope'], task.get('scope_approval'), copy.deepcopy(request),
                                          workspace_roots=dict((k, v['path']) for k, v in run.workspaces.items()),
                                          now=self.clock(), **self.decide_options)
            if not isinstance(decision, dict) or decision.get('decision') not in ('allow', 'ask', 'deny'):
                raise ValueError('Invalid policy decision.')
            return decision
        except Exception:
            self._error(run, 'policy_failed', 'The policy check failed, so the action was refused.', True)
            return {'decision': 'deny', 'rule': 'policy.failed', 'reason': 'The policy check failed.',
                    'scope_version': task['scope'].get('version'), 'scope_digest': None, 'ask': None}

    def _authorize(self, run, request, call_id):
        cancelled = {'decision': 'deny', 'rule': 'task.cancelled', 'reason': 'The task was stopped.',
                     'scope_version': None, 'scope_digest': None}
        with run.ask_lock:  # One open ask per task.
            while True:
                with self.lock:
                    if run.cancel.is_set():
                        return cancelled
                    task = self._task(run.task_id)
                    decision = self._decide(run, task, request)
                    try:
                        self._audit(run, 'decision', call_id=call_id, request=request, decision=decision['decision'],
                                    rule=decision.get('rule'), scope_version=decision.get('scope_version'),
                                    scope_digest=decision.get('scope_digest'))
                    except Exception:
                        self._error(run, 'audit_failed', 'The audit log could not be written, so the action was refused.', True, call_id)
                        return dict(_final(decision), decision='deny', rule='audit.failed')
                    if decision['decision'] != 'ask':
                        return _final(decision)
                    ask = decision.get('ask') or {}
                    if ask.get('reason') == 'scope_unapproved':
                        self._set_state(run, 'paused_scope', detail='The task scope changed. Approve it to continue.')
                        while not run.cancel.is_set() and not self.approved(self._task(run.task_id)):
                            self._cond.wait(0.5)
                        if run.cancel.is_set():
                            return cancelled
                        self._set_state(run, 'running')
                        continue
                    run.ask = {'ask_id': uuid.uuid4().hex, 'call_id': call_id, 'request': copy.deepcopy(request),
                               'reason': ask.get('reason'), 'options': list(ask.get('options') or []),
                               'scope_patch': ask.get('scope_patch'), 'request_digest': ask.get('request_digest'),
                               'patched_scope_digest': ask.get('patched_scope_digest'),
                               'scope_digest': decision.get('scope_digest')}
                    ask_id = run.ask['ask_id']
                    self._emit(run, 'ask', {'ask_id': ask_id, 'call_id': call_id, 'reason': ask.get('reason'),
                                            'title': ask.get('title'), 'detail': ask.get('detail'),
                                            'request': copy.deepcopy(request), 'options': run.ask['options'],
                                            'scope_patch': ask.get('scope_patch'),
                                            'patched_scope_digest': ask.get('patched_scope_digest'),
                                            'request_digest': ask.get('request_digest')},
                               turn_id=run.turn_id, item_id='ask_' + ask_id)
                    self._set_state(run, 'paused_ask', detail=(ask.get('title') or '')[:200])
                    while run.ask_answer is None and not run.cancel.is_set():
                        self._cond.wait(0.5)
                    answer, opened = run.ask_answer, run.ask
                    run.ask, run.ask_answer = None, None
                    if answer is None:
                        try:
                            self._record_answer(run, opened, 'cancelled')
                        except Exception:
                            self._error(run, 'audit_failed', 'The audit log could not be written.', True, call_id)
                        self._emit(run, 'answer', {'ask_id': ask_id, 'decision': 'cancelled', 'text': None,
                                                   'scope_version': self._task(run.task_id)['scope']['version']},
                                   item_id='ask_' + ask_id)
                        return cancelled
                    self._set_state(run, 'running')
                    scope = self._task(run.task_id)['scope']
                    base = {'reason': 'Answered by the user.', 'scope_version': scope['version'],
                            'scope_digest': self.policy.digest(scope)}
                    if answer['decision'] == 'deny':
                        return dict(base, decision='deny', rule='ask.deny')
                    if answer['decision'] == 'text':
                        return dict(base, decision='allow', rule='ask.text', text=answer['text'])
                    return dict(base, decision='allow', rule='ask.' + answer['decision'])

    def _record_answer(self, run, ask, decision):
        try:
            self._audit(run, 'answer', actor='user', call_id=ask['call_id'], request=ask['request'], decision=decision,
                        detail={'ask_id': ask['ask_id'], 'request_digest': ask['request_digest']})
        except Exception:
            raise ValueError('Could not record the answer, so nothing was allowed.') from None

    def _apply_answer(self, run, task, ask, decision, scope_digest):
        """Bind the answer to the exact ask with `scope.apply_answer` (coordinator ruling: one place for the checks)."""
        apply_answer = getattr(self.policy, 'apply_answer', None)
        if apply_answer is None:  # service.ScopeAdapter wraps the scope module itself.
            apply_answer = getattr(getattr(self.policy, 'module', None), 'apply_answer', None)
        if apply_answer is None:
            raise ValueError('The scope engine is not available, so nothing was allowed.')
        stored = {'ask_id': ask['ask_id'], 'request_digest': ask['request_digest'], 'options': ask['options'],
                  'scope_patch': ask.get('scope_patch'), 'patched_scope_digest': ask.get('patched_scope_digest')}
        answer = {'ask_id': ask['ask_id'], 'request_digest': ask['request_digest'], 'decision': decision,
                  'scope_digest': scope_digest}
        current, approval = task['scope'], task.get('scope_approval')
        if decision == 'add_to_scope' and self.policy.digest(current) != ask['scope_digest']:
            raise ValueError('The scope changed since this question was asked. Nothing was changed.')
        outcome = apply_answer(current, approval, stored, answer, now=self.clock())
        if outcome.get('change') != 'amended':
            return
        amended, new_approval = outcome['scope'], outcome['approval']
        self.policy.validate(amended, project_ids=list(self.store.state['projects']))
        digest = self.policy.digest(amended)
        if digest != scope_digest or new_approval.get('scope_digest') != digest:
            raise ValueError('The scope change does not match what was shown.')
        try:
            self._audit(run, 'scope', actor='user', detail={'from_version': current['version'], 'to_version': amended['version'],
                                                            'from_digest': ask['scope_digest'], 'to_digest': digest})
        except Exception:
            raise ValueError('Could not record the scope change, so nothing was changed.') from None
        task['scope'] = amended
        task['token_budget'] = amended.get('limits', {}).get('token_budget', task.get('token_budget'))
        task['scope_approval'] = new_approval
        self.events.append(run.task_id, run.project_id, 'scope',
                           {'scope_version': amended['version'], 'scope_digest': digest, 'change': 'amended',
                            'by': 'user', 'summary': 'Added to the scope while answering a question.'})

    # -- runtime support ----------------------------------------------------------------------------

    def _observed(self, run, request, call_id):
        with self.lock:
            scope = self._task(run.task_id)['scope']
            version = scope.get('version')
            try:
                digest = self.policy.digest(scope)
            except Exception:
                digest = None
        decision = {'decision': 'allow', 'rule': 'provider.sandbox',
                    'reason': 'Run by the provider inside its sandbox and reported after the fact.',
                    'scope_version': version, 'scope_digest': digest}
        try:
            self._audit(run, 'decision', call_id=call_id, request=copy.deepcopy(request), decision='allow',
                        rule='provider.sandbox', scope_version=version, scope_digest=digest,
                        detail={'after_the_fact': True})
        except Exception:
            self._error(run, 'audit_failed', 'An action the agent ran could not be recorded in the audit log.', True, call_id)
        return decision
