"""The only network client for research sources (research/tools.md, README "Network only from source clients").

https only, to each source's fixed hosts; no proxies; same-host redirects only; a 10 MiB response cap; a
generic User-Agent; one token bucket and one connection limit per source; bounded 429 handling. Upstream
error bodies never leave this module: every error carries only its code and a fixed Interspace message.
The HTTP client and error types are restored from the deleted `spaces/base.py` (fe65e32^).
"""
import contextvars
import http.client
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = '0.1.0'  # CFBundleShortVersionString in scripts/build-macos-app.py
USER_AGENT = 'Interspace/%s (research)' % VERSION
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
TIMEOUT_S = 30
MAX_RETRY_AFTER_S = 10        # honour a longer Retry-After only by failing with it
NO_RETRY_AFTER_BACKOFF_S = (2.0, 4.0)   # Semantic Scholar sends 429 without Retry-After (spike-0b)

TITLES = {
    'semantic_scholar': 'Semantic Scholar',
    'openalex': 'OpenAlex',
    'arxiv': 'arXiv',
    'crossref': 'Crossref',
    'unpaywall': 'Unpaywall',
}

# The fixed host allowlist per source. Source modules expose the same tuple as `Source.hosts`.
HOSTS = {
    'semantic_scholar': ('api.semanticscholar.org',),
    'openalex': ('api.openalex.org',),
    'arxiv': ('export.arxiv.org', 'arxiv.org'),
    'crossref': ('api.crossref.org',),
    'unpaywall': ('api.unpaywall.org',),
}

# Requests per second per bucket (spike-0b.md). Crossref list queries use their own, slower pool.
RATES = {
    'semantic_scholar': 1.0,
    'openalex': 5.0,
    'arxiv': 1 / 3.0,
    'crossref': 5.0,
    'crossref.list': 1.0,
    'unpaywall': 5.0,
}

# Requests in flight at once per source. arXiv and Crossref (public pool) allow one connection.
CONCURRENCY = {
    'semantic_scholar': 1,
    'openalex': 2,
    'arxiv': 1,
    'crossref': 1,
    'unpaywall': 2,
}


# Metering -------------------------------------------------------------------

# The tool call being served, if any: `meter(kind, source)` with kind 'calls' (a request was sent) or 'cached' (the
# response cache answered instead). `research.dispatch` sets it, so each task counts its own calls.
METER = contextvars.ContextVar('research_meter', default=None)


def note(kind, source):
    meter = METER.get()
    if meter is not None:
        meter(kind, source)


# Errors ---------------------------------------------------------------------

class ResearchError(ValueError):
    """A source call failed. The message is fixed Interspace text, safe for agents and the UI."""
    code = 'research_error'

    def __init__(self, message, *, retry_after_s=None):
        super().__init__(message)
        self.retry_after_s = retry_after_s


class NotConfigured(ResearchError):
    code = 'not_configured'


class RateLimited(ResearchError):
    code = 'rate_limited'       # retry_after_s set when the source said


class Unavailable(ResearchError):
    code = 'unavailable'        # network failure or 5xx


class BadResponse(ResearchError):
    code = 'bad_response'       # unreadable or unexpected reply, refused redirect, oversize body


class NotFound(ResearchError):
    code = 'not_found'


class BadRequest(ResearchError):
    code = 'bad_request'        # Interspace refused to send the request (address outside the allowlist)


ERRORS = {cls.code: cls for cls in (NotConfigured, RateLimited, Unavailable, BadResponse, NotFound, BadRequest)}


def _title(source):
    return TITLES.get(source, 'The research source')


def not_configured(source):
    return NotConfigured('%s needs a key or email in Settings → Research sources.' % _title(source))


# Responses ------------------------------------------------------------------

class Response:
    def __init__(self, source, status, headers, body):
        self.source = source
        self.status = status
        self.headers = {str(k).lower(): v for k, v in dict(headers or {}).items()}
        self.body = body

    def json(self):
        import json
        try:
            return json.loads(self.body.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            raise BadResponse('%s sent a reply Interspace could not read.' % _title(self.source)) from None

    def text(self):
        return self.body.decode('utf-8', errors='replace')


# Transport ------------------------------------------------------------------

class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to the same scheme, host and port."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = urllib.parse.urlsplit(req.full_url)
        new = urllib.parse.urlsplit(newurl)
        if (old.scheme, old.hostname, old.port) != (new.scheme, new.hostname, new.port):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _read_capped(stream):
    body = stream.read(MAX_RESPONSE_BYTES + 1) if stream is not None else b''
    if len(body) > MAX_RESPONSE_BYTES:
        raise BadResponse('The research source sent a reply larger than Interspace accepts.')
    return body


class UrllibTransport:
    """The real network layer. `send` returns (status, headers, body); a refused redirect returns its 3xx."""

    def __init__(self):
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _SameHostRedirect())

    def send(self, method, url, headers, timeout_s):
        request = urllib.request.Request(url, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=timeout_s) as reply:
                return reply.getcode(), dict(reply.headers.items()), _read_capped(reply)
        except urllib.error.HTTPError as error:
            try:
                return error.code, dict(error.headers.items()) if error.headers else {}, _read_capped(error)
            finally:
                error.close()


# Rate limiting --------------------------------------------------------------

class TokenBucket:
    """At most `rate` requests per second, with no burst: each caller reserves the next free slot."""

    def __init__(self, rate, *, clock=time.monotonic, sleep=time.sleep):
        self.interval = 1.0 / rate
        self._clock = clock
        self._sleep = sleep
        self._next = None
        self._lock = threading.Lock()

    def acquire(self):
        with self._lock:
            now = self._clock()
            start = now if self._next is None else max(now, self._next)
            self._next = start + self.interval
        if start > now:
            self._sleep(start - now)


def _retry_after(headers):
    value = headers.get('retry-after')
    try:
        seconds = float(str(value).strip())
    except (TypeError, ValueError):
        return None   # missing, or an HTTP date: treat as missing
    return seconds if seconds >= 0 else None


# Client ---------------------------------------------------------------------

class Http:
    """GET-only research client. `transport.send(method, url, headers, timeout_s)` does the I/O."""

    def __init__(self, transport=None, *, clock=time.monotonic, sleep=time.sleep):
        self._transport = transport or UrllibTransport()
        self._clock = clock
        self._sleep = sleep
        self._buckets = {name: TokenBucket(rate, clock=clock, sleep=sleep) for name, rate in RATES.items()}
        self._slots = {name: threading.BoundedSemaphore(n) for name, n in CONCURRENCY.items()}
        self._lock = threading.Lock()
        self.calls = {}   # requests sent per source, for research_usage

    def _check_url(self, source, url):
        parts = urllib.parse.urlsplit(url) if isinstance(url, str) else None
        if (source not in HOSTS or parts is None or parts.scheme != 'https' or parts.hostname not in HOSTS[source]
                or parts.port not in (None, 443) or parts.username or parts.password):
            raise BadRequest('Interspace does not send research requests to that address.')
        return parts

    def get(self, source, url, *, params=None, headers=None, pool=None, timeout_s=TIMEOUT_S):
        """One GET to `source`'s allowlist. `pool` picks a second bucket (Crossref 'list'). Returns a 2xx Response."""
        parts = self._check_url(source, url)
        if params:
            query = urllib.parse.urlencode([(k, v) for k, v in params.items() if v is not None], doseq=True)
            url = urllib.parse.urlunsplit(parts._replace(query=(parts.query + '&' if parts.query else '') + query))
        sent = {str(k): str(v) for k, v in (headers or {}).items() if str(k).lower() != 'user-agent'}
        sent['User-Agent'] = USER_AGENT
        bucket = self._buckets[source + '.' + pool if pool else source]
        backoff = list(NO_RETRY_AFTER_BACKOFF_S)
        retried_after_header = False
        while True:
            status, reply_headers, body = self._send(source, bucket, url, sent, timeout_s)
            response = Response(source, status, reply_headers, body)
            if status != 429:
                return self._check_status(response)
            wait = _retry_after(response.headers)
            if wait is not None:
                if wait > MAX_RETRY_AFTER_S or retried_after_header:
                    raise RateLimited('%s is limiting requests. Try again later.' % _title(source),
                                      retry_after_s=int(wait))
                retried_after_header = True
                self._sleep(wait)
                continue
            if not backoff:
                raise RateLimited('%s is limiting requests. Try again later, or add a key in Settings.'
                                  % _title(source))
            self._sleep(backoff.pop(0))

    def _send(self, source, bucket, url, headers, timeout_s):
        with self._slots[source]:
            bucket.acquire()
            with self._lock:
                self.calls[source] = self.calls.get(source, 0) + 1
            note('calls', source)
            try:
                return self._transport.send('GET', url, headers, timeout_s)
            except ResearchError:
                raise
            except (urllib.error.URLError, OSError, http.client.HTTPException, socket.timeout, ssl.SSLError):
                raise Unavailable('Could not reach %s. Check the connection and try again.' % _title(source)) from None

    def _check_status(self, response):
        status, title = response.status, _title(response.source)
        if 200 <= status < 300:
            return response
        if status == 404:
            raise NotFound('%s has no record of that.' % title)
        if status in (401, 403):
            raise NotConfigured('%s refused the request. Check the key or email in Settings → Research sources.'
                                % title)
        if 300 <= status < 400:
            raise BadResponse('%s redirected to an address Interspace does not follow.' % title)
        if status >= 500:
            raise Unavailable('%s is not responding. Try again later.' % title)
        raise BadResponse('%s could not answer that request.' % title)
