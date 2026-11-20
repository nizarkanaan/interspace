"""The deterministic citation checker (docs/superpowers/specs/research/tools.md, "Citation checker").

`check(references, lookup)` reports each reference as verified, mismatch, not_found, retracted or unchecked. It
never calls a model and never changes the agent's text: it only reports.

`lookup(source, verb, value)` is the dispatch layer, so the checker is tested with fakes:
- `lookup(source, 'paper', identifier)` returns a normalized record (tools.md) or None when the source does not
  know the identifier;
- `lookup(source, 'search', title)` returns a list of records (the five best);
- either raises `Skipped(reason)` when that source could not check (not configured, denied or failed).
Any other exception from a lookup also counts as a skip, with a fixed reason: upstream text never reaches the report.

`source_lookup(sources, authorize)` builds such a lookup over Source instances (research/<source>.py).

Title helpers come from `research.records`.
"""
import re
import time
import unicodedata

from timeutil import iso_time

from . import records

V = 1
MAX_REFERENCES = 200
MAX_TEXT = 4000
VERIFIED_SIMILARITY = 0.90
CANDIDATE_SIMILARITY = 0.75
SEARCH_LIMIT = 5
STATUSES = ('verified', 'mismatch', 'not_found', 'retracted', 'unchecked')
INPUT_FIELDS = ('title', 'authors', 'year', 'doi', 'arxiv_id', 'raw')
# Where each kind of reference is looked up, in order (tools.md step 2).
DOI_SOURCES = ('crossref', 'openalex')
ARXIV_SOURCES = ('arxiv', 'semantic_scholar')
SEARCH_SOURCES = ('semantic_scholar', 'openalex')
# The matched record in the report: everything but the abstract, which is long and not part of the check.
MATCH_FIELDS = ('v', 'title', 'authors', 'year', 'venue', 'doi', 'arxiv_id', 's2_id', 'openalex_id',
                'citation_count', 'url', 'oa_url', 'retracted', 'sources')
MAX_MATCH_AUTHORS = 20

DOI = re.compile(r'\b(10\.\d{4,9}/[^\s"<>“”]+)', re.I)
ARXIV = re.compile(r'(?:arxiv\s*:\s*|arxiv\.org/(?:abs|pdf)/)([0-9]{4}\.[0-9]{4,5}|[a-z][a-z.-]+/[0-9]{7})(v[0-9]+)?',
                   re.I)
BARE_ARXIV = re.compile(r'^([0-9]{4}\.[0-9]{4,5})(v[0-9]+)?$')
URL = re.compile(r'https?://\S+', re.I)
QUOTED = re.compile(r'[“"]([^“”"]{3,})[”"]')
YEAR = re.compile(r'\b(1[89][0-9]{2}|20[0-9]{2})\b')
SENTENCE_BREAK = re.compile(r'(?<=[.?!])\s+')
WORD = re.compile(r'[^\W\d_]{2,}')
INITIAL = re.compile(r'(?<![\w])[A-Z]\b\.?')  # "Y." or "N" in an author list.
RETRACTED_PREFIX = re.compile(r'^\s*retracted\s*:\s*', re.I)


TITLE_ONLY = ('Only the title could be compared, and papers can share a title. Give the first author or the '
              'year to verify it.')


class Skipped(Exception):
    """A source could not check this reference; the message is a short reason code such as `denied`."""


# ------------------------------------------------------------------------------------------ titles

def similarity(a, b):
    """Normalized title similarity from 0 to 1. A leading `RETRACTED:` is ignored (spike-0b.md gotcha 3)."""
    a, b = RETRACTED_PREFIX.sub('', a or ''), RETRACTED_PREFIX.sub('', b or '')
    return float(records.title_similarity(a, b))


# ---------------------------------------------------------------------------------------- references

def _plain(text):
    text = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in text if not unicodedata.combining(c)).casefold()


def surname(name):
    """The surname of an author as written ('Ashish Vaswani', 'Vaswani, A.', 'A. Vaswani'): case and diacritics
    removed. None when nothing name-like is there."""
    if not isinstance(name, str) or not name.strip():
        return None
    part = name.split(',')[0] if ',' in name else name
    words = [w for w in re.split(r'[\s.]+', _plain(part)) if w]
    words = [w for w in words if len(w) > 1 or len(words) == 1]
    if not words:
        return None
    word = re.sub(r'[^\w\'-]', '', words[-1])
    return word or None


def normalize_doi(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    text = re.sub(r'^(https?://(dx\.)?doi\.org/|doi:\s*)', '', text, flags=re.I)
    found = DOI.search(text)
    return found.group(1).rstrip('.,;)]').lower() if found else None


def normalize_arxiv(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    found = ARXIV.search(text) or BARE_ARXIV.match(text)
    return found.group(1).lower() if found else None


def _title_from_raw(text):
    quoted = QUOTED.search(text)
    if quoted:
        return quoted.group(1).strip().rstrip(',.;:').strip()
    best, best_words = None, 0
    for segment in SENTENCE_BREAK.split(text):
        segment = segment.strip().rstrip('.').strip()
        count = len(WORD.findall(segment)) - len(INITIAL.findall(segment))
        if count > best_words or (count == best_words and best is not None and len(segment) > len(best)):
            best, best_words = segment, count
    return best if best_words >= 2 else None


def _check_text(value, what, limit=MAX_TEXT):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError('Reference %s must be text of at most %d characters.' % (what, limit))
    return value.strip() or None


def _year(value):
    if value is None:
        return None
    if type(value) is int:
        year = value
    elif isinstance(value, str) and value.strip().isdigit():
        year = int(value.strip())
    else:
        raise ValueError('A reference year must be a whole number.')
    if not 1000 <= year <= 3000:
        raise ValueError('A reference year must be a whole number.')
    return year


def normalize_reference(reference):
    """What the checker compares: {title, first_author, year, doi, arxiv_id}. Given fields win over `raw`."""
    if not isinstance(reference, dict):
        raise ValueError('Each reference must be an object.')
    title = _check_text(reference.get('title'), 'title')
    raw = _check_text(reference.get('raw'), 'text')
    authors = reference.get('authors')
    if isinstance(authors, str):
        authors = [authors]
    if authors is not None and (not isinstance(authors, list) or len(authors) > 500
                                or not all(isinstance(a, str) and len(a) <= 1000 for a in authors)):
        raise ValueError('Reference authors must be a list of names.')
    year = _year(reference.get('year'))
    doi = normalize_doi(_check_text(reference.get('doi'), 'DOI', 1000))
    arxiv_id = normalize_arxiv(_check_text(reference.get('arxiv_id'), 'arXiv ID', 1000))
    if raw:
        doi = doi or normalize_doi(raw)
        arxiv_id = arxiv_id or normalize_arxiv(raw)
        rest = ARXIV.sub(' ', DOI.sub(' ', URL.sub(' ', raw)))
        title = title or _title_from_raw(rest)
        if year is None:
            found = YEAR.search(rest)
            year = int(found.group(1)) if found else None
    # arXiv's DataCite DOI (10.48550/arXiv.<id>) names an arXiv paper: it is checked by its arXiv ID.
    arxiv_id = arxiv_id or records.arxiv_from_doi(doi)
    first = next((a for a in authors or [] if a.strip()), None)
    # With no author list, the first author is looked for in the pasted line itself (Wave 3B).
    names = _plain(raw) if raw and first is None else None
    return {'title': title, 'first_author': surname(first), 'year': year, 'doi': doi, 'arxiv_id': arxiv_id,
            'raw_names': names}


# ---------------------------------------------------------------------------------------- checking

def _match_view(record):
    view = {k: record.get(k) for k in MATCH_FIELDS if k in record}
    if isinstance(view.get('authors'), list):
        view['authors'] = view['authors'][:MAX_MATCH_AUTHORS]
    return view


def _ask(lookup, source, verb, value, skipped):
    try:
        return lookup(source, verb, value)
    except Skipped as reason:
        skipped.append('%s: %s' % (source, str(reason)[:64] or 'skipped'))
    except Exception:
        skipped.append('%s: failed' % source)
    return None


def _valid(record):
    return isinstance(record, dict) and isinstance(record.get('title'), str)


def _source_of(record, source):
    sources = record.get('sources')
    return source if not isinstance(sources, list) or source in sources or not sources else sources[0]


def _find(ref, lookup):
    """(record, source, exact, similarity, answered, skipped) for one normalized reference."""
    skipped, answered = [], 0
    lookups = []
    if ref['doi']:
        lookups.append((DOI_SOURCES, ref['doi']))
    if ref['arxiv_id']:
        lookups.append((ARXIV_SOURCES, 'arXiv:' + ref['arxiv_id']))
    for sources, identifier in lookups:
        for source in sources:
            before = len(skipped)
            found = _ask(lookup, source, 'paper', identifier, skipped)
            if len(skipped) == before:
                answered += 1
            if _valid(found):
                score = similarity(ref['title'], found['title']) if ref['title'] else None
                return found, _source_of(found, source), True, score, answered, skipped
    best = None
    if ref['title']:
        for source in SEARCH_SOURCES:
            before = len(skipped)
            found = _ask(lookup, source, 'search', ref['title'], skipped)
            if len(skipped) == before:
                answered += 1
            for candidate in (found if isinstance(found, list) else [])[:SEARCH_LIMIT]:
                if not _valid(candidate):
                    continue
                score = similarity(ref['title'], candidate['title'])
                if best is None or score > best[3]:
                    best = (candidate, _source_of(candidate, source), False, score)
    if best is not None and best[3] >= CANDIDATE_SIMILARITY:
        return best + (answered, skipped)
    return None, None, False, best[3] if best else None, answered, skipped


def _named_in(surname_text, plain_text):
    """Whether a surname appears as a word (or two adjacent words, 'Le Cun') of the pasted line."""
    words = re.findall(r"[\w'-]+", plain_text)
    joined = set(words) | {a + b for a, b in zip(words, words[1:])}
    return surname_text in joined


def _differs(ref, match, score, exact):
    """(fields that differ, whether a field besides the title confirmed the match)."""
    fields, confirmed = [], False
    if ref['title'] and score is not None and score < VERIFIED_SIMILARITY:
        fields.append('title')
    year = match.get('year')
    if ref['year'] is not None and type(year) is int:
        if abs(year - ref['year']) > 1:
            fields.append('year')
        else:
            confirmed = True
    authors = match.get('authors') if isinstance(match.get('authors'), list) else []
    found = surname(next((a for a in authors if isinstance(a, str) and a.strip()), None))
    # A pasted line is searched for the first author only when a title search found the paper; an exact DOI or
    # arXiv ID already identifies it, and a line may name no author at all.
    raw_names = ref.get('raw_names') if not exact else None
    if found and (ref['first_author'] or raw_names):
        if ref['first_author'] == found or (not ref['first_author'] and _named_in(found, raw_names)):
            confirmed = True
        else:
            fields.append('authors')
    # Every identifier the reference gives must be the matched paper's: a DOI or arXiv ID that no source
    # resolved is never verified by a title match that lacks it (Wave 3B).
    doi = normalize_doi(match.get('doi'))
    arxiv_id = match.get('arxiv_id') if isinstance(match.get('arxiv_id'), str) else None
    arxiv_id = (normalize_arxiv(arxiv_id) or arxiv_id) if arxiv_id else records.arxiv_from_doi(doi)
    doi_given = ref['doi'] if ref['doi'] and not records.arxiv_from_doi(ref['doi']) else None
    doi_same = bool(doi_given) and doi == doi_given
    arxiv_same = bool(ref['arxiv_id']) and arxiv_id == ref['arxiv_id']
    any_same = doi_same or arxiv_same
    if doi_given and not doi_same and (doi is not None or not any_same):
        fields.append('doi')
    if ref['arxiv_id'] and not arxiv_same and (arxiv_id is not None or not any_same):
        fields.append('arxiv_id')
    return fields, confirmed or any_same


def _check_one(index, given, lookup):
    ref = normalize_reference(given)
    entry = {'index': index, 'input': given, 'status': 'not_found', 'fields': [], 'match': None,
             'similarity': None, 'source': None}
    if not (ref['title'] or ref['doi'] or ref['arxiv_id']):
        return dict(entry, status='unchecked', reason='The reference has no title, DOI or arXiv ID to check.')
    match, source, exact, score, answered, skipped = _find(ref, lookup)
    entry['similarity'] = round(score, 4) if score is not None else None
    if match is None:
        if not answered:
            return dict(entry, status='unchecked', reason=', '.join(skipped) or 'No source could check it.')
        return entry
    entry.update(match=_match_view(match), source=source)
    if match.get('retracted') is True:
        return dict(entry, status='retracted')
    entry['fields'], confirmed = _differs(ref, match, score, exact)
    if entry['fields']:
        return dict(entry, status='mismatch')
    if not exact and not confirmed:
        # A title alone cannot tell papers with the same title apart ('Deep learning'): not verified.
        return dict(entry, status='unchecked', reason=TITLE_ONLY)
    entry['status'] = 'verified'
    return entry


def _clean_input(reference):
    return {k: reference[k] for k in INPUT_FIELDS if k in reference}


def check(references, lookup, *, now=None):
    """The citation report (tools.md) for 1–200 references. Raises ValueError for bad arguments only."""
    if not isinstance(references, list) or not 1 <= len(references) <= MAX_REFERENCES:
        raise ValueError('Give 1–200 references to check.')
    cleaned = []
    for reference in references:
        if not isinstance(reference, dict):
            raise ValueError('Each reference must be an object.')
        normalize_reference(reference)  # Every argument is checked before any lookup runs.
        cleaned.append(_clean_input(reference))
    results = [_check_one(i, reference, lookup) for i, reference in enumerate(cleaned)]
    summary = {status: sum(1 for r in results if r['status'] == status) for status in STATUSES}
    return {'v': V, 'checked_at': iso_time(time.time() if now is None else now), 'summary': summary,
            'references': results}


# ------------------------------------------------------------------------------------------ compact

COMPACT_TEXT = 120
COMPACT_TITLE = 160
COMPACT_AUTHORS = 3


def _clip(value, limit):
    if not isinstance(value, str):
        return value
    return value if len(value) <= limit else value[:limit - 1] + '…'


def compact(report):
    """A smaller copy of a report for an agent or a card when the whole one is too large: every status, field
    and identifier is kept; long text is clipped and author lists shortened. The report itself is unchanged."""
    small = {k: v for k, v in report.items() if k != 'references'}
    small['references'] = []
    for entry in report.get('references') or []:
        if not isinstance(entry, dict):
            continue
        given = entry.get('input') if isinstance(entry.get('input'), dict) else {}
        shown = {k: given[k] for k in ('year', 'doi', 'arxiv_id') if k in given}
        if isinstance(given.get('title'), str):
            shown['title'] = _clip(given['title'], COMPACT_TEXT)
        elif isinstance(given.get('raw'), str):
            shown['raw'] = _clip(given['raw'], COMPACT_TEXT)
        if isinstance(given.get('authors'), list):
            shown['authors'] = [_clip(a, COMPACT_TEXT) for a in given['authors'][:1]]
        item = {k: v for k, v in entry.items() if k not in ('input', 'match')}
        item['input'] = shown
        match = entry.get('match')
        if isinstance(match, dict):
            item['match'] = {k: match.get(k) for k in ('title', 'authors', 'year', 'doi', 'arxiv_id', 'retracted',
                                                       'sources') if k in match}
            item['match']['title'] = _clip(match.get('title'), COMPACT_TITLE)
            if isinstance(match.get('authors'), list):
                item['match']['authors'] = [_clip(a, COMPACT_TEXT) for a in match['authors'][:COMPACT_AUTHORS]]
        else:
            item['match'] = None
        small['references'].append(item)
    return small


# ------------------------------------------------------------------------------------ source lookup

ERROR_CODES = {'NotConfigured': 'not_configured', 'RateLimited': 'rate_limited', 'Unavailable': 'unavailable',
               'BadResponse': 'bad_response', 'NotFound': 'not_found'}


def _code(error):
    code = getattr(error, 'code', None)
    if isinstance(code, str) and re.match(r'^[a-z_]{1,32}$', code):
        return code
    return ERROR_CODES.get(type(error).__name__, 'failed')


def source_lookup(sources, authorize):
    """A `lookup` over Source instances (tools.md "Source modules"). `authorize(source) -> bool` decides each call
    (the caller wraps `ctx.authorize` with the `verify_citations` tool). Errors become skips with their code only."""
    def lookup(source, verb, value):
        instance = sources.get(source)
        if instance is None:
            raise Skipped('not_configured')
        if not authorize(source):
            raise Skipped('denied')
        try:
            if verb == 'paper':
                return instance.paper(value)
            return instance.search(value, limit=SEARCH_LIMIT)
        except Exception as error:
            code = _code(error)
            if code == 'not_found':
                return None if verb == 'paper' else []
            raise Skipped(code) from None
    return lookup
