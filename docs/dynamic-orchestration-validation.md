# Dynamic orchestration validation — 2026-11-11

Branch: `codex/dynamic-orchestration`; approved specification: [bounded dynamic orchestration](superpowers/specs/2026-11-11-dynamic-orchestration-design.md). The verified multi-project predecessor was integrated into local main at `b2fa576` before this branch. Dynamic orchestration remains unmerged and unpushed.

## Implemented behavior

Project chat may answer directly or propose a bounded dependency graph using Web searcher, Researcher and Reviewer, with one assignment per role. The user inspects objectives, dependencies, expected output, source revision, public search brief and call ceiling. Start binds project, canonical source, revision, plan ID and full content digest. Proposal edits and duplicate/stale actions cannot authorize another dispatch.

Durable per-job reservations precede sequential provider execution. Specialists receive explicit allowed inputs and cannot spawn more jobs. Web jobs receive only their displayed public objective in a fresh app-owned working directory. Hosted search URLs are recorded from provider events and required for accepted web evidence. Text-only jobs reject tools; search jobs reject other tools. A fixed synthesis job combines validated artifacts, with Reviewer verdicts and objections preserved. Unreviewed results cannot use reviewed acceptance. Partial work and unknown consumption remain inspectable after failure, cancellation or restart.

Legacy plans, report history, content-bound acceptance and the one-round legacy revision workflow are retained. New team runs use an additive `team-v1` format and require a new proposal for further work. Malformed or unsupported saved records are isolated as unavailable. Sample Project was not modified, executed or used in the new live checks.

## Deterministic and interface checks

- `python3 -m unittest discover -s tests -q`: **79/79 passed** (Homebrew Python 3.14.6).
- `/usr/bin/python3 -m unittest discover -s tests -q`: **79/79 passed** (Apple Python 3.9.6).
- Initial policy tests failed for the absent module; provider tests failed for absent search/failed-usage support; integration tests failed for absent dynamic proposals. They passed after implementation.
- Coverage includes graph/role/field limits, full Reviewer ancestry, reserved internal IDs, exact plan digests, canonical-path replacement, duplicate reservations, evidence provenance/ranges, role-scoped search, rejected tool activity, durable reservation before provider launch, unknown failed usage, project switching/cancellation, failed synthesis, legacy compatibility, restart and malformed history.
- A live Reviewer exposed an extra numbered blank line after a trailing LF. A regression reproduced the phantom line and passed after source prompts were restricted to actual manifest LF lines; Unicode line separators remain within their LF line.
- `tests/team-ui.mjs` initially failed because the public search brief was absent. It now passes on source and packaged UI: assignments/dependencies, exact Start references, waiting/running states, shared Observatory, combined/specialist output, retained selection, unresolved questions, excerpt links, reviewed acceptance and partial failures. Light/dark checks pass at widths 320, 390, 760, 1024 and 1280.
- Existing `tests/project-ui.mjs` passes on source and packaged UI: project/draft isolation, metadata save races, history and delayed responses.
- Packaged Observatory artwork was loaded and visually inspected; its canvas was painted at 964×605 with fixed Web scouts, Research and Review figures. No animation loop or simulated work was added. The synthetic screenshot is local ignored development data at `workspace-data/team-observatory-light.png`.
- `python3 scripts/build-macos-app.py`: native arm64 bundle built. `codesign --verify --deep --strict dist/Interspace.app`: passed after the final rebuild.
- Generated preview/role checks and `git diff --check`: passed. The 23 catalog role contracts and 69 seed scenarios are structurally validated, not model-accuracy evaluations.

## Live provider evidence and limits

A durable external test ledger reserved each call before launch and stopped at the approved **ten CLI jobs**. All prompts/sources were public or disposable. No failed job was automatically retried. All ten returned token usage: summed provider counters were 273,235 input tokens, 78,208 cached input tokens and 4,113 output tokens. Cached input is a separately reported provider counter; these figures do not establish price or remaining account allowance.

1. Direct project greeting: passed, with no specialist plan or run.
2. Local Researcher → Reviewer proposal: routing passed; Researcher artifact validated. Reviewer output cited an invalid line range and the run correctly stopped before synthesis. The source-prompt phantom EOF line was subsequently reproduced and fixed with a regression test.
3. Web searcher → Researcher → Reviewer proposal: routing passed and real hosted search events exposed search/open-page URLs. The web output had an empty summary and was rejected before handoff. Nonempty schema strings and explicit summary instructions were added; evidence checks were not relaxed.
4. With four jobs left, a fresh smaller public Web searcher → Researcher proposal was explicitly started. Search artifacts passed observed-URL validation, the Researcher used retrieved evidence, and synthesis completed as `completed_unreviewed`. This demonstrated live web provenance, handoff and combined output while preserving the ten-job ceiling.

No successful live full three-specialist reviewed run is established. That path passes deterministic integration tests, including Reviewer accept/revise and exact report acceptance. General specialist quality, source-to-claim correctness and full-paper review are not established by these checks. The ten-job live budget is exhausted; no additional live calls were made.

## Independent review and corrections

A fresh whole-branch reviewer confirmed three actionable issues. Each was reproduced with a failing regression before correction:

- Internal `synthesis`, `combined`, `sources` and `events` task IDs could collide with dispatcher jobs or result tabs. They are rejected before proposal display.
- Valid long Reviewer summaries/findings could make the combined unresolved-question list fail saved-record validation. The combined representation now permits complete bounded objections without truncation; worker output limits remain separate.
- A crash after publishing a completed record but before clearing the registry's active flag could mark a completed report interrupted. Recovery now interrupts only nonterminal team records and preserves terminal outcomes/errors.

All corrected regressions and both complete 79-test suites passed. No deferred minor findings. The review declined general accuracy/full-team live reliability; these remain explicit validation limits, not inferred successes.

## Native inspection status

A separately identified synthetic native test bundle was built and opened with isolated disposable state, without additional model work. The native inspection tool timed out; a subsequent inventory reported that the Mac was locked and could not be automatically unlocked. Thus the new native-window plan/Tasks/Observatory interaction check is **unavailable**, not passed. The user was asked to unlock the Mac while other verification continued. Packaged-browser rendering, native compilation and signature verification are separate successful checks.

## Implementation decisions recorded

- Reused the existing approved feature checkout rather than creating another worktree. This matches the requested branch and host checkout preference; it does not isolate filesystem edits from another editor.
- Used the remaining four live calls for a new smaller web/research plan after the initial rejected outputs. This kept the ten-job limit and no automatic retry policy; it leaves full reviewed live completion unverified.
- Kept general model accuracy and full-team live reliability outside completion claims. Successful routing and structural validation do not certify semantic correctness.

## Follow-up complete-team verification — 2026-11-11

The user authorized a fresh five-call complete-team check and subsequent local integration. On a new disposable public queue-design repository, the actual Orchestrator selected Web searcher → Researcher → Reviewer. Live hosted retrieval supplied an observed official Python documentation URL; Researcher compared that excerpt with the committed README, and Reviewer accepted the bounded brief while preserving the unspecified tie behavior and absence of implementation/performance evidence. Synthesis completed, retained the limitations/questions and passed citation validation. All three tasks and four execution jobs completed; no retry occurred. HEAD, status and tracked-file hashes matched the pre-run baseline.

The full plan used exactly five calls (planning, three specialists, synthesis), enforced by a separate persistent test ledger under ignored `workspace-data/reviewed-smoke-20261111/`. Report acceptance and repeated acceptance were also verified against the exact artifact without another provider call. The saved test report is `accepted`; the app recorded five usage entries. This closes the earlier missing successful live full-team path. General agent accuracy and independent full-page verification remain unestablished.

Fresh pre-integration suite: 79/79 Python tests passed. No Sample Project files or app data were used. The native-window check remains unavailable while the Mac stays locked; the user explicitly accepted deferring that check. No remote push is included in this integration.
