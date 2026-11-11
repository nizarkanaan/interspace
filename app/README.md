# Interspace Mac app

Launch `dist/Interspace.app` with a double-click. It opens its own native window; no HTML file, browser tab or local web server is required. The backend starts and stops with the application.

The first executable workflow is a read-only project review. Add a Git repository folder, select its conversation scope, and ask the Orchestrator to review its evidence or propose a bounded experiment. It returns an inspectable plan; **Start read-only review** dispatches Researcher then Reviewer automatically through Codex. Tasks, source citations, results and the static Observatory display recorded work. Other catalog roles and external-app writes are not executable in this release.

## Connection

The application discovers `codex` on PATH or the official ChatGPT/Codex Mac application's bundled CLI. **Check connection** queries Codex's sign-in status. **Sign in with ChatGPT** starts the CLI's device authorization flow and displays its instructions in the window. Finish that authorization in your browser. Credentials remain in Codex's own store; Interspace never reads or copies the credential file.

The CLI's configured authentication determines account usage. ChatGPT sign-in uses the supported Codex path and its account limits; API-key sign-in is separately billed. Returned token counts are displayed. Monetary cost and remaining subscription allowance are not inferred.

## Data and project protection

Conversations, plans, usage records and source snapshots live in `~/Library/Application Support/Interspace`. The source checkout is never edited or executed. Selected technical evidence comes from its committed revision; uncommitted and private files are excluded. Approvals bind to a stable project ID, canonical project path, committed revision and (for report actions) artifact version. If HEAD changes, request a new plan.

One app backend may own a data directory at a time. One interaction runs at a time; a review uses two sequential worker sessions with a four-minute deadline each and no retries. Stop terminates the owned provider process group. Quit closes the backend input pipe and guarantees cancellation cleanup. On restart, unfinished runs become interrupted rather than silently resuming. A stage deadline is not a monetary spending cap.

External document text is input evidence, never permission to run tools. This workflow disables CLI shell/multi-agent features and web search, ignores user-configured MCP integrations, uses the CLI read-only sandbox/never-approve policy, and aborts on observed command/file/MCP/search events. The process adapter is not a replacement for Codex's sandbox or a containment boundary for a malicious executable. Only use the official Codex installation.

## Developer build

Requires Apple Silicon macOS 13+, Xcode command-line tools, Python 3.9+ and Codex. The current app is a local development bundle, ad-hoc signed; it is not a notarized installer or a self-contained Python distribution. Labmates currently build from their own checkout and sign into their own account.

```sh
python3 scripts/build-macos-app.py
```

This creates `dist/Interspace.app` from source. No personal state, source snapshot, credentials or prior reports are bundled. The app can be moved after building because backend and UI resources are embedded. Python and Codex remain external prerequisites and are checked at startup/connection time.

For isolated development state, the native executable supports `--data-root /absolute/test/directory`; do not point that directory inside a source project.

## Source ownership

- `macos/main.swift`: native window, folder/path picker, restricted local UI bridge, process lifecycle.
- `backend/projects.py`: versioned registry, v1 migration, project metadata validation.
- `backend/service.py`: ownership-bound conversations, version-bound plans, dispatch and result acceptance.
- `backend/provider.py`: signed-in Codex CLI process adapter, event validation, deadlines and cancellation.
- `ui/index.html`, `ui/app.js`: app interface and conversation/report state; model/report text is inserted as text, not executable markup.
- `ui/workspace.js`: project picker, metadata drafts, overview cards and run-history controls.
- `../pilot/runner.py`: reusable committed snapshots, evidence validation and source integrity checks.
- `../scripts/build-macos-app.py`: reproducible app packaging.

Routine tests use disposable Git repositories and fake provider processes, never personal projects or paid model calls. Target-machine launch and real provider checks are documented separately from unit tests.

## How roles connect to Codex

Interspace uses one Codex sign-in and starts separate ephemeral `codex exec` jobs for Orchestrator turns, Researcher passes and Reviewer passes. It does not keep a single ongoing Codex conversation or depend on the controlling ChatGPT chat. Codex's built-in multi-agent spawning is disabled; Interspace coordinates the jobs and hands off artifacts explicitly. All current jobs use the same provider/default model setting, with role-specific instructions and inputs.

Interspace stores conversations locally. A new Orchestrator job receives recent conversation plus selected project context and prior results. Researcher and Reviewer receive their explicit source snapshot and role playbooks. They do not inherit one another's private session context. These jobs share the authenticated account's usage limits; an idle app does not run model jobs. Separate jobs resend their selected context, so future persistent threads may be an optimization, rather than a current capability.

## Revise and accept reports

When a Reviewer requests changes, **Revise from reviewer feedback** starts one additional Researcher → Reviewer round against the same committed snapshot. It adds two Codex jobs without an extra planning call. You can instead ask the Orchestrator for a revision plan; that conversation adds its own job. Supplemental instructions in that plan reach both revision workers.

The one-round allowance is reserved before dispatch and survives cancellation, failure and restart. It cannot loop indefinitely. Old results remain available in **Artifact version**, and Run history identifies each round. Source changes or stale artifact references block actions. After the Reviewer accepts a report, **Accept this report** records your acceptance of that exact artifact without a model call. It does not authorize code changes or the proposed experiment.

## Multiple projects

**Add project folder** registers another repository without clearing existing conversations or reviews. Choose its repository root, with a committed `README.md`. Project chat prefers committed `docs/PROJECT_CONTEXT.md` when present, otherwise README. Review snapshots still use the explicit technical allowlist in `pilot/runner.py`; registering a repository does not expose all its files. Source selection beyond that allowlist is future work. Re-adding the same canonical folder selects its existing record and refreshes its context choice.

The project picker switches among separate conversations, pending plans and report histories. **Project brief & priority** saves a name, brief (1,200 characters), high/normal/low priority and next action locally, without a model call or source edits. **Project review history** restores a prior run; **Artifact version** selects rounds within that run. Unsent chat and metadata drafts survive switching in the current app session, but are not persisted across app restarts.

In Workspace scope, the project desk shows all registered projects. Workspace Orchestrator receives only names, briefs, priorities, next actions, proposal availability and latest review status. It can suggest priorities; it does not automatically edit metadata or dispatch across projects. Raw sources, report bodies and project conversations are excluded from Workspace prompts. Project scope receives only that project's own context and selected report. User-entered briefs are intentionally available to Workspace summaries.

You can browse another project or report while a job runs. The active banner names the actual owner, and the worker saves results, failures and usage to that owner. Only one interaction runs at a time. Mutating actions carry explicit project IDs; stale project/run/artifact references fail before dispatch.

Existing single-project state migrates automatically to version 2, preserving its conversations, plan, run and usage. The original is kept once as `state.v1-backup.json` beside `state.json`. Migration does not revise or accept a saved report. Unknown future schema versions fail without overwriting the state.
