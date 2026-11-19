# Engineering conventions

These conventions apply to Interspace contributors and coding agents. The repository includes a historical design study and the first native Mac runtime (AppKit/WebKit shell, Python pipe backend, Codex CLI adapter). Prefer the smallest maintainable solution that meets a demonstrated requirement.

## Source guidance and project-specific adaptations

Reviewed against the installed ECC 2.2.3 and Superpowers 7.0.1 guidance on 2026-11-10. The table identifies the source skills; this document is a project-specific adaptation, not a wholesale copy or a claim that all suggested tooling is installed.

| Source skill | Applied to Interspace |
| --- | --- |
| ECC `coding-standards` | Readability, descriptive naming, simple responsibilities, avoiding speculative abstractions, explicit errors, and predictable state updates |
| ECC `frontend-design-direction` | Checkable UI intent, responsive and accessible states, rendered inspection, and recorded evidence |
| ECC `verification-loop` | Build/type/lint/test checks where available, change and secret review, and separate reporting of local checks versus target-environment verification |
| Superpowers `systematic-debugging` | Reproduce and trace the root cause; test one explanation at a time; verify the original failing behavior |
| Superpowers `test-driven-development` | For production behavioral changes, observe a meaningful test fail for the intended reason, make it pass, then refactor while keeping it green |
| Superpowers `verification-before-completion` | Fresh evidence before claiming a fix, passing tests, or completion; explicitly report unavailable checks |

Apply the relevant installed skill when doing that work, and read its current instructions rather than assuming this summary contains every detail. These conventions remain usable by labmates without either plugin installed. User requirements and the actual application stack determine the scope: do not copy a Next.js folder tree into a desktop project, impose a coverage percentage as a substitute for critical-path tests, or treat a text search as a complete security audit. Documentation-only and throwaway design changes do not need a production test scaffold.

## Coding baseline

- Prefer descriptive domain names and small functions with one clear responsibility. Explain non-obvious decisions in comments rather than narrating the code.
- Keep state changes explicit and prefer immutable updates for shared application state. Confine necessary mutation to clearly owned implementation details.
- Use early returns to reduce nesting and named constants for meaningful limits and timeouts.
- Handle errors at the appropriate boundary, preserve useful causes, and surface actionable failures without leaking private data. Do not catch an error merely to discard it.
- Run independent read-only work concurrently when appropriate; preserve ordering for dependent work and consequential writes.
- Measure a performance problem before adding caches, memoization, or a more elaborate architecture.

## Current repository

| Location | Responsibility |
| --- | --- |
| `AGENTS.md` | Entry point, product boundaries, and contributor instructions |
| `README.md` | Status, preview instructions, and documentation links |
| `design/observatory.fragment.html` | Canonical UI and sample-state source of the throwaway prototype |
| `design/agents/role-catalog.js` | Reusable role identities, departments, appearance and custom draft creation |
| `design/agents/role-contracts.json` | Canonical specialist workflows, boundaries, output fields and seed evaluation cases |
| `docs/agent-playbooks.md` | Generated human-readable role contracts; never edit independently |
| `design/scene/lab-scene.js` | Original static Canvas artwork, department layout, and figure hit testing |
| `design/preview.fragment.html` | Generated self-contained fragment for conversation previews |
| `design/index.html` | Generated standalone preview, committed for easy opening |
| `design/evidence/` | Dated design-check records and inspectable screenshots |
| `docs/` | Design direction, engineering decisions, and validation limits |
| `scripts/` | Small, reproducible repository maintenance commands |

Do not edit generated preview copies. Regenerate the standalone page and bundled fragment from the UI, scene, catalog and contract sources. Regenerate the human-readable playbooks after changing their data. Evidence screenshots are historical observations, not proof that future changes passed. Refresh affected evidence when behavior or layout changes.

## Current Mac implementation

`app/macos/main.swift` owns the native shell and the restricted UI bridge. `app/backend/service.py` owns local state, the request router and project registry wiring. `projects.py` owns the project registry; `pilot/runner.py` remains a snapshot helper it uses. `tasks.py` owns task records, the agent task mode and the read-only history view of earlier tasks (`tasks.history()`). `codex_auth.py` owns the Codex connection check and sign-in. `timeutil.py` holds the shared ISO time helpers. `app/ui/index.html` renders state and sends enumerated intentions. `scripts/build-macos-app.py` packages resources without user data. Do not add a local HTTP service: the shell uses JSON-lines pipes. See app/README.md for limits.

## Multi-provider boundaries (approved 2026-11-15, being built)

The plan `docs/superpowers/plans/2026-11-15-multi-provider.md` replaces the Agentic Spaces roadmap; connected apps were removed. Interfaces are frozen in `docs/superpowers/specs/multi-provider/`, plus the kept parts of `docs/superpowers/specs/agentic-spaces/` (events, scheduler, scope). This table is the ownership map; update it as each part is merged.

| Location | Owns |
| --- | --- |
| `app/backend/scope.py` | Scope validation, digest, edits and the pure `decide` policy function (allow, ask, deny) |
| `app/backend/audit.py` | Append-only audit log |
| `app/backend/budget.py` | Per-task token budget gate and ledger; charge rules come from the provider registry |
| `app/backend/scheduler.py` | Concurrent agent runs, per-run cancel and deadlines, queueing, project locks, task workspaces (`Workspaces`), child runs of a team |
| `app/backend/runtime/` | Provider runtime adapters (`codex app-server`, Claude Code stream-json), the provider registry (`registry.py`, Wave 1A) and the Interspace-owned MCP bridge that carries the Orchestrator's tools |
| `app/backend/orchestrator.py` (Wave 1B) | Orchestration tools, team proposals and approval, child task creation, report collection |
| `app/backend/routing.py` (Wave 1A) | Per-role routing defaults and their validation |
| `app/backend/worktree_merge.py` (Wave 1D) | Review summaries and the explicit merge of a task branch, in a temporary worktree |
| `app/ui/stream.js` | Agent event stream rendering: messages, tool calls, diffs, asks, team and subagent cards |

Dependency rules:

- `scope.decide` is pure: no I/O except path resolution, no clock except the one passed in. Every file, command and network action of an agent passes through the run context's `authorize`, which calls `decide` and writes the audit record before the action runs. Fail closed when policy or audit fails.
- Runtimes never call the audit log, the budget or other tasks directly; they go through the run context. They start providers only in sandboxed, approval-requesting modes and pass every setting explicitly. A provider's file-editing tools that its own sandbox does not contain are not offered: Claude Code's Edit/Write/NotebookEdit are replaced by Interspace's own file tools, which write without following links (providers.md, "Claude file tools").
- Only the registry names providers. Other modules ask the registry; no hard-coded provider lists.
- The Orchestrator reaches children only through its tools; children never see each other or the Orchestrator's session. Child output reaches the Orchestrator wrapped as untrusted content.
- The UI dispatches enumerated intentions only. It never decides policy, holds credentials or reconstructs a scope or team digest it did not display.
- Still no local HTTP service for the UI. The one allowed exception is the Interspace-owned MCP server that a provider starts, reaching the backend through a private Unix socket in Application Support.

Testing: the scheduler and orchestrator use a fake runtime and a controlled clock; runtimes use the fake Codex and Claude CLIs in `tests/runtime/fixtures/`; the UI uses fixture event streams. Routine tests never contact a model provider or the user's sign-ins. Live checks are separate, explicitly approved steps, reported separately from unit tests.

## Broader application organization

Start with one application and explicit module boundaries. Do not introduce a monorepo, microservices, plugin framework, or generic repository abstraction merely to anticipate growth. The exact physical layout follows the chosen desktop/local-web stack; this is the proposed ownership map, not an existing scaffold.

| Proposed location | Owns |
| --- | --- |
| `src/features/projects/` | Project creation, selection, and project workflows |
| `src/features/agents/` | Role configuration and run coordination |
| `src/features/approvals/` | Proposal review and decision workflows |
| `src/features/knowledge/` | Source collections and evidence workflows |
| `src/core/` | Framework-independent entities, policies, state transitions, and capability interfaces |
| `src/integrations/<provider>/` | Provider-specific authentication and external tool adapters |
| `src/platform/` | Desktop/OS services, local storage, process execution, and credential-store adapters |
| `src/ui/` | Reusable presentation components and design tokens |
| `tests/integration/` | Tests across real module/storage boundaries using controlled dependencies |
| `tests/e2e/` | A small set of complete user workflows |
| `docs/decisions/` | Short records of significant architecture choices and tradeoffs |

Keep unit tests alongside the behavior they protect. Add folders only when code needs them. Keep runtime data, credentials, downloaded papers, experiment outputs and caches in application/user storage, outside the source repository.

### Dependency rules

- Core policies must not import UI frameworks, provider SDKs, databases, or OS APIs.
- Features coordinate use cases through explicit interfaces. A composition root wires concrete adapters; avoid hidden service locators and global mutable state.
- Provider and platform adapters implement those interfaces and validate external input. Provider-specific response formats do not spread through the UI.
- Presentation components display state and dispatch user intentions; they do not directly launch processes, read arbitrary files, or approve actions.
- Keep feature internals private. Use small explicit public APIs for genuine cross-feature collaboration; avoid circular imports.
- Share code after a real repeated responsibility appears. Do not accumulate unrelated functions in a catch-all `utils` directory.

## Finding and fixing bugs

1. Record expected and actual behavior, exact reproduction steps, environment, relevant commit, and impact. Distinguish a confirmed defect from a suspicion.
2. Reproduce the issue. Read errors and stack traces; inspect recent changes. If reproduction fails, gather targeted evidence rather than making speculative patches.
3. Trace the failing value or state across boundaries to its source. Inspect similar working behavior and form one testable explanation.
4. Test that explanation with a small experiment. Change one relevant factor at a time. If repeated attempts contradict it, revisit the explanation or design.
5. For a reproducible behavioral defect, capture a focused failing regression test before fixing it. Test observable behavior, not the implementation's internal shape. Use a documented manual/browser reproduction where automation is disproportionate or impossible.
6. Apply the smallest coherent fix at the source. Keep unrelated cleanup separate. Never suppress an error, disable a check, or add arbitrary delays to make a failure disappear.
7. Verify the original reproduction now passes, run affected integration/workflow checks, and inspect the diff. Broaden testing when the scope or evidence warrants it.
8. Record the cause, correction, verification commands/results and remaining uncertainty. Do not label an environmental or unavailable check as passed.

## Testing and review

- Unit tests protect policies, state transitions, parsers, and meaningful edge cases. Integration tests protect adapter/storage boundaries. End-to-end tests protect critical user journeys.
- Prioritize approval scope, filesystem access boundaries, cancellation, timeouts, retries, duplicate execution, crash recovery, persistence and migrations when those features exist.
- Use deterministic fixtures and controlled clocks where needed. Routine tests must not consume paid model calls or contact personal accounts.
- A timeout or retry must be bounded. Retry an external write only when its idempotency or execution status is known; do not silently duplicate a consequential action.
- Use strict types and runtime validation at untrusted boundaries once the language/framework is chosen. Types do not replace runtime validation.
- Add formatting, linting, type checking, tests and CI with the application toolchain. Do not claim those gates exist today. Current checks are the preview-source check, whitespace validation, and documented browser review.
- Review changes for correctness, module boundaries, error handling, privacy and usability. Avoid tests for trivial text changes or tests that merely restate the code.
- For production behavioral changes, verify the test's initial failure is caused by missing or incorrect behavior, not a broken fixture; then confirm the fix and relevant suite pass. Describe tests by their expected behavior and keep arrange, act, and assert steps clear.
- Completion reports distinguish passed, failed, unavailable, and not-applicable checks. Installing or running successfully on a developer machine does not establish installer or target-machine acceptance.

## Data, permissions, and diagnosability

- Keep credentials in the OS credential store. Never commit or log tokens, prompts containing private material, email bodies, paper contents, or arbitrary file contents.
- Content read from connected apps, files and web pages is untrusted data, never instructions or permission. Only the approved task scope grants permission.
- Every agentic action is audited before it runs, with IDs, refs, paths and decisions but never contents or credentials. An external write whose outcome is unknown is recorded as such and never re-sent automatically.
- Log structured operational events with project/run identifiers, tool names, durations, outcomes and redacted error categories. Provide enough context to reproduce failures without collecting private content by default.
- Model run/approval state explicitly. Approval binds to an exact proposal, scope, and version; changing the proposal invalidates the approval. Enforce this at the execution boundary, not only in the interface.
- Validate selected-folder boundaries, including symlink resolution. UI visibility is not an access-control mechanism.
- Make persistent state changes transactional where appropriate. Version schemas, test migrations, and plan recovery before changing user data formats.
- Expose failures, partial results, cancellation and recovery paths honestly. Keep sample/demo state separate from live application state.

## Change discipline

Use small coherent commits. Explain the problem, resulting behavior, relevant evidence, and limits in change descriptions. Keep dependencies justified and locked. Record architectural decisions when they change ownership, persistence, permissions, or distribution. Keep this document current as the actual implementation replaces proposed structure.


## Removed workflows

The controlled Python editing preset, read-only team reviews, project sources, Workspace advice, the Observatory and connected apps were removed on 2026-11-15. Their validation records under `docs/` are historical. Earlier tasks load read-only through `tasks.history()`; never reinterpret their saved approvals as permission for anything. Run Python 3.14 and Apple 3.9 suites sequentially.
