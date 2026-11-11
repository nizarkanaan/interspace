# Dynamic Orchestration Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Project chat proposes an inspectable, content-bound specialist graph and executes it with bounded usage and evidence-backed combined results.

**Architecture:** `orchestration.py` owns plan/artifact validation and the additive team run format; `team.py` coordinates persisted jobs through the existing Application/provider interfaces. The existing pilot remains the snapshot helper and legacy workflow. `team.js` renders new plans, tasks and results alongside existing legacy UI.

**Tech Stack:** Python 3.9+, vanilla JavaScript, AppKit/WKWebView, unittest, existing controlled Playwright bridge.

**Spec:** `docs/superpowers/specs/2026-11-11-dynamic-orchestration-design.md` (approved 2026-11-11).

## Global Constraints

Sample Project and all registered sources remain read-only; committed allowlisted snapshots only. One global interaction. One to three assignments, unique executable roles, complete plan before Start. Four-minute stage deadlines, no retries; one synthesis after specialists. At most ten live CLI jobs on public/disposable inputs. No remote push or merge of this branch. Preserve legacy state and report actions. No new dependencies, service, Notion or Firecrawl.

## Review Focus

- A returned plan or source body attempts to expand capabilities: backend owns capabilities and rejects extra fields (task 1).
- A Reviewer misses an independent assignment: require all non-review tasks in its ancestry (task 1).
- A stale Start races project switching or proposal edits: require exact identity and full digest before dispatch (task 3).
- A failed search or synthesis still consumed usage: persist a reservation and unknown consumption, keep partial artifacts (tasks 2–3).
- Legacy and new run histories coexist across restart: discriminate formats, reject unsupported versions, preserve old actions (tasks 1, 3–4).

### Task 1: Plans, evidence and additive team records

**Files:** create `app/backend/orchestration.py`, `tests/test_orchestration.py`.
**Interfaces:** `validate_tasks(tasks)->list`; `plan_digest(plan)->str`; `make_plan(project, revision, goal, tasks)->dict`; `prepare(project, plan, storage)->Path`; `artifact_id(record)->str`; `validate_artifact(record, task, result, observed_urls=())->dict`; `accept(run, reference)->bool`; `interrupt(record, stage, detail)->None`.
- [x] Write policy tests: graph/role/length limits, full review coverage, web jobs cannot depend on private artifacts, exact digest, local/web citation validation and reviewed acceptance.
- [x] Run `python3 -m unittest discover -s tests -p test_orchestration.py -v`; observe missing behavior.
- [x] Implement strict runtime validators, immutable capability mapping, schemas, source registry, versioned team record and acceptance. Reuse runner snapshot/integrity checks without legacy transitions.
- [x] Run focused tests and full Python suite; expect all pass. Commit coherent policy module.

### Task 2: Search capability and provenance

**Files:** modify `app/backend/provider.py`; create `tests/test_search_provider.py`.
**Interfaces:** keep `run(prompt,schema,cwd,cancel)` unchanged for text-only jobs; add `search(prompt,schema,cwd,cancel,on_event)->(result,usage)` for isolated web jobs. `ProviderError` may carry validated usage from completed turns, otherwise unknown.
- [x] Write fake-process tests: only search accepts search events, forbidden tools still terminate, web config is live only for search, observed provenance is bounded and forwarded, malformed/unsupported events fail closed, failures preserve known usage.
- [x] Run focused tests and observe failure; implement role-scoped search while preserving text-only adapter and cleanup. No live jobs in routine tests.
- [x] Run `python3 -m unittest discover -s tests -p 'test*provider.py' -v` and existing ProviderTests; expect all pass. Commit adapter.

### Task 3: Application routing and durable dispatch

**Files:** create `app/backend/team.py`, `tests/test_team.py`; modify `app/backend/service.py`, `app/macos/main.swift`.
**Interfaces:** planner supports `propose_plan` and `tasks`; `team.execute(app,project,plan)`; new bridge `start_plan` requires project_id/plan_id/plan_digest; existing accept_report discriminates run format. `Application.call` remains legacy-compatible; team jobs use durable per-job reservation and explicit owner/run/task records.
- [ ] Write failing integration tests for dynamic plan/Start/synthesis, direct answers, invalid model plans, full dependency artifacts, public-only search input, proposal digest mutation, duplicate/cross-project starts, failure/cancel/restart, call ceiling and legacy action rejection.
- [ ] Implement validated proposal creation and explicit dispatch. Persist reservations before provider invocation, unknown usage on failed jobs, events/partial results on failures, reviewer verdict dominance, source verification, and new run history/acceptance. Keep legacy proposal and revision compatibility.
- [ ] Run `python3 -m unittest discover -s tests -v`; expect all pass. Commit integrated backend and native bridge.

### Task 4: Inspectable plan, activity and combined result

**Files:** create `app/ui/team.js`, `tests/team-ui.mjs`; modify `app/ui/app.js`, `app/ui/index.html`.
**Interfaces:** `interspaceTeam` exposes `isTeam`, `renderPlan`, `items`, `renderResults` with passed DOM helpers/request/source callbacks; legacy UI branches on run format. New tasks use shared fixed department artwork.
- [ ] Write controlled browser check for assignments, public brief, dependency labels, exact Start references, waiting/running/partial states, source links, combined/individual results, review acceptance and switching legacy/team runs; observe failure before UI changes.
- [ ] Implement within existing olive light/dark layout, text-only model rendering, accessible buttons and safe links. Preserve selected task across Tasks/Observatory.
- [ ] Run new and existing controlled browser checks; inspect light/dark at 320, 390, 760, 1024, 1280px; expect no page errors or horizontal overflow. Commit UI.

### Task 5: Live compatibility, documentation and final verification

**Files:** update `app/README.md`, `docs/engineering.md`; create `docs/dynamic-orchestration-validation.md`; keep live data/scripts under ignored `workspace-data/`.
- [ ] Run at most ten public/disposable CLI jobs across direct answer (1), local review (4), web/research/review (5), each four minutes/no retry; reserve job count before dispatch. Confirm actual web event provenance or fail closed and report incompatibility. Record actual outcomes, not accuracy claims.
- [ ] Run full suites on both `python3` and `/usr/bin/python3`, generated preview/role checks and diff review. Build native app, inspect isolated team fixture, verify signature.
- [ ] Request fresh whole-branch review, address important findings test-first, rerun affected/full suites. Document limitations and live usage; commit. Keep branch for user acceptance.
