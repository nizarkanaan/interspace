# Sample Project read-only pilot Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Run the first evidence-review workflow on a committed Sample Project snapshot without changing its checkout.

**Architecture:** A standard-library Python runner exports a fixed allowlist of committed technical files into ignored Interspace storage. The current Codex session orchestrates two real specialist sessions through an explicit artifact bridge. A generated, offline HTML run viewer displays persisted events, artifacts and provenance; it makes no model calls. This is a bounded pilot, not the standalone chat/runtime.

**Tech Stack:** Python 3 standard library; native HTML/CSS/JavaScript; current Codex session as provider bridge.

**Spec:** docs/orchestrator-design.md, bounded to the evidence-review pilot.

## Global Constraints

- All changes stay on feature/readonly-pilot in Interspace; do not merge main.
- Sample Project is input only. Read committed files via git show; never checkout, modify, start or benchmark it.
- No credentials, private records, untracked files or raw simulation data enter snapshots or git.
- Runtime artifacts stay under ignored workspace-data; record source SHA and content hashes.
- No simulated agent execution. Label the Codex-session bridge and unknown usage explicitly.

## Review Focus

- Source checkout contains existing edits: preserve exact tracked status and bytes.
- Caller submits paths outside run root: reject traversal and symlink run directories.
- Agent reports nonexistent evidence: reject unknown source/line citations.
- Reviewer arrives before researcher: reject out-of-order completion.
- Untrusted report text contains markup: escape it in the generated viewer.

### Task 1: Snapshot and workflow state

Files: pilot/runner.py; tests/test_pilot.py.
Interfaces: prepare(source: Path, storage: Path) -> Path; complete(run: Path, role: str, result: dict) -> None; render(run: Path) -> Path.

- [x] Write failing tests for immutable committed snapshots, explicit allowlists, excluded dirty data, missing input, invalid evidence, out-of-order completion, traversal/symlinks and safe report rendering.
- [x] Run python3 -m unittest discover -s tests -v and confirm missing behavior.
- [x] Implement validated snapshots, state transitions, event records and verification of source before/after.
- [x] Run all tests and both existing build checks.

### Task 2: Real session bridge and view

Files: pilot/view.html; pilot/README.md; README.md.
Interfaces: CLI prepare/complete/render/verify commands; result JSON schema documented in pilot/README.md.

- [x] Create a single original, responsive offline viewer with tasks, events, source manifest, report and reviewer findings; show executed provider path and uncertainty.
- [x] Prepare a real Sample Project snapshot. Run Researcher then Reviewer through the current session, recording completion only when artifacts exist and validate.
- [x] Verify source checkout matches baseline, inspect the viewer in Chromium and run all tests.
- [x] Commit implementation on the feature branch; retain branch for review. Do not include runtime artifacts in git.

Ruling: Nested Codex and loopback server operations are blocked by this environment. Use an explicitly labelled current-session artifact bridge for this run; do not claim standalone automatic dispatch. Cost: this pilot requires the controlling Codex session to dispatch workers.

## Execution record

- Researcher and Reviewer ran sequentially through the current session. Reviewer accepted the report within its stated repository-evidence scope; no fresh literature search or experiment ran.
- Source integrity matched the baseline after completion. Existing Sample Project changes were preserved.
- Final engineering review found relocated-run and symlink path gaps; added failing regression tests and fixed them. Also aligned LF citation counting with the viewer. Final suite: 9/9 pass.
- Browser: report/review/history/source tabs, citation expansion, 320–1280px fit, and rendered light appearance checked. No page errors in fresh navigations.
- Ruling: macOS temporary paths are canonicalized in test fixtures so system /var aliases do not mask the source-containment regression.
- No deferred code-review findings. Standalone server/provider remains unavailable here and is explicitly outside this bridge.
