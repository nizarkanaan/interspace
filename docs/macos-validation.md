# Native Mac application validation

Checked 2026-11-10 on feature/readonly-pilot. No merge into main.

## Observed target behavior

The built Interspace.app opened as its own native Mac window. It started the local Python backend without a web server, recognized Codex authentication and answered a real Workspace-scope question. After quitting and reopening, that conversation was restored. The native path-confirmation sheet selected Sample Project and switched to its separate project thread.

A real project request produced a revision-bound plan. Starting it dispatched Researcher then Reviewer automatically through Codex CLI; the controlling chat did not create those worker sessions. The report, source citations, task states, reviewer outcome and usage remained in the app. The Reviewer returned `needs_revision` with specific corrections to the proposed experiment. The app retained that outcome. No experiment or source-project code ran. The final integrity check matched the sample project's source HEAD, Git status and tracked-file hashes.

The app user data is not committed or embedded in the bundle. The old session-bridge run remains separate and is not relabelled as this automatic run.

## Engineering checks

- Native Swift compilation, arm64 macOS deployment target, bundled resource layout and ad-hoc signature verification succeed.
- Python tests exercise real disposable provider processes for JSONL events, invalid output, failures, deadlines, cancellation, immediate rejection of tool events, descendants after leader exit and broken-pipe shutdown. Application fixtures cover persistent threads, role handoffs, source integrity, stale revisions, duplicate/busy requests, failed/interrupted states and invalid actions.
- Safety tests for committed snapshots, dirty/private exclusions, citation ranges, source/output separation, relocated/symlinked runs and markup injection remain in the full suite.
- Chromium tested app UI states using an explicitly synthetic native bridge: report/source selection, literal markup, task/Observatory switching and 320–1280px fit. No page errors or horizontal document overflow were observed. This UI fixture did not call a provider and is distinct from the real native run above.
- Existing preview/playbook checks pass. The 69 role-playbook seed scenarios have not been executed as a benchmark.

Python 3.14 and the system Python 3.9 full suites both pass 23 tests. A first Python 3.9 run hit a three-second fake-process startup allowance; its focused rerun and full suite passed with a less brittle startup allowance while retaining the delayed-side-effect assertion. Final app restart restored the selected project, saved run artifacts and separate conversations.

## Recorded limits

The first terminal `open` attempt reported kLSNoExecutableErr despite a valid executable/signature. Native app control successfully opened the bundle afterward. NSOpenPanel's Open control stayed disabled during testing; the verified native path-confirmation sheet is the primary project-selection path, with Browse optional.

This is an ad-hoc signed local Apple Silicon build, not a notarized installer or a self-contained Python/Codex distribution. No Intel/Windows/Linux native package is delivered. Sign-in device flow is implemented but was not exercised against a new account because an existing Codex sign-in was available. Routine tests do not spend model usage. Returned live token counts are recorded; dollar cost and account allowance remain unknown. The real Reviewer outcome does not establish scientific validity.

## Signed-resource restart regression

A final post-launch signature check initially failed because Python wrote provider/runner bytecode caches into signed Resources. The native launcher now uses Python -B. After rebuilding and launching the actual app again, strict signature verification still passed and no .pyc files existed in the bundle. The app restored its saved workflow. The regenerated archive contains this fixed build.
