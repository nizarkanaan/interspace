# Interspace project guidance

This repository contains the design prototype, an offline pilot and a native Mac application in `app/`. The app is becoming a **multi-provider agent workspace**: Claude and Codex (Gemini later) run as agents under one Orchestrator, which proposes teams of subagents on mixed providers that run in parallel. See the multi-provider section below.

The user authorized the first working workflow on a branch with Sample Project as read-only input. Keep snapshot/pilot helpers under `pilot/`, native/backend/UI code under `app/`, tests under `tests/`, and development run data under ignored `workspace-data/`. App user data belongs in its Application Support directory. See `app/README.md`. Never modify, checkout or run the sample project. Preserve existing source edits. Do not merge a branch into main without the user accepting it.

## Multi-provider workspace (approved 2026-11-15, being built)

The user approved `docs/superpowers/plans/2026-11-15-multi-provider.md`. It replaces the Agentic Spaces roadmap. It is built in parallel waves; the frozen contracts are in `docs/superpowers/specs/multi-provider/`, with the parts of `docs/superpowers/specs/agentic-spaces/` they keep. Code against them and ask the coordinator before changing any shape.

- **One task type.** Every new task is a conversation with the Orchestrator agent. The Read-only review and Fix & test (Python) modes, the Observatory, Workspace advice, project conversation and connected apps (Notion, GitHub, Google Drive, Zotero) are removed. Earlier tasks stay readable and never run again.
- **Teams need approval.** The Orchestrator proposes a team: role, brief, provider, model and read or write access per subagent. The user's per-role routing defaults apply unless the Orchestrator suggests otherwise with a reason. Nothing runs until the user approves the team, edits included. Edits invalidate the proposal.
- **Workspace access like Codex auto mode.** Each agent works in its own isolated local clone of the project, published to the user's repository only as its own `interspace/task-…` branch. Read roles get no write or writing-command permissions. Claude agents may write inside their own workspace through scope-decided permission prompts, like Codex `workspace-write`; the earlier Claude read-only rule is retired.
- **Merge is explicit.** Changes reach the user's branches only through the explicit **Merge** action, which runs in a temporary worktree, never touches the checked-out branch or working files, never forces, and reports conflicts.
- **One scope approval per task.** Inside the scope agents act without asking; outside it, that task alone pauses and asks (Allow once, Add to scope, Deny). Command network is off by default and asks per host. MCP tools other than Interspace's own always ask.
- **Always deny:** credential files and the Keychain (the sandbox may not block every read; see the contracts), sandbox or approval bypass modes (never Codex `danger-full-access` or `--dangerously-bypass-approvals-and-sandbox`, never Claude `bypassPermissions`), privilege escalation, writes outside the task workspace, Interspace's own app data, and an agent editing its own scope, budget or team.
- **Many tasks at once.** Up to 4 agent runs in parallel by default (changeable); subagents each take a run slot. Writes to the user's repository (cloning, branch publishing, merge) are serialised by project locks.
- **Providers use the user's own sign-ins.** Codex signs in to an app-owned `CODEX_HOME`; Claude uses the user's `claude` sign-in. Gemini waits for the user's choice (`agy` with a Google account for read roles, or a paid API key). Real sign-ins and real model calls during development need the user's explicit approval at the time.

Kept: an approval binds the exact scope and team, enforced at the execution boundary; no automatic retries or resumes after failure or restart; a full append-only audit trail; the provider-independent UI. Sample Project stays read-only and is not accessed; Snack Picker is the only authorized live write-test target. Routine tests use disposable repositories and fake CLIs, never personal app data or real source projects.

## Token budgets

Every task-owned model call, the Orchestrator's and every subagent's, passes the per-task budget gate (`app/backend/budget.py`) before it starts. One budget covers a task and all its subagents; each provider's usage is charged by its own rule from the provider registry. Budgets are tokens only; never show or imply money or remaining account allowance. The budget is part of the task scope. See `app/README.md#token-budgets`.

## Product boundaries

- Each installation belongs to one person and runs on their own machine.
- Do not introduce lab membership, invitations, a hosted multi-user service, or shared provider credentials without a new request.
- Keep the UI provider-independent: every provider goes through the registry and the runtime adapter API.
- Do not imply a consumer subscription includes arbitrary third-party API access. Verify supported authentication before implementing it.
- Keep private project data and credentials out of git. Store credentials in the macOS Keychain or the provider's own store.
- No real email, calendar, filesystem, repository, or external-app writes in the design prototype.
- Agent activity, papers, hypotheses, metrics and run outcomes in the prototype must be clearly identified as sample data.
- Approval must bind to an exact proposed action and scope. Edits invalidate an approval. For agent tasks the approved objects are the task scope and each team.

## Design

Read docs/design-direction.md before changing the UI. Keep accessible controls, light/dark appearance and responsive layout. Avoid decorative activity that implies real agent work.

The design preview under `design/` is a separate throwaway prototype. Its sources are design/observatory.fragment.html (UI/state), design/scene/lab-scene.js (static character artwork and hit testing), and design/agents/ (role catalog and contract data). Generate design/index.html and design/preview.fragment.html with `node scripts/build-preview.mjs`; never edit the generated page independently. Run `node scripts/build-preview.mjs --check` and `node scripts/build-role-playbooks.mjs --check` before committing preview changes. Role contract changes regenerate docs/agent-playbooks.md. Never claim agent accuracy without model-backed evaluation evidence. Do not promote the preview into the production app without agreeing on architecture and scope.

## Engineering conventions

Use `interspace/` for new branch names, following the user's naming preference. No `claude/` branch names and no AI co-author trailers in commits.

Parallel work follows the plan's working rules: one session and git worktree per stream, a declared set of owned files, and one owner per shared file per wave (`service.py`, `scheduler.py`, `index.html`, `app.js`, `main.swift`). A stream that needs a change outside its files, or to a frozen contract, asks the coordinator. Routine tests use fake CLIs and a fake runtime; never the user's real accounts.

Read docs/engineering.md before implementing or debugging. Keep changes focused and follow the dependency boundaries there. Reproduce bugs and trace their cause before editing; use meaningful regression coverage for behavioral fixes. Verify the affected behavior and report actual results, including anything untested. Do not create speculative framework layers, empty application directories, or shared utilities without a concrete use.

The conventions incorporate ECC coding/design/verification guidance and Superpowers debugging/test-first/verification workflows; docs/engineering.md records the sources and adaptations. When installed, read and apply the relevant skill for the task. Keep the repository understandable and usable without requiring contributors to install those plugins. Do not claim skill compliance or successful verification merely because this guidance exists.
