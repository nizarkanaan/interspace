# Task desk and repeated specialists

Status: implemented on `interspace/task-desk`, 2026-11-11, with the user amendment below. See [validation and acceptance limits](../../task-desk-validation.md).

User amendment: replace the proposed fixed six-specialist maximum with a per-task editable specialist allowance. Six is only the initial default, not a product ceiling. The Orchestrator proposes the smallest useful team within that allowance; Start approves the exact assignments and derived call limit. Account usage and local resources still constrain practical team size. Execution remains sequential; no automatic team expansion or unlimited recursive spawning is added.

## Intent and confirmed direction

The user finds the olive palette, text styling and navigation unappealing and cannot readily see where to work on tasks. They also questioned the one-Web-searcher limit. They selected the task-desk direction: neutral white/charcoal, a blue accent and larger clean text. This supersedes the native app's current olive visual treatment; it retains the optional static Observatory and light/dark accessibility requirements.

The outcome is one obvious workflow: **New task → describe the goal → inspect the plan → Start → follow activity → read the result.**

## Approaches

- Recolour the existing shell: cheapest, but keeps the split among project chat, work panels and review history that caused the navigation problem.
- Chat first: keeps the composer dominant, with task activity secondary. Offered to the user, who chose the task desk instead.
- Task desk: selected direction. Task creation and task history become primary; the conversation, plan, activity and result belong to a selected task. This requires a small task record and migration, rather than relabelling project-wide chat as task-specific history.

## Visual design

Visual thesis: a quiet working desk with clear text, neutral surfaces and a single blue action colour. Avoid a dashboard mosaic and stacked bordered panels.

- Light: near-white canvas, white work surface, charcoal text; blue for the primary action and selection. Dark: charcoal canvas and surfaces, near-white text, accessible lighter blue.
- Proposed typeface: Avenir Next with system sans-serif fallback, installed locally on the target Mac; no remote font request. Body and editable fields 15–16px, readable line spacing. Ordinary sentence-case labels replace the pervasive tiny uppercase/monospace labels. Monospace stays for code and source locators.
- Sidebar: Tasks, project list, optional Observatory; Settings/connection at the bottom. Project selection is the navigation context, without a second conversation-scope selector over every task.
- Task list: plain rows with goal, project and truthful status. A visible **New task** button is the primary action. Empty state gives the same action.
- Task detail: Back to tasks, goal, status and four views: Conversation, Plan, Activity, Result. Sources and limits remain available in the relevant view; they do not dominate the default screen. Settings contains project metadata and account controls.
- Motion is limited to direct feedback and short view transitions. No simulated agent movement, timers, fabricated progress or background animation. Honour reduced motion.
- Preserve accessible native controls, visible focus, clear errors and light/dark contrast. Narrow layouts stack navigation/detail content without losing actions. Inspect 320, 390, 760, 1024 and 1280px; the native window keeps its existing minimum size.

Content plan: task list for orientation; goal composer for creation; plan for scope and approval; task activity for execution; result for evidence and unresolved questions. Each view has one job.

## Task ownership and history (assistant proposal)

A task is a user goal with its own conversation, pending proposal and run history. A specialist assignment is a unit of work within that task; distinguish those labels in code and UI.

- **New task** opens a goal composer in an explicitly selected project. With no project, show the project chooser. Creating/saving a local draft does not call a provider. Sending its first message invokes planning as today.
- **Create draft** saves the full goal locally (up to the existing 6,000-character message limit), not just its shortened list title. It survives app restart without entering a model prompt. Sending the message consumes that saved draft only after source consent and durable message storage; ordinary newer unsaved edits remain scoped to their task.
- Only the active task's conversation, approved project sources and explicitly relevant previous result enter its project prompt. Another task's raw messages/results are not implicitly included. Workspace advice retains its existing metadata-only boundary.
- Plans, Start, source previews, report selection/acceptance and asynchronous responses carry task plus project identity. Switching task/project cannot attach a late reply, draft, approval or result to the new selection.
- Keep one active interaction globally. Viewing other tasks remains possible. The active banner identifies its true project/task owner. Stop targets that active interaction.
- Store task records and source snapshots in Application Support, never the source project. A versioned, backed-up application-state migration preserves old projects, project chat, pending plans, usage and every run/acceptance. Keep the original project conversation accessible as **Project conversation**; do not invent historical per-run chat attribution. Existing runs become task-history entries with preserved IDs and artifacts. An old pending proposal becomes a clearly identified imported task with its exact proposal unchanged.
- A pending legacy revision belongs to the imported task owning its referenced run; do not create a second task for that revision. Previous attempts within the same run remain in the same task. Preserve the pending revision's exact run/artifact/approval references.
- Relevant previous result means only the selected earlier run of that same task. This milestone has no cross-task result attachment; another task's result is not inferred to be relevant merely because it was selected elsewhere in the project.
- Existing approval digests stay valid only for their recorded scope. New task-bound proposals include task identity in the digest. A conversation request to change specialists replaces the proposal; it cannot silently alter an approved plan.
- Existing source-selection consent, source hash verification, report acceptance and legacy revision rules remain enforced. No loss or deletion of task history is part of this milestone.

## Repeated specialists (assistant proposal)

The current one-instance-per-role limit was a first-milestone implementation policy. It is not a provider limit. It is enforced in plan validation and the planner prompt; the UI also currently labels every instance “1”. Search evidence IDs additionally lack assignment identity, so simply removing the uniqueness check is unsafe.

Proposed bounded policy:

- Allow **one or more specialist assignments within the task's user-set allowance**, including repeated Web searchers, Researchers or Reviewers. Task IDs remain unique and stable; role IDs name templates, not instances. Each assignment has its own objective, expected output, dependencies, artifact and usage entry.
- The Orchestrator chooses the complete team before Start and should use the smallest useful team. The task composer/settings allow a positive whole-number allowance, initially six, which the user can raise. The plan displays actual assignment count and exact call ceiling. Changing the allowance invalidates an unstarted proposal; it cannot expand a running plan. Validate the allowance as a positive JavaScript-safe integer for exact UI/JSON representation, not silently clamped to six. Existing provider response/context size guards still apply.
- Example: two Web searchers with distinct public briefs → Researcher → Reviewer → synthesis. This is **six calls total**: one planning, four specialist, one synthesis; five calls after Start.
- Keep execution sequential for this milestone, including otherwise independent searches. Repeated instances do not imply simultaneous execution. Keep the four-minute stage deadline and no automatic retry or recursive delegation.
- Each Web searcher still receives only its disclosed public assignment, in a fresh isolated directory, with no private sources or dependency artifacts. Namespace new web evidence by run and assignment and source index. Preserve old evidence IDs as recorded. Bound evidence to ten sources per search assignment and a bounded total derived from the approved team; reject cross-assignment ownership or collisions.
- Researchers receive only approved sources and the declared ancestor artifacts/evidence. Multiple Researchers can work on distinct questions without sharing undeclared outputs.
- Every Reviewer must have all non-review assignments upstream. Reviewers need not be upstream of each other; they can provide independent assessments. A dependency on an earlier Reviewer is allowed if explicit and acyclic. A team containing only Reviewers is invalid.
- With multiple Reviewers, acceptance requires **all** verdicts to be accept. Any blocked verdict yields blocked; otherwise any revise yields needs_revision. Without a Reviewer, completion remains explicitly unreviewed and cannot use reviewed acceptance. Retain every Reviewer objection in the combined result; no last-reviewer-wins behaviour.
- Task/Observatory labels and artifact selectors distinguish repeated instances using role plus assignment name/ID, with stable numbering within that role. Preserve the same selection across views.
- Version the new plan policy explicitly. Existing one-per-role plans and saved records continue to validate under their original limits and review semantics; they do not inherit a larger allowance. No stale plan is upgraded or automatically started.

## Interaction states

- No projects: select/add a project before creating provider work.
- Sources unconfirmed/stale: the task composer shows an actionable Sources requirement; no call occurs.
- Draft: locally saved goal/conversation; no plan or running-work implication.
- Plan ready: team, dependencies, disclosed web briefs, revision/source paths and call ceiling are reviewable before Start.
- Working: actual reserved/completed jobs drive activity. Waiting assignments identify their dependencies.
- Needs revision/blocked/failed/cancelled/interrupted: show the cause and retained partial artifacts. Never rename failure as completion. Further work requires the existing explicit new-plan or legacy-revision path.
- Result: combined report first, then specialist output, citations and unresolved questions. Reviewed acceptance binds the exact result as today.

## Scope and verification

The initial visual proposal used labelled synthetic tasks, public example briefs and local-only interactions. Production implementation subsequently completed under this accepted scope; its tests use disposable data and controlled provider responses. The proposal itself does not call a model or change application state.

Implementation stays in the existing Mac shell, Python backend and JavaScript UI; no new framework, HTTP service, hosted account or prototype promotion. Preserve role artwork and static departments. Keep changes on an `interspace/` branch.

Use test-first regression coverage for migration, task/project isolation and stale actions, repeated roles, evidence identity/ownership, multiple-reviewer verdict aggregation, exact call reservations, cancellation and source integrity. Use controlled providers and disposable projects; no real provider job, Sample Project write, simulation or experiment is authorized by this design discussion. Browser-test the task journey, error/empty/partial states, responsive sizes and both appearances. Build/sign the native bundle. Native interaction remains unavailable while the Mac is locked.

Routine implementation decisions left to the builder: exact file decomposition, backed-up state-version encoding, spacing, icon choice and accessible token adjustments. The user accepted the visual direction, task ownership and repeated-specialist workflow. The fixed six-assignment ceiling is superseded by their editable-allowance amendment. The repeated-reviewer policy is included in the accepted design.

## Design review evidence

A read-only builder check identified two material migration/context questions. The design now explicitly keeps a pending legacy revision with its existing run's imported task and limits prior-result context to that same task. No cross-task attachment workflow is included.

The interactive conversation mockup is labelled sample data and does not connect to application state or a provider. Its task creation, plan/activity/stop controls, result selection and example evidence expansion were inspected in an isolated headless browser. Five screens at 320, 390, 760, 1024 and 1280px in both light and dark appearance passed horizontal-fit checks (50 screen/appearance/width combinations), with no page errors. Light desktop and dark narrow rendering were visually inspected. These are mockup checks, not production workflow or native-window verification. Temporary browser assets and screenshots remain ignored in `workspace-data/`; no additional `.app` bundle was created.
