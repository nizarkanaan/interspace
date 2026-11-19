# Provider registry, sign-in and routing defaults

Owner: 1A; wired by 2A. Status: implemented (Wave 1A), with the Wave 2A additions below. Conventions: [README.md](README.md).

## Registry: `app/backend/runtime/registry.py`

One record per provider replaces the hard-coded `PROVIDERS` tuples:
- `runtime/__init__.py`;
- `tasks.py`;
- the `budget.py` charge tables;
- the `RUNTIMES` object in `app/ui/agent-new.js`.

```python
PROVIDERS = {
  'claude': {
    'name': 'claude', 'title': 'Claude',
    'models': ('claude-sonnet-5-5', 'claude-opus-5-5', 'claude-haiku-5-5'),  # full IDs only, never aliases
    'default_model': 'claude-sonnet-5-5',
    'capabilities': {'write': True, 'web_search': True, 'approvals': True},
    'charge_fields': ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens'),
    'runtime': 'runtime.claude:ClaudeRuntime',     # lazy import 'module:Class'
  },
  'codex': {
    'name': 'codex', 'title': 'Codex',
    'models': (),                                   # empty = free-text model name, checked by MODEL_RE
    'default_model': None,                          # None = the CLI's own default
    'capabilities': {'write': True, 'web_search': True, 'approvals': True},
    'charge_fields': ('input_tokens', 'output_tokens'),
    'runtime': 'runtime.codex:CodexRuntime',
  },
}
DEFAULT_PROVIDER = 'claude'
MODEL_RE = r'[A-Za-z0-9._:-]{1,64}\Z'

def get(name) -> dict          # ValueError('Unknown provider.') otherwise
def names() -> tuple           # registry order
def runtime_class(name)        # imports lazily
def check_model(name, model)   # returns the model, or the default for None; ValueError if invalid
def public() -> list           # JSON-safe list for the UI: name, title, models, default_model, capabilities
```

- `budget.charge(usage, provider)` reads `charge_fields` from the registry. The rule stays the same: every field must be a non-negative int, otherwise the result is `None`. A provider without `charge_fields` cannot be registered.
- The Claude runtime's model checks read the registry. The old `MODELS`/`DEFAULT_MODEL` constants become aliases of the registry values.
- Gemini later adds one record (`'runtime': 'runtime.gemini:GeminiRuntime'`). If its capabilities include `write: False`, it can only get read roles.

## Sign-in

Each runtime class gains two class methods that work without a task:

```python
@classmethod
def auth_status(cls, app) -> dict   # {'provider', 'state': 'signed_in'|'signed_out'|'missing_cli'|'error', 'account': str|None, 'detail': str}
@classmethod
def begin_sign_in(cls, app, on_finish=None) -> dict # {'provider', 'kind': 'device', 'url': str, 'code': str|None, 'detail': str} or {'kind': 'terminal', 'command': str}
@classmethod
def sign_out(cls, app) -> dict      # optional (Wave 2A): the auth_status shape after signing out
```

`on_finish(outcome)` (Wave 2A) is called once, on a background thread, when a device sign-in ends on its own: `'success'`, `'failed'` or `'expired'`. It is not called for a sign-in that a new one replaced, that was signed out or that was cancelled (app shutdown). A `terminal` sign-in never calls it.

- **Codex** signs in to the app-owned `CODEX_HOME` with the CLI's device flow. Exact commands come from spike 0B (`spike-0b.md`).
- **Claude** uses the user's own `claude` sign-in. If it is signed out, `begin_sign_in` returns `{'kind': 'terminal', 'command': 'claude auth login'}`, and the UI shows it as an instruction.
- `account` is a display name or email only. No tokens, credential paths or file contents are ever returned.

Backend methods (Swift allowlist), each answering from a small request pool and never from a run slot:

| Method | Params | Result |
| --- | --- | --- |
| `providers_list` | `{}` | `{'providers': registry.public(), 'status': [auth_status…], 'routing': Routing}` |
| `provider_sign_in` | `{provider}` | `begin_sign_in` result |
| `provider_status` | `{provider}` | `auth_status` result |
| `routing_update` | `{routing}` | the validated `Routing` |
| `provider_sign_out` (Wave 2A) | `{provider}` | the `auth_status` shape after signing out |

**Sign-out (Wave 2A).** `provider_sign_out` calls the runtime class's `sign_out`. Codex signs the app-owned `CODEX_HOME` out (`account/logout`). Claude has no `sign_out`: Interspace never signs the user's own `claude` login out, so the method refuses with a sentence telling the user to run `claude auth logout` in Terminal. The result is also put in `state.provider_status` (below).

**Sign-in completion (Wave 2A).** When a device sign-in ends (`on_finish`), the backend reads the provider's `auth_status` again, stores it in `state['provider_status'][provider]` and publishes `state`. The UI learns the result from the ordinary `{"type": "state"}` message: `state.provider_status` is `{provider: auth_status}` for providers whose sign-in finished, or that were signed out, since the app started. It starts empty at every launch; `providers_list` and `provider_status` remain the way to ask. The UI no longer needs to poll while a device sign-in is open.

**Codex home (Wave 2A).** Every Codex sign-in path uses the app-owned home `<Application Support>/codex-home`, including the legacy `connection` and `sign_in` methods. A pending device sign-in's app-server is stopped when the backend exits.

## Routing defaults

Stored in `state['routing']`:

```json
{"v": 1, "orchestrator": {"provider": "claude", "model": null},
 "roles": {
   "researcher":  {"provider": "codex",  "model": null},
   "implementer": {"provider": "claude", "model": null},
   "reviewer":    {"provider": "codex",  "model": null},
   "tester":      {"provider": "claude", "model": null},
   "writer":      {"provider": "claude", "model": null}}}
```

- `ROLES = ('researcher', 'implementer', 'reviewer', 'tester', 'writer')`. `implementer` and `tester` are **write roles**: they need `capabilities.write`. The rest are read roles.
- `routing.validate(value)` lives in `app/backend/routing.py`. It checks every provider against the registry and every model with `check_model`, and refuses a write role on a provider without write.
- The defaults above apply when `state` has no `routing`. They are a coordinator choice and the user may change them.

## Wave 2A: where the registry is used

- **New tasks.** `agent_create` creates an Orchestrator task (`role: 'orchestrator'`). Without `provider` and `model` it uses `routing.orchestrator`. An explicit `provider` overrides it; with no `model`, that provider runs its own default (the routing model applies only to the routing provider). An explicit `model` overrides the model; blank means the provider's default.
- **Task rows.** `tasks.py` keeps no provider or model list. New rows check the provider with `registry.names()` and the model with `registry.check_model`. A saved row's model only needs the registry's name shape (`MODEL_RE`), so a model a provider stops offering fails that turn rather than hiding the saved task. Rows without `provider` are Codex (`LEGACY_PROVIDER`).
