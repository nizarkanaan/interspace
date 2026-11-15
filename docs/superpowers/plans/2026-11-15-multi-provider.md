# Multi-provider agent workspace: revamp plan

Date: 2026-11-15. Status: approved by the user on 2026-11-15. Branch: `interspace/multi-provider`, from `main` (`6823383`).

## Context

The user is dropping the connected apps (Notion, GitHub, Google Drive, Zotero) because they are too much trouble to keep building. The new point of Interspace:

- Claude, Codex and later Gemini work under **one workspace**, used **at once**.
- An **orchestrator** picks the best provider for each subagent. For example, Gemini researches, Claude codes and Codex reviews.

Prep is done:
- `interspace/agentic-spaces` is merged into `main` (`6823383`). That merge is local only, not pushed.
- The superseded code-first plan is committed as a record.

User decisions (2026-11-15):
1. **Gemini is decided later.** Claude and Codex come first. Context: since 18 June 2026, personal and AI Pro accounts reach Gemini only through the closed-source `agy` (Antigravity CLI), whose headless mode refuses anything needing approval. The open Gemini CLI now needs a paid API key.
2. **Delete the Spaces connector code.** Git history keeps it.
3. **Routing is "auto with your defaults".**
   - You set a default provider per role.
   - The orchestrator may suggest another one.
   - You approve the team, including each subagent's provider, before it starts.
4. **Replace the old task modes** (Read-only review, Fix & test Python), the Observatory and Workspace advice with the new flow. Old task history stays readable.

Unchanged: single person, local, your own sign-ins, token budgets (tokens only, never money), scope and auto-mode policy, Sample Project read-only, Snack Picker as the only live write target, real sign-ins and model calls only with your approval at the time, no Claude co-author trailers, no `claude/` branches.

## Target design

**One task type: a conversation with the Orchestrator.**
1. You describe the goal.
2. The Orchestrator, itself an agent session (default Claude), answers directly or calls `propose_team`.
3. A **team card** appears: role, brief, provider, model and read/write for each subagent, plus the token budget. You approve or edit.
4. Subagents run **in parallel** as child runs. Each runs on its own provider. Coding subagents work in their own git worktree.
5. Results return to the Orchestrator, which synthesises an answer and can propose a follow-up team.
6. Code changes end in **Review changes**: a diff, then an explicit **Merge** into a branch you choose.

**Provider registry** (`app/backend/runtime/registry.py`, new). One entry per provider replaces the hard-coded `('codex','claude')` lists in `runtime/__init__.py:18`, `tasks.py:16`, `agent-new.js:7` and the budget rules. Each entry holds:
- name and factory;
- models and default model;
- capabilities: `write`, `web_search`, `approvals`;
- sign-in check;
- charge rule, moved from `budget.py` `CHARGE_RULES`.

Gemini later becomes one more entry plus an adapter.

**Orchestration tools.** These are exposed to the Orchestrator through the existing provider-neutral MCP bridge (`runtime/mcp_bridge.py`), which now carries orchestration tools instead of connector tools:
- `propose_team(members[])`: pauses for your approval and returns the approved team.
- `run_team()` / `wait(ids)`: wait for children and return their final reports and diff summaries.
- `message_subagent(id, text)`: a follow-up turn on a child.

**Routing defaults** live in Settings → Providers:
- connection status for each provider (`claude auth status`, `codex login status`);
- a Sign in button;
- a default provider and model per role: Researcher, Implementer, Reviewer, Tester, Writer.

The Orchestrator gets these defaults and each provider's capabilities in its prompt. A suggestion for a provider without `write` cannot get a write role.

**Budgets.** One task budget covers the Orchestrator and all children. Each child is charged with its own provider's rule. The scheduler already stops runs that go over (`scheduler.py:964`).

## What gets reused

- **Scheduler:** parallel runs, per-project locks, per-task worktrees (`Workspaces`, `scheduler.py:307`), `RunContext` (`:412`). Children become runs with a `parent_run_id`.
- **Runtimes:** `runtime/codex.py` (`codex app-server`) and `runtime/claude.py` (stream-json with stdio permission prompts).
- **Scope engine** (`scope.py:815` `decide`): it has no provider branch, so it applies to every child unchanged.
- **Agent stream UI:** `app/ui/stream.js`, `agent*.js`, `composer.js`, `scope.js`. Cards get a provider badge.
- **Budget ledger:** `budget.py` `reserve`/`settle`/`ledger`.

## What gets deleted

- **Spaces:**
  - `app/backend/spaces/`;
  - the Spaces parts of `service.py`: `SpacesHub`, `KeychainBridge`, `BridgeCredentials`, the `spaces_*` router, `tool_catalog`, `agent_tool`;
  - the Spaces parts of `scheduler.py`: `_tools`, `_app_tool`, `_app_read`, ancestry;
  - the app-ref and app-decision code in `scope.py`, and the connector journal in `audit.py`;
  - `app/ui/spaces*.js`, the Spaces nav and styles, and the `/spaces` command;
  - `main.swift`'s `spaces_*` allowlist and `SpacesKeychain`;
  - `tests/spaces/`, `tests/spaces-ui.mjs`, and the app cases in the scope, scheduler, agent and audit tests.
- **Old execution:**
  - `provider.py` (`codex exec`), `team.py`, `change_team.py`, `orchestration.py` execution;
  - the Observatory and Workspace advice;
  - the read-only and python_fix modes in `tasks.MODES`.
- Old tasks keep a **read-only history view**: conversation, plan and result text. Nothing in them can run.

## Rule changes (`AGENTS.md`, `docs/engineering.md`)

1. **Claude may write.**
   - Change: Claude agents may edit files and run commands inside their own task worktree.
   - Mechanism: scope decides through the CLI's permission prompts, the same model as Codex `workspace-write`.
   - What it replaces: the earlier "Claude read-only" decision (`provider.claude_readonly`), which goes.
2. **Merge is explicit.** Changes reach a project branch only through **Merge**. This fills the unbuilt `workspace_merge`.
3. **No connected apps.** The Spaces rules go.

## Waves

Same working rules as before:
- a worktree per stream with declared file ownership;
- test-first, with fake CLIs;
- the coordinator (this session) merges and runs full verification;
- new branch `interspace/multi-provider`, cut from `main`.

**Wave 0. Coordinator, sequential, about half a day; 0B runs in parallel.**
- **0A. Delete and contracts** (coordinator).
  - Delete Spaces and the old execution paths.
  - Keep the read-only history view.
  - Write short frozen specs in `docs/superpowers/specs/multi-provider/`: provider registry, orchestration tools, child-run lifecycle, new events (`team_proposed`, `subagent_started`, `subagent_output`, `subagent_finished`), and the routing-defaults schema.
  - Full suites green.
- **0B. Sign-in spike** (one session, parallel with 0A).
  - Sign in to the app-owned `CODEX_HOME` with the Codex device flow.
  - Confirm Claude edit and Bash permission prompts in a scratch worktree.
  - Real sign-in only with your approval at the time.

**Wave 1. 4 sessions in parallel.**

| Stream | Owns |
| --- | --- |
| **1A Providers** | `runtime/registry.py`, `runtime/codex.py` (app-owned `CODEX_HOME` sign-in), `runtime/claude.py` (write mode in the worktree), `tasks.py`, `budget.py` charge rules via the registry |
| **1B Orchestrator engine** | new `orchestrator.py`, `scheduler.py` (child runs, `parent_run_id`, team approval pause, results to parent), `mcp_bridge.py` orchestration tools |
| **1C UI** | `index.html`, `app.js`, `agent*.js`, new `ui/team-card.js`, `ui/providers.js` (Settings → Providers and routing defaults), against fixture events |
| **1D Review and merge** | new `worktree_merge.py`: diff summary per child, merge into a chosen branch, conflicts reported and never forced; `ui/review.js`, registered through a one-line hook owned by 1C |

**Wave 2. 2 sessions: integrate.**
- **2A:** wire the Orchestrator to real runtimes; routing defaults in the prompt; capability checks; budget across children.
- **2B:** live streams of several children in the UI, the Running view grouped by task, and resume after restart (children become interrupted, never silently resumed).

**Wave 3. Close out, in parallel.**
- Independent reviews of three areas: providers, orchestrator and scheduler, UI. Critical and Important findings are fixed test-first.
- Live acceptance on Snack Picker, with your approval at the time:
  1. The Orchestrator, on Claude, proposes a team: Codex researches the code, Claude implements, Codex reviews.
  2. You approve.
  3. The children run in parallel.
  4. You review the diff and merge.
  5. A second task runs at the same time.
- Fix the two timing flakes: `test_known_usage_survives_invalid_final_response` and `test_backend_quit_with_closed_output_stops_active_provider`.

**Later wave G: Gemini.** This waits for your choice of `agy` with your Google account (read-only roles only) or a paid Gemini API key. It needs one adapter in `runtime/gemini.py` plus a registry entry.

**Size:** about 9 sessions. Wave 1 runs 4 at once, which uses your Claude usage several times faster than one session.

## Critical files

- `app/backend/runtime/__init__.py`, `registry.py` (new), `codex.py`, `claude.py`, `mcp_bridge.py`
- `app/backend/scheduler.py`, `orchestrator.py` (new), `worktree_merge.py` (new), `service.py`, `tasks.py`, `budget.py`, `scope.py`, `audit.py`
- `app/ui/index.html`, `app.js`, `agent*.js`, `stream.js`, new `team-card.js`, `providers.js`, `review.js`
- `app/macos/main.swift`: allowlist only
- `AGENTS.md`, `docs/engineering.md`, `docs/superpowers/specs/multi-provider/`

## Verification

- **Backend:** `python3 -m unittest discover -s tests` on Python 3.14 and `/usr/bin/python3` (3.9.6), with no skips.
- **Browser:** `NODE_PATH=…/node_modules node tests/run-ui.cjs`. The `spaces-ui` suite is removed, and suites for the team card, providers and review are added.
- **Fake CLIs:** the existing fake Codex and Claude fixtures (`tests/runtime/fixtures/`) are extended. They prove that a mixed team runs in parallel, that the approval pause works, that each child is charged by its own provider's rule, and that merge conflicts are reported.
- **App check:** build with `python3 scripts/build-macos-app.py` and launch with `--data-root` set to a scratch folder. Screenshot the Orchestrator conversation, the team card and Settings → Providers.
- **Live run:** the Wave 3 acceptance on Snack Picker, only with your approval at the time.
