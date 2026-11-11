# Bounded dynamic orchestration

Date: 2026-11-11
Status: approved by the user on 2026-11-11, including the ten-job public-data live verification ceiling.

## Intent and scope

A person describes an outcome in a project's chat. Interspace proposes the smallest useful team from Web searcher, Researcher and Reviewer, with assignments, dependencies, expected outputs and a visible usage allowance. The person starts that exact plan, watches recorded work in Tasks or the static Observatory, and receives a combined result with citations and unresolved questions. Sample Project and all registered source projects remain read-only.

This extends the native app, Python pipe backend and vanilla JavaScript UI. It does not promote the throwaway design prototype, enable other catalog roles, execute experiments, edit source repositories, add external writes or create a hosted service. Each installation retains its own provider authentication and data.

## Approaches

1. **Bounded plan chosen before Start — selected by the user.** One validated dependency graph; execution cannot change assignments or add workers. It makes the team and allowance inspectable and preserves exact approval.
2. Adaptive proposals during execution — deferred. It could respond to discoveries but needs additional authorization, budget and reconciliation interactions.
3. Fixed templates with an optional search stage — rejected as the milestone design. It would preserve the current fixed workflow rather than let the Orchestrator choose specialists and assignments.

## Interaction

Project chat may answer directly with no specialists or propose a new plan. Workspace chat remains metadata-only and cannot dispatch. The plan card lists each specialist, objective, dependencies, expected output, capabilities, committed source revision and usage ceiling. A Web searcher assignment additionally displays the exact public brief supplied to its network-enabled job. Raw project files, reports and private conversation history are never supplied to that job. The user can ask for changes in chat; the revised proposal gets a new identity and invalidates the previous Start action. No separate plan editor is needed.

Start validates the canonical project path, project ID, committed revision, full plan content digest and plan ID at the backend. It consumes the proposal before launch. Duplicate or stale actions fail without another worker. The native bridge sends explicit project and plan identity; it grants no additional access itself.

Tasks and Observatory render the same persisted assignments and events, including waiting for dependencies, queued, working, done, failed, cancelled and blocked. Department figures stay fixed. A completed artifact is visibly different from an actively running model; no fake animation or inferred work. Selecting an assignment opens its objective, dependencies, output or failure. Project switches preserve the actual active owner.

The final panel defaults to Combined result, with specialist artifacts, evidence and events separately inspectable. It distinguishes facts, interpretations, proposals and unanswered questions. Reviewer verdict and user acceptance remain separate. A result without independent review is labelled unreviewed and cannot use the existing reviewed-report acceptance action. Failed or cancelled runs show useful saved partial artifacts and never claim completion.

## Plan contract and execution

A new app-owned orchestration module validates and executes new plans; the historical pilot runner remains the committed-source snapshot/integrity helper and the legacy two-stage workflow implementation. Do not force arbitrary task graphs through its researcher/reviewer stage machine.

An assignment contains a stable task ID, one executable role ID/version, a nonempty bounded objective, expected output and an explicit list of dependency task IDs. The backend derives capabilities and output schemas from its allowlist; model text cannot grant permissions. For this first milestone there are one to three assignments, at most one per executable role. IDs are unique, dependencies exist, self-dependencies/cycles are rejected, and every assignment must contribute to the requested outcome. Dispatch is sequential in a deterministic topological order, even for independent tasks. One global interaction remains the workspace ceiling.

The Orchestrator receives role contracts and the current project scope and produces the plan as structured output. The runtime rejects unsupported roles, malformed fields, oversize payloads, invalid graphs and impossible limits before showing a startable proposal. Specialists cannot dispatch further work. Each specialist receives only its explicit assignment, permitted committed snapshot input, and validated dependency artifacts. A Reviewer checks all upstream artifacts and supplies accept/revise/blocked with reasons. When present, the Reviewer must be downstream of every other assignment; reject a graph that leaves any specialist work outside its review. It receives the complete transitive dependency artifacts, including original Web searcher evidence when a Researcher stands between them. Validation requires at least one dependency for a Reviewer. Review is optional when the goal does not warrant it. No automatic revision loop is added.

After successful specialist execution, one text-only Orchestrator synthesis job receives the validated artifacts and creates the combined result. Every substantive finding refers to existing evidence IDs; synthesis cannot invent sources or remove a Reviewer's unresolved objections. Overall status is needs_revision or blocked when the Reviewer returns that verdict, regardless of fluent synthesis text. Without Reviewer, successful synthesis is completed_unreviewed. A synthesis failure preserves all specialist artifacts. No completed status is assigned before required work, evidence validation and source integrity checks finish. Source drift is surfaced as an integrity failure and prevents acceptance.

## Provider and web search

Reuse the existing signed-in Codex CLI adapter; do not introduce an API key or assume that a subscription includes third-party API credits. Keep ephemeral jobs, read-only sandbox, never-approve policy, disabled shell and CLI multi-agent features, and ignored user-configured MCP integrations. Text-only planner, Researcher, Reviewer and synthesis jobs continue to reject tool events.

Only the Web searcher job enables hosted live web search. It receives its visible public brief and no snapshot, full user goal, conversation, project path or other artifacts. Its provider workspace is empty application-owned storage, not a registered repository. The adapter accepts recorded web_search events for this capability and continues to reject commands, file changes, MCP and collaboration activity. Search remains disabled for every other role. An unsupported/failed search fails visibly; never substitute model memory and label it fresh research.

Persist observed web-search activity and validated web evidence with URL, title, retrieval time and a bounded supporting excerpt. Accept only public http/https URLs with no embedded credentials or local/loopback/private literal hosts, and require returned source URLs to be present in the observed search events before treating them as retrieved evidence. Confirm the installed CLI event format against a minimal live smoke check during implementation; if provenance cannot be established, fail the search task rather than weakening the check. URL provenance proves retrieval, not semantic support. Reviewer can assess supplied snippets, but does not independently browse or establish that a full paper was read. This limit is visible.

The CLI's hosted search is separate from local-command network restrictions. Prompt constraints and event rejection supplement the official CLI protections; Interspace does not claim it is containment for a malicious provider. No arbitrary URL fetching, browser automation, Notion or Firecrawl integration is added.

Official documentation checked during design: [Codex web search](https://learn.chatgpt.com/docs/web-search), [non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode). Local CLI reports 0.167.0-alpha.3.2; exec help confirms --ignore-user-config, --ephemeral, --json, --output-schema and read-only mode. Hosted search availability and event contents still require actual validation.

## Evidence and storage

Keep the registry at v2 with an additive, explicitly versioned new run format. Persist the exact approved plan, project ID, snapshot revision, task records, dispatch reservations, validated artifacts, source registry, events and terminal outcome under Application Support. New fields cannot reinterpret legacy run records. Preserve all legacy conversations, pending review/revision plans, histories, revision allowance and content-bound acceptance behavior. New dynamic runs use their own renderer and actions; they never enter the legacy revision path. An explicit new plan is required after revise/blocked for new runs.

Committed evidence remains constrained by pilot/runner.py's allowlist and SHA-256 checks. Local citations retain source path and exact LF line ranges. Web evidence uses stable run-local IDs referencing observed URLs and excerpts. Citation validation rejects unknown IDs, invalid ranges, cross-run references and malformed web sources. A combined result preserves specialist provenance. Model claims without supporting evidence are unresolved questions, not verified findings. Do not copy downloaded full papers or private user material into Git.

Run history identifies the format and restores the appropriate view. Acceptance for a new run requires Reviewer accept, successful synthesis, unchanged sources and an exact content digest covering plan, evidence, specialist results and synthesis. It authorizes that report only. Acceptance is idempotent and rejects changed content.

## Usage, failure and restart

The proposal shows one already-used planning call and a hard ceiling of one call per proposed specialist plus one final synthesis call: at most five calls including planning, or four after Start. Each call has a four-minute deadline, no retries and bounded provider output. A three-specialist run therefore permits at most sixteen minutes of post-Start model stages. Token usage is recorded when returned; unknown usage stays unknown. The limit is model invocations and elapsed stage time, not tokens, dollars, hosted-search actions or remaining subscription allowance. Do not advertise a hard spend or search-count cap that the CLI cannot enforce.

Reserve each job durably before launching it; never repeat a reserved job automatically after timeout, cancellation or restart. Save known usage and mark missing consumption unknown for failed jobs. Stop prevents future jobs, terminates the owned provider process group and leaves completed artifacts intact. Failure blocks dependent assignments and stops further dispatch and synthesis; the UI displays saved partial work without another model call. On restart, any nonterminal new run becomes interrupted, outstanding assignments become cancelled/blocked as appropriate, and no job resumes automatically. All writes and failures remain bound to the captured project/run owner regardless of the browsed project.

## Verification and release sequence

1. Finish current multi-project verification and local integration; preserve the feature branch. No remote push is implied.
2. Create codex/dynamic-orchestration from the integrated main branch for the design. Begin product implementation after design approval; keep focused implementation commits.
3. Test-first validation of plan graph/role/size limits, content-bound Start, duplicate dispatch, durable call reservations, project-switch ownership, stale actions, dependency failure, cancellation, interrupted recovery, citations/provenance, unknown usage and legacy compatibility. Routine tests use disposable repositories and fake providers, never paid calls.
4. Add controlled browser checks for inspectable plans, actual persisted task statuses in both views, public search brief, combined output, partial failures and project switching. Inspect light/dark and 320–1280px fit. Build and inspect the native app using isolated data.
5. Run a minimal official-provider smoke evaluation on public/disposable inputs: one direct answer, one local review plan and one search/research/review plan. Maximum ten CLI jobs in total (1 + 4 + 5), four minutes per job, no retry. This validates routing and web event compatibility, not general specialist accuracy. No Sample Project prompts or fresh research experiments in this evaluation. Report failures and actual usage honestly. Other live evaluation needs a separate scope.
6. Full Python suite on both supported local interpreters; generated preview/role checks; diff review, native build and signature verification. Keep the new branch unmerged for user acceptance.

## Builder decisions and approval

The user selected the pre-Start complete team. Sequential execution, one instance per role, a fixed final synthesis job, optional independent review with explicit unreviewed status, live search using only its disclosed public brief, no automatic retries/revision for new-format runs, and the ten-job public smoke budget are assistant proposals. Implementation can settle file names, helper boundaries and visual spacing within existing conventions. Changes to source access, authentication, execution scope or these resource limits require a revised design.

Builder review resolved two gaps: reviewed acceptance now requires the Reviewer to cover all other assignments, and the public smoke ceiling is corrected to ten jobs because the local review includes a synthesis call. Both details are included in the approved scope.
