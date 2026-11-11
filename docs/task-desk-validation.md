# Native task desk validation

Date: 2026-11-11. This record covers the launchable application resources in `app/`, using controlled local bridge fixtures and disposable backend test repositories. The separate generated design preview was checked for consistency and was not changed.

## Delivered behavior

The application opens on Tasks, with New task and project navigation visible. Local creation is separate from the planning call. New tasks retain the full goal in task conversation/draft, use a title of at most 160 characters, and accept an editable positive safe-integer specialist allowance (default 6, no fixed six-specialist maximum). Each task has Conversation, Plan, Activity and Result. Project conversation explicitly selects `task_id:null`; Workspace advice remains a distinct metadata-only surface. Settings groups metadata, source consent and connection controls.

Plan exposes the actual assignments, distinct repeated-role labels, dependencies, exact public search briefs, source revision/version/manifest and approved call ceiling before Start. Detailed output/access/source information uses inspectable disclosure sections. Start, report acceptance, legacy revision, run selection and committed citations retain their project/task and existing plan/digest/run/artifact references. Combined answers lead the Result surface, followed by report actions. Specialist outputs/evidence/history navigation and usage/integrity are in named secondary disclosures. Per-assignment outputs, unresolved questions, exact historical reports and honest partial/unreviewed states remain accessible. Only recorded activity is shown.

Drafts are scoped by task/project/workspace. Creation responses arriving after switching or reopening New task leave the created task's goal recoverable without dispatching it into the newer context. Held project metadata/source saves cannot restore an old selected task over another task. Source helpers retain their project-owned late-preview/save and newer-draft guards. The active banner and Stop action follow the actual active owner. Malformed saved team proposals show an unavailable message without Start; other tasks remain usable.

The original scene file is unchanged. The UI passes distinct assignment numbers to it, so repeated figures render WS 1 and WS 2 while staying at fixed department stations. No timers, walking, simulated progress, framework or remote fonts were added.

## Executed checks

| Check | Actual result |
| --- | --- |
| `python3 -m unittest discover -s tests -v` with Python 3.14.6 | 142 tests passed, 90.523 seconds. Log `/tmp/interspace-task3-python314.log`. |
| `/usr/bin/python3 -m unittest discover -s tests -v` with Apple Python 3.9.6, after the 3.14 run completed | 142 tests passed, 69.697 seconds. Log `/tmp/interspace-task3-python39.log`. |
| `INTERSPACE_UI=dist/Interspace.app/Contents/Resources/app/ui/index.html node tests/run-ui.cjs` | All four browser suites passed: task desk, projects, sources and teams. Log `/tmp/interspace-task3-packaged-ui-final.log`. |
| Task desk responsive journeys | 80 surface/appearance/width checks: eight surfaces at 320, 390, 760, 1024 and 1280px, in light and dark. No horizontal overflow or page errors. Existing suites retain their additional fit checks. |
| Keyboard and untrusted text | Enter activates New task and exact Start; normal labelled forms/buttons remain keyboard operable. Artifact markup appears literally and creates no image element. |
| `python3 scripts/build-macos-app.py` | Passed, rebuilding only the sole `dist/Interspace.app`. Log `/tmp/interspace-task3-build-final.log`. |
| `codesign --verify --deep --strict --verbose=2 dist/Interspace.app` | Passed: valid on disk and satisfies Designated Requirement. Log `/tmp/interspace-task3-signature.log`. |
| Packaged resource comparison | Six UI resources and original static scene match source byte-for-byte. No app data or screenshots are bundled. |
| JavaScript syntax checks | `node --check` passed for `app.js`, `team.js` and `workspace.js`. |
| Generated checks | Preview matches source; 23 role contracts and 69 seed scenarios pass structural validation. No model evaluation was run. |
| `git diff --check` | Passed. |

`tests/run-ui.cjs` uses the existing environment's Playwright package and installed Google Chrome at `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`, with an isolated temporary browser profile and HTTP(S) requests blocked. It does not use the shared browser, personal tabs, a native app launch, a backend process or real providers. The packaged path also verifies the actual original scene code and drawn distinct figure labels. A source-only `node tests/run-ui.cjs` checks the UI without the packaging-only scene copy.

## Test-first evidence and fixture changes

The initial new journey failed because the old app did not open on Tasks. Additional regressions reproduced a late creation sending its goal after leaving/reopening New task, a same-project late metadata save restoring the wrong task, a malformed saved proposal lacking a safe display state, and duplicate WS 1 labels in the packaged original scene. Each received a focused correction and then passed the final browser run. The project-save regression covers both metadata and source saves.

Existing project/source/team browser fixtures were updated to use Tasks, Settings, Project conversation and distinct assignment labels instead of the removed conversation-scope selector and old default navigation. Output/history interactions explicitly expand the secondary disclosure. Their exact Start/digest, old-report history, project isolation, metadata/source draft preservation, delayed source/send/save protection, consent gate, citation link, partial-output and responsive assertions remain. No obsolete duplicate controls were retained for tests.

## Visual evidence and limits

The following generated screenshots are under ignored `workspace-data/` and were inspected: `task-desk-native-proposed-plan-light-1280.png`, `task-desk-native-tasks-light-1280.png`, `task-desk-native-settings-light-1280.png`, `task-desk-native-observatory-light-1280.png`, `task-desk-native-result-dark-320.png` and `task-desk-native-new-dark-320.png`. They show controlled fixture data, not real agent work. The runner regenerates them; they are not application data or Git artifacts.

Native window/keyboard integration on the locked Mac was unavailable and was not attempted. No device unlock, extra test app copy, source-project access, personal app-data access, network research, real sign-in or paid model call was used. Current Chrome light/dark screenshots do not establish macOS 13 WebKit appearance compatibility. The neutral/blue `@supports not (color:light-dark(...))` light/dark fallback remains in CSS, but target WebKit/native acceptance still needs an unlocked-device check. Strict signature validation is for this ad-hoc development bundle, not notarization or installer acceptance. The happy-path team fixture uses two independent public web searches, a Researcher consuming both, and a Reviewer covering them through the Researcher; fixture data is synthetic. Browser fixtures establish UI contracts and isolation; they do not establish model accuracy.
