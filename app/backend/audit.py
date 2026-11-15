"""Append-only audit log.

Contract: docs/superpowers/specs/agentic-spaces/scope.md (audit record). The log is JSON lines, written and
fsynced one record at a time, and never rewritten. A crash can leave at most a torn last line; it is
terminated, kept and skipped, never repaired in place. Records of removed kinds in older logs stay readable.
"""
import hashlib
import json
import os
import re
import shlex
import threading
import time
import uuid

import scope

from timeutil import iso_time

VERSION = 1
ACTORS = ('agent', 'user', 'system')
KINDS = ('decision', 'action', 'answer', 'scope')
DECISIONS = ('allow', 'ask', 'deny')
OUTCOMES = ('succeeded', 'failed', 'outcome_unknown', 'cancelled')
RECORD_FIELDS = ('v', 'id', 'at', 'prev', 'actor', 'kind', 'task_id', 'project_id', 'turn_id', 'call_id', 'request',
                 'decision', 'rule', 'scope_version', 'scope_digest', 'outcome', 'idempotency_key', 'detail')
INPUT_FIELDS = RECORD_FIELDS[4:]
DEFAULT_READ_LIMIT = 500
MAX_ARG_CHARS = 200
MAX_ARGV_CHARS = 2000
MAX_TITLE_CHARS = 160
MAX_DETAIL_CHARS = 300
MAX_PATH_CHARS = 1024
MAX_PATHS = 100
TAIL_CHUNK = 65536

# Request fields that may be recorded, per category. Everything else (contents, queries, env) is dropped.
REQUEST_FIELDS = {
    'file_read': ('project_id', 'path'),
    'file_write': ('project_id', 'paths'),
    'command': ('argv', 'command', 'cwd', 'sandbox', 'network', 'project_id'),
    'network': ('host', 'port', 'via'),
    'web_search': (),
    'mcp': ('server', 'tool'),
}
DETAIL_FIELDS = {
    'answer': ('ask_id', 'request_digest'),
    'scope': ('from_version', 'to_version', 'from_digest', 'to_digest'),
}


class AuditFailed(ValueError):
    """The record could not be made durable, so the audited action must not run."""
    code = 'audit_failed'


def _fail(message):
    raise ValueError(message)


# ---------------------------------------------------------------- durable append

def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_directory(path):
    if os.path.isdir(path):
        return
    os.makedirs(path, exist_ok=True)
    _fsync_directory(os.path.dirname(os.path.abspath(path)))


def _append_line(path, line, *, terminate_torn):
    """Append one line and fsync it. `terminate_torn` first ends a torn last line with a newline."""
    created = not os.path.exists(path)
    with open(path, 'ab') as handle:
        if terminate_torn:
            handle.write(b'\n')
        handle.write(line + b'\n')
        handle.flush()
        os.fsync(handle.fileno())
    if created:
        _fsync_directory(os.path.dirname(os.path.abspath(path)))


def _tail(path):
    """(last line bytes or None, whether the file ends without a newline)."""
    try:
        size = os.path.getsize(path)
    except FileNotFoundError:
        return None, False
    if size == 0:
        return None, False
    with open(path, 'rb') as handle:
        handle.seek(size - 1)
        torn = handle.read(1) != b'\n'
        end = size if torn else size - 1
        start, data = end, b''
        while start > 0:
            start = max(0, start - TAIL_CHUNK)
            handle.seek(start)
            data = handle.read(end - start)
            if b'\n' in data:
                break
        return data.rsplit(b'\n', 1)[-1], torn


def _line_digest(line):
    return 'sha256:' + hashlib.sha256(line).hexdigest()


def _encode(record):
    return json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def _parse(line):
    """A JSON object of the current version, or None for anything malformed."""
    try:
        record = json.loads(line.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(record, dict) or record.get('v') != VERSION:
        return None
    return record


# ---------------------------------------------------------------- record sanitizing

def _clip(text, limit):
    return text[:limit] if isinstance(text, str) else text


def _record_argv(argv):
    out, total = [], 0
    for arg in scope.redact_argv([str(a) for a in argv]):
        arg = arg[:MAX_ARG_CHARS]
        if total + len(arg) > MAX_ARGV_CHARS:
            break
        out.append(arg)
        total += len(arg)
    return out


def sanitize_request(request):
    """The recordable part of a scope request: IDs, refs, paths, hosts and redacted argv only."""
    if request is None:
        return None
    if not isinstance(request, dict) or request.get('category') not in REQUEST_FIELDS:
        _fail('Audit records need a known request category.')
    clean = {'category': request['category']}
    for field in REQUEST_FIELDS[request['category']]:
        if field not in request:
            continue
        value = request[field]
        if field == 'argv' and isinstance(value, list):
            value = _record_argv(value)
        elif field == 'command' and isinstance(value, str):
            try:
                value = shlex.join(_record_argv(shlex.split(value)))
            except ValueError:
                value = '[unparsed command]'
        elif field == 'title':
            value = _clip(value, MAX_TITLE_CHARS)
        elif field == 'paths' and isinstance(value, list):
            value = [_clip(p, MAX_PATH_CHARS) for p in value[:MAX_PATHS]]
        elif field in ('path', 'cwd'):
            value = _clip(value, MAX_PATH_CHARS)
        elif isinstance(value, str):
            value = _clip(value, MAX_PATH_CHARS)
        if not _is_json_scalar_or_list(value):
            continue
        clean[field] = value
    return clean


def _is_json_scalar_or_list(value):
    if value is None or isinstance(value, (str, bool, int)):
        return True
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _sanitize_detail(kind, detail):
    if detail is None:
        if kind in DETAIL_FIELDS:
            _fail('This audit record kind needs its detail fields.')
        return None
    if not isinstance(detail, dict):
        _fail('Audit detail must be an object.')
    allowed = DETAIL_FIELDS.get(kind)
    if allowed is not None and set(detail) != set(allowed):
        _fail('Audit detail for %s records holds exactly %s.' % (kind, ', '.join(allowed)))
    clean = {}
    for key, value in detail.items():
        if not isinstance(key, str) or not (value is None or isinstance(value, (str, int, bool))):
            _fail('Audit detail holds short scalar values only.')
        clean[key] = _clip(value, MAX_DETAIL_CHARS)
    return clean


def _validate(record):
    if not isinstance(record, dict):
        _fail('An audit record must be an object.')
    unknown = set(record) - set(INPUT_FIELDS) - {'v'}
    if unknown or record.get('v', VERSION) != VERSION:
        _fail('The audit record has unknown fields or version.')
    actor, kind = record.get('actor'), record.get('kind')
    if actor not in ACTORS or kind not in KINDS:
        _fail('Audit records need a known actor and kind.')
    request = record.get('request')
    decision, outcome = record.get('decision'), record.get('outcome')
    if kind == 'decision':
        if request is None or decision not in DECISIONS or not isinstance(record.get('rule'), str):
            _fail('Decision records need the request, decision and rule.')
    elif kind == 'action':
        if request is None or outcome not in OUTCOMES:
            _fail('Action records need the request and a known outcome.')
    elif kind == 'answer':
        if decision not in scope.ANSWER_DECISIONS:
            _fail('Answer records need a known answer.')
    elif kind == 'scope':
        if request is not None:
            _fail('Scope records carry no request.')
    if outcome is not None and outcome not in OUTCOMES:
        _fail('Unknown action outcome.')


# ---------------------------------------------------------------- audit log

class AuditLog:
    """`<directory>/<YYYY-MM>.jsonl`, one record per line, appended and fsynced before the action runs."""

    def __init__(self, directory, *, clock=time.time):
        self.directory = str(directory)
        self.clock = clock
        self._lock = threading.Lock()
        self._tails = {}  # path -> (digest of last line, torn)

    def _path(self, month):
        return os.path.join(self.directory, month + '.jsonl')

    def append(self, record):
        """Validate, sanitize and durably append one record; returns the stored record.

        Raises ValueError for an invalid record and AuditFailed when the write is not durable.
        """
        _validate(record)
        stored = {field: None for field in RECORD_FIELDS}
        for field in INPUT_FIELDS:
            stored[field] = record.get(field)
        stored['request'] = sanitize_request(record.get('request'))
        stored['detail'] = _sanitize_detail(stored['kind'], record.get('detail'))
        with self._lock:
            now = self.clock()
            stored.update(v=VERSION, id=uuid.uuid4().hex, at=iso_time(now))
            path = self._path(stored['at'][:7])
            try:
                _ensure_directory(self.directory)
                if path not in self._tails:
                    last, torn = _tail(path)
                    self._tails[path] = (_line_digest(last) if last is not None else None, torn)
                prev, torn = self._tails[path]
                stored['prev'] = prev
                line = _encode(stored)
                _append_line(path, line, terminate_torn=torn)
            except OSError:
                self._tails.pop(path, None)  # re-read the tail next time; the file may hold a partial line
                raise AuditFailed('The audit log could not be written, so the action did not run.')
            self._tails[path] = (_line_digest(line), False)
        return stored

    def _files(self):
        try:
            names = os.listdir(self.directory)
        except FileNotFoundError:
            return []
        return sorted((n for n in names if re.match(r'^\d{4}-\d{2}\.jsonl$', n)), reverse=True)

    def read(self, task_id=None, since=None, limit=DEFAULT_READ_LIMIT):
        """Records newest first, skipping malformed lines; `since` is an ISO time (inclusive)."""
        results = []
        for name in self._files():
            if since is not None and name[:7] < since[:7]:
                break
            with open(os.path.join(self.directory, name), 'rb') as handle:
                lines = handle.read().split(b'\n')
            for line in reversed(lines):
                record = _parse(line) if line else None
                if record is None or not isinstance(record.get('at'), str):
                    continue
                if task_id is not None and record.get('task_id') != task_id:
                    continue
                if since is not None and record['at'] < since:
                    continue
                results.append(record)
                if len(results) >= limit:
                    return results
        return results

    def verify(self):
        """Hash-chain and format problems as [{"file", "line", "problem"}]; detects accidental edits."""
        problems = []
        for name in sorted(self._files()):
            with open(os.path.join(self.directory, name), 'rb') as handle:
                lines = handle.read().split(b'\n')
            if lines and lines[-1] == b'':
                lines.pop()
            previous = None
            for number, line in enumerate(lines, 1):
                record = _parse(line)
                if record is None:
                    problems.append({'file': name, 'line': number, 'problem': 'malformed'})
                elif record.get('prev') != (_line_digest(previous) if previous is not None else None):
                    problems.append({'file': name, 'line': number, 'problem': 'prev_mismatch'})
                previous = line
        return problems
