# Interspace project guidance

This repository contains the design prototype, an offline pilot and a native Mac application in `app/`. The user authorized the launchable app, read-only Orchestrator/task workflow and the controlled Python editing preset. Read-only tasks support Web searcher, Researcher and Reviewer; editing tasks support Researcher, Implementer, Tester and Reviewer, including repeated roles within a user-set allowance. The runtime does not execute all catalog roles.

The user authorized the first working workflow on a branch with Sample Project as read-only input. Keep snapshot/pilot helpers under `pilot/`, native/backend/UI code under `app/`, tests under `tests/`, and development run data under ignored `workspace-data/`. App user data belongs in its Application Support directory. See `app/README.md`. Never modify, checkout or run the sample project from the pilot. Preserve existing source edits; use committed snapshots and verify integrity. Do not merge the pilot branch into main without the user accepting it. Read `pilot/README.md` for the explicit current-session bridge and its limitations.

## Controlled editing

Read `docs/controlled-editing-validation.md` and `app/README.md` for the current implementation and actual acceptance limits. Task mode defaults to review and is immutable. Change plans/runs use dedicated identities; never reinterpret a saved read-only approval as permission to write. Generation, fixed candidate checks and final reviewed application require distinct exact approvals. UI write/check intentions must use backend-projected action references without dropping fields; only read-only post-Apply evidence may derive the documented immutable reference. No automatic repair/resume/retry or source writes after restart. Sample Project stays read-only and is not accessed for the editing pilot; Snack Picker is the sole authorized live write-test target, with coordinator-owned exact approvals. Routine tests use disposable repositories and fake providers, never personal app data or real source projects.

## Token budgets

Every task-owned model call passes the per-task budget gate (`app/backend/budget.py`) in `Application.call` or `team.invoke` before any provider launch or job reservation. Budgets are tokens only; never show or imply money or remaining account allowance. Budgets bind into plans and check approvals like the specialist allowance. For agentic tasks the budget is part of the scope, and every agent turn passes the same gate before it starts. See `app/README.md#token-budgets` and `docs/token-budgets-validation.md`.

## Agentic Spaces (approved 2026-11-11, being built)

The user approved `docs/superpowers/plans/2026-11-11-agentic-spaces-roadmap.md`. It is built in parallel waves. Until each part is merged, the behaviour described in `app/README.md` stays as it is. The frozen interface contracts are in `docs/superpowers/specs/agentic-spaces/`; code against them and ask the coordinator before changing any shape.

For tasks in the new `agent` mode, these rules replace the text-only, one-interaction rules:

- **Workspace access like Codex auto mode.** Agents read, write and run commands inside a task workspace: an isolated local clone of the selected project, published to the user's repository only as its own `interspace/task-…` branch. Interspace never writes the user's checked-out branch or working files; the user merges the branch or uses the explicit Merge action. Anything outside the workspace follows the task scope.
- **One scope approval per task.** The user approves a scope: projects and paths (read or write), commands, network hosts, app resources (read or write), token budget and time limit. Inside the scope the agent acts without asking. Outside it, that task alone pauses and asks (Allow once, Add to scope, Deny).
- **Always ask:** destructive app actions (delete, archive, trash, close, whole-document replacement), commands leaving the sandbox, and MCP tools other than Interspace's own connectors. Command network is off by default and asks per host.
- **Always deny:** credential files and the Keychain (the sandbox may not block every read; see the contracts), sandbox or approval bypass modes (never Codex `danger-full-access` or `--dangerously-bypass-approvals-and-sandbox`, never Claude `bypassPermissions`), privilege escalation, writes outside the task workspace, Interspace's own app data, sharing or permission changes and acting as another account, and an agent editing its own scope or budget.
- **Many tasks at once.** Up to 4 agentic tasks run in parallel by default (changeable). Each keeps its own token budget, cancel and event stream. Writes to the user's repository (cloning, branch publishing, merge) and to the same app resource are serialised by locks.

Kept: the approval binds the exact scope, and any edit to the scope invalidates it, enforced at the execution boundary; no automatic retries of external writes whose outcome is unknown; a full append-only audit trail; per-task token budgets; the provider-independent UI. Existing `review` and `python_fix` tasks keep their exact plan and check approvals unchanged.

**Spaces.** Interspace connects Notion, GitHub, Google Drive and Zotero through free APIs with the user's own accounts. Credentials live only in the macOS Keychain through the Swift bridge, never in app state, logs or git. Browsing and editing in the Spaces UI costs no model call. Connected-app writes by agents happen only inside an approved scope; writes against the user's real accounts during development need the user's explicit approval at the time.

## Product boundaries

- Each installation belongs to one person and runs on their own machine.
- Do not introduce lab membership, invitations, a hosted multi-user service, or shared provider credentials without a new request.
- Keep the UI provider-independent, initially targeting supported OpenAI integrations.
- Do not imply a consumer subscription includes arbitrary third-party API access. Verify supported authentication before implementing it.
- Keep private project data and credentials out of git. Store credentials in the macOS Keychain.
- No real email, calendar, filesystem, repository, or external-app writes in the design prototype. In the app, external-app writes follow the Agentic Spaces rules above.
- Agent activity, papers, hypotheses, metrics and run outcomes in the prototype must be clearly identified as sample data.
- Approval must bind to an exact proposed action and scope. Edits invalidate an approval. For agentic tasks the approved object is the task scope.

## Design

Read docs/design-direction.md before changing the UI. Preserve the observatory direction, accessible controls, light/dark appearance, and responsive layout. Avoid decorative activity that implies real agent work. Agent figures stay in fixed departments; do not add walking, idle animation, or a simulation loop.

The preview sources are design/observatory.fragment.html (UI/state), design/scene/lab-scene.js (original static character artwork and hit testing), and design/agents/ (role catalog and contract data). Generate design/index.html and design/preview.fragment.html with `node scripts/build-preview.mjs`; never edit the generated page independently. Run `node scripts/build-preview.mjs --check` and `node scripts/build-role-playbooks.mjs --check` before committing preview changes. Role contract changes regenerate docs/agent-playbooks.md. Template validation is structural; never claim agent accuracy without model-backed evaluation evidence. Do not promote this throwaway UI into the production app before agreeing on architecture and scope.

## Engineering conventions

Use `interspace/` for new branch names, following the user's naming preference.

Parallel work follows the roadmap's working rules: one session and git worktree per stream, a declared set of owned files, and one owner per shared file per wave (`service.py`, `index.html`, `app.js`, `main.swift`). A stream that needs a change outside its files, or to a frozen contract, asks the coordinator. Routine tests use fake providers, a fake runtime and fake HTTP; never the user's real accounts.

Read docs/engineering.md before implementing or debugging. Keep changes focused and follow the dependency boundaries there. Reproduce bugs and trace their cause before editing; use meaningful regression coverage for behavioral fixes. Verify the affected behavior and report actual results, including anything untested. Do not create speculative framework layers, empty application directories, or shared utilities without a concrete use.

The conventions incorporate ECC coding/design/verification guidance and Superpowers debugging/test-first/verification workflows; docs/engineering.md records the sources and adaptations. When installed, read and apply the relevant skill for the task. Keep the repository understandable and usable without requiring contributors to install those plugins. Do not claim skill compliance or successful verification merely because this guidance exists.
