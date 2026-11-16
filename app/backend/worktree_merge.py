"""Review and merge of a task's published branch (docs/superpowers/specs/multi-provider/merge.md).

A merge runs in a temporary worktree of the target branch. The user's checkout and working files are never
touched, nothing is forced, reset, rebased or deleted, and a conflicted merge is aborted and reported.
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import scheduler

MAX_PATCH_BYTES = 256 * 1024
MAX_TITLE_CHARS = 160
COMMIT = re.compile(r'^[0-9a-f]{40}([0-9a-f]{24})?$')
CHANGES = {'A': 'add', 'M': 'modify', 'D': 'delete', 'R': 'rename', 'C': 'copy', 'T': 'modify'}
OUTCOMES = {'merged': 'succeeded', 'conflict': 'failed', 'stale': 'failed', 'dirty': 'failed', 'error': 'failed'}


def _git(repo, args, check=True):
    # User hooks and external diff or textconv programs never run: these calls must not execute repository code.
    command = ['git', '-c', 'core.hooksPath=/dev/null', '-C', str(repo)] + list(args)
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace',
                            timeout=scheduler.GIT_TIMEOUT_S, env=scheduler._git_env(), stdin=subprocess.DEVNULL)
    if check and result.returncode:
        raise ValueError('Git failed: ' + _last_line(result.stderr))
    return result


def _last_line(text):
    lines = [line.strip() for line in (text or '').splitlines() if line.strip()]
    return lines[-1][:300] if lines else 'no detail.'


def _branch_head(repo, name, what):
    if not isinstance(name, str) or not name or name.startswith('-') or \
            _git(repo, ['check-ref-format', 'refs/heads/' + name], check=False).returncode:
        raise ValueError('The %s branch name is not valid.' % what)
    found = _git(repo, ['rev-parse', '--verify', '--quiet', 'refs/heads/' + name + '^{commit}'], check=False)
    if found.returncode:
        raise ValueError('The %s branch %s does not exist.' % (what, name))
    return found.stdout.strip()


def _checked_out(repo, branch):
    """True when `branch` is checked out in the user's repository or any of its worktrees."""
    listing = _git(repo, ['worktree', 'list', '--porcelain']).stdout
    return ('branch refs/heads/' + branch) in listing.splitlines()


# ------------------------------------------------------------------------------------------- summary

def summary(repo_path, branch, base_commit):
    head = _branch_head(repo_path, branch, 'task')
    if not isinstance(base_commit, str) or not COMMIT.match(base_commit) or \
            _git(repo_path, ['cat-file', '-e', base_commit + '^{commit}'], check=False).returncode:
        raise ValueError('The task base commit is not in this repository.')
    common = ['diff', '--no-color', '--no-ext-diff', '--no-textconv', '-M', base_commit, head]
    names = _git(repo_path, common[:1] + ['--name-status', '-z'] + common[1:]).stdout.split('\0')
    counts = _git(repo_path, common[:1] + ['--numstat', '-z'] + common[1:]).stdout.split('\0')
    files = []
    i = 0
    while i < len(names) and names[i]:
        status = names[i]
        letter = status[:1]
        if letter in 'RC':
            old, path = names[i + 1], names[i + 2]
            i += 3
        else:
            old, path = None, names[i + 1]
            i += 2
        files.append({'path': path, 'change': CHANGES.get(letter, 'modify'), 'old_path': old,
                      'additions': None, 'deletions': None, 'binary': False})
    stats = []
    i = 0
    while i < len(counts) and counts[i]:
        added, deleted, rest = counts[i].split('\t', 2)
        if rest == '':  # A rename or copy: the old and new paths follow as their own fields.
            i += 3
        else:
            i += 1
        stats.append((added, deleted))
    for entry, (added, deleted) in zip(files, stats):
        if added == '-':
            entry['binary'] = True
        else:
            entry['additions'], entry['deletions'] = int(added), int(deleted)
    patch = _git(repo_path, common).stdout.encode('utf-8')
    truncated = len(patch) > MAX_PATCH_BYTES
    return {'branch': branch, 'base_commit': base_commit, 'head_commit': head, 'files': files,
            'patch': patch[:MAX_PATCH_BYTES].decode('utf-8', 'ignore'), 'truncated': truncated}


# --------------------------------------------------------------------------------------------- merge

def _message(title):
    words = ' '.join(str(title or '').split())[:MAX_TITLE_CHARS]
    return 'Merge interspace task ' + (words or 'changes')  # One line, so git never reads a trailer from it.


def _result(status, detail, merge_commit=None, conflicts=()):
    return {'status': status, 'merge_commit': merge_commit, 'conflicts': list(conflicts), 'detail': detail}


def merge(repo_path, branch, into, *, expected_head, title=None):
    head = _branch_head(repo_path, branch, 'task')
    before = _branch_head(repo_path, into, 'target')
    if not isinstance(expected_head, str) or head != expected_head:
        return _result('stale', 'The task branch changed since you reviewed it. Review the new changes first.')
    if _checked_out(repo_path, into):
        return _result('dirty', '%s is checked out in your working copy, so Interspace leaves it alone. '
                                'Merge it yourself there, or pick another branch.' % into)
    folder = Path(tempfile.mkdtemp(prefix='interspace-merge-'))
    work = folder / 'worktree'
    added = False
    try:
        _git(repo_path, ['worktree', 'add', '--quiet', str(work), into])
        added = True
        done = _git(work, ['merge', '--no-ff', '--no-edit', '--no-log', '--no-signoff', '-m', _message(title), branch],
                    check=False)
        if done.returncode == 0:
            after = _git(work, ['rev-parse', 'HEAD']).stdout.strip()
            if after == before:
                return _result('merged', '%s already contains these changes.' % into)
            return _result('merged', 'Merged into %s.' % into, merge_commit=after)
        conflicts = [p for p in _git(work, ['diff', '--name-only', '--diff-filter=U', '-z']).stdout.split('\0') if p]
        _git(work, ['merge', '--abort'], check=False)
        if conflicts:
            return _result('conflict', 'The merge into %s conflicts, so nothing was changed.' % into,
                           conflicts=sorted(conflicts))
        raise ValueError('Git could not merge: ' + _last_line(done.stderr or done.stdout))
    finally:
        # The temporary worktree always goes, also on failure. No --force: an aborted merge leaves it clean,
        # and anything left over is deleted and pruned.
        if added:
            _git(repo_path, ['worktree', 'remove', str(work)], check=False)
        shutil.rmtree(str(folder), ignore_errors=True)
        _git(repo_path, ['worktree', 'prune'], check=False)


# ----------------------------------------------------------------------------------- backend methods

def _text(params, name):
    value = params.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError('Missing %s.' % name)
    return value


def _task_branch(app, params):
    """The task's published branch as the scheduler recorded it: agent.workspaces[project].target_branch."""
    task_id = _text(params, 'task_id')
    with app.lock:
        for project_id, project in app.state['projects'].items():
            saved = project.get('tasks') if isinstance(project, dict) else None
            task = saved.get(task_id) if isinstance(saved, dict) else None
            if isinstance(task, dict):
                break
        else:
            raise ValueError('Unknown task.')
        agent = task.get('agent') if task.get('mode') == 'agent' else None
        if not isinstance(agent, dict):
            raise ValueError('This task has no changes to review.')
        wanted = params.get('project_id') or agent.get('project_id')
        info = (agent.get('workspaces') or {}).get(wanted)
        owner = app.state['projects'].get(wanted)
        if not isinstance(info, dict) or not info.get('target_branch') or not isinstance(owner, dict):
            raise ValueError('This task has not published a branch yet.')
        return {'task_id': task_id, 'project_id': wanted, 'title': task.get('title'),
                'source_path': owner['source_path'], 'branch': info['target_branch'],
                'base_commit': info.get('base_commit')}


def _locked(app, project_id, action):
    key = 'project:' + project_id
    app.locks.acquire(key, None, None)
    try:
        return action()
    finally:
        app.locks.release(key, None)


def review_summary(app, params):
    task = _task_branch(app, params)
    return _locked(app, task['project_id'], lambda: summary(task['source_path'], task['branch'], task['base_commit']))


def review_branches(app, params):
    project_id = _text(params, 'project_id')
    with app.lock:
        project = app.state['projects'].get(project_id)
        if not isinstance(project, dict):
            raise ValueError('Unknown project.')
        source = project['source_path']

    def read():
        names = _git(source, ['for-each-ref', '--format=%(refname:short)', 'refs/heads/']).stdout.splitlines()
        current = _git(source, ['symbolic-ref', '--quiet', '--short', 'HEAD'], check=False).stdout.strip() or None
        return {'branches': [n for n in names if n], 'current': current}
    return _locked(app, project_id, read)


def review_merge(app, params):
    task = _task_branch(app, params)
    into, expected = _text(params, 'into'), _text(params, 'expected_head')

    def run():
        try:
            result = merge(task['source_path'], task['branch'], into, expected_head=expected, title=task['title'])
        except ValueError as error:
            _audit(app, task, into, 'error', None)
            raise error
        try:
            _audit(app, task, into, result['status'], result['merge_commit'])
        except Exception:
            result['detail'] += ' The audit log could not be written.'
        return result
    return _locked(app, task['project_id'], run)


def _audit(app, task, into, status, merge_commit):
    app.audit.append({
        'v': 1, 'actor': 'user', 'kind': 'action', 'task_id': task['task_id'], 'project_id': task['project_id'],
        'turn_id': None, 'call_id': None,
        'request': {'category': 'command', 'argv': ['git', 'merge', '--no-ff', '--no-edit', task['branch']],
                    'project_id': task['project_id']},
        'decision': None, 'rule': None, 'scope_version': None, 'scope_digest': None,
        'outcome': OUTCOMES[status], 'idempotency_key': None,
        'detail': {'branch': task['branch'], 'into': into, 'result': status, 'merge_commit': merge_commit}})


METHODS = {'review_summary': review_summary, 'review_merge': review_merge, 'review_branches': review_branches}
