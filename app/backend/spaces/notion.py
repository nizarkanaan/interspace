"""Notion connector (contract: connectors.md; route: docs/research/connector-auth.md).

Route: the Notion REST API (`api.notion.com`, `Notion-Version: 2026-03-11`)
with a pasted internal connection token or personal access token
(`token_entry` sign-in). The hosted Notion MCP is not used.

Route details the Connector API hides:
- `notion:database:<id>` uses the database (container) ID. Rows live in its
  data sources; browsing walks every data source, creating a page uses the
  first one.
- Browsing the roots lists every page and database the token can see, newest
  edit first (Notion has no "list shared roots" call). Children of a page are
  its sub-pages and inline databases.
- Reading a page renders its top-level blocks as Markdown. Nested blocks
  (inside toggles or list items) are not fetched, to bound requests.
- Appended Markdown is plain text per block: headings, lists, to-dos, quotes,
  dividers, code fences and paragraphs. Inline formatting is kept as typed.
- `changes` polls search sorted by last edit. Notion rounds `last_edited_time`
  to the minute and its index can lag, so a second edit to the same page in
  the same minute can be missed. Deleted pages leave search and are never
  reported as `deleted`.
"""
import base64
import binascii
import json
import re
import time

from spaces.base import (
    AuthExpired, Conflict, CredentialStoreUnavailable, Forbidden, InvalidRequest, InvalidResponse, NotFound,
    NotSignedIn, OutcomeUnknown, RateLimited, SignInCancelled, SpaceError, Unavailable,
    check_idempotency_key, iso_time, journaled_write, make_ref, parse_ref, parse_time,
)

API = 'https://api.notion.com/v1'
NOTION_VERSION = '2026-03-11'
TOKEN_PATTERN = '^[A-Za-z0-9_-]{20,256}$'
HELP_URL = 'https://developers.notion.com/guides/get-started/internal-connections'
# Notion reports no capabilities for a token; a missing one surfaces as Forbidden on use.
GRANTED = ['content:read', 'content:write', 'comments:write']

MAX_TITLE = 300
MAX_META = 12
MAX_META_STRING = 200
MAX_CURSOR = 2048
MAX_RICH_TEXT = 2000          # Notion's limit per rich text element
MAX_RICH_TEXT_ITEMS = 100
MAX_BLOCKS_PER_APPEND = 100
MAX_BLOCK_REQUESTS_PER_READ = 10
MAX_SEEN_IDS = 12            # keeps a changes cursor well under 2,048 characters
_ID = re.compile(r'[0-9a-fA-F]{32}\Z')
_LIST_TYPES = ('bulleted_list_item', 'numbered_list_item', 'to_do')
_CODE_LANGUAGES = frozenset((
    'bash', 'c', 'c#', 'c++', 'css', 'go', 'html', 'java', 'javascript', 'json', 'kotlin', 'markdown', 'php',
    'python', 'r', 'ruby', 'rust', 'shell', 'sql', 'swift', 'typescript', 'yaml', 'plain text'))


def _schema(description, properties, required):
    return {'type': 'object', 'additionalProperties': False, 'description': description,
            'properties': properties, 'required': required}


_PROPERTY_VALUE = {'anyOf': [
    {'type': 'string', 'maxLength': MAX_RICH_TEXT}, {'type': 'number'}, {'type': 'boolean'}, {'type': 'null'},
    {'type': 'array', 'maxItems': 100, 'items': {'type': 'string', 'maxLength': 100}}]}

ACTIONS = (
    {'name': 'notion.database.create_page', 'title': 'Create page in database', 'target_kind': 'database',
     'effect': 'create', 'requires_version': False,
     'params_schema': _schema('Create a page (row) in a Notion database with a title and optional Markdown body.', {
         'title': {'type': 'string', 'minLength': 1, 'maxLength': MAX_RICH_TEXT},
         'markdown': {'type': 'string', 'maxLength': 100000}}, ['title'])},
    {'name': 'notion.page.append', 'title': 'Append to page', 'target_kind': 'page',
     'effect': 'update', 'requires_version': False,
     'params_schema': _schema('Append Markdown blocks to the end of a Notion page.', {
         'markdown': {'type': 'string', 'minLength': 1, 'maxLength': 100000}}, ['markdown'])},
    {'name': 'notion.page.update_properties', 'title': 'Update page properties', 'target_kind': 'page',
     'effect': 'update', 'requires_version': True,
     'params_schema': _schema(
         'Set property values of a Notion database page by property name: text for title, text, select, '
         'status, date, URL, email and phone; a number; true or false for checkboxes; a list of names for '
         'multi-select. `base_version` is the version from the last read.', {
             'properties': {'type': 'object', 'minProperties': 1, 'maxProperties': 25,
                            'propertyNames': {'maxLength': 100}, 'additionalProperties': _PROPERTY_VALUE},
             'base_version': {'type': 'string', 'maxLength': 64}}, ['properties', 'base_version'])},
    {'name': 'notion.page.comment', 'title': 'Comment on page', 'target_kind': 'page',
     'effect': 'create', 'requires_version': False,
     'params_schema': _schema('Add a comment to a Notion page.', {
         'text': {'type': 'string', 'minLength': 1, 'maxLength': MAX_RICH_TEXT}}, ['text'])},
    {'name': 'notion.page.archive', 'title': 'Move page to trash', 'target_kind': 'page',
     'effect': 'destructive', 'requires_version': False,
     'params_schema': _schema('Move a Notion page to the Notion trash.', {}, [])},
)
_ACTIONS = {spec['name']: spec for spec in ACTIONS}


# Remote JSON validation ---------------------------------------------------------

def _bad():
    return InvalidResponse('Notion sent a reply Interspace could not read.')


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
    if not isinstance(found, kind):
        raise _bad()
    return found


def _remote_id(value, key='id'):
    ident = _field(value, key, str)
    if not _ID.match(ident.replace('-', '')):
        raise _bad()
    return ident


def _time(value, key):
    return iso_time(parse_time(_field(value, key, str)))


def _list_page(reply):
    results = _field(reply, 'results', list)
    next_cursor = _opt(reply, 'next_cursor', str) if reply.get('has_more') else None
    return [_obj(item) for item in results], next_cursor


def _truncate(text, limit):
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _plain(rich_text):
    if rich_text is None:
        return ''
    if not isinstance(rich_text, list):
        raise _bad()
    return ''.join(_field(item, 'plain_text', str) for item in rich_text)


def _markdown_text(rich_text):
    if not isinstance(rich_text, list):
        raise _bad()
    parts = []
    for item in rich_text:
        text = _field(item, 'plain_text', str)
        notes = item.get('annotations') if isinstance(item.get('annotations'), dict) else {}
        if text and notes.get('code') is True:
            text = '`%s`' % text
        if text and notes.get('bold') is True:
            text = '**%s**' % text
        if text and notes.get('italic') is True:
            text = '*%s*' % text
        href = item.get('href')
        if isinstance(href, str) and href.startswith(('https://', 'http://')):
            text = '[%s](%s)' % (text, href)
        parts.append(text)
    return ''.join(parts)


def _page_title(page):
    for prop in _field(page, 'properties', dict).values():
        if isinstance(prop, dict) and prop.get('type') == 'title':
            return _plain(prop.get('title'))
    return ''


def _scalar(prop):
    """A property value as one scalar for `meta`, or None when it has none."""
    kind = prop.get('type')
    value = prop.get(kind) if isinstance(kind, str) else None
    if kind in ('select', 'status'):
        return value.get('name') if isinstance(value, dict) and isinstance(value.get('name'), str) else None
    if kind == 'multi_select' and isinstance(value, list):
        return ', '.join(o['name'] for o in value if isinstance(o, dict) and isinstance(o.get('name'), str))
    if kind == 'rich_text' and isinstance(value, list):
        return _plain(value)
    if kind == 'date':
        return value.get('start') if isinstance(value, dict) and isinstance(value.get('start'), str) else None
    if kind == 'number' and isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if kind == 'checkbox' and isinstance(value, bool):
        return value
    if kind in ('url', 'email', 'phone_number') and isinstance(value, str):
        return value
    return None


def _meta(page):
    meta = {}
    for name, prop in _field(page, 'properties', dict).items():
        if len(meta) >= MAX_META:
            break
        if not isinstance(prop, dict) or prop.get('type') == 'title':
            continue
        value = _scalar(prop)
        if value is None:
            continue
        meta[_truncate(str(name), MAX_META_STRING)] = _truncate(value, MAX_META_STRING) if isinstance(value, str) else value
    return meta


def _parent_ref(parent):
    parent = _obj(parent)
    kind = parent.get('type')
    if kind == 'page_id':
        return make_ref('notion', 'page', _remote_id(parent, 'page_id'))
    if kind in ('database_id', 'data_source_id') and parent.get('database_id'):
        return make_ref('notion', 'database', _remote_id(parent, 'database_id'))
    if kind == 'block_id':
        return make_ref('notion', 'block', _remote_id(parent, 'block_id'))
    return None


def _url(value):
    url = _opt(value, 'url', str)
    return url if url and url.startswith('https://') else None


def _page_resource(page):
    return {'ref': make_ref('notion', 'page', _remote_id(page)), 'kind': 'page',
            'title': _truncate(_page_title(page), MAX_TITLE), 'parent': _parent_ref(page.get('parent')),
            'url': _url(page), 'updated_at': _time(page, 'last_edited_time'), 'has_children': True, 'meta': _meta(page)}


def _data_source_resource(source):
    database_id = _remote_id(_field(source, 'parent', dict), 'database_id')
    database_parent = source.get('database_parent')
    return {'ref': make_ref('notion', 'database', database_id), 'kind': 'database',
            'title': _truncate(_plain(source.get('title')), MAX_TITLE),
            'parent': _parent_ref(database_parent) if database_parent is not None else None,
            'url': _url(source), 'updated_at': _time(source, 'last_edited_time'), 'has_children': True, 'meta': {}}


def _search_resource(item):
    kind = item.get('object')
    if kind == 'page':
        return _page_resource(item)
    if kind == 'data_source':
        return _data_source_resource(item)
    return None


def _child_resource(block, parent_ref):
    kind = _field(block, 'type', str)
    if kind not in ('child_page', 'child_database'):
        return None
    ref_kind = 'page' if kind == 'child_page' else 'database'
    return {'ref': make_ref('notion', ref_kind, _remote_id(block)), 'kind': ref_kind,
            'title': _truncate(_field(_field(block, kind, dict), 'title', str), MAX_TITLE), 'parent': parent_ref,
            'url': None, 'updated_at': _time(block, 'last_edited_time'),
            'has_children': ref_kind == 'database' or block.get('has_children') is True, 'meta': {}}


def _block_markdown(block):
    """One block as Markdown, ending in a newline."""
    kind = _field(block, 'type', str)
    body = block.get(kind) if isinstance(block.get(kind), dict) else {}
    text = lambda: _markdown_text(body.get('rich_text', []))  # noqa: E731
    if kind == 'paragraph':
        return text() + '\n\n'
    if kind in ('heading_1', 'heading_2', 'heading_3'):
        return '#' * int(kind[-1]) + ' ' + text() + '\n\n'
    if kind == 'bulleted_list_item':
        return '- ' + text() + '\n'
    if kind == 'numbered_list_item':
        return '1. ' + text() + '\n'
    if kind == 'to_do':
        return ('- [x] ' if body.get('checked') is True else '- [ ] ') + text() + '\n'
    if kind in ('quote', 'callout', 'toggle'):
        return '> ' + text().replace('\n', '\n> ') + '\n\n'
    if kind == 'code':
        language = body.get('language') if isinstance(body.get('language'), str) else ''
        language = '' if language == 'plain text' else language
        return '```%s\n%s\n```\n\n' % (language, _plain(body.get('rich_text', [])))
    if kind == 'divider':
        return '---\n\n'
    if kind == 'equation':
        return '$$%s$$\n\n' % (body.get('expression') if isinstance(body.get('expression'), str) else '')
    if kind == 'child_page':
        return 'Sub-page: %s\n\n' % _field(body, 'title', str)
    if kind == 'child_database':
        return 'Database: %s\n\n' % _field(body, 'title', str)
    if kind in ('bookmark', 'embed', 'link_preview'):
        return (body.get('url') if isinstance(body.get('url'), str) else '') + '\n\n'
    if kind in ('image', 'file', 'pdf', 'video', 'audio'):
        # Notion-hosted file links are short-lived signed URLs, so only the caption is kept.
        caption = _plain(body.get('caption', []))
        return '[%s%s]\n\n' % (kind, ': ' + caption if caption else '')
    return '[Unsupported Notion block: %s]\n\n' % kind


def _render_blocks(blocks, skip, offset, budget, previous_list, empty):
    """Render blocks[skip:] into at most `budget` characters.

    Returns (text, stopped_at): stopped_at is None when every block fitted,
    else (index, offset) of the first character not returned. A block larger
    than the budget is split only when nothing was returned yet (`empty`).
    """
    out = []
    used = 0
    for index in range(skip, len(blocks)):
        block = blocks[index]
        kind = block.get('type')
        core = _block_markdown(block)
        start = offset if index == skip else 0
        # A blank line separates a list from the block after it; offsets count `core` only.
        prefix = '\n' if previous_list and kind not in _LIST_TYPES and not start else ''
        piece = prefix + core[start:]
        previous_list = kind in _LIST_TYPES
        if used + len(piece) > budget:
            if empty and used == 0:
                out.append(piece[:budget])
                return ''.join(out), (index, start + budget - len(prefix))
            return ''.join(out), (index, 0)
        out.append(piece)
        used += len(piece)
    return ''.join(out), None


def _rich_text(text):
    chunks = [text[i:i + MAX_RICH_TEXT] for i in range(0, len(text), MAX_RICH_TEXT)] or ['']
    if len(chunks) > MAX_RICH_TEXT_ITEMS:
        raise InvalidRequest('One block of that text is too long for Notion. Split it into shorter paragraphs.')
    return [{'type': 'text', 'text': {'content': chunk}} for chunk in chunks]


def _block(kind, text, **extra):
    return {'object': 'block', 'type': kind, kind: dict({'rich_text': _rich_text(text)}, **extra)}


_PREFIXES = (
    (re.compile(r'### (.*)\Z'), 'heading_3', {}), (re.compile(r'## (.*)\Z'), 'heading_2', {}),
    (re.compile(r'# (.*)\Z'), 'heading_1', {}),
    (re.compile(r'[-*] \[[xX]\] (.*)\Z'), 'to_do', {'checked': True}),
    (re.compile(r'[-*] \[ \] (.*)\Z'), 'to_do', {'checked': False}),
    (re.compile(r'[-*] (.*)\Z'), 'bulleted_list_item', {}), (re.compile(r'\d+[.)] (.*)\Z'), 'numbered_list_item', {}),
    (re.compile(r'> ?(.*)\Z'), 'quote', {}),
)


def markdown_blocks(markdown):
    """Plain Markdown lines as Notion block objects (at most 100)."""
    blocks = []
    paragraph = []
    lines = markdown.replace('\r\n', '\n').split('\n')

    def flush():
        if paragraph:
            blocks.append(_block('paragraph', '\n'.join(paragraph)))
            del paragraph[:]

    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        fence = re.match(r'```\s*([\w#+ -]*)\Z', line)
        if fence:
            flush()
            code = []
            while index < len(lines) and lines[index].strip() != '```':
                code.append(lines[index])
                index += 1
            index += 1
            language = fence.group(1).strip().lower()
            blocks.append(_block('code', '\n'.join(code), language=language if language in _CODE_LANGUAGES else 'plain text'))
            continue
        if not line.strip():
            flush()
            continue
        if re.match(r'(-{3,}|\*{3,})\s*\Z', line):
            flush()
            blocks.append({'object': 'block', 'type': 'divider', 'divider': {}})
            continue
        for pattern, kind, extra in _PREFIXES:
            match = pattern.match(line)
            if match:
                flush()
                blocks.append(_block(kind, match.group(1), **extra))
                break
        else:
            paragraph.append(line)
    flush()
    if len(blocks) > MAX_BLOCKS_PER_APPEND:
        raise InvalidRequest('Notion accepts at most 100 blocks at a time. Split the text into smaller parts.')
    return blocks


# Parameter validation -------------------------------------------------------------

def _check_text(params, key, minimum, maximum, required):
    if key not in params:
        if required:
            raise InvalidRequest('The %s is required.' % key.replace('_', ' '))
        return None
    value = params[key]
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise InvalidRequest('The %s must be text of %d to %d characters.' % (key.replace('_', ' '), minimum, maximum))
    return value


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
        if rule.get('type') == 'string':
            _check_text(params, key, rule.get('minLength', 0), rule['maxLength'], key in schema['required'])
    if spec['name'] == 'notion.page.update_properties':
        properties = params['properties']
        if not isinstance(properties, dict) or not 1 <= len(properties) <= 25:
            raise InvalidRequest('Give 1 to 25 properties to update.')
        for name, value in properties.items():
            ok = (value is None or isinstance(value, (bool, int, float))
                  or isinstance(value, str) and len(value) <= MAX_RICH_TEXT
                  or isinstance(value, list) and len(value) <= 100
                  and all(isinstance(v, str) and len(v) <= 100 for v in value))
            if len(name) > 100 or not ok:
                raise InvalidRequest('Property values must be text, a number, true or false, or a list of names.')


def _property_value(kind, value):
    """A simple value as a Notion property value for a property of type `kind`."""
    is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind in ('title', 'rich_text') and isinstance(value, str):
        return {kind: [{'type': 'text', 'text': {'content': value}}]}
    if kind in ('select', 'status') and isinstance(value, str):
        return {kind: {'name': value}}
    if kind in ('select', 'date', 'url', 'email', 'phone_number', 'number') and value is None:
        return {kind: None}
    if kind == 'multi_select' and isinstance(value, list):
        return {kind: [{'name': name} for name in value]}
    if kind == 'number' and is_number:
        return {kind: value}
    if kind == 'checkbox' and isinstance(value, bool):
        return {kind: value}
    if kind == 'date' and isinstance(value, str):
        return {kind: {'start': value}}
    if kind in ('url', 'email', 'phone_number') and isinstance(value, str):
        return {kind: value}
    return None


# Cursors ----------------------------------------------------------------------

def _encode_cursor(data):
    raw = json.dumps(data, separators=(',', ':'), sort_keys=True).encode('utf-8')
    cursor = base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
    if len(cursor) > MAX_CURSOR:
        raise InvalidResponse('Notion sent a page position Interspace cannot keep.')
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


# Connector ----------------------------------------------------------------------

class Connector:
    app = 'notion'
    kinds = ('page', 'database', 'block')
    max_read_chars = 200000

    def __init__(self, *, http, credentials, journal, clock=time.time):
        self.http = http
        self.credentials = credentials
        self.journal = journal
        self.clock = clock

    # Requests -----------------------------------------------------------------

    def _token(self):
        secret = self.credentials.get()
        token = secret.get('access_token') if isinstance(secret, dict) else None
        if not isinstance(token, str) or not token:
            raise NotSignedIn('Sign in to Notion first.')
        return token

    def _call(self, token, method, path, *, params=None, body=None, write=False):
        headers = {'Authorization': 'Bearer ' + token, 'Notion-Version': NOTION_VERSION}
        response = self.http.request(method, API + path, headers=headers, params=params, json=body)
        status = response.status
        if 200 <= status < 300:
            return _obj(response.json())
        if status == 401:
            raise AuthExpired('Notion no longer accepts the saved token. Sign in to Notion again.')
        if status == 403:
            raise Forbidden('Notion did not allow this. Check the connection’s capabilities in Notion.')
        if status == 404:
            raise NotFound('Notion could not find this item, or it is not shared with the Interspace connection.')
        if status in (409, 412):
            raise Conflict('The item changed in Notion meanwhile. Reload it and try again.')
        if status in (429, 529):
            retry = response.headers.get('retry-after', '')
            raise RateLimited('Notion is limiting requests. Try again shortly.',
                              retry_after_s=int(retry) if retry.isdigit() else None)
        if status in (400, 422):
            raise InvalidRequest('Notion rejected the request as invalid.')
        if status >= 500:
            if write:
                raise OutcomeUnknown('Notion failed while making this change; it may or may not have happened.')
            raise Unavailable('Notion is unavailable right now. Try again later.')
        raise InvalidResponse('Notion sent an unexpected reply.')

    def _read_step(self, token, method, path, **kwargs):
        """A read made as the first step of a write: its failures never leave a write unknown."""
        try:
            return self._call(token, method, path, **kwargs)
        except Unavailable as error:
            error.request_sent = False
            raise

    def _id(self, ref, kinds):
        _, kind, ident = parse_ref(ref, 'notion')
        if kind not in kinds or not _ID.match(ident.replace('-', '')):
            raise InvalidRequest('That Notion item reference is not valid here.')
        return kind, ident

    def _data_sources(self, token, database_id, step=False):
        call = self._read_step if step else self._call
        sources = _field(call(token, 'GET', '/databases/' + database_id), 'data_sources', list)
        ids = [_remote_id(source) for source in sources]
        if not ids:
            raise InvalidResponse('This Notion database has no data source to use.')
        return ids

    # Auth ---------------------------------------------------------------------

    def _status(self, state, account=None, detail=''):
        return {'v': 1, 'app': self.app, 'state': state, 'account': account,
                'granted': list(GRANTED) if state == 'signed_in' else [], 'detail': detail,
                'checked_at': iso_time(self.clock())}

    def _signed_in(self, me):
        bot = me.get('bot') if isinstance(me.get('bot'), dict) else {}
        label = bot.get('workspace_name') if isinstance(bot.get('workspace_name'), str) else None
        label = label or _opt(me, 'name', str) or 'Notion'
        return self._status('signed_in', {'label': _truncate(label, MAX_TITLE), 'id': _remote_id(me)})

    def status(self):
        try:
            token = self._token()
        except NotSignedIn:
            return self._status('signed_out')
        except CredentialStoreUnavailable as error:
            return self._status('unavailable', detail=str(error))
        try:
            return self._signed_in(self._call(token, 'GET', '/users/me'))
        except (AuthExpired, Forbidden):
            return self._status('expired', detail='Notion no longer accepts the saved token. Sign in to Notion again.')
        except SpaceError:
            return self._status('unavailable', detail='Notion cannot be reached right now. Check the connection and try again.')

    def begin_sign_in(self, params):
        return {'v': 1, 'app': self.app, 'kind': 'token_entry', 'label': 'Notion connection token',
                'help_url': HELP_URL, 'pattern': TOKEN_PATTERN}

    def complete_sign_in(self, params, cancel):
        if not isinstance(params, dict) or set(params) != {'token'}:
            raise InvalidRequest('Paste the Notion token to continue.')
        token = params['token']
        if not isinstance(token, str) or not re.match(TOKEN_PATTERN, token):
            raise InvalidRequest('That does not look like a Notion token. Copy it again from Notion.')
        cancelled = lambda: cancel is not None and cancel.is_set()  # noqa: E731
        if cancelled():
            raise SignInCancelled('Sign-in was cancelled.')
        try:
            me = self._call(token, 'GET', '/users/me')
        except (AuthExpired, Forbidden):
            raise InvalidRequest('Notion did not accept this token. Copy it again from the connection settings.') from None
        status = self._signed_in(me)
        if cancelled():
            raise SignInCancelled('Sign-in was cancelled.')
        self.credentials.set({'kind': 'token', 'access_token': token, 'account_id': status['account']['id']})
        return status

    def sign_out(self):
        # Notion has no revocation endpoint for connection tokens; revoke them in Notion's settings.
        self.credentials.delete()
        return self._status('signed_out')

    # Read ---------------------------------------------------------------------

    def browse(self, parent=None, cursor=None, limit=50):
        _check_limit(limit)
        state = _decode_cursor(cursor, 'browse', p=parent)
        if parent is None:
            token = self._token()
            body = {'page_size': limit, 'sort': {'timestamp': 'last_edited_time', 'direction': 'descending'}}
            if state:
                body['start_cursor'] = state['c']
            items, next_cursor = _list_page(self._call(token, 'POST', '/search', body=body))
            resources = [r for r in map(_search_resource, items) if r]
            return self._page(resources, {'m': 'browse', 'p': None, 'c': next_cursor} if next_cursor else None)
        kind, ident = self._id(parent, ('page', 'database'))
        token = self._token()
        if kind == 'page':
            params = {'page_size': limit}
            if state:
                params['start_cursor'] = state['c']
            items, next_cursor = _list_page(self._call(token, 'GET', '/blocks/%s/children' % ident, params=params))
            resources = [r for r in (_child_resource(item, parent) for item in items) if r]
            return self._page(resources, {'m': 'browse', 'p': parent, 'c': next_cursor} if next_cursor else None)
        sources = self._data_sources(token, ident)
        index = state['ds'] if state else 0
        if not isinstance(index, int) or not 0 <= index < len(sources):
            raise InvalidRequest('That page position is not valid. Start again from the first page.')
        body = {'page_size': limit}
        if state and state.get('c'):
            body['start_cursor'] = state['c']
        items, next_cursor = _list_page(self._call(token, 'POST', '/data_sources/%s/query' % sources[index], body=body))
        resources = [_page_resource(item) for item in items if item.get('object') == 'page']
        for resource in resources:
            resource['parent'] = parent
        if next_cursor:
            following = {'m': 'browse', 'p': parent, 'ds': index, 'c': next_cursor}
        elif index + 1 < len(sources):
            following = {'m': 'browse', 'p': parent, 'ds': index + 1, 'c': None}
        else:
            following = None
        return self._page(resources, following)

    def _page(self, items, following):
        return {'v': 1, 'items': items, 'next_cursor': _encode_cursor(following) if following else None}

    def search(self, query, kinds=None, cursor=None, limit=25):
        _check_limit(limit)
        if not isinstance(query, str) or not 1 <= len(query) <= 500:
            raise InvalidRequest('Search text must be 1 to 500 characters.')
        if kinds is not None:
            if not isinstance(kinds, (list, tuple)) or not kinds or not set(kinds) <= set(self.kinds):
                raise InvalidRequest('Notion can search pages and databases only.')
        wanted = set(kinds or self.kinds) & {'page', 'database'}
        state = _decode_cursor(cursor, 'search', q=query, k=sorted(wanted))
        if not wanted:
            return self._page([], None)   # blocks are not searchable
        body = {'query': query, 'page_size': limit}
        if wanted != {'page', 'database'}:
            body['filter'] = {'property': 'object', 'value': 'page' if 'page' in wanted else 'data_source'}
        if state:
            body['start_cursor'] = state['c']
        items, next_cursor = _list_page(self._call(self._token(), 'POST', '/search', body=body))
        resources = [r for r in map(_search_resource, items) if r and r['kind'] in wanted]
        following = {'m': 'search', 'q': query, 'k': sorted(wanted), 'c': next_cursor} if next_cursor else None
        return self._page(resources, following)

    def read(self, ref, cursor=None):
        kind, ident = self._id(ref, self.kinds)
        state = _decode_cursor(cursor, 'read', r=ref)
        token = self._token()
        if kind == 'database':
            if state:
                raise InvalidRequest('That page position is not valid. Start again from the first page.')
            return self._read_database(token, ref, ident)
        if kind == 'block':
            if state:
                raise InvalidRequest('That page position is not valid. Start again from the first page.')
            block = self._call(token, 'GET', '/blocks/' + ident)
            return self._content(ref, _field(block, 'type', str), 'markdown', _block_markdown(block), None,
                                 _time(block, 'last_edited_time'), None, {}, _parent_ref(block.get('parent')))
        page = self._call(token, 'GET', '/pages/' + ident)
        title = _page_title(page)
        version = _time(page, 'last_edited_time')
        text = '' if state else '# %s\n\n' % title
        notion_cursor, skip, offset = (state.get('c'), state.get('s'), state.get('o')) if state else (None, 0, 0)
        if not (isinstance(skip, int) and isinstance(offset, int) and skip >= 0 and offset >= 0
                and (notion_cursor is None or isinstance(notion_cursor, str))):
            raise InvalidRequest('That page position is not valid. Start again from the first page.')
        following = None
        previous_list = bool(state and state.get('l') is True)
        for _ in range(MAX_BLOCK_REQUESTS_PER_READ):
            params = {'page_size': 100}
            if notion_cursor:
                params['start_cursor'] = notion_cursor
            blocks, next_cursor = _list_page(self._call(token, 'GET', '/blocks/%s/children' % ident, params=params))
            part, stopped = _render_blocks(blocks, skip, offset, self.max_read_chars - len(text), previous_list, not text)
            text += part
            if stopped:
                index = stopped[0]
                list_before = blocks[index - 1].get('type') in _LIST_TYPES if index > skip else previous_list
                following = {'m': 'read', 'r': ref, 'c': notion_cursor, 's': index, 'o': stopped[1], 'l': list_before}
                break
            if not next_cursor:
                break
            previous_list = bool(blocks) and blocks[-1].get('type') in _LIST_TYPES
            notion_cursor, skip, offset = next_cursor, 0, 0
        else:
            following = {'m': 'read', 'r': ref, 'c': notion_cursor, 's': 0, 'o': 0, 'l': previous_list}
        return self._content(ref, title, 'markdown', text, following, version, _url(page), _meta(page),
                             _parent_ref(page.get('parent')))

    def _read_database(self, token, ref, ident):
        database = self._call(token, 'GET', '/databases/' + ident)
        sources = [{'id': _remote_id(s), 'name': _opt(s, 'name', str) or ''}
                   for s in _field(database, 'data_sources', list)]
        properties = {}
        if sources:
            schema = _field(self._call(token, 'GET', '/data_sources/' + sources[0]['id']), 'properties', dict)
            for name, prop in schema.items():
                kind = _field(prop, 'type', str)
                entry = {'type': kind}
                options = prop.get(kind, {}).get('options') if isinstance(prop.get(kind), dict) else None
                if isinstance(options, list):
                    entry['options'] = [_field(o, 'name', str) for o in options]
                properties[name] = entry
        title = _plain(database.get('title'))
        text = json.dumps({'title': title, 'data_sources': sources, 'properties': properties},
                          ensure_ascii=False, sort_keys=True, indent=1)
        return self._content(ref, title, 'json', text[:self.max_read_chars], None,
                             _time(database, 'last_edited_time'), _url(database), {},
                             _parent_ref(database.get('parent')))

    def _content(self, ref, title, fmt, text, following, version, url, meta, parent):
        # `parent` (nearest parent ref or None) is the coordinator's additive field for scope `parents` chains.
        return {'parent': parent, 'v': 1, 'ref': ref, 'title': _truncate(title, MAX_TITLE), 'format': fmt, 'text': text,
                'truncated': following is not None, 'next_cursor': _encode_cursor(following) if following else None,
                'version': version, 'url': url, 'meta': meta}

    # Write --------------------------------------------------------------------

    def actions(self):
        return json.loads(json.dumps(ACTIONS))

    def write(self, action, ref, params, idempotency_key):
        spec = _ACTIONS.get(action)
        if spec is None:
            raise InvalidRequest('Notion has no such action.')
        _, ident = self._id(ref, (spec['target_kind'],))
        _check_params(spec, params)
        prepared = markdown_blocks(params['markdown']) if params.get('markdown') else []
        check_idempotency_key(idempotency_key)
        token = self._token()
        perform = getattr(self, '_' + action.split('.', 1)[1].replace('.', '_'))
        return journaled_write(self.journal, key=idempotency_key, app=self.app, action=action, ref=ref, params=params,
                               perform=lambda: perform(token, ref, ident, params, prepared))

    def _result(self, action, ref, result_ref, url, version, summary):
        return {'v': 1, 'ok': True, 'action': action, 'ref': ref, 'result_ref': result_ref, 'url': url,
                'version': version, 'replayed': False, 'summary': _truncate(summary, 300)}

    def _database_create_page(self, token, ref, ident, params, blocks):
        """Two steps: read the database's data sources, then create the page. Stopping after the read is safe."""
        source = self._data_sources(token, ident, step=True)[0]
        body = {'parent': {'type': 'data_source_id', 'data_source_id': source},
                'properties': {'title': {'title': [{'type': 'text', 'text': {'content': params['title']}}]}}}
        if blocks:
            body['children'] = blocks
        page = self._call(token, 'POST', '/pages', body=body, write=True)
        return self._result('notion.database.create_page', ref, make_ref('notion', 'page', _remote_id(page)),
                            _url(page), _time(page, 'last_edited_time'), 'Created page "%s".' % _truncate(params['title'], 200))

    def _page_append(self, token, ref, ident, params, blocks):
        reply = self._call(token, 'PATCH', '/blocks/%s/children' % ident, body={'children': blocks}, write=True)
        _field(reply, 'results', list)
        return self._result('notion.page.append', ref, ref, None, None,
                            'Appended %d block%s to the page.' % (len(blocks), '' if len(blocks) == 1 else 's'))

    def _page_update_properties(self, token, ref, ident, params, blocks):
        """Two steps: read the page (types and version), then update it. Stopping after the read is safe."""
        page = self._read_step(token, 'GET', '/pages/' + ident)
        try:
            same = parse_time(params['base_version']) == parse_time(_field(page, 'last_edited_time', str))
        except InvalidResponse:
            raise InvalidRequest('The base version is not a version from Notion.') from None
        if not same:
            raise Conflict('The page changed in Notion since it was read. Read it again before updating.')
        current = _field(page, 'properties', dict)
        update = {}
        for name, value in params['properties'].items():
            prop = current.get(name)
            if not isinstance(prop, dict):
                raise InvalidRequest('The page has no property with that name.')
            converted = _property_value(prop.get('type'), value)
            if converted is None:
                raise InvalidRequest('A property value does not fit its Notion property type.')
            update[name] = converted
        updated = self._call(token, 'PATCH', '/pages/' + ident, body={'properties': update}, write=True)
        count = len(update)
        return self._result('notion.page.update_properties', ref, ref, _url(updated), _time(updated, 'last_edited_time'),
                            'Updated %d propert%s.' % (count, 'y' if count == 1 else 'ies'))

    def _page_comment(self, token, ref, ident, params, blocks):
        reply = self._call(token, 'POST', '/comments', write=True, body={
            'parent': {'page_id': ident}, 'rich_text': [{'type': 'text', 'text': {'content': params['text']}}]})
        _remote_id(reply)
        return self._result('notion.page.comment', ref, ref, None, None, 'Added a comment.')

    def _page_archive(self, token, ref, ident, params, blocks):
        page = self._call(token, 'PATCH', '/pages/' + ident, body={'in_trash': True}, write=True)
        return self._result('notion.page.archive', ref, ref, _url(page), _time(page, 'last_edited_time'),
                            'Moved "%s" to the Notion trash.' % _truncate(_page_title(page), 200))

    # Changes ------------------------------------------------------------------

    def changes(self, cursor=None, limit=100):
        """Poll search, newest edit first, back to the cursor's time.

        The cursor keeps `since` (minute precision, as Notion rounds edit
        times) and the IDs already reported at exactly that time.
        """
        _check_limit(limit)
        if cursor is None:
            now = self.clock()
            return {'v': 1, 'items': [], 'complete': True,
                    'cursor': _encode_cursor({'m': 'changes', 'since': iso_time(now - now % 60), 'seen': []})}
        state = _decode_cursor(cursor, 'changes')
        try:
            since = parse_time(state['since'])
            seen = set(state['seen'])
            high = parse_time(state['high']) if state.get('high') else None
            high_seen = set(state.get('hseen') or [])
        except (KeyError, TypeError, InvalidResponse):
            raise InvalidRequest('That change position is not valid.') from None
        body = {'page_size': limit, 'sort': {'timestamp': 'last_edited_time', 'direction': 'descending'}}
        if state.get('c'):
            body['start_cursor'] = state['c']
        results, next_cursor = _list_page(self._call(self._token(), 'POST', '/search', body=body))
        items = []
        reached_end = next_cursor is None
        for result in results:
            resource = _search_resource(result)
            if resource is None:
                continue
            edited = parse_time(resource['updated_at'])
            if edited < since:
                reached_end = True
                break
            ident = resource['ref'].split(':', 2)[2].replace('-', '')
            if edited == since and ident in seen:
                continue
            if high is None or edited > high:
                high, high_seen = edited, set()
            if edited == high:
                high_seen.add(ident)
            created = result.get('created_time')
            change = 'created' if isinstance(created, str) and parse_time(created) >= since else 'updated'
            items.append({'ref': resource['ref'], 'change': change, 'at': resource['updated_at'], 'title': resource['title']})
        if reached_end:
            if high is None or high == since:
                following = {'m': 'changes', 'since': iso_time(since), 'seen': sorted(seen | high_seen)[:MAX_SEEN_IDS]}
            else:
                following = {'m': 'changes', 'since': iso_time(high), 'seen': sorted(high_seen)[:MAX_SEEN_IDS]}
        else:
            following = {'m': 'changes', 'since': state['since'], 'seen': state['seen'], 'c': next_cursor,
                         'high': iso_time(high) if high is not None else None, 'hseen': sorted(high_seen)[:MAX_SEEN_IDS]}
        return {'v': 1, 'items': items, 'cursor': _encode_cursor(following), 'complete': reached_end}
