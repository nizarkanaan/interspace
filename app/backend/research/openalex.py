"""OpenAlex works client (spike-0b.md "OpenAlex"). The key is optional and only raises the quota."""
import re
import urllib.parse

from . import base, http, records

BASE = 'https://api.openalex.org'
SELECT = ('id,doi,display_name,title,publication_year,ids,authorships,primary_location,best_oa_location,'
          'open_access,cited_by_count,is_retracted,abstract_inverted_index,type')
MAX_PER_PAGE = 100
MAX_ABSTRACT_WORDS = 2000
_WORK = re.compile(r'^W\d{1,12}$')


def abstract(inverted):
    """Rebuild text from `abstract_inverted_index` ({word: [positions]}), or None."""
    if not isinstance(inverted, dict):
        return None
    slots = []
    for word, positions in inverted.items():
        for position in positions if isinstance(positions, list) else []:
            if isinstance(position, int) and 0 <= position < MAX_ABSTRACT_WORDS:
                slots.append((position, str(word)))
    return ' '.join(word for _, word in sorted(slots)) or None


def _work_id(value):
    return str(value or '').rsplit('/', 1)[-1] or None


def record(work):
    location = work.get('primary_location') or {}
    best = work.get('best_oa_location') or {}
    oa = (work.get('open_access') or {}).get('oa_url') or best.get('pdf_url') or best.get('landing_page_url')
    authors = [((a.get('author') or {}).get('display_name')) for a in work.get('authorships') or []
               if isinstance(a, dict)]
    retracted = work.get('is_retracted')
    work_id = _work_id(work.get('id'))
    url = work.get('doi') or ('https://openalex.org/' + work_id if work_id else None)
    return records.make(
        'openalex', title=work.get('display_name') or work.get('title'), authors=authors,
        year=work.get('publication_year'), venue=(location.get('source') or {}).get('display_name'),
        doi=work.get('doi'), openalex_id=work_id, abstract=abstract(work.get('abstract_inverted_index')),
        citation_count=work.get('cited_by_count'), url=url, oa_url=oa,
        retracted=retracted if isinstance(retracted, bool) else None)


def _year_filter(year_from, year_to):
    if year_from is None and year_to is None:
        return None
    if year_from is not None and year_to is not None:
        return 'publication_year:%d-%d' % (year_from, year_to)
    if year_from is not None:
        return 'publication_year:>%d' % (year_from - 1)
    return 'publication_year:<%d' % (year_to + 1)


class Source(base.Source):
    name = 'openalex'
    title = 'OpenAlex'
    hosts = http.HOSTS['openalex']
    credential = 'openalex'
    credential_kind = 'api_key'
    required = False          # spike 0B: keyless calls work on a small shared per-IP budget
    capabilities = ('search', 'paper', 'citations', 'fulltext', 'retraction')
    id_kinds = ('doi', 'arxiv', 'openalex')
    help_url = 'https://help.openalex.org/api/authentication/'
    test_id = '10.1038/nature14539'

    def _headers(self):
        key = self.secret()
        return {'Authorization': 'Bearer ' + key} if key else None

    def _work_url(self, kind, value):
        if kind == 'openalex':
            return BASE + '/works/' + value
        doi = value if kind == 'doi' else '10.48550/arxiv.' + value
        return BASE + '/works/doi:' + urllib.parse.quote(doi, safe='/:;()')

    def _work(self, kind, value, select=SELECT):
        return self.get(self._work_url(kind, value), params={'select': select}, headers=self._headers()).json()

    def _list(self, params):
        body = self.get(BASE + '/works', params=dict(params, select=SELECT), headers=self._headers()).json()
        return [record(w) for w in body.get('results') or [] if isinstance(w, dict)]

    def _search(self, query, year_from, year_to, limit):
        return self._list({'search': query, 'filter': _year_filter(year_from, year_to),
                           'per_page': min(limit, MAX_PER_PAGE)})

    def _paper(self, kind, value):
        return record(self._work(kind, value))

    def _citations(self, kind, value, direction, limit):
        limit = min(limit, MAX_PER_PAGE)
        if direction == 'citations':
            work_id = value if kind == 'openalex' else _work_id(self._work(kind, value, 'id').get('id'))
            if not work_id:
                return None
            return self._list({'filter': 'cites:' + work_id, 'per_page': limit})
        referenced = self._work(kind, value, 'id,referenced_works').get('referenced_works') or []
        ids = [_work_id(w) for w in referenced[:limit] if isinstance(w, str)]
        ids = [w for w in ids if w and _WORK.match(w)]
        if not ids:
            return []
        return self._list({'filter': 'openalex:' + '|'.join(ids), 'per_page': limit})

    def _fulltext(self, kind, value):
        work = self._work(kind, value, 'id,best_oa_location,open_access')
        best = work.get('best_oa_location') or {}
        link = records.clean_url(best.get('pdf_url') or best.get('landing_page_url')
                                 or (work.get('open_access') or {}).get('oa_url'))
        if not link:
            return None
        host_type = 'repository' if ((best.get('source') or {}).get('type') == 'repository') else None
        return {'oa_url': link, 'license': records.clean_text(best.get('license'), 100),
                'version': records.clean_text(best.get('version'), 100), 'host_type': host_type}
