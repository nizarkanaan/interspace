# Controlled Python editing validation

Date: 2026-11-11 (Toronto; some UTC test timestamps fall on November 12). This record covers the controlled editing UI, backend compatibility and rebuilt native resources on `interspace/controlled-editing`. The native/live acceptance pilot remains coordinator-owned and pending. Browser screenshots contain controlled fixture data, not real agent work.

## Delivered workflow

New task defaults to **Read-only review** and offers **Fix & test (Python)**. Mode is fixed on creation and displayed in task detail. The existing task conversations, source consent, allowance, Plan/Activity/Result and project/workspace navigation remain in place. Implementer and Tester use the original fixed builder artwork; Reviewer retains the existing review figure. No original scene rewrite, timers, simulated activity, new service, framework or external imagery was added.

A change proposal shows assignments, each Implementer's exact write paths (existing selected or new), dependencies, committed source scope and fixed model/process/file budgets. **Generate candidate** uses only its complete server-projected exact start reference. It does not approve checks or source application.

Result shows the frozen unified diff, original/candidate evidence and recorded original/regression/candidate check summary. **Run candidate checks** displays the complete candidate/artifact/recipe/runtime identity, three fixed processes with scratch/deadline/output restrictions, and the number and names of remaining specialist/synthesis calls. **Apply reviewed changes** is separate and available only through the backend's ready gate and exact projected application reference; its copy lists paths, target, retained originals/journal, invalidated plans and uncommitted consequences.

The main explanation uses plain isolated-copy and check-phase consequences; detailed tree/scratch/network/output bounds are in **Check isolation & execution limits**, while deadlines and remaining calls stay visible. The UI never constructs write/check references or discards runtime fields. Captured action handlers validate the current owner and projected reference; late check/application responses also validate run, plan, candidate and artifact before replacing state. Evidence uses `change_evidence`, checks the full returned identity and selection epoch, and cannot replace another task's source pane/draft. After Apply consumes action refs, immutable read-only evidence refs can be derived from the selected public owner/run/plan/candidate/artifact, including a fresh UI session. Original evidence retains original bytes.

Paused, checking, revision-needed, failed, applied, unavailable and recovery states remain explicit. No automatic repair/retry/resume is introduced. Diff blocks scroll within the task column on narrow screens; ordinary buttons/selects/details retain visible keyboard focus and light/dark appearance.

## Test-first evidence

The initial restricted Chrome launch failed before UI execution (SIGABRT/EPERM); `/private/tmp/interspace-task4-ui-red.log` is environmental, not RED evidence. The approved outside-restriction run reached the intended assertion **New tasks need a plain task-mode choice** (`/private/tmp/interspace-task4-ui-red-clean.log`, exit 1), before UI implementation.

A separate late-artifact regression failed **Late approval restored an older artifact** (`/private/tmp/interspace-task4-late-approval-red.log`, exit 1). Its trace showed that shared response handling checked owner but did not distinguish the newer artifact of the same task. Explicit run/plan/candidate/artifact response gating fixes it. Both regressions passed in subsequent complete source journeys.

`tests/change_saved_state_fixture.py` creates disposable Git repositories and temporary app storage, consumes actual backend public projections through the complete lifecycle, applies only to its own source, and verifies evidence again through a freshly reopened Application. Model and process adapters are fake. It also supplies actual revision, failed and source-stale projections. The browser bridge plays those states/evidence through the real UI and rejects requests that differ from complete public action refs. These checks establish presentation/contracts, not real process execution or model accuracy. Task 3 separately records its actual default-adapter temporary end-to-end check/apply/reopen probe.

## Executed checks

| Check | Actual result |
| --- | --- |
| Full Python 3.14.6 backend suite, required OS canaries | Passed: 214 tests in 331.747 seconds, exit 0, zero skips or failure/background-exception diagnostics. `/private/tmp/interspace-task4-backend-python314-final.log`. |
| Full signed Apple Python 3.9.6 backend suite, required OS canaries, sequentially after 3.14 | Passed: 214 tests in 283.932 seconds, exit 0, zero skips or failure/background-exception diagnostics. `/private/tmp/interspace-task4-backend-apple39-final.log`. |
| Source `node tests/run-ui.cjs` | All five suites passed (task desk, projects, sources, teams, changes); `/private/tmp/interspace-task4-source-ui-copy-final.log`. |
| Packaged `INTERSPACE_UI=dist/Interspace.app/Contents/Resources/app/ui/index.html node tests/run-ui.cjs` | All five suites passed on final copy; `/private/tmp/interspace-task4-packaged-ui-copy-final.log`. |
| Editing responsive checks | 60 stage/appearance/width combinations: plan, paused, ready, revision, failure and fresh applied state at 320/390/760/1024/1280, light/dark. No whole-page overflow or page errors. Existing journeys retain their checks, including 80 task-desk surface combinations. |
| Keyboard / text / scene | Enter activates Generate and final Apply; native controls remain keyboard operable. Model/diff markup is literal. Original fixed scene draws IM 1 and TS 1. |
| `python3 scripts/build-macos-app.py` | Passed; rebuilt only `dist/Interspace.app` after coordinator confirmed the old app was closed. `/private/tmp/interspace-task4-build-copy-final.log`. No native launch. |
| `codesign --verify --deep --strict --verbose=2 dist/Interspace.app` | Passed outside nested restriction: valid on disk, satisfies Designated Requirement; `/private/tmp/interspace-task4-signature-copy-final.log`. |
| Packaged resources | All 26 resources byte-match source, including editing backend modules, `changes.js` and original scene copied into UI. No app state/run data/Python caches bundled. `/private/tmp/interspace-task4-resources-copy-final.log`. Recursive packaging already includes them; build script unchanged. |
| Syntax / generated | Every UI JS plus new browser test/runner passed `node --check`; all backend modules/new fixture passed Python AST parsing. Preview matches source; 23 role contracts/69 seed scenarios validated structurally. Model evaluations not run. |
| `git diff --check` | Passed after final-copy implementation and documentation updates. |

## Visual evidence

Ignored `workspace-data/` screenshots are regenerated by the suite. Inspected source screenshots: `changes-source-ready-light-1280.png` (combined result, frozen diff, three check summaries and distinct Apply), `changes-source-paused-dark-320.png` (narrow diff locally scrolls, test pause and remaining calls). Both show controlled data. Corresponding light/dark and packaged variants plus `changes-{source,packaged}-observatory-light-1280.png` are retained for inspection. Exact final screenshot paths and test commands are also recorded in `.superpowers/sdd/2026-11-11-controlled-editing/task-4-report.md`.

## Limits and pending acceptance

No personal app-data access, real model/sign-in job, Sample Project or Snack Picker access, native launch, account changes, external messages, new app copy, merge or push occurred in this UI task. The sole bundle remains an ad-hoc signed development build, not a notarized/self-contained installer. Chrome fixtures do not establish native WebKit integration or macOS 13 appearance acceptance. The neutral CSS fallback remains intact. Coordinator-owned scoped/whole-feature review and the exact live Snack Picker generation/check/application approvals remain pending; implementation approval does not preapprove that unknown patch. Passing generated tests does not certify semantic correctness or general hostile-code containment.
