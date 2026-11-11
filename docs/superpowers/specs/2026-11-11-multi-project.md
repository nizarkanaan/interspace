# Multi-project workspaces

Interspace keeps a local registry of Git projects. Each owns its conversation, pending proposal, review history, brief, priority and next action. Adding a folder never replaces another project's data. Existing v1 state migrates once with an exclusive backup, preserving the Sample Project conversation and reports. Unknown schemas fail without overwriting storage.

A selected project controls browsing; an active job captures its owner independently. Browsing during work is allowed, but only one model interaction runs globally. Project requests include an explicit project ID and report actions retain run/artifact version binding. Requests from another selected project are rejected. Snapshot sources remain committed, bounded and allowlisted; README is required, PROJECT_CONTEXT is preferred when present. No source writes, execution, auto-dispatch or extra model calls.

Workspace Orchestrator receives registered names, user briefs, priorities, next actions and latest run status, without raw source, report bodies or project conversations. Project Orchestrator receives only its owner's evidence/history. Metadata updates are local and explicit. UI offers a project selector, overview cards, editable briefs/priorities, project run history, separately retained unsent drafts, and the existing static Tasks/Observatory views. Each installation stays personal and independent.

Python 3.9+; native macOS 13+ arm64; no new dependencies or HTTP service. Keep the olive light/dark design and static agent figures. Migration and testing must not spend a live model call or modify Sample Project.
