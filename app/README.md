# Interspace Mac app

Launch `dist/Interspace.app` with a double-click. It opens its own native window; no HTML file, browser tab or local web server is required. The backend starts and stops with the application.

**Status (2026-11-20): a multi-provider agent workspace with a research reader.** Claude Code and Codex run as agents under one Orchestrator; Gemini comes later.
- **Every task** is a conversation with the Orchestrator. It answers directly, or proposes a team of subagents on Claude and Codex that you approve before anything runs.
- **Review and merge:** each writing subagent commits to its own `interspace/task-…` branch. **Review changes** shows the diff; **Merge** merges it into a branch you pick.
- **Research:** research questions without a project, scholarly sources with your own keys, a corpus of found papers, a citation checker, a report reader, a claim check and a two-agent evidence table. See [Research](#research).
- **Removed:** the Read-only review and Fix & test (Python) modes, project sources, Workspace advice, the Observatory, project conversation and connected apps. Earlier tasks still open read-only, labelled "Earlier task (read-only)".
- **Verification:** the team flow and the research screens are tested with fake command-line tools, recorded fixtures and fake replies, never the network. Live runs with real sign-ins have started, but the claim check, full text and evidence table have not yet been tried live.

## Projects and tasks

**Sidebar.** A **Research | Code** switch follows the page you are on.
- **New research question** or **New code task** starts a task of that kind.
- In Code mode, the **Project** picker and **Add project folder** sit under the button.
- **◀** collapses the sidebar to a narrow **☰** rail, and **☰** opens it again. **⌘\** does the same on a Mac (Ctrl+\ elsewhere) unless you are typing in a field. Interspace remembers the choice. While it is collapsed, **☰** shows how many tasks need you (a question, a scope change or a team to approve), for example **☰ 2**.
- The mode's tasks are grouped under **Needs you**, **Working** and **Done**, each with its state in words: Approve the team, Answer a question, Working, Report ready, Stopped after an error. Subagents are listed under their task, not here.
- **Running now** lists every running task across both modes.
- **Usage** shows each provider's usage limits as the provider reported them during its latest run (percent used, status, reset time), with the time of the reading. It updates only while an agent of that provider runs.

**Task actions.** Right-click a task, or press Shift+F10 or the context-menu key on it, for **Open**, **Stop** (while it works), **Archive** or **Restore**, and **Delete…**.
- A task that is working, or waiting on you, can't be archived or deleted until you stop it.
- **Archived tasks** move to a closed **Archived** list at the bottom of the sidebar, and you can restore them.
- **Delete** is permanent, and asks first. It removes the task, its subagents, its conversation, its outputs and its private project copy.
- **Deleting a code task with a published branch** says how many commits are not merged and offers **Review and merge first**. You choose to delete the branch or keep it. A branch that is checked out in your working copy is never deleted, and each branch deletion is written to the audit log.

**Add project folder** registers a Git repository. The project picker switches among projects; each keeps its own tasks. **Settings → Project details** saves a name, brief, priority and next action locally, without a model call or source edits.

**Settings → Providers** shows each provider's sign-in state, starts a sign-in or shows the command to run, and sets the default provider for each role (Orchestrator, researcher, implementer, reviewer, tester, writer, citation checker). Each role has a Model and an Effort dropdown. Claude lists claude-sonnet-5-5, claude-opus-5-5, claude-haiku-5-5 and claude-fable-5-2, with efforts low to max; Default runs low. Codex's models and efforts come from your signed-in account. If Codex is signed out or does not answer, you type the model instead. Codex's Default effort is the Codex CLI's own default. A saved model your account no longer offers shows as "(not available)", and Save warns about it. A team member takes its role's effort only on the role's provider and model, so changing a member's model resets its effort to Default.

**New task** starts an Orchestrator conversation. Choose **Research question** (no project needed; see [Research](#research)) or **Project task**:
1. Give a title and, for a project task, pick the project. The Orchestrator uses your default provider, model and effort unless you change them here; New task has the same Model and Effort dropdowns.
2. Review the task scope, then choose **Create task**.
3. Approve the scope on the task, then message the Orchestrator.

**Teams.** When the Orchestrator wants help, it proposes a team. Each member has a role, a brief, a provider, a model (a dropdown on the team card) and read or write access. A member that differs from your defaults shows the Orchestrator's one-line reason. You can change any member's provider, model, access and brief, or remove members. Nothing runs until you choose **Approve team**; **Decline** can carry a note back to the Orchestrator.

**Subagents.** Approved members run in parallel. Each works in its own copy of the project, and its card on the task shows its state, tokens and latest activity. **Show activity** opens its full stream. Subagents never appear as separate tasks on the desk; **Running** groups them under their task. Inside a subagent opened from its card, **Back** names its task and returns to it where you left it, with focus on the button that opened the subagent.

**Review changes → Merge.** A writing subagent's changes are committed to its own `interspace/task-…` branch. **Review changes** lists the changed files and the diff. **Merge** merges the branch into the branch you pick, in a temporary worktree, and only if the branch is still the one you reviewed. Interspace never changes your checked-out branch or working files: to merge into the branch you have checked out, run `git merge` there yourself. Conflicts are reported, and nothing is forced.

Inside the scope an agent acts without asking. Outside it, that task alone pauses and asks: Allow once, Add to scope, or Deny. Read-only members and the Orchestrator can never write. Up to 4 agent runs work at once, subagents included; further runs queue.

## Research

Interspace is a research environment that still codes. A **research question** needs no project: agents search scholarly sources, follow citations, and write a report. The app keeps track of every paper they found, lets you check every cited claim, and fills an evidence table with two independent models.

**Sources.** Semantic Scholar, OpenAlex, arXiv, Crossref and Unpaywall. **Settings → Research sources** lists each one with what it needs, its status, **Test**, **Remove** and a link to get a free key:
- Semantic Scholar and OpenAlex: an optional API key, which raises your allowance.
- Crossref: an optional email; Unpaywall: a required email. The email goes to that service with each request, as the contact address it asks API users for.
- arXiv: nothing to enter.

Keys and emails are your own. They are kept in this Mac's Keychain, are never shown again after you save them, and never reach agents, logs, events or git. Research calls use no tokens; each task shows, per source, the requests it sent and the answers that came from the cache, never money.

**Scope.** **New task → Research question** offers **Literature review**, **Related work** and **Verify my references**.
- The scope has research sources only: no project, files, commands or network.
- Each source is **Allow**, **Ask** (each call waits for you) or **Off**.
- **Open-access full text** is a separate permission for downloading free copies of papers from publishers' own sites. New research tasks have it on **Ask**; for an older task, add it in **Edit scope**.
- Every team member only reads.

**The split reader.** In a window 1100px or wider, a research task shows the conversation on the left and the results on the right. Drag the divider, or use its arrow keys, to resize them; double-click it to reset.
- **Report.** `report.md` at reading width.
  - Each `[n]` links to its reference, and each reference shows the citation checker's verdict: Verified, Retracted, Not verified, Not checked, or Not found by the agents (possibly cited from memory).
  - **Check claims** splits the report into cited sentences and asks the Orchestrator for an independent checker on the other provider. The checker judges each sentence against the cited paper's abstract and, when an open-access copy exists, its most relevant passages: Supported, Partly, Not supported or Can't tell.
  - Each verdict carries a reason and a quote, and the quote must appear in the source. Citations take their verdict's colour, and **Claims to look at** lists the problems first.
- **Corpus.** Every paper the agents and subagents found, with duplicates merged, and each one's verdict and where it was found. It has search, filters (Checked, Not checked, Open access) and sorting. Agents can read the corpus too.
- **Evidence.** Choose columns, from presets or your own, and rows: the cited papers, or every checked paper.
  - **Fill table** asks for two extractors, one on Claude and one on Codex. Each fills the table alone, with a quote for every value.
  - The table fills the pane. Each cell shows its value and a short status word: **Agree**, **Check**, **Disagree**, **Not reported**, **Waiting** or **Decided**. The longer wording ("Agree, check the number", "Decided by you") is in the cell details. A disagreement shows both values on two lines, "Claude: x" and "Codex: y". Papers are labelled like "Zhang et al. 2022"; hover for the title. **Needs you** filters to what needs a decision.
  - Click a cell, or press Enter on it, to open **Cell details** beside the table: the paper, the column, and each value with its quote. A disagreement adds **Use Claude's**, **Use Codex's** and **Type my own**; a decided cell shows your value with **Undo**. Esc or **×** closes it (Esc while typing your own value only stops typing).
  - **Export CSV** saves `evidence.csv`.
- **Scope and outputs.** Status, scope and outputs.

**Focus.** In the split reader (a window 1100px or wider), **Focus** on the results tab row hides the conversation and the sidebar so the results use the whole window. A narrower window has no Focus. **Exit focus** or Esc brings them back (Esc closes an open cell drawer first). If a team, a question or a scope needs you, a banner says so, with **Go to conversation**.

**Simple and Detailed.** The conversation shows **Simple** by default: subagents and teams are one-line rows with **Details ▸**, and an opened card folds back with **Hide details ▾**; a team to approve is a short card with **Approve team**, **Decline** and **Edit team**, and orchestration calls stay hidden unless they fail. Questions for you, approvals and errors always show in full. Switch with the **Simple | Detailed** switch in the conversation header (the current view is filled), or under **Settings → Conversation display**, which also sets **Thinking** and **Paper searches** (Summary, Full or Hidden) and holds the switches **Commands and file changes**, **Citation reports**, **Plans** and **Status notes**.

In a research task, Simple reads as a chat: each turn is your message, one work line for the agents' work, then the reply. Code tasks, the **Running** view and a subagent's **Show activity** keep the Simple above.
- **The work line** counts what it folded, for example "Searched 3 sources 2 times · 3 papers · saved report.md · 8 steps", and starts with "Working ·" and the newest search while the turn runs. It has **Open** for up to two finished subagents, and **Details ▸** puts the folded steps back in place, in order, followed by **Hide details ▴**.
- It folds ok and running research calls, reasoning, token and settled scope rows, an answered team, subagents that finished cleanly, a citation report with every reference verified, and an interim agent message ("I'll start by searching…") once a later one exists in the same turn. Questions, open teams, errors, failed calls, status rows, scope approvals and subagents that are still running or ended badly never fold.
- **Earlier messages.** In an earlier turn, your message or the reply over 600 characters shows its first lines, then **Show whole message ▾** or **Show whole reply ▾**; **Show less ▴** cuts it again. The newest turn, a reply still being written, and a message still sending or not sent are never cut.
- **Citations.** A citation report with a problem is one warn line, such as "Citations: 2 of 3 verified · 1 mismatch", ending in "retracted: do not cite" when a reference was retracted. **Show citation report ▸** opens a brief card of the problem rows, and on the research task itself **Open Corpus ›** switches to the Corpus tab.
- Beside the switch, a note says how many steps Simple folded ("16 steps folded"). It is hidden in Detailed, when nothing folded, and in Focus. The display settings still decide what shows and is counted; Simple only decides how it is folded.

In a narrower window the same parts are tabs: **Conversation**, **Report**, **Corpus**, **Evidence** and **Details**.

**Reports.** `report.md` changes only when the Orchestrator saves a finished report with `save_report`. The app refuses anything without a title heading and a numbered References list, so a status reply can never replace your report. `references.bib` holds the references the checker verified, marks mismatched ones in a comment, and leaves out not-found and retracted ones.

**Full text.**
- **arXiv papers** are read from arXiv's own pages, under the arXiv permission.
- **Any other open-access copy** is downloaded only with the full-text permission, and only:
  - over https;
  - from public addresses, checked on every redirect;
  - up to 10 MB.

  PDF text is read by macOS PDFKit, and the downloaded file is deleted after reading.

**What is shown.** Research text is always shown as plain text, links appear only for https addresses, and a link's real host is shown after its text.

**Browser end-to-end.** `tests/research-e2e-ui.mjs` drives the real backend (`tests/e2e/research_backend.py`) over JSON lines with fake agent runtimes, research HTTP answered from `tests/research/fixtures/`, and a fake Swift side (an in-memory Keychain and save panel). Run it with `node tests/run-ui.cjs research-e2e-ui`. Screenshots go to `workspace-data/research-e2e/`, or `INTERSPACE_SHOTS`.

## Connection

The app finds `codex` on PATH or inside the official ChatGPT/Codex Mac app, and checks its sign-in. Claude Code uses your own `claude` sign-in. Credentials stay in each provider's own store; Interspace never reads or copies them.

Model use counts against your own accounts. Returned token counts are displayed. Usage limits are shown only as each provider reports them; money is never shown, and no limit is ever estimated.

## Token usage

New tasks have **no token limit**; you are never asked for one. Each task shows the tokens its model calls used:
- **Codex:** `input + output`.
- **Claude:** `input + cache creation + cache read + output`.
- **A call that reports no counts** is charged its estimate and labelled as estimated.

Tasks saved by earlier versions keep the limit they were created with: a turn that cannot fit is refused, and a run that hits it stops as **Budget exhausted**. Usage is tokens only, and money is never shown.

## Data and project protection

Tasks, events, usage records, audit logs, research outputs (`report.md`, `references.bib`, `evidence.csv`), each research task's corpus, claim check, evidence table and full-text cache, and the research response cache live in `~/Library/Application Support/Interspace`. Research keys and emails live only in the macOS Keychain.

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

## License

[MIT](../LICENSE). Third-party files keep their own licenses; see [docs/third-party](../docs/third-party/README.md).
