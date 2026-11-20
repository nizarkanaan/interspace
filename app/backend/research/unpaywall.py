"""Unpaywall client (spike-0b.md "Unpaywall"). The user's email is required on every call."""
import urllib.parse

from . import base, http, records

BASE = 'https://api.unpaywall.org/v2/'


def _location(best):
    if not isinstance(best, dict):
        return None
    link = records.clean_url(best.get('url_for_pdf') or best.get('url') or best.get('url_for_landing_page'))
    if not link:
        return None
    return {'oa_url': link, 'license': records.clean_text(best.get('license'), 100),
            'version': records.clean_text(best.get('version'), 100),
            'host_type': records.clean_text(best.get('host_type'), 100)}


def _author(person):
    if not isinstance(person, dict):
        return None
    return ' '.join(p for p in (person.get('given'), person.get('family')) if p) or None


def record(body):
    location = _location(body.get('best_oa_location'))
    return records.make(
        'unpaywall', title=body.get('title'), authors=[_author(a) for a in body.get('z_authors') or []],
        year=body.get('year'), venue=body.get('journal_name'), doi=body.get('doi'), url=body.get('doi_url'),
        oa_url=location['oa_url'] if location else None)


class Source(base.Source):
    name = 'unpaywall'
    title = 'Unpaywall'
    hosts = http.HOSTS['unpaywall']
    credential = 'unpaywall_email'
    credential_kind = 'email'
    required = True
    capabilities = ('paper', 'fulltext')
    id_kinds = ('doi',)
    help_url = 'https://unpaywall.org/products/api'
    test_id = '10.1038/nature14539'

    def _lookup(self, doi):
        email = self.secret()   # raises NotConfigured when missing
        return self.get(BASE + urllib.parse.quote(doi, safe='/:;()'), params={'email': email}).json()

    def _paper(self, kind, value):
        return record(self._lookup(value))

    def _fulltext(self, kind, value):
        return _location(self._lookup(value).get('best_oa_location'))
