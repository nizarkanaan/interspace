# Interspace Mac app

Launch `dist/Interspace.app` with a double-click. It opens its own native window; no HTML file, browser tab or local web server is required. The backend starts and stops with the application.

**Status (2026-11-15): being rebuilt as a multi-provider agent workspace.** Plan: `docs/superpowers/plans/2026-11-15-multi-provider.md`.
- **Planned:** every task will be a conversation with an Orchestrator that proposes teams of Claude and Codex subagents. You approve each team before it runs.
- **Today:** agent tasks run one agent (Codex or Claude Code) under an approved scope.
- **Removed:** the Read-only review and Fix & test (Python) modes, project sources, Workspace advice, the Observatory, project conversation and connected apps. Earlier tasks still open read-only, labelled "Earlier task (read-only)".

## Projects and tasks

**Add project folder** registers a Git repository. The project picker switches among projects; each keeps its own tasks. **Settings → Project details** saves a name, brief, priority and next action locally, without a model call or source edits.

**New task** creates an agent task.
1. Pick the runtime and model.
2. Review and approve the task scope.
3. Message the agent.

The agent works in its own copy of the project. That copy is published to your repository only as its own `interspace/task-…` branch. Interspace never writes your checked-out branch or working files.

Inside the scope the agent acts without asking. Outside it, that task alone pauses and asks: Allow once, Add to scope, or Deny. Up to 4 agent runs work at once; further runs queue. **Running** shows them all.

## Connection

The app finds `codex` on PATH or inside the official ChatGPT/Codex Mac app, and checks its sign-in. Claude Code uses your own `claude` sign-in. Credentials stay in each provider's own store; Interspace never reads or copies them.

Model use counts against your own accounts. Returned token counts are displayed. Money and remaining subscription allowance are never inferred.

## Token budgets

Each task has a **token budget**, 250,000 by default.
- It counts the tokens each provider reports for every model call the task owns:
  - **Codex:** `input + output`.
  - **Claude:** `input + cache creation + cache read + output`.
- **Before each turn:** the app reserves an estimate and refuses a turn that cannot fit.
- **A run that hits the limit** stops as **Budget exhausted**.
- **A call that reports no counts** is charged its estimate and labelled as estimated.

Budgets are tokens only.

## Data and project protection

Tasks, events, usage records and audit logs live in `~/Library/Application Support/Interspace`.

Always refused:
- credential files;
- bypass modes;
- writes outside the task's own copy;
- Interspace's own data.

On restart, unfinished runs become interrupted rather than silently resuming. Existing saved state from earlier versions migrates automatically, with backups beside `state.json`. Unknown future schema versions fail without overwriting the state.

## Developer build

Requires Apple Silicon macOS 13+, Xcode command-line tools and Python 3.9+, plus Codex and/or Claude Code for agent runs. The current app is a local development bundle, ad-hoc signed; it is not a notarized installer or a self-contained Python distribution.

```sh
python3 scripts/build-macos-app.py
```

This creates `dist/Interspace.app` from source. No personal state, credentials or prior reports are bundled.

For isolated development state, the native executable supports `--data-root /absolute/test/directory`. Do not point that directory inside a source project.
