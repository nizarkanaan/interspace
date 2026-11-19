# Interspace Mac app

Launch `dist/Interspace.app` with a double-click. It opens its own native window; no HTML file, browser tab or local web server is required. The backend starts and stops with the application.

**Status (2026-11-19): a multi-provider agent workspace.** Claude Code and Codex run as agents under one Orchestrator; Gemini comes later. Plan: `docs/superpowers/plans/2026-11-15-multi-provider.md`.
- **Every task** is a conversation with the Orchestrator. It answers directly, or proposes a team of subagents on Claude and Codex that you approve before anything runs.
- **Review and merge:** each writing subagent commits to its own `interspace/task-…` branch. **Review changes** shows the diff; **Merge** merges it into a branch you pick.
- **Removed:** the Read-only review and Fix & test (Python) modes, project sources, Workspace advice, the Observatory, project conversation and connected apps. Earlier tasks still open read-only, labelled "Earlier task (read-only)".
- **Not yet done:** a live run with real Claude and Codex sign-ins inside the app. The full team flow is tested with fake command-line tools.

## Projects and tasks

**Add project folder** registers a Git repository. The project picker switches among projects; each keeps its own tasks. **Settings → Project details** saves a name, brief, priority and next action locally, without a model call or source edits.

**Settings → Providers** shows each provider's sign-in state, starts a sign-in or shows the command to run, and sets the default provider and model for each role (Orchestrator, researcher, implementer, reviewer, tester, writer).

**New task** starts an Orchestrator conversation:
1. Give a title and pick the project. The Orchestrator uses your default provider and model unless you change them here.
2. Review the task scope, then choose **Create task**.
3. Approve the scope on the task, then message the Orchestrator.

**Teams.** When the Orchestrator wants help, it proposes a team. Each member has a role, a brief, a provider, a model and read or write access. A member that differs from your defaults shows the Orchestrator's one-line reason. You can change any member's provider, model, access and brief, or remove members. Nothing runs until you choose **Approve team**; **Decline** can carry a note back to the Orchestrator.

**Subagents.** Approved members run in parallel. Each works in its own copy of the project, and its card on the task shows its state, tokens and latest activity. **Show activity** opens its full stream. Subagents never appear as separate tasks on the desk; **Running** groups them under their task.

**Review changes → Merge.** A writing subagent's changes are committed to its own `interspace/task-…` branch. **Review changes** lists the changed files and the diff. **Merge** merges the branch into the branch you pick, in a temporary worktree, and only if the branch is still the one you reviewed. Interspace never changes your checked-out branch or working files: to merge into the branch you have checked out, run `git merge` there yourself. Conflicts are reported, and nothing is forced.

Inside the scope an agent acts without asking. Outside it, that task alone pauses and asks: Allow once, Add to scope, or Deny. Read-only members and the Orchestrator can never write. Up to 4 agent runs work at once, subagents included; further runs queue.

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
