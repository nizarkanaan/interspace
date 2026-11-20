# Interspace Mac app

Launch `dist/Interspace.app` with a double-click. It opens its own native window; no HTML file, browser tab or local web server is required. The backend starts and stops with the application.

**Status (2026-11-19): a multi-provider agent workspace.** Claude Code and Codex run as agents under one Orchestrator; Gemini comes later. Plan: `docs/superpowers/plans/2026-11-15-multi-provider.md`.
- **Every task** is a conversation with the Orchestrator. It answers directly, or proposes a team of subagents on Claude and Codex that you approve before anything runs.
- **Review and merge:** each writing subagent commits to its own `interspace/task-…` branch. **Review changes** shows the diff; **Merge** merges it into a branch you pick.
- **Removed:** the Read-only review and Fix & test (Python) modes, project sources, Workspace advice, the Observatory, project conversation and connected apps. Earlier tasks still open read-only, labelled "Earlier task (read-only)".
- **Research workspace (approved 2026-11-19, being built):** research questions without a project, scholarly sources with your own keys, and a citation checker. See [Research](#research). Plan: `docs/superpowers/plans/2026-11-19-research-workspace.md`.
- **Not yet done:** a live run with real Claude and Codex sign-ins inside the app, and live research calls with your own keys. The full team flow and the research screens are tested with fake command-line tools, recorded fixtures and fake replies, never the network.

## Projects and tasks

**Add project folder** registers a Git repository. The project picker switches among projects; each keeps its own tasks. **Settings → Project details** saves a name, brief, priority and next action locally, without a model call or source edits.

**Settings → Providers** shows each provider's sign-in state, starts a sign-in or shows the command to run, and sets the default provider and model for each role (Orchestrator, researcher, implementer, reviewer, tester, writer, citation checker).

**New task** starts an Orchestrator conversation. Choose **Research question** (no project needed; see [Research](#research)) or **Project task**:
1. Give a title and, for a project task, pick the project. The Orchestrator uses your default provider and model unless you change them here.
2. Review the task scope, then choose **Create task**.
3. Approve the scope on the task, then message the Orchestrator.

**Teams.** When the Orchestrator wants help, it proposes a team. Each member has a role, a brief, a provider, a model and read or write access. A member that differs from your defaults shows the Orchestrator's one-line reason. You can change any member's provider, model, access and brief, or remove members. Nothing runs until you choose **Approve team**; **Decline** can carry a note back to the Orchestrator.

**Subagents.** Approved members run in parallel. Each works in its own copy of the project, and its card on the task shows its state, tokens and latest activity. **Show activity** opens its full stream. Subagents never appear as separate tasks on the desk; **Running** groups them under their task.

**Review changes → Merge.** A writing subagent's changes are committed to its own `interspace/task-…` branch. **Review changes** lists the changed files and the diff. **Merge** merges the branch into the branch you pick, in a temporary worktree, and only if the branch is still the one you reviewed. Interspace never changes your checked-out branch or working files: to merge into the branch you have checked out, run `git merge` there yourself. Conflicts are reported, and nothing is forced.

Inside the scope an agent acts without asking. Outside it, that task alone pauses and asks: Allow once, Add to scope, or Deny. Read-only members and the Orchestrator can never write. Up to 4 agent runs work at once, subagents included; further runs queue.

## Research

Interspace is a research environment that still codes. A **research question** needs no project: agents search scholarly sources, follow citations, and give you a report. They are told to check what they cite with the citation checker before answering; that is an instruction to the agents, not something the app enforces, so the citation report shows exactly what was checked. When it ran, you also get a BibTeX file.

**Status.** Everything here is tested with recorded source replies and fake agents only. No live call to a research source or a model has run inside the app yet.

**Sources.** Semantic Scholar, OpenAlex, arXiv, Crossref and Unpaywall. **Settings → Research sources** lists each one with what it needs, its status, **Test**, **Remove** and a link to get a free key:
- Semantic Scholar and OpenAlex: an optional API key, which raises your allowance.
- Crossref: an optional email; Unpaywall: a required email. The email goes to that service with each request, as the contact address it asks API users for.
- arXiv: nothing to enter.

Keys and emails are your own. They are kept in this Mac's Keychain, are never shown again after you save them, and never reach agents, logs, events or git. Only Interspace's backend calls these services, over https. Research calls use no tokens; each task shows, per source, the requests it sent and the answers that came from the cache instead, never money.

**Research questions.** **New task → Research question** offers presets: **Literature review**, **Related work** and **Verify my references** (paste a bibliography). The scope has research sources only: no project, files, commands or network. Each source is **Allow**, **Ask** (each call waits for you) or **Off**; new scopes allow the sources you can use. Every team member only reads. Research tasks are listed under **Research** in the sidebar, next to your projects, and have no Review or Merge.

**What you see.** Research tool calls show papers with title, authors, year, venue, sources and citation counts; links appear only for https addresses, and all text from the sources is shown as plain text. A search names the sources it skipped and why (not set up, rate limited, unavailable, off in the scope). The **citation report** marks each reference **Verified** (a published record's title is at least 90% similar, and the year within one and the first author match when the reference gives them), **Not verified** (differs, with the fields, or not found), **Retracted**, or **Not checked** with the reason. Retracted and unverified references are listed first, with their reference number, and a retracted one is called out above the list. Nothing is called verified unless the checker said so. In a report, every link shows its real host after its text, and only https links are links.

**Outputs.** A finished research answer is saved as `report.md`, plus `references.bib` when the citation checker ran: it holds the verified references, mismatched ones marked in a comment, and leaves not-found and retracted ones out. **Outputs** on the task shows them; **Save** copies a file to a place you choose. Project tasks still use Review and Merge for code.

When the citation checker runs as a subagent, its citation report also appears on that subagent's card in the task, so you do not need to open the subagent to see it. A subagent that has answered its brief shows **Finished**.

**Browser end-to-end.** `tests/research-e2e-ui.mjs` drives the real backend (`tests/e2e/research_backend.py`) over JSON lines with fake agent runtimes, research HTTP answered from `tests/research/fixtures/`, and a fake Swift side (an in-memory Keychain and save panel). It covers Settings → Research sources, a Literature review with a researcher and a citation checker, Verify my references, and a project task's Review changes. It writes screenshots to `workspace-data/research-e2e/` (or `INTERSPACE_SHOTS`). Run it with `node tests/run-ui.cjs research-e2e-ui`.

## Connection

The app finds `codex` on PATH or inside the official ChatGPT/Codex Mac app, and checks its sign-in. Claude Code uses your own `claude` sign-in. Credentials stay in each provider's own store; Interspace never reads or copies them.

Model use counts against your own accounts. Returned token counts are displayed. Money and remaining subscription allowance are never inferred.

## Token budgets

Each task has a **token budget**, 250,000 by default.
- It counts the tokens each provider reports for every model call the task owns:
  - **Codex:** `input + output`.
  - **Claude:** `input + cache creation + cache read + output`.
- **Before each turn:** the app reserves an estimate and refuses a turn that cannot fit.
- **A run that hits the limit** stops as **Budget exhausted**.
- **A call that reports no counts** is charged its estimate and labelled as estimated.

Budgets are tokens only.

## Data and project protection

Tasks, events, usage records, audit logs, research outputs and the research response cache live in `~/Library/Application Support/Interspace`. Research keys and emails live only in the macOS Keychain.

Always refused:
- credential files;
- bypass modes;
- writes outside the task's own copy;
- Interspace's own data.

On restart, unfinished runs become interrupted rather than silently resuming. Existing saved state from earlier versions migrates automatically, with backups beside `state.json`. Unknown future schema versions fail without overwriting the state.

## Developer build

Requires Apple Silicon macOS 13+, Xcode command-line tools and Python 3.9+, plus Codex and/or Claude Code for agent runs. The current app is a local development bundle, ad-hoc signed; it is not a notarized installer or a self-contained Python distribution.

```sh
python3 scripts/build-macos-app.py
```

This creates `dist/Interspace.app` from source. No personal state, credentials or prior reports are bundled.

For isolated development state, the native executable supports `--data-root /absolute/test/directory`. Do not point that directory inside a source project.
