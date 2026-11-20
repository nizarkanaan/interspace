"""The behaviour every research source module shares (research/tools.md "Source modules").

A source subclass sets its class attributes and implements the `_search`, `_paper`, ... hooks for the verbs
in its `capabilities`. This class adds identifier parsing, the cache, credentials and `status`.
"""
import time
import xml.etree.ElementTree as ET

from . import credentials, http, records

VERBS = {'search': 'search', 'paper': 'look up papers', 'citations': 'list citations',
         'fulltext': 'find open-access links', 'bibtex': 'give BibTeX'}
DIRECTIONS = ('citations', 'references')


class Source:
    name = None
    title = None
    hosts = ()
    credential = None          # Keychain account (credentials.md) or None
    credential_kind = None     # 'api_key' | 'email' | None
    required = False
    capabilities = ()
    id_kinds = ()              # identifier kinds `paper` and friends accept
    help_url = None
    test_id = None             # the fixed identifier `status(test=True)` looks up

    def __init__(self, *, http, credentials, cache, clock=time.time):
        self.http = http
        self.credentials = credentials
        self.cache = cache
        self.clock = clock

    # Credentials --------------------------------------------------------

    def secret(self):
        """The stored key or email, or None. A required one that is missing raises NotConfigured."""
        if not self.credential or self.credentials is None:
            value = None
        else:
            value = self.credentials.get(self.credential)
        if not value and self.required:
            raise http.not_configured(self.name)
        return value or None

    def configured(self):
        if not self.credential:
            return True
        if self.credentials is None:
            return False
        return bool(self.credentials.configured(self.credential))

    # Plumbing -----------------------------------------------------------

    def get(self, url, **options):
        return self.http.get(self.name, url, **options)

    def _unsupported(self, verb):
        return ValueError('%s cannot %s.' % (self.title, VERBS.get(verb, verb)))

    def _require(self, verb):
        if verb not in self.capabilities:
            raise self._unsupported(verb)

    def _identifier(self, identifier, verb):
        kind, value = identifier if isinstance(identifier, tuple) else records.parse_id(identifier)
        if kind not in self.id_kinds:
            raise ValueError('%s cannot look up that kind of identifier.' % self.title)
        return kind, value

    def _cached(self, method, args, compute):
        if self.cache is not None:
            hit, value = self.cache.get(self.name, method, args)
            if hit:
                return value
        try:
            value = compute()
        except (KeyError, IndexError, TypeError, AttributeError, ET.ParseError):
            # Upstream JSON or XML that did not fit the documented shape.
            raise http.BadResponse('%s sent a reply Interspace could not read.' % self.title) from None
        if self.cache is not None:
            self.cache.put(self.name, method, args, value)
        return value

    def _not_found_is_none(self, compute):
        try:
            return compute()
        except http.NotFound:
            return None

    def can_lookup(self, identifier):
        try:
            kind = records.parse_id(identifier)[0] if not isinstance(identifier, tuple) else identifier[0]
        except ValueError:
            return False
        return kind in self.id_kinds

    # Verbs --------------------------------------------------------------

    def search(self, query, *, year_from=None, year_to=None, limit=10):
        self._require('search')
        args = {'query': query, 'year_from': year_from, 'year_to': year_to, 'limit': limit}
        return self._cached('search', args, lambda: self._search(query, year_from, year_to, limit))

    def paper(self, identifier):
        self._require('paper')
        kind, value = self._identifier(identifier, 'paper')
        return self._cached('paper', [kind, value], lambda: self._not_found_is_none(lambda: self._paper(kind, value)))

    def citations(self, identifier, direction, limit=25):
        self._require('citations')
        if direction not in DIRECTIONS:
            raise ValueError('direction must be citations or references.')
        kind, value = self._identifier(identifier, 'citations')
        return self._cached('citations', [kind, value, direction, limit],
                            lambda: self._not_found_is_none(lambda: self._citations(kind, value, direction, limit)))

    def fulltext(self, identifier):
        self._require('fulltext')
        kind, value = self._identifier(identifier, 'fulltext')
        return self._cached('fulltext', [kind, value], lambda: self._not_found_is_none(lambda: self._fulltext(kind, value)))

    def bibtex(self, identifier):
        self._require('bibtex')
        kind, value = self._identifier(identifier, 'bibtex')
        return self._cached('bibtex', [kind, value], lambda: self._not_found_is_none(lambda: self._bibtex(kind, value)))

    def status(self, test=False):
        row = {'source': self.name, 'configured': False, 'required': self.required, 'state': 'unchecked',
               'detail': None}
        try:
            row['configured'] = self.configured()
        except credentials.CredentialStoreUnavailable:
            raise   # Settings reports it as `credential_store_unavailable` (credentials.md "Handshake")
        except ValueError as error:   # the Keychain could not be read; its message is safe to show
            return dict(row, state='error', detail=str(error))
        if self.required and not row['configured']:
            return dict(row, state='needs_key', detail='Add your %s in Settings → Research sources.'
                        % ('email' if self.credential_kind == 'email' else 'key'))
        if not test:
            return row
        try:
            kind, value = records.parse_id(self.test_id)
            self._not_found_is_none(lambda: self._paper(kind, value))
        except http.ResearchError as error:
            return dict(row, state='error', detail=str(error))
        except ValueError as error:
            return dict(row, state='error', detail=str(error))
        except (KeyError, IndexError, TypeError, AttributeError, ET.ParseError):
            return dict(row, state='error', detail='%s sent a reply Interspace could not read.' % self.title)
        return dict(row, state='ready')

    # Hooks a source implements for its capabilities ----------------------

    def _search(self, query, year_from, year_to, limit):
        raise self._unsupported('search')

    def _paper(self, kind, value):
        raise self._unsupported('paper')

    def _citations(self, kind, value, direction, limit):
        raise self._unsupported('citations')

    def _fulltext(self, kind, value):
        raise self._unsupported('fulltext')

    def _bibtex(self, kind, value):
        raise self._unsupported('bibtex')
