"""Agent runtimes for agentic tasks (scheduler.md, "Runtime adapter API").

`make_factory(app)` returns the `runtime_factory(task_id) -> Runtime` that `scheduler.Scheduler` takes. The
runtime is chosen by the task row's `provider` field, looked up in the provider registry (`runtime/registry.py`).
A runtime module is imported only when a task asks for its provider.
"""
import os
from pathlib import Path

from . import registry

# Task rows saved before providers existed have no `provider` field; they were all Codex tasks.
LEGACY_PROVIDER = 'codex'

# Home-relative locations whose contents a sandboxed command must not read (scope.md always_deny.credentials).
CREDENTIAL_PATHS = ('.ssh', '.gnupg', '.aws', '.azure', '.codex', '.claude', '.docker', '.kube', '.netrc',
                    '.npmrc', '.pypirc', '.git-credentials', '.config/gh', '.config/gcloud', '.config/git/credentials',
                    'Library/Keychains', 'Library/Cookies')


# macOS limits a Unix socket path to 104 bytes; the bridge adds "/isb-XXXXXXXX/s" to the run folder.
MAX_RUN_DIR_CHARS = 104 - len('/isb-XXXXXXXX/s') - 1


def run_dir(app_data):
    """`<app data>/run` (mode 0700) for the MCP bridge's socket and the Claude CLI's MCP configuration, or None.

    The folder is part of Interspace's data, which `deny_paths` keeps away from sandboxed commands; the shared
    temporary folder is readable by every command. None (no app data, or a path too long for a socket) means the
    caller falls back to the temporary folder.
    """
    if app_data is None:
        return None
    path = os.path.join(os.path.realpath(str(app_data)), 'run')
    if len(path.encode('utf-8')) > MAX_RUN_DIR_CHARS:
        return None
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def own_folders(ctx):
    """The folders a session may read: its task workspaces, or the scratch run folder of a task without a project
    (research/tasks.md). `deny_paths` keeps these readable."""
    found = list(getattr(ctx, 'workspaces', {}).values())
    scratch = getattr(ctx, 'scratch', None)
    if isinstance(scratch, str) and scratch and scratch not in found:
        found.append(scratch)
    return found


def research_only(ctx):
    """Whether the session belongs to a task without a project: no files, no commands, research tools only."""
    return getattr(ctx, 'research_only', False) is True


def _within(path, root):
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def deny_paths(workspaces, *, home, app_data=None, credential_paths=CREDENTIAL_PATHS, extra=()):
    """Paths a task's sandboxed commands must not read (scope.md, known limit 0B-8).

    Credential locations under `home`, `extra` paths, and all of Interspace's data (`app_data`) except the task's
    own workspaces and the folders that lead to them: other tasks' clones, events, audit, state, the Codex home.
    Folders are listed when the session starts. Nothing returned contains or equals one of `workspaces`.
    """
    found = [str(Path(home) / p) for p in credential_paths] + [str(p) for p in extra]
    own = [os.path.realpath(p) for p in workspaces]
    if app_data is not None and os.path.isdir(str(app_data)):
        ancestors = set()
        for path in own:
            ancestors.update(str(parent) for parent in Path(path).parents)
        stack = [os.path.realpath(str(app_data))]
        while stack:
            directory = stack.pop()
            for name in sorted(os.listdir(directory)):
                child = os.path.realpath(os.path.join(directory, name))
                if child in own:
                    continue
                if child in ancestors and os.path.isdir(child):
                    stack.append(child)
                else:
                    found.append(child)
    return [p for p in dict.fromkeys(found) if not any(_within(own_path, p) for own_path in own)]


class RuntimeFailure(ValueError):
    """A runtime failure with a code from events.md and one sentence that is safe to show."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _task_provider(app, task_id):
    with app.lock:
        task = app.store.task(task_id)
        provider = task.get('provider') if isinstance(task, dict) else None
    if provider is None:
        return LEGACY_PROVIDER
    if provider not in registry.names():
        raise ValueError('This task names an unknown agent provider.')
    return provider


def make_factory(app):
    """The scheduler's runtime factory. One runtime object per provider is shared by every task."""
    made = {}

    def factory(task_id):
        provider = _task_provider(app, task_id)
        if provider not in made:
            made[provider] = registry.runtime_class(provider)(app)
        return made[provider]
    return factory
