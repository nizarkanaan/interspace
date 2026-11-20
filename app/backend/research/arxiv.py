"""arXiv API client (spike-0b.md "arXiv API"): Atom XML search and lookup, PDF links and BibTeX."""
import re
import xml.etree.ElementTree as ET

from . import base, http, records

QUERY = 'https://export.arxiv.org/api/query'
BIBTEX = 'https://arxiv.org/bibtex/'
NS = {'atom': 'http://www.w3.org/2005/Atom', 'arxiv': 'http://arxiv.org/schemas/atom'}
MAX_RESULTS = 100
ERROR_ID = 'arxiv.org/api/errors'
_ABS = re.compile(r'^https?://(?:www\.)?arxiv\.org/abs/(.+)$')
_YEAR = re.compile(r'(\byear\s*=\s*)(\{\s*\d{4}\s*\}|"\s*\d{4}\s*"|\d{4})', re.I)
_TERM = re.compile(r'[^\w\-.]+', re.U)
MAX_BIBTEX = 20000


def _parse(text):
    if '<!DOCTYPE' in text or '<!ENTITY' in text:   # never expand entities from upstream XML
        raise http.BadResponse('arXiv sent a reply Interspace could not read.')
    return ET.fromstring(text)


def _text(entry, path):
    node = entry.find(path, NS)
    return node.text if node is not None and node.text else None


def record(entry):
    """A record for one Atom <entry>, or None for arXiv's error entry."""
    entry_id = _text(entry, 'atom:id') or ''
    if ERROR_ID in entry_id:
        return None
    match = _ABS.match(entry_id.strip())
    arxiv_id = records.normalize_arxiv(match.group(1)) if match else None
    if not arxiv_id:
        return None
    published = _text(entry, 'atom:published') or ''
    return records.make(
        'arxiv', title=_text(entry, 'atom:title'),
        authors=[_text(a, 'atom:name') for a in entry.findall('atom:author', NS)],
        year=published[:4] or None, venue=_text(entry, 'arxiv:journal_ref'), doi=_text(entry, 'arxiv:doi'),
        arxiv_id=arxiv_id, abstract=_text(entry, 'atom:summary'), url='https://arxiv.org/abs/' + arxiv_id,
        oa_url='https://arxiv.org/pdf/' + arxiv_id)


def _entries(text):
    root = _parse(text)
    return [r for r in (record(e) for e in root.findall('atom:entry', NS)) if r is not None]


def search_query(query, year_from=None, year_to=None):
    """`all:` terms joined by AND, plus a submittedDate range. Quotes and brackets in the query are dropped."""
    terms = [t for t in _TERM.split(query) if t and t.upper() not in ('AND', 'OR', 'ANDNOT')][:20]
    parts = ['all:' + t for t in terms] or ['all:' + '""']
    if year_from is not None or year_to is not None:
        parts.append('submittedDate:[%s01010000 TO %s12312359]' % (year_from or 1991, year_to or 2999))
    return ' AND '.join(parts)


class Source(base.Source):
    name = 'arxiv'
    title = 'arXiv'
    hosts = http.HOSTS['arxiv']
    credential = None
    credential_kind = None
    required = False
    capabilities = ('search', 'paper', 'fulltext', 'bibtex')
    id_kinds = ('arxiv',)
    help_url = 'https://info.arxiv.org/help/api/index.html'
    test_id = 'arXiv:1706.03762'

    def _search(self, query, year_from, year_to, limit):
        params = {'search_query': search_query(query, year_from, year_to), 'start': 0,
                  'max_results': min(limit, MAX_RESULTS)}
        return _entries(self.get(QUERY, params=params).text())

    def _paper(self, kind, value):
        found = [r for r in _entries(self.get(QUERY, params={'id_list': value}).text()) if r['arxiv_id'] == value]
        return found[0] if found else None

    def _fulltext(self, kind, value):
        paper = self.paper((kind, value))
        if paper is None:
            return None
        return {'oa_url': paper['oa_url'], 'license': None, 'version': 'submittedVersion', 'host_type': 'repository'}

    def _bibtex(self, kind, value):
        """arXiv's BibTeX, with the year replaced by the v1 year (arXiv reports the latest version's)."""
        text = self.get(BIBTEX + value).text().strip()
        if not text.startswith('@') or len(text) > MAX_BIBTEX:
            raise http.BadResponse('arXiv sent BibTeX Interspace could not read.')
        paper = self.paper((kind, value))
        if paper is None:
            return None
        if paper.get('year'):
            text = _YEAR.sub(lambda m: m.group(1) + '{%d}' % paper['year'], text, count=1)
        return text
