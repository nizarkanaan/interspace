# Multi-project validation — 2026-11-11

Branch: `feature/multi-project-workspaces`. Implemented scope is described in the [spec](superpowers/specs/2026-11-11-multi-project.md).

- New tests initially failed because add_project was unsupported and v1 state was not migrated. After implementation, all 46 Python tests pass on Python 3.14.6 and Apple's Python 3.9.6.
- Disposable repositories and recording providers verify independent threads/plans/runs, canonical folder deduplication, README-only fallback, metadata validation, stale project/source/report rejection, selected run history, owner-bound worker completion and cancellation after switching, active-owner restart recovery, migration backup and future-schema protection.
- Workspace prompt inspection confirms registered brief/priority inclusion while source markers, project messages and report bodies remain excluded. Project prompts exclude the other project's context.
- `tests/project-ui.mjs` exports a controlled Playwright bridge check accepting a Page and local UI URL. Observed pass: project switching, conversation/metadata draft retention, metadata save ownership, history restoration, stale source response suppression, late send response safety, newer metadata drafts retained across delayed save responses, overview cards and horizontal fit at 320, 390, 760, 1024 and 1280 pixels. No live provider/backend is connected in that check.
- Native arm64 macOS app built and launched. Existing Sample Project state migrated to v2; hashed conversations, current report reference and usage count matched before/after, with original v1 backup retained. Native brief/priority controls, Add project dialog cancellation and static Observatory were inspected. No extra user project was registered and no model work was started.
- `codesign --verify --deep --strict dist/Interspace.app` passes after launch. No Python bytecode appears in the signed bundle.
- Generated design preview and role-contract checks pass; no changes to catalog roles or prototype sources. Template checks do not establish model accuracy.

Limits: no fresh model evaluation of Workspace priority advice; deterministic prompt/ownership checks cover this change. The official provider adapter's prior live validation still applies. No notarized installer or bundled Python; one global interaction; fixed source allowlist; dynamic specialist routing remains future work.

Independent review confirmed no Critical/Important isolation findings. Its metadata-save race was treated as Important because it could discard newer edits; a controlled browser regression failed before the fix and passed after. Corrupt/missing snapshot and run-metadata isolation was also strengthened: backend regressions failed first, then passed with unavailable-history status and other projects still usable. Both fixes preserve strict ownership and evidence checks. Full post-fix suites: 46/46 on both Python versions; native app rebuilt/reopened and signature verified after launch. No model-backed priority advice evaluation was run.

## Integration recheck — 2026-11-11

The user requested integration before dynamic orchestration. Fresh checks at `d3a015f`: 46/46 Python tests pass with both `python3` and `/usr/bin/python3`; generated preview and role-contract checks pass; `git diff --check` passes. The native arm64 app rebuild and strict signature verification pass. The controlled two-project browser check passes for drafts, metadata, report history, delayed responses and 320–1280px fit.

A separately identified native test bundle loaded two disposable Git projects and synthetic reports from isolated development storage. Switching A → B displayed each project's own conversation marker and review history. No personal project was registered, no model job was run, and the saved Sample Project workspace was not changed. An initial duplicate test instance shared a data-directory lock and showed a stopped backend; relaunching the separate test bundle with its own data directory completed the check. Test bundles and data remain ignored under `workspace-data/`.

A fresh independent review of `e594e249..d3a015f` reported no blocking findings in project ownership, stale actions, recovery, migration or source boundaries. This supports local integration only; no new specialist-routing or model-accuracy evaluation is implied.
