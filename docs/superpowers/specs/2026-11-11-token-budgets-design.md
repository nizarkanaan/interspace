# Per-task token budgets

Date: 2026-11-11. Status: approved by the user on 2026-11-11; implementation pending.
Branch: `interspace/token-budgets`, stacked on `interspace/controlled-editing` (`b54e9ec`), which is not yet in `main`.

## Intent and decisions

The user compared Interspace with Paperclip and chose to stay single-person and local. They chose cost budgets as the first adopted feature, with these decisions (2026-11-11):

- **Unit: tokens only.** No money is shown or estimated. With ChatGPT sign-in, Codex usage counts against plan limits rather than a per-token price, so Interspace cannot know a monetary cost or the remaining account allowance, and must not imply it can.
- **Scope: per task.** No project-wide or period budgets in this version.
- **Hard stop: check before each call.** Token counts arrive only when a call finishes, so a call cannot be stopped at an exact token count. Interspace refuses to start a call whose estimate does not fit in what remains. A started call may finish over the limit; any overshoot is recorded and shown.
- **Unknown usage counts as the estimate.** A failed, timed-out or cancelled call that reports no counts is charged its pre-call estimate, labelled as estimated.

The remaining details below are proposals by the assistant, not prior user decisions.

## What a budget is

Each task has a **token budget**: a positive whole number of tokens, set on the New task form next to the specialist allowance and editable later on the Plan tab, like the allowance. The proposed default is **250,000 tokens**. For comparison, the complete live Snack Picker fix used 5 calls, 92,371 input and 3,525 output tokens (95,896 in total), according to the app's usage records.

**What counts.** A call's charge is `input_tokens + output_tokens` as reported by Codex in `turn.completed`. Cached input is part of `input_tokens` and still counts; account plans may discount it, but Interspace does not model plan rules. Implementation must confirm against current Codex output whether `reasoning_output_tokens` is already part of `output_tokens`. It must count each token exactly once and record the rule it used.

**What is charged to the task.** All model calls owned by the task:
- task conversation and planning calls;
- every specialist and synthesis call in its read-only team runs and Python-fix change runs;
- legacy revision rounds launched from it.

Project conversation and Workspace advice belong to no task and are not limited in this version. The UI says so plainly.

**The ledger.** The task's used total is derived from the existing durable usage records (`state.usage` entries with `task_id`, plus run job `tokens`), not from a separate counter that could drift. Each entry is one of:
- **reported**: counts were returned;
- **estimated**: no counts were returned, so the pre-call estimate is charged;
- **reserved**: the call is in flight and its estimate is held until it ends.

## Enforcement

**Estimate before each call.** The estimate is the prompt's input tokens plus a fixed output reserve for that role.
- Input tokens are approximated from prompt length, plus a fixed allowance for the provider's own instructions. Both are named constants calibrated from recorded calls, and biased to over-estimate. The recorded live calls reported 14,193–21,719 input tokens for prompts this app built.
- Output reserves are per role: planner, specialist and synthesis.
- No tokenizer dependency is added.

**Gate.** Every call goes through one budget check, at the same boundary where calls are already reserved durably: `team.invoke`, `Application.call`, and the change workflow's use of `team.invoke`.
- If `used + reserved + estimate > budget`, the call is not started. The refusal is recorded as `budget_exhausted` with the numbers, and no reservation is consumed.
- Otherwise the estimate is held as **reserved** before the provider launches. When the call ends, the reservation is replaced by the reported count, or by the estimate if nothing was reported.

**Running work.** A team or change run that hits the gate stops as a new terminal stage, `budget_exhausted`, just like a failed required call:
- completed artifacts, evidence, check results and the candidate are preserved;
- no retry, automatic resume or skipped stage follows;
- synthesis does not run if its own call does not fit.

The run's existing call ceiling and four-minute deadlines still apply. The budget is an additional limit, not a replacement.

**Before approval.** Plan and check-approval screens show the remaining budget and a projected total for the approved calls, built from the same estimates. If the projection exceeds what remains, Start and Run checks stay available but carry a clear warning that the run will likely stop early. Only a first call that cannot fit blocks the action outright.

## Approval binding and editing

The task budget at the moment of approval is bound into the approval, as the specialist allowance is today:
- plan `limits.token_budget` is included in the plan digest;
- change-run check approval records `token_budget` alongside the candidate, recipe and runtime identity.

Changing a task's budget clears any unstarted plan, as changing the allowance does. A started run keeps enforcing the budget recorded at its approval, against the task's whole ledger. A later approval, such as a change run's check approval, uses the task's current budget and is re-bound. Raising the budget never resumes a stopped run; further work needs a new plan or approval, as today.

## Existing data

Tasks created before this feature have no budget. They are migrated without rewriting history:
- their `token_budget` is `null`, shown as **No budget set**, with past usage still totalled;
- their unstarted plans stay valid;
- new calls from such a task are allowed, but the task header recommends setting a budget.

Only new tasks get the default. Saved records with a malformed budget become unavailable without affecting other tasks, following the existing malformed-record isolation. State moves to a new version with the usual one-time backup beside `state.json`.

## UI

- **New task:** a **Token budget** field next to Specialist allowance, with one line explaining that it counts reported tokens and is checked before each call.
- **Task header:** `Tokens 95,896 / 250,000`, with "estimated" marked when any charge is estimated.
- **Plan:** remaining budget, the projected total, and the warning above when it does not fit.
- **Activity and Result:** each call's charge, labelled reported, estimated or reserved. Any overshoot is shown explicitly.
- **Budget exhausted:** a plain message saying which call was not started and why. It also says the next step: raise the budget, then request a new plan or approval.

All of this follows the existing light/dark, keyboard and narrow-layout conventions. No money figures or remaining-account claims appear anywhere.

## Out of scope

Project or period budgets, money estimates, user-entered prices, mid-call cancellation on token count, budgets for project conversation and Workspace advice, and any change to the call ceilings, deadlines or approval model.

## Verification

Test-first coverage, using fake providers only:
- estimate, gate and reservation arithmetic, including the boundary when a call exactly fits;
- refusal before launch, with no provider call and no consumed reservation;
- overshoot recording;
- unknown usage charged as estimated;
- cancellation and timeout while reserved;
- restart while a reservation is held: it becomes estimated, never released silently;
- `budget_exhausted` stops for team runs and for change runs at each phase, with artifacts preserved;
- plan-digest and check-approval binding; budget edits clearing unstarted plans;
- migration of budget-less tasks with a backup; malformed-budget isolation; unchanged behaviour for legacy runs.

Browser journeys cover the New task field, the header totals, Plan projection and warning, the exhausted state, light/dark appearance and widths 320–1280. Both full backend suites run on Python 3.14 and Apple 3.9 with the OS canaries, plus the browser suites and a rebuild of the sole app bundle.

Live check: a small task deliberately given a tight budget, so that the gate stops it before a later call. This uses at most the calls you approve at that time. Exact live calls still need your explicit approval.
