# Keychain bridge and Research sources settings

Owner: 1A (`app/macos/main.swift`, `app/backend/research/credentials.py`, `app/backend/research_api.py`, and the stdin bridge-line handling in `service.py`). Conventions: [README.md](README.md).

This restores the bridge deleted in `fe65e32` (see `git show fe65e32^:app/backend/spaces/base.py` and `git show fe65e32 -- app/macos/main.swift`) under a new service name.

## Swift side (`ResearchKeychain`)

- **Item settings:** generic password items with service `app.interspace.research` and label `Interspace: <title>`.
  - `kSecAttrAccessibleWhenUnlockedThisDeviceOnly`, not synchronizable.
  - Secret at most 64 KiB, UTF-8.
- **Account allowlist:** `semantic_scholar`, `openalex`, `crossref_email`, `unpaywall_email`. Any other account is refused.
- **Pipe messages.** These are backend-only and never reach or come from the WebView.
  - The backend writes `{"type": "keychain", "id": "kc-<hex>", "op": "read"|"write"|"delete", "account": "<account>", "secret"?: "<text>"}`. The `id` starts with `kc-`, is at most 64 characters, and `secret` is present only on `write`.
  - Swift answers on the backend's stdin with `{"type": "keychain_reply", "id": "kc-…", "ok": true, "secret"?: "…"}` or `{"type": "keychain_reply", "id": "kc-…", "ok": false, "error": "not_found"|"denied"|"unavailable"}`.
- **Handling.** Keychain work runs on a serial `keychainQueue`. A write tries an update first and adds the item if it is missing.
- **Handshake.** At backend start Swift sends `{"type": "bridge_hello", "keychain": 1, "save_panel": 1}`. Without it, the backend reports every source as `credential_store_unavailable`.
- **The WebView** can never send `keychain`, `keychain_reply` or `bridge_hello`. Swift drops those types if the UI sends them, and never forwards them to the UI.

**Save panel**, for task outputs (tasks.md):
- The backend writes `{"type": "save_panel", "id": "sp-<hex>", "suggested_name": "related-work.bib", "path": "<absolute path inside app data>"}`.
- Swift shows an `NSSavePanel`, copies that file to the place the user picks, and answers `{"type": "save_panel_reply", "id": "sp-…", "ok": true|false, "error"?: "cancelled"|"failed"}`.
- Swift refuses a `path` outside the app data folder.

## Backend side (`research/credentials.py`)

```python
class Credentials:
    def __init__(self, channel, timeout_s=10): ...
    def get(self, account) -> str | None        # None when not set
    def set(self, account, secret): ...         # validates: api keys 8–256 printable chars; emails RFC-ish, ≤254
    def delete(self, account): ...
    def configured(self, account) -> bool       # cached answer, never the secret
```

- Errors: `CredentialStoreUnavailable(ValueError)` when there is no handshake, the reply times out or access is denied.
- **Read cache:** each secret is held in memory for at most 10 minutes, then read again. It is dropped on `set`/`delete` and at shutdown.
- **Never** log, audit, persist, include in errors or return a secret, except to the source client that needs it.

## Settings methods (`research_api.py`, through `METHODS` and the `service.extension_methods` hook; each also goes in the Swift allowlist)

| Method | Params | Result |
| --- | --- | --- |
| `research_sources` | `{}` | `{sources: [{source, title, credential_kind, required, configured, state, detail, help_url, capabilities}]}` |
| `research_credential_set` | `{source, value}` | the source's status row (the value is never echoed back) |
| `research_credential_delete` | `{source}` | the source's status row |
| `research_test` | `{source}` | `status(test=True)` |
| `research_usage` | `{task_id?}` | `{calls: {source: n}, cached: {source: n}}`: call counts, never money |

`value` for an email-kind source is the user's own email. The UI says, in plain language, that the email goes to that service as its polite-pool contact.
