# Token Budgets Implementation Plan

**Goal:** Per-task token budgets, checked before every model call, as specified in `docs/superpowers/specs/2026-11-11-token-budgets-design.md` (approved by the user on 2026-11-11).

**Architecture:** A new `app/backend/budget.py` owns the arithmetic and the ledger: estimates, charges, reservations, settlement and recovery. Its only collaborator is the state dict passed in. Every model call already goes through `Application.call` or `team.invoke`. Each gets one gate: reserve before the provider launches, settle in `finally`. A refusal raises `budget.Exhausted` (a `ValueError`), which `launch` turns into the terminal stage `budget_exhausted`.

**Stack:** Existing Python 3.9+, plain JavaScript and the Swift shell. No new dependencies.

## Constraints

- Branch `interspace/token-budgets`. No merge or push.
- Tokens only; no money anywhere.
- One budget per task. Project conversation and Workspace advice are never gated.
- Charge rule: `input_tokens + output_tokens`. First confirm from Codex's usage definition whether `reasoning_output_tokens` is already included in `output_tokens`, so no token is counted twice. Record the finding in `budget.py`.
- Usage ledger entries are durable before launch and are never deleted. A reservation left over after a restart becomes **estimated**.
- Existing call ceilings, deadlines, approvals and no-retry rules are unchanged.
- Routine tests use fake providers and disposable repositories only.

## Task 1: Budget policy and ledger

**Files:** create `app/backend/budget.py` and `tests/test_budget.py`.

**Interfaces:**
- `validate(value)`: a positive safe integer, or `None` for legacy tasks.
- `charge(usage)`
- `estimate(prompt, role)`: named constants `CHARS_PER_TOKEN`, `PROVIDER_OVERHEAD_TOKENS`, and per-role `OUTPUT_RESERVE`, all biased to over-estimate.
- `ledger(state, task_id)`: returns `{used, reserved, estimated, entries}`. It sums `charge` for reported and estimated entries plus `estimate` for reserved ones. Legacy entries without `charge` are charged from their `tokens` when present.
- `reserve(state, task, *, role, prompt, project_id, run_id=None, assignment_id=None)`: raises `Exhausted` if `used + reserved + estimate > budget`; returns an entry ID. With a `None` budget it still records the entry, but never refuses.
- `settle(state, entry_id, usage, outcome)`
- `recover(state)`
- `project(state, task_id)`: projects the remaining budget and the estimate for a list of planned calls.

Steps:
- [x] Write failing tests:
  - the exact-fit boundary and refusal by one token;
  - unknown usage charged as the estimate;
  - an overshoot recorded with the actual count;
  - recovery of reserved entries to estimated;
  - `None` budgets never refusing;
  - malformed budgets rejected;
  - the charge rule.
- [x] Implement until green.

## Task 2: Gates, terminal stage and approval binding

**Files:** modify `service.py`, `team.py`, `orchestration.py`, `changes.py`, `change_team.py` and `tasks.py`. Extend the workflow tests: `test_task_workflow.py`, `test_team.py`, `test_change_workflow.py` and `test_tasks.py`.

Steps:
- [x] Write failing tests:
  - a refused call never reaches the provider and adds no job reservation;
  - each gate checks the right task;
  - `budget_exhausted` ends team runs and change runs (at generation, after check approval, and at synthesis), with artifacts preserved;
  - a task chat refusal keeps the user message and records the error;
  - legacy reviews fail with the budget message;
  - a restart while a reservation is held turns it into an estimated charge;
  - a budget edit clears unstarted plans;
  - plan digests and check approvals bind `token_budget`, so a stale budget reference is rejected;
  - legacy budget-less tasks and their pending plans remain valid;
  - Project conversation and Workspace advice are never refused.
- [x] `Application.call`: when an active task exists, reserve before `provider.run` and settle in `finally`.
- [x] `team.invoke`: reserve after the existing ceiling check, before the job reservation is saved. Replace its post-call usage append with `settle`, keeping the existing entry fields.
- [x] `launch`: on `budget.Exhausted`, set stage and task status to `budget_exhausted`. Add `budget_exhausted` to `orchestration.TERMINAL`, which `changes.TERMINAL` inherits. `interrupt` marks unfinished assignments as failed.
- [x] `Application.__init__`: call `budget.recover`.
- [x] Bind the budget into approvals:
  - `orchestration.make_plan` (v2) and `changes.make_plan` add `limits.token_budget` only when the task has a budget, so legacy digests are unchanged;
  - `tasks.validate_plan_owner` requires plan and task budgets to match;
  - `approve_checks` binds `token_budget` in `test_approval` and in the projected `approve_checks` reference.
- [x] `create_task` and `update_task` accept `token_budget`, with a default of 250,000 for new tasks. An edit that changes the budget clears the pending plan.
- [x] Public projection per task: `token_budget`, the ledger totals, and a `budget_projection` for the pending plan or paused check approval.
- [x] Run the focused suites, then the full backend suite.

## Task 3: State v4 migration

**Files:** modify `projects.py` and `tasks.py`; extend `test_projects.py`.

- [x] Write failing tests:
  - v3 migrates to v4 with `state.v3-backup.json` written exactly once;
  - existing tasks get `token_budget: null` and their usage is preserved;
  - unknown future versions fail without writing;
  - a malformed budget isolates only its task.
- [x] Implement. `tasks.validate` accepts `None` or a valid budget.

## Task 4: UI, docs and verification

**Files:** modify `app/ui/index.html`, `app.js`, `team.js`, `changes.js` and `desk.css`; extend the browser fixtures and journeys (`tests/task-desk-ui.mjs`, `tests/changes-ui.mjs`, `tests/task_saved_state_fixture.py`, `tests/change_saved_state_fixture.py`); update `app/README.md`, `README.md` and `AGENTS.md`; create `docs/token-budgets-validation.md`.

- [x] Write a failing browser journey covering:
  - the New task **Token budget** field and its default;
  - the header `Tokens used / budget`, with "estimated" marked;
  - the Plan and check projection, and the warning when it doesn't fit;
  - the exhausted state and its next-step message;
  - per-call charge labels (reported, estimated, reserved) and overshoot;
  - "No budget set" on legacy tasks;
  - a budget edit clearing the plan;
  - no money text anywhere;
  - light/dark appearance at widths 320, 390, 760, 1024 and 1280.
- [x] Implement. UI write intentions keep using backend-projected references unchanged.
- [x] Verify:
  - full backend suites on Python 3.14 and on signed Apple 3.9 with `INTERSPACE_REQUIRE_OS_CHECKS=1`, run one after the other;
  - source and packaged browser suites;
  - syntax and `git diff --check`;
  - rebuild of the sole bundle, signature check and byte-for-byte resource match.
- [x] Write the validation document with actual results. Commit.

## Closeout

- [x] One independent whole-feature review. Fix Critical and Important findings test-first.
- [ ] Live check, only with the user's exact approval at the time: a small task with a deliberately tight budget, showing a call refused before launch and the exhausted state in the native app.

Execution: sequential tasks, each committed when its tests pass.
