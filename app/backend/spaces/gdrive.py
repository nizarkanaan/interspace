"""Google Drive and Docs connector (contract: connectors.md; route: docs/research/connector-auth.md).

Route: the Drive v3 and Docs v1 REST APIs with the user's own OAuth client
(a Desktop client in their own Google Cloud project), the
`https://www.googleapis.com/auth/drive.file` scope only, and PKCE with a
single-use redirect to `http://127.0.0.1:<port>/`.

Sign-in has two stages, both through the fixed step kinds:
1. No OAuth client stored yet: `begin_sign_in` returns a `token_entry` step
   and the user pastes the client JSON downloaded from Google Cloud
   (`{"installed": {"client_id", "client_secret", ...}}`). It is checked with
   one call to Google's token endpoint (a placeholder code: an unknown client
   is refused as `invalid_client`, a known one as `invalid_grant`) and stored
   in the Keychain item. `status()` says the client is missing until then.
2. With a client: `begin_sign_in` opens a loopback listener and returns a
   `browser` step; `complete_sign_in` waits for the one redirect, checks
   `state`, exchanges the code with the PKCE verifier and stores the tokens.

Route details the Connector API hides:
- `drive.file` sees only files Interspace created or the user opened or
  picked with it, so browsing shows that subset of My Drive.
- Kinds follow the MIME type: Google Docs are `doc`, folders are `folder`,
  everything else (including Sheets and Slides) is `file`. The
  `gdrive.file.*` actions accept any of the three kinds, because Drive
  renames and trashes them the same way.
- Docs are read as Drive's Markdown export (`text/markdown`), Sheets as CSV,
  Slides as plain text; text files are downloaded; anything else is
  `unavailable`. Exports are capped at 10 MB by Google. A continued read
  exports again and raises `Conflict` if the Drive `version` changed.
- `version` is the Drive file `version`. `gdrive.doc.replace_text` reads it,
  compares, then sends the edit: an edit landing between the two requests
  is not detected.
- Appended text is plain text in a new paragraph; Markdown is not rendered.
  A new doc made from Markdown is converted by Drive's import.
- `changes` follows Drive's change log (`changes.getStartPageToken`, then
  `changes.list`). Changes in shared drives are not listed.

Not verified against a live account (the user has no OAuth client yet):
the placeholder-code check of a client, and Drive's `text/markdown` export
and import for Google Docs.
"""
import base64
import binascii
import hashlib
import hmac
import http.server
import json
import re
import secrets
import socketserver
import threading
import time
import urllib.parse
import uuid

from spaces.base import (
    AuthExpired, Conflict, CredentialStoreUnavailable, Forbidden, InvalidRequest, InvalidResponse, NotFound,
    NotSignedIn, OutcomeUnknown, RateLimited, SignInCancelled, SignInExpired, SpaceError, Unavailable,
    check_idempotency_key, iso_time, journaled_write, make_ref, parse_ref, parse_time,
)

DRIVE = 'https://www.googleapis.com/drive/v3'
UPLOAD = 'https://www.googleapis.com/upload/drive/v3'
DOCS = 'https://docs.googleapis.com/v1'
AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
REVOKE_URL = 'https://oauth2.googleapis.com/revoke'
SCOPE = 'https://www.googleapis.com/auth/drive.file'
HELP_URL = 'https://developers.google.com/identity/protocols/oauth2/native-app'
CLIENT_PATTERN = r'^\s*\{[\s\S]{20,8000}\}\s*$'
NEEDS_CLIENT = ('Google Drive needs your own Google OAuth client first. Create a Desktop client in Google Cloud, '
                'then choose Connect and paste its JSON.')
CLIENT_SAVED = 'Your Google OAuth client is saved. Connect again to sign in with Google.'
# The connector's own capability names for drive.file (PROVISIONAL(0C-2)).
GRANTED = ['files:read', 'files:write']

FOLDER_MIME = 'application/vnd.google-apps.folder'
DOC_MIME = 'application/vnd.google-apps.document'
EXPORTS = {DOC_MIME: ('text/markdown', 'markdown'),
           'application/vnd.google-apps.spreadsheet': ('text/csv', 'text'),
           'application/vnd.google-apps.presentation': ('text/plain', 'text')}
TEXT_MIMES = ('application/json', 'application/xml', 'application/javascript', 'application/x-yaml',
              'application/yaml', 'application/x-sh', 'application/x-python', 'application/sql')
FILE_FIELDS = 'id,name,mimeType,parents,webViewLink,modifiedTime,version,size,trashed'
CHANGE_FIELDS = ('nextPageToken,newStartPageToken,'
                 'changes(changeType,fileId,removed,time,file(id,name,mimeType,trashed,createdTime,modifiedTime))')

SIGN_IN_S = 300
REFRESH_MARGIN_S = 60
MAX_DOWNLOAD = 10 * 1024 * 1024
MAX_TITLE = 300
MAX_CURSOR = 2048
MAX_TEXT = 100000
_ID = re.compile(r'[A-Za-z0-9_-]{1,200}\Z')
_CLIENT_ID = re.compile(r'[0-9]{6,32}-[a-z0-9]{8,64}\.apps\.googleusercontent\.com\Z')
_CLIENT_SECRET = re.compile(r'[A-Za-z0-9_-]{10,128}\Z')


def _schema(description, properties, required):
    return {'type': 'object', 'additionalProperties': False, 'description': description,
            'properties': properties, 'required': required}


ACTIONS = (
    {'name': 'gdrive.folder.create_doc', 'title': 'Create Google Doc', 'target_kind': 'folder',
     'effect': 'create', 'requires_version': False,
     'params_schema': _schema('Create a Google Doc in a Drive folder, optionally filled from Markdown.', {
         'title': {'type': 'string', 'minLength': 1, 'maxLength': MAX_TITLE},
         'markdown': {'type': 'string', 'maxLength': MAX_TEXT}}, ['title'])},
    {'name': 'gdrive.doc.append', 'title': 'Append to Google Doc', 'target_kind': 'doc',
     'effect': 'update', 'requires_version': False,
     'params_schema': _schema('Append plain text as a new paragraph at the end of a Google Doc.', {
         'text': {'type': 'string', 'minLength': 1, 'maxLength': MAX_TEXT}}, ['text'])},
    {'name': 'gdrive.doc.replace_text', 'title': 'Replace text in Google Doc', 'target_kind': 'doc',
     'effect': 'update', 'requires_version': True,
     'params_schema': _schema(
         'Replace every exact, case-sensitive match of `find` in a Google Doc with `replace`. '
         '`base_version` is the version from the last read.', {
             'find': {'type': 'string', 'minLength': 1, 'maxLength': 1000},
             'replace': {'type': 'string', 'maxLength': MAX_TEXT},
             'base_version': {'type': 'string', 'minLength': 1, 'maxLength': 64}}, ['find', 'replace', 'base_version'])},
    {'name': 'gdrive.file.rename', 'title': 'Rename in Google Drive', 'target_kind': 'file',
     'effect': 'update', 'requires_version': False,
     'params_schema': _schema('Rename a Google Drive file, Doc or folder.', {
         'name': {'type': 'string', 'minLength': 1, 'maxLength': MAX_TITLE}}, ['name'])},
    {'name': 'gdrive.file.trash', 'title': 'Move to Google Drive trash', 'target_kind': 'file',
     'effect': 'destructive', 'requires_version': False,
     'params_schema': _schema('Move a Google Drive file, Doc or folder to the Drive trash.', {}, [])},
)
_ACTIONS = {spec['name']: spec for spec in ACTIONS}


# Remote JSON validation ---------------------------------------------------------

def _bad():
    return InvalidResponse('Google Drive sent a reply Interspace could not read.')


def _obj(value):
    if not isinstance(value, dict):
        raise _bad()
    return value


def _field(value, key, kind):
    found = _obj(value).get(key)
    if not isinstance(found, kind) or isinstance(found, bool) and kind is not bool:
        raise _bad()
    return found


def _opt(value, key, kind):
    found = _obj(value).get(key)
    if found is None:
        return None
    if not isinstance(found, kind) or isinstance(found, bool) and kind is not bool:
        raise _bad()
    return found


def _remote_id(value, key='id'):
    ident = _field(value, key, str)
    if not _ID.match(ident):
        raise _bad()
    return ident


def _iso(t):
    """`iso_time` rounded to the millisecond (base.iso_time truncates float error: .123 became .122)."""
    ms = int(round(t * 1000))
    return iso_time(ms // 1000)[:-4] + '%03dZ' % (ms % 1000)


def _time(value, key):
    return _iso(parse_time(_field(value, key, str)))


def _truncate(text, limit):
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _kind(mime):
    return 'folder' if mime == FOLDER_MIME else 'doc' if mime == DOC_MIME else 'file'


def _size(file):
    size = _opt(file, 'size', str)
    if size is None:
        return None
    if not size.isdigit():
        raise _bad()
    return int(size)


def _resource(file):
    ident = _remote_id(file)
    mime = _field(file, 'mimeType', str)
    parents = _opt(file, 'parents', list) or []
    parent = parents[0] if parents and isinstance(parents[0], str) and _ID.match(parents[0]) else None
    url = _opt(file, 'webViewLink', str)
    meta = {'mime_type': _truncate(mime, 200)}
    size = _size(file)
    if size is not None:
        meta['size'] = size
    kind = _kind(mime)
    return {'ref': make_ref('gdrive', kind, ident), 'kind': kind,
            'title': _truncate(_field(file, 'name', str), MAX_TITLE),
            'parent': make_ref('gdrive', 'folder', parent) if parent else None,
            'url': url if url and url.startswith('https://') else None,
            'updated_at': _time(file, 'modifiedTime'), 'has_children': kind == 'folder', 'meta': meta}


def _file_list(reply):
    files = [_obj(item) for item in _field(reply, 'files', list)]
    return [_resource(item) for item in files], _opt(reply, 'nextPageToken', str)


def _quote(text):
    return "'" + text.replace('\\', '\\\\').replace("'", "\\'") + "'"


_KIND_CLAUSES = {
    'folder': "mimeType = '%s'" % FOLDER_MIME,
    'doc': "mimeType = '%s'" % DOC_MIME,
    'file': "(mimeType != '%s' and mimeType != '%s')" % (FOLDER_MIME, DOC_MIME),
}


# Parameter validation -------------------------------------------------------------

def _check_params(spec, params):
    if not isinstance(params, dict):
        raise InvalidRequest('Action parameters must be an object.')
    schema = spec['params_schema']
    unknown = set(params) - set(schema['properties'])
    if unknown:
        raise InvalidRequest('This action does not take: %s.' % ', '.join(sorted(map(str, unknown)))[:200])
    missing = [key for key in schema['required'] if key not in params]
    if missing:
        raise InvalidRequest('The %s is required.' % missing[0].replace('_', ' '))
    for key, rule in schema['properties'].items():
        if key in params:
            value = params[key]
            minimum, maximum = rule.get('minLength', 0), rule['maxLength']
            if not isinstance(value, str) or not minimum <= len(value) <= maximum:
                raise InvalidRequest('The %s must be text of %d to %d characters.' % (key.replace('_', ' '), minimum, maximum))


# Cursors ----------------------------------------------------------------------

def _encode_cursor(data):
    raw = json.dumps(data, separators=(',', ':'), sort_keys=True).encode('utf-8')
    cursor = base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
    if len(cursor) > MAX_CURSOR:
        raise InvalidResponse('Google Drive sent a page position Interspace cannot keep.')
    return cursor


def _decode_cursor(cursor, method, **expected):
    if cursor is None:
        return None
    try:
        if not isinstance(cursor, str) or len(cursor) > MAX_CURSOR:
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)).decode('utf-8'))
        if not isinstance(data, dict) or data.get('m') != method:
            raise ValueError
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise InvalidRequest('That page position is not valid. Start again from the first page.') from None
    for key, value in expected.items():
        if data.get(key) != value:
            raise InvalidRequest('That page position belongs to a different listing. Start again from the first page.')
    return data


def _check_limit(limit):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise InvalidRequest('The limit must be a whole number from 1 to 100.')
    return limit


# Loopback redirect listener ---------------------------------------------------------

class _Server(http.server.HTTPServer):
    def server_bind(self):
        # Skip HTTPServer's reverse-DNS lookup of the host name.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class _Handler(http.server.BaseHTTPRequestHandler):
    timeout = 5

    def do_GET(self):
        parts = urllib.parse.urlsplit(self.path)
        query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
        if parts.path != '/' or not ('code' in query or 'error' in query):
            self._reply(404, b'Not found.')
            return
        if self.server.result is None:
            self.server.result = query
        self._reply(200, b'Interspace received the Google sign-in. You can close this window.')

    def _reply(self, status, body):
        self.send_response(status)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass   # the request line carries the authorization code; never log it


class LoopbackListener:
    """A one-shot HTTP listener on 127.0.0.1 with a random port.

    It only receives the browser's redirect from Google (inbound, local);
    every outbound request still goes through `http`.
    """

    def __init__(self):
        self._server = _Server(('127.0.0.1', 0), _Handler)
        self._server.result = None
        self._lock = threading.Lock()
        self.port = self._server.server_address[1]

    def wait(self, timeout_s):
        """Serve at most one request; return the redirect's query, or None."""
        with self._lock:
            server = self._server
            if server is None:
                return None
            server.timeout = timeout_s
            server.handle_request()
            return server.result

    def close(self):
        server, self._server = self._server, None
        if server is not None:
            server.server_close()


# Connector ----------------------------------------------------------------------

class Connector:
    app = 'gdrive'
    kinds = ('folder', 'file', 'doc')
    max_read_chars = 200000

    def __init__(self, *, http, credentials, journal, clock=time.time, loopback=LoopbackListener):
        self.http = http
        self.credentials = credentials
        self.journal = journal
        self.clock = clock
        self._loopback = loopback
        self._refresh_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending = None   # the one browser sign-in in progress

    # Requests -----------------------------------------------------------------

    def _secret(self):
        secret = self.credentials.get()
        return secret if isinstance(secret, dict) else {}

    def _signed_in_secret(self):
        secret = self._secret()
        if not isinstance(secret.get('access_token'), str) or not secret['access_token']:
            raise NotSignedIn('Sign in to Google Drive first.')
        return secret

    def _session(self):
        secret = self._signed_in_secret()
        try:
            expires = parse_time(secret.get('expires_at'))
        except InvalidResponse:
            expires = None
        if expires is not None and expires <= self.clock() + REFRESH_MARGIN_S and secret.get('refresh_token'):
            secret = self._refresh(secret)
        return secret

    def _refresh(self, used):
        """Exchange the refresh token once and store the new access token."""
        with self._refresh_lock:
            current = self._signed_in_secret()
            if current.get('access_token') != used.get('access_token'):
                return current   # another call refreshed meanwhile
            refresh = current.get('refresh_token')
            if not isinstance(refresh, str) or not refresh:
                raise AuthExpired('Google no longer accepts the saved sign-in. Sign in to Google Drive again.')
            try:
                response = self.http.request('POST', TOKEN_URL, data={
                    'client_id': current.get('client_id'), 'client_secret': current.get('client_secret'),
                    'refresh_token': refresh, 'grant_type': 'refresh_token'})
            except Unavailable as error:
                error.request_sent = False   # a refresh never leaves a write unknown
                raise
            if response.status in (400, 401):
                raise AuthExpired('Google no longer accepts the saved sign-in. Sign in to Google Drive again.')
            try:
                token = self._token_reply(response)
            except Unavailable as error:
                error.request_sent = False
                raise
            updated = dict(current, access_token=token['access_token'], expires_at=token['expires_at'])
            for key in ('refresh_token', 'scope'):
                if token.get(key):
                    updated[key] = token[key]
            self.credentials.set(updated)
            return updated

    def _token_reply(self, response):
        if response.status != 200:
            self._check(response)
            raise _bad()
        reply = _obj(response.json())
        access = _field(reply, 'access_token', str)
        expires_in = _field(reply, 'expires_in', int)
        if not access or not 0 < expires_in <= 86400:
            raise _bad()
        return {'access_token': access, 'expires_at': _iso(self.clock() + expires_in),
                'refresh_token': _opt(reply, 'refresh_token', str), 'scope': _opt(reply, 'scope', str)}

    def _check(self, response, write=False):
        status = response.status
        if 200 <= status < 300:
            return response
        if status == 401:
            raise AuthExpired('Google no longer accepts the saved sign-in. Sign in to Google Drive again.')
        if status == 403:
            if self._rate_limited(response):
                raise RateLimited('Google Drive is limiting requests. Try again shortly.', retry_after_s=self._retry_after(response))
            raise Forbidden('Google Drive did not allow this. Interspace can use only files it created or you opened with it.')
        if status == 404:
            raise NotFound('Google Drive could not find this item, or Interspace has no access to it.')
        if status in (409, 412):
            raise Conflict('The item changed in Google Drive meanwhile. Reload it and try again.')
        if status == 429:
            raise RateLimited('Google Drive is limiting requests. Try again shortly.', retry_after_s=self._retry_after(response))
        if status in (400, 422):
            raise InvalidRequest('Google Drive rejected the request as invalid.')
        if status >= 500:
            if write:
                raise OutcomeUnknown('Google failed while making this change; it may or may not have happened.')
            raise Unavailable('Google Drive is unavailable right now. Try again later.')
        raise InvalidResponse('Google Drive sent an unexpected reply.')

    @staticmethod
    def _retry_after(response):
        retry = response.headers.get('retry-after', '')
        return int(retry) if isinstance(retry, str) and retry.isdigit() else None

    @staticmethod
    def _rate_limited(response):
        try:
            errors = response.json().get('error', {}).get('errors', [])
            return any(isinstance(e, dict) and e.get('reason') in ('rateLimitExceeded', 'userRateLimitExceeded')
                       for e in errors)
        except (InvalidResponse, AttributeError):
            return False

    def _call(self, method, url, *, params=None, body=None, data=None, headers=None, write=False, raw=False):
        """One request, refreshing the access token once on a 401."""
        secret = self._session()
        for attempt in (0, 1):
            sent = dict(headers or {}, Authorization='Bearer ' + secret['access_token'])
            response = self.http.request(method, url, headers=sent, params=params, json=body, data=data)
            if response.status != 401 or attempt:
                break
            secret = self._refresh(secret)
        self._check(response, write)
        return response if raw else _obj(response.json())

    def _read_step(self, method, url, **kwargs):
        """A read made as the first step of a write: its failures never leave a write unknown."""
        try:
            return self._call(method, url, **kwargs)
        except Unavailable as error:
            error.request_sent = False
            raise

    def _id(self, ref, kinds):
        _, kind, ident = parse_ref(ref, 'gdrive')
        if kind not in kinds or not _ID.match(ident):
            raise InvalidRequest('That Google Drive item reference is not valid here.')
        return kind, ident

    # Auth ---------------------------------------------------------------------

    def _status(self, state, account=None, detail=''):
        return {'v': 1, 'app': self.app, 'state': state, 'account': account,
                'granted': list(GRANTED) if state == 'signed_in' else [], 'detail': detail,
                'checked_at': _iso(self.clock())}

    def _signed_in(self, about):
        user = _field(about, 'user', dict)
        label = _opt(user, 'displayName', str) or 'Google Drive'
        return self._status('signed_in', {'label': _truncate(label, MAX_TITLE), 'id': _field(user, 'permissionId', str)})

    @staticmethod
    def _client(secret):
        client_id, client_secret = secret.get('client_id'), secret.get('client_secret')
        if isinstance(client_id, str) and isinstance(client_secret, str) and client_id and client_secret:
            return {'client_id': client_id, 'client_secret': client_secret}
        return None

    def status(self):
        try:
            secret = self._secret()
        except CredentialStoreUnavailable as error:
            return self._status('unavailable', detail=str(error))
        if self._client(secret) is None:
            return self._status('signed_out', detail=NEEDS_CLIENT)
        if not secret.get('access_token'):
            return self._status('signed_out')
        try:
            return self._signed_in(self._call('GET', DRIVE + '/about', params={'fields': 'user(displayName,permissionId)'}))
        except (AuthExpired, Forbidden, NotSignedIn):
            return self._status('expired', detail='Google no longer accepts the saved sign-in. Sign in to Google Drive again.')
        except SpaceError:
            return self._status('unavailable', detail='Google Drive cannot be reached right now. Check the connection and try again.')

    def begin_sign_in(self, params):
        client = self._client(self._secret())
        if client is None:
            return {'v': 1, 'app': self.app, 'kind': 'token_entry',
                    'label': 'Google OAuth client (paste the downloaded client JSON)',
                    'help_url': HELP_URL, 'pattern': CLIENT_PATTERN}
        try:
            listener = self._loopback()
        except OSError:
            raise Unavailable('Interspace could not open a local port for the Google sign-in. Try again.') from None
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode('ascii').rstrip('=')
        state = secrets.token_urlsafe(32)
        expires = self.clock() + SIGN_IN_S
        redirect = 'http://127.0.0.1:%d/' % listener.port
        pending = {'listener': listener, 'verifier': verifier, 'state': state, 'redirect': redirect, 'expires': expires}
        with self._pending_lock:
            previous, self._pending = self._pending, pending
        if previous is not None:
            previous['listener'].close()
        url = AUTH_URL + '?' + urllib.parse.urlencode({
            'client_id': client['client_id'], 'redirect_uri': redirect, 'response_type': 'code', 'scope': SCOPE,
            'code_challenge': challenge, 'code_challenge_method': 'S256', 'state': state,
            'access_type': 'offline', 'prompt': 'consent'})
        return {'v': 1, 'app': self.app, 'kind': 'browser', 'url': url, 'expires_at': _iso(expires)}

    def complete_sign_in(self, params, cancel):
        if not isinstance(params, dict):
            raise InvalidRequest('Sign-in details are not valid.')
        cancelled = lambda: cancel is not None and cancel.is_set()  # noqa: E731
        secret = self._secret()
        client = self._client(secret)
        if client is None:
            return self._save_client(params, cancelled)
        if params:
            raise InvalidRequest('Google sign-in continues in the browser.')
        with self._pending_lock:
            pending, self._pending = self._pending, None
        if pending is None:
            raise InvalidRequest('Start signing in to Google first.')
        try:
            reply = self._await_redirect(pending, cancelled)
            token = self._exchange(client, pending, reply)
            about = self._check(self.http.request(
                'GET', DRIVE + '/about', params={'fields': 'user(displayName,permissionId)'},
                headers={'Authorization': 'Bearer ' + token['access_token']}))
            status = self._signed_in(_obj(about.json()))
            if cancelled():
                raise SignInCancelled('Sign-in was cancelled.')
            stored = dict(client, access_token=token['access_token'], expires_at=token['expires_at'],
                          scope=token['scope'] or SCOPE, account_id=status['account']['id'])
            if token['refresh_token']:
                stored['refresh_token'] = token['refresh_token']
            self.credentials.set(stored)
            return status
        finally:
            pending['listener'].close()

    def _await_redirect(self, pending, cancelled):
        while True:
            if cancelled():
                raise SignInCancelled('Sign-in was cancelled.')
            if self.clock() >= pending['expires']:
                raise SignInExpired('The Google sign-in took too long. Start again.')
            reply = pending['listener'].wait(0.5)
            if reply is not None:
                break
        state = reply.get('state')
        if not isinstance(state, str) or not hmac.compare_digest(state, pending['state']):
            raise InvalidRequest('The Google sign-in reply did not match this sign-in. Start again.')
        if reply.get('error') == 'access_denied':
            raise SignInCancelled('Google sign-in was declined.')
        code = reply.get('code')
        if 'error' in reply or not isinstance(code, str) or not 0 < len(code) <= 2048:
            raise InvalidRequest('Google did not complete the sign-in. Start again.')
        return reply

    def _exchange(self, client, pending, reply):
        response = self.http.request('POST', TOKEN_URL, data=dict(
            client, code=reply['code'], redirect_uri=pending['redirect'], grant_type='authorization_code',
            code_verifier=pending['verifier']))
        if response.status in (400, 401):
            raise InvalidRequest('Google did not accept the sign-in. Start again.')
        return self._token_reply(response)

    def _save_client(self, params, cancelled):
        if set(params) != {'token'} or not isinstance(params['token'], str) or len(params['token']) > 8100:
            raise InvalidRequest('Paste the Google OAuth client JSON to continue.')
        try:
            data = json.loads(params['token'])
        except ValueError:
            data = None
        if isinstance(data, dict) and isinstance(data.get('installed'), dict):
            data = data['installed']
        client = self._client(data) if isinstance(data, dict) else None
        if (client is None or not _CLIENT_ID.match(client['client_id'])
                or not _CLIENT_SECRET.match(client['client_secret'])):
            raise InvalidRequest('That is not a Google Desktop OAuth client JSON. Download it again from Google Cloud.')
        if cancelled():
            raise SignInCancelled('Sign-in was cancelled.')
        # A placeholder code: Google answers invalid_grant for a known client and invalid_client otherwise.
        response = self.http.request('POST', TOKEN_URL, data=dict(
            client, code='interspace-client-check', redirect_uri='http://127.0.0.1/', grant_type='authorization_code'))
        try:
            error = response.json().get('error') if response.status in (400, 401) else None
        except (InvalidResponse, AttributeError):
            error = None
        if response.status == 401 or error in ('invalid_client', 'unauthorized_client'):
            raise InvalidRequest('Google did not recognise this OAuth client. Check it in Google Cloud and paste it again.')
        if response.status != 400:
            self._check(response)
        if cancelled():
            raise SignInCancelled('Sign-in was cancelled.')
        self.credentials.set(client)
        return self._status('signed_out', detail=CLIENT_SAVED)

    def sign_out(self):
        """Revoke the refresh token once (outcome ignored), then keep only the OAuth client."""
        secret = self._secret()
        token = secret.get('refresh_token') or secret.get('access_token')
        if isinstance(token, str) and token:
            try:
                self.http.request('POST', REVOKE_URL, data={'token': token})
            except SpaceError:
                pass
        client = self._client(secret)
        if client is None:
            self.credentials.delete()
        else:
            self.credentials.set(client)
        return self._status('signed_out')

    # Read ---------------------------------------------------------------------

    def _page(self, items, following):
        return {'v': 1, 'items': items, 'next_cursor': _encode_cursor(following) if following else None}

    def _list(self, query, limit, page_token, **extra):
        params = dict({'q': query, 'pageSize': limit, 'fields': 'nextPageToken,files(%s)' % FILE_FIELDS}, **extra)
        if page_token:
            params['pageToken'] = page_token
        return _file_list(self._call('GET', DRIVE + '/files', params=params))

    def browse(self, parent=None, cursor=None, limit=50):
        _check_limit(limit)
        state = _decode_cursor(cursor, 'browse', p=parent)
        ident = 'root' if parent is None else self._id(parent, ('folder',))[1]
        items, token = self._list("'%s' in parents and trashed = false" % ident, limit, state and state.get('c'),
                                  orderBy='folder,name_natural')
        if parent is not None:
            for item in items:
                item['parent'] = parent
        return self._page(items, {'m': 'browse', 'p': parent, 'c': token} if token else None)

    def search(self, query, kinds=None, cursor=None, limit=25):
        _check_limit(limit)
        if not isinstance(query, str) or not 1 <= len(query) <= 500:
            raise InvalidRequest('Search text must be 1 to 500 characters.')
        if kinds is not None:
            if not isinstance(kinds, (list, tuple)) or not kinds or not set(kinds) <= set(self.kinds):
                raise InvalidRequest('Google Drive can search folders, files and docs only.')
        wanted = [kind for kind in self.kinds if kinds is None or kind in kinds]
        state = _decode_cursor(cursor, 'search', q=query, k=wanted)
        text = _quote(query)
        clause = '(name contains %s or fullText contains %s) and trashed = false' % (text, text)
        if len(wanted) == 1:
            clause += ' and ' + _KIND_CLAUSES[wanted[0]]
        elif len(wanted) < len(self.kinds):
            clause += ' and (' + ' or '.join(_KIND_CLAUSES[kind] for kind in wanted) + ')'
        items, token = self._list(clause, limit, state and state.get('c'))
        return self._page(items, {'m': 'search', 'q': query, 'k': wanted, 'c': token} if token else None)

    def read(self, ref, cursor=None):
        kind, ident = self._id(ref, self.kinds)
        state = _decode_cursor(cursor, 'read', r=ref)
        offset = state.get('o') if state else 0
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise InvalidRequest('That page position is not valid. Start again from the first page.')
        file = self._call('GET', DRIVE + '/files/' + ident, params={'fields': FILE_FIELDS})
        resource = _resource(file)
        if resource['kind'] != kind:
            raise InvalidRequest('That reference does not match the item in Google Drive.')
        version = _opt(file, 'version', str)
        if state and state.get('ver') != version:
            raise Conflict('The item changed in Google Drive since the first part was read. Read it again from the start.')
        mime = resource['meta']['mime_type']
        meta = dict(resource['meta'])
        if kind == 'folder':
            if state:
                raise InvalidRequest('That page position is not valid. Start again from the first page.')
            text = json.dumps({'name': resource['title'], 'mime_type': mime, 'updated_at': resource['updated_at']},
                              ensure_ascii=False, sort_keys=True, indent=1)
            return self._content(resource, 'json', text, None, version, meta)
        size = _size(file)
        if mime in EXPORTS:
            export, fmt = EXPORTS[mime]
            fetch = lambda: self._call('GET', DRIVE + '/files/%s/export' % ident, params={'mimeType': export}, raw=True)  # noqa: E731
        elif mime.startswith('text/') or mime in TEXT_MIMES:
            fmt = 'text'
            fetch = lambda: self._call('GET', DRIVE + '/files/' + ident, params={'alt': 'media'}, raw=True)  # noqa: E731
        else:
            return self._unavailable(resource, version, meta, 'Interspace cannot show %s files as text.' % _truncate(mime, 120))
        if size is not None and size > MAX_DOWNLOAD:
            return self._unavailable(resource, version, meta, 'This file is larger than Interspace reads (10 MB).')
        try:
            text = fetch().body.decode('utf-8')
        except UnicodeDecodeError:
            return self._unavailable(resource, version, meta, 'This file is not UTF-8 text.')
        if offset > len(text):
            raise InvalidRequest('That page position is not valid. Start again from the first page.')
        end = offset + self.max_read_chars
        following = {'m': 'read', 'r': ref, 'o': end, 'ver': version} if end < len(text) else None
        return self._content(resource, fmt, text[offset:end], following, version, meta)

    def _unavailable(self, resource, version, meta, reason):
        return self._content(resource, 'unavailable', '', None, version, dict(meta, reason=reason))

    def _content(self, resource, fmt, text, following, version, meta):
        # `parent` (nearest parent ref or None) is the coordinator's additive field for scope `parents` chains.
        return {'v': 1, 'ref': resource['ref'], 'title': resource['title'], 'format': fmt, 'text': text,
                'truncated': following is not None, 'next_cursor': _encode_cursor(following) if following else None,
                'version': version, 'url': resource['url'], 'meta': meta, 'parent': resource['parent']}

    # Write --------------------------------------------------------------------

    def actions(self):
        return json.loads(json.dumps(ACTIONS))

    def write(self, action, ref, params, idempotency_key):
        spec = _ACTIONS.get(action)
        if spec is None:
            raise InvalidRequest('Google Drive has no such action.')
        kinds = self.kinds if spec['target_kind'] == 'file' else (spec['target_kind'],)
        _, ident = self._id(ref, kinds)
        _check_params(spec, params)
        check_idempotency_key(idempotency_key)
        self._signed_in_secret()
        perform = getattr(self, '_' + action.split('.', 1)[1].replace('.', '_'))
        return journaled_write(self.journal, key=idempotency_key, app=self.app, action=action, ref=ref, params=params,
                               perform=lambda: perform(ref, ident, params))

    def _result(self, action, ref, result_ref, url, version, summary):
        return {'v': 1, 'ok': True, 'action': action, 'ref': ref, 'result_ref': result_ref, 'url': url,
                'version': version, 'replayed': False, 'summary': _truncate(summary, 300)}

    def _folder_create_doc(self, ref, ident, params):
        """One request: a metadata-only create, or one multipart upload that Drive converts from Markdown."""
        metadata = {'name': params['title'], 'mimeType': DOC_MIME, 'parents': [ident]}
        fields = {'fields': FILE_FIELDS}
        if params.get('markdown'):
            boundary = 'interspace-' + uuid.uuid4().hex
            body = ('--{b}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n'
                    '--{b}\r\nContent-Type: text/markdown; charset=UTF-8\r\n\r\n{md}\r\n--{b}--\r\n').format(
                b=boundary, meta=json.dumps(metadata, ensure_ascii=False), md=params['markdown'])
            file = self._call('POST', UPLOAD + '/files', params=dict(fields, uploadType='multipart'),
                              data=body.encode('utf-8'), write=True,
                              headers={'Content-Type': 'multipart/related; boundary=' + boundary})
        else:
            file = self._call('POST', DRIVE + '/files', params=fields, body=metadata, write=True)
        created = _resource(file)
        return self._result('gdrive.folder.create_doc', ref, created['ref'], created['url'], _opt(file, 'version', str),
                            'Created Google Doc "%s".' % _truncate(params['title'], 200))

    def _batch_update(self, ident, requests):
        reply = self._call('POST', DOCS + '/documents/%s:batchUpdate' % ident, body={'requests': requests}, write=True)
        _remote_id(reply, 'documentId')
        return reply

    def _doc_append(self, ref, ident, params):
        self._batch_update(ident, [{'insertText': {'endOfSegmentLocation': {}, 'text': '\n' + params['text']}}])
        return self._result('gdrive.doc.append', ref, ref, None, None, 'Appended text to the document.')

    def _doc_replace_text(self, ref, ident, params):
        """Two steps: read the Drive version, then edit. Stopping after the read is safe."""
        current = _opt(self._read_step('GET', DRIVE + '/files/' + ident, params={'fields': 'version'}), 'version', str)
        if current != params['base_version']:
            raise Conflict('The document changed in Google Drive since it was read. Read it again before editing.')
        reply = self._batch_update(ident, [{'replaceAllText': {
            'containsText': {'text': params['find'], 'matchCase': True}, 'replaceText': params['replace']}}])
        replies = _opt(reply, 'replies', list) or [{}]
        changed = _opt(_obj(replies[0]).get('replaceAllText') or {}, 'occurrencesChanged', int) or 0
        summary = ('Found no matches; nothing changed.' if not changed
                   else 'Replaced %d match%s.' % (changed, '' if changed == 1 else 'es'))
        return self._result('gdrive.doc.replace_text', ref, ref, None, None, summary)

    def _file_rename(self, ref, ident, params):
        file = self._call('PATCH', DRIVE + '/files/' + ident, params={'fields': FILE_FIELDS},
                          body={'name': params['name']}, write=True)
        renamed = _resource(file)
        return self._result('gdrive.file.rename', ref, ref, renamed['url'], _opt(file, 'version', str),
                            'Renamed to "%s".' % _truncate(params['name'], 200))

    def _file_trash(self, ref, ident, params):
        file = self._call('PATCH', DRIVE + '/files/' + ident, params={'fields': FILE_FIELDS},
                          body={'trashed': True}, write=True)
        trashed = _resource(file)
        return self._result('gdrive.file.trash', ref, ref, trashed['url'], _opt(file, 'version', str),
                            'Moved "%s" to the Google Drive trash.' % _truncate(trashed['title'], 200))

    # Changes ------------------------------------------------------------------

    def changes(self, cursor=None, limit=100):
        """Follow Drive's change log. The cursor keeps the page token and the
        time of the last complete poll, which tells `created` from `updated`."""
        _check_limit(limit)
        if cursor is None:
            token = _field(self._call('GET', DRIVE + '/changes/startPageToken'), 'startPageToken', str)
            return {'v': 1, 'items': [], 'complete': True,
                    'cursor': _encode_cursor({'m': 'changes', 't': token, 'since': _iso(self.clock())})}
        state = _decode_cursor(cursor, 'changes')
        try:
            if not isinstance(state['t'], str) or not state['t']:
                raise TypeError
            since = parse_time(state['since'])
        except (KeyError, TypeError, InvalidResponse):
            raise InvalidRequest('That change position is not valid.') from None
        reply = self._call('GET', DRIVE + '/changes', params={
            'pageToken': state['t'], 'pageSize': limit, 'includeRemoved': 'true', 'spaces': 'drive',
            'fields': CHANGE_FIELDS})
        items = []
        for change in _field(reply, 'changes', list):
            if _obj(change).get('changeType', 'file') != 'file':
                continue
            at = _time(change, 'time')
            file = _opt(change, 'file', dict)
            if change.get('removed') is True or file is None:
                items.append({'ref': make_ref('gdrive', 'file', _remote_id(change, 'fileId')),
                              'change': 'deleted', 'at': at, 'title': ''})
                continue
            kind = _kind(_field(file, 'mimeType', str))
            created = _opt(file, 'createdTime', str)
            if file.get('trashed') is True:
                verb = 'deleted'
            elif created and parse_time(created) >= since:
                verb = 'created'
            else:
                verb = 'updated'
            items.append({'ref': make_ref('gdrive', kind, _remote_id(file)), 'change': verb, 'at': at,
                          'title': _truncate(_field(file, 'name', str), MAX_TITLE)})
        following = _opt(reply, 'nextPageToken', str)
        if following:
            return {'v': 1, 'items': items, 'complete': False,
                    'cursor': _encode_cursor({'m': 'changes', 't': following, 'since': state['since']})}
        fresh = _field(reply, 'newStartPageToken', str)
        return {'v': 1, 'items': items, 'complete': True,
                'cursor': _encode_cursor({'m': 'changes', 't': fresh, 'since': _iso(self.clock())})}
