"""Agent runtimes for agentic tasks (scheduler.md, "Runtime adapter API").

`make_factory(app)` returns the `runtime_factory(task_id) -> Runtime` that `scheduler.Scheduler` takes. The
runtime is chosen by the task row's `provider` field: `codex` (the default) or `claude`. The Claude runtime is
built by stream 2B in `runtime/claude.py` and imported only when a task asks for it.
"""
import importlib


class RuntimeFailure(ValueError):
    """A runtime failure with a code from events.md and one sentence that is safe to show."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


PROVIDERS = ('codex', 'claude')


def _task_provider(app, task_id):
    with app.lock:
        task = app.store.task(task_id)
        provider = task.get('provider') if isinstance(task, dict) else None
    if provider is None:
        return 'codex'
    if provider not in PROVIDERS:
        raise ValueError('This task names an unknown agent provider.')
    return provider


def _claude(app):
    try:
        module = importlib.import_module(__name__ + '.claude')
    except ImportError:
        raise ValueError('The Claude Code runtime is not in this build yet.') from None
    runtime_class = getattr(module, 'ClaudeRuntime', None)
    if runtime_class is None:
        raise ValueError('The Claude Code runtime is not in this build yet.')
    return runtime_class(app)


def make_factory(app):
    """The scheduler's runtime factory. One runtime object per provider is shared by every task."""
    made = {}

    def factory(task_id):
        provider = _task_provider(app, task_id)
        if provider not in made:
            if provider == 'codex':
                from . import codex
                made[provider] = codex.CodexRuntime(app)
            else:
                made[provider] = _claude(app)
        return made[provider]
    return factory

