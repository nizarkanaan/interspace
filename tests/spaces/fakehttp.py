"""Fake-HTTP harness for connector tests (contract: connectors.md).

No network, Keychain or real accounts: requests are matched in order against
scripted expectations, credentials live in memory.
"""
import json as jsonlib
import threading
import urllib.parse

from spaces.base import MemoryJournal, Response, Unavailable  # noqa: F401  (MemoryJournal is re-exported)

_RAISES = ('connection', 'timeout_after_send')


def _split(url):
    parts = urllib.parse.urlsplit(url)
    bare = urllib.parse.urlunsplit(parts._replace(query='', fragment=''))
    return bare, dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))


def _subset_mismatch(expected, actual, path):
    """Return a description of the first place `expected` is not a subset of `actual`."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return '%s: expected an object, got %r' % (path or 'value', actual)
        for key, value in expected.items():
            if key not in actual:
                return '%s.%s: missing' % (path, key)
            found = _subset_mismatch(value, actual[key], '%s.%s' % (path, key))
            if found:
                return found
        return None
    if expected != actual:
        return '%s: expected %r, got %r' % (path or 'value', expected, actual)
    return None


class FakeHttp:
    def __init__(self):
        self._expected = []
        self._lock = threading.Lock()
        self.calls = []

    def expect(self, method, url, *, status=200, json=None, body=b'', headers=None,
               match_params=None, match_json=None, match_headers=None, raises=None):
        if raises is not None and raises not in _RAISES:
            raise ValueError('raises must be one of %s' % (_RAISES,))
        if json is not None:
            body = jsonlib.dumps(json).encode('utf-8')
        self._expected.append({'method': method, 'url': url, 'status': status, 'body': body,
                               'headers': dict(headers or {}), 'match_params': match_params,
                               'match_json': match_json, 'match_headers': match_headers, 'raises': raises})

    def request(self, method, url, *, headers=None, params=None, json=None, data=None, timeout_s=30):
        bare, query = _split(url)
        # Values compare as they would appear in a query string.
        all_params = dict(query, **{str(k): str(v) for k, v in (params or {}).items()})
        call = {'method': method, 'url': bare, 'params': all_params, 'headers': dict(headers or {}),
                'json': json, 'data': data, 'timeout_s': timeout_s}
        with self._lock:
            self.calls.append(call)
            if not self._expected:
                raise AssertionError('Unexpected request: %s %s' % (method, bare))
            expected = self._expected.pop(0)
        problems = []
        if (expected['method'], expected['url']) != (method, bare):
            problems.append('expected %s %s, got %s %s' % (expected['method'], expected['url'], method, bare))
        lower_headers = {k.lower(): v for k, v in call['headers'].items()}
        for label, wanted, actual in (
                ('params', expected['match_params'], all_params),
                ('json', expected['match_json'], json),
                ('headers', {k.lower(): v for k, v in (expected['match_headers'] or {}).items()} or None, lower_headers)):
            if wanted is not None:
                found = _subset_mismatch(wanted, actual, label)
                if found:
                    problems.append(found)
        if problems:
            raise AssertionError('Request did not match the next expectation: ' + '; '.join(problems))
        if expected['raises']:
            error = Unavailable('Could not reach the app. Check the connection and try again.')
            error.request_sent = expected['raises'] == 'timeout_after_send'
            raise error
        return Response(expected['status'], expected['headers'], expected['body'])

    def assert_done(self):
        if self._expected:
            left = ', '.join('%s %s' % (e['method'], e['url']) for e in self._expected)
            raise AssertionError('Expected requests were not made: ' + left)


class MemoryCredentials:
    def __init__(self, secret=None):
        self._secret = dict(secret) if secret is not None else None
        self._lock = threading.Lock()

    def get(self):
        with self._lock:
            return dict(self._secret) if self._secret is not None else None

    def set(self, secret):
        with self._lock:
            self._secret = dict(secret)

    def delete(self):
        with self._lock:
            self._secret = None
