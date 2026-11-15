"""Zotero connector (contract: connectors.md; route: docs/research/connector-auth.md).

Routes:
- Reads use Zotero's local API on `http://127.0.0.1:23119/api` (API v3). Zotero
  must be running with "Allow other applications on this computer to
  communicate with Zotero" turned on. Reads need no credential. When Zotero is
  closed or the local API is off, status is `unavailable` and reads raise
  `Unavailable` with a sentence saying what to do.
- Writes use the free Zotero web API (`api.zotero.org`) with a web API key the
  user pastes at sign-in (`write_key`), stored only in the Keychain. Without a
  key Zotero is read-only and every write raises `Unsupported`. This is the
  `PROVISIONAL(0C-4)` assumption; `_write_route` is the one place to change if
  writes move to Zotero 10's local write API. A web write reaches the Zotero app
  only after Zotero syncs.

Sign-in is `local_check`: it checks the local API once and, when a write key
is given, verifies it once with `GET /keys/current`. The Keychain item holds
`{"kind": "zotero"}` plus, with a key, `write_key`, `user_id` and `username`.
Zotero keys never expire, so status never reports `expired`; a revoked key
surfaces as `Forbidden` on the next write. Sign-out deletes the Keychain item;
the key itself is revoked by the user at zotero.org/settings/keys.

Route details the Connector API hides:
- IDs are library paths: `users/0` is the user's own library (the local API's
  name for it), `groups/<id>` a group library, `<library>/collections/<KEY>`
  a collection and `<library>/items/<KEY>` an item, note or attachment. Writes
  map `users/0` to `users/<user ID of the key>`.
- Notes are items (kind `item`); attachments have kind `attachment`.
- Browsing a library or collection lists its subcollections first, then its
  top-level items, newest edit first. Browsing an item lists its notes and
  attachments. Collections and My Library have no edit time (`updated_at` null).
- Search covers My Library only, with Zotero's title, creator and year search.
  Collections and libraries are not searchable.
- A resource's `parent` is its parent item, else its first collection, else its
  library; listings use the browsed parent.
- Reading an item returns its fields as JSON, a note its text, an attachment
  the text Zotero indexed (`unavailable` when there is none).
- `changes` polls My Library's items with `since=<library version>`, including
  trashed items (reported as `deleted`). Group libraries, collections and items
  removed from the trash for good are not reported.
"""
import base64
import binascii
import hashlib
import html
import json
import re
import time
from html.parser import HTMLParser

from spaces.base import (
    AuthExpired, Conflict, CredentialStoreUnavailable, Forbidden, InvalidRequest, InvalidResponse, NotFound,
    NotSignedIn, OutcomeUnknown, RateLimited, SignInCancelled, SpaceError, Unavailable, Unsupported,
    check_idempotency_key, iso_time, journaled_write, make_ref, parse_ref, parse_time,
)

LOCAL_API = 'http://127.0.0.1:23119/api'
WEB_API = 'https://api.zotero.org'
API_VERSION = '3'
WRITE_KEY_PATTERN = '^[A-Za-z0-9]{24}$'
NOT_RUNNING = 'Zotero is not running. Open Zotero on this Mac, then try again.'
LOCAL_OFF = ('Turn on "Allow other applications on this computer to communicate with Zotero" '
             'in Zotero Settings, Advanced, then try again.')
SIGN_IN_DETAIL = ('Open Zotero 7 or later and turn on "Allow other applications on this computer to communicate '
                  'with Zotero" in Settings, Advanced. To let Interspace make changes, also paste a Zotero web API '
                  'key with write access from zotero.org/settings/keys.')
USER_LIBRARY = 'users/0'

MAX_TITLE = 300
MAX_META_STRING = 200
MAX_CURSOR = 2048
MAX_NOTE = 100000
_KEY_CHARS = '[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}'
_KEY = re.compile(_KEY_CHARS + r'\Z')
_LIBRARY = re.compile(r'(users/0|groups/[1-9][0-9]{0,11})\Z')
_OBJECT = re.compile(r'(users/0|groups/[1-9][0-9]{0,11})/(collections|items)/(' + _KEY_CHARS + r')\Z')
_URL = re.compile(r'https?://[^\s]+\Z')
ITEM_TYPES = ('journalArticle', 'book', 'bookSection', 'conferencePaper', 'preprint', 'report', 'thesis',
              'webpage', 'document')


def _schema(description, properties, required):
    return {'type': 'object', 'additionalProperties': False, 'description': description,
            'properties': properties, 'required': required}


def _names(maximum, length):
    return {'type': 'array', 'minItems': 1, 'maxItems': maximum,
            'items': {'type': 'string', 'minLength': 1, 'maxLength': length}}


ACTIONS = (
    {'name': 'zotero.library.create_item', 'title': 'Add item to library', 'target_kind': 'library',
     'effect': 'create', 'requires_version': False,
     'params_schema': _schema(
         'Add a reference to a Zotero library. Creators are "Last, First" or one name.', {
             'item_type': {'type': 'string', 'enum': list(ITEM_TYPES), 'maxLength': 32},
             'title': {'type': 'string', 'minLength': 1, 'maxLength': 2000},
             'creators': _names(50, 300),
             'date': {'type': 'string', 'maxLength': 100},
             'url': {'type': 'string', 'maxLength': 2000},
             'abstract': {'type': 'string', 'maxLength': 20000},
             'tags': _names(50, 255)}, ['item_type', 'title'])},
    {'name': 'zotero.item.add_note', 'title': 'Add note', 'target_kind': 'item',
     'effect': 'create', 'requires_version': False,
     'params_schema': _schema('Add a child note with plain text to a Zotero item.', {
         'text': {'type': 'string', 'minLength': 1, 'maxLength': MAX_NOTE}}, ['text'])},
    {'name': 'zotero.item.add_tags', 'title': 'Add tags', 'target_kind': 'item',
     'effect': 'update', 'requires_version': False,
     'params_schema': _schema('Add tags to a Zotero item, keeping its existing tags.', {
         'tags': _names(50, 255)}, ['tags'])},
    {'name': 'zotero.collection.add_item', 'title': 'Add item to collection', 'target_kind': 'collection',
     'effect': 'update', 'requires_version': False,
     'params_schema': _schema('Add an existing item (a zotero:item ref in the same library) to a Zotero collection.', {
         'item': {'type': 'string', 'minLength': 1, 'maxLength': 600}}, ['item'])},
    {'name': 'zotero.item.trash', 'title': 'Move item to trash', 'target_kind': 'item',
     'effect': 'destructive', 'requires_version': False,
     'params_schema': _schema('Move a Zotero item to the Zotero trash.', {}, [])},
)
_ACTIONS = {spec['name']: spec for spec in ACTIONS}


# Remote JSON validation ---------------------------------------------------------

def _bad():
    return InvalidResponse('Zotero sent a reply Interspace could not read.')


def _obj(value):
    if not isinstance(value, dict):
        raise _bad()
    return value


def _field(value, key, kind):
    found = _obj(value).get(key)
    if not isinstance(found, kind) or isinstance(found, bool) and kind is not bool:
        raise _bad()
    return found


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _object_key(value):
    key = _field(value, 'key', str)
    if not _KEY.match(key):
        raise _bad()
    return key


def _version(value):
    version = _int(_obj(value).get('version'))
    if version is None or version < 0:
        raise _bad()
    return str(version)


def _opt_time(value, key):
    found = _obj(value).get(key)
    if found is None:
        return None
    if not isinstance(found, str):
        raise _bad()
    return iso_time(parse_time(found))


def _truncate(text, limit):
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _web_url(value):
    links = _obj(value).get('links')
    alternate = links.get('alternate') if isinstance(links, dict) else None
    href = alternate.get('href') if isinstance(alternate, dict) else None
    return href if isinstance(href, str) and href.startswith('https://') and len(href) <= 2000 else None


class _NoteText(HTMLParser):
    """Zotero note HTML as plain text: blocks become lines, list items `- `."""
    _BLOCKS = frozenset(('p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'pre', 'ul', 'ol', 'table', 'tr'))

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'br':
            self.parts.append('\n')
        elif tag == 'li':
            self.parts.append('\n- ')
        elif tag in self._BLOCKS:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in self._BLOCKS:
            self.parts.append('\n')

    def handle_data(self, data):
        self.parts.append(data)


def note_text(note):
    parser = _NoteText()
    parser.feed(note)
    parser.close()
    lines = [line.rstrip() for line in ''.join(parser.parts).split('\n')]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()


def note_html(text):
    paragraphs = [p for p in re.split(r'\n\s*\n', text.replace('\r\n', '\n')) if p.strip()]
    return ''.join('<p>%s</p>' % html.escape(p.strip('\n'), quote=False).replace('\n', '<br>') for p in paragraphs)


# Resources --------------------------------------------------------------------

def _item_ref(library, key, kind='item'):
    return make_ref('zotero', kind, '%s/items/%s' % (library, key))


def _collection_ref(library, key):
    return make_ref('zotero', 'collection', '%s/collections/%s' % (library, key))


def _library_ref(library):
    return make_ref('zotero', 'library', library)


def _item_title(data):
    if data.get('itemType') == 'note':
        note = data.get('note')
        text = note_text(note) if isinstance(note, str) else ''
        return text.split('\n', 1)[0]
    title = data.get('title')
    return title if isinstance(title, str) else ''


def _item_parent(data, library):
    parent = data.get('parentItem')
    if isinstance(parent, str) and _KEY.match(parent):
        return _item_ref(library, parent)
    collections = data.get('collections')
    if isinstance(collections, list) and collections and isinstance(collections[0], str) and _KEY.match(collections[0]):
        return _collection_ref(library, collections[0])
    return _library_ref(library)


def _item_meta(item, data):
    meta = {'type': data['itemType']}
    info = item.get('meta') if isinstance(item.get('meta'), dict) else {}
    for name, source, key in (('creators', info, 'creatorSummary'), ('date', info, 'parsedDate'),
                              ('content_type', data, 'contentType'), ('filename', data, 'filename')):
        if isinstance(source.get(key), str) and source[key]:
            meta[name] = _truncate(source[key], MAX_META_STRING)
    children = _int(info.get('numChildren'))
    if children:
        meta['children'] = children
    return meta


def _item_data(item):
    data = _field(item, 'data', dict)
    _field(data, 'itemType', str)
    return data


def _item_resource(item, library, parent=None):
    key = _object_key(item)
    data = _item_data(item)
    kind = 'attachment' if data['itemType'] == 'attachment' else 'item'
    meta = _item_meta(item, data)
    return {'ref': _item_ref(library, key, kind), 'kind': kind, 'title': _truncate(_item_title(data), MAX_TITLE),
            'parent': parent or _item_parent(data, library), 'url': _web_url(item),
            'updated_at': _opt_time(data, 'dateModified'), 'has_children': kind == 'item' and bool(meta.get('children')),
            'meta': meta}


def _collection_parent(data, library):
    parent = data.get('parentCollection')
    if isinstance(parent, str) and _KEY.match(parent):
        return _collection_ref(library, parent)
    return _library_ref(library)


def _collection_counts(collection):
    info = collection.get('meta') if isinstance(collection.get('meta'), dict) else {}
    return {'items': _int(info.get('numItems')), 'subcollections': _int(info.get('numCollections'))}


def _collection_resource(collection, library, parent=None):
    key = _object_key(collection)
    data = _field(collection, 'data', dict)
    counts = _collection_counts(collection)
    known = [n for n in counts.values() if n is not None]
    return {'ref': _collection_ref(library, key), 'kind': 'collection',
            'title': _truncate(_field(data, 'name', str), MAX_TITLE), 'parent': parent or _collection_parent(data, library),
            'url': _web_url(collection), 'updated_at': None, 'has_children': sum(known) > 0 if known else True,
            'meta': {k: v for k, v in counts.items() if v is not None}}


def _user_library():
    return {'ref': _library_ref(USER_LIBRARY), 'kind': 'library', 'title': 'My Library', 'parent': None, 'url': None,
            'updated_at': None, 'has_children': True, 'meta': {'type': 'user'}}


def _group(group):
    ident = _int(_obj(group).get('id'))
    if ident is None or not 0 < ident < 10 ** 12:
        raise _bad()
    data = _field(group, 'data', dict)
    info = group.get('meta') if isinstance(group.get('meta'), dict) else {}
    return ident, _field(data, 'name', str), info


def _group_resource(group):
    ident, name, info = _group(group)
    meta = {'type': 'group'}
    if _int(info.get('numItems')) is not None:
        meta['items'] = info['numItems']
    return {'ref': _library_ref('groups/%d' % ident), 'kind': 'library', 'title': _truncate(name, MAX_TITLE),
            'parent': None, 'url': None, 'updated_at': _opt_time(info, 'lastModified'), 'has_children': True,
            'meta': meta}


# Parameters ---------------------------------------------------------------------

def _parse(ref, kinds):
    """(kind, library, key) of a Zotero ref; key is None for a library."""
    _, kind, ident = parse_ref(ref, 'zotero')
    if kind not in kinds:
        raise InvalidRequest('That Zotero reference is not valid here.')
    if kind == 'library':
        if not _LIBRARY.match(ident):
            raise InvalidRequest('That Zotero reference is not valid here.')
        return kind, ident, None
    match = _OBJECT.match(ident)
    if not match or (match.group(2) == 'collections') != (kind == 'collection'):
        raise InvalidRequest('That Zotero reference is not valid here.')
    return kind, match.group(1), match.group(3)


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
    for key, value in params.items():
        rule = schema['properties'][key]
        label = key.replace('_', ' ')
        if rule['type'] == 'string':
            if not isinstance(value, str) or not rule.get('minLength', 0) <= len(value) <= rule['maxLength']:
                raise InvalidRequest('The %s must be text of at most %d characters.' % (label, rule['maxLength']))
            if 'enum' in rule and value not in rule['enum']:
                raise InvalidRequest('The %s must be one of: %s.' % (label, ', '.join(rule['enum'])))
        else:
            items = rule['items']
            if (not isinstance(value, list) or not rule['minItems'] <= len(value) <= rule['maxItems']
                    or not all(isinstance(v, str) and items['minLength'] <= len(v.strip()) and len(v) <= items['maxLength']
                               for v in value)):
                raise InvalidRequest('The %s must be a list of 1 to %d names.' % (label, rule['maxItems']))
    if params.get('url') and not _URL.match(params['url']):
        raise InvalidRequest('The URL must start with http:// or https://.')


def _creator(name):
    last, comma, first = name.partition(',')
    if comma and last.strip() and first.strip():
        return {'creatorType': 'author', 'lastName': last.strip(), 'firstName': first.strip()}
    return {'creatorType': 'author', 'name': name.strip()}


def _new_item(params):
    item = {'itemType': params['item_type'], 'title': params['title'],
            'creators': [_creator(name) for name in params.get('creators', [])]}
    for key, field in (('date', 'date'), ('url', 'url'), ('abstract', 'abstractNote')):
        if params.get(key):
            item[field] = params[key]
    item.update(tags=[{'tag': tag.strip()} for tag in params.get('tags', [])], collections=[], relations={})
    return item


# Cursors ----------------------------------------------------------------------

def _encode_cursor(data):
    raw = json.dumps(data, separators=(',', ':'), sort_keys=True).encode('utf-8')
    cursor = base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
    if len(cursor) > MAX_CURSOR:
        raise InvalidResponse('Zotero sent a page position Interspace cannot keep.')
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


def _cursor_int(state, key, default=0):
    value = state.get(key, default) if state else default
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequest('That page position is not valid. Start again from the first page.')
    return value


def _check_limit(limit):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise InvalidRequest('The limit must be a whole number from 1 to 100.')
    return limit


# Connector ----------------------------------------------------------------------

class Connector:
    app = 'zotero'
    kinds = ('library', 'collection', 'item', 'attachment')
    max_read_chars = 200000

    def __init__(self, *, http, credentials, journal, clock=time.time):
        self.http = http
        self.credentials = credentials
        self.journal = journal
        self.clock = clock

    # Requests -----------------------------------------------------------------

    def _secret(self):
        secret = self.credentials.get()
        if not isinstance(secret, dict) or secret.get('kind') != 'zotero':
            raise NotSignedIn('Connect Zotero first.')
        return secret

    def _request(self, method, url, *, headers, params=None, body=None, local=False, write=False):
        try:
            response = self.http.request(method, url, headers=headers, params=params, json=body)
        except Unavailable as error:
            if not local:
                raise
            failure = Unavailable(NOT_RUNNING)
            failure.request_sent = error.request_sent
            raise failure from None
        status = response.status
        if 200 <= status < 300:
            return response
        if status == 403 and local:
            raise Unavailable(LOCAL_OFF)
        if status == 401:
            raise AuthExpired('Zotero no longer accepts the saved web API key. Connect Zotero again with a new key.')
        if status == 403:
            raise Forbidden('Zotero did not allow this with the saved web API key. Check the key’s permissions at zotero.org.')
        if status == 404:
            raise NotFound('Zotero could not find this item.')
        if status == 409:
            raise Conflict('The Zotero library is busy. Try again shortly.')
        if status == 412:
            raise Conflict('The item changed in Zotero since it was read. Read it again and retry.')
        if status == 429:
            retry = response.headers.get('retry-after', '')
            raise RateLimited('Zotero is limiting requests. Try again shortly.',
                              retry_after_s=int(retry) if retry.isdigit() else None)
        if status in (400, 413, 422, 428):
            raise InvalidRequest('Zotero rejected the request as invalid.')
        if status == 501:
            raise Unsupported('This Zotero version cannot do that. Update Zotero and try again.')
        if status >= 500:
            if write:
                raise OutcomeUnknown('Zotero failed while making this change; it may or may not have happened.')
            raise Unavailable('Zotero is unavailable right now. Try again later.')
        raise InvalidResponse('Zotero sent an unexpected reply.')

    def _local(self, path, params=None):
        return self._request('GET', LOCAL_API + '/' + path, headers={'Zotero-API-Version': API_VERSION},
                             params=params, local=True)

    def _local_json(self, path, params=None):
        return self._local(path, params).json()

    def _listing(self, path, start, count, params=None):
        response = self._local(path, dict(params or {}, start=start, limit=count))
        items = response.json()
        if not isinstance(items, list):
            raise _bad()
        total = response.headers.get('total-results', '')
        more = start + len(items) < int(total) if total.isdigit() else len(items) >= count
        return [_obj(item) for item in items], bool(items) and more, response

    def _local_check(self):
        if not isinstance(self._local_json('users/0/items/top', {'limit': 1}), list):
            raise _bad()

    # Auth ---------------------------------------------------------------------

    def _status(self, state, account=None, detail='', granted=()):
        return {'v': 1, 'app': self.app, 'state': state, 'account': account, 'granted': list(granted),
                'detail': detail, 'checked_at': iso_time(self.clock())}

    def _signed_in(self, secret):
        # PROVISIONAL(0C-2): capability names for Zotero.
        if secret.get('write_key'):
            account = {'label': _truncate(secret.get('username') or 'My Library', MAX_TITLE), 'id': secret['user_id']}
            return self._status('signed_in', account, granted=('library:read', 'library:write'))
        return self._status('signed_in', {'label': 'My Library', 'id': 'local'}, granted=('library:read',))

    def status(self):
        try:
            secret = self._secret()
        except NotSignedIn:
            return self._status('signed_out')
        except CredentialStoreUnavailable as error:
            return self._status('unavailable', detail=str(error))
        try:
            self._local_check()
        except Unavailable as error:
            return self._status('unavailable', detail=str(error))
        except SpaceError:
            return self._status('unavailable', detail='Zotero did not answer as expected. Restart Zotero and try again.')
        return self._signed_in(secret)

    def begin_sign_in(self, params):
        return {'v': 1, 'app': self.app, 'kind': 'local_check', 'detail': SIGN_IN_DETAIL}

    def complete_sign_in(self, params, cancel):
        if not isinstance(params, dict) or not set(params) <= {'write_key'}:
            raise InvalidRequest('Zotero sign-in takes only an optional web API key.')
        write_key = params.get('write_key') or None
        if write_key is not None and (not isinstance(write_key, str) or not re.match(WRITE_KEY_PATTERN, write_key)):
            raise InvalidRequest('That does not look like a Zotero API key. Copy it again from zotero.org/settings/keys.')
        cancelled = lambda: cancel is not None and cancel.is_set()  # noqa: E731
        if cancelled():
            raise SignInCancelled('Sign-in was cancelled.')
        self._local_check()
        secret = {'kind': 'zotero'}
        if write_key:
            secret.update(self._verify_write_key(write_key))
        else:
            previous = self.credentials.get()
            if isinstance(previous, dict) and previous.get('kind') == 'zotero' and previous.get('write_key'):
                secret.update({k: previous[k] for k in ('write_key', 'user_id', 'username') if k in previous})
        if cancelled():
            raise SignInCancelled('Sign-in was cancelled.')
        self.credentials.set(secret)
        return self._signed_in(secret)

    def _verify_write_key(self, write_key):
        try:
            reply = _obj(self._request('GET', WEB_API + '/keys/current', headers=self._web_headers(write_key)).json())
        except (AuthExpired, Forbidden, NotFound):
            raise InvalidRequest('Zotero did not accept this key. Copy it again from zotero.org/settings/keys.') from None
        user_id = _int(reply.get('userID'))
        if user_id is None or user_id <= 0:
            raise _bad()
        access = reply.get('access') if isinstance(reply.get('access'), dict) else {}
        user = access.get('user') if isinstance(access.get('user'), dict) else {}
        if user.get('write') is not True or user.get('library') is not True:
            raise InvalidRequest('This key has no write access to your library. Create one with "Allow write access" '
                                 'at zotero.org/settings/keys.')
        username = reply.get('username') if isinstance(reply.get('username'), str) else ''
        return {'write_key': write_key, 'user_id': str(user_id), 'username': _truncate(username, MAX_TITLE)}

    def sign_out(self):
        # Zotero web API keys are revoked by the user at zotero.org/settings/keys.
        self.credentials.delete()
        return self._status('signed_out')

    # Read ---------------------------------------------------------------------

    def _page(self, items, following):
        return {'v': 1, 'items': items, 'next_cursor': _encode_cursor(following) if following else None}

    def _source(self, path, mapper, params=None):
        def fetch(start, count):
            items, more, _ = self._listing(path, start, count, params)
            return [mapper(item) for item in items], more
        return fetch

    def _paged(self, sources, state, limit, extra):
        """Fill one page from `sources` in order; the cursor keeps the source index and offset."""
        phase, start = _cursor_int(state, 'ph'), _cursor_int(state, 's')
        if phase >= len(sources) and sources:
            raise InvalidRequest('That page position is not valid. Start again from the first page.')
        resources = []
        while phase < len(sources) and len(resources) < limit:
            found, more = sources[phase](start, limit - len(resources))
            resources.extend(found)
            if more:
                start += len(found)
                break
            phase, start = phase + 1, 0
        following = dict(extra, ph=phase, s=start) if phase < len(sources) else None
        return self._page(resources, following)

    def browse(self, parent=None, cursor=None, limit=50):
        _check_limit(limit)
        state = _decode_cursor(cursor, 'browse', p=parent)
        if parent is None:
            self._secret()
            # My Library first, then the groups.
            sources = [lambda start, count: ([_user_library()], False), self._source('users/0/groups', _group_resource)]
            return self._paged(sources, state, limit, {'m': 'browse', 'p': None})
        kind, library, key = _parse(parent, self.kinds)
        self._secret()
        newest = {'sort': 'dateModified', 'direction': 'desc'}
        collection = lambda item: _collection_resource(item, library, parent)  # noqa: E731
        item = lambda value: _item_resource(value, library, parent)  # noqa: E731
        if kind == 'library':
            sources = [self._source(library + '/collections/top', collection),
                       self._source(library + '/items/top', item, newest)]
        elif kind == 'collection':
            base_path = '%s/collections/%s' % (library, key)
            sources = [self._source(base_path + '/collections', collection),
                       self._source(base_path + '/items/top', item, newest)]
        elif kind == 'item':
            sources = [self._source('%s/items/%s/children' % (library, key), item)]
        else:
            sources = []
        return self._paged(sources, state, limit, {'m': 'browse', 'p': parent})

    def search(self, query, kinds=None, cursor=None, limit=25):
        _check_limit(limit)
        if not isinstance(query, str) or not 1 <= len(query) <= 500:
            raise InvalidRequest('Search text must be 1 to 500 characters.')
        if kinds is not None:
            if not isinstance(kinds, (list, tuple)) or not kinds or not set(kinds) <= set(self.kinds):
                raise InvalidRequest('Zotero can search libraries, collections, items and attachments only.')
        wanted = set(kinds or self.kinds) & {'item', 'attachment'}
        state = _decode_cursor(cursor, 'search', q=query, k=sorted(wanted))
        if not wanted:
            return self._page([], None)   # collections and libraries are not searchable
        self._secret()
        params = {'q': query, 'qmode': 'titleCreatorYear'}
        if wanted == {'item'}:
            params['itemType'] = '-attachment'
        elif wanted == {'attachment'}:
            params['itemType'] = 'attachment'
        start = _cursor_int(state, 's')
        items, more, _ = self._listing(USER_LIBRARY + '/items', start, limit, params)
        resources = [_item_resource(item, USER_LIBRARY) for item in items]
        following = {'m': 'search', 'q': query, 'k': sorted(wanted), 's': start + len(items)} if more else None
        return self._page(resources, following)

    def read(self, ref, cursor=None):
        kind, library, key = _parse(ref, self.kinds)
        state = _decode_cursor(cursor, 'read', r=ref)
        offset = _cursor_int(state, 'o')
        self._secret()
        url, meta, fmt = None, {}, 'json'
        if kind == 'library':
            title, version, parent, record = self._library_record(library)
            text = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=1)
        elif kind == 'collection':
            collection = _obj(self._local_json('%s/collections/%s' % (library, key)))
            data = _field(collection, 'data', dict)
            title, version, url = _field(data, 'name', str), _version(collection), _web_url(collection)
            parent = _collection_parent(data, library)
            text = json.dumps(dict(_collection_counts(collection), name=title), ensure_ascii=False, sort_keys=True, indent=1)
        else:
            item = _obj(self._local_json('%s/items/%s' % (library, key)))
            data = _item_data(item)
            _object_key(item)
            title, version, url = _item_title(data), _version(item), _web_url(item)
            parent, meta = _item_parent(data, library), _item_meta(item, data)
            _opt_time(data, 'dateModified')
            self._check_same_version(state, version)
            fmt, text = self._item_text(library, key, data, meta)
        self._check_same_version(state, version)
        part = text[offset:offset + self.max_read_chars] if offset <= len(text) else ''
        following = None
        if offset + len(part) < len(text):
            following = {'m': 'read', 'r': ref, 'o': offset + len(part), 'ver': version}
        return {'parent': parent, 'v': 1, 'ref': ref, 'title': _truncate(title, MAX_TITLE), 'format': fmt,
                'text': part, 'truncated': following is not None,
                'next_cursor': _encode_cursor(following) if following else None,
                'version': version, 'url': url, 'meta': meta}

    @staticmethod
    def _check_same_version(state, version):
        if state and state.get('ver') != version:
            raise InvalidRequest('This changed in Zotero since the first part was read. Read it again from the start.')

    def _item_text(self, library, key, data, meta):
        item_type = data['itemType']
        if item_type == 'note':
            note = data.get('note')
            return 'text', note_text(note) if isinstance(note, str) else ''
        if item_type == 'attachment':
            try:
                fulltext = _obj(self._local_json('%s/items/%s/fulltext' % (library, key)))
            except NotFound:
                meta['reason'] = 'Zotero has no indexed text for this attachment.'
                return 'unavailable', ''
            return 'text', _field(fulltext, 'content', str)
        record = {k: v for k, v in data.items() if k not in ('key', 'version', 'relations')}
        return 'json', json.dumps(record, ensure_ascii=False, sort_keys=True, indent=1)

    def _library_record(self, library):
        if library == USER_LIBRARY:
            return 'My Library', None, None, {'name': 'My Library', 'type': 'user'}
        wanted = int(library.split('/')[1])
        groups = self._local_json('users/0/groups', {'limit': 100})
        if not isinstance(groups, list):
            raise _bad()
        for group in groups:
            ident, name, info = _group(group)
            if ident == wanted:
                record = {'name': name, 'type': 'group'}
                if _int(info.get('numItems')) is not None:
                    record['items'] = info['numItems']
                return name, _version(group), None, record
        raise NotFound('Zotero could not find this library.')

    # Write --------------------------------------------------------------------

    def actions(self):
        return json.loads(json.dumps(ACTIONS))

    def write(self, action, ref, params, idempotency_key):
        spec = _ACTIONS.get(action)
        if spec is None:
            raise InvalidRequest('Zotero has no such action.')
        _, library, key = _parse(ref, (spec['target_kind'],))
        _check_params(spec, params)
        target = None
        if action == 'zotero.collection.add_item':
            _, item_library, item_key = _parse(params['item'], ('item',))
            if item_library != library:
                raise InvalidRequest('The item and the collection must be in the same Zotero library.')
            target = item_key
        check_idempotency_key(idempotency_key)
        route = self._write_route()
        perform = getattr(self, '_' + action.split('.', 1)[1].replace('.', '_'))
        return journaled_write(self.journal, key=idempotency_key, app=self.app, action=action, ref=ref, params=params,
                               perform=lambda: perform(route, ref, library, key, params, target, idempotency_key))

    def _write_route(self):
        """PROVISIONAL(0C-4): writes go to the Zotero web API with the saved key."""
        secret = self._secret()
        if not secret.get('write_key') or not str(secret.get('user_id', '')).isdigit():
            raise Unsupported('Zotero is read-only in Interspace. Connect Zotero again with a web API key that can write.')
        return {'key': secret['write_key'], 'user_id': secret['user_id']}

    @staticmethod
    def _web_headers(key, **extra):
        return dict({'Zotero-API-Key': key, 'Zotero-API-Version': API_VERSION}, **extra)

    def _web(self, route, method, library, path, *, body=None, write=True, **headers):
        if library == USER_LIBRARY:
            library = 'users/' + route['user_id']
        return self._request(method, '%s/%s/%s' % (WEB_API, library, path),
                             headers=self._web_headers(route['key'], **headers), body=body, write=write)

    def _read_item(self, route, library, key):
        """A read made as the first step of a write: its failures never leave a write unknown."""
        try:
            item = _obj(self._web(route, 'GET', library, 'items/' + key, write=False).json())
        except Unavailable as error:
            error.request_sent = False
            raise
        _item_data(item)
        return item, _version(item)

    def _patch_item(self, route, library, key, body, version):
        response = self._web(route, 'PATCH', library, 'items/' + key, body=body,
                             **{'If-Unmodified-Since-Version': version})
        updated = response.headers.get('last-modified-version', '')
        return updated if updated.isdigit() else None

    def _create(self, route, library, item, idempotency_key):
        token = hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()[:32]
        reply = _obj(self._web(route, 'POST', library, 'items', body=[item], **{'Zotero-Write-Token': token}).json())
        failed = reply.get('failed')
        if isinstance(failed, dict) and failed.get('0') is not None:
            code = _int(failed['0'].get('code')) if isinstance(failed['0'], dict) else None
            if code in (409, 412):
                raise Conflict('Zotero refused the change because the library changed. Try again.')
            if code == 403:
                raise Forbidden('Zotero did not allow this with the saved web API key. Check the key’s permissions at zotero.org.')
            raise InvalidRequest('Zotero rejected the new item as invalid.')
        successful = reply.get('successful')
        created = _obj(successful.get('0') if isinstance(successful, dict) else None)
        return created, _object_key(created), _version(created)

    def _result(self, action, ref, result_ref, url, version, summary):
        return {'v': 1, 'ok': True, 'action': action, 'ref': ref, 'result_ref': result_ref, 'url': url,
                'version': version, 'replayed': False, 'summary': _truncate(summary, 300)}

    def _library_create_item(self, route, ref, library, key, params, target, idempotency_key):
        created, new_key, version = self._create(route, library, _new_item(params), idempotency_key)
        return self._result('zotero.library.create_item', ref, _item_ref(library, new_key), _web_url(created), version,
                            'Created "%s" in Zotero. It appears in the Zotero app after Zotero syncs.'
                            % _truncate(params['title'], 150))

    def _item_add_note(self, route, ref, library, key, params, target, idempotency_key):
        note = {'itemType': 'note', 'parentItem': key, 'note': note_html(params['text']),
                'tags': [], 'collections': [], 'relations': {}}
        created, new_key, version = self._create(route, library, note, idempotency_key)
        return self._result('zotero.item.add_note', ref, _item_ref(library, new_key), _web_url(created), version,
                            'Added a note to the item.')

    def _item_add_tags(self, route, ref, library, key, params, target, idempotency_key):
        """Two steps: read the item (tags and version), then patch it. Stopping after the read is safe."""
        item, version = self._read_item(route, library, key)
        tags = _item_data(item).get('tags')
        tags = [t for t in tags if isinstance(t, dict) and isinstance(t.get('tag'), str)] if isinstance(tags, list) else []
        have = {t['tag'] for t in tags}
        added = []
        for tag in (t.strip() for t in params['tags']):
            if tag not in have and tag not in added:
                added.append(tag)
        if not added:
            return self._result('zotero.item.add_tags', ref, ref, _web_url(item), version, 'The item already has these tags.')
        new_version = self._patch_item(route, library, key, {'tags': tags + [{'tag': t} for t in added]}, version)
        return self._result('zotero.item.add_tags', ref, ref, _web_url(item), new_version,
                            'Added %d tag%s.' % (len(added), '' if len(added) == 1 else 's'))

    def _collection_add_item(self, route, ref, library, key, params, target, idempotency_key):
        """Two steps: read the item (collections and version), then patch it. Stopping after the read is safe."""
        item, version = self._read_item(route, library, target)
        data = _item_data(item)
        collections = [c for c in data.get('collections') or [] if isinstance(c, str) and _KEY.match(c)]
        title = _truncate(_item_title(data), 150)
        item_ref = _item_ref(library, target)
        if key in collections:
            return self._result('zotero.collection.add_item', ref, item_ref, _web_url(item), version,
                                'The item is already in the collection.')
        new_version = self._patch_item(route, library, target, {'collections': collections + [key]}, version)
        return self._result('zotero.collection.add_item', ref, item_ref, _web_url(item), new_version,
                            'Added "%s" to the collection.' % title)

    def _item_trash(self, route, ref, library, key, params, target, idempotency_key):
        """Two steps: read the item (version), then mark it deleted. Stopping after the read is safe."""
        item, version = self._read_item(route, library, key)
        new_version = self._patch_item(route, library, key, {'deleted': 1}, version)
        return self._result('zotero.item.trash', ref, ref, _web_url(item), new_version,
                            'Moved "%s" to the Zotero trash.' % _truncate(_item_title(_item_data(item)), 150))

    # Changes ------------------------------------------------------------------

    @staticmethod
    def _library_version(response):
        version = response.headers.get('last-modified-version', '')
        if not version.isdigit():
            raise _bad()
        return int(version)

    def changes(self, cursor=None, limit=100):
        """Items in My Library changed since the cursor's library version.

        The cursor keeps `since` (library version), `t` (time of the last
        complete sweep, to tell created from updated), and while paging, the
        offset `s` and the library version `to` seen on the first page.
        """
        _check_limit(limit)
        if cursor is None:
            self._secret()
            response = self._local(USER_LIBRARY + '/items', {'format': 'versions', 'limit': 1})
            since = self._library_version(response)
            return {'v': 1, 'items': [], 'complete': True,
                    'cursor': _encode_cursor({'m': 'changes', 'since': since, 't': iso_time(self.clock())})}
        state = _decode_cursor(cursor, 'changes')
        since, start = _cursor_int(state, 'since', None), _cursor_int(state, 's')
        try:
            swept = parse_time(state.get('t'))
        except InvalidResponse:
            raise InvalidRequest('That change position is not valid.') from None
        self._secret()
        params = {'since': since, 'includeTrashed': 1, 'sort': 'dateModified', 'direction': 'asc'}
        items, more, response = self._listing(USER_LIBRARY + '/items', start, limit, params)
        target = _cursor_int(state, 'to') if 'to' in state else self._library_version(response)
        changed = []
        for item in items:
            resource = _item_resource(item, USER_LIBRARY)
            data = _item_data(item)
            added = data.get('dateAdded')
            if data.get('deleted') in (1, True):
                change = 'deleted'
            elif isinstance(added, str) and parse_time(added) >= swept:
                change = 'created'
            else:
                change = 'updated'
            changed.append({'ref': resource['ref'], 'change': change,
                            'at': resource['updated_at'] or iso_time(self.clock()), 'title': resource['title']})
        if more:
            following = {'m': 'changes', 'since': since, 't': state['t'], 's': start + len(items), 'to': target}
        else:
            following = {'m': 'changes', 'since': target, 't': iso_time(self.clock())}
        return {'v': 1, 'items': changed, 'cursor': _encode_cursor(following), 'complete': not more}
