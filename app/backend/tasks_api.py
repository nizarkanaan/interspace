"""Archive and delete tasks (docs/superpowers/specs/2026-11-20-archive-delete-design.md).

A working task is never archived or deleted. Deleting removes the task, its subagents and everything Interspace stored
for them inside app data. A code task's published branch is deleted from the user's repository only when the user
chose it, never while it is checked out, and each deletion is written to the audit log. Usage records and the audit
log itself stay.
"""
import shutil
from pathlib import Path

import time

from timeutil import iso_time
import worktree_merge

BUSY = ('queued', 'starting', 'running', 'waiting_lock', 'cancelling', 'paused_ask', 'paused_scope', 'paused_team')
WORKING = 'Stop this task first. A working task, or one waiting on you, cannot be archived or deleted.'


def _root_task(app, task_id):
    """The root agent task and the dict that holds it. Under app.lock."""
    if not isinstance(task_id, str) or not task_id:
        raise ValueError('Missing task_id.')
    task = app.store.task(task_id)
    if task.get('mode') != 'agent':
        raise ValueError('Only agent tasks can be archived or deleted.')
    if task.get('parent_task_id'):
        raise ValueError('Archive or delete the task this subagent belongs to.')
    return task, app.store.collection(task)


def _family(app, root):
    """The root task and its subagents. Under app.lock."""
    return [root] + [t for t in app.store.agent_tasks() if t.get('parent_task_id') == root['id']]


def _working(app, family):
    runs = getattr(app.scheduler, '_runs', {})
    return any(t['id'] in runs or (t.get('agent') or {}).get('state') in BUSY for t in family)


def _branches(app, root):
    """The task's published branches as the scheduler recorded them: [(project_id, source_path, name)]."""
    found = []
    agent = root.get('agent') or {}
    for project_id, info in (agent.get('workspaces') or {}).items():
        project = app.state['projects'].get(project_id)
        if isinstance(info, dict) and isinstance(info.get('target_branch'), str) and isinstance(project, dict):
            found.append((project_id, project['source_path'], info['target_branch']))
    return found


def _branch_state(source, name):
    exists = worktree_merge._git(source, ['rev-parse', '--verify', '--quiet', 'refs/heads/' + name + '^{commit}'],
                                 check=False).returncode == 0
    into = worktree_merge._git(source, ['symbolic-ref', '--quiet', '--short', 'HEAD'], check=False).stdout.strip() or None
    ahead = None
    if exists:
        base = ('refs/heads/' + into) if into else 'HEAD'
        counted = worktree_merge._git(source, ['rev-list', '--count', base + '..refs/heads/' + name], check=False)
        ahead = int(counted.stdout.strip()) if counted.returncode == 0 and counted.stdout.strip().isdigit() else None
    return {'name': name, 'exists': exists, 'ahead': ahead, 'into': into,
            'checked_out': exists and worktree_merge._checked_out(source, name)}


def task_archive(app, params):
    """`{task_id, archived}` -> `{archived}`. Archive hides a task from its mode's groups; restore brings it back."""
    archived = params.get('archived')
    if not isinstance(archived, bool):
        raise ValueError('archived must be true or false.')
    with app.lock:
        root, _ = _root_task(app, params.get('task_id'))
        if archived and _working(app, _family(app, root)):
            raise ValueError(WORKING)
        if archived:
            root['archived_at'] = iso_time(time.time())
        else:
            root.pop('archived_at', None)
        app.store.changed(root['id'])
    return {'archived': archived}


def task_delete_check(app, params):
    """`{task_id}` -> what deleting would remove, and the state of the task's branches."""
    with app.lock:
        root, _ = _root_task(app, params.get('task_id'))
        family = _family(app, root)
        working = _working(app, family)
        branches = _branches(app, root)
    out = []
    for project_id, source, name in branches:
        state = worktree_merge._locked(app, project_id, lambda: _branch_state(source, name))
        out.append(dict(state, project_id=project_id))
    return {'working': working, 'subagents': len(family) - 1, 'kind': root.get('kind') or 'project', 'branches': out}


def _remove(folder, root):
    """Remove `folder` if it is a real directory inside `root`; links are removed, never followed."""
    folder, root = Path(folder), Path(root).resolve()
    if folder.is_symlink():
        folder.unlink()
        return
    if folder.is_dir() and root in folder.resolve().parents:
        shutil.rmtree(folder)


def _audit_branch(app, task_id, project_id, name, outcome):
    app.audit.append({
        'v': 1, 'actor': 'user', 'kind': 'action', 'task_id': task_id, 'project_id': project_id,
        'turn_id': None, 'call_id': None,
        'request': {'category': 'command', 'argv': ['git', 'branch', '-D', name], 'project_id': project_id},
        'decision': None, 'rule': None, 'scope_version': None, 'scope_digest': None,
        'outcome': outcome, 'idempotency_key': None, 'detail': {'branch': name, 'reason': 'task deleted'}})


def task_delete(app, params):
    """`{task_id, branches: 'delete'|'keep'}` -> `{deleted, deleted_branches, kept_branches}`. Permanent."""
    choice = params.get('branches', 'keep')
    if choice not in ('delete', 'keep'):
        raise ValueError("branches must be 'delete' or 'keep'.")
    with app.lock:
        root, _ = _root_task(app, params.get('task_id'))
        family = _family(app, root)
        if _working(app, family):
            raise ValueError(WORKING)
        branches = _branches(app, root)
    deleted, kept = [], []
    for project_id, source, name in branches:
        if choice == 'keep':
            kept.append({'name': name, 'reason': 'You chose to keep it.'})
            continue

        def drop(source=source, name=name):
            state = _branch_state(source, name)
            if not state['exists']:
                return None
            if state['checked_out']:
                return 'It is checked out in your working copy.'
            result = worktree_merge._git(source, ['branch', '-D', '--', name], check=False)
            return None if result.returncode == 0 else 'Git could not delete it: ' + worktree_merge._last_line(result.stderr)
        reason = worktree_merge._locked(app, project_id, drop)
        try:
            _audit_branch(app, root['id'], project_id, name, 'failed' if reason else 'succeeded')
        except Exception:
            pass  # The branch is already gone or kept; a failed audit write never undoes the user's choice.
        if reason:
            kept.append({'name': name, 'reason': reason})
        else:
            deleted.append(name)
    ids = [t['id'] for t in family]
    with app.lock:
        if _working(app, _family(app, root)):
            raise ValueError(WORKING)
        for task in _family(app, root):
            app.store.collection(task).pop(task['id'], None)
        for holder in [p for p in app.state['projects'].values() if isinstance(p, dict)] + [app.state.get('research') or {}]:
            if holder.get('selected_task_id') in ids:
                holder['selected_task_id'] = None
        cache = getattr(app.scheduler, '_bibtex', None)
        if isinstance(cache, dict):
            cache.pop(root['id'], None)
        app.store.changed(root['id'])
    seq = getattr(app.events, '_seq', None)
    for task_id in ids:
        if isinstance(seq, dict):
            seq.pop(task_id, None)
        _remove(Path(app.events.root) / task_id, app.storage)
        _remove(app.storage / 'workspaces' / task_id, app.storage)
        _remove(app.storage / 'research-runs' / task_id, app.storage)
    return {'deleted': ids, 'deleted_branches': deleted, 'kept_branches': kept}


METHODS = {'task_archive': task_archive, 'task_delete_check': task_delete_check, 'task_delete': task_delete}
