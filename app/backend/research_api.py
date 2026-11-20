"""Settings → Research sources (docs/superpowers/specs/research/credentials.md).

`service.extension_methods` registers METHODS; each handler is `(app, params)` and runs on the request pool.
Source facts and status come from `research.sources(app)`. A key or email goes in through `research_credential_set`
and never comes back: rows carry only `configured`, and errors carry fixed text.
"""
import copy

import research
from research import credentials

SOURCE_NAMES = research.SOURCES
UNAVAILABLE = 'credential_store_unavailable'
MAX_DETAIL = 300


def _sources(app):
    return list(research.sources(app))


def _source(app, params):
    name = params.get('source')
    for source in _sources(app):
        if source.name == name:
            return source
    raise ValueError('Unknown research source.')


def _row(app, source, test=False):
    row = {'source': source.name, 'title': source.title, 'credential_kind': source.credential_kind,
           'required': bool(source.required), 'configured': False, 'state': 'error', 'detail': '',
           'help_url': source.help_url if str(source.help_url).startswith('https://') else None,
           'capabilities': list(source.capabilities)}
    try:
        status = source.status(test=test)
    except credentials.CredentialStoreUnavailable as error:
        return dict(row, state=UNAVAILABLE, detail=str(error))
    except Exception:
        # Never pass a client's own error text on: it may hold upstream text or, by mistake, a key.
        return dict(row, detail=source.title + ' could not report its status.')
    if not isinstance(status, dict):
        return dict(row, detail=source.title + ' could not report its status.')
    detail = status.get('detail')
    return dict(row, configured=status.get('configured') is True, state=str(status.get('state') or 'error'),
                detail=detail[:MAX_DETAIL] if isinstance(detail, str) else '')


def _credential_source(app, params):
    source = _source(app, params)
    if not source.credential:
        raise ValueError(source.title + ' needs no key or email.')
    return source


def research_sources(app, params):
    return {'sources': [_row(app, source) for source in _sources(app)]}


def research_credential_set(app, params):
    source = _credential_source(app, params)
    credentials.for_app(app).set(source.credential, params.get('value'))
    return _row(app, source)


def research_credential_delete(app, params):
    source = _credential_source(app, params)
    credentials.for_app(app).delete(source.credential)
    return _row(app, source)


def research_test(app, params):
    return _row(app, _source(app, params), test=True)


def _counts(table):
    if not isinstance(table, dict):
        return {}
    return {name: count for name, count in table.items()
            if name in SOURCE_NAMES and isinstance(count, int) and not isinstance(count, bool) and count >= 0}


def _task_usage(app, task_id):
    """The counts the scheduler keeps on a task's root (research/tasks.md `research_usage` event)."""
    with app.lock:
        task = app.store.task(task_id)
        parent_id = task.get('parent_task_id')
        root = app.store.task(parent_id) if parent_id else task
        agent = root.get('agent') if isinstance(root.get('agent'), dict) else {}
        return copy.deepcopy(agent.get('research_usage') or {})


def research_usage(app, params):
    """Call counts per source, never money: one task's (`task_id`), else this app run's from `research.usage`."""
    task_id = params.get('task_id')
    if task_id is not None and not isinstance(task_id, str):
        raise ValueError('Unknown task.')
    result = research.usage(app) if task_id is None else _task_usage(app, task_id)
    result = result if isinstance(result, dict) else {}
    zeros = {name: 0 for name in SOURCE_NAMES}
    return {'calls': dict(zeros, **_counts(result.get('calls'))), 'cached': dict(zeros, **_counts(result.get('cached')))}


METHODS = {
    'research_sources': research_sources,
    'research_credential_set': research_credential_set,
    'research_credential_delete': research_credential_delete,
    'research_test': research_test,
    'research_usage': research_usage,
}
