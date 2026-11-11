# Multi-project Workspaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Register multiple local projects with isolated work and a Workspace priority overview.

**Architecture:** Versioned JSON registry owns project state; orchestration captures project ownership before launching a worker. UI projects the selected registry entry and sends explicit IDs through the existing native pipe bridge.

**Tech Stack:** Python 3.9+, AppKit/WKWebView, vanilla JavaScript, unittest.

**Spec:** `docs/superpowers/specs/2026-11-11-multi-project.md`

## Global Constraints

Python 3.9+; native macOS 13+ arm64; no new dependencies or HTTP service. Keep the olive light/dark design and static agent figures. Migration and testing must not spend a live model call or modify Sample Project.

## Review Focus

- A worker finishes after switching projects: results remain with its captured owner (task 2 blocking-provider test).
- Stale report/source actions after switching: reject explicit mismatched ownership (task 2 stale-action test).
- Reopening while viewing a different project: recover the active owner's run (task 2 recovery test).
- Generic repository lacks PROJECT_CONTEXT: committed README fallback works without private imports (task 1 fallback test).
- Unsaved drafts or delayed source responses cross project switches: keep drafts scoped and discard delayed source views (task 3 browser test).

### Task 1: Registry and migration
**Files:** create `app/backend/projects.py`, `tests/test_projects.py`; modify `pilot/runner.py`.
**Interfaces:** `projects.load(storage) -> dict`; `projects.register(state, source, storage) -> project`; `projects.selected(state, reference=None) -> project`; `runner.prepare(source, storage, required_paths=None, project_name=None) -> Path`.
- [x] Write migration, backup, unknown-schema, canonical dedup and README fallback tests; run and observe missing behavior.
- [x] Implement v2 state migration and registry validation; preserve original source protections and default pilot requirements.
- [x] Run focused registry tests, then commit with task 2 as a coherent integration change.

### Task 2: Ownership-bound orchestration
**Files:** modify `app/backend/service.py`, `tests/test_app.py`, `tests/test_revision.py`, `tests/test_projects.py`.
**Interfaces:** add/switch/update project and select_run bridge requests; selected public state exposes `project_id`, summary `projects`, selected `threads.project`, `pending`, `run`, and scoped `runs`.
- [x] Test two projects retain independent chats/plans/runs, stale project actions fail, workspace context excludes private project bodies, project prompts exclude other projects, worker completion/cancellation stays owned, restart recovers active owner.
- [x] Capture owner ID at launch and pass it through chat/review/revise/run_stages; validate request identity before mutations; expose metadata summaries and history.
- [x] Update existing tests to send explicit project IDs and seed registry-owned reports. Run all Python tests on both available Python versions.

### Task 3: Native project interface
**Files:** modify `app/macos/main.swift`, `app/ui/index.html`; create `app/ui/workspace.js` for registry-specific UI; modify `app/README.md` and root `README.md`.
**Interfaces:** existing bridge plus switch_project/update_project/select_run; native choose_project maps to add_project.
- [x] Implement selector, overview, metadata form and run history with explicit IDs; preserve per-scope drafts and discard stale source responses. Keep metadata drafts stable on background state updates.
- [x] Check switching, metadata saving, history, delayed source races, light/dark and 320–1280px layout with a synthetic browser bridge.
- [x] Build native app, inspect migrated live state without model work, verify signature after launch; document checks and limitations.
- [x] Obtain a fresh independent whole-branch review, address substantive findings, rerun affected checks and commit. Leave feature branch unmerged for user review.
