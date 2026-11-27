# Model and effort pickers

## Intent

Choosing a model for each kind of agent should be a pick from a list, not typing a model name from memory. Today **Settings → Providers** already has a row per role (Orchestrator, researcher, implementer, reviewer, tester, writer, citation checker) with a provider dropdown and a typed model box. Claude's box suggests three IDs; Codex's box suggests nothing. Effort cannot be chosen at all: every Claude run uses `--effort low` (`DEFAULT_EFFORT` in `app/backend/runtime/claude.py`), and every Codex run uses the CLI's default effort.

The user wants, for both Claude and Codex, a model dropdown and a reasoning-effort dropdown for each role, so picking the right model and effort per agent type is easy.

## Goals

- In **Settings → Providers**, each role row has: provider (as today), **Model** dropdown, **Effort** dropdown.
- In **New task**, the Orchestrator override uses the same two dropdowns instead of the typed model box.
- The chosen effort actually reaches the runtime for the Orchestrator and for every subagent on that role.
- Both dropdowns start with a **Default** entry that keeps today's behaviour (stored as `null`).

## Non-goals

- No per-task effort override for subagents in the team-approval card. Subagents take their role's routing.
- No model or effort choice for the claim checker or the evidence extractors beyond their role's routing (they already run under a role).
- No Gemini.
- No pricing or cost display.

## Anti-goals

- A dropdown that lists a model the signed-in Codex account cannot use, so the run fails with `modelNotFound`.
- A saved routing from before this change that stops loading, or that silently changes which model runs.
- Changing Claude's effective effort for users who never touch the setting.

## Constraints

- Claude Code has no command that lists models. The Claude list is the fixed `PROVIDERS['claude']['models']` in `app/backend/runtime/registry.py`: `claude-sonnet-5-5`, `claude-opus-5-5`, `claude-haiku-5-5`. Its default is `claude-sonnet-5-5`.
- Claude effort levels come from `claude --effort`: `low`, `medium`, `high`, `xhigh`, `max`. The same list applies to every Claude model.
- Codex `app-server` has `model/list`. It returns the signed-in account's models with `id`, `isDefault`, `defaultReasoningEffort` and `supportedReasoningEfforts` (docs/research/codex-app-server-runtime.md, lines 278–283). Effort is set by `turn/start.effort` or `config.model_reasoning_effort`.
- The Codex model list depends on the account and the CLI version, so it is read live and never hard-coded.
- Keys, tokens and account details never reach the UI beyond what the sign-in status already shows.

## Approaches

1. **Live Codex list, fixed Claude list (chosen).** The backend asks Codex `model/list` when Settings or New task opens and caches the answer for the app session. If Codex is signed out or the call fails, the Codex model field becomes the typed box it is today, with a one-line note saying why. Claude uses the registry list. This list matches what the account can actually run.
2. **Fixed lists for both.** Simpler, but Codex model names change often and depend on the account, so the list would go stale and offer models that fail. Rejected on the first anti-goal.
3. **Typed box with better suggestions.** Keeps free text and fills Codex's datalist from `model/list`. It doesn't meet "easier to pick": a datalist is not a dropdown and still lets typos through. Rejected.

The user asked for dropdowns for both providers. Approach 1 was proposed and the user went ahead with it, adding effort.

## Design

### Stored routing

Each routing entry gains an optional `effort`: `{"provider", "model", "effort"}`. `null` or a missing key means the provider's default. The document stays `v: 1`. `routing.validate` accepts entries with or without `effort` and always returns it, so old saved routing loads unchanged with `effort: null`. `orchestrator.routing_defaults`' fallback validation path must accept the key too.

### Effort validation

- Claude: one of `low`, `medium`, `high`, `xhigh`, `max`, or `null`. Add `efforts` to the registry record.
- Codex: any short token matching `[a-z]{1,16}` or `null`. The backend does not reject an effort just because the cached `model/list` lacks it, because the list may not have been fetched. The UI only offers efforts from `supportedReasoningEfforts`.
- When the model changes in the UI and the chosen effort is not supported by the new model, the effort resets to Default.

### Runtime

- Claude: `--effort` takes the task's effort. When it is `null`, it stays `DEFAULT_EFFORT` (`low`), so behaviour is unchanged for anyone who never picks.
- Codex: when effort is set, pass it as `turn/start.effort`. When `null`, send nothing, which keeps the CLI default.
- Effort travels exactly like `model` does today: routing → task record (`task['effort']`, validated the way `tasks.validate_model` validates model) → `RunContext` → runtime. This covers the Orchestrator task and team members (`orchestrator.py` around line 170, where a member's model falls back to the role default; effort falls back the same way and is reset to `null` when the member's provider differs from the role's).
- Tasks saved before this change have no `effort` and run as before.
- *(Builder's call, settled in review.)* A team member keeps its role's effort only when it runs the role's provider **and** the role's model. When the Orchestrator or the user picks a different model, even on the same provider, the member's effort resets to `null`, so an effort the new model may not support is never carried over. `propose_team` gets no `effort` field.
- *(Builder's call.)* When Codex refuses an effort for a model, for example after a stale routing, the turn fails with a clear mapped error, as `modelNotFound` does. It is never retried automatically and the effort is never silently dropped.

### Codex model list

- New backend request `provider_models` with `{provider}`. It returns `{models: [{id, is_default, default_effort, efforts: [...]}], error: ""}`.
- For Codex it starts a short-lived `codex app-server` on the app-owned `CODEX_HOME`, sends `initialize`, then `model/list`, then exits, with a 10-second deadline. The result is cached in memory until the app quits or the user signs in or out of Codex.
- For Claude it answers from the registry without a process.
- On any failure it returns an empty list and a safe one-sentence `error`. The UI shows the typed box plus that sentence.

### UI

- `modelInput` in `app/ui/providers.js` becomes a `<select>`: **Default (…)** first, naming the default model when known, then each model. Same in `app/ui/agent-new.js`.
- A new **Effort** `<select>` sits beside it: **Default (…)**, naming `low` for Claude and the model's `defaultReasoningEffort` for Codex, then the supported levels.
- When the provider changes, both selects refill and reset to Default.
- A stored model that is no longer in the live Codex list stays shown as a selected entry marked "(not available)", and Save warns about it instead of silently dropping it.
- The New task summary line shows effort next to model, e.g. "Claude · claude-opus-5-5 · high effort".
- *(Builder's call.)* In **New task**, "Default" means **your routing default**, matching how the model field works today: "Default (your default: high)" when Settings sets an Orchestrator effort, otherwise the provider default. `service.orchestrator_choice` fills the effort from `routing.orchestrator` when the request sends none. If the user overrides the provider or the model, the effort falls back to that provider's default unless they also pick one.
- *(Builder's call.)* The **team-approval card** (`app/ui/team-card.js`) shares `P.modelInput`, so its model field becomes the same dropdown, with the same Codex fallback and "(not available)" handling. It gets **no** Effort select: members take their role's effort under the rule above.

### Tests

- `routing.validate`: old routing without `effort` loads with `null`; bad effort refused with a safe message.
- Claude runtime argv carries the chosen effort, and `low` when `null`.
- Codex runtime sends `turn/start.effort` only when set.
- `provider_models` against the fake Codex app-server fixture: success, signed out, timeout.
- Team member effort: kept on the role's provider and model, reset to `null` on a different model or provider.
- UI test for the Settings row, New task and the team card's model dropdown: selects fill, the effort reset on model change, the typed-box fallback.

## Left to the builder

- The exact visual layout of the two selects in the existing route row grid (follow existing field styles).
- Whether `provider_models` reuses the runtime's app-server launch helper or a small dedicated one.
- Wording of the fallback note, within the house style (plain, one sentence).
