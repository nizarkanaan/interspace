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
import orchestrator
import tasks as task_rows
from research import corpus as research_corpus
from research import claims as research_claims
from research import fulltext as research_fulltext
from research import evidence as research_evidence

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
RECOVER = ('queued', 'starting', 'running', 'waiting_lock', 'paused_ask', 'paused_scope', 'paused_team', 'cancelling')
STATES = ('queued', 'starting', 'running', 'waiting_lock', 'paused_ask', 'paused_scope', 'paused_team', 'idle',
          'cancelling') + TERMINAL
RUNTIME_KINDS = ('message_delta', 'message', 'reasoning', 'plan_update', 'tool_call', 'tool_output_delta',
                 'tool_result', 'diff')
ANSWERS = ('allow_once', 'add_to_scope', 'deny', 'text')
IDENTIFIER = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
BLOB_ID = re.compile(r'^[0-9a-f]{32}$')
MAX_RESEARCH_RESULT_BYTES = 64 * 1024  # research/tools.md: a result is cut to 64 KB of JSON, flagged `truncated`.
RESEARCH_USAGE_INTERVAL_S = 1.0  # research/tasks.md: `research_usage` at most once per second while calls happen.
OUTPUT_NAMES = (('report.md', 'report'), ('references.bib', 'bibtex'), ('evidence.csv', 'table'))
MAX_SAVED_REPORT = 400000  # save_report: characters of Markdown.
RESEARCH_LISTS = ('papers', 'entries', 'references')  # The list a too-large research result is shortened by.


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

    def reserve(self, task, text, provider, turn_id, source_task_id=None):
        """Reserve against `task`, the root task (orchestration.md: one budget per root). A child's entry records
        the child as `source_task_id` and is charged by the child's own provider rule."""
        entry_id = budget.reserve(self.store.state, task, role='Agent', prompt=text,
                                  project_id=task['agent']['project_id'], estimate=budget.estimate_turn(len(text)),
                                  provider=provider, turn_id=turn_id, call_kind='agent_turn')
        if source_task_id is not None and source_task_id != task['id']:
            self.entry(entry_id)['source_task_id'] = source_task_id
        return entry_id

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


SCRATCH_EXCLUDES = ('/.interspace/', '/.claude/')  # Provider scratch folders never committed from a task clone.
# The only settings a task clone's own git config keeps. Interspace runs git outside any sandbox in a folder the agent
# can write, so everything else (fsmonitor, filters, diff programs, aliases, includes, worktree) is dropped before use.
_BOOL = re.compile(r'^(true|false)$')
CLONE_CONFIG = (('core', 'repositoryformatversion', re.compile(r'^[01]$')), ('core', 'filemode', _BOOL),
                ('core', 'bare', re.compile(r'^false$')), ('core', 'logallrefupdates', _BOOL),
                ('core', 'ignorecase', _BOOL), ('core', 'precomposeunicode', _BOOL), ('core', 'symlinks', _BOOL),
                ('extensions', 'objectformat', re.compile(r'^(sha1|sha256)$')),
                ('interspace', 'base-commit', re.compile(r'^[0-9a-f]{40}([0-9a-f]{24})?$')))


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

    def _clone(self, work):
        """Git options that pin a task clone's own repository, after checking and cleaning its metadata.

        The agent can write its clone, so `.git` must be a real folder of this clone (not a `gitdir:` file, a
        symlink or a `commondir` redirect into another repository), and its config keeps only `CLONE_CONFIG`.
        """
        work = Path(work)
        git_dir = work / '.git'
        config = git_dir / 'config'
        if (git_dir.is_symlink() or not git_dir.is_dir() or os.path.lexists(str(git_dir / 'commondir'))
                or config.is_symlink() or not config.is_file()):
            raise ValueError('The task workspace repository was changed, so Interspace will not use it.')
        listed = self._git(['config', '--file', str(config), '--list', '-z']).stdout
        values = {}
        for item in listed.split('\0'):
            key, _, value = item.partition('\n')
            values[key.lower()] = value  # The last value of a key wins, as in git.
        lines, section = [], None
        for name, key, pattern in CLONE_CONFIG:
            value = values.get(name + '.' + key)
            if value is None or not pattern.match(value):
                continue
            if name != section:
                lines.append('[%s]' % name)
                section = name
            lines.append('\t%s = %s' % (key, value))
        text = '\n'.join(lines) + '\n'
        if config.read_text(encoding='utf-8', errors='replace') != text:
            fresh = git_dir / ('config.interspace-' + uuid.uuid4().hex)
            fresh.write_text(text, encoding='utf-8')
            os.replace(str(fresh), str(config))
        return ['-c', 'core.fsmonitor=false', '--git-dir=' + str(git_dir), '--work-tree=' + str(work), '-C', str(work)]

    def prepare(self, task_id, project_id, source_path):
        if not IDENTIFIER.match(task_id) or not IDENTIFIER.match(project_id):
            raise ValueError('Invalid task or project.')
        path = self.root / task_id / project_id
        branch = 'interspace/task-' + task_id[:8]
        if os.path.lexists(str(path / '.git')):
            base = self._git(self._clone(path) + ['config', 'interspace.base-commit']).stdout.strip()
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

    def commit(self, info, message):
        """Commit everything the agent changed in its clone to the task branch; the commit ID, or None when clean.

        Only the task clone is touched. Scratch folders (`.interspace/`, `.claude/`) stay out through the clone's
        `info/exclude`. The user's own git identity is used when the clone has one, else a local Interspace
        identity. No signing, no hooks and a one-line message, so nothing can add a trailer.
        """
        clone = self._clone(info['path'])
        info_dir = Path(info['path']) / '.git' / 'info'
        if info_dir.is_symlink() or (info_dir / 'exclude').is_symlink():
            raise ValueError('The task workspace repository was changed, so Interspace will not use it.')
        exclude = info_dir / 'exclude'
        exclude.parent.mkdir(parents=True, exist_ok=True)
        lines = exclude.read_text(encoding='utf-8').splitlines() if exclude.exists() else []
        missing = [line for line in SCRATCH_EXCLUDES if line not in lines]
        if missing:
            with exclude.open('a', encoding='utf-8') as handle:
                handle.write('\n' + '\n'.join(missing) + '\n')
        if not self._git(clone + ['status', '--porcelain', '--untracked-files=all']).stdout.strip():
            return None
        identity = []
        if self._git(clone + ['config', 'user.email'], check=False).returncode != 0:
            identity = ['-c', 'user.name=Interspace', '-c', 'user.email=interspace@localhost']
        self._git(clone + ['add', '--all'])
        self._git(identity + ['-c', 'commit.gpgsign=false'] + clone + ['commit', '--quiet', '--no-verify',
                                                                        '-m', ' '.join(message.split())])
        return self._git(clone + ['rev-parse', 'HEAD']).stdout.strip()

    def publish(self, info, source_path):
        """Write only the task's branch into the user's repository. The chosen name is kept in `info`."""
        clone = self._clone(info['path'])
        head = self._git(clone + ['rev-parse', '--verify', 'refs/heads/' + info['branch'] + '^{commit}']).stdout.strip()
        target = info.get('target_branch')
        if target:
            found = self._git(['-C', str(source_path), 'rev-parse', '--verify', '--quiet',
                               'refs/heads/' + target + '^{commit}'], check=False)
            published = found.stdout.strip() if found.returncode == 0 else None
            # Only a fast-forward updates the published branch: a commit the user added there is never dropped.
            if published and published != head and self._git(
                    clone + ['merge-base', '--is-ancestor', published, head], check=False).returncode != 0:
                target = None
        if not target:
            target, number = info['branch'], 1
            while self._git(['-C', str(source_path), 'show-ref', '--verify', '--quiet', 'refs/heads/' + target],
                            check=False).returncode == 0:
                number += 1
                target = info['branch'] + '-' + str(number)
            info['target_branch'] = target
        self._git(['-C', str(source_path), 'fetch', '--quiet', '--no-tags', str(Path(info['path']) / '.git'),
                   'refs/heads/' + info['branch'] + ':refs/heads/' + target])
        return target

    def diff(self, info):
        """The whole workspace (committed, staged, unstaged and new files) against the base commit."""
        clone = self._clone(info['path'])
        git_dir = Path(info['path']) / '.git'
        handle, index = tempfile.mkstemp(prefix='interspace-index-', dir=str(git_dir))
        os.close(handle)
        try:
            shutil.copyfile(str(git_dir / 'index'), index)
            env = dict(_git_env(), GIT_INDEX_FILE=index)  # The agent's own index is never touched.
            self._git(clone + ['add', '--all'], env=env)
            common = clone + ['diff', '--cached', '--no-renames', '--no-ext-diff', '--no-textconv', '--no-color']
            names = self._git(common + ['--name-status', info['base_commit']], env=env).stdout
            counts = self._git(common + ['--numstat', info['base_commit']], env=env).stdout
            patch = self._git(common + [info['base_commit']], env=env).stdout
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
        changed += [t for t in orchestrator.recover(store) if t not in changed]
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
        # A task without a project (research/tasks.md) has no workspace: its runtime starts in an empty, app-owned
        # scratch folder, with no file tools (Claude) or a read-only sandbox (Codex).
        self.research_only = task_rows.is_research(task)
        self.scratch = run.scratch
        self.primary_workspace = (self.workspaces.get(run.project_id) or next(iter(self.workspaces.values()), None)
                                  or self.scratch)
        self.scope = copy.deepcopy(task['scope'])  # For prompts and display only; decisions read the live scope.
        # A model id from the signed-in account's model list (0B-7), or None for the provider default.
        self.model = task.get('model') if isinstance(task.get('model'), str) and task.get('model') else None
        # An effort level for the provider, or None for its default.
        self.effort = task.get('effort') if isinstance(task.get('effort'), str) and task.get('effort') else None
        self.cancel = run.cancel
        self.role = run.role
        # 'read' or 'write': runtimes start read sessions without workspace writes. The Orchestrator reads only.
        self.access = run.access
        # Added system instructions for Orchestrator sessions (orchestration.md "Prompt"), else None.
        self.instructions = scheduler.orchestrator.system_prompt(task) if run.orchestrates else None
        self._offered = tuple(t['name'] for t in self.tools())

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

    def call_tool(self, name, arguments):
        """Run one Interspace tool from the MCP bridge: an orchestration tool (Orchestrator sessions) or a research
        tool (sessions of a task whose scope enables a research source). Only tools this session was offered run."""
        if not isinstance(name, str) or name not in self._offered:
            raise ValueError('Unknown tool.')
        if name in orchestrator.TOOLS:
            return self._scheduler._orchestrate(self._run, name, arguments)
        return self._scheduler._research(self._run, name, arguments)

    def orchestrate(self, name, arguments):
        """The earlier name of `call_tool`, kept for runtimes and tests written before research tools."""
        return self.call_tool(name, arguments)

    def report_usage(self, usage):
        self._scheduler._report_usage(self._run, usage)

    def report_limits(self, raw):
        """A usage-limit reading from this session's provider (2026-11-20-usage-limits-design.md)."""
        self._scheduler._report_limits(self._run, raw)

    def tools(self):
        """Tool descriptors for the MCP bridge, built per session: the orchestration tools for the root Orchestrator,
        then the research tools whenever the scope enables a research source (research/tools.md "Who gets them").
        Claude's file tools are added by the Claude runtime itself."""
        from runtime import mcp_bridge
        found = list(mcp_bridge.ORCHESTRATION_TOOLS) if self._run.orchestrates else []
        if research_enabled(self.scope):
            found += list(mcp_bridge.RESEARCH_TOOLS)
            if self.research_only:
                found.append(mcp_bridge.CORPUS_TOOL)
                found += list(mcp_bridge.CLAIM_TOOLS)
                found += list(mcp_bridge.TABLE_TOOLS)
                if self._run.orchestrates:
                    found.append(mcp_bridge.SAVE_REPORT_TOOL)
        return copy.deepcopy(found)

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
        self.parent_task_id = None
        self.role = None
        self.access = 'write'
        self.orchestrates = False
        self.yielded = False  # Waiting on the user or on its children: holds no run slot.
        self.team_wait = None
        self.scratch = None  # The app-owned run folder of a task without a project.
        self.research_only = False
        self.citation_report = None  # The latest `verify_citations` report of this turn (root Orchestrator runs).
        self.citation_report_own = False  # Whether it is the Orchestrator's own, which a member's never replaces.
        self.report_saved = False  # Whether this turn saved report.md with `save_report`.


def research_enabled(scope):
    """Whether a scope turns on at least one research source (a missing `research` key means off)."""
    research = scope.get('research') if isinstance(scope, dict) else None
    sources = research.get('sources') if isinstance(research, dict) else None
    return isinstance(sources, dict) and any(v in ('allow', 'ask') for v in sources.values())


class _ResearchCall:
    """What `research.dispatch` gets for one tool call: per-source authorization, cache notes and the task.

    Every source call is decided by the task scope (`category: research`), audited without its query, and counted.
    """

    def __init__(self, scheduler, run, tool, call_id):
        self._scheduler = scheduler
        self._run = run
        self.tool = tool
        self.call_id = call_id
        self.task_id = run.task_id
        self.cancel = run.cancel
        with scheduler.lock:
            self.scope = copy.deepcopy(scheduler._task(run.task_id)['scope'])
        self.allowed = []
        self.cached = []

    def authorize(self, request, call_id=None):
        source = request.get('source') if isinstance(request, dict) else None
        if (not isinstance(request, dict) or request.get('category') != 'research' or request.get('tool') != self.tool
                or not isinstance(source, str) or not source or len(source) > 64):
            return {'decision': 'deny', 'rule': 'policy.invalid_request', 'reason': 'The research request is malformed.',
                    'scope_version': None, 'scope_digest': None}
        decision = self._scheduler._authorize(self._run, {'category': 'research', 'source': source, 'tool': self.tool},
                                              self.call_id)
        if decision.get('decision') == 'allow':
            self.allowed.append(source)
        return decision

    def note_call(self, source):
        """A request went to `source` (counted as `calls` on the root task; never money)."""
        if source in self.allowed:
            self._scheduler._count_research(self._run, source, cached=False)

    def note_cached(self, source):
        """The response cache answered for `source` instead of a request (counted as `cached`)."""
        if source in self.allowed:
            self.cached.append(source)
            self._scheduler._count_research(self._run, source, cached=True)


READ_ACCESS_RULE = 'access.read'


def _writes(request):
    """Whether a request changes files or leaves the sandbox (what a read-access run may never do)."""
    if not isinstance(request, dict):
        return False
    if request.get('category') == 'file_write':
        return True
    return request.get('category') == 'command' and request.get('sandbox') != 'workspace'


def _final(decision, rule=None):
    result = {k: decision.get(k) for k in ('decision', 'rule', 'reason', 'scope_version', 'scope_digest')}
    if rule:
        result['rule'] = rule
    return result


# ------------------------------------------------------------------------------------- scheduler

class Scheduler:
    def __init__(self, *, max_running, runtime_factory, policy, audit, events, budget_gate, locks, clock,
                 tasks, workspaces=None, interrupt_grace_s=INTERRUPT_GRACE_S,
                 monotonic=time.monotonic, tick_s=0.5, decide_options=None, research_dispatch=None, scratch_root=None,
                 research_usage_interval_s=RESEARCH_USAGE_INTERVAL_S, fulltext=None):
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
        self.interrupt_grace_s = interrupt_grace_s
        self.monotonic = monotonic
        # Extra keyword arguments for policy.decide (coordinator ruling): app_data, home, temp_roots.
        self.decide_options = dict(decide_options or {})
        # research.dispatch(ctx, name, arguments) -> result (stream 1B, wired by the service); None: no sources.
        self.research_dispatch = research_dispatch
        # `<storage>/research-runs`: tasks without a project run in `<scratch_root>/<task_id>/` (research/tasks.md).
        self.scratch_root = Path(scratch_root) if scratch_root is not None else None
        self.research_usage_interval_s = research_usage_interval_s
        # fulltext(call, paper, folder) -> (text, error): a paper's open-access text for the claim check, or None.
        self.fulltext = fulltext
        self._usage_last = {}
        self._usage_timers = {}
        self._bibtex = {}  # Root task ID -> {identifier: BibTeX} from `research_bibtex` results this app run.
        self._cond = threading.Condition(self.lock)
        self._runs = {}
        self._queue = []
        self._resuming = []  # Yielded parents waiting for a slot to continue their turn; served before the queue.
        self._sessions = {}
        self._closed = False
        self._stop_watch = threading.Event()
        self.orchestrator = orchestrator.Orchestrator(self)
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
            run.parent_task_id = task.get('parent_task_id')
            run.role = task.get('role')
            run.orchestrates = run.role == 'orchestrator' and run.parent_task_id is None
            run.access = task.get('access') or ('read' if run.orchestrates else 'write')
            run.research_only = task_rows.is_research(task)
            if run.research_only:
                run.access = 'read'  # A task without a project has nothing to write to (research/tasks.md).
            self._runs[task_id] = run
            if not self._queue and self._open_slots() > 0:
                self._start(run)
                return {'task_id': task_id, 'state': 'starting', 'position': None}
            self._queue.append(task_id)
            position = len(self._queue)
            self._set_state(run, 'queued', position=position)
            self._user_message(run)
            return {'task_id': task_id, 'state': 'queued', 'position': position}

    def cancel(self, task_id):
        """Cancel a task's run, then every running or queued child of that task (the parent stops first, so a
        parent waiting on its children sees the cancel rather than finished children)."""
        cancelled = self._cancel_one(task_id)
        with self.lock:
            children = [t for t, r in self._runs.items() if r.parent_task_id == task_id]
        for child_id in children:
            cancelled = self._cancel_one(child_id) or cancelled
        return cancelled

    def _cancel_one(self, task_id):
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

    def pump(self):
        with self.lock:
            started = False
            while self._queue and not self._closed and self._open_slots() > 0:
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
                totals = self.budget.totals(self._root(task))
                running.append(dict(self._lineage(run, task), task_id=run.task_id, project_id=run.project_id,
                                    state=task['agent']['state'], started_at=run.started_at,
                                    tokens={'used': totals['used'], 'budget': totals['budget']}, lock=run.lock_key))
            queued = [dict(self._lineage(self._runs[t], self._task(t)), task_id=t, project_id=self._runs[t].project_id,
                           position=i + 1) for i, t in enumerate(self._queue)]
            return {'max_running': self.max_running, 'running': running, 'queued': queued}

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

    def _root(self, task):
        """The task whose budget a run is charged against: the parent of a child, else the task itself."""
        parent_id = task.get('parent_task_id')
        return self._task(parent_id) if parent_id else task

    @staticmethod
    def _lineage(run, task):
        return {'parent_task_id': run.parent_task_id, 'role': run.role, 'provider': task.get('provider', 'codex')}

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
        return sum(1 for run in self._runs.values() if run.thread is not None and not run.yielded)

    def _free_slots(self):
        return self.max_running - self._running_count()

    def _open_slots(self):
        """Slots a queued run may take: parents resuming their turn are served first."""
        return self._free_slots() - len(self._resuming)

    def resume(self, run):
        """Take a run slot back for a parent that yielded it (`propose_team`, `wait_for`); call under the lock.

        The parent waits ahead of the FIFO queue until a slot is free, so resuming never pushes the running
        count above `max_running`. A cancelled parent stops waiting and ends its turn without a slot.
        """
        self._resuming.append(run.task_id)
        try:
            while not run.cancel.is_set() and (self._resuming[0] != run.task_id or self._free_slots() <= 0):
                self._cond.wait(0.5)
        finally:
            self._resuming.remove(run.task_id)
            self._cond.notify_all()
        if not run.cancel.is_set():
            run.yielded = False

    def hold_clock(self, run):
        """Stop counting a running parent's active time while it waits on its children (`wait_for`); under the lock."""
        if run.counted_since is not None:
            agent = self._task(run.task_id)['agent']
            agent['active_s'] = agent.get('active_s', 0.0) + (self.monotonic() - run.counted_since)
            run.counted_since = None

    def restart_clock(self, run):
        """Count active time again after `hold_clock`, unless the run left a counted state meanwhile."""
        if run.counted_since is None and self._task(run.task_id)['agent'].get('state') in COUNTED:
            run.counted_since = self.monotonic()

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
            if run.parent_task_id:
                self.orchestrator.child_changed(self._task(run.task_id), state)
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
            totals = self.budget.totals(self._root(self._task(run.task_id)))
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
                run.reservation = self.budget.reserve(self._root(task), run.text, run.provider, run.turn_id,
                                                      source_task_id=run.task_id)
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
        if status == 'completed' and not run.stop_reason:
            self._write_outputs(run)
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
        if run.research_only:
            # No clone, no branch and no project lock: an empty, app-owned folder that is not a git repository.
            if self.scratch_root is None:
                raise ValueError('There is no folder for tasks without a project.')
            folder = self.scratch_root / run.task_id
            if not IDENTIFIER.match(run.task_id) or folder.is_symlink():
                raise ValueError('Invalid run folder.')
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            run.scratch = str(folder)
            return
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
                if run.access == 'write':
                    # The agent's edits become a commit on its own task branch, so publishing and Merge carry them.
                    self.workspaces.commit(info, 'Interspace task %s turn %s' % (run.task_id[:8], run.turn_id))
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

    def _report_limits(self, run, raw):
        """Store the provider's latest usage-limit reading on the app state; only what the provider reported."""
        import limits
        provider = getattr(run, 'provider', None)
        reader = limits.READERS.get(provider)
        windows = reader(raw) if reader else []
        if not windows:
            return
        with self.lock:
            stored = self.store.state.setdefault('provider_limits', {})
            if not isinstance(stored, dict):
                stored = self.store.state['provider_limits'] = {}
            stored[provider] = limits.merge(stored.get(provider), windows, iso_time(self.clock()))
            self.store.changed(None)

    def _report_usage(self, run, usage):
        """`usage` is the turn's cumulative usage so far, reported after each model request (0B: Codex sends
        `thread/tokenUsage/updated` per request). Over budget, the turn is interrupted."""
        with self.lock:
            run.last_usage = copy.deepcopy(usage)
            amount = budget.charge(usage, run.provider)
            if amount is None or run.reservation is None:
                return
            totals = self.budget.totals(self._root(self._task(run.task_id)))
            own = self.budget.entry(run.reservation)['estimate']
            over = totals['budget'] is not None and totals['used'] + totals['reserved'] - own + amount > totals['budget']
        if over:
            self._stop(run, 'budget')

    # -- policy -------------------------------------------------------------------------------------

    def _decide(self, run, task, request):
        if run.access == 'read' and _writes(request):
            # Read members (orchestration.md "Shape") never write or leave the sandbox, whatever the scope says:
            # refused here, so the user is never asked to let a read role write.
            try:
                digest = self.policy.digest(task['scope'])
            except Exception:
                digest = None
            return {'decision': 'deny', 'rule': READ_ACCESS_RULE, 'ask': None,
                    'reason': 'This agent has read access, so it cannot change files or leave the sandbox.',
                    'scope_version': task['scope'].get('version'), 'scope_digest': digest}
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

    def _orchestrate(self, run, name, arguments):
        """An orchestration tool call from an Orchestrator session, shown as a `tool_call`/`tool_result` pair."""
        if not run.orchestrates or name not in orchestrator.TOOLS:
            raise ValueError('Unknown tool.')
        call_id = 'orc_' + uuid.uuid4().hex
        with self.lock:
            version = self._task(run.task_id)['scope'].get('version')
        shown = json.dumps(arguments, ensure_ascii=False)
        self._emit(run, 'tool_call', {'call_id': call_id, 'category': 'orchestrate', 'tool': name, 'app': None,
                                      'title': name.replace('_', ' ').capitalize(),
                                      'input': arguments if len(shown) <= 16384 else {'truncated': True},
                                      'decision': {'decision': 'allow', 'rule': 'orchestrate', 'scope_version': version}},
                   turn_id=run.turn_id, item_id=call_id)
        started = time.monotonic()
        try:
            result = self.orchestrator.call(run, name, arguments)
        except Exception:
            result = {'ok': False, 'error': {'code': 'unavailable', 'message': 'The orchestration tool failed.'}}
        error = result.get('error') if not result.get('ok') else None
        text = json.dumps({k: v for k, v in result.items() if k != 'ok'}, ensure_ascii=False)
        status = 'ok' if result.get('ok') else 'cancelled' if (error or {}).get('code') == 'cancelled' else 'error'
        self._emit(run, 'tool_result', {'call_id': call_id, 'status': status, 'exit_code': None,
                                        'duration_ms': int((time.monotonic() - started) * 1000),
                                        'output': {'text': text[:MAX_PATCH_CHARS], 'truncated': len(text) > MAX_PATCH_CHARS,
                                                   'blob_id': None}, 'error': error},
                   turn_id=run.turn_id, item_id=call_id)
        return result

    # -- research tools (research/tools.md, tasks.md) ------------------------------------------------------

    @staticmethod
    def _research_input(name, arguments):
        """What the tool card shows: the tool and its query or IDs, never more (events.md research additions)."""
        shown = {'tool': name}
        if not isinstance(arguments, dict):
            return shown
        if isinstance(arguments.get('query'), str):
            shown['query'] = arguments['query'][:500]
        if isinstance(arguments.get('id'), str):
            shown['id'] = arguments['id'][:200]
        if isinstance(arguments.get('ids'), list):
            shown['ids'] = [i[:200] for i in arguments['ids'][:100] if isinstance(i, str)]
        if isinstance(arguments.get('references'), list):
            shown['references'] = len(arguments['references'])
        if isinstance(arguments.get('sources'), list):
            shown['source'] = ', '.join(str(x)[:64] for x in arguments['sources'][:16])
        return shown

    @staticmethod
    def _cap(result, limit=MAX_RESEARCH_RESULT_BYTES):
        """Cut a research result to 64 KB of JSON by shortening its main list (`truncated: true`). A citation
        report is first made compact (every status kept, long text clipped), so as many references as possible fit."""
        def size(value):
            return len(json.dumps(value, ensure_ascii=False).encode('utf-8'))
        if size(result) <= limit:
            return result
        if isinstance(result.get('references'), list) and isinstance(result.get('summary'), dict):
            from research import citations
            result = dict(citations.compact(result), truncated=True)
            if size(result) <= limit:
                return result
        key = next((k for k in RESEARCH_LISTS if isinstance(result.get(k), list)), None)
        if key is None:
            return {'ok': False, 'error': {'code': 'bad_response', 'message': 'The research result was too large.'}}
        result = dict(result, truncated=True)
        items = list(result[key])
        while items and size(dict(result, **{key: items})) > limit:
            items = items[:max(0, min(len(items) - 1, len(items) * 3 // 4))]
        result[key] = items
        return result

    def _research(self, run, name, arguments, quiet=False):
        """A research tool call (from `RunContext.call_tool`), shown as a `tool_call`/`tool_result` pair.

        `quiet`: Interspace's own call (the BibTeX for `references.bib`), not an agent's: authorized, audited and
        counted the same way, but shown as no tool card.

        `research.dispatch` (stream 1B) runs it; each source it uses is authorized per call (`category: research`)
        through `_ResearchCall`, audited, and counted on the root task. The result goes to the agent as untrusted
        content; upstream error text never does.
        """
        call_id = 'res_' + uuid.uuid4().hex
        with self.lock:
            version = self._task(run.task_id)['scope'].get('version')
        emit = (lambda *a, **k: None) if quiet else self._emit
        emit(run, 'tool_call', {'call_id': call_id, 'category': 'research', 'tool': name, 'app': None,
                                      'title': name.replace('_', ' ').capitalize(),
                                      'input': self._research_input(name, arguments),
                                      'decision': {'decision': 'allow', 'rule': 'research', 'scope_version': version}},
                   turn_id=run.turn_id, item_id=call_id)
        started = time.monotonic()
        call = _ResearchCall(self, run, name, call_id)
        failed = False
        whole = None
        try:
            if name == 'research_corpus':
                payload = self._corpus_read(run, arguments)  # Interspace's own list: no source, no request.
            elif name in ('table_pending', 'record_table_cells'):
                payload = self._table_tool(run, name, arguments, call)  # The task's own evidence table.
            elif name in ('claims_pending', 'record_claim_support'):
                payload = self._claims_tool(run, name, arguments, call)  # The task's own claims file.
            elif name == 'save_report':
                payload = self._save_report(run, arguments)  # Into app data only: no source, no request.
            elif self.research_dispatch is None:
                raise _NoResearch()
            else:
                payload = self.research_dispatch(call, name, copy.deepcopy(arguments))
            if not isinstance(payload, dict):
                raise TypeError('research result')
            whole = payload  # A citation report is kept whole for references.bib; the agent gets it capped.
            result = self._cap(dict(payload, ok=True))
        except _NoResearch:
            failed = True
            result = {'ok': False, 'error': {'code': 'not_configured',
                                             'message': 'Research sources are not in this build yet.'}}
        except ValueError as error:
            result = {'ok': False, 'error': {'code': 'invalid_request', 'message': str(error)[:300]}}
        except Exception:
            failed = True
            result = {'ok': False, 'error': {'code': 'unavailable', 'message': 'The research tool failed.'}}
        self._research_actions(run, call, result, failed)
        error = result.get('error') if not result.get('ok') else None
        text = json.dumps({k: v for k, v in result.items() if k != 'ok'}, ensure_ascii=False)
        emit(run, 'tool_result', {'call_id': call_id, 'status': 'ok' if result.get('ok') else 'error',
                                        'exit_code': None, 'duration_ms': int((time.monotonic() - started) * 1000),
                                        'output': {'text': text[:MAX_PATCH_CHARS], 'truncated': len(text) > MAX_PATCH_CHARS,
                                                   'blob_id': None}, 'error': error},
                   turn_id=run.turn_id, item_id=call_id)
        if result.get('ok') and name == 'verify_citations':
            # The card says when it shows only part of the report (an event holds at most 64 KB).
            card = self._cap({k: v for k, v in result.items() if k != 'ok'}, MAX_EVENT_BYTES - 4096)
            emit(run, 'citation_report', card, turn_id=run.turn_id, item_id='cite_' + call_id)
            self._keep_report(run, {k: v for k, v in whole.items() if k != 'truncated'})
        if result.get('ok') and name == 'research_bibtex':
            self._keep_bibtex(run, result)
        if result.get('ok') and not quiet:
            self._corpus_add(run, call_id, name, arguments, whole)
        return result

    def _research_actions(self, run, call, result, failed):
        """One `action` record per source the call was allowed to use: failed when the source was skipped."""
        skipped = set()
        for item in result.get('skipped') or [] if result.get('ok') else []:
            if isinstance(item, dict) and isinstance(item.get('source'), str):
                skipped.add(item['source'])
        for source in dict.fromkeys(call.allowed):
            outcome = 'failed' if failed or source in skipped else 'succeeded'
            try:
                self._audit(run, 'action', call_id=call.call_id, outcome=outcome,
                            request={'category': 'research', 'source': source, 'tool': call.tool})
            except Exception:
                self._error(run, 'audit_failed', 'A research call could not be recorded in the audit log.', True,
                            call.call_id)

    def _root_task(self, run):
        with self.lock:
            return self._root(self._task(run.task_id))

    def _count_research(self, run, source, cached):
        with self.lock:
            root = self._root(self._task(run.task_id))
            usage = root['agent'].setdefault('research_usage', {'calls': {}, 'cached': {}})
            bucket = usage.setdefault('cached' if cached else 'calls', {})
            bucket[source] = bucket.get(source, 0) + 1
            self.store.changed(root['id'])
            self._usage_changed(root['id'])

    def _usage_changed(self, root_id):
        """`research_usage` on the root task, at most once per interval; the last count is always sent. Under lock."""
        now = self.monotonic()
        last = self._usage_last.get(root_id)
        if last is None or now - last >= self.research_usage_interval_s:
            self._emit_usage(root_id)
            return
        if root_id not in self._usage_timers:
            timer = threading.Timer(self.research_usage_interval_s - (now - last), self._timed_usage, args=(root_id,))
            timer.daemon = True
            self._usage_timers[root_id] = timer
            timer.start()

    def _timed_usage(self, root_id):
        with self.lock:
            self._usage_timers.pop(root_id, None)
            self._emit_usage(root_id)

    def _emit_usage(self, root_id):
        self._usage_last[root_id] = self.monotonic()
        try:
            root = self._task(root_id)
        except ValueError:
            return
        usage = root['agent'].get('research_usage') or {}
        self.events.append(root_id, root['agent'].get('project_id'), 'research_usage',
                           {'calls': dict(usage.get('calls') or {}), 'cached': dict(usage.get('cached') or {})})

    def _keep_report(self, run, report):
        """The latest citation report of the root Orchestrator's turn feeds its `references.bib`. The Orchestrator's
        own check wins: a member's check (often of a few references) is used only while the Orchestrator has none."""
        with self.lock:
            own = not run.parent_task_id
            root = run if own else self._runs.get(run.parent_task_id)
            if root is None or (root.citation_report_own and not own):
                return
            root.citation_report = report
            root.citation_report_own = own

    def _keep_bibtex(self, run, result):
        root_id = self._root_task(run)['id']
        with self.lock:
            kept = self._bibtex.setdefault(root_id, {})
            for entry in result.get('entries') or []:
                if isinstance(entry, dict) and isinstance(entry.get('bibtex'), str) and entry['bibtex'].strip():
                    key = _bib_key(entry.get('id'))
                    if key:
                        kept[key] = entry['bibtex'].strip()

    # -- corpus (docs/superpowers/specs/2026-11-20-task-corpus-design.md) -----------------------------------

    def _corpus_path(self, root_id):
        return Path(self.events.root) / root_id / 'corpus.json'

    @staticmethod
    def _member(task):
        """Who made a call, as the Corpus shows it: the member's role title, or 'Orchestrator' for the root task."""
        role = task.get('role')
        if not task.get('parent_task_id') or not isinstance(role, str):
            return 'Orchestrator'
        return role.replace('_', ' ').capitalize()

    def _all_events(self, task_id):
        found, after = [], 0
        while True:
            page = self.events.read(task_id, after, 1000)
            found.extend(page['events'])
            if page['complete'] or not page['events']:
                return found
            after = page['events'][-1]['seq']

    def _corpus_save(self, root_id, value):
        path = self._corpus_path(root_id)
        if path.is_symlink():
            raise ValueError('The corpus file was changed.')
        path.parent.mkdir(parents=True, exist_ok=True)
        value['updated_at'] = iso_time(self.clock())
        _write_file(path, json.dumps(value, ensure_ascii=False, separators=(',', ':')))

    def _corpus_load(self, root, skip=()):
        """The root research task's corpus: the saved file, or one rebuilt (and saved) from the events of the task
        and its members. Under `self.lock`, so a rebuild and live writes never interleave."""
        path = self._corpus_path(root['id'])
        try:
            saved = None if path.is_symlink() else research_corpus.load(json.loads(path.read_text(encoding='utf-8')))
        except (OSError, ValueError):
            saved = None
        if saved is not None:
            return saved
        members = [t for t in self.store.agent_tasks() if t.get('parent_task_id') == root['id']]
        lists = [('Orchestrator', self._all_events(root['id']))]
        lists += [(self._member(t), self._all_events(t['id'])) for t in members]
        built, incomplete = research_corpus.rebuild(lists, skip=skip)
        built['incomplete'] = incomplete
        self._corpus_save(root['id'], built)
        return built

    def _corpus_add(self, run, call_id, name, arguments, whole):
        """Merge a successful research call's whole result into the root research task's corpus."""
        if not isinstance(whole, dict):
            return
        shown = self._research_input(name, arguments)
        changed = False
        try:
            with self.lock:
                task = self._task(run.task_id)
                root = self._root(task)
                if not task_rows.is_research(root):
                    return
                value = self._corpus_load(root, skip=(call_id,))
                member, at = self._member(task), iso_time(self.clock())
                if name == 'verify_citations':
                    by = research_corpus.MEMBER if task.get('parent_task_id') else research_corpus.ORCHESTRATOR
                    changed = research_corpus.add_report(value, whole.get('references'), by, member, at)
                else:
                    found = {'tool': name, 'query': shown.get('query') or shown.get('id'), 'member': member, 'at': at}
                    changed = research_corpus.add_result(value, name, whole, found)
                if changed:
                    self._corpus_save(root['id'], value)
                counts = research_corpus.counts(value)
        except Exception:
            self._error(run, 'corpus_failed', "Could not update the task's paper list.", True, call_id)
            return
        if changed:
            self.events.append(root['id'], root['agent'].get('project_id'), 'corpus', counts)

    def _corpus_read(self, run, arguments):
        """`research_corpus` for an agent: a page of the root research task's corpus (research/corpus.py `view`)."""
        with self.lock:
            root = self._root(self._task(run.task_id))
            if not task_rows.is_research(root):
                raise ValueError('Only research tasks have a corpus.')
            value = copy.deepcopy(self._corpus_load(root))
        return research_corpus.view(value, arguments)

    # -- claim check (docs/superpowers/specs/2026-11-20-claim-check-design.md) ------------------------------

    def _claims_path(self, root_id):
        return Path(self.events.root) / root_id / 'claims.json'

    def _claims_load(self, root_id):
        path = self._claims_path(root_id)
        try:
            value = None if path.is_symlink() else json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) and value.get('v') == research_claims.V else None

    def _report_text(self, root_id):
        path = Path(self.events.root) / root_id / 'outputs' / 'report.md'
        if path.is_symlink() or not path.is_file():
            raise ValueError('This task has no saved report yet.')
        return path.read_text(encoding='utf-8')

    def claims_start(self, task_id):
        """`claims_start`: split the saved report into claims and start a new check, replacing any earlier one."""
        with self.lock:
            task = self.store.task(task_id)
            if not task_rows.is_research(task) or task.get('parent_task_id'):
                raise ValueError('Only research tasks have a claim check.')
            if (task.get('agent') or {}).get('state') in ('queued', 'starting', 'running', 'waiting_lock', 'cancelling'):
                raise ValueError('Wait for the task to finish before checking claims.')
            text = self._report_text(task_id)
            value = research_claims.start(text, self._corpus_load(task), iso_time(self.clock()))
            if not value['claims']:
                raise ValueError('The report has no numbered citations to check.')
            self._claims_save(task_id, value)
            counts = research_claims.counts(value)
        self.events.append(task_id, None, 'claims', counts)
        return research_claims.public(value)

    def claims(self, task_id):
        """`task_claims`: the current claim check for the UI."""
        with self.lock:
            task = self.store.task(task_id)
            if not task_rows.is_research(task) or task.get('parent_task_id'):
                raise ValueError('Only research tasks have a claim check.')
            return research_claims.public(self._claims_load(task_id))

    def _claims_save(self, root_id, value):
        path = self._claims_path(root_id)
        if path.is_symlink():
            raise ValueError('The claims file was changed.')
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_file(path, json.dumps(value, ensure_ascii=False, separators=(',', ':')))

    def _claims_with_fulltext(self, run, root, ids, todo, call):
        """Fetch full text for the batch's papers outside the lock (it may wait on an ask), then hand out the batch
        with each claim's best passages (2026-11-20-claim-fulltext-design.md)."""
        texts = {}
        folder = Path(self.events.root) / root['id'] / 'fulltext'
        for claim in todo:
            key = research_fulltext.cache_key(claim['paper'])
            if key in texts:
                continue
            if self.fulltext is None or call is None:
                texts[key] = (None, 'Full text is not available in this build.')
                continue
            try:
                texts[key] = self.fulltext(call, claim['paper'], folder)
            except Exception:
                texts[key] = (None, 'The full text could not be read.')
        with self.lock:
            value = self._claims_load(root['id'])
            if value is None:
                raise ValueError('No claim check has started. The user starts one with Check claims.')
            at = iso_time(self.clock())
            for claim in value['claims']:
                if claim['id'] in ids and claim.get('status') == 'pending' and not claim.get('fulltext_tried'):
                    text, error = texts.get(research_fulltext.cache_key(claim.get('paper') or {}), (None, None))
                    research_claims.attach(claim, text, error, at)
            self._claims_save(root['id'], value)
            out = research_claims.pending(value, ids=ids)
        return out

    def _claims_tool(self, run, name, arguments, call=None):
        arguments = arguments if isinstance(arguments, dict) else {}
        with self.lock:
            task = self._task(run.task_id)
            root = self._root(task)
            if not task_rows.is_research(root):
                raise ValueError('Only research tasks have a claim check.')
            value = self._claims_load(root['id'])
            if name == 'claims_pending':
                if set(arguments) - {'limit'}:
                    raise ValueError('claims_pending takes only limit.')
                if value is None:
                    raise ValueError('No claim check has started. The user starts one with Check claims.')
                ids = research_claims.next_ids(value, arguments.get('limit', research_claims.MAX_BATCH))
                todo = [copy.deepcopy(c) for c in value['claims']
                        if c['id'] in ids and not c.get('fulltext_tried')
                        and ((c.get('paper') or {}).get('arxiv_id') or (c.get('paper') or {}).get('oa_url'))]
        if name == 'claims_pending':
            return self._claims_with_fulltext(run, root, ids, todo, call)
        with self.lock:
            value = self._claims_load(root['id'])
            if set(arguments) != {'results'}:
                raise ValueError('record_claim_support takes only results.')
            by = (run.provider or 'agent') + ' ' + (self._member(task) or 'agent')
            out = research_claims.record(value, self._report_text(root['id']), arguments['results'], by,
                                         iso_time(self.clock()))
            if out['recorded']:
                self._claims_save(root['id'], value)
        if out['recorded']:
            self.events.append(root['id'], root['agent'].get('project_id'), 'claims', out['counts'])
        return out

    # -- evidence table (docs/superpowers/specs/2026-11-20-evidence-table-design.md) ---------------------------

    def _table_path(self, root_id):
        return Path(self.events.root) / root_id / 'evidence.json'

    def _table_load(self, root_id):
        path = self._table_path(root_id)
        try:
            value = None if path.is_symlink() else json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) and value.get('v') == research_evidence.V else None

    def _table_save(self, root_id, value):
        path = self._table_path(root_id)
        if path.is_symlink():
            raise ValueError('The evidence table file was changed.')
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_file(path, json.dumps(value, ensure_ascii=False, separators=(',', ':')))

    def _research_root(self, task_id):
        task = self.store.task(task_id)
        if not task_rows.is_research(task) or task.get('parent_task_id'):
            raise ValueError('Only research tasks have an evidence table.')
        return task

    def table_start(self, task_id, columns, rows):
        """`table_start`: a new evidence table over the cited or the checked papers, replacing any earlier one."""
        cols = research_evidence.columns(columns)
        with self.lock:
            task = self._research_root(task_id)
            if (task.get('agent') or {}).get('state') in ('queued', 'starting', 'running', 'waiting_lock', 'cancelling'):
                raise ValueError('Wait for the task to finish before filling the evidence table.')
            try:
                report = self._report_text(task_id)
            except ValueError:
                report = None
            papers = research_evidence.rows_from(rows, report, self._corpus_load(task))
            value = research_evidence.start(cols, papers, iso_time(self.clock()))
            self._table_save(task_id, value)
            counts = research_evidence.counts(value)
        self.events.append(task_id, None, 'evidence', counts)
        return research_evidence.public(value)

    def table(self, task_id):
        with self.lock:
            self._research_root(task_id)
            return research_evidence.public(self._table_load(task_id))

    def table_resolve(self, task_id, row, column, value):
        with self.lock:
            self._research_root(task_id)
            table = self._table_load(task_id)
            if table is None:
                raise ValueError('There is no evidence table yet.')
            research_evidence.resolve(table, row, column, value, iso_time(self.clock()))
            self._table_save(task_id, table)
            counts = research_evidence.counts(table)
        self.events.append(task_id, None, 'evidence', counts)
        return research_evidence.public(table)

    def table_export(self, task_id):
        """Write outputs/evidence.csv from the table's final values."""
        with self.lock:
            self._research_root(task_id)
            table = self._table_load(task_id)
            if table is None:
                raise ValueError('There is no evidence table yet.')
            folder = Path(self.events.root) / task_id / 'outputs'
            if folder.is_symlink():
                raise ValueError('The outputs folder was changed.')
            folder.mkdir(parents=True, exist_ok=True)
            _write_file(folder / 'evidence.csv', research_evidence.to_csv(table))
            outputs = list_outputs(folder)
        self.events.append(task_id, None, 'outputs',
                           {'outputs': [{k: o[k] for k in ('name', 'kind', 'bytes')} for o in outputs]})
        return {'name': 'evidence.csv'}

    def _table_tool(self, run, name, arguments, call=None):
        arguments = arguments if isinstance(arguments, dict) else {}
        provider = getattr(run, 'provider', None) or 'agent'
        with self.lock:
            task = self._task(run.task_id)
            root = self._root(task)
            if not task_rows.is_research(root):
                raise ValueError('Only research tasks have an evidence table.')
            table = self._table_load(root['id'])
            if table is None:
                raise ValueError('There is no evidence table yet. The user starts one in the Evidence tab.')
            if name == 'table_pending':
                if set(arguments) - {'limit'}:
                    raise ValueError('table_pending takes only limit.')
                ids = research_evidence.pending_rows(table, provider, arguments.get('limit', research_evidence.MAX_BATCH))
                todo = [copy.deepcopy(r) for r in table['rows'] if r['id'] in ids and not r.get('fulltext_tried')]
            else:
                if set(arguments) != {'results'}:
                    raise ValueError('record_table_cells takes only results.')
                out = research_evidence.record(table, provider, arguments['results'], iso_time(self.clock()))
                if out['recorded']:
                    self._table_save(root['id'], table)
        if name == 'record_table_cells':
            if out['recorded']:
                self.events.append(root['id'], root['agent'].get('project_id'), 'evidence', out['counts'])
            return out
        texts = {}
        folder = Path(self.events.root) / root['id'] / 'fulltext'
        for row in todo:
            paper = row['paper']
            if not (paper.get('arxiv_id') or paper.get('oa_url')) or self.fulltext is None or call is None:
                texts[row['id']] = None
                continue
            try:
                texts[row['id']] = self.fulltext(call, paper, folder)[0]
            except Exception:
                texts[row['id']] = None
        with self.lock:
            table = self._table_load(root['id'])
            for row in table['rows']:
                if row['id'] in ids and not row.get('fulltext_tried'):
                    research_evidence.attach(row, texts.get(row['id']), table['columns'])
            self._table_save(root['id'], table)
            return research_evidence.pending(table, provider, ids)

    def corpus(self, task_id):
        """`task_corpus`: the research task's corpus, rebuilt from its saved events the first time."""
        with self.lock:
            task = self.store.task(task_id)
            if not task_rows.is_research(task) or task.get('parent_task_id'):
                raise ValueError('Only research tasks have a corpus.')
            value = copy.deepcopy(self._corpus_load(task))
        value.setdefault('incomplete', 0)
        return value

    # -- outputs (research/tasks.md "Outputs") ---------------------------------------------------------------

    def _save_report(self, run, arguments):
        """`save_report` (root Orchestrator of a research task): write report.md now, inside app data only."""
        if not (run.research_only and run.orchestrates):
            raise ValueError('Only the Orchestrator of a research task saves a report.')
        if not isinstance(arguments, dict) or set(arguments) != {'markdown'}:
            raise ValueError('save_report takes only markdown.')
        text = arguments['markdown']
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_SAVED_REPORT:
            raise ValueError('markdown must be 1 to 400,000 characters of text.')
        problem = research_claims.report_problem(text)
        if problem:
            raise ValueError(problem)  # A status reply or a question never becomes report.md.
        folder = self._outputs_folder(run)
        _write_file(folder / 'report.md', text)
        run.report_saved = True
        self._emit_outputs(run, folder)
        return {'saved': 'report.md', 'characters': len(text)}

    def _outputs_folder(self, run):
        folder = self.events.root / run.task_id / 'outputs'
        if folder.is_symlink():
            raise ValueError('The outputs folder was changed.')
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _emit_outputs(self, run, folder):
        outputs = list_outputs(folder)
        self._emit(run, 'outputs', {'outputs': [{k: o[k] for k in ('name', 'kind', 'bytes')} for o in outputs]},
                   turn_id=run.turn_id)

    def _write_outputs(self, run):
        """A research task's Orchestrator finished a turn in which it saved a report: add the BibTeX of the references
        the citation checker verified this turn. A turn without `save_report` leaves the outputs as they are, so a
        reply that asks the user something never replaces the report (2026-11-20-save-report-design.md)."""
        if not (run.research_only and run.orchestrates and run.report_saved and run.citation_report is not None):
            return
        try:
            folder = self._outputs_folder(run)
            _write_file(folder / 'references.bib', self._bibliography(run, run.citation_report))
        except Exception:
            self._error(run, 'outputs_failed', 'Could not save the references in the app.', True)
            return
        self._emit_outputs(run, folder)

    def _bibliography(self, run, report):
        kept, left_out, wanted = [], [], []
        for reference in report.get('references') or []:
            if not isinstance(reference, dict):
                continue
            title = _reference_title(reference)
            status = reference.get('status')
            match = reference.get('match') if isinstance(reference.get('match'), dict) else None
            if status in ('verified', 'mismatch') and match is not None:
                identifier = _bib_id(match)
                kept.append((reference, match, identifier))
                if identifier and _bib_key(identifier) not in self._bibtex.get(run.task_id, {}):
                    wanted.append(identifier)
            else:
                label = {'retracted': 'retracted', 'not_found': 'not found'}.get(status, 'not checked')
                left_out.append('%% Left out, %s: %s' % (label, title))
        if wanted:
            # BibTeX the agents did not fetch yet comes through the same checked, audited research path.
            self._research(run, 'research_bibtex', {'ids': list(dict.fromkeys(wanted))[:100]}, quiet=True)
        fetched = self._bibtex.get(run.task_id, {})
        lines = ['% References checked by the Interspace citation checker on ' + str(report.get('checked_at')) + '.',
                 '%% Verified: %d. Mismatch: %d (marked below).' % (
                     sum(1 for r, _, _ in kept if r.get('status') == 'verified'),
                     sum(1 for r, _, _ in kept if r.get('status') == 'mismatch'))]
        lines += left_out
        for reference, match, identifier in kept:
            lines.append('')
            if reference.get('status') == 'mismatch':
                fields = ', '.join(f for f in reference.get('fields') or [] if isinstance(f, str))
                lines.append('%% mismatch (%s): %s' % (fields, _reference_title(reference)))
            entry = fetched.get(_bib_key(identifier)) if identifier else None
            if entry is None:
                lines.append('% Built by Interspace from the verified record; the sources gave no BibTeX for it.')
                entry = _record_bibtex(match, reference.get('index'))
            lines.append(entry)
        return '\n'.join(lines) + '\n'

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


class _NoResearch(Exception):
    pass


def _bib_id(match):
    """The identifier `research_bibtex` takes for a matched record: arXiv for arXiv papers, else the DOI."""
    arxiv_id, doi = match.get('arxiv_id'), match.get('doi')
    if isinstance(arxiv_id, str) and arxiv_id and (not doi or str(doi).lower().startswith('10.48550/')):
        return 'arXiv:' + arxiv_id
    if isinstance(doi, str) and doi:
        return doi
    return None


def _bib_key(identifier):
    if not isinstance(identifier, str) or not identifier.strip():
        return None
    text = identifier.strip().lower()
    text = re.sub(r'^(https?://(dx\.)?doi\.org/|doi:)', '', text)
    return text


def _reference_title(reference):
    given = reference.get('input') if isinstance(reference.get('input'), dict) else {}
    match = reference.get('match') if isinstance(reference.get('match'), dict) else {}
    title = given.get('title') or given.get('raw') or match.get('title') or given.get('doi') or 'untitled reference'
    return ' '.join(str(title).split())[:300]


def _bib_text(value):
    return re.sub(r'[{}\\]', '', ' '.join(str(value).split()))[:1000]


def _record_bibtex(match, index):
    """A minimal entry from the checker's verified record, when no source gave BibTeX."""
    authors = [a for a in match.get('authors') or [] if isinstance(a, str)]
    fields = [('title', match.get('title')), ('author', ' and '.join(authors[:50]) if authors else None),
              ('year', match.get('year')), ('journal', match.get('venue')), ('doi', match.get('doi')),
              ('eprint', match.get('arxiv_id'))]
    body = ',\n'.join('  %s = {%s}' % (k, _bib_text(v)) for k, v in fields if v not in (None, ''))
    return '@misc{interspace%s,\n%s\n}' % (index if type(index) is int else 0, body)


def _write_file(path, text):
    partial = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    partial.write_text(text, encoding='utf-8')
    os.replace(str(partial), str(path))


def list_outputs(folder):
    """`[{name, kind, bytes, updated_at}]` for the known output files in a task's outputs folder."""
    found = []
    folder = Path(folder)
    if folder.is_symlink() or not folder.is_dir():
        return found
    for name, kind in OUTPUT_NAMES:
        path = folder / name
        if path.is_symlink() or not path.is_file():
            continue
        info = path.stat()
        found.append({'name': name, 'kind': kind, 'bytes': info.st_size, 'updated_at': iso_time(info.st_mtime)})
    return found
