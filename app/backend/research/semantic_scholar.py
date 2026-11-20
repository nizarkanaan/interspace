"""Semantic Scholar Graph API client (spike-0b.md "Semantic Scholar Graph API")."""
import urllib.parse

from . import base, http, records

BASE = 'https://api.semanticscholar.org/graph/v1'
FIELDS = ('paperId,externalIds,title,abstract,year,venue,publicationVenue,authors,citationCount,url,'
          'openAccessPdf,isOpenAccess,publicationTypes,publicationDate')
LINK_FIELDS = 'paperId,externalIds,title,year,authors,venue,citationCount,url'
MAX_LIMIT = 100


def record(paper):
    ids = paper.get('externalIds') or {}
    venue = paper.get('venue') or (paper.get('publicationVenue') or {}).get('name')
    pdf = paper.get('openAccessPdf') or {}
    return records.make(
        'semantic_scholar', title=paper.get('title'),
        authors=[a.get('name') for a in paper.get('authors') or [] if isinstance(a, dict)],
        year=paper.get('year'), venue=venue, doi=ids.get('DOI'), arxiv_id=ids.get('ArXiv'),
        s2_id=paper.get('paperId'), abstract=paper.get('abstract'), citation_count=paper.get('citationCount'),
        url=paper.get('url'), oa_url=pdf.get('url'))


def _year_param(year_from, year_to):
    if year_from is None and year_to is None:
        return None
    if year_from == year_to:
        return str(year_from)
    return '%s-%s' % ('' if year_from is None else year_from, '' if year_to is None else year_to)


class Source(base.Source):
    name = 'semantic_scholar'
    title = 'Semantic Scholar'
    hosts = http.HOSTS['semantic_scholar']
    credential = 'semantic_scholar'
    credential_kind = 'api_key'
    required = False
    capabilities = ('search', 'paper', 'citations')
    id_kinds = ('doi', 'arxiv', 's2')
    help_url = 'https://www.semanticscholar.org/product/api#api-key-form'
    test_id = 'arXiv:1706.03762'

    def _headers(self):
        key = self.secret()
        return {'x-api-key': key} if key else None

    def _paper_path(self, kind, value):
        prefix = {'doi': 'DOI:', 'arxiv': 'ARXIV:', 's2': ''}[kind]
        return BASE + '/paper/' + urllib.parse.quote(prefix + value, safe=':/()')

    def _search(self, query, year_from, year_to, limit):
        params = {'query': query, 'year': _year_param(year_from, year_to), 'limit': min(limit, MAX_LIMIT),
                  'fields': FIELDS}
        body = self.get(BASE + '/paper/search', params=params, headers=self._headers()).json()
        return [record(p) for p in body.get('data') or [] if isinstance(p, dict)]

    def _paper(self, kind, value):
        body = self.get(self._paper_path(kind, value), params={'fields': FIELDS}, headers=self._headers()).json()
        return record(body)

    def match(self, title):
        """The best title match (`/paper/search/match`), or None. For lookups by DOI that Semantic Scholar misses."""
        self._require('search')
        text = records.clean_text(title, 500)
        if not text:
            return None

        def compute():
            try:
                body = self.get(BASE + '/paper/search/match', params={'query': text, 'fields': FIELDS},
                                headers=self._headers()).json()
            except http.NotFound:   # no match is a 404 with a JSON message
                return None
            data = [p for p in body.get('data') or [] if isinstance(p, dict)]
            return record(data[0]) if data else None
        return self._cached('match', [text], compute)

    def _citations(self, kind, value, direction, limit):
        key = 'citingPaper' if direction == 'citations' else 'citedPaper'
        body = self.get(self._paper_path(kind, value) + '/' + direction,
                        params={'fields': LINK_FIELDS, 'limit': min(limit, MAX_LIMIT)}, headers=self._headers()).json()
        papers = [item.get(key) for item in body.get('data') or [] if isinstance(item, dict)]
        return [record(p) for p in papers if isinstance(p, dict) and p.get('title')]
