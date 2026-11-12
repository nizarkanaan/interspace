# Connector API

Status: approved by the user on 2026-11-12, Wave 0A. The 0B fields were reconciled in Wave 2A (2026-11-12); 0C fields await their reconciliation. Conventions and the provisional register are in [README.md](README.md).

One module per app: `app/backend/spaces/notion.py`, `github.py`, `gdrive.py`, `zotero.py`. Each defines a class `Connector`. The same object serves the **Spaces UI** (the user browsing and editing, no model call, no tokens) and **agent tools** (through the runtime's MCP bridge, every call authorized by the scope engine first).

A connector does not know about tasks, scopes, budgets or the UI. It talks to one app for one signed-in account. It never logs or returns credentials.

## Registry: `spaces/__init__.py` (coordinator stub)

```python
"""Spaces hub: one connector module per app, loaded on first use."""
import importlib

APPS = ('notion', 'github', 'gdrive', 'zotero')
TITLES = {'notion': 'Notion', 'github': 'GitHub', 'gdrive': 'Google Drive', 'zotero': 'Zotero'}


def connector(app, http, credentials, journal):
    if app not in APPS:
        raise ValueError('Unknown app.')
    module = importlib.import_module('spaces.' + app)
    return module.Connector(http=http, credentials=credentials, journal=journal)
```

Modules load lazily, so a missing connector fails only for its own app, and Wave 1 never edits this file.

## The `Connector` class

```python
class Connector:
    app = 'notion'                      # one of spaces.APPS
    kinds = ('page', 'database')        # resource kinds this connector returns

    def __init__(self, *, http, credentials, journal, clock=time.time): ...

    # Auth
    def status(self) -> dict: ...                         # AuthStatus
    def begin_sign_in(self, params: dict) -> dict: ...    # SignInStep
    def complete_sign_in(self, params: dict, cancel) -> dict: ...  # AuthStatus; blocks
    def sign_out(self) -> dict: ...                       # AuthStatus

    # Read
    def browse(self, parent=None, cursor=None, limit=50) -> dict: ...    # Page of Resource
    def search(self, query, kinds=None, cursor=None, limit=25) -> dict: ...  # Page of Resource
    def read(self, ref, cursor=None) -> dict: ...         # Content

    # Write
    def actions(self) -> list: ...                         # list of ActionSpec
    def write(self, action, ref, params, idempotency_key) -> dict: ...   # WriteResult

    # Changes
    def changes(self, cursor=None, limit=100) -> dict: ...  # ChangeBatch
```

Rules for every method:
- **Blocking and thread-safe for distinct calls.** The scheduler may call one connector from several task threads. A connector keeps no per-call mutable state on `self` except a lock-protected token refresh.
- **No threads, timers or background polling inside a connector.** The hub decides when to call `changes`.
- **All network goes through `http`.** A connector never imports `urllib`, `http.client` or `socket` directly. This is what makes the fake-HTTP harness complete.
- **Validate everything that comes back.** Remote JSON is untrusted. Map it to the shapes below and raise `InvalidResponse` when it does not fit.
- **No automatic retries.** A connector makes each remote request once. Reads may be retried by the caller; writes never are (see the write journal).
- **Refresh tokens are the one exception:** on a `401` with a stored refresh token, the connector refreshes once, stores the new credentials and repeats that single request once. A second `401` raises `AuthExpired`.

## Auth

### AuthStatus

```json
{"v": 1, "app": "github", "state": "signed_in",
 "account": {"label": "octocat", "id": "583231"},
 "granted": ["repo:read", "issues:write"],
 "detail": "", "checked_at": "2026-11-11T09:30:00.000Z"}
```

- `state`: `signed_out` | `signing_in` | `signed_in` | `expired` | `unavailable`. `unavailable` means the route cannot be reached at all (for Zotero: the desktop app is not running or its local API is off). `detail` then says what to do, in one sentence.
- `account.label` is the name the app shows the user for that account. Never an email address unless that is the only identifier the API returns.
- `granted` lists the connector's own capability names (`<area>:read|write`) actually granted, so the UI and scope editor can grey out what the account cannot do. Its value set per app is `PROVISIONAL(0C-2)`.
- `status()` reads the Keychain and makes at most one cheap remote call (for example GitHub `GET /user`). The result is cached by the hub, not the connector.

### SignInStep

`begin_sign_in` returns one step for the UI to show. Its `kind` is `PROVISIONAL(0C-2)` per app; the four kinds are fixed:

| `kind` | Fields | UI shows | `complete_sign_in` does |
| --- | --- | --- | --- |
| `device_code` | `user_code`, `verification_uri`, `expires_at`, `interval_s` | the code and a button that opens the URI | polls the token endpoint at `interval_s` until success, expiry or `cancel` |
| `browser` | `url`, `expires_at` | "Continue in your browser"; the backend asks Swift to open `url` | waits for the single-use loopback redirect `PROVISIONAL(0C-3)`, exchanges the code with PKCE |
| `token_entry` | `label`, `help_url`, `pattern` | a secure field; the token goes in `params.token` of `complete_sign_in` | validates the token with one remote call, then stores it |
| `local_check` | `detail` | instructions (for example "Enable the local API in Zotero settings") | checks the local endpoint once |

`complete_sign_in` stores credentials only after they are verified, then returns the new `AuthStatus`. It raises `SignInCancelled` when `cancel` is set and `SignInExpired` after `expires_at`. `params` never contains anything except `token` (for `token_entry`) and an optional `write_key` (Zotero web API key for writes, `PROVISIONAL(0C-4)`).

`sign_out` deletes the Keychain item. If the app has a revocation endpoint and the token still works, it calls it once and ignores the outcome. It always returns `signed_out` unless the Keychain delete fails.

Google requires the user's own OAuth client (roadmap decision 2). Its client ID and secret are stored in the Keychain as part of the `gdrive` item; desktop-app client secrets are not confidential, but they still never enter git or state.

### Credentials and the Keychain bridge

A connector receives `credentials`, an object for its own app:

```python
class Credentials:
    def get(self) -> dict or None: ...   # the stored secret dict, or None
    def set(self, secret: dict): ...     # replace atomically
    def delete(self): ...
```

`secret` is a JSON object owned by the connector, for example `{"access_token": "...", "refresh_token": "...", "expires_at": "...", "client_id": "..."}`. Only the connector reads its fields.

The production `Credentials` (in `spaces/base.py`) talks to the Swift shell over the existing pipes. Message names are fixed; transport details are `PROVISIONAL(0C-1)`.

**Backend → Swift** (a line on backend stdout, consumed by Swift and never forwarded to the WebView):

```json
{"type": "keychain", "id": "kc-5b0e…", "op": "read", "account": "github"}
{"type": "keychain", "id": "kc-77a1…", "op": "write", "account": "github", "secret": "{\"access_token\":\"…\"}"}
{"type": "keychain", "id": "kc-9c3d…", "op": "delete", "account": "github"}
{"type": "open_url", "url": "https://github.com/login/device"}
```

**Swift → backend** (a line on backend stdin, alongside UI requests):

```json
{"keychain_reply": "kc-5b0e…", "ok": true, "secret": "{\"access_token\":\"…\"}"}
{"keychain_reply": "kc-5b0e…", "ok": false, "error": "not_found"}
```

- Service name `app.interspace.spaces`, account = app name. One item per app. `PROVISIONAL(0C-1)`.
- `error` is one of `not_found`, `denied` (the user refused a Keychain prompt), `unavailable`.
- `secret` is a JSON string, so Swift never parses it.
- **Handshake.** When Swift starts the backend it writes `{"bridge_hello": {"keychain": 1, "open_url": 1}}` as the first stdin line. The backend sends `keychain` and `open_url` messages only after receiving it; without it, every `Credentials` call raises `CredentialStoreUnavailable` at once. A shell that predates the bridge therefore never receives a secret it would forward to the WebView.
- **Routing (1F, `service.main`).** Today one thread reads stdin and runs `app.handle` synchronously, so a `Credentials` call inside a request could never read its own reply. The loop changes to: a dedicated **reader thread** reads every stdin line; `keychain_reply` and `bridge_hello` lines are delivered to the waiting `Credentials` call (or handshake flag) on that thread; every other line goes to a request queue. Legacy methods are handled from that queue by one dispatcher thread, exactly in today's order. `spaces_*` methods, scope methods and `agent_*` methods are handed to their pools (scheduler.md) and reply when done. A reply with an unknown `id` is dropped. A `Credentials` call waits at most 10 s, then raises `CredentialStoreUnavailable`.
- Swift opens `open_url` only for `https:` URLs, in the default browser, and shows nothing else. Its `receive` method must consume `keychain` and `open_url` lines **before** `deliver`; it never forwards them to the WebView, and the WebView can never send `keychain_reply` (the UI allowlist in `main.swift` is method-based and `keychain_reply` lines have no `method`).
- Credentials are never written to `state.json`, events, the audit log or error messages.

## Resources and reads

### Resource reference

`ref` is `<app>:<kind>:<id>`. `<kind>` is `[a-z_]{1,32}`. `<id>` is the app's own stable ID, any printable characters except control characters, at most 512 characters. Helpers in `spaces/base.py`: `make_ref(app, kind, id)` and `parse_ref(ref) -> (app, kind, id)`; `parse_ref` raises `InvalidRequest` for anything malformed or for an app other than the connector's own.

Kinds (fixed for v1; adding a kind needs the coordinator):

| App | Kinds | Example ID |
| --- | --- | --- |
| notion | `page`, `database`, `block` | Notion UUID |
| github | `repo`, `issue`, `pull`, `file`, `branch` | `owner/name`, `owner/name#12`, `owner/name@ref:path`, `owner/name@branch` |
| gdrive | `folder`, `file`, `doc` | Drive file ID |
| zotero | `library`, `collection`, `item`, `attachment` | `users/123/items/ABCD1234` |

### Resource (one listing row)

```json
{"ref": "notion:page:1f2e…", "kind": "page", "title": "Reading notes",
 "parent": "notion:database:9a8b…", "url": "https://www.notion.so/…",
 "updated_at": "2026-11-10T18:02:11.000Z", "has_children": true,
 "meta": {"status": "Draft"}}
```

`title` is at most 300 characters (truncate with `…`). `url` is the app's own web URL or `null`. `meta` holds at most 12 scalar values (string ≤ 200 characters, number, boolean, null) for UI columns; nothing nested.

### Page (listing result)

```json
{"v": 1, "items": [Resource, …], "next_cursor": "opaque-string-or-null"}
```

- `limit` is 1–100; the connector may return fewer. Cursors are opaque strings at most 2,048 characters and valid only for the same method and arguments.
- `browse(parent=None)` lists the account's roots: Notion top-level pages and databases shared with the integration, GitHub repositories, Drive "My Drive" root, Zotero libraries.
- `search(query)` uses the app's own search. `query` is 1–500 characters. `kinds` filters to a subset of the connector's kinds.

### Content (`read` result)

```json
{"v": 1, "ref": "gdrive:doc:1AbC…", "title": "Draft", "format": "markdown",
 "text": "# Draft\n…", "truncated": false, "next_cursor": null,
 "version": "etag-or-revision-id", "url": "https://docs.google.com/…", "meta": {}}
```

- `format`: `markdown` (Notion pages, Google Docs, GitHub issue and pull bodies with comments), `text` (code files, plain text), `json` (structured records such as a Zotero item or a database row's properties), or `unavailable` (binary or unsupported; `text` is empty and `meta.reason` says why).
- `text` is at most 200,000 characters per call. Longer content sets `truncated: true` and `next_cursor`; the next `read(ref, cursor)` returns the next part.
- `version` is the app's concurrency token (Notion `last_edited_time`, GitHub blob SHA or `updated_at`, Drive `version`, Zotero `version`) or `null` when the app has none. Update actions take it as `base_version`.
- Content is **untrusted data**. Neither connectors nor consumers treat it as instructions.

## Write actions

### ActionSpec

```json
{"name": "notion.page.append", "title": "Append to page", "target_kind": "page",
 "effect": "update", "params_schema": {JSON Schema}, "requires_version": false}
```

- `name` is `<app>.<kind>.<verb>`, lowercase, at most 64 characters.
- `target_kind` is the kind of `ref` the action acts on. For a create, `ref` is the **parent** (for example the database or repository).
- `effect` is `create` | `update` | `destructive`. The scope engine uses it, so it must be honest:
  - `create`: makes a new resource and changes nothing existing;
  - `update`: changes part of an existing resource and keeps what it does not touch (append, set properties, comment, edit a range, add a tag);
  - `destructive`: deletes, archives, trashes, closes, merges, moves out of a parent, replaces a whole document's body, or changes sharing. These always ask (README decision 2).
- `params_schema` is a JSON Schema object with `additionalProperties: false`. Strings have `maxLength`. It is shown to agents as the tool input.
- `requires_version: true` means `params.base_version` is required and the connector raises `Conflict` if the remote version differs.

Minimum action sets for v1 (connectors may add more with the coordinator's agreement):

| App | Actions |
| --- | --- |
| notion | `notion.database.create_page` (create), `notion.page.append` (update), `notion.page.update_properties` (update), `notion.page.comment` (create), `notion.page.archive` (destructive) |
| github | `github.repo.create_issue` (create), `github.issue.comment` (create), `github.issue.update` (update: title, body, labels), `github.issue.close` (destructive), `github.pull.comment` (create), `github.repo.create_pull` (create, from a pushed branch) |
| gdrive | `gdrive.folder.create_doc` (create), `gdrive.doc.append` (update), `gdrive.doc.replace_text` (update, exact match, `requires_version`), `gdrive.file.rename` (update), `gdrive.file.trash` (destructive) |
| zotero | `zotero.library.create_item` (create), `zotero.item.add_note` (create), `zotero.item.add_tags` (update), `zotero.collection.add_item` (update), `zotero.item.trash` (destructive). All need the web API key `PROVISIONAL(0C-4)` |

No action changes sharing, permissions, membership or another person's account. Those are not offered at all (scope.md always-deny).

### `write(action, ref, params, idempotency_key)`

`idempotency_key` is required, 1–128 characters of `[A-Za-z0-9:_-]`. Agents' writes use `<task_id>:` + the first 32 hex characters of `sha256((turn_id + ':' + call_id).encode('utf-8'))`, at most 65 characters for 32-character task IDs (`agent_key(task_id, turn_id, call_id)` in `spaces/base.py`). UI writes use a fresh `uuid4().hex` per user click.

Every write follows the same journal sequence, implemented once in `spaces/base.py` as `journaled_write` and used by every connector:

1. `journal.begin(key, app, action, ref, params_digest)` where `params_digest` is `sha256:` + hex of canonical JSON (sorted keys, `(',', ':')` separators, UTF-8).
   - New key: records `started` durably and continues.
   - Same key, same digest, `succeeded`: returns the stored `WriteResult` with `replayed: true` and makes no remote call.
   - Same key, same digest, `started` or `outcome_unknown`: raises `OutcomeUnknown`. Never re-sends.
   - Same key, same digest, `failed`: raises the stored error class again (by `code`) without a remote call. Trying again needs a new key, which only a new user click or a new agent call produces.
   - Same key, different digest: raises `InvalidRequest`.
2. The connector performs **one** remote request (or one fixed sequence that is safe to stop between steps, stated in the action's docstring). Where the app supports a native idempotency header, pass the key (Zotero `Zotero-Write-Token`).
3. `journal.finish(key, result)` on success; `journal.fail(key, error_code)` on a definite failure (the app answered with an error status); `journal.unknown(key)` when the request may have reached the app but no answer arrived (timeout, connection reset after sending).

### WriteResult

```json
{"v": 1, "ok": true, "action": "github.repo.create_issue", "ref": "github:repo:octo/notes",
 "result_ref": "github:issue:octo/notes#41", "url": "https://github.com/octo/notes/issues/41",
 "version": "2026-11-11T09:31:02Z", "replayed": false, "summary": "Created issue #41 \"Track reading list\""}
```

`summary` is one sentence for the UI and the agent, at most 300 characters.

### Journal interface

```python
class Journal:
    def begin(self, key, app, action, ref, params_digest) -> dict or None: ...  # stored record or None
    def finish(self, key, result: dict): ...
    def fail(self, key, error_code: str): ...
    def unknown(self, key): ...
```

`spaces/base.py` provides `MemoryJournal` for tests. 1E provides the durable `FileJournal` in `audit.py` (append-only JSON lines under Application Support `spaces/writes.jsonl`, fsync per record). On startup, every `started` record becomes `outcome_unknown`; the UI shows it, and nothing re-sends it.

## Changes

`changes(cursor=None, limit=100)` returns what changed since `cursor`:

```json
{"v": 1, "items": [{"ref": "github:issue:octo/notes#41", "change": "updated",
  "at": "2026-11-11T09:40:00.000Z", "title": "Track reading list"}],
 "cursor": "opaque", "complete": true}
```

- `change`: `created` | `updated` | `deleted`.
- `cursor=None` returns no items and a baseline cursor for "now". The hub stores cursors per app in `state.json` under `spaces.cursors`.
- `complete: false` means more items are waiting; call again with the returned cursor.
- If the app cannot list changes since a point, the connector compares `updated_at` of the roots and their direct children and says so in its docstring. It never downloads whole libraries to diff.
- Polling (hub, not connector): every 120 s while the app window is open and the app is `signed_in`; never during sign-in; backs off to 15 minutes after `RateLimited`. Change polling costs no tokens.

## Errors (`spaces/base.py`)

```python
class SpaceError(ValueError):
    code = 'space_error'
    def __init__(self, message, *, retry_after_s=None):
        super().__init__(message)
        self.retry_after_s = retry_after_s

class NotSignedIn(SpaceError):          code = 'not_signed_in'
class AuthExpired(SpaceError):          code = 'auth_expired'
class SignInCancelled(SpaceError):      code = 'sign_in_cancelled'
class SignInExpired(SpaceError):        code = 'sign_in_expired'
class CredentialStoreUnavailable(SpaceError): code = 'credential_store_unavailable'
class Forbidden(SpaceError):            code = 'forbidden'        # the app refused this account
class NotFound(SpaceError):             code = 'not_found'
class Conflict(SpaceError):             code = 'conflict'         # base_version mismatch
class RateLimited(SpaceError):          code = 'rate_limited'     # retry_after_s set when known
class InvalidRequest(SpaceError):       code = 'invalid_request'  # bad ref, params or cursor
class InvalidResponse(SpaceError):      code = 'invalid_response' # remote JSON did not fit
class Unavailable(SpaceError):          code = 'unavailable'      # network, 5xx, local app closed
class OutcomeUnknown(SpaceError):       code = 'outcome_unknown'  # a write may or may not have happened
class Unsupported(SpaceError):          code = 'unsupported'      # not possible on this route
```

Messages are one actionable sentence and never include response bodies, tokens or resource content. Status mapping: `401` → `AuthExpired` (after the one refresh), `403` → `Forbidden` (GitHub `403` with rate-limit headers → `RateLimited`), `404` → `NotFound`, `409`/`412` → `Conflict`, `429` → `RateLimited`, `400`/`422` → `InvalidRequest`, `5xx` and connection errors → `Unavailable`, except after a write's request was sent → `OutcomeUnknown`.

## Tool descriptors for agents

`spaces/base.py` generates the tools from the connector, so all four apps look the same to an agent:

```python
def tools(connector) -> list: ...   # list of ToolDescriptor
```

```json
{"v": 1, "name": "notion_page_append", "app": "notion", "title": "Append to page",
 "description": "Append Markdown blocks to the end of a Notion page.",
 "input_schema": {"type": "object", "additionalProperties": false,
   "properties": {"ref": {"type": "string", "maxLength": 600}, "markdown": {"type": "string", "maxLength": 100000}},
   "required": ["ref", "markdown"]},
 "effect": "update", "action": "notion.page.append", "ref_param": "ref"}
```

- Standard tools for every app: `<app>_search` (effect `read`), `<app>_browse` (`read`), `<app>_read` (`read`). One tool per `ActionSpec`, named by replacing `.` with `_`. Names match `^[a-z][a-z0-9_]{0,63}$`.
- `effect` is `read` | `create` | `update` | `destructive`. `ref_param` names the input holding the target `ref` (the parent for creates), or `null` for search.
- The agent never supplies an idempotency key. `RunContext.app_tool` sets `agent_key(task_id, turn_id, call_id)`.
- The runtime adapter configures the Interspace MCP server under the fixed server name `interspace` and routes its tool calls to `RunContext.app_tool`, never to `authorize` as `category: mcp`. Provider configuration is passed explicitly, so no other server can use that name.
- Tool results are JSON: `{"ok": true, "result": …}` or `{"ok": false, "error": {"code": "…", "message": "…"}}`. Read results are wrapped by the bridge (2A) as untrusted external content.
- How these reach the provider (0B-4, decided): through the Interspace MCP bridge, server `interspace` (scheduler.md, "MCP bridge API"). The provider starts a stdio relay that reaches the backend over a private Unix socket; every call runs through `RunContext.app_tool`. The tools listed are those of the apps in the task's scope. The descriptor shape does not change.

## Backend protocol for the Spaces UI

New request methods on the existing JSON-lines bridge. 1F adds them to `service.py`; the `main.swift` owner adds them to the method allowlist. UI writes are the user's own actions: no scope applies, but each is audited with `actor: "user"`, and the UI confirms `destructive` actions in a dialog first.

| Method | Params | Result |
| --- | --- | --- |
| `spaces_status` | `{}` | `{"apps": [AuthStatus, …]}` for all four apps |
| `spaces_sign_in` | `{app}` | `SignInStep`; completion arrives as a `spaces_auth` message and a `state` update |
| `spaces_complete_sign_in` | `{app, token?, write_key?}` | `AuthStatus` (for `token_entry` and `local_check`) |
| `spaces_cancel_sign_in` | `{app}` | `{"cancelled": true}` |
| `spaces_sign_out` | `{app}` | `AuthStatus` |
| `spaces_browse` | `{app, parent?, cursor?, limit?}` | `Page` |
| `spaces_search` | `{app, query, kinds?, cursor?, limit?}` | `Page` |
| `spaces_read` | `{app, ref, cursor?}` | `Content` |
| `spaces_actions` | `{app}` | `{"actions": [ActionSpec, …]}` |
| `spaces_write` | `{app, action, ref, params, idempotency_key}` | `WriteResult` |
| `spaces_changes` | `{}` | `{"apps": {app: [change item, …]}}`: changes since the UI last asked |

Spaces requests do not wait for the legacy `active` slot and run on a small worker pool (see scheduler.md), so browsing never blocks behind a running task.

Unsolicited messages:

```json
{"type": "spaces_auth", "app": "github", "status": AuthStatus}
{"type": "spaces_changed", "app": "github", "items": [change item, …]}
```

The `state` projection gains `"spaces": {"apps": {app: AuthStatus}}`. It never contains credentials.

## Fake-HTTP test harness

### `Http` (production, `spaces/base.py`)

```python
class Response:
    status: int; headers: dict  # lower-case keys
    body: bytes
    def json(self): ...   # raises InvalidResponse on bad JSON
    def text(self): ...

class Http:
    def request(self, method, url, *, headers=None, params=None, json=None, data=None, timeout_s=30) -> Response: ...
```

Built on `urllib.request`, HTTPS only (except `http://127.0.0.1:23119` for Zotero's local API and the loopback redirect), a fixed `User-Agent: Interspace`, no proxies from the environment, a 10 MB response cap, and no redirects to another host. It raises `Unavailable` for connection errors and returns every HTTP status as a `Response`.

### `FakeHttp` (`tests/spaces/fakehttp.py`)

```python
class FakeHttp:
    def __init__(self): ...
    def expect(self, method, url, *, status=200, json=None, body=b'', headers=None,
               match_params=None, match_json=None, match_headers=None, raises=None): ...
    def request(self, method, url, **kwargs) -> Response: ...  # same signature as Http.request
    def assert_done(self): ...
    calls: list  # every request made, for assertions
```

- Expectations are matched **in order**. A request that does not match the next expectation fails the test immediately with a diff of expected and actual method, URL and matched fields.
- `url` is matched without its query string; `match_params`, `match_json` and `match_headers` are subset matches.
- `raises` simulates transport failures: `'connection'` (before sending → `Unavailable`) and `'timeout_after_send'` (→ `OutcomeUnknown` for writes).
- `assert_done()` fails if expectations remain. Every connector test calls it.

Also in `tests/spaces/fakehttp.py`: `MemoryCredentials(secret=None)` and a re-export of `MemoryJournal`.

### Fixtures and test rules

- Response bodies live in `tests/spaces/fixtures/<app>/<name>.json`. They follow the shapes in each app's public API documentation and contain invented IDs, names and text. Never real account data, tokens or personal content.
- Each connector's tests cover at least: status signed in / signed out / expired; one full sign-in path per step kind it uses (with a fake clock and a cancelled variant); browse with two pages; search; read with truncation; each action's success; `Conflict` for version-checked actions; journal replay and `OutcomeUnknown` (`timeout_after_send`); every status mapping in the error table that applies; `changes` baseline and a non-empty batch.
- Test files: `tests/spaces/test_<app>.py`, runnable with `python3 -m unittest tests.spaces.test_<app>`, on Python 3.9 and 3.14.
- No test touches the network, the Keychain or the user's real apps. A live check against the user's own account is a separate, explicitly approved step, never part of the suite.

## UI panels

Each connector stream also owns `app/ui/spaces/<app>.js`. A panel registers itself with the Spaces sidebar frame (owned by 1G):

```js
window.interspaceSpaces.register({
  app: 'notion', title: 'Notion',
  render(container, api) {},   // draw the panel into container
  dispose() {}                 // remove listeners
});
```

`api` provides `request(method, params)` (the existing bridge, limited to `spaces_*` methods for this app), `openRef(ref)` (select a resource in the panel), `mention(ref, title)` (insert an `@mention` into the composer) and `confirm(text)` (the shared destructive-action dialog). Panels insert remote text with `textContent`, never as markup. Panels never call another app's methods.

1G adds `<script src="spaces/<app>.js">` tags for all four apps to `index.html` in Wave 1 and defines `window.interspaceSpaces` before them, so connector streams never edit `index.html`. A missing panel file leaves its sidebar entry showing "Not available yet".
