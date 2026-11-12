# Per-task token budgets validation

Date: 2026-11-11. Branch `interspace/token-budgets`, stacked on `interspace/controlled-editing`. Design: `docs/superpowers/specs/2026-11-11-token-budgets-design.md` (approved 2026-11-11). Plan: `docs/superpowers/plans/2026-11-11-token-budgets.md`.

## Delivered

- **`app/backend/budget.py`**: validation, charge rule, estimates, the durable ledger (reported, estimated and reserved entries), reserve, settle, recover, and the plan projection.
- **Charge rule:** `input_tokens + output_tokens`. This was confirmed against Codex's `TokenUsage` in `codex-rs/protocol/src/protocol.rs`: `non_cached_input = input − cached`, and the blended total is non-cached input plus `output_tokens`, with no separate reasoning term. So cached input is inside input and reasoning is inside output.
- **Gates:** `Application.call` covers task chat, planning and legacy reviews; `team.invoke` covers team and change runs. Both reserve before launch, and `team.invoke` reserves before the job reservation is saved. Both settle in `finally`. Project conversation and Workspace advice are not gated.
- **Stops:** a refusal raises `budget.Exhausted`. `launch` records the terminal stage `budget_exhausted` for team and change runs, and `failed` for legacy reviews. Completed artifacts, the candidate and check results are kept. Start, Generate and Run checks are blocked outright only when even the smallest next call cannot fit.
- **Binding:** the budget is bound into v2 team plans and change plans (`limits.token_budget`, only when set, so digests of budget-less plans are unchanged) and into check approvals (`test_approval.token_budget`, plus the projected `approve_checks` reference). Editing the budget clears unstarted plans.
- **Restart:** a reservation held at shutdown becomes an estimated charge with outcome `interrupted`.
- **State v4:** existing tasks get `token_budget: null`, with a one-time `state.v3-backup.json`. A malformed budget isolates only its own task.
- **UI:**
  - New task **Token budget** field, default 250,000;
  - task header `Tokens used / budget`, with estimated, reserved, uncounted and overshoot details;
  - Plan tab budget editor and projection, with a warning when a plan likely won't fit;
  - check-approval projection;
  - **Budget exhausted** stage text and next step;
  - per-call charge labels in Usage;
  - **No budget set** for older tasks;
  - no money text anywhere.

## Estimates

The constants are named in `budget.py`: 3 characters per token, a 12,000-token provider overhead, and output reserves of 4,000 tokens (8,000 for the Implementer). They are biased to over-estimate. They were chosen from the recorded live calls, which reported 14,193–21,719 input tokens, not from a fitted calibration. The fake-provider fixtures return incomplete counts, so routine tests exercise the estimated-charge path heavily.

## Test-first evidence

- **`tests/test_budget.py`:** failed on the missing module first. Three later failures were mistakes in the tests themselves (number formatting, a missing budget argument and an over-loose fixture budget), corrected without changing behaviour.
- **`tests/test_budget_workflow.py`:** 12 tests, 11 failing before the gates existed. The twelfth, Project conversation and Workspace advice never refused, failed because the fake provider proposed a plan in Workspace chat; it was fixed in the fixture.
- **Migration tests in `tests/test_projects.py`:** failed before the migration existed.
- **First full-suite run:** 18 regressions surfaced and were fixed.
  - Existing check-approval helpers lacked `token_budget`; the new binding correctly refused them. The helpers now include it, and the missing-key test also covers `token_budget`.
  - A public pending plan had changed shape; the projection moved to a top-level `plan_budget`.
  - The `team.invoke` fallback had dropped task attribution for a task outside `project['tasks']`; the original fallback was restored.
- **`tests/budget-ui.mjs`:** run against the pre-change committed UI, it failed at the first budget assertion (`#task-tokens` missing). It uses actual backend public states from `tests/budget_saved_state_fixture.py`.

## Executed checks

| Check | Actual result |
| --- | --- |
| Full Python 3.14.6 suite, `INTERSPACE_REQUIRE_OS_CHECKS=1` | 240 tests, exit 0, zero skips, failures or tracebacks. `/private/tmp/interspace-budgets-backend-python314.log` |
| Full signed Apple Python 3.9.6 suite, run afterwards | 240 tests, exit 0, zero skips, failures or tracebacks. `/private/tmp/interspace-budgets-backend-apple39.log` |
| Source browser suites (6) | All passed: task desk (80 surfaces), projects, sources, teams, changes (60 states), budgets (30 states). `/private/tmp/interspace-budgets-source-ui.log` |
| Rebuild and strict signature | Passed; the sole `dist/Interspace.app` was rebuilt while the app was not running. `/private/tmp/interspace-budgets-{build,signature}.log` |
| Packaged browser suites (6) | All passed. `/private/tmp/interspace-budgets-packaged-ui.log` |
| Packaged resources | All 27 bundled files are byte-identical to source, including `budget.py`, with no extra files. `/private/tmp/interspace-budgets-resources.log` |
| Syntax and whitespace | `node --check` on all UI, test and runner scripts; `git diff --check`. Passed. |

## Whole-feature review

One independent review of `b54e9ec..ce4b3b3` returned **Clean**: no Critical or Important findings. It confirmed:
- all model calls go through the two gates;
- refusals consume no job reservation;
- `budget_exhausted` is terminal and survives restart;
- approval binding, migration and owner-bound UI requests work as specified.

Three Minor robustness findings were fixed test-first. Each new test failed before its fix.

- **A setup failure after the reservation left it held.** If saving `run.json` or publishing failed after reserving but before launch, the reservation stayed held and was later charged. It is now released (`budget.release`), because no call was made.
- **Cancel before dispatch charged the estimate.** `Application.call` reserved before checking cancel, so a cancel in that window charged the estimate. It now checks cancel first, as `team.invoke` already did.
- **A corrupt usage entry could stop the app opening.** A malformed entry (a reservation without an estimate, or a non-integer charge) could make `recover` raise at startup. Such entries now count as unknown, never as zero, and never crash.

The reviewer also noted, as a non-defect, that the gate enforces the task's current budget. That matches the approval only because budget edits are refused while a run is active.

After the fixes, both full suites passed again with the OS checks required: Python 3.14.6 and Apple 3.9.6, 244 tests each, zero skips. The rebuilt bundle passed the signature check, the byte-for-byte resource match and all six packaged browser suites. Logs: `/private/tmp/interspace-budgets-review-*.log`.

## Live native check

Run on 2026-11-11 in the rebuilt `dist/Interspace.app`, with the user's approval of exactly one real model call. Opening the app migrated the user's app data from v3 to v4, writing `state.v3-backup.json` first; existing tasks loaded normally.

- **Sizing:** offline, against a copy of the app data with a fake provider, the planner prompt for the chosen goal measured 7,811 characters. That gives an estimate of 18,604 tokens, against a 16,000-token minimum for any next call. A budget of 20,000 was chosen so that the planner call fits but no later call can.
- **The call:** a new **Read-only review** task on Snack Picker, budget 20,000, then **Propose a plan**. The one planner call launched, then hit its four-minute deadline: "Stage deadline reached; Codex process stopped. No automatic retry." With no counts returned, the ledger charged the estimate, 18,604, labelled estimated. The header read `Tokens 18,604 / 20,000 · 18,604 estimated`. No plan was produced, so Start refusal could not be exercised.
- **Refusal:** a follow-up message was refused before launch with "Token budget exhausted: the next Orchestrator call needs about 18,589 tokens, but only 1,396 of 20,000 remain. No call was started…". No `codex` process started. The message was kept in the conversation, and the task status became **budget exhausted**.
- **Total:** one real model call, which timed out. No Snack Picker files were read beyond the saved committed selection, and none were written.

The planner timeout is unexplained. Together with the earlier ~45-second delay before a first planning call, it suggests the first Codex call in a freshly started app can stall. It was not investigated here, and nothing was retried.

## Limits and pending

- No real model calls, native launch, personal app data or source projects were used for these checks.
- Estimates are heuristics, so a real call can be refused early or overshoot slightly. Both outcomes are shown and never hidden.
- Start refusal was verified only in automated tests, not live, because the live planner timed out without a plan.
- When this branch rejoins `main`, rebase it. `main` now carries the graphify setup as `51bbf6b` and `fdbaca0`, while this branch carries the older copy `57eaa4f`. In a merge instead, keep `main`'s `.claude/settings.json`.
- No merge or push.
