"""Settings → Research sources (docs/superpowers/specs/research/credentials.md).

`service.extension_methods` registers METHODS; each handler is `(app, params)` and runs on the request pool.
Source facts and status come from stream 1B's `research.sources(app)`. Until that exists, a small fallback table
with the spike-0B facts stands in. A key or email goes in through `research_credential_set` and never comes back:
rows carry only `configured`, and errors carry fixed text.
"""
import importlib

from research import credentials

SOURCE_NAMES = ('semantic_scholar', 'openalex', 'arxiv', 'crossref', 'unpaywall')
UNAVAILABLE = 'credential_store_unavailable'
MAX_DETAIL = 300


class _FallbackSource:
    """The facts of one source before the 1B clients exist. Its status makes no network call."""

    def __init__(self, app, name, title, credential, kind, required, capabilities, help_url, missing):
        self.app = app
        self.name, self.title, self.credential, self.credential_kind = name, title, credential, kind
        self.required, self.capabilities, self.help_url = required, capabilities, help_url
        self.missing = missing

    def status(self, test=False):
        configured = bool(self.credential) and credentials.for_app(self.app).configured(self.credential)
        if configured:
            state, detail = 'ready', ('Email saved.' if self.credential_kind == 'email' else 'Key saved.')
        else:
            state, detail = ('needs_key' if self.required else 'ready'), self.missing
        return {'source': self.name, 'configured': configured, 'required': self.required, 'state': state,
                'detail': detail}


_FALLBACK = (
    ('semantic_scholar', 'Semantic Scholar', 'semantic_scholar', 'api_key', False,
     ('search', 'paper', 'citations', 'bibtex'), 'https://www.semanticscholar.org/product/api',
     'Works without a key, but the shared pool is often busy. A free key gives steadier access.'),
    ('openalex', 'OpenAlex', 'openalex', 'api_key', False,
     ('search', 'paper', 'citations', 'retraction'), 'https://openalex.org/settings/api',
     'Works without a key on a small shared allowance. A free key raises it.'),
    ('arxiv', 'arXiv', None, None, False,
     ('search', 'paper', 'fulltext', 'bibtex'), 'https://info.arxiv.org/help/api/index.html',
     'No key needed.'),
    ('crossref', 'Crossref', 'crossref_email', 'email', False,
     ('search', 'paper', 'bibtex', 'retraction'), 'https://www.crossref.org/documentation/retrieve-metadata/rest-api/',
     'Works without an email. Adding yours uses Crossref\'s faster polite pool.'),
    ('unpaywall', 'Unpaywall', 'unpaywall_email', 'email', True,
     ('fulltext',), 'https://unpaywall.org/products/api',
     'Unpaywall needs your email address as its contact.'),
)


def _research_module(attribute):
    return getattr(importlib.import_module('research'), attribute, None)


def _sources(app):
    build = _research_module('sources')
    if build is not None:
        return list(build(app))
    return [_FallbackSource(app, *facts) for facts in _FALLBACK]


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
            if isinstance(name, str) and isinstance(count, int) and not isinstance(count, bool) and count >= 0}


def research_usage(app, params):
    """Call counts per source, never money. From 1B's `research.usage(app, task_id)` once it exists."""
    task_id = params.get('task_id')
    if task_id is not None and not isinstance(task_id, str):
        raise ValueError('Unknown task.')
    usage = _research_module('usage')
    if usage is None:
        zeros = {name: 0 for name in SOURCE_NAMES}
        return {'calls': dict(zeros), 'cached': dict(zeros)}
    result = usage(app, task_id)
    result = result if isinstance(result, dict) else {}
    return {'calls': _counts(result.get('calls')), 'cached': _counts(result.get('cached'))}


METHODS = {
    'research_sources': research_sources,
    'research_credential_set': research_credential_set,
    'research_credential_delete': research_credential_delete,
    'research_test': research_test,
    'research_usage': research_usage,
}
