# Model and Effort Pickers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the typed model box with Model and Effort dropdowns per role (Settings → Providers), a Model and Effort dropdown in New task, and a Model dropdown on the team-approval card. The chosen effort reaches the Claude and Codex runtimes.

**Architecture:** Routing entries and task records gain an optional `effort` (`null` = provider default), travelling the same path `model` takes today: routing → task → `RunContext` → runtime. Claude's model and effort lists are fixed in the registry. Codex's come live from `codex app-server` `model/list` through a new `provider_models` backend method, cached per app session.

**Tech Stack:** Python 3 stdlib backend (`unittest`), vanilla JS UI tested with `node tests/run-ui.cjs <name>`, Swift shell built by `scripts/build-macos-app.py`.

**Spec:** `docs/superpowers/specs/2026-11-26-model-effort-picker-design.md`

## Global Constraints

- Claude models: `claude-sonnet-5-5` (default), `claude-opus-5-5`, `claude-haiku-5-5`. Full IDs only, never aliases.
- Claude efforts: `low`, `medium`, `high`, `xhigh`, `max`. When effort is `null`, Claude runs `--effort low` (`DEFAULT_EFFORT`), unchanged.
- Codex effort: any `[a-z]{1,16}` token or `null`. When `null`, send no effort, so the CLI default applies.
- Routing document stays `v: 1`. Old routing without `effort` loads with `effort: null`. Saved tasks without `effort` run as before.
- Codex models come only from the **signed-in** `model/list`. A signed-out account or a failed call gives an empty list, a one-sentence `error` and the typed box.
- `model/list` deadline: 10 s. The cache lasts until the app quits or the user signs in or out of Codex.
- A team member keeps its role's effort only on the role's provider **and** the role's model; otherwise its effort is `null`. `propose_team` has no `effort` field.
- An effort Codex refuses fails the turn with a clear mapped error, never retried and never silently dropped.
- Never send tokens, account IDs or credential paths to the UI.
- UI copy: plain sentences, the house style of `app/ui/providers.js`.
- Commit messages: plain sentence style as in `git log`, no attribution trailers.

## Review Focus

1. **Stored Codex model no longer in the live list** (account changed plan): Settings shows it selected as "… (not available)", Save warns instead of silently dropping it. Test in Task 5.
2. **Saved routing from before this change** with a Codex model typed by hand: it loads, and the dropdown shows that model. Test in Task 1 (backend) and Task 5 (UI).
3. **Codex signed out when Settings opens, then the user signs in**: the cached failure must not stick. Signing in clears the cache and the list refills. Test in Task 4.
4. **Changing provider from Codex to Claude with effort `xhigh` set**: effort resets to Default, never sends a Codex-only value to Claude. Test in Task 6.
5. **`model/list` hangs** (first-call stall seen in the spike): the request returns the error within the 10 s deadline and the app-server process is closed. Test in Task 4.

---

### Task 1: Effort in the registry and routing

**Files:**
- Modify: `app/backend/runtime/registry.py` (PROVIDERS, new `check_effort`)
- Modify: `app/backend/routing.py` (`DEFAULT_ROUTING`, `_choice`)
- Modify: `app/backend/orchestrator.py:36-43, 75-115` (fallback `DEFAULT_ROUTING`, `registry()`, `routing_defaults`)
- Test: `tests/test_routing.py`, `tests/test_registry.py`

**Interfaces:**
- Produces: `registry.PROVIDERS[name]['efforts']`, a tuple: Claude `('low','medium','high','xhigh','max')`, Codex `()` (empty = checked by shape).
- Produces: `registry.check_effort(name: str, effort: str | None) -> str | None`. `None` passes through. Claude: must be in `efforts`, else `ValueError('Choose one of the Claude effort levels.')`. Codex: must match `[a-z]{1,16}`, else `ValueError('The effort must be a short lowercase word.')`.
- Produces: every routing entry is `{'provider', 'model', 'effort'}`; `routing.validate` always returns `effort`.
- Produces: `orchestrator.registry()` dict gains `'check_effort'`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_routing.py`: update `test_defaults_match_the_contract` so every entry has `'effort': None`. Add:
```python
def test_routing_without_effort_loads_with_none(self):
    old = {'v': 1, 'orchestrator': {'provider': 'claude', 'model': 'claude-opus-5-5'},
           'roles': {r: {'provider': 'codex', 'model': 'gpt-6-sol'} for r in routing.ROLES if r not in routing.WRITE_ROLES}
                    | {r: {'provider': 'claude', 'model': None} for r in routing.WRITE_ROLES}}
    clean = routing.validate(old)
    self.assertIsNone(clean['orchestrator']['effort'])
    self.assertEqual(clean['roles']['researcher'], {'provider': 'codex', 'model': 'gpt-6-sol', 'effort': None})

def test_effort_is_kept_and_checked(self):
    value = routing.default(); value['orchestrator']['effort'] = 'high'; value['roles']['researcher']['effort'] = 'xhigh'
    self.assertEqual(routing.validate(value)['orchestrator']['effort'], 'high')
    value['orchestrator']['effort'] = 'turbo'
    with self.assertRaisesRegex(ValueError, 'Claude effort'):
        routing.validate(value)

def test_unknown_entry_keys_are_refused(self):
    value = routing.default(); value['orchestrator']['temperature'] = 1
    with self.assertRaises(ValueError):
        routing.validate(value)
```
In `tests/test_registry.py`: `check_effort('claude', 'max') == 'max'`, `check_effort('claude', None) is None`, `check_effort('codex', 'minimal') == 'minimal'`, `check_effort('codex', 'High!')` raises, `check_effort('claude', 'minimal')` raises.

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m unittest tests.test_routing tests.test_registry -v`
Expected: FAIL (no `effort` key, no `check_effort`).

- [ ] **Step 3: Implement**

Add `efforts` to both PROVIDERS records and to the record check in `registry.py` (an `efforts` tuple of distinct `[a-z]{1,16}` names, default `()` for records registered without it). Add `check_effort`. In `routing._choice`, accept keys `{'provider','model'}` or `{'provider','model','effort'}` and return all three, checking effort with `registry.check_effort`. Add `'effort': None` to every `DEFAULT_ROUTING` entry in `routing.py` and the fallback copy in `orchestrator.py`. In `orchestrator.registry()`, return `check_effort` (fallback: Claude list above, Codex by shape). In `routing_defaults`' fallback path, also run `check_effort`.

- [ ] **Step 4: Run them and see them pass**

Run: `python3 -m unittest tests.test_routing tests.test_registry tests.test_orchestrator tests.test_providers_api -v`
Expected: PASS. Fix any existing assertion that compares routing entries without `effort`.

- [ ] **Step 5: Commit**

`git commit -m "Add an optional effort to each routing entry"`

---

### Task 2: Effort on task records, the Orchestrator choice and team members

**Files:**
- Modify: `app/backend/tasks.py:76-82, 100-115, 133-143, 165-175`
- Modify: `app/backend/service.py:650-660, 685-696` and the task rows at `:405, :467`
- Modify: `app/backend/orchestrator.py:159-190` (`_resolve`), `:134` (system prompt line), `:527` (`tasks.child` call)
- Modify: `app/backend/scheduler.py:519` (`RunContext`)
- Test: `tests/test_tasks.py`, `tests/test_orchestrator.py`, `tests/test_agent_service.py`

**Interfaces:**
- Consumes: `registry.check_effort` (Task 1).
- Produces: `tasks.validate_effort(provider_name: str, value: str | None) -> str | None` (blank → `None`).
- Produces: `tasks.create(..., effort=None)` and `tasks.child(..., effort=None)` store `task['effort']`.
- Produces: `Service.orchestrator_choice(params) -> (provider, model, effort)`. With no `effort` in params, effort is the routing Orchestrator effort when the provider **and** the model equal the routing's, else `None`.
- Produces: resolved team members carry `'effort'`; `RunContext.effort: str | None`.

- [ ] **Step 1: Write the failing tests**

- `tests/test_tasks.py`: `create('t', project_id='p', provider='claude', model=None, effort='high')['effort'] == 'high'`; a saved task without `effort` validates; a saved task with `effort: 'Bad Value'` is refused by the saved-task check.
- `tests/test_orchestrator.py`, with routing researcher `{'provider':'codex','model':'gpt-6-sol','effort':'xhigh'}`:
  - `test_member_on_role_model_keeps_role_effort`: member `{'role':'researcher','brief':'b'}` resolves with `effort == 'xhigh'`.
  - `test_member_on_other_model_gets_default_effort`: member with `'model':'gpt-6-luna'` resolves with `effort is None`.
  - `test_member_on_other_provider_gets_default_effort`: member with `'provider':'claude'` resolves with `effort is None`.
  - The approved team creates child tasks whose `effort` matches the member.
- `tests/test_agent_service.py`, routing Orchestrator `{'provider':'claude','model':'claude-opus-5-5','effort':'high'}`:
  - no provider/model/effort in params → `('claude','claude-opus-5-5','high')`;
  - `{'model':'claude-haiku-5-5'}` → effort `None`;
  - `{'effort':'max'}` → `('claude','claude-opus-5-5','max')`;
  - `{'effort':'turbo'}` → `ValueError`.

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m unittest tests.test_tasks tests.test_orchestrator tests.test_agent_service -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add `validate_effort` beside `validate_model`; add `effort` to `create` and `child`; in the saved-task check, accept `effort` of `None` or a `[a-z]{1,16}` string (shape only, like `SAVED_MODEL`). Change `orchestrator_choice` to return three values and update its caller at `service.py:656` to pass `effort=`. Include `effort` in the two task-row dicts so the UI can show it. In `_resolve`: `effort = default.get('effort') if provider == default['provider'] and model == default_model else None`; add it to the result. Do not add `effort` to the `default` flag rule. Pass `effort=member['effort']` at `orchestrator.py:527`. The system prompt line becomes `'- %s: %s, model %s, effort %s'` with `'default'` for `None`. Set `self.effort` in `RunContext` the way `self.model` is set.

- [ ] **Step 4: Run them and see them pass**

Run: `python3 -m unittest tests.test_tasks tests.test_orchestrator tests.test_agent_service tests.test_scheduler -v`
Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "Carry the chosen effort from routing to tasks and team members"`

---

### Task 3: Runtimes use the effort

**Files:**
- Modify: `app/backend/runtime/claude.py:67, 541`
- Modify: `app/backend/runtime/codex.py:55-65` (error map), `:512` (`turn/start`)
- Modify: `tests/runtime/fixtures/codex/fake_app_server.py` (record `turn/start` params; scenario `effort_refused`)
- Test: `tests/runtime/test_claude.py`, `tests/runtime/test_codex.py`

**Interfaces:**
- Consumes: `ctx.effort` (Task 2).

- [ ] **Step 1: Write the failing tests**

- `test_claude.py`: argv contains `['--effort', 'high']` when `ctx.effort == 'high'`, and `['--effort', 'low']` when `ctx.effort is None`.
- `test_codex.py`:
  - recorded `turn/start` params include `'effort': 'xhigh'` when `ctx.effort == 'xhigh'`;
  - no `effort` key when `None`;
  - with the fake server's `effort_refused` scenario (it answers `turn/start` with a JSON-RPC error whose message names the reasoning effort), the turn ends with error code `runtime_unavailable` and the message `This Codex model does not support the chosen effort. Choose another in Settings → Providers.`;
  - the fake server saw exactly one `turn/start`.

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m unittest tests.runtime.test_claude tests.runtime.test_codex -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Claude: `'--effort', ctx.effort or DEFAULT_EFFORT`. Codex: add `effort` to the `turn/start` params only when `ctx.effort` is a non-empty string. A `turn/start` error, or a turn error with `codexErrorInfo`, whose text mentions `effort` maps to the message above (`runtime_unavailable`), with no retry. Before writing the mapping, check the real CLI once if it is installed: send `turn/start` with an effort that `model/list` does not list for that model. Then match the fake server's error to what the real one sends, and note the observed shape in a comment.

- [ ] **Step 4: Run them and see them pass**

Run: `python3 -m unittest tests.runtime.test_claude tests.runtime.test_codex -v`
Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "Pass the chosen effort to Claude Code and Codex"`

---

### Task 4: `provider_models` backend method

**Files:**
- Modify: `app/backend/codex_auth.py` (new `CodexAuth.list_models`)
- Modify: `app/backend/runtime/codex.py:215-240` (classmethod `models(app)`)
- Modify: `app/backend/providers_api.py` (handler, cache, `METHODS`, cache clear in sign-in/sign-out)
- Modify: `tests/runtime/fixtures/codex/fake_app_server.py` (`model/list`, scenarios `models`, `models_hang`)
- Test: `tests/test_providers_api.py`, `tests/runtime/test_codex_auth.py`

**Interfaces:**
- Produces: `CodexAuth.list_models() -> list[dict]`, raising `AuthError` with a safe sentence. It reads `account/read` first; no account → `AuthError('Sign in to Codex to see its models.')`. Then it pages `model/list` (follow `nextCursor` until absent, at most 10 pages) inside a 10 s total deadline, and always closes the server.
- Produces: backend method `provider_models` with params `{provider}`. It returns `{'provider', 'models': [{'id', 'is_default', 'default_effort', 'efforts'}], 'error': ''}`. For Claude it answers from the registry: `is_default` for `claude-sonnet-5-5`, `default_effort: 'low'`, `efforts` = registry list. For Codex it calls `list_models`. On failure: `models: []`, `error` = the sentence.
- Produces: `providers_api.clear_models_cache(name: str | None = None)`, called by `provider_sign_in` completion and `provider_sign_out`.

- [ ] **Step 1: Write the failing tests**

- `test_codex_auth.py`, against the fake server:
  - signed in with scenario `models` (two models, one `isDefault`, `supportedReasoningEfforts` given as objects `{'reasoningEffort': 'low', 'description': '…'}`) → a list of `{'id','is_default','default_effort','efforts'}` with `efforts` as plain strings;
  - signed out → `AuthError` 'Sign in to Codex to see its models.';
  - scenario `models_hang` → `AuthError` in under 11 s, and the process is gone.
- `test_providers_api.py`:
  - Claude answer as above;
  - a Codex answer is cached: a second call starts no process;
  - `provider_sign_out` and a finished sign-in each clear the cache, so a cached signed-out failure does not stick;
  - the answer has no keys other than the contract keys.

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m unittest tests.runtime.test_codex_auth tests.test_providers_api -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Reuse `CodexAuth._server()` and `AppServer.request`. Accept `supportedReasoningEfforts` items as strings or as objects with `reasoningEffort`, and drop entries that fail `registry.check_effort('codex', …)`. Drop model IDs that fail the registry model shape. Cache in a module dict under a lock; a failure is cached too, so the UI does not respawn Codex on every render, and sign-in/out clears it.

- [ ] **Step 4: Run them and see them pass**

Run: `python3 -m unittest tests.runtime.test_codex_auth tests.test_providers_api tests.test_service_extensions -v`
Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "List each provider's models and efforts for the pickers"`

---

### Task 5: Shared model and effort selects

**Files:**
- Modify: `app/ui/providers.js:40-60, 119-145, 189` (replace `modelInput`; add `effortSelect`, `models(provider)`)
- Test: `tests/providers-ui.mjs`

**Interfaces:**
- Consumes: `provider_models` (Task 4).
- Produces, exported on the providers object:
  - `P.models(provider) -> Promise<{models, error}>`, memoized per provider, cleared on sign-in/out.
  - `P.modelInput(parent, {id, label, provider, value, defaultLabel})`. Same name and call shape, so callers keep working. It returns a `<select>` when the provider has a list, else today's text input with the error sentence as a footnote. Either way the element exposes `.value`, `.setProvider(next)` and fires `oninput`/`onchange`. The first option has value `''` and text `defaultLabel || 'Default (' + default model + ')'`. A `value` not in the list is added as `value + ' (not available)'` and selected.
  - `P.effortSelect(parent, {id, label, provider, model, value, defaultLabel}) -> HTMLSelectElement` with `.setModel(provider, model)`. Options: Default first, then the model's `efforts` (Claude: registry list). `setModel` keeps the value if still offered, else resets to `''`.

- [ ] **Step 1: Write the failing UI test**

In `tests/providers-ui.mjs`, with the fake backend answering `provider_models`:
- the researcher row shows a `select#route-researcher-model` whose options are Default plus the two Codex models;
- the row also shows `select#route-researcher-effort`;
- choosing a model whose efforts lack `xhigh` resets effort to Default;
- switching provider to Claude refills both selects and resets effort;
- Save sends `{'provider','model','effort'}` for each role;
- when `provider_models` returns `error`, the row shows a text input and the error sentence;
- saved routing with a model not in the list shows "gpt-5-old (not available)" selected, and Save shows a warning naming it.

- [ ] **Step 2: Run it and see it fail**

Run: `node tests/run-ui.cjs providers-ui`
Expected: FAIL.

- [ ] **Step 3: Implement**

`routingRow` adds the effort select next to the model, wires `target.effort`, and calls `effort.setModel` on model and provider change. `save` validates effort with the same check as the model and sends it. The Default label for effort: `'Default (low)'` for Claude, `'Default (' + model.default_effort + ')'` for a Codex model, `'Default'` when unknown.

- [ ] **Step 4: Run it and see it pass**

Run: `node tests/run-ui.cjs providers-ui`
Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "Pick each role's model and effort from dropdowns in Settings"`

---

### Task 6: New task and team card use the selects

**Files:**
- Modify: `app/ui/agent-new.js:23-40, 52-58, 81-131`
- Modify: `app/ui/team-card.js:67-77`
- Modify: the New task form markup that holds `#new-model` and `#new-model-list` (find it with `graphify query "new-model input New task form"`)
- Test: `tests/agent-ui.mjs`, `tests/team-card-ui.mjs`

**Interfaces:**
- Consumes: `P.modelInput`, `P.effortSelect` (Task 5); `orchestrator_choice`'s effort rule (Task 2).

- [ ] **Step 1: Write the failing UI tests**

- `agent-ui.mjs`:
  - with routing Orchestrator effort `high`, New task shows the effort select with `Default (your default: high)`;
  - submitting with defaults sends no `effort`;
  - picking `max` sends `effort: 'max'`;
  - picking another model resets effort to Default;
  - the summary line reads `Claude · claude-opus-5-5 · high effort (from your defaults)`.
- `team-card-ui.mjs`:
  - a member's model is a `select.member-model` with Default plus the provider's models;
  - changing provider refills it;
  - there is no effort control on the card.

- [ ] **Step 2: Run them and see them fail**

Run: `node tests/run-ui.cjs agent-ui && node tests/run-ui.cjs team-card-ui`
Expected: FAIL.

- [ ] **Step 3: Implement**

Replace `#new-model` and its datalist with `P.modelInput` and `P.effortSelect` built at form open. `resolved()` gains effort under the Task 2 rule, and params send `effort` only when the user picked one. In `team-card.js`, keep the `P.modelInput` call. Change `model.oninput` to `onchange` if the element is a select, and drop the `checkModel` clearing, because a select cannot hold an invalid value.

- [ ] **Step 4: Run them and see them pass**

Run: `node tests/run-ui.cjs agent-ui && node tests/run-ui.cjs team-card-ui && node tests/run-ui.cjs subagents-ui`
Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "Use the model and effort dropdowns in New task and the team card"`

---

### Task 7: Full suite, docs, app build

**Files:**
- Modify: `app/README.md` (Settings → Providers paragraph: model and effort dropdowns, the Codex list from your account, the typed fallback)
- Modify: `dist/Interspace.app` (rebuilt)

- [ ] **Step 1: Run the whole suite**

Run: `python3 -m unittest discover -s tests -q` then `for t in providers-ui agent-ui team-card-ui subagents-ui e2e-ui research-e2e-ui; do node tests/run-ui.cjs $t || break; done`
Expected: all pass.

- [ ] **Step 2: Update the README paragraph and rebuild**

Run: `python3 scripts/build-macos-app.py` then `graphify update .`
Expected: the build finishes. The app opens, and Settings → Providers shows the Codex models from the signed-in account.

- [ ] **Step 3: Commit**

`git commit -m "Describe the model and effort pickers and rebuild the app"`
