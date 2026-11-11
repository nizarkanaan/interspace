# Project source selection validation — 2026-11-11

Branch: `codex/project-sources`. Approved scope: [source-selection design](superpowers/specs/2026-11-11-project-sources-design.md). A separately authorized live verification and local integration followed the initial branch review; see the follow-up below.

## Implemented behavior

- New projects show suggested committed sources but require an explicit **Save sources** before project chat can store a message or start a model call. Pre-existing projects retain their previously authorized legacy defaults until an explicit selection is saved.
- The Sources panel lists committed names/sizes, excluded reasons, a path filter and committed previews with exact LF ranges and a 200-line omission label. Saved file sets persist locally; unsaved selection drafts remain project-owned across switches.
- Selection save checks project ownership, canonical folder, exact revision and expected selection version. It validates 1–16 paths, 250,000 bytes per file and a 240,000-character numbered corpus before changing state. A changed selection invalidates pending plans. Start independently rejects a restored stale proposal or scope mismatch.
- Project chat receives selected committed excerpts with explicit omissions beyond 24,000 characters and the full path manifest. Researcher/Reviewer receive the selected immutable snapshot. Workspace and Web searcher prompts receive no selected file bodies.
- Working drafts and unselected file bodies stay outside model evidence. Symlinks, submodules, unsafe paths, binary/non-UTF-8 files and known credential/key names are rejected. These exclusions do not certify that all other text files are free of secrets. The separate existing integrity check still hashes tracked working files locally.
- New team-v2 snapshots bind the exact selected paths, selection version and revision to the approved plan. Legacy/team-v1 histories retain their original snapshots and report actions. Explicit legacy report revision continues to use that original snapshot. The standalone pilot code and allowlist remain unchanged.
- Delayed source previews/saves cannot switch the visible project or erase a newer source draft. Read-only browsing is available during work; saves are blocked while a model interaction is active.

## Evidence

The source policy tests initially failed for the absent module; workflow tests failed for the absent source actions/consent gate; the browser test failed for the absent panel. After implementation:

- Source policy tests cover committed rather than dirty content, LF preview/omissions, excluded modes/names, binary/UTF-8 validation, file/count/tree/context limits, malformed/unconfirmed/stale selections, out-of-allowlist selected snapshots, scope/hash/symlink validation and legacy loading.
- Workflow tests use actual disposable Git repositories, snapshots and Application state with controlled provider processes. They cover explicit first Save without a model call, selected-only prompts, exact plan scope, source edits/old acceptance, save compare-and-set, stale Start restoration, changed commits, Workspace/web exclusion, active-save rejection, cross-project requests and restart.
- Existing tests now explicitly seed previously authorized registrations through a test-only helper; the new tests separately verify that fresh registrations cannot inherit that legacy permission. No consent bypass helper exists in production.
- `tests/sources-ui.mjs` passes against packaged resources: explicit Save gate, file selection and preview, exact plan source list/version, source-save project/revision/version binding, project draft retention, late preview/save isolation, exclusion reasons and omission labels. Light/dark and widths 320, 390, 760, 1024, 1280 pass without horizontal overflow or page errors.
- Existing project/team browser suites pass on the packaged resources. The Sources panel screenshot was visually inspected; it remains within the existing olive light/dark layout. Screenshots and test data stay ignored under `workspace-data/`.
- Generated design preview and role-contract checks pass. The unchanged role contracts are structurally checked, not a new model-accuracy evaluation.
- Native arm64 build and strict signature verification pass. Interactive native-window inspection remains unavailable by the user's locked-Mac preference; packaged-browser coverage is not represented as native interaction.

Final verification:

- `python3 -m unittest discover -s tests -q`: **100/100 passed**, Python 3.14.6.
- `/usr/bin/python3 -m unittest discover -s tests -q`: **100/100 passed**, Apple Python 3.9.6.
- One concurrent Apple run failed the existing `test_backend_quit_with_closed_output_stops_active_provider` startup PID-file wait. Its focused rerun and a sequential full Apple suite passed; no timeout was extended and no test was suppressed. The transient failure is retained here rather than treated as a resolved production defect.
- Final packaged project, team and source UI checks passed. Both light desktop and dark narrow Sources rendering were visually inspected.
- `python3 scripts/build-macos-app.py`, `codesign --verify --deep --strict dist/Interspace.app`, generated-preview/role checks and `git diff --check` passed. `pilot/runner.py` has no diff from the integrated main baseline.

## Independent review fixes

A fresh whole-branch review reported two confirmed issues:

1. Non-object JSON in a saved run could raise an uncaught AttributeError and prevent other projects/startup from working. A regression reproduced arrays, nulls, strings and numbers; the loader now rejects them through the normal unavailable-history path. The test also verifies another project and restart remain usable.
2. Universal-newline conversion could turn standalone CR characters into LF and truncate worker evidence against the true LF manifest. A regression reproduced loss in the actual worker prompt and source-view response. App snapshot readers now decode original bytes without newline translation, preserving evidence and LF citation ranges. The pilot remains unchanged.

Both focused regressions failed before the correction and passed afterward. An initial parameterized test fixture retained its own project switch between corruption cases; that fixture was corrected before the final suite runs. No other production fix was needed for that fixture failure. No deferred minor findings. The reviewer did not independently verify native interaction or every possible asynchronous UI ordering; controlled regression cases cover the stated races.

## Scope and limits

The initial implementation used no real provider/model call, account change, Sample Project access, source-project execution or external write. The separately authorized follow-up below records live verification and local integration; no remote push is included. Verification uses disposable repositories and controlled providers. The native-window check can be performed after unlocking; source consent and ownership are enforced at the backend regardless of UI state.

## Live source-selection follow-up — 2026-11-11

The user authorized up to four fresh model calls, followed by local integration after a successful check. A new disposable project contained an unselected README, another unselected note, and `review/selected-brief.txt`, which is outside the historical pilot allowlist. The selected working file was deliberately changed after commit. The first project chat was rejected before any provider call; the source set was then explicitly saved and bound into the plan.

The live Orchestrator selected Researcher → Reviewer. All four calls (planning, both specialists, synthesis) completed, the Reviewer accepted the bounded brief, and the source integrity comparison passed. Every provider input was checked before launch for the unselected README/note and dirty-draft sentinels; none was present. The resulting team-v2 manifest contained exactly `review/selected-brief.txt`, and findings cited its committed LF lines. Acceptance and repeated acceptance succeeded without another call. The separate durable ledger recorded exactly four calls: 54,759 input tokens, zero reported cached input tokens, and 1,771 output tokens. These are provider counters, not a spending estimate.

The report raised the commit identifier as missing because the worker prompt had not included that runtime metadata. A focused regression failed for both Researcher and Reviewer; prompts now include the captured snapshot revision, approved source paths and selection version, and synthesis receives the same provenance. Web input remains unchanged. The regression and full 101-test Python suite pass; generated checks, native rebuild/signature verification also pass. No additional live call was used to re-evaluate the small prompt-metadata correction. This establishes one successful live selected-source path, not general agent accuracy.

Post-integration verification: both complete suites pass 101/101 on Python 3.14 and Apple Python 3.9. Local main contains the source-selection milestone. A separate Sample Project contact/visit measurement request was prepared from committed technical files only; its source baseline remained unchanged. It is awaiting a separate model-call allowance, with no Sample Project model run started.
