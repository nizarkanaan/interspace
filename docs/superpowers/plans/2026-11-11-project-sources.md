# Project Sources Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, task by task, with one final independent review.

**Goal:** Let a project owner inspect and save a bounded committed source set, bound to chat and executable plans.

**Architecture:** `sources.py` owns Git tree/preview/selection and team-v2 snapshot boundaries while delegating old snapshots to the unchanged pilot. Registry/service expose explicit source actions; existing team policy/dispatcher support both versions. `sources.js` owns source panel drafts and responses.

**Tech Stack:** Python 3.9+, AppKit/WKWebView pipe bridge, vanilla JS, unittest and controlled browser tests; no dependencies.

**Spec:** `docs/superpowers/specs/2026-11-11-project-sources-design.md`, approved 2026-11-11.

## Global Constraints

Read-only source repositories, no Sample Project work or paid model calls. Reuse `codex/project-sources`. Maximum 16 selected UTF-8 text files, 250,000 bytes per file, numbered corpus 240,000 characters; tree 5,000 entries; preview 200 LF lines. New registrations require Save before project chat. Old projects/legacy/team-v1 reports retain original behavior. Keep static artwork, light/dark, responsive layout. Stay unmerged/unpushed for acceptance.

## Review Focus

- Bad/missing source metadata must never fall back to broader access (tasks 1–2).
- Scope changes between proposal, Start and snapshot must invalidate or retain the exact approved scope (task 2).
- Committed symlink ancestors, path collisions or snapshot tampering must not escape storage (task 1).
- Late panel/preview/save responses after project switches must not leak data or discard newer drafts (task 3).
- Old reports and accepted references must still load after new source settings are saved (task 2).

### Task 1: Committed source and snapshot boundary
**Files:** create `app/backend/sources.py`, `tests/test_sources.py`.
**Interfaces:** `selection(project)->dict`; `catalog(project)->dict`; `preview(project, revision, path)->dict`; `validate_selection(project, revision, paths)->dict`; `context(project)->(revision, scope, excerpt)`; `prepare(project, plan, storage)->Path`; `load(run)->dict`; `verify(run)->dict`.
- [x] Write failing tests for committed discovery/preview, credential/binary/symlink/submodule/path exclusions, 16/file/context/tree limits, LF behavior, immutable selected snapshots outside old allowlist, scope/hash/symlink validation and legacy loading.
- [x] Run `python3 -m unittest discover -s tests -p test_sources.py -v`; expect missing module failure.
- [x] Implement bounded read-only Git helpers, strict selection metadata, preview/context excerpts, selected snapshots and versioned loader. Preserve pilot code.
- [x] Run focused tests; expect all pass. Commit.

### Task 2: Source consent, plan binding and compatibility
**Files:** modify `app/backend/projects.py`, `service.py`, `orchestration.py`, `team.py`, native action allowlist; create `tests/test_source_workflow.py`; adapt existing fixtures to explicitly represent legacy registrations.
**Interfaces:** bridge `list_sources(project_id)`, `preview_source(project_id,revision,path)`, `save_sources(project_id,revision,selection_version,paths)`; public state `source_selection`/`source_error`; team-v2 plans include exact `source_scope` with revision/paths/selection version, covered by existing digest.
- [x] Write failing integration tests for new registration gate/no model call, save CAS and invalidation, selected-only chat/workers, Workspace/web exclusion, stale Start, source disappearance/HEAD change, active-save rejection, malformed settings, restart, and legacy report acceptance after source edits.
- [x] Run focused tests and observe failure. Implement actions and version dispatch; route all app run loads/integrity checks through `sources` so old loaders remain unchanged. Validate before user thread/provider launch.
- [x] Run all Python tests; expect all pass, with meaningful legacy fixtures preserved. Commit.

### Task 3: Inspectable source controls
**Files:** create `app/ui/sources.js`, `tests/sources-ui.mjs`; modify UI index/app/team sources.
**Interfaces:** `interspaceSources.render(state,request)` maintains per-project drafts and pending request generations. Source plan cards show immutable paths/selection version; run rendering supports team-v1 and team-v2.
- [x] Write controlled UI regression for catalog/preview, new project gate, check/save, source plan scope, retained drafts and delayed response isolation; observe failure.
- [x] Implement accessible Sources panel, committed-only labels/omissions, limits, excluded reasons and exact-save identity. Preserve unsaved drafts across background updates/switches.
- [x] Run new and prior project/team UI checks on built resources, inspect source panel at 320/390/760/1024/1280 in light/dark. Commit.

### Task 4: Verification and documentation
**Files:** update app/README.md and docs/engineering.md; create docs/project-sources-validation.md.
- [ ] Run full Python suites on both available interpreters, generated preview/role checks and diff check; build/signature verification. No further model calls.
- [ ] Obtain independent whole-branch review; reproduce/fix important findings test-first and rerun relevant/full suites. Record exact outcomes, limits and unavailable locked-Mac native inspection.
- [ ] Commit, keep branch unmerged, deliver built app and validation record.
