# Bounded revision loop validation

Checked on feature/readonly-pilot. Main remains unmerged; Sample Project remains read-only input.

- Python 3.14 and system Python 3.9 full suites each passed 33 tests.
- Revision tests cover explicit previous-report/reviewer-feedback transfer, added user constraints, previous-version preservation, source/artifact binding, one-round allowance across failure/cancel/restart, duplicate-start rejection, acceptance eligibility/idempotence and report-only scope.
- A failing test reproduced supplemental revision instructions being discarded; both worker prompts now receive those instructions. A separate regression caught acceptance dropping freshly checked integrity metadata; the accepted record retains it.
- Chromium's synthetic native bridge verified exact run/artifact references on revision and acceptance requests, previous-version rendering, absence of acceptance actions on historical versions, and no horizontal document overflow at 1280, 1024, 390 or 320 pixels. No page errors were observed.
- No live model revision was started during this update. Tests use synthetic providers and disposable Git repositories. This is workflow/state verification, not an accuracy evaluation.
- Existing runs use round zero defaults and remain readable. Earlier reports are preserved when a revision starts. Failed/cancelled/interrupted revisions retain their spent allowance and history.

The app still uses separate ephemeral Codex jobs under one account. Backend state and explicit artifact handoff provide continuity; persistent Codex threads and per-role model selection are not implemented. Account usage is shared, and a round limit is not a dollar cap.

The rebuilt native Mac app opened the existing Sample Project run with Artifact version controls and an enabled Revise from reviewer feedback button showing 0/1 rounds used. The real round was left unspent. Strict app-signature verification passed after native launch; the archive was refreshed without user data.
