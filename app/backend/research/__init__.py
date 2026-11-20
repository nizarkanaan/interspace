"""Research sources: the registry and tool dispatch (research/tools.md "Registry and dispatch", "Tools").

`dispatch` authorizes every source call through the run context before making it. A source that is off in
the scope, denied, unable to serve the call or failing is skipped and named in `skipped`; a tool fails as a
whole only for bad arguments. Results are plain JSON, capped at 64 KB (a citation report is capped by the scheduler).
"""
from concurrent.futures import ThreadPoolExecutor
import contextvars
import json
import threading

from . import citations, credentials, records
from .records import parse_id  # noqa: F401  (contract: research.parse_id)

SOURCES = ('semantic_scholar', 'openalex', 'arxiv', 'crossref', 'unpaywall')
TOOLS = ('research_search', 'research_paper', 'research_citations', 'research_fulltext', 'research_bibtex',
         'verify_citations')
RESULT_LIMIT = 64 * 1024
MATCH_SIMILARITY = 0.9         # a Semantic Scholar title match joins a lookup only above this
MAX_WORKERS = 4

_registry_lock = threading.Lock()


# Registry -------------------------------------------------------------------

def sources(app):
    """The `Source` instances in SOURCES order, built once per app from `app.http`, credentials and the cache."""
    with _registry_lock:
        built = getattr(app, '_research_sources', None)
        if built is not None:
            return list(built)
        from . import arxiv, cache, crossref, http, openalex, semantic_scholar, unpaywall
        web = getattr(app, 'http', None)
        if not isinstance(web, http.Http):
            web = http.Http()
            app.http = web
        store = cache.Cache(app.storage / 'research-cache')
        store_of_keys = credentials.for_app(app)   # the one store Settings also uses, so changes drop its cache
        modules = {'semantic_scholar': semantic_scholar, 'openalex': openalex, 'arxiv': arxiv,
                   'crossref': crossref, 'unpaywall': unpaywall}
        built = tuple(modules[name].Source(http=web, credentials=store_of_keys, cache=store) for name in SOURCES)
        app._research_sources = built
        return list(built)


def usage(app):
    """Call counts per source: sent to the network and answered from the cache. Never money."""
    built = sources(app)
    return {'calls': dict(built[0].http.calls), 'cached': dict(built[0].cache.hits)}


def enabled(scope):
    """Source names whose scope setting is `allow` or `ask` (a missing key or source counts as `off`)."""
    research = scope.get('research') if isinstance(scope, dict) else None
    settings = research.get('sources') if isinstance(research, dict) else None
    if not isinstance(settings, dict):
        return []
    return [name for name in SOURCES if settings.get(name) in ('allow', 'ask')]


# Argument validation ----------------------------------------------------------

def _check_keys(arguments, allowed, required):
    if not isinstance(arguments, dict):
        raise ValueError('Tool arguments must be an object.')
    extra = sorted(set(arguments) - set(allowed))
    if extra:
        raise ValueError('Unknown argument: %s.' % extra[0])
    for key in required:
        if arguments.get(key) is None:
            raise ValueError('%s is required.' % key)


def _int(arguments, key, low, high, default=None):
    value = arguments.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError('%s must be a whole number from %d to %d.' % (key, low, high))
    return value


def _text(arguments, key, low, high):
    value = arguments.get(key)
    if not isinstance(value, str) or not low <= len(value.strip()) <= high:
        raise ValueError('%s must be text of %d to %d characters.' % (key, low, high))
    return value.strip()


def _list(arguments, key, low, high):
    value = arguments.get(key)
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise ValueError('%s must be a list of %d to %d items.' % (key, low, high))
    return value


def _identifier(arguments):
    value = arguments.get('id')
    if not isinstance(value, str):
        raise ValueError('id is required.')
    return parse_id(value)


# Authorization and per-source calls ---------------------------------------------

class Skipped(ValueError):
    """A source could not take part in a call. `reason` is `off`, `denied`, `unsupported` or an error code."""

    def __init__(self, source, reason):
        super().__init__('%s was skipped: %s.' % (source, reason))
        self.source = source
        self.reason = reason


def _allowed(decision):
    if decision is True:
        return True
    return isinstance(decision, dict) and decision.get('decision') == 'allow'


class _Gate:
    """Authorizes each source once per tool call (an `ask` is shown once, not per identifier)."""

    def __init__(self, ctx, tool):
        self.ctx = ctx
        self.tool = tool
        scope = getattr(ctx, 'scope', None)
        self.on = set(enabled(scope)) if scope is not None else set(SOURCES)
        self.decisions = {}
        self.lock = threading.Lock()

    def check(self, source):
        """Raise Skipped unless the scope enables `source` and the run context allows this call."""
        if source not in self.on:
            raise Skipped(source, 'off')
        with self.lock:
            if source not in self.decisions:
                request = {'category': 'research', 'source': source, 'tool': self.tool}
                self.decisions[source] = _allowed(self.ctx.authorize(request))
        if not self.decisions[source]:
            raise Skipped(source, 'denied')


def _reason(error):
    if isinstance(error, Skipped):
        return error.reason
    return getattr(error, 'code', None) or 'error'


def _run(gate, source, call):
    """(value, None) or (None, reason): authorize, then call. User-visible errors become a reason code."""
    try:
        gate.check(source.name)
        return call(), None
    except ValueError as error:   # ResearchError, Skipped and credential-store errors; messages never forwarded
        return None, _reason(error)


def _parallel(jobs):
    """Run [(name, fn)] concurrently; returns {name: fn()} in the given order."""
    if len(jobs) <= 1:
        return {name: fn() for name, fn in jobs}
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(jobs))) as pool:
        # Each job runs in a copy of this context, so the call's meter (http.METER) counts its requests.
        futures = [(name, pool.submit(contextvars.copy_context().run, fn)) for name, fn in jobs]
        return {name: future.result() for name, future in futures}


class Lookup:
    """What the citation checker calls (`research.citations.check(references, lookup)`).

    Each method authorizes the source with tool `verify_citations` and raises `Skipped(source, reason)` when
    the source is off, denied, cannot serve the call or fails. Called as `lookup(source, verb, value)`, the
    checker's own interface, it raises `citations.Skipped(reason)` instead.
    """

    def __init__(self, registry, gate):
        self._registry = registry
        self._gate = gate

    def _call(self, source, verb, call):
        if source not in self._registry:
            raise Skipped(source, 'unsupported')
        target = self._registry[source]
        if verb not in target.capabilities:
            raise Skipped(source, 'unsupported')
        value, reason = _run(self._gate, target, lambda: call(target))
        if reason is not None:
            raise Skipped(source, reason)
        return value

    def paper(self, source, identifier):
        """The source's record for a DOI or arXiv ID, or None when it has none."""
        kind = parse_id(identifier)
        if kind[0] not in self._registry.get(source, _NoSource).id_kinds:
            raise Skipped(source, 'unsupported')
        return self._call(source, 'paper', lambda s: s.paper(kind))

    def search(self, source, query, *, limit=5, year_from=None, year_to=None):
        return self._call(source, 'search', lambda s: s.search(query, year_from=year_from, year_to=year_to,
                                                               limit=limit))

    def match(self, source, title):
        """Semantic Scholar's single best title match, or None."""
        return self._call(source, 'search', lambda s: s.match(title) if hasattr(s, 'match') else None)

    def __call__(self, source, verb, value):
        """`citations.check`'s lookup: `paper` by identifier, or `search` by title for the best few records."""
        try:
            if verb == 'paper':
                return self.paper(source, value)
            if verb == 'search':
                return self.search(source, value, limit=citations.SEARCH_LIMIT)
            raise Skipped(source, 'unsupported')
        except ValueError as error:   # Skipped, or an identifier this source cannot take
            raise citations.Skipped(_reason(error)) from None


class _NoSource:
    id_kinds = ()


# Tools ------------------------------------------------------------------------

def _skip(skipped, source, reason):
    skipped.append({'source': source, 'reason': reason})


def _interleave(lists):
    """Rank 0 of every source, then rank 1, ... so each source's best results come first."""
    out = []
    for rank in range(max((len(items) for items in lists), default=0)):
        out.extend(items[rank] for items in lists if rank < len(items))
    return out


def _search(registry, gate, arguments):
    _check_keys(arguments, ('query', 'sources', 'year_from', 'year_to', 'limit'), ('query',))
    query = _text(arguments, 'query', 1, 500)
    year_from = _int(arguments, 'year_from', 1000, 3000)
    year_to = _int(arguments, 'year_to', 1000, 3000)
    if year_from is not None and year_to is not None and year_from > year_to:
        raise ValueError('year_from must not be after year_to.')
    limit = _int(arguments, 'limit', 1, 50, 10)
    requested = arguments.get('sources')
    if requested is None:
        # Every source that can search: one the scope turns off is named in `skipped` (reason `off`), never called.
        names = [name for name in SOURCES if 'search' in registry[name].capabilities]
    else:
        if not isinstance(requested, list) or not requested or any(name not in SOURCES for name in requested):
            raise ValueError('sources must list research sources: %s.' % ', '.join(SOURCES))
        names = [name for name in SOURCES if name in requested]
    skipped, jobs = [], []
    for name in names:
        if 'search' not in registry[name].capabilities:
            _skip(skipped, name, 'unsupported')
            continue
        source = registry[name]
        try:
            gate.check(name)   # asks happen one at a time, before any call runs
        except Skipped as error:
            _skip(skipped, name, error.reason)
            continue
        jobs.append((name, lambda s=source: _run(gate, s, lambda: s.search(query, year_from=year_from,
                                                                            year_to=year_to, limit=limit))))
    found, searched = [], []
    for name, (value, reason) in _parallel(jobs).items():
        if reason is not None:
            _skip(skipped, name, reason)
            continue
        searched.append(name)
        found.append(value or [])
    skipped.sort(key=lambda s: SOURCES.index(s['source']))
    papers = records.merge(_interleave(found))[:limit]
    return _cap({'papers': papers, 'searched': searched, 'skipped': skipped}, 'papers')


def _paper(registry, gate, arguments):
    _check_keys(arguments, ('id',), ('id',))
    kind = _identifier(arguments)
    skipped, jobs = [], []
    for name in SOURCES:
        source = registry[name]
        if 'paper' not in source.capabilities or kind[0] not in source.id_kinds:
            continue
        jobs.append((name, lambda s=source: _run(gate, s, lambda: s.paper(kind))))
    found, missed_s2 = [], False
    for name, (value, reason) in _parallel(jobs).items():
        if reason is not None:
            _skip(skipped, name, reason)
        elif value is not None:
            found.append(value)
        elif name == 'semantic_scholar':
            missed_s2 = True
    merged = records.merge(found)
    paper = merged[0] if merged else None
    if paper is not None and missed_s2 and paper.get('title'):
        # Semantic Scholar misses some DOIs (spike 0B): match by title instead.
        match, _ = _run(gate, registry['semantic_scholar'], lambda: registry['semantic_scholar'].match(paper['title']))
        if match and records.title_similarity(match.get('title'), paper['title']) >= MATCH_SIMILARITY:
            paper = records.merge([paper, match])[0]
    return _cap({'paper': paper, 'sources': list(paper['sources']) if paper else [], 'skipped': skipped}, None)


def _citations(registry, gate, arguments):
    _check_keys(arguments, ('id', 'direction', 'limit'), ('id', 'direction'))
    kind = _identifier(arguments)
    direction = arguments.get('direction')
    if direction not in ('citations', 'references'):
        raise ValueError('direction must be citations or references.')
    limit = _int(arguments, 'limit', 1, 100, 25)
    skipped = []
    for name in ('semantic_scholar', 'openalex'):
        source = registry[name]
        if kind[0] not in source.id_kinds:
            _skip(skipped, name, 'unsupported')
            continue
        value, reason = _run(gate, source, lambda: source.citations(kind, direction, limit))
        if reason is not None:
            _skip(skipped, name, reason)
        elif value:
            return _cap({'papers': value[:limit], 'source': name, 'skipped': skipped}, 'papers')
    return {'papers': [], 'source': None, 'skipped': skipped}


FULLTEXT_ORDER = {'doi': ('unpaywall', 'openalex'), 'arxiv': ('arxiv', 'openalex'), 'openalex': ('openalex',),
                  's2': ()}


def _fulltext(registry, gate, arguments):
    _check_keys(arguments, ('id',), ('id',))
    kind = _identifier(arguments)
    skipped = []
    for name in FULLTEXT_ORDER[kind[0]]:
        source = registry[name]
        value, reason = _run(gate, source, lambda: source.fulltext(kind))
        if reason is not None:
            _skip(skipped, name, reason)
        elif value and value.get('oa_url'):
            return dict(value, source=name, skipped=skipped)
    return {'oa_url': None, 'skipped': skipped}


BIBTEX_SOURCE = {'doi': 'crossref', 'arxiv': 'arxiv'}


def _bibtex(registry, gate, arguments):
    _check_keys(arguments, ('ids',), ('ids',))
    ids = _list(arguments, 'ids', 1, 100)
    entries = []
    for raw in ids:
        entry = {'id': raw if isinstance(raw, str) else None, 'bibtex': None, 'error': None}
        entries.append(entry)
        try:
            kind = parse_id(raw)
        except ValueError:
            entry['error'] = 'invalid_id'
            continue
        name = BIBTEX_SOURCE.get(kind[0])
        if name is None:
            entry['error'] = 'unsupported'
            continue
        source = registry[name]
        value, reason = _run(gate, source, lambda: source.bibtex(kind))
        if reason is not None:
            entry['error'] = reason
        elif value is None:
            entry['error'] = 'not_found'
        else:
            entry['bibtex'] = value
    return _cap({'entries': entries}, 'entries')


def _verify(registry, gate, arguments):
    _check_keys(arguments, ('references',), ('references',))
    references = _list(arguments, 'references', 1, 200)
    if any(not isinstance(reference, dict) for reference in references):
        raise ValueError('Each reference must be an object.')
    # Returned whole: the scheduler keeps the whole report for references.bib and gives the agent a compact,
    # capped copy (scheduler._cap), so references past 64 KB are never lost from the bibliography.
    return citations.check(references, Lookup(registry, gate))


HANDLERS = {'research_search': _search, 'research_paper': _paper, 'research_citations': _citations,
            'research_fulltext': _fulltext, 'research_bibtex': _bibtex, 'verify_citations': _verify}


def _size(result):
    return len(json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def _cap(result, list_key):
    """Shorten `result[list_key]` until the JSON fits RESULT_LIMIT; mark the result `truncated: true`."""
    if list_key is None or _size(result) <= RESULT_LIMIT:
        return result
    result = dict(result, truncated=True)
    items = list(result.get(list_key) or [])
    low, high = 0, len(items)   # the longest prefix that fits
    while low < high:
        middle = (low + high + 1) // 2
        if _size(dict(result, **{list_key: items[:middle]})) <= RESULT_LIMIT:
            low = middle
        else:
            high = middle - 1
    result[list_key] = items[:low]
    return result


def _meter(ctx):
    """`http.METER` for one call: requests sent go to `ctx.note_call(source)`, cache answers to `ctx.note_cached`."""
    targets = {'calls': getattr(ctx, 'note_call', None), 'cached': getattr(ctx, 'note_cached', None)}

    def meter(kind, source):
        target = targets.get(kind)
        if callable(target):
            target(source)
    return meter


def dispatch(app, ctx, name, arguments):
    """Run one research tool call. `ctx.authorize(request)` decides each source call before it is made; each
    request sent and each cache answer is reported to `ctx.note_call(source)` / `ctx.note_cached(source)`."""
    if name not in HANDLERS:
        raise ValueError('Unknown research tool.')
    registry = {source.name: source for source in sources(app)}
    from . import http
    token = http.METER.set(_meter(ctx))
    try:
        return HANDLERS[name](registry, _Gate(ctx, name), arguments)
    finally:
        http.METER.reset(token)
