# Inspectable project source selection

Date: 2026-11-11
Status: approved by the user on 2026-11-11, including reusable project source sets and explicit first Save before model access.

## Intent

A person adds any suitable local Git project, inspects its committed files and chooses which ones Interspace may supply to project chat and read-only specialists. The selected sources and revision are visible before a plan starts. Imported snapshots, report bodies, private drafts and credentials stay out of Interspace Git, and app data stays in Application Support. Sample Project remains read-only; no builds, scripts, experiments or project edits run.

The current hardcoded technical allowlist is useful for the original Sample Project pilot but misses relevant files in other projects. This milestone replaces that limitation for explicitly configured projects without widening old saved plans or reinterpreting prior evidence.

## Approaches

1. **Reusable project source set (recommended).** Save one bounded selection per project. Project chat and new plans use it; the exact file list is copied into every proposed plan. Convenient for continuing work and fits the existing project settings.
2. Per-plan source selection. More flexibility for unrelated tasks within one project, but adds a file-selection step to each plan and leaves project chat's prior context needing separate configuration. Defer unless the user prefers it.

The draft below uses approach 1 as an assistant proposal. Approval of this document also confirms that approach, unless the user chooses otherwise.

## User interaction

Add a **Sources** section beside project brief/priority controls. It shows the committed revision, current selected paths and total context size, with a searchable list of committed regular files, checkboxes and a read-only committed-content preview. It clearly distinguishes committed content from working drafts. Saving sources is a local action without a model call; display a summary of the files that subsequent project conversations and specialist jobs can receive. No full-repository auto-selection or agent-controlled source expansion.

The committed-file list contains names/modes/sizes only, not automatic content sent to models. Preview reads only the explicitly opened committed file and is labelled with path, revision and exact LF lines; long previews show the first 200 lines with an explicit omission label. The actual source allowance is controlled by the saved selection, not merely by opening a preview.

A source edit draft survives project switching within the current UI session, like existing metadata drafts. Save and delayed responses remain bound to project ID, revision and selection version. A late response must not replace a newer draft or another project's source panel. Source settings cannot be saved while any model interaction is running; browsing another project remains available.

Changing the saved selection increments its version and invalidates the project's pending plan. A stale save cannot overwrite a newer selection. New plan cards show the exact source paths, committed revision and selection version. Start checks all three along with the existing plan identity/content digest. Source settings are backend-owned; the Orchestrator cannot request additional paths in its response.

## Bounds and exclusions

Assistant-proposed initial limits: at least one and at most 16 selected files, each at most 250,000 bytes, and a combined numbered source corpus at most 240,000 characters. Selection save fails before changing state when these limits are exceeded; show which files or limit need attention. Empty text files may be listed but cannot be the only evidence. Committed file discovery is bounded at 5,000 entries; larger trees return a clear unsupported-size error without silently hiding selected files. These are deliberate first-release limits, not universal repository support.

Accept UTF-8 text blobs without NUL bytes. Reject absolute/traversing paths, control characters, Git metadata paths, tracked symlinks, submodules and nonregular entries. Do not follow working-tree symlinks to obtain content: read the chosen blob from the pinned commit. Validate canonical project ownership again before save and Start.

Known credential-file patterns such as `.env*`, private-key/certificate containers (`.key`, `.pem`, `.p12`, `.pfx`) and standard private-key filenames are unavailable in this first selection UI. Show the reason locally. These exclusions reduce accidental disclosure; they do not certify that an otherwise eligible text file contains no secrets. Only an explicit saved selection grants selected-source content access to models. Opening a committed preview authorizes that local preview only. Existing integrity checks separately hash tracked working files locally, including unselected files and dirty drafts; they store hashes rather than those file bodies and never supply that content to models. No heuristic secret scanning, downloads or external integrations are added.

## Context and execution

Once a project uses an explicit source set, project chat receives only selected committed file excerpts (up to the existing 24,000-character total chat context allowance), plus its own conversation, brief and explicitly selected historical report. Excerpts identify original LF line ranges and any omissions. The planner can see the full selected file manifest and knows that chat excerpts may be partial. Existing historical reports remain labelled with their original revision; they do not become fresh evidence for new runs or expand the new snapshot.

Researcher and Reviewer receive the complete selected, numbered snapshot within the 240,000-character bound and their assigned dependency artifacts. Live Web searcher input remains only the displayed public objective; source selection never gives it project text, paths or reports. Workspace conversation still receives metadata summaries only, without selected file contents.

New projects show the committed README and PROJECT_CONTEXT when present as suggested checkboxes in an unconfirmed draft. The user must save that source set before the first project chat or specialist plan; registration alone does not authorize model access to those contents. Workspace metadata conversations remain available. Existing projects keep their previously authorized legacy source behavior until the user explicitly saves a new set. Registering a folder does not read/send its entire contents. The existing committed README requirement for registration remains for this milestone; changing that requirement is separate work.

If a selected path disappears, becomes ineligible or the commit changes, do not silently substitute another source. Ask the person to inspect the changed source selection and request a new plan. In-progress runs keep their approved immutable snapshots; final source-integrity checks and acceptance retain their existing behavior. No running scope changes, automatic reruns or budget expansion.

## Ownership and persistence

Keep the v2 project registry with an additive, versioned source-selection field and a monotonic per-project selection version. For pre-existing registry entries, missing fields mean legacy defaults. Newly registered projects explicitly store an unconfirmed selection state, so they cannot fall back to legacy access before Save. Never silently turn a corrupt selection into legacy or whole-repository access. Save the selected paths and context policy locally and transactionally. Old source choices, histories and approval scope must survive project switching and app restart.

A focused app-owned `app/backend/sources.py` will own committed-tree discovery, eligibility, preview, bounded selected-blob snapshots and loading/verification of those snapshots. It is a concrete filesystem/Git boundary, not a generic repository framework. Preserve `pilot/runner.py`'s existing allowlist and standalone pilot behavior. New app code dispatches to the legacy loader for existing pilot/team-v1 reports and to the selected-source loader for new team-v2 records. Both loaders validate run ownership, snapshot boundaries and hashes before returning data.

Team-v2 keeps the current team graph, durable usage reservation, evidence and acceptance contracts, adding an explicit versioned selected-source manifest bound to the approved plan. Team-v1 and legacy histories remain viewable and retain their original acceptance/revision behavior. Unknown future formats remain unavailable without rewriting them. The UI discriminates supported team versions explicitly; no format inference from optional fields.

Saving a source set invalidates unstarted legacy or team proposals for that project. Previously completed reports retain their original source manifests and acceptance references. New runs do not use the legacy two-stage revision action.

## Implementation and verification

Use the existing Python pipe backend, native action allowlist, vanilla JavaScript and static Observatory. Reuse the current checkout on `codex/project-sources`; no new dependencies, account settings, network service, role, provider or external-app integration. No additional live model calls are included: use controlled providers and disposable repositories to verify the source boundary.

Test-first coverage includes selecting a file outside the old allowlist; exclusion of unselected/dirty/private files; committed rather than working content; symlink/submodule/path rejection; file/count/context limits; malformed selection recovery; stale saves/Start; selection-version invalidation; source disappearance and commit changes; project switch/delayed-response ownership; new/legacy snapshot integrity and accepted-report compatibility. Verify project prompts contain only selected current file bodies while Workspace and web prompts contain none.

Browser checks cover saved source inspection, committed previews/omission labels, changed selections, exact plan source lists, draft retention, stale responses and light/dark responsive layouts. Run both supported Python suites, generated-preview/role checks, native build and signature verification, and independent final code review. The Mac may remain locked; packaged-browser and backend checks proceed, with native interactive inspection recorded as unavailable until it can run.

Keep implementation on its new feature branch for review. Do not push or integrate this source-selection milestone into main before acceptance.

Builder check clarified two assistant-proposed decisions for approval: source selection controls model inputs while the existing local tracked-file integrity hashing remains, and newly registered projects require an explicit first Save before model access. Other implementation questions were sufficiently specified.
