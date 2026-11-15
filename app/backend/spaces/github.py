"""GitHub connector (contract: connectors.md; route: docs/research/connector-auth.md).

Route: the GitHub REST API (`api.github.com`, `X-GitHub-Api-Version: 2022-11-28`)
with a pasted fine-grained personal access token (`token_entry` sign-in).
Classic tokens are refused because they carry broad scopes. No OAuth app and
no client ID ship with Interspace.

Route details the Connector API hides:
- Reference IDs: `owner/name` (repo), `owner/name#12` (issue, pull),
  `owner/name@branch` (branch) and `owner/name@branch:path` (file or folder;
  folders are `file` resources with `meta.type == "dir"`).
- Browsing the roots lists the repositories the token can see, newest update
  first. A repository's first page leads with its default branch, then lists
  open issues and pull requests, newest update first. A branch or folder
  lists its files.
- Search uses GitHub's own search syntax, passed through unchanged, with an
  `is:issue` or `is:pr` qualifier added. When several kinds are wanted, the
  limit is shared between one search per kind; files and branches are not
  searchable.
- Reading an issue or pull request renders its body and conversation
  comments as Markdown (up to 1,000 comments; review comments on code are not
  included). A continuation read fetches the item again and fails if it
  changed meanwhile.
- `changes` polls `GET /issues?filter=all&state=all&since=…`, newest update
  first: issues and pull requests in every repository the token can see.
  Pushes, new repositories and deletions are not reported. If items are
  updated while a batch is being paged, an item can be reported twice.
- Sign-out removes the token from the Keychain only. GitHub's token
  revocation endpoint is meant for leaked credentials, so the user deletes the
  token in GitHub's settings.
"""
import base64
import binascii
import hashlib
import json
import re
import time

from spaces.base import (
    AuthExpired, Conflict, CredentialStoreUnavailable, Forbidden, InvalidRequest, InvalidResponse, NotFound,
    NotSignedIn, OutcomeUnknown, RateLimited, SignInCancelled, SpaceError, Unavailable,
    check_idempotency_key, iso_time, journaled_write, make_ref, parse_ref, parse_time,
)

API = 'https://api.github.com'
WEB = 'https://github.com/'
API_VERSION = '2022-11-28'
TOKEN_PATTERN = '^github_pat_[A-Za-z0-9_]{20,255}$'
HELP_URL = ('https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/'
            'managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token')
# Fine-grained tokens do not report their permissions; a missing one surfaces as Forbidden on use. PROVISIONAL(0C-2)
GRANTED = ['repo:read', 'contents:read', 'issues:write', 'pulls:write']

MAX_TITLE = 300
MAX_META_STRING = 200
MAX_CURSOR = 2048
MAX_COMMENT_PAGES = 10
MAX_SEEN = 12
MAX_BODY = 65536
_OWNER = r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})'
_NAME = r'[A-Za-z0-9._-]{1,100}'
_REPO = re.compile(r'(%s)/(%s)\Z' % (_OWNER, _NAME))
_NUMBERED = re.compile(r'(%s/%s)#([1-9][0-9]{0,9})\Z' % (_OWNER, _NAME))
_BAD_BRANCH = re.compile(r'[\x00-\x20\x7f~^:?*\[\\]|\.\.|@\{|//|^[/.-]|[/.]$|\.lock$')
_CONTROL = re.compile(r'[\x00-\x1f\x7f]')
_SAFE = frozenset(b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~')
_SEARCH_KINDS = ('repo', 'issue', 'pull')


def _schema(description, properties, required):
    return {'type': 'object', 'additionalProperties': False, 'description': description,
            'properties': properties, 'required': required}


_TITLE = {'type': 'string', 'minLength': 1, 'maxLength': 256}
_BODY = {'type': 'string', 'maxLength': MAX_BODY}
_COMMENT = {'type': 'string', 'minLength': 1, 'maxLength': MAX_BODY}
_LABELS = {'type': 'array', 'maxItems': 20, 'items': {'type': 'string', 'minLength': 1, 'maxLength': 50}}
_BRANCH_NAME = {'type': 'string', 'minLength': 1, 'maxLength': 255}

ACTIONS = (
    {'name': 'github.repo.create_issue', 'title': 'Create issue', 'target_kind': 'repo',
     'effect': 'create', 'requires_version': False,
     'params_schema': _schema('Open a new issue in a GitHub repository, with an optional Markdown body and labels.', {
         'title': _TITLE, 'body': _BODY, 'labels': _LABELS}, ['title'])},
    {'name': 'github.issue.comment', 'title': 'Comment on issue', 'target_kind': 'issue',
     'effect': 'create', 'requires_version': False,
     'params_schema': _schema('Add a Markdown comment to a GitHub issue.', {'body': _COMMENT}, ['body'])},
    {'name': 'github.issue.update', 'title': 'Edit issue', 'target_kind': 'issue',
     'effect': 'update', 'requires_version': True,
     'params_schema': _schema(
         'Change the title, body or labels of a GitHub issue. `labels` replaces the whole label list. '
         '`base_version` is the version from the last read.', {
             'title': _TITLE, 'body': _BODY, 'labels': _LABELS,
             'base_version': {'type': 'string', 'minLength': 1, 'maxLength': 64}}, ['base_version'])},
    {'name': 'github.issue.close', 'title': 'Close issue', 'target_kind': 'issue',
     'effect': 'destructive', 'requires_version': False,
     'params_schema': _schema('Close a GitHub issue as completed (default) or not planned.', {
         'reason': {'type': 'string', 'enum': ['completed', 'not_planned'], 'maxLength': 16}}, [])},
    {'name': 'github.pull.comment', 'title': 'Comment on pull request', 'target_kind': 'pull',
     'effect': 'create', 'requires_version': False,
     'params_schema': _schema('Add a Markdown comment to a GitHub pull request conversation.', {'body': _COMMENT}, ['body'])},
    {'name': 'github.repo.create_pull', 'title': 'Open pull request', 'target_kind': 'repo',
     'effect': 'create', 'requires_version': False,
     'params_schema': _schema(
         'Open a pull request from a branch already pushed to GitHub (`head`) into `base`.', {
             'title': _TITLE, 'head': _BRANCH_NAME, 'base': _BRANCH_NAME, 'body': _BODY, 'draft': {'type': 'boolean'}},
         ['title', 'head', 'base'])},
)
_ACTIONS = {spec['name']: spec for spec in ACTIONS}


# Remote JSON validation ---------------------------------------------------------

def _bad():
    return InvalidResponse('GitHub sent a reply Interspace could not read.')


def _obj(value):
    if not isinstance(value, dict):
        raise _bad()
    return value


def _list(value):
    if not isinstance(value, list):
        raise _bad()
    return [_obj(item) for item in value]


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


def _time(value, key):
    return iso_time(parse_time(_field(value, key, str)))


def _truncate(text, limit):
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _number(value):
    number = _field(value, 'number', int)
    if number < 1:
        raise _bad()
    return number


def _web_url(value, key='html_url'):
    url = _opt(value, key, str)
    return url if url and url.startswith(WEB) else None


def _login(value):
    user = _obj(value).get('user')
    login = user.get('login') if isinstance(user, dict) else None
    return login if isinstance(login, str) else 'ghost'


def _quote(text, safe='/'):
    keep = _SAFE | frozenset(safe.encode('ascii'))
    return ''.join(chr(b) if b in keep else '%%%02X' % b for b in text.encode('utf-8'))


def _next_page(response):
    return 'rel="next"' in str(response.headers.get('link', ''))


# References ---------------------------------------------------------------------

def _repo_ok(full):
    match = _REPO.match(full) if isinstance(full, str) else None
    return bool(match) and match.group(2) not in ('.', '..')


def _branch_ok(name):
    return isinstance(name, str) and 1 <= len(name) <= 255 and not _BAD_BRANCH.search(name)


def _path_ok(path):
    return (isinstance(path, str) and 1 <= len(path) <= 400 and not _CONTROL.search(path)
            and all(part not in ('', '.', '..') for part in path.split('/')))


def _remote_repo(full):
    if not _repo_ok(full):
        raise _bad()
    return full


def _repo_of(item):
    """`owner/name` from an issue's `repository_url`."""
    url = _field(item, 'repository_url', str)
    prefix = API + '/repos/'
    if not url.startswith(prefix):
        raise _bad()
    return _remote_repo(url[len(prefix):])


def _parse(ref, kinds):
    """(kind, repo, extra) for a GitHub ref: extra is the number, the branch, or (branch, path)."""
    _, kind, ident = parse_ref(ref, 'github')
    invalid = InvalidRequest('That GitHub reference is not valid here.')
    if kind not in kinds:
        raise invalid
    if kind == 'repo':
        if not _repo_ok(ident):
            raise invalid
        return kind, ident, None
    if kind in ('issue', 'pull'):
        match = _NUMBERED.match(ident)
        if not match or not _repo_ok(match.group(1)):
            raise invalid
        return kind, match.group(1), int(match.group(2))
    repo, _, rest = ident.partition('@')
    if not _repo_ok(repo):
        raise invalid
    if kind == 'branch':
        if not _branch_ok(rest):
            raise invalid
        return kind, repo, rest
    branch, colon, path = rest.partition(':')
    if not colon or not _branch_ok(branch) or not _path_ok(path):
        raise invalid
    return kind, repo, (branch, path)


def _branch_ref(repo, branch):
    return make_ref('github', 'branch', '%s@%s' % (repo, branch))


def _file_ref(repo, branch, path):
    return make_ref('github', 'file', '%s@%s:%s' % (repo, branch, path))


def _file_parent(repo, branch, path):
    folder = path.rpartition('/')[0]
    return _file_ref(repo, branch, folder) if folder else _branch_ref(repo, branch)


# Resources ----------------------------------------------------------------------

def _meta(**values):
    meta = {}
    for key, value in values.items():
        if isinstance(value, str):
            meta[key] = _truncate(value, MAX_META_STRING)
        elif isinstance(value, (bool, int, float)):
            meta[key] = value
    return meta


def _repo_meta(repo):
    return _meta(private=repo.get('private'), description=repo.get('description') or None,
                 language=repo.get('language'), open_issues=repo.get('open_issues_count')
                 if not isinstance(repo.get('open_issues_count'), bool) else None,
                 default_branch=repo.get('default_branch'), archived=repo.get('archived'))


def _repo_resource(repo):
    full = _remote_repo(_field(repo, 'full_name', str))
    return {'ref': make_ref('github', 'repo', full), 'kind': 'repo', 'title': _truncate(full, MAX_TITLE),
            'parent': None, 'url': _web_url(repo), 'updated_at': _time(repo, 'updated_at'), 'has_children': True,
            'meta': _repo_meta(repo)}


def _labels(item):
    labels = _obj(item).get('labels')
    if not isinstance(labels, list):
        return None
    names = [label['name'] for label in labels if isinstance(label, dict) and isinstance(label.get('name'), str)]
    return ', '.join(names) or None


def _issue_meta(item, kind):
    comments = item.get('comments')
    meta = _meta(number=_number(item), state=_field(item, 'state', str), author=_login(item),
                 comments=comments if isinstance(comments, int) and not isinstance(comments, bool) else None,
                 labels=_labels(item))
    if kind == 'pull' and isinstance(item.get('head'), dict):
        head, base_branch = item['head'].get('ref'), _obj(item.get('base')).get('ref')
        meta.update(_meta(head=head, base=base_branch, draft=item.get('draft') is True, merged=item.get('merged') is True))
    return meta


def _issue_resource(item, kind=None, repo=None):
    kind = kind or ('pull' if isinstance(item.get('pull_request'), dict) else 'issue')
    repo = repo or _repo_of(item)
    number = _number(item)
    return {'ref': make_ref('github', kind, '%s#%d' % (repo, number)), 'kind': kind,
            'title': _truncate(_field(item, 'title', str), MAX_TITLE), 'parent': make_ref('github', 'repo', repo),
            'url': _web_url(item), 'updated_at': _time(item, 'updated_at'), 'has_children': False,
            'meta': _issue_meta(item, kind)}


def _branch_resource(repo, branch, default=False):
    return {'ref': _branch_ref(repo, branch), 'kind': 'branch', 'title': _truncate(branch, MAX_TITLE),
            'parent': make_ref('github', 'repo', repo), 'url': WEB + repo + '/tree/' + _quote(branch),
            'updated_at': None, 'has_children': True, 'meta': {'default': default}}


def _entry_resource(entry, repo, branch, parent):
    path = _field(entry, 'path', str)
    kind = _field(entry, 'type', str)
    if not _path_ok(path):
        raise _bad()
    meta = {'type': _truncate(kind, MAX_META_STRING)}
    if kind == 'file':
        size = entry.get('size')
        if isinstance(size, int) and not isinstance(size, bool):
            meta['size'] = size
    return {'ref': _file_ref(repo, branch, path), 'kind': 'file',
            'title': _truncate(_field(entry, 'name', str), MAX_TITLE), 'parent': parent, 'url': _web_url(entry),
            'updated_at': None, 'has_children': kind == 'dir', 'meta': meta}


def _issue_markdown(item, kind):
    number = _number(item)
    state = _field(item, 'state', str)
    if kind == 'pull':
        if item.get('merged') is True:
            label = 'Merged pull request'
        elif state != 'open':
            label = 'Closed pull request'
        else:
            label = 'Draft pull request' if item.get('draft') is True else 'Open pull request'
    else:
        label = ('Open' if state == 'open' else 'Closed') + ' issue'
    line = '%s by @%s' % (label, _login(item))
    labels = _labels(item)
    if labels:
        line += ' · Labels: ' + labels
    if kind == 'pull' and isinstance(item.get('head'), dict):
        head, base_branch = item['head'].get('ref'), _obj(item.get('base')).get('ref')
        if isinstance(head, str) and isinstance(base_branch, str):
            line += ' · %s into %s' % (head, base_branch)
    body = _opt(item, 'body', str) or '_No description._'
    return '# %s (#%d)\n\n%s\n\n%s\n' % (_field(item, 'title', str), number, line, body.rstrip())


def _comment_markdown(comment):
    body = _opt(comment, 'body', str) or ''
    return '\n---\n\n**@%s** commented on %s:\n\n%s\n' % (_login(comment), _time(comment, 'created_at')[:10], body.rstrip())


def _decode_file(entry):
    """(text, reason): text of a file entry, or None and why it cannot be shown."""
    if entry.get('type') != 'file':
        return None, 'This entry is a %s, not a file.' % _truncate(str(entry.get('type')), 40)
    content = _opt(entry, 'content', str) or ''
    if entry.get('encoding') != 'base64' or not content and (entry.get('size') or 0) > 0:
        return None, 'This file is too large to read here (over 1 MB). Open it on GitHub.'
    try:
        text = base64.b64decode(content).decode('utf-8')
    except (binascii.Error, ValueError):
        return None, 'This file is not text.'
    if '\x00' in text:
        return None, 'This file is not text.'
    return text, None


# Parameters and cursors ---------------------------------------------------------

def _check_value(key, rule, value):
    name = key.replace('_', ' ')
    kind = rule.get('type')
    if kind == 'string':
        if not isinstance(value, str) or not rule.get('minLength', 0) <= len(value) <= rule['maxLength']:
            raise InvalidRequest('The %s must be text of %d to %d characters.' % (name, rule.get('minLength', 0), rule['maxLength']))
        if 'enum' in rule and value not in rule['enum']:
            raise InvalidRequest('The %s must be one of: %s.' % (name, ', '.join(rule['enum'])))
    elif kind == 'boolean':
        if not isinstance(value, bool):
            raise InvalidRequest('The %s must be true or false.' % name)
    elif kind == 'array':
        items = rule['items']
        if (not isinstance(value, list) or len(value) > rule['maxItems']
                or not all(isinstance(v, str) and items['minLength'] <= len(v) <= items['maxLength'] for v in value)):
            raise InvalidRequest('The %s must be a list of at most %d names.' % (name, rule['maxItems']))


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
        _check_value(key, schema['properties'][key], value)
    if spec['name'] == 'github.issue.update' and not set(params) & {'title', 'body', 'labels'}:
        raise InvalidRequest('Give a new title, body or labels.')
    if spec['name'] == 'github.repo.create_pull':
        for key in ('head', 'base'):
            owner, colon, branch = params[key].rpartition(':')
            if not _branch_ok(branch) or colon and (key == 'base' or not re.match(_OWNER + r'\Z', owner)):
                raise InvalidRequest('The %s must be a branch name.' % key)


def _encode_cursor(data):
    raw = json.dumps(data, separators=(',', ':'), sort_keys=True).encode('utf-8')
    cursor = base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
    if len(cursor) > MAX_CURSOR:
        raise InvalidResponse('GitHub sent a page position Interspace cannot keep.')
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


def _positive(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequest('That page position is not valid. Start again from the first page.')
    return value


def _check_limit(limit):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise InvalidRequest('The limit must be a whole number from 1 to 100.')
    return limit


def _since(t):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(int(t)))


# Connector ----------------------------------------------------------------------

class Connector:
    app = 'github'
    kinds = ('repo', 'issue', 'pull', 'file', 'branch')
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
            raise NotSignedIn('Sign in to GitHub first.')
        return token

    def _send(self, token, method, path, *, params=None, body=None, write=False):
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                   'X-GitHub-Api-Version': API_VERSION}
        response = self.http.request(method, API + path, headers=headers, params=params, json=body)
        status = response.status
        if 200 <= status < 300:
            return response
        retry = response.headers.get('retry-after', '')
        retry_after = int(retry) if str(retry).isdigit() else None
        if status == 401:
            raise AuthExpired('GitHub no longer accepts the saved token. Sign in to GitHub again.')
        if status == 403:
            if str(response.headers.get('x-ratelimit-remaining', '')) == '0':
                reset = str(response.headers.get('x-ratelimit-reset', ''))
                wait = max(0, int(reset) - int(self.clock())) if reset.isdigit() else retry_after
                raise RateLimited('GitHub is limiting requests. Try again later.', retry_after_s=wait)
            if retry_after is not None:
                raise RateLimited('GitHub is limiting requests. Try again shortly.', retry_after_s=retry_after)
            raise Forbidden('GitHub did not allow this. Check the token’s repository access and permissions.')
        if status in (404, 410):
            raise NotFound('GitHub could not find this, or the token cannot see it.')
        if status in (409, 412):
            raise Conflict('This changed on GitHub meanwhile. Reload it and try again.')
        if status == 429:
            raise RateLimited('GitHub is limiting requests. Try again shortly.', retry_after_s=retry_after)
        if status in (400, 422):
            raise InvalidRequest('GitHub rejected the request as invalid.')
        if status >= 500:
            if write:
                raise OutcomeUnknown('GitHub failed while making this change; it may or may not have happened.')
            raise Unavailable('GitHub is unavailable right now. Try again later.')
        raise InvalidResponse('GitHub sent an unexpected reply.')

    def _call(self, token, method, path, **kwargs):
        return self._send(token, method, path, **kwargs).json()

    def _read_step(self, token, method, path, **kwargs):
        """A read made as the first step of a write: its failures never leave a write unknown."""
        try:
            return self._call(token, method, path, **kwargs)
        except Unavailable as error:
            error.request_sent = False
            raise

    def _contents(self, token, repo, branch, path):
        suffix = '/' + _quote(path) if path else ''
        return self._call(token, 'GET', '/repos/%s/contents%s' % (repo, suffix), params={'ref': branch})

    # Auth ---------------------------------------------------------------------

    def _status(self, state, account=None, detail=''):
        return {'v': 1, 'app': self.app, 'state': state, 'account': account,
                'granted': list(GRANTED) if state == 'signed_in' else [], 'detail': detail,
                'checked_at': iso_time(self.clock())}

    def _signed_in(self, user):
        login = _field(user, 'login', str)
        return self._status('signed_in', {'label': _truncate(login, MAX_TITLE), 'id': str(_field(user, 'id', int))})

    def status(self):
        try:
            token = self._token()
        except NotSignedIn:
            return self._status('signed_out')
        except CredentialStoreUnavailable as error:
            return self._status('unavailable', detail=str(error))
        try:
            return self._signed_in(_obj(self._call(token, 'GET', '/user')))
        except (AuthExpired, Forbidden):
            return self._status('expired', detail='GitHub no longer accepts the saved token. Sign in to GitHub again.')
        except SpaceError:
            return self._status('unavailable', detail='GitHub cannot be reached right now. Check the connection and try again.')

    def begin_sign_in(self, params):
        return {'v': 1, 'app': self.app, 'kind': 'token_entry', 'label': 'GitHub fine-grained token',
                'help_url': HELP_URL, 'pattern': TOKEN_PATTERN}

    def complete_sign_in(self, params, cancel):
        if not isinstance(params, dict) or set(params) != {'token'}:
            raise InvalidRequest('Paste the GitHub token to continue.')
        token = params['token']
        if not isinstance(token, str) or not re.match(TOKEN_PATTERN, token):
            raise InvalidRequest('That does not look like a GitHub fine-grained token. It starts with github_pat_.')
        cancelled = lambda: cancel is not None and cancel.is_set()  # noqa: E731
        if cancelled():
            raise SignInCancelled('Sign-in was cancelled.')
        try:
            user = _obj(self._call(token, 'GET', '/user'))
        except (AuthExpired, Forbidden):
            raise InvalidRequest('GitHub did not accept this token. Check that it has not expired, then paste it again.') from None
        status = self._signed_in(user)
        if cancelled():
            raise SignInCancelled('Sign-in was cancelled.')
        self.credentials.set({'kind': 'token', 'access_token': token, 'account_id': status['account']['id']})
        return status

    def sign_out(self):
        self.credentials.delete()
        return self._status('signed_out')

    # Read ---------------------------------------------------------------------

    def _page(self, items, following):
        return {'v': 1, 'items': items, 'next_cursor': _encode_cursor(following) if following else None}

    def browse(self, parent=None, cursor=None, limit=50):
        _check_limit(limit)
        state = _decode_cursor(cursor, 'browse', p=parent)
        if parent is None:
            token = self._token()
            if state and state.get('pp') != limit:
                raise InvalidRequest('That page position belongs to a different listing. Start again from the first page.')
            page = _positive(state['pg']) if state else 1
            response = self._send(token, 'GET', '/user/repos', params={'per_page': limit, 'page': page, 'sort': 'updated'})
            items = [_repo_resource(repo) for repo in _list(response.json())]
            following = {'m': 'browse', 'p': None, 'pg': page + 1, 'pp': limit} if _next_page(response) else None
            return self._page(items, following)
        kind, repo, extra = _parse(parent, ('repo', 'branch', 'file'))
        token = self._token()
        if kind == 'repo':
            return self._browse_repo(token, parent, repo, state, limit)
        branch, path = (extra, '') if kind == 'branch' else extra
        listing = self._contents(token, repo, branch, path)
        if not isinstance(listing, list):
            _obj(listing)
            raise InvalidRequest('That is a file, not a folder.')
        offset = _positive(state['o']) if state else 0
        entries = _list(listing)
        items = [_entry_resource(entry, repo, branch, parent) for entry in entries[offset:offset + limit]]
        following = {'m': 'browse', 'p': parent, 'o': offset + limit} if offset + limit < len(entries) else None
        return self._page(items, following)

    def _browse_repo(self, token, parent, repo, state, limit):
        per_page = limit - 1 if limit > 1 else 1
        items = []
        if state is None:
            info = _obj(self._call(token, 'GET', '/repos/' + repo))
            default = _field(info, 'default_branch', str)
            if not _branch_ok(default):
                raise _bad()
            items.append(_branch_resource(repo, default, True))
            if limit == 1:
                return self._page(items, {'m': 'browse', 'p': parent, 'pg': 1, 'pp': per_page})
            page = 1
        else:
            if state.get('pp') != per_page:
                raise InvalidRequest('That page position belongs to a different listing. Start again from the first page.')
            page = _positive(state['pg'])
        response = self._send(token, 'GET', '/repos/%s/issues' % repo, params={
            'state': 'open', 'sort': 'updated', 'direction': 'desc', 'per_page': per_page, 'page': page})
        items.extend(_issue_resource(item, repo=repo) for item in _list(response.json()))
        following = {'m': 'browse', 'p': parent, 'pg': page + 1, 'pp': per_page} if _next_page(response) else None
        return self._page(items, following)

    def search(self, query, kinds=None, cursor=None, limit=25):
        _check_limit(limit)
        if not isinstance(query, str) or not 1 <= len(query) <= 500:
            raise InvalidRequest('Search text must be 1 to 500 characters.')
        if kinds is not None:
            if not isinstance(kinds, (list, tuple)) or not kinds or not set(kinds) <= set(self.kinds):
                raise InvalidRequest('GitHub can search repositories, issues and pull requests only.')
        wanted = [kind for kind in _SEARCH_KINDS if kind in (kinds or self.kinds)]
        state = _decode_cursor(cursor, 'search', q=query, k=wanted, pp=limit)
        if not wanted:
            return self._page([], None)   # files and branches are not searchable
        share, extra = divmod(limit, len(wanted))
        sizes = {kind: share + (1 if index < extra else 0) for index, kind in enumerate(wanted)}
        pages = state['pg'] if state else {kind: 1 for kind in wanted if sizes[kind]}
        if not isinstance(pages, dict) or not set(pages) <= set(wanted):
            raise InvalidRequest('That page position is not valid. Start again from the first page.')
        token = self._token()
        items, following = [], {}
        for kind in wanted:
            if kind not in pages:
                continue
            page = _positive(pages[kind])
            params = {'q': query if kind == 'repo' else query + (' is:issue' if kind == 'issue' else ' is:pr'),
                      'per_page': sizes[kind], 'page': page}
            response = self._send(token, 'GET', '/search/repositories' if kind == 'repo' else '/search/issues', params=params)
            found = _list(_field(response.json(), 'items', list))
            items.extend(_repo_resource(item) if kind == 'repo' else _issue_resource(item, kind) for item in found)
            if _next_page(response):
                following[kind] = page + 1
        return self._page(items, {'m': 'search', 'q': query, 'k': wanted, 'pp': limit, 'pg': following} if following else None)

    def read(self, ref, cursor=None):
        kind, repo, extra = _parse(ref, self.kinds)
        state = _decode_cursor(cursor, 'read', r=ref)
        offset = _positive(state.get('o')) if state else 0
        token = self._token()
        if kind == 'branch':
            if state:
                raise InvalidRequest('That page position is not valid. Start again from the first page.')
            branch = _obj(self._call(token, 'GET', '/repos/%s/branches/%s' % (repo, _quote(extra))))
            sha = _field(_field(branch, 'commit', dict), 'sha', str)
            text = json.dumps({'name': _field(branch, 'name', str), 'commit': sha, 'protected': branch.get('protected') is True},
                              ensure_ascii=False, sort_keys=True, indent=1)
            return self._content(ref, extra, 'json', text, None, sha, WEB + repo + '/tree/' + _quote(extra), {},
                                 make_ref('github', 'repo', repo))
        if kind == 'repo':
            return self._read_repo(token, ref, repo, state, offset)
        if kind == 'file':
            return self._read_file(token, ref, repo, extra, state, offset)
        return self._read_issue(token, ref, kind, repo, extra, state, offset)

    def _check_version(self, state, check):
        if state is not None and state.get('ver') != check:
            raise InvalidRequest('This changed on GitHub since the first part was read. Read it again from the start.')

    def _sliced(self, ref, title, fmt, full, offset, check, version, url, meta, parent):
        end = offset + self.max_read_chars
        following = {'m': 'read', 'r': ref, 'o': end, 'ver': check} if len(full) > end else None
        return self._content(ref, title, fmt, full[offset:end], following, version, url, meta, parent)

    def _read_issue(self, token, ref, kind, repo, number, state, offset):
        path = '/repos/%s/%s/%d' % (repo, 'pulls' if kind == 'pull' else 'issues', number)
        item = _obj(self._call(token, 'GET', path))
        version = _time(item, 'updated_at')
        self._check_version(state, version)
        text = _issue_markdown(item, kind)
        comments = item.get('comments')
        if isinstance(comments, int) and comments > 0:
            for page in range(1, MAX_COMMENT_PAGES + 1):
                response = self._send(token, 'GET', '/repos/%s/issues/%d/comments' % (repo, number),
                                      params={'per_page': 100, 'page': page})
                text += ''.join(_comment_markdown(comment) for comment in _list(response.json()))
                if not _next_page(response) or len(text) > offset + self.max_read_chars:
                    break
            else:
                text += '\n---\n\n[More comments on GitHub]\n'
        resource = _issue_resource(item, kind, repo)
        return self._sliced(ref, resource['title'], 'markdown', text, offset, version, version, resource['url'],
                            resource['meta'], resource['parent'])

    def _read_repo(self, token, ref, repo, state, offset):
        info = _obj(self._call(token, 'GET', '/repos/' + repo))
        resource = _repo_resource(info)   # a renamed repository answers under its new name; `ref` stays as asked
        try:
            readme = _obj(self._call(token, 'GET', '/repos/%s/readme' % repo))
        except NotFound:
            readme = None
        check = resource['updated_at'] + ':' + (_opt(readme, 'sha', str) or '' if readme else '')
        self._check_version(state, check)
        text = '# %s\n\n' % repo
        description = _opt(info, 'description', str)
        if description:
            text += description.strip() + '\n\n'
        text += 'Default branch: %s · %d open issues and pull requests\n' % (
            _field(info, 'default_branch', str), _opt(info, 'open_issues_count', int) or 0)
        if readme:
            body, _ = _decode_file(readme)
            if body:
                text += '\n---\n\n' + body
        return self._sliced(ref, repo, 'markdown', text, offset, check, resource['updated_at'], resource['url'],
                            resource['meta'], None)

    def _read_file(self, token, ref, repo, location, state, offset):
        branch, path = location
        parent = _file_parent(repo, branch, path)
        title = path.rpartition('/')[2]
        found = self._contents(token, repo, branch, path)
        if isinstance(found, list):
            names = [_field(entry, 'name', str) + ('/' if entry.get('type') == 'dir' else '') for entry in _list(found)]
            text = ''.join(name + '\n' for name in names)
            check = 'dir:' + hashlib.sha256(text.encode('utf-8')).hexdigest()[:32]
            self._check_version(state, check)
            url = WEB + repo + '/tree/' + _quote(branch) + '/' + _quote(path)
            return self._sliced(ref, title, 'text', text, offset, check, None, url, {'type': 'dir'}, parent)
        entry = _obj(found)
        sha = _field(entry, 'sha', str)
        self._check_version(state, sha)
        text, reason = _decode_file(entry)
        size = entry.get('size') if isinstance(entry.get('size'), int) and not isinstance(entry.get('size'), bool) else None
        meta = _meta(type='file', size=size)
        if text is None:
            meta['reason'] = reason
            return self._content(ref, title, 'unavailable', '', None, sha, _web_url(entry), meta, parent)
        return self._sliced(ref, title, 'text', text, offset, sha, sha, _web_url(entry), meta, parent)

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
            raise InvalidRequest('GitHub has no such action.')
        _, repo, number = _parse(ref, (spec['target_kind'],))
        _check_params(spec, params)
        check_idempotency_key(idempotency_key)
        token = self._token()
        perform = getattr(self, '_' + action.split('.', 1)[1].replace('.', '_'))
        return journaled_write(self.journal, key=idempotency_key, app=self.app, action=action, ref=ref, params=params,
                               perform=lambda: perform(token, ref, repo, number, params))

    def _result(self, action, ref, result_ref, url, version, summary):
        return {'v': 1, 'ok': True, 'action': action, 'ref': ref, 'result_ref': result_ref, 'url': url,
                'version': version, 'replayed': False, 'summary': _truncate(summary, 300)}

    def _repo_create_issue(self, token, ref, repo, _, params):
        body = {key: params[key] for key in ('title', 'body', 'labels') if key in params}
        issue = _obj(self._call(token, 'POST', '/repos/%s/issues' % repo, body=body, write=True))
        number = _number(issue)
        return self._result('github.repo.create_issue', ref, make_ref('github', 'issue', '%s#%d' % (repo, number)),
                            _web_url(issue), _time(issue, 'updated_at'),
                            'Created issue #%d "%s".' % (number, _truncate(params['title'], 200)))

    def _comment(self, token, action, ref, repo, number, params, noun):
        comment = _obj(self._call(token, 'POST', '/repos/%s/issues/%d/comments' % (repo, number),
                                  body={'body': params['body']}, write=True))
        _field(comment, 'id', int)
        return self._result(action, ref, ref, _web_url(comment), None, 'Commented on %s #%d.' % (noun, number))

    def _issue_comment(self, token, ref, repo, number, params):
        return self._comment(token, 'github.issue.comment', ref, repo, number, params, 'issue')

    def _pull_comment(self, token, ref, repo, number, params):
        return self._comment(token, 'github.pull.comment', ref, repo, number, params, 'pull request')

    def _issue_update(self, token, ref, repo, number, params):
        """Two steps: read the issue (version), then edit it. Stopping after the read is safe."""
        current = _obj(self._read_step(token, 'GET', '/repos/%s/issues/%d' % (repo, number)))
        try:
            same = parse_time(params['base_version']) == parse_time(_field(current, 'updated_at', str))
        except InvalidResponse:
            raise InvalidRequest('The base version is not a version from GitHub.') from None
        if not same:
            raise Conflict('The issue changed on GitHub since it was read. Read it again before editing.')
        body = {key: params[key] for key in ('title', 'body', 'labels') if key in params}
        issue = _obj(self._call(token, 'PATCH', '/repos/%s/issues/%d' % (repo, number), body=body, write=True))
        return self._result('github.issue.update', ref, ref, _web_url(issue), _time(issue, 'updated_at'),
                            'Updated issue #%d.' % number)

    def _issue_close(self, token, ref, repo, number, params):
        issue = _obj(self._call(token, 'PATCH', '/repos/%s/issues/%d' % (repo, number), write=True,
                                body={'state': 'closed', 'state_reason': params.get('reason', 'completed')}))
        return self._result('github.issue.close', ref, ref, _web_url(issue), _time(issue, 'updated_at'),
                            'Closed issue #%d.' % number)

    def _repo_create_pull(self, token, ref, repo, _, params):
        body = {key: params[key] for key in ('title', 'head', 'base', 'body', 'draft') if key in params}
        pull = _obj(self._call(token, 'POST', '/repos/%s/pulls' % repo, body=body, write=True))
        number = _number(pull)
        return self._result('github.repo.create_pull', ref, make_ref('github', 'pull', '%s#%d' % (repo, number)),
                            _web_url(pull), _time(pull, 'updated_at'),
                            'Opened pull request #%d "%s".' % (number, _truncate(params['title'], 200)))

    # Changes ------------------------------------------------------------------

    def changes(self, cursor=None, limit=100):
        """Poll issues and pull requests updated since the cursor's time, newest first.

        The cursor keeps `since` (GitHub times have second precision) and the
        items already reported at exactly that time.
        """
        _check_limit(limit)
        if cursor is None:
            return {'v': 1, 'items': [], 'complete': True,
                    'cursor': _encode_cursor({'m': 'changes', 'since': _since(self.clock()), 'seen': []})}
        state = _decode_cursor(cursor, 'changes')
        try:
            since = parse_time(state['since'])
            seen = set(state['seen'])
            page = _positive(state.get('pg', 1))
            high = parse_time(state['high']) if state.get('high') else None
            high_seen = set(state.get('hseen') or [])
        except (KeyError, TypeError, InvalidResponse):
            raise InvalidRequest('That change position is not valid.') from None
        response = self._send(self._token(), 'GET', '/issues', params={
            'filter': 'all', 'state': 'all', 'sort': 'updated', 'direction': 'desc',
            'since': _since(since), 'per_page': limit, 'page': page})
        items = []
        reached_end = not _next_page(response)
        for result in _list(response.json()):
            resource = _issue_resource(result)
            edited = parse_time(resource['updated_at'])
            if edited < since:
                reached_end = True
                break
            key = resource['ref'].split(':', 2)[2]
            if edited == since and key in seen:
                continue
            if high is None or edited > high:
                high, high_seen = edited, set()
            if edited == high:
                high_seen.add(key)
            created = result.get('created_at')
            change = 'created' if isinstance(created, str) and parse_time(created) >= since else 'updated'
            items.append({'ref': resource['ref'], 'change': change, 'at': resource['updated_at'], 'title': resource['title']})
        if reached_end:
            if high is None or high == since:
                following = {'m': 'changes', 'since': _since(since), 'seen': sorted(seen | high_seen)[:MAX_SEEN]}
            else:
                following = {'m': 'changes', 'since': _since(high), 'seen': sorted(high_seen)[:MAX_SEEN]}
        else:
            following = {'m': 'changes', 'since': state['since'], 'seen': state['seen'], 'pg': page + 1,
                         'high': _since(high) if high is not None else None, 'hseen': sorted(high_seen)[:MAX_SEEN]}
        return {'v': 1, 'items': items, 'cursor': _encode_cursor(following), 'complete': reached_end}
