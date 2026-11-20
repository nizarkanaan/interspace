"""Crossref REST client (spike-0b.md "Crossref REST"). The optional email joins the polite pool as `mailto`."""
import urllib.parse

from . import base, http, records

BASE = 'https://api.crossref.org'
SELECT = 'DOI,title,author,issued,container-title,is-referenced-by-count,URL,type,update-to,updated-by'
MAX_ROWS = 100
MAX_BIBTEX = 20000


def retracted(work):
    """True when an `updated-by` notice has type `retraction`, else None (Crossref cannot say "not retracted").

    Retraction Watch data also lists corrections, so only `type == 'retraction'` counts (spike 0B).
    """
    notices = work.get('updated-by') or []
    if any(isinstance(n, dict) and str(n.get('type', '')).lower() == 'retraction' for n in notices):
        return True
    return None


def _author(person):
    if not isinstance(person, dict):
        return None
    if person.get('name'):
        return person['name']
    return ' '.join(part for part in (person.get('given'), person.get('family')) if part) or None


def _year(work):
    for key in ('issued', 'published', 'published-print', 'published-online'):
        parts = (work.get(key) or {}).get('date-parts') or []
        if parts and parts[0] and parts[0][0]:
            return parts[0][0]
    return None


def _first(values):
    return values[0] if isinstance(values, list) and values else None


def record(work):
    return records.make(
        'crossref', title=_first(work.get('title')), authors=[_author(a) for a in work.get('author') or []],
        year=_year(work), venue=_first(work.get('container-title')), doi=work.get('DOI'),
        abstract=None,   # JATS XML when present; not parsed in v1
        citation_count=work.get('is-referenced-by-count'), url=work.get('URL'), retracted=retracted(work))


def _date_filter(year_from, year_to):
    parts = []
    if year_from is not None:
        parts.append('from-pub-date:%d' % year_from)
    if year_to is not None:
        parts.append('until-pub-date:%d' % year_to)
    return ','.join(parts) or None


class Source(base.Source):
    name = 'crossref'
    title = 'Crossref'
    hosts = http.HOSTS['crossref']
    credential = 'crossref_email'
    credential_kind = 'email'
    required = False
    capabilities = ('search', 'paper', 'bibtex', 'retraction')
    id_kinds = ('doi',)
    help_url = 'https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/'
    test_id = '10.1038/nature14539'

    def _params(self, params=None):
        email = self.secret()
        return dict(params or {}, mailto=email) if email else dict(params or {})

    def _work_url(self, doi):
        return BASE + '/works/' + urllib.parse.quote(doi, safe='/:;()')

    def _search(self, query, year_from, year_to, limit):
        params = {'query.bibliographic': query, 'filter': _date_filter(year_from, year_to),
                  'rows': min(limit, MAX_ROWS), 'select': SELECT}
        body = self.get(BASE + '/works', params=self._params(params), pool='list').json()
        return [record(w) for w in (body.get('message') or {}).get('items') or [] if isinstance(w, dict)]

    def _paper(self, kind, value):
        body = self.get(self._work_url(value), params=self._params()).json()
        return record(body['message'])

    def _bibtex(self, kind, value):
        text = self.get(self._work_url(value) + '/transform/application/x-bibtex', params=self._params()).text().strip()
        if not text.startswith('@') or len(text) > MAX_BIBTEX:
            raise http.BadResponse('Crossref sent BibTeX Interspace could not read.')
        return text
