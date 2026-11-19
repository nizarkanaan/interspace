# Review and merge

Owner: 1D (`app/backend/worktree_merge.py`, `app/ui/review.js`). Status: implemented (Wave 1D); exercised end to end in Wave 2A. Conventions: [README.md](README.md).

The scheduler already publishes each task's clone into the user's repository as the branch `interspace/task-<id8>` (or `-2`, `-3` and so on when that name is taken). This happens after every turn, and the branch name is recorded as `target_branch`. Since Wave 2A a `write` run's changes are first committed in its clone, so the branch carries them (orchestration.md, "Changes"). Merging into the user's branches is new.

## API (`worktree_merge.py`)

```python
def summary(repo_path, branch, base_commit) -> dict
# {'branch', 'base_commit', 'head_commit', 'files': [{'path', 'change', 'old_path', 'additions', 'deletions', 'binary'}],
#  'patch': str (<= 256 KB), 'truncated': bool}

def merge(repo_path, branch, into, *, expected_head) -> dict
# {'status': 'merged'|'conflict'|'stale'|'dirty', 'merge_commit': str|None, 'conflicts': [paths], 'detail': str}
```

Merge rules:
- The merge runs in a **temporary worktree** of `into`, never in the user's checkout. The command is `git merge --no-ff --no-edit <branch>`.
- **Success.** `into` advances, and the user's checked-out files are never touched. If `into` is the currently checked-out branch, the result is `dirty` and nothing happens; the user can merge it themselves.
- **Conflict.** The merge is aborted and the conflicting paths are reported. Nothing is ever forced.
- **Stale.** `expected_head` is the head the user reviewed. If the branch moved since, the result is `stale`.
- **Never** `--force`, reset, rebase or deleting a branch.
- The commit message is `Merge interspace task <title>`, with no co-author trailers.
- Every merge is audited: task, branch, `into`, result and merge commit.

## Backend methods

| Method | Params | Result |
| --- | --- | --- |
| `review_summary` | `{task_id}` | `summary(…)` for the task's published branch |
| `review_merge` | `{task_id, into, expected_head}` | `merge(…)` result |
| `review_branches` | `{project_id}` | `{'branches': [names], 'current': name}` (local branches only) |

All three take the project lock.

## UI

**Review changes** opens from:
- a child's card;
- the parent's `subagent_finished` row;
- an agent task header.

The view shows:
- a file list with additions and deletions;
- the unified diff, rendered as text-safe content;
- an **Into** picker, defaulting to the project's current branch and listing its other local branches;
- a **Merge** button.

The result appears inline: merged with its commit, conflicts with their paths, stale, or dirty with its explanation.
