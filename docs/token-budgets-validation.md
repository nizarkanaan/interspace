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

## Limits and pending

- No real model calls, native launch, personal app data or source projects were used for these checks.
- Estimates are heuristics, so a real call can be refused early or overshoot slightly. Both outcomes are shown and never hidden.
- The whole-feature review and the live native check with a deliberately tight budget are pending. The live check needs the user's exact approval of its calls.
- No merge or push.
