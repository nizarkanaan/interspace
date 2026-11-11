# Bounded revision loop Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for native execution and one final independent review.

**Goal:** Complete request → research → review → revise → accept inside the existing Mac app.
**Architecture:** Reuse the committed run snapshot and automatic Codex jobs. Preserve prior results as immutable attempt records; tag events by round. Gate revision and acceptance on current run ID, artifact digest, source path/revision and source integrity. One extra two-stage revision round per run; no recursive loops or automatic retry. User acceptance records only acceptance of a report.
**Tech Stack:** Existing Python backend/runner, Swift local bridge and native HTML UI.
**Spec:** docs/orchestrator-design.md and the user's authorization to implement the bounded revision loop.

## Global Constraints

- Work on feature/readonly-pilot; main remains unmerged.
- Sample Project is committed snapshot input only; no edits, simulations or experiments.
- One additional revision round, two sequential jobs, existing four-minute stage deadlines, no retries.
- Preserve old artifacts and feedback across failure, cancellation and app restart.
- No new provider/authentication path; jobs remain ephemeral and use the signed-in Codex account.

## Review Focus

- Double clicks or stale artifact IDs must not dispatch or accept different content.
- Revision allowance survives restart and failed/cancelled attempts.
- Reviewer feedback and the previous report reach the new Researcher explicitly.
- Acceptance is possible only after Reviewer acceptance and never approves experiment execution.
- Existing runs without round metadata remain readable; source protection stays enforced.

### Task 1: State transitions and workflow

Files: pilot/runner.py, app/backend/service.py, tests/test_revision.py.
Interfaces: artifact_id(record) -> str; handle revise_run/accept_report({run_id,artifact_id}); chat proposes revision-bound pending plans.
- [x] Write failing tests for revision, feedback transfer, preserved attempts, round ceiling, failure/cancel, stale artifacts/source, acceptance/idempotence and chat routing.
- [x] Add round-aware events/start gates and guarded revision/acceptance; share stage execution without changing the provider adapter.
- [x] Run full Python suite and existing generated-source checks.

### Task 2: App interaction and delivery

Files: app/ui/index.html, app/macos/main.swift, app/README.md, docs/revision-validation.md.
- [x] Show revision allowance, explicit revision/accept actions, prior attempt comparison and round-labelled history; bind requests to artifact digest.
- [x] Test native UI states with synthetic bridge; rebuild, inspect real existing revision workflow if available, verify source and post-launch signature.
- [x] Independent review, scoped fixes and final checks; commit/push branch only and refresh app archive.

## Execution record

- Implemented round-aware state, revision archive, content/source gates, explicit supplemental-instruction transfer and report-only acceptance.
- Full Python 3.14 and 3.9 suites pass 33 tests; synthetic UI bridge checks pass at 320–1280px. No live revision/model jobs started in this update.
- Independent review identified dropped supplemental revision constraints; added failing regression, passed after fix. Additional coverage checks active-revision restart and source change before acceptance.
- Native app rebuild preserves the existing source-protection and signed-resource behavior. Main remains unmerged.
