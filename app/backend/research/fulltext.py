"""Full text for the claim check (docs/superpowers/specs/2026-11-20-claim-fulltext-design.md).

Two ways in. arXiv papers come from arxiv.org through the arXiv source's fixed host. Any other open-access copy comes
from its `oa_url`, which may be on any publisher host, so it is fetched only after the scope's `fulltext` permission
allows it and only from public addresses: every address of every hop is checked, and the connection goes to the
checked address. PDFs are read by macOS PDFKit over the native bridge; HTML by the standard library.
"""
import hashlib
import html.parser
import http.client
import ipaddress
import re
import socket
import ssl
import time
import urllib.parse

MAX_BYTES = 10 * 1024 * 1024
MAX_TEXT = 2 * 1024 * 1024
MAX_REDIRECTS = 5
TIMEOUT_S = 30
MAX_REQUEST_S = 60
USER_AGENT = 'Interspace/0.1.0 (research full text)'
PASSAGE = 1200
PASSAGES = 3
STOP = set('a an the of in on for to and or with by from at as is are was were be been that this these those it its '
           'we our their they than then which who whom whose into over under between among not no can may might '
           'also such more most less least very about after before during while within without per via'.split())


class FullTextError(Exception):
    """A full text that could not be fetched or read. The message is Interspace's own, never upstream text."""


# -- public-address downloads -------------------------------------------------------------------------------------

def _public_addresses(host, port, resolve=socket.getaddrinfo):
    try:
        infos = resolve(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        raise FullTextError('The open-access host could not be found.') from None
    addresses = []
    for info in infos:
        address = info[4][0]
        try:
            parsed = ipaddress.ip_address(address.split('%', 1)[0])
        except ValueError:
            raise FullTextError('The open-access host has an address Interspace cannot check.') from None
        if not parsed.is_global or parsed.is_multicast:
            raise FullTextError('The open-access link points to a local or private address, so it was not opened.')
        addresses.append((info[0], address))
    if not addresses:
        raise FullTextError('The open-access host could not be found.')
    return addresses


class _PinnedHTTPS(http.client.HTTPSConnection):
    """An HTTPS connection to one checked address, verified against the hostname."""

    def __init__(self, host, address, family, **kwargs):
        super().__init__(host, 443, timeout=TIMEOUT_S, context=ssl.create_default_context(), **kwargs)
        self._address, self._family = address, family

    def connect(self):
        sock = socket.socket(self._family, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT_S)
        sock.connect((self._address, 443) if self._family == socket.AF_INET else (self._address, 443, 0, 0))
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _check(url):
    parts = urllib.parse.urlsplit(url) if isinstance(url, str) else None
    if parts is None or parts.scheme != 'https' or not parts.hostname or parts.username or parts.password \
            or parts.port not in (None, 443):
        raise FullTextError('Only https open-access links are opened.')
    return parts


def fetch_public(url, *, resolve=socket.getaddrinfo, connection=_PinnedHTTPS, clock=time.monotonic):
    """GET an open-access copy from a public host. Returns (body, content_type)."""
    started = clock()
    for _ in range(MAX_REDIRECTS + 1):
        parts = _check(url)
        family, address = _public_addresses(parts.hostname, 443, resolve)[0]
        conn = connection(parts.hostname, address, family)
        try:
            path = urllib.parse.urlunsplit(('', '', parts.path or '/', parts.query, ''))
            conn.request('GET', path, headers={'User-Agent': USER_AGENT, 'Accept': 'application/pdf, text/html;q=0.8'})
            reply = conn.getresponse()
            if reply.status in (301, 302, 303, 307, 308):
                location = reply.getheader('Location')
                if not location:
                    raise FullTextError('The open-access link redirected nowhere.')
                url = urllib.parse.urljoin(url, location)
                continue
            if reply.status != 200:
                raise FullTextError('The open-access copy was not available (HTTP %d).' % reply.status)
            kind = (reply.getheader('Content-Type') or '').split(';', 1)[0].strip().lower()
            if kind not in ('application/pdf', 'text/html', 'application/xhtml+xml', 'application/octet-stream'):
                raise FullTextError('The open-access copy is not a PDF or a web page.')
            body = bytearray()
            while True:
                chunk = reply.read(64 * 1024)
                if not chunk:
                    break
                body += chunk
                if len(body) > MAX_BYTES:
                    raise FullTextError('The open-access copy is larger than 10 MB.')
                if clock() - started > MAX_REQUEST_S:
                    raise FullTextError('The open-access copy took too long to download.')
            if kind == 'application/octet-stream':
                kind = 'application/pdf' if bytes(body[:5]) == b'%PDF-' else kind
            return bytes(body), kind
        except FullTextError:
            raise
        except (OSError, http.client.HTTPException, ssl.SSLError, ValueError):
            raise FullTextError('The open-access copy could not be downloaded.') from None
        finally:
            conn.close()
    raise FullTextError('The open-access link redirected too many times.')


# -- text ---------------------------------------------------------------------------------------------------------

class _Text(html.parser.HTMLParser):
    SKIP = {'script', 'style', 'nav', 'header', 'footer', 'noscript', 'svg', 'math', 'button', 'form'}
    BLOCK = {'p', 'div', 'section', 'article', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br', 'tr', 'figcaption',
             'blockquote', 'dd', 'dt'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_text(body):
    parser = _Text()
    try:
        parser.feed(body.decode('utf-8', 'replace'))
    except Exception:
        raise FullTextError('The web page could not be read.') from None
    text = re.sub(r'[ \t\r\f\v]+', ' ', ''.join(parser.parts))
    return re.sub(r'\n\s*\n+', '\n\n', text).strip()[:MAX_TEXT]


def clean(text):
    text = re.sub(r'-\n(?=[a-z])', '', str(text or ''))  # Words broken across PDF lines.
    return re.sub(r'[ \t]+', ' ', text).strip()[:MAX_TEXT]


def _words(text):
    return [w for w in re.findall(r'[a-z0-9]+', text.lower()) if len(w) > 2 and w not in STOP]


def passages(text, sentence, k=PASSAGES, size=PASSAGE):
    """The k passages of about `size` characters that share the most content words with `sentence`, in text order."""
    text = clean(text)
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n|\n', text) if p.strip()]
    chunks, current = [], ''
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) > size:
            chunks.append(current)
            current = ''
        current = (current + ' ' + paragraph).strip()
        while len(current) > size * 1.5:
            chunks.append(current[:size])
            current = current[size:]
    if current:
        chunks.append(current)
    wanted = set(_words(sentence))
    if not wanted:
        return []
    scored = [(len(wanted & set(_words(chunk))), i) for i, chunk in enumerate(chunks)]
    best = sorted([s for s in scored if s[0] > 0], key=lambda s: (-s[0], s[1]))[:k]
    return [chunks[i] for _, i in sorted(best, key=lambda s: s[1])]


def cache_key(paper):
    basis = (paper or {}).get('doi') or (paper or {}).get('arxiv_id') or (paper or {}).get('title') or ''
    return hashlib.sha256(str(basis).lower().encode('utf-8')).hexdigest()[:32]


# -- one paper's text ---------------------------------------------------------------------------------------------

def _pdf_text(bridge, folder, body):
    """PDF bytes to text through PDFKit on the native bridge; None without it. The file is removed afterwards."""
    reader = getattr(bridge, 'pdf_text', None)
    if not callable(reader):
        return None
    path = folder / ('.download-%s.pdf' % hashlib.sha256(body).hexdigest()[:16])
    path.write_bytes(body)
    try:
        reply = reader(str(path))
    finally:
        try:
            path.unlink()
        except OSError:
            pass
    text = reply.get('text') if isinstance(reply, dict) and reply.get('ok') else None
    return clean(text) if isinstance(text, str) and text.strip() else None


def text_for(app, call, paper, folder, *, fetch=fetch_public):
    """The full text of `paper` for the claim check, or None. Cached per task; each download is authorized first:
    arXiv as the `arxiv` source, any other open-access host as `fulltext`. Returns (text, error)."""
    folder.mkdir(parents=True, exist_ok=True)
    cached = folder / (cache_key(paper) + '.txt')
    if cached.is_file() and not cached.is_symlink():
        return cached.read_text(encoding='utf-8'), None
    text, error = None, None
    arxiv = paper.get('arxiv_id') if isinstance(paper.get('arxiv_id'), str) else None
    web = getattr(app, 'http', None)
    if arxiv and web is not None and call.authorize({'category': 'research', 'source': 'arxiv', 'tool': call.tool})['decision'] == 'allow':
        for url, kind in (('https://arxiv.org/html/' + arxiv, 'html'), ('https://arxiv.org/pdf/' + arxiv, 'pdf')):
            try:
                call.note_call('arxiv')
                body = web.get('arxiv', url).body
                text = html_text(body) if kind == 'html' else _pdf_text(getattr(app, 'bridge', None), folder, body)
                if text and len(text) > 2000:
                    break
                text = None
            except Exception:
                text = None
    oa = paper.get('oa_url') if isinstance(paper.get('oa_url'), str) else None
    if not text and oa:
        decision = call.authorize({'category': 'research', 'source': 'fulltext', 'tool': call.tool})
        if decision.get('decision') != 'allow':
            return None, 'Open-access full text is not allowed by this task\'s scope.'
        try:
            body, kind = fetch(oa)
            call.note_call('fulltext')
            text = html_text(body) if kind != 'application/pdf' else _pdf_text(getattr(app, 'bridge', None), folder, body)
        except FullTextError as failure:
            return None, str(failure)
    if not text:
        return None, error or 'No open-access full text was found.'
    cached.write_text(text, encoding='utf-8')
    return text, None
