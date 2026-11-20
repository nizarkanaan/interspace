"""A research task's corpus: every paper its agents found, merged, with citation verdicts
(docs/superpowers/specs/2026-11-20-task-corpus-design.md).

Pure functions over a JSON-safe dict; the scheduler owns the file and its lock. A verdict says something about a
reference as it was cited, so only `verified` and `retracted` rows attach to a paper (the checker confirmed which paper
it is). `mismatch`, `not_found` and `unchecked` rows go to `unverified`, keeping a mismatch's record only as `closest`.
The Orchestrator's check beats a member's; within one owner the latest wins; a confirmed verdict is never downgraded.
"""
import json

from research import records

V = 1
MAX_PAPERS = 2000
MAX_UNVERIFIED = 500
MAX_FOUND = 20
CONFIRMED = ('verified', 'retracted')
OPEN = ('mismatch', 'not_found', 'unchecked')
ORCHESTRATOR = 'orchestrator'
MEMBER = 'member'
PAPER_TOOLS = ('research_search', 'research_citations', 'research_paper')
INPUT_KEYS = ('title', 'authors', 'year', 'doi', 'arxiv_id', 'raw')
TEXT = 500


def empty():
    return {'v': V, 'updated_at': None, 'full': False, 'papers': [], 'unverified': []}


def load(value):
    """A corpus read from disk, or None when it is not one (the caller rebuilds)."""
    if not isinstance(value, dict) or value.get('v') != V:
        return None
    if not isinstance(value.get('papers'), list) or not isinstance(value.get('unverified'), list):
        return None
    return value


def _text(value, limit=TEXT):
    return records.clean_text(value, limit) if isinstance(value, str) else None


def _record(value, source=None):
    """A normalized paper record from a source record or a checker match; None without a title, DOI or arXiv ID."""
    if not isinstance(value, dict):
        return None
    sources = [s for s in value.get('sources') or [] if isinstance(s, str)] or ([source] if source else [])
    record = records.make(sources[0] if sources else 'unknown', title=value.get('title'),
                          authors=[a for a in value.get('authors') or [] if isinstance(a, str)],
                          year=value.get('year'), venue=value.get('venue'), doi=value.get('doi'),
                          arxiv_id=value.get('arxiv_id'), s2_id=value.get('s2_id'),
                          openalex_id=value.get('openalex_id'), abstract=value.get('abstract'),
                          citation_count=value.get('citation_count'), url=value.get('url'),
                          oa_url=value.get('oa_url'), retracted=value.get('retracted'))
    record['sources'] = sources or []
    if not (record['title'] or record['doi'] or record['arxiv_id']):
        return None
    return record


def _found(found):
    return {'tool': _text(found.get('tool'), 64), 'query': _text(found.get('query')),
            'member': _text(found.get('member'), 64), 'at': _text(found.get('at'), 40)}


def _same_found(a, b):
    return all(a.get(k) == b.get(k) for k in ('tool', 'query', 'member'))


def _ref_key(given):
    """One reference as cited: its DOI, else its arXiv ID, else its normalized title (or raw line)."""
    if not isinstance(given, dict):
        return None
    doi = records.normalize_doi(given.get('doi')) if isinstance(given.get('doi'), str) else None
    if doi:
        return 'doi:' + doi
    arxiv = records.normalize_arxiv(given['arxiv_id']) if isinstance(given.get('arxiv_id'), str) else None
    if arxiv:
        return 'arxiv:' + arxiv
    title = records.normalize_title(given.get('title') or given.get('raw') or '')
    return 'title:' + title if title else None


def _input(given):
    shown = {}
    for key in INPUT_KEYS:
        value = given.get(key) if isinstance(given, dict) else None
        if key == 'authors':
            if isinstance(value, list):
                shown[key] = [_text(a, 200) for a in value[:50] if isinstance(a, str)]
        elif key == 'year':
            if type(value) is int:
                shown[key] = value
        elif isinstance(value, str) and value.strip():
            shown[key] = _text(value, 1000)
    return shown


def _wins(old_by, new_by):
    """Whether a check by `new_by` may replace one by `old_by`."""
    return not (old_by == ORCHESTRATOR and new_by == MEMBER)


def _add_one(corpus, record, found):
    """Merge one record; the paper entry, or None when it is new and the corpus is full."""
    for entry in corpus['papers']:
        if records.same_paper(entry['paper'], record):
            entry['paper'] = records.merge([entry['paper'], record])[0]
            break
    else:
        if len(corpus['papers']) >= MAX_PAPERS:
            corpus['full'] = True
            return None
        entry = {'paper': record, 'found': [], 'check': None}
        corpus['papers'].append(entry)
    if found and not any(_same_found(found, f) for f in entry['found']) and len(entry['found']) < MAX_FOUND:
        entry['found'].append(found)
    return entry


def add_papers(corpus, papers, found):
    """Papers from one research call. `found` is `{tool, query, member, at}`. Returns whether anything changed."""
    before = json.dumps(corpus, sort_keys=True)
    found = _found(found or {})
    for value in papers if isinstance(papers, list) else []:
        record = _record(value)
        if record is not None:
            _add_one(corpus, record, found)
    return json.dumps(corpus, sort_keys=True) != before


def add_report(corpus, rows, by, member, at):
    """The rows of one citation report, checked by `by` ('orchestrator' or 'member'). Returns whether it changed."""
    before = json.dumps(corpus, sort_keys=True)
    by = ORCHESTRATOR if by == ORCHESTRATOR else MEMBER
    found = _found({'tool': 'verify_citations', 'query': None, 'member': member, 'at': at})
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        status, given = row.get('status'), row.get('input')
        key = _ref_key(given)
        if status in CONFIRMED:
            record = _record(row.get('match'), _text(row.get('source'), 64))
            if record is None:
                continue
            entry = _add_one(corpus, record, found)
            if entry is None:
                continue
            check = entry.get('check')
            if check is None or _wins(check.get('by'), by):
                refs = list(check.get('refs') or []) if check else []
                entry['check'] = {'status': status, 'by': by, 'at': _text(at, 40), 'refs': refs}
            if key and key not in entry['check']['refs']:
                entry['check']['refs'].append(key)
            if key:
                corpus['unverified'] = [u for u in corpus['unverified'] if u.get('key') != key]
        elif status in OPEN and key:
            if any(key in ((p.get('check') or {}).get('refs') or []) for p in corpus['papers']):
                continue  # Already confirmed: never downgraded.
            old = next((u for u in corpus['unverified'] if u.get('key') == key), None)
            if old is not None and not _wins(old.get('by'), by):
                continue
            closest = _record(row.get('match'), _text(row.get('source'), 64)) if status == 'mismatch' else None
            item = {'key': key, 'reference': _input(given), 'status': status,
                    'fields': [f for f in row.get('fields') or [] if isinstance(f, str)][:8],
                    'reason': _text(row.get('reason')), 'closest': closest, 'by': by, 'at': _text(at, 40)}
            if old is not None:
                corpus['unverified'][corpus['unverified'].index(old)] = item
            elif len(corpus['unverified']) < MAX_UNVERIFIED:
                corpus['unverified'].append(item)
            else:
                corpus['full'] = True
    return json.dumps(corpus, sort_keys=True) != before


def add_result(corpus, tool, result, found):
    """A parsed research tool result. Paper tools add papers; the rest are ignored here."""
    if tool not in PAPER_TOOLS or not isinstance(result, dict):
        return False
    if tool == 'research_paper':
        return add_papers(corpus, [result.get('paper')] if result.get('paper') else [], found)
    return add_papers(corpus, result.get('papers'), found)


def rebuild(task_events, skip=()):
    """A corpus from saved events. `task_events` is `[(member, events)]`, the root task first with member
    'Orchestrator'. Returns `(corpus, incomplete)`: how many research results could not be read. Calls in `skip`
    are left out (the live call that triggered the rebuild adds its whole result itself)."""
    corpus, incomplete = empty(), 0
    timeline = []
    for order, (member, events) in enumerate(task_events):
        for event in events or []:
            if isinstance(event, dict):
                timeline.append((str(event.get('at') or ''), order, event.get('seq') or 0, member, event))
    timeline.sort(key=lambda item: item[:3])
    calls = {}
    for _, order, _, member, event in timeline:
        kind, data = event.get('kind'), event.get('data')
        if not isinstance(data, dict):
            continue
        if kind == 'tool_call' and data.get('category') == 'research':
            shown = data.get('input') if isinstance(data.get('input'), dict) else {}
            calls[data.get('call_id')] = (data.get('tool'), shown.get('query') or shown.get('id'))
        elif kind == 'tool_result' and data.get('call_id') in calls and data.get('status') == 'ok' \
                and data.get('call_id') not in skip:
            tool, query = calls[data['call_id']]
            if tool not in PAPER_TOOLS:
                continue
            output = data.get('output') if isinstance(data.get('output'), dict) else {}
            try:
                if output.get('truncated'):
                    raise ValueError('truncated')
                parsed = json.loads(output.get('text') or '')
            except ValueError:
                incomplete += 1
                continue
            add_result(corpus, tool, parsed, {'tool': tool, 'query': query, 'member': member, 'at': event.get('at')})
        elif kind == 'citation_report' and str(event.get('item_id') or '')[5:] not in skip:
            if data.get('truncated'):
                incomplete += 1
            by = ORCHESTRATOR if order == 0 else MEMBER
            add_report(corpus, data.get('references'), by, member, event.get('at'))
    return corpus, incomplete


def counts(corpus):
    return {'papers': len(corpus.get('papers') or []), 'unverified': len(corpus.get('unverified') or [])}


STATUSES = ('all', 'unchecked', 'checked', 'unverified')
MAX_VIEW = 200
VIEW_AUTHORS = 3


def _verdict(entry):
    status = (entry.get('check') or {}).get('status')
    return status if status in CONFIRMED else 'unchecked'


def view(corpus, arguments):
    """`research_corpus` for an agent: a page of the corpus, filtered. Compact records only (no abstracts), each with
    its number in the corpus, so a follow-up call can page on. ValueError for bad arguments."""
    arguments = arguments if isinstance(arguments, dict) else {}
    unknown = set(arguments) - {'status', 'query', 'limit', 'offset'}
    if unknown:
        raise ValueError('Unknown argument: ' + sorted(unknown)[0] + '.')
    status = arguments.get('status', 'all')
    if status not in STATUSES:
        raise ValueError('status must be all, unchecked, checked or unverified.')
    query = arguments.get('query', '')
    if not isinstance(query, str) or len(query) > 200:
        raise ValueError('query must be text of at most 200 characters.')
    limit, offset = arguments.get('limit', 50), arguments.get('offset', 0)
    if type(limit) is not int or not 1 <= limit <= MAX_VIEW:
        raise ValueError('limit must be from 1 to 200.')
    if type(offset) is not int or not 0 <= offset <= MAX_PAPERS:
        raise ValueError('offset must be from 0 to 2000.')
    words = [w for w in query.lower().split() if w]

    def hit(texts):
        joined = ' '.join(t for t in texts if isinstance(t, str)).lower()
        return all(w in joined for w in words)

    papers = corpus.get('papers') or []
    counts = {'papers': len(papers), 'checked': sum(1 for p in papers if _verdict(p) != 'unchecked'),
              'unchecked': sum(1 for p in papers if _verdict(p) == 'unchecked'),
              'unverified': len(corpus.get('unverified') or [])}
    result = {'counts': counts, 'status': status}
    if status == 'unverified':
        rows = [u for u in corpus.get('unverified') or []
                if hit([str((u.get('reference') or {}).get(k) or '') for k in ('title', 'raw')])]
        result['matched'] = len(rows)
        result['references'] = [{'reference': u.get('reference'), 'status': u.get('status'),
                                 'fields': u.get('fields') or [], 'reason': u.get('reason')}
                                for u in rows[offset:offset + limit]]
        return result
    numbered = [(n, p) for n, p in enumerate(papers, 1)
                if (status == 'all' or (status == 'checked') == (_verdict(p) != 'unchecked'))
                and hit([p['paper'].get('title'), p['paper'].get('venue')] + list(p['paper'].get('authors') or []))]
    result['matched'] = len(numbered)
    result['offset'] = offset
    result['papers'] = [{'n': n, 'title': p['paper'].get('title'),
                         'authors': list(p['paper'].get('authors') or [])[:VIEW_AUTHORS],
                         'year': p['paper'].get('year'), 'venue': p['paper'].get('venue'), 'doi': p['paper'].get('doi'),
                         'arxiv_id': p['paper'].get('arxiv_id'), 'url': p['paper'].get('url'),
                         'oa_url': p['paper'].get('oa_url'), 'citation_count': p['paper'].get('citation_count'),
                         'sources': p['paper'].get('sources') or [], 'verdict': _verdict(p)}
                        for n, p in numbered[offset:offset + limit]]
    if offset + limit < len(numbered):
        result['next_offset'] = offset + limit
    return result
