"""The normalized paper record, identifiers, title comparison and de-duplication (research/tools.md)."""
import difflib
import re
import unicodedata

FIELDS = ('v', 'title', 'authors', 'year', 'venue', 'doi', 'arxiv_id', 's2_id', 'openalex_id', 'abstract',
          'citation_count', 'url', 'oa_url', 'retracted', 'sources')
TEXT_LIMIT = 1000
ABSTRACT_LIMIT = 4000
MAX_AUTHORS = 100
MAX_ID_TEXT = 512

# Merge priority for every field (tools.md). Open-access links follow spike-0b gotcha 6 instead.
PRIORITY = ('crossref', 'openalex', 'semantic_scholar', 'arxiv', 'unpaywall')
OA_PRIORITY = ('unpaywall', 'arxiv', 'openalex', 'semantic_scholar', 'crossref')

_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]')
_SPACE = re.compile(r'\s+')
_DOI_PREFIX = re.compile(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)', re.I)
_DOI = re.compile(r'^10\.\d{4,9}/\S+$')
_ARXIV_DOI = re.compile(r'^10\.48550/arxiv\.(.+)$', re.I)
_ARXIV_PREFIX = re.compile(r'^(?:arxiv:\s*|https?://(?:www\.|export\.)?arxiv\.org/(?:abs|pdf)/)', re.I)
_ARXIV_NEW = re.compile(r'^(\d{4}\.\d{4,5})(?:v\d+)?$')
_ARXIV_OLD = re.compile(r'^([a-z][a-z-]*(?:\.[A-Za-z]{2})?/\d{7})(?:v\d+)?$')
_S2 = re.compile(r'^[A-Za-z0-9:._-]{1,128}$')
_OPENALEX = re.compile(r'^(?:https://openalex\.org/|openalex:)(W\d{1,12})$', re.I)


# Identifiers ------------------------------------------------------------------

def normalize_doi(text):
    """Lower case, without a doi.org or `doi:` prefix; None when `text` is not a DOI."""
    if not isinstance(text, str):
        return None
    value = _DOI_PREFIX.sub('', text.strip()).strip().lower()
    return value if _DOI.match(value) and len(value) <= MAX_ID_TEXT and not _CONTROL.search(value) else None


def normalize_arxiv(text, *, bare_old_style=True):
    """An arXiv ID without `arXiv:` or a version suffix; None when `text` is not one."""
    if not isinstance(text, str):
        return None
    value = _ARXIV_PREFIX.sub('', text.strip()).strip()
    match = _ARXIV_NEW.match(value) or (_ARXIV_OLD.match(value) if bare_old_style else None)
    return match.group(1) if match else None


def arxiv_from_doi(doi):
    """The arXiv ID behind arXiv's DataCite DOI `10.48550/arXiv.<id>`, else None."""
    match = _ARXIV_DOI.match(doi or '')
    return normalize_arxiv(match.group(1)) if match else None


def parse_id(text):
    """('doi'|'arxiv'|'s2'|'openalex', value) for an identifier an agent passes, or ValueError."""
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_ID_TEXT or _CONTROL.search(text):
        raise ValueError('That is not a DOI, arXiv, s2: or openalex: identifier.')
    value = text.strip()
    lower = value.lower()
    if lower.startswith('s2:'):
        ident = value[3:].strip()
        if _S2.match(ident):
            return 's2', ident
    elif lower.startswith('openalex:') or lower.startswith('https://openalex.org/'):
        match = _OPENALEX.match(value)
        if match:
            return 'openalex', match.group(1).upper()
    elif _ARXIV_PREFIX.match(value):
        arxiv = normalize_arxiv(value)
        if arxiv:
            return 'arxiv', arxiv
    else:
        doi = normalize_doi(value)
        if doi:
            arxiv = arxiv_from_doi(doi)
            return ('arxiv', arxiv) if arxiv else ('doi', doi)
        arxiv = normalize_arxiv(value, bare_old_style=False)
        if arxiv:
            return 'arxiv', arxiv
    raise ValueError('That is not a DOI, arXiv, s2: or openalex: identifier.')


# Text -----------------------------------------------------------------------

# Formatting markup some sources put in titles and abstracts (Crossref: <sup>, <i>, <jats:p>, <mml:math>). Only
# these known tags are removed; any other angle-bracket text is kept as literal text.
_MARKUP = re.compile(r'</?(?:sup|sub|i|b|em|strong|scp|u|tt|jats:[a-z-]+|mml:[a-z-]+)(?:\s[^<>]*)?/?>', re.I)


def clean_text(value, limit=TEXT_LIMIT):
    """One line of text: control characters stripped, whitespace collapsed, cut to `limit` with `…`."""
    if value is None:
        return None
    text = _SPACE.sub(' ', _CONTROL.sub('', _MARKUP.sub('', str(value)))).strip()
    if not text:
        return None
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def clean_url(value):
    """Only https links are kept (README: links are shown only for https: URLs)."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value.lower().startswith('https://') or _CONTROL.search(value) or ' ' in value or len(value) > 2048:
        return None
    return value


def _year(value):
    if isinstance(value, bool):
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 1000 <= year <= 3000 else None


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def make(source, *, title=None, authors=None, year=None, venue=None, doi=None, arxiv_id=None, s2_id=None,
         openalex_id=None, abstract=None, citation_count=None, url=None, oa_url=None, retracted=None):
    """A normalized record from one source's values. Missing values are None; `authors` is [] when unknown."""
    doi = normalize_doi(doi)
    arxiv = normalize_arxiv(arxiv_id) if arxiv_id else None
    names = [clean_text(name) for name in (authors or [])[:MAX_AUTHORS]]
    openalex = _OPENALEX.match('openalex:' + str(openalex_id).rsplit('/', 1)[-1]) if openalex_id else None
    return {
        'v': 1,
        'title': clean_text(title),
        'authors': [name for name in names if name],
        'year': _year(year),
        'venue': clean_text(venue),
        'doi': doi,
        'arxiv_id': arxiv or arxiv_from_doi(doi),
        's2_id': clean_text(s2_id, 128),
        'openalex_id': openalex.group(1).upper() if openalex else None,
        'abstract': clean_text(abstract, ABSTRACT_LIMIT),
        'citation_count': _count(citation_count),
        'url': clean_url(url),
        'oa_url': clean_url(oa_url),
        'retracted': retracted if isinstance(retracted, bool) else None,
        'sources': [source],
    }


# Titles ---------------------------------------------------------------------

_RETRACTED = re.compile(r'^\s*retracted\s*[:\-–—]\s*', re.I)


def normalize_title(text):
    """NFKD, diacritics and punctuation removed, lower case, single spaces; a `RETRACTED:` prefix dropped."""
    if not isinstance(text, str):
        return ''
    text = _RETRACTED.sub('', text)
    decomposed = unicodedata.normalize('NFKD', text)
    letters = ''.join(ch for ch in decomposed if not unicodedata.combining(ch))
    words = re.sub(r'[\W_]+', ' ', letters.casefold())
    return _SPACE.sub(' ', words).strip()


def title_similarity(a, b):
    """0–1 similarity of two titles after normalization."""
    left, right = normalize_title(a), normalize_title(b)
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(None, left, right).ratio()


# Merging --------------------------------------------------------------------

def _doi_key(record):
    """The DOI used for identity. arXiv's DataCite DOI identifies by arXiv ID instead."""
    doi = record.get('doi')
    return doi if doi and not arxiv_from_doi(doi) else None


def same_paper(a, b):
    """Same DOI, else same arXiv ID, else equal normalized titles with years within ±1."""
    doi_a, doi_b = _doi_key(a), _doi_key(b)
    if doi_a and doi_b:
        return doi_a == doi_b
    if a.get('arxiv_id') and b.get('arxiv_id'):
        return a['arxiv_id'] == b['arxiv_id']
    title_a, title_b = normalize_title(a.get('title')), normalize_title(b.get('title'))
    year_a, year_b = a.get('year'), b.get('year')
    return bool(title_a) and title_a == title_b and year_a is not None and year_b is not None \
        and abs(year_a - year_b) <= 1


def _rank(record, order):
    source = (record.get('sources') or [None])[0]
    return order.index(source) if source in order else len(order)


def _combine(group):
    ordered = sorted(group, key=lambda r: _rank(r, PRIORITY))
    merged = {'v': 1}
    for field in FIELDS:
        if field in ('v', 'sources', 'retracted', 'oa_url'):
            continue
        empty = [] if field == 'authors' else None
        merged[field] = next((r[field] for r in ordered if r.get(field)), empty)
        if isinstance(merged[field], list):
            merged[field] = list(merged[field])
    merged['oa_url'] = next((r['oa_url'] for r in sorted(group, key=lambda r: _rank(r, OA_PRIORITY))
                             if r.get('oa_url')), None)
    flags = [r.get('retracted') for r in ordered if r.get('retracted') is not None]
    merged['retracted'] = True if True in flags else (flags[0] if flags else None)
    names = {name for r in group for name in r.get('sources') or []}
    merged['sources'] = [s for s in PRIORITY if s in names] + sorted(names - set(PRIORITY))
    return {field: merged[field] for field in FIELDS}


def merge(list_of_records):
    """Records with duplicates combined; groups keep the order in which they first appear."""
    groups = []
    for record in list_of_records:
        joined = [g for g in groups if any(same_paper(record, member) for member in g)]
        if not joined:
            groups.append([record])
            continue
        first = joined[0]
        for other in joined[1:]:
            first.extend(other)
            groups.remove(other)
        first.append(record)
    return [_combine(group) for group in groups]
