# Interspace Mac app

Launch `dist/Interspace.app` with a double-click. It opens its own native window; no HTML file, browser tab or local web server is required. The backend starts and stops with the application.

Add a Git repository folder, select its project conversation, and describe an outcome. The Orchestrator can answer directly or propose the smallest team from **Web searcher, Researcher and Reviewer**. Inspect objectives, expected outputs, dependencies, source revision and usage ceiling, then choose **Start this plan**. Tasks and the static Observatory show the same recorded assignments. The Combined result preserves evidence and unresolved questions; each specialist artifact remains inspectable. Other catalog roles and external-app writes remain unavailable.

## Connection

The application discovers `codex` on PATH or the official ChatGPT/Codex Mac application's bundled CLI. **Check connection** queries Codex's sign-in status. **Sign in with ChatGPT** starts the CLI's device authorization flow and displays its instructions in the window. Finish that authorization in your browser. Credentials remain in Codex's own store; Interspace never reads or copies the credential file.

The CLI's configured authentication determines account usage. ChatGPT sign-in uses the supported Codex path and its account limits; API-key sign-in is separately billed. Returned token counts are displayed. Monetary cost and remaining subscription allowance are not inferred.

## Data and project protection

Conversations, plans, usage records and source snapshots live in `~/Library/Application Support/Interspace`. The source checkout is never edited or executed. Selected technical evidence comes from its committed revision; uncommitted and private files are excluded. Approvals bind to a stable project ID, canonical project path, committed revision and (for report actions) artifact version. If HEAD changes, request a new plan.

One app backend may own a data directory at a time. One interaction runs at a time; a team uses one to three sequential specialist jobs and one synthesis job, each with a four-minute deadline and no retries. A proposal shows one already-used planning call and up to four calls after Start. Legacy reviews retain their original two-stage path. Stop terminates the owned provider process group. Quit closes the backend input pipe and guarantees cancellation cleanup. On restart, unfinished runs become interrupted rather than silently resuming. A stage deadline is not a monetary spending cap.

External document text is input evidence, never permission to run tools. CLI shell and multi-agent features remain disabled; jobs ignore user configuration, execution rules and automatically loaded project instructions. All jobs use the CLI read-only sandbox/never-approve policy. Text-only planner, Researcher, Reviewer and synthesis jobs reject tool events. Only an explicitly approved Web searcher assignment enables hosted live search. It receives the displayed public objective in a fresh app-owned provider workspace, without project sources, the full goal, history, prior reports or dependency artifacts. Search jobs still reject other tools. Observed URL events establish retrieval provenance for accepted web evidence; invented or private/local source URLs fail validation. The process adapter is not a replacement for Codex's sandbox or a containment boundary for a malicious executable. Only use the official Codex installation.

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
- `backend/service.py`: ownership-bound conversations, content-bound plans, legacy dispatch and protocol actions.
- `backend/orchestration.py`: bounded team graph, evidence validation, versioned team records and report acceptance.
- `backend/team.py`: dependency handoffs, durable call reservations, specialist dispatch, synthesis and partial failure.
- `backend/provider.py`: signed-in Codex CLI process adapter, event validation, deadlines and cancellation.
- `ui/index.html`, `ui/app.js`, `ui/team.js`: app interface, conversation state, team plans/tasks/results and legacy report views; model/report text is inserted as text, not executable markup.
- `ui/workspace.js`: project picker, metadata drafts, overview cards and run-history controls.
- `../pilot/runner.py`: reusable committed snapshots, evidence validation and source integrity checks.
- `../scripts/build-macos-app.py`: reproducible app packaging.

Routine tests use disposable Git repositories and fake provider processes, never personal projects or paid model calls. Target-machine launch and real provider checks are documented separately from unit tests.

## How roles connect to Codex

Interspace uses one Codex sign-in and starts separate ephemeral `codex exec` jobs for planning, each approved specialist assignment and final synthesis. It does not keep a single ongoing Codex conversation or depend on the controlling ChatGPT chat. Codex's built-in multi-agent spawning is disabled; Interspace coordinates the jobs and hands off artifacts explicitly. All current jobs use the same provider/default model setting, with role-specific instructions and inputs.

Interspace stores conversations locally. A new Orchestrator job receives recent conversation plus selected project context and prior results. Researcher and Reviewer receive their committed snapshot, role playbooks and assigned dependency artifacts. The Reviewer must cover all other assignments in a reviewed plan. Web searcher receives only the disclosed public objective. They do not inherit one another's private session context. These jobs share the authenticated account's usage limits; an idle app does not run model jobs. Separate jobs resend their selected context, so future persistent threads may be an optimization, rather than a current capability.

## Team results and evidence

A proposed team is complete before Start. Changes requested in chat replace its identity and content digest; stale Start actions fail. The runtime accepts one assignment per executable role, rejects dependency cycles and stops when a required task fails. No specialist can dispatch another job. A required call is reserved durably before provider launch; cancellation, timeout and restart never retry it automatically. Completed artifacts survive failed synthesis or cancellation.

Combined results label facts, interpretations and proposals, cite committed source lines or retrieved web excerpts, and retain unresolved questions and Reviewer objections. A Reviewer checks supplied excerpts and artifacts without browsing independently; a retrieved excerpt is not a claim that a full paper was read. Tokens appear when returned; unknown consumption is shown as unavailable. Call/deadline limits do not cap tokens, money, search actions or remaining subscription allowance.

**Accept this report** is available only after Reviewer acceptance, successful synthesis and unchanged source integrity. Acceptance binds the exact plan, evidence and result content and authorizes the report only. Runs without a Reviewer finish as **completed unreviewed** and cannot be accepted through the reviewed-report action. New team runs need a new approved plan for further work; they do not use the legacy revision loop.

## Revise and accept legacy reports

For saved legacy two-stage reviews, when a Reviewer requests changes, **Revise from reviewer feedback** starts one additional Researcher → Reviewer round against the same committed snapshot. It adds two Codex jobs without an extra planning call. You can instead ask the Orchestrator for a revision plan; that conversation adds its own job. Supplemental instructions in that plan reach both revision workers.

The one-round allowance is reserved before dispatch and survives cancellation, failure and restart. It cannot loop indefinitely. Old results remain available in **Artifact version**, and Run history identifies each round. Source changes or stale artifact references block actions. After the Reviewer accepts a report, **Accept this report** records your acceptance of that exact artifact without a model call. It does not authorize code changes or the proposed experiment.

## Multiple projects

**Add project folder** registers another repository without clearing existing conversations or reviews. Choose its repository root, with a committed `README.md`. Project chat prefers committed `docs/PROJECT_CONTEXT.md` when present, otherwise README. Review snapshots still use the explicit technical allowlist in `pilot/runner.py`; registering a repository does not expose all its files. Source selection beyond that allowlist is future work. Re-adding the same canonical folder selects its existing record and refreshes its context choice.

The project picker switches among separate conversations, pending plans and report histories. **Project brief & priority** saves a name, brief (1,200 characters), high/normal/low priority and next action locally, without a model call or source edits. **Project review history** restores a prior run; **Artifact version** selects rounds within that run. Unsent chat and metadata drafts survive switching in the current app session, but are not persisted across app restarts.

In Workspace scope, the project desk shows all registered projects. Workspace Orchestrator receives only names, briefs, priorities, next actions, proposal availability and latest review status. It can suggest priorities; it does not automatically edit metadata or dispatch across projects. Raw sources, report bodies and project conversations are excluded from Workspace prompts. Project scope receives only that project's own context and selected report. User-entered briefs are intentionally available to Workspace summaries.

You can browse another project or report while a job runs. The active banner names the actual owner, and the worker saves results, failures and usage to that owner. Only one interaction runs at a time. Mutating actions carry explicit project IDs; stale project/run/artifact references fail before dispatch.

Existing single-project state migrates automatically to version 2, preserving its conversations, plan, run and usage. The original is kept once as `state.v1-backup.json` beside `state.json`. Migration does not revise or accept a saved report. Unknown future schema versions fail without overwriting the state.
