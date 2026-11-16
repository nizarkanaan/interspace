"""Agent runtimes for agentic tasks (scheduler.md, "Runtime adapter API").

`make_factory(app)` returns the `runtime_factory(task_id) -> Runtime` that `scheduler.Scheduler` takes. The
runtime is chosen by the task row's `provider` field, looked up in the provider registry (`runtime/registry.py`).
A runtime module is imported only when a task asks for its provider.
"""
from . import registry

# Task rows saved before providers existed have no `provider` field; they were all Codex tasks.
LEGACY_PROVIDER = 'codex'


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
