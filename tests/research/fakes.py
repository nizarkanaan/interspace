"""Fakes for the research source clients: a recorded-fixture HTTP transport, a controlled clock and credentials.

Nothing here touches the network. `FakeTransport` stands in for the urllib layer under `research.http.Http`,
so the allowlist, rate limiter and error mapping still run.
"""
import json
from pathlib import Path
import urllib.parse

FIXTURES = Path(__file__).resolve().parent / 'fixtures'


def fixture(source, name):
    """(status, headers, body bytes) of one recorded response."""
    data = json.loads((FIXTURES / source / (name + '.json')).read_text(encoding='utf-8'))
    if data.get('body') is not None:
        body = json.dumps(data['body']).encode('utf-8')
    else:
        body = (data.get('text') or '').encode('utf-8')
    return data['status'], dict(data.get('headers') or {}), body


def reply(status=200, body=None, headers=None, text=None):
    if text is not None:
        return status, dict(headers or {}), text.encode('utf-8')
    return status, dict(headers or {'content-type': 'application/json'}), json.dumps(body).encode('utf-8')


class Route:
    def __init__(self, host, path, params, response, times):
        self.host, self.path, self.params, self.response, self.times = host, path, params or {}, response, times

    def matches(self, url):
        parts = urllib.parse.urlsplit(url)
        if parts.hostname != self.host or urllib.parse.unquote(parts.path) != self.path:
            return False
        query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
        return all(query.get(key) == value for key, value in self.params.items())


class FakeTransport:
    """Answers each request from the first matching route; records every request it was sent."""

    def __init__(self):
        self.routes = []
        self.requests = []

    def add(self, host, path, response, *, params=None, times=None):
        """`response` is (status, headers, body), a fixture (source, name) pair or an exception to raise."""
        if isinstance(response, tuple) and len(response) == 2:
            response = fixture(*response)
        self.routes.append(Route(host, path, params, response, times))
        return self

    def send(self, method, url, headers, timeout_s):
        self.requests.append({'method': method, 'url': url, 'headers': dict(headers)})
        for route in self.routes:
            if route.times == 0 or not route.matches(url):
                continue
            if route.times is not None:
                route.times -= 1
            if isinstance(route.response, BaseException):
                raise route.response
            status, headers, body = route.response
            return status, dict(headers), body
        raise AssertionError('No fake route for %s' % url)

    def urls(self):
        return [request['url'] for request in self.requests]


class FakeClock:
    """A monotonic clock that only `sleep` advances."""

    def __init__(self, start=1000.0):
        self.now = start
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeCredentials:
    """The `research.credentials` shape: `get(account)` and `configured(account)`."""

    def __init__(self, secrets=None, *, broken=False):
        self.secrets = dict(secrets or {})
        self.broken = broken
        self.reads = []

    def get(self, account):
        self.reads.append(account)
        if self.broken:
            raise ValueError('Interspace cannot reach the Keychain. Update or restart the app.')
        return self.secrets.get(account)

    def configured(self, account):
        if self.broken:
            raise ValueError('Interspace cannot reach the Keychain. Update or restart the app.')
        return bool(self.secrets.get(account))


# Fake secrets: distinctive strings a test can search for anywhere they must never appear.
SECRETS = {
    'semantic_scholar': 'S2-KEY-fake-0123456789',
    'openalex': 'OA-KEY-fake-9876543210',
    'crossref_email': 'crossref.contact@example.invalid',
    'unpaywall_email': 'unpaywall.contact@example.invalid',
}
