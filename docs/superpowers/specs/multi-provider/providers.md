# Provider registry, sign-in and routing defaults

Owner: 1A. Conventions: [README.md](README.md).

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
def begin_sign_in(cls, app) -> dict # {'provider', 'kind': 'device', 'url': str, 'code': str|None, 'detail': str} or {'kind': 'terminal', 'command': str}
```

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
