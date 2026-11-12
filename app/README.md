# Interspace Mac app

Launch `dist/Interspace.app` with a double-click. It opens its own native window; no HTML file, browser tab or local web server is required. The backend starts and stops with the application.

The app opens on **Tasks**. Select or add a Git repository, then open **Settings → Sources**, inspect committed files and **Save sources**. Choose **New task**, describe the outcome (up to 6,000 characters), and set a **Specialist allowance** (default 6, any positive JavaScript-safe whole number). **Create draft** durably saves the full goal in a local task without a model call; **Propose a plan** creates the task and sends its full goal to the Orchestrator. Its display title is limited to 160 characters.

Each task owns separate **Conversation**, **Plan**, **Activity** and **Result** sections. For **Read-only review** (the default), the Orchestrator may answer directly or propose the smallest useful team from **Web searcher, Researcher and Reviewer** within the allowance. **Fix & test (Python)** creates an immutable editing task with Researcher, Implementer, Tester and Reviewer assignments as needed. Plan rows show distinct assignments, including repeated roles. Expand **Assignment details** for expected output and the exact public search brief; **Approved sources & scope** shows committed revision, selected paths and selection version. The actual team and exact call ceiling are fixed by that proposal. **Start this plan** is available from Plan. Changing an unstarted task's allowance or replacing a proposal requires a fresh approval.

Activity shows recorded reservations, assignment states and events. **Result** leads with the combined answer and its report actions. **Specialist outputs, evidence & history** expands the distinct assignment outputs, citations and run history; **Usage & integrity** holds reservation and source-check detail. **Task run history** restores an older report and retains its exact artifact acceptance reference. Failed, cancelled, interrupted and unreviewed output stays labelled; saved partial artifacts remain inspectable. The optional **Observatory** displays the same assignments with the original static figures in fixed departments, without simulated progress or movement. Other catalog roles and external-app integrations remain unavailable.

**Project conversation** preserves the separate general project chat. **Workspace advice** is a distinct surface for metadata-only prioritization. **Settings** contains project details, source consent and the connection controls. An active banner names the actual project/task owner while browsing other work, and **Stop run** targets that active interaction.

## Connection

The application discovers `codex` on PATH or the official ChatGPT/Codex Mac application's bundled CLI. **Check connection** queries Codex's sign-in status. **Sign in with ChatGPT** starts the CLI's device authorization flow and displays its instructions in the window. Finish that authorization in your browser. Credentials remain in Codex's own store; Interspace never reads or copies the credential file.

The CLI's configured authentication determines account usage. ChatGPT sign-in uses the supported Codex path and its account limits; API-key sign-in is separately billed. Returned token counts are displayed. Monetary cost and remaining subscription allowance are not inferred.

## Token budgets

Each task has a **token budget**: 250,000 by default, set on **New task** and editable on the Plan tab. It counts the tokens Codex reports for every model call the task owns: planning and conversation, specialists, synthesis and legacy revisions. A call's charge is `input_tokens + output_tokens`. In Codex's usage report, cached input is part of `input_tokens` and reasoning is part of `output_tokens`, so each token counts once. Project conversation and Workspace advice are not budgeted.

Counts only arrive when a call finishes, so the budget is checked **before** each call:
- The app estimates the call from its prompt size, plus fixed allowances for the provider's own instructions and the reply, and refuses the call if the estimate does not fit what remains.
- A refused call starts nothing and consumes no reservation. A run that hits the limit stops as **Budget exhausted** and keeps its completed artifacts and check results, with no retry.
- A call that started may finish slightly over the budget; any overshoot is shown.
- A call that returns no counts, because it failed, was cancelled or the app quit mid-call, is charged its estimate and labelled as estimated.

The task header shows `Tokens used / budget`. Plan and check-approval screens show the remaining budget and a projected total; Start and Run checks warn when the plan likely will not fit, and are blocked only when no next call can fit at all. The budget in force is part of each plan and check approval: editing it clears unstarted plans, makes an earlier check approval stale, and never resumes a stopped run.

Tasks created before budgets show **No budget set** and are not limited until you set one. Budgets are tokens only: Interspace does not know money, prices or your account's remaining allowance.

## Data and project protection

Conversations, plans, usage records and source snapshots live in `~/Library/Application Support/Interspace`. Read-only tasks never edit or execute the source checkout. Python editing tasks generate and check app-owned copies; only the separate exact **Apply reviewed changes** action writes the approved paths to the original checkout. Evidence comes only from the approved committed source set; working drafts are excluded. Known credential filenames are unavailable, but eligibility does not certify that a selected text file contains no secrets. Approvals bind to a stable project ID, canonical project path, committed revision, exact selected paths and selection version, and (for report actions) artifact version. If HEAD changes, request a new plan.

One app backend may own a data directory at a time. One interaction runs at a time. A task’s positive specialist allowance limits the proposed number of assignments, including repeated roles; it is not a fixed six-specialist cap. A proposal shows one already-used planning call and exactly one call per approved specialist assignment plus one synthesis call after Start, each with a four-minute deadline and no retries. There is no automatic team expansion. Legacy reviews retain their original two-stage path. Stop terminates the owned provider process group. Quit closes the backend input pipe and guarantees cancellation cleanup. On restart, unfinished runs become interrupted rather than silently resuming. A stage deadline is not a monetary spending cap.

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
- `backend/projects.py`, `backend/tasks.py`: versioned project/task registry, v1/v2 migration, durable task ownership, metadata and registration consent state.
- `backend/sources.py`: committed tree/preview access, bounded source selection, selected snapshots and legacy snapshot loading.
- `backend/service.py`: ownership-bound conversations, content-bound plans, legacy dispatch and protocol actions.
- `backend/orchestration.py`: bounded team graph, evidence validation, versioned team records and report acceptance.
- `backend/team.py`: dependency handoffs, durable call reservations, specialist dispatch, synthesis and partial failure.
- `backend/changes.py`, `backend/change_apply.py`: bounded replacement policy, immutable candidate/evidence and guarded source application with durable journals.
- `backend/checks.py`: fixed, restricted three-phase Python unittest adapter and runtime identity.
- `backend/change_team.py`: editing planning, generation, durable test approval pause, check handoffs, review and synthesis.
- `backend/provider.py`: signed-in Codex CLI process adapter, event validation, deadlines and cancellation.
- `ui/index.html`, `ui/desk.css`, `ui/app.js`, `ui/team.js`, `ui/changes.js`: native task desk, scoped drafts/navigation, team plans/assignments/results and legacy report views; model/report text is inserted as text, not executable markup.
- `ui/workspace.js`: project picker, metadata drafts, overview and owner-bound run-history controls.
- `ui/sources.js`: project source drafts, consent and asynchronous source replies.
- `../pilot/runner.py`: reusable committed snapshots, evidence validation and source integrity checks.
- `../scripts/build-macos-app.py`: reproducible app packaging.

Routine tests use disposable Git repositories and fake provider processes, never personal projects or paid model calls. Target-machine launch and real provider checks are documented separately from unit tests.

## How roles connect to Codex

Interspace uses one Codex sign-in and starts separate ephemeral `codex exec` jobs for planning, each approved specialist assignment and final synthesis. It does not keep a single ongoing Codex conversation or depend on the controlling ChatGPT chat. Codex's built-in multi-agent spawning is disabled; Interspace coordinates the jobs and hands off artifacts explicitly. All current jobs use the same provider/default model setting, with role-specific instructions and inputs.

Interspace stores conversations locally. A new Orchestrator job receives recent conversation plus selected project context and prior results. Researcher and Reviewer receive their committed snapshot, role playbooks and assigned dependency artifacts. The Reviewer must cover all other assignments in a reviewed plan. Web searcher receives only the disclosed public objective. They do not inherit one another's private session context. These jobs share the authenticated account's usage limits; an idle app does not run model jobs. Separate jobs resend their selected context, so future persistent threads may be an optimization, rather than a current capability.

## Team results and evidence

A proposed team is complete before Start. Changes requested in chat replace its identity and content digest; stale Start actions fail. The runtime accepts repeated executable roles as distinct assignments, rejects duplicate assignment identities and dependency cycles and stops when a required task fails. No specialist can dispatch another job. A required call is reserved durably before provider launch; cancellation, timeout and restart never retry it automatically. Completed artifacts survive failed synthesis or cancellation.

Combined results label facts, interpretations and proposals, cite committed source lines or retrieved web excerpts, and retain unresolved questions and Reviewer objections. A Reviewer checks supplied excerpts and artifacts without browsing independently; a retrieved excerpt is not a claim that a full paper was read. Tokens appear when returned; unknown consumption is shown as unavailable. Call/deadline limits do not cap tokens, money, search actions or remaining subscription allowance.

Every finding requires 1–10 citations in both the provider response schema and runtime validation. Proposal citations identify the source context motivating a change; they do not establish that it is implemented or validated. Ideas without relevant supplied evidence belong in unresolved questions. Invalid output stops the run without a retry or dependent dispatch.

**Accept this report** is available only after Reviewer acceptance, successful synthesis and unchanged source integrity. Acceptance binds the exact plan, evidence and result content and authorizes the report only. Runs without a Reviewer finish as **completed unreviewed** and cannot be accepted through the reviewed-report action. New team runs need a new approved plan for further work; they do not use the legacy revision loop.

## Revise and accept legacy reports

For saved legacy two-stage reviews, when a Reviewer requests changes, **Revise from reviewer feedback** starts one additional Researcher → Reviewer round against the same committed snapshot. It adds two Codex jobs without an extra planning call. You can instead ask the Orchestrator for a revision plan; that conversation adds its own job. Supplemental instructions in that plan reach both revision workers.

The one-round allowance is reserved before dispatch and survives cancellation, failure and restart. It cannot loop indefinitely. Old results remain available in **Artifact version**, and Run history identifies each round. Source changes or stale artifact references block actions. After the Reviewer accepts a report, **Accept this report** records your acceptance of that exact artifact without a model call. It does not authorize code changes or the proposed experiment.

## Choose project sources

**Sources** lists committed file names and sizes with a filter, checkboxes and read-only **Preview** actions. Previews show committed content, its revision and LF line numbers, at most 200 lines with an explicit omission label. Previewing a file does not select it for models. Save a reusable source set for each project; it is applied to subsequent project chats and new specialist plans without a model call.

New projects show README and PROJECT_CONTEXT when available as suggestions, but project chat remains blocked until the first Save. Existing projects retain their previously authorized legacy defaults until an explicit source selection is saved. Updating the selection invalidates unstarted proposals and increments its version. A stale save or Start fails; source saves are blocked while work is active. A changed commit requires refreshing, inspecting and saving Sources again. Missing selected files are never silently replaced.

Choose 1–16 UTF-8 regular committed files, at most 250,000 bytes each and 240,000 characters of numbered specialist context. Empty files cannot be the only evidence. Discovery is bounded to 5,000 tree entries. Symlinks, submodules, traversing/control-character paths, binary content and known credential/key filenames are rejected. Only selected committed bodies are model evidence. The existing separate integrity check hashes tracked working files locally, including unselected files, and keeps only the baseline hashes.

Project chat receives at most 24,000 characters of explicitly labelled selected excerpts and the full path manifest; omitted context is identified. Specialists receive the complete bounded approved snapshot. Workspace and live Web searcher prompts receive no selected file bodies. Each new plan shows its exact source paths and selection version. Team-v2 snapshots store only those selected files; old legacy/team-v1 snapshots keep their original allowlist, evidence and acceptance behavior. An explicitly requested legacy report revision continues to use that report's original snapshot, rather than the current source set.

Source drafts stay separate across project switches. Delayed previews and save responses cannot replace the currently selected project's panel or erase newer drafts. Source settings and snapshots are local application data, never copied into the Interspace repository.

## Multiple projects

**Add project folder** registers another repository without clearing existing conversations or reviews. Choose its repository root, with a committed `README.md`. Project chat prefers committed `docs/PROJECT_CONTEXT.md` when present, otherwise README. New projects require an explicit source selection before model access. Existing reports retain their recorded source snapshots; registering a repository does not expose all its files. Re-adding the same canonical folder selects its existing record and refreshes its context choice.

The project picker switches among projects with separate tasks and a separate general conversation. Selecting a task restores its conversation, pending plan and report history. **Settings → Project details** saves a name, brief (1,200 characters), high/normal/low priority and next action locally, without a model call or source edits. **Task run history** restores a prior task run; **Artifact version** selects rounds within that run. Composer edits, unsubmitted New task forms and metadata drafts survive switching during the current app session. Created task records, the full goal explicitly saved by Create draft, and sent conversations are durable. Reopening a saved local task restores that full goal without sending it. Further unsent edits remain session-only. A successful task message consumes the saved draft in the same save as its conversation entry; rejected source consent keeps the saved draft. Late creation and settings replies cannot send a goal to a different owner, restore an old task selection or erase a newer draft.

In **Workspace advice**, the project overview shows all registered projects. Workspace Orchestrator receives only names, briefs, priorities, next actions, proposal availability and latest review status. It can suggest priorities; it does not automatically edit metadata or dispatch across projects. Raw sources, report bodies and project conversations are excluded from Workspace prompts. A task receives only its own conversation and selected prior report alongside approved project context. General project chat remains separate. User-entered briefs are intentionally available to Workspace summaries.

You can browse another project or report while a job runs. The active banner names the actual owner, and the worker saves results, failures and usage to that owner. Only one interaction runs at a time. Mutating actions carry explicit project IDs; stale project/run/artifact references fail before dispatch.

Existing state migrates automatically to version 3. Historical runs become imported tasks without rewriting their run/artifact identities or inventing task conversation; general conversation stays general. Exact imported approvals retain their original bindings and revocation lifecycle. Original inputs are kept once as `state.v1-backup.json` and/or `state.v2-backup.json` beside `state.json`. Migration does not revise or accept a saved report. Unknown future schema versions fail without overwriting the state.

## Task desk validation

Controlled browser journeys run with `node tests/run-ui.cjs` using installed Google Chrome in an isolated temporary profile. They use in-memory native bridge fixtures and actual public backend projections from disposable repositories. No live provider, personal app data or real source project is accessed. To verify the packaged UI, build the sole bundle, then run `INTERSPACE_UI=dist/Interspace.app/Contents/Resources/app/ui/index.html node tests/run-ui.cjs`. The packaged resource includes the original static scene; source-only file previews do not include its packaging copy. See `docs/task-desk-validation.md` and `docs/controlled-editing-validation.md` for actual runtime, signature, browser and appearance evidence and pending native/live acceptance.


## Fix & test (Python)

Choose **Fix & test (Python)** when creating a task; mode cannot change afterward. Save committed sources first. The proposed plan lists each Implementer's exact disjoint Python write paths, dependencies, source revision/selection and budgets. Existing targets must be selected committed files; new targets must be absent. This preset allows at most eight `.py` paths, including code and tests under `tests/`, 100,000 generated bytes per file and 200,000 total. No packages, shell commands, binaries, renames, deletions or arbitrary tools are supported.

1. **Generate candidate** approves the exact plan and call ceiling. It produces replacements and a unified diff in an app-owned copy. Source files remain untouched, and no generated tests run yet.
2. **Run candidate checks** approves that frozen candidate, artifact, fixed recipe and complete signed Apple Python runtime identity. It runs at most three processes: original code/original tests, original code/candidate tests, and candidate code/the same candidate tests. Each has a 30-second deadline and 100,000-byte combined output limit. This action also continues the remaining planned Tester, Reviewer and synthesis calls shown at the approval. The runtime uses read-only check trees, separate writable scratch, a clean environment, no network and no child programs; unsupported restrictions/runtime fail closed.
3. **Apply reviewed changes** is separately available only after the required test pattern (original pass, assertion-failing regression without errors, candidate pass), independent Reviewer acceptance and successful synthesis. It binds the exact project/task/run/plan/candidate/check/report artifact. It writes only the displayed replacements, leaves them uncommitted and invalidates other pending project plans. Commit in your project and refresh/save committed sources before further plans.

The test-approval pause survives restart and releases the active interaction slot. There are no retries, automatic repair, automatic resume or automatic application. Model calls retain their four-minute deadline and original allowance/ceiling. Repeated Testers reuse the same three captured check results. Passing tests do not establish semantic correctness or model accuracy.

Result shows the frozen diff, actual recorded check statuses/exit codes/test/failure/error counts and review conclusions. Process output, specialist findings, original/candidate citations, full approval identities and history remain inspectable. Original evidence always reads the original committed bytes, including after application and a fresh session. Failed or revision-needed runs preserve partial artifacts and require a new plan.

Application requires supported same-filesystem atomic exchange/exclusive creation. It retains displaced files, backups and a durable journal; it has no destructive fallback. A source conflict or unavailable primitive blocks application. Multi-file application is not a single filesystem transaction. Incomplete/conflicted application becomes **Recovery required** for inspection and never rewrites the project automatically on startup. This bounded preset does not certify general hostile-code containment; generated assertions and framework behavior still require review.
