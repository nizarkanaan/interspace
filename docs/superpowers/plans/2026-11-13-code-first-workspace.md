# Code-first workspace roadmap (parallel execution)

Date: 2026-11-13. Status: **superseded on 2026-11-15, never approved.** The user dropped the connected apps in favour of a multi-provider agent workspace (Claude, Codex and Gemini under one orchestrator). Kept for the record. Branch: a new `interspace/code-first-workspace`, cut from `interspace/agentic-spaces` (`6058265`).

## What the user asked for (2026-11-13)

- **Code first.** The centre of Interspace is coding in projects with AI agents and talking to them like Codex.
- **Different from Codex.** Codex agents can already reach Notion, Zotero and the rest through MCP. Interspace is different because **the user** works in those apps inside Interspace, next to the code and the agents. The built-in app views are the product, not an agent plug-in.
- Same idea as Macro (macro-inc/macro, a unified team workspace), but single-person, local and code-first. Macro is AGPL-3.0: we take **ideas only, no code**.

Unchanged from the agentic-spaces roadmap:
- single-person and local;
- your own accounts;
- scopes and the auto-mode policy;
- token budgets, never money;
- real sign-ins, model calls and app writes only with your approval at the time.

## The product in one picture

```
┌ Sidebar ─────────┬ Pane 1 ──────────────────┬ Pane 2 ───────────────┬ Pane 3 ─────────────┐
│ Projects         │ Thread: "Fix #12 import" │ GitHub issue #12      │ Zotero: Smith 2024  │
│  interspace      │  agent messages, tool    │  body, comments,      │  PDF + notes        │
│   ● Fix #12      │  calls, diffs, asks      │  "Threads using this" │  "Threads using     │
│   ○ Refactor UI  │  composer: @#12 @Smith   │  [Start thread here]  │   this"             │
│ Spaces           │  [Review changes]        │                       │                     │
│  Notion GitHub   │                          │                       │                     │
│  Drive  Zotero   │                          │                       │                     │
└──────────────────┴──────────────────────────┴───────────────────────┴─────────────────────┘
```

Four pieces:

1. **Threads (the Codex part).**
   - A project holds many agent threads. Each thread is one agent session in its own git worktree and branch.
   - Threads stream messages, tool calls and diffs, and ask when they need approval. Many run at once.
   - Each thread ends in **Review changes**: a diff, then merge into your branch or open a pull request.
2. **Built-in app views (the difference).**
   - Notion, GitHub, Google Drive and Zotero become real places to work: browse, search, read, edit and comment.
   - No model call and no tokens are involved.
   - Today the panels are mostly sign-in screens.
3. **Links.**
   - Anything can be @mentioned in a thread: a file, page, issue, pull request, doc or paper.
   - Interspace records what each thread **mentioned, used, changed and created**, in both directions.
   - Every view shows "Threads using this" and has **Start thread here**.
   - The chain stays connected: issue, thread, diff, PR, Notion changelog.
4. **Panes.**
   - Up to three side-by-side panes, with a `⌘K` switcher across threads, files and every app's resources.
   - A thread and the paper or spec it works from sit side by side.

## What already exists and is reused

| Piece | Where | Reused for |
| --- | --- | --- |
| Connectors with `browse`, `search`, `read`, `write`, `changes` and journaled writes | `app/backend/spaces/*.py` | All app views; writes stay journaled and idempotent |
| Resource refs (`app:kind:id`) | `spaces/base.py` `make_ref`/`parse_ref` | Link store keys and @mentions |
| Codex and Claude runtimes, MCP bridge, scope engine, scheduler | `app/backend/runtime/`, `scope.py`, `scheduler.py` | Threads |
| Agent stream, cards, composer, scope chips | `app/ui/stream.js`, `agent*.js`, `composer.js`, `scope.js` | Thread pane |

Write actions available today:
- **Notion:** create page, append, update properties, comment, archive.
- **GitHub:** create issue, comment, update, close, comment on a pull request, create a pull request.
- **Drive:** create doc, append, replace text, rename, trash.
- **Zotero:** create item, add note, add tags, add to collection, trash.

## Gaps to close

- **Codex sign-in.** Nothing signs in to the app-owned `CODEX_HOME`, so Codex threads fail with `runtime_unavailable`.
- **Merging a thread's changes back.** `workspace_merge` is not built.
- **Restart.** Threads do not resume after an app restart. They become "interrupted".
- **Thin app views.** Each panel needs a real reader and editor.
- **Old surfaces.** The task desk's plan-and-approve flow, the Observatory and Workspace advice are not code-first. See decision 2.

## Ideas taken from Macro (no code)

- **Worktree per session.**
  - A new worktree starts from a fresh fetch of the base branch, and the session ID fixes its path and branch.
  - Running the same session again reuses its edits.
  - The user's working branch is never pulled into.
- **Session resume.** After a restart, replay the native agent transcript and reattach if the agent still runs.
- **Change summaries.** Each file's status and line counts, cut to a size budget, so long diffs stay reviewable.
- **Two-way links.** A link is stored as a graph edge, so every object can show what refers to it.
- **Split panes and a keyboard-first switcher.**

## Waves

Same working rules as the agentic-spaces roadmap:
- a worktree per stream, each owning declared files;
- test-first, with fake HTTP and fake providers;
- the coordinator merges each wave and runs full verification.

### Wave 0: contracts (coordinator plus 1 spike, about half a day)

| Stream | Output |
| --- | --- |
| **0A Contracts** | Short frozen specs under `docs/superpowers/specs/code-first/`: thread and worktree lifecycle (create, run, review, merge or PR, archive, resume); link store schema and link kinds; pane and layout model with `⌘K` search results; view contract for app views. |
| **0B Codex sign-in spike** | Sign in to the app-owned `CODEX_HOME` with the CLI's device flow, run one thread turn, record the facts. Real sign-in only with your approval at the time. |

### Wave 1: build in parallel (6 sessions)

| Stream | Owns |
| --- | --- |
| **1A Threads backend** | `threads.py` and `worktree.py`, with tests. A worktree and branch per thread (`interspace/thread/<id>`); change summary; merge into a chosen local branch as an explicit action; open a PR through the GitHub connector; resume after restart; archive. |
| **1B Pane shell** | `index.html`, `app.js`, new `ui/layout.js` and `ui/switcher.js`. Up to 3 panes; open in split; `⌘K` across threads, files and app resources (through each connector's `search`); keyboard focus between panes. |
| **1C Notion and Drive views** | `ui/spaces/notion.js`, `ui/spaces/gdrive.js`, new `ui/render-doc.js`. Read blocks and docs as formatted text; edit with the existing write actions; comments; page properties. |
| **1D GitHub view** | `ui/spaces/github.js`, new `ui/render-diff.js`. Issues and pull requests: list, filter, read, comment, close; PR diff view, shared later with thread review. |
| **1E Zotero view** | `ui/spaces/zotero.js`. Library, collections, item details, notes, tags; PDF viewer for attachments (see decision 4). |
| **1F Link store** | `links.py` and tests. Record links from @mentions and from every journaled tool call; backlinks query; "Start thread here" prefill (resource attached, scope chip suggested). |

### Wave 2: integrate (3 sessions)

| Stream | Work |
| --- | --- |
| **2A Thread experience** | Thread list per project in the sidebar; thread pane on the existing stream; **Review changes** pane using `render-diff.js`; merge and PR buttons; resume on launch. |
| **2B Links in the UI** | @mention picker across apps; "Threads using this" in every view; Start thread here; links shown as chips in thread messages. |
| **2C Runtime and service wiring** | Threads on the scheduler; Codex sign-in in Settings; worktree cleanup; the old task desk handled per decision 2. |

### Wave 3: closeout (parallel)

- Independent reviews of three areas: threads and worktrees, app views and links, panes and UI. Critical and Important findings are fixed test-first.
- Live acceptance, with your approval at the time:
  1. From a GitHub issue in Snack Picker, start a thread.
  2. Open a Zotero paper and a Notion spec beside the thread, and @mention both.
  3. The agent edits code in its worktree.
  4. Review the diff and open a PR.
  5. Append a changelog line to the Notion page.
  6. A second thread runs in parallel the whole time.
  7. Every object shows its backlinks.
- Fix the two timing flakes:
  - `test_known_usage_survives_invalid_final_response`;
  - `test_backend_quit_with_closed_output_stops_active_provider`.

**Size:** about 12 sessions across four waves, with up to 6 at once in Wave 1. Parallel sessions use your Claude usage several times faster than one.

## Rule changes

| Today | Becomes |
| --- | --- |
| Agent work happens in an isolated workspace; `workspace_merge` is unbuilt. | Each thread has its own worktree and branch. Changes reach your checkout only through an explicit **Merge** that you press, or through a pull request. |
| App views mainly connect and browse. | App views read and write with the existing journaled actions. Each user edit is your own click, so there is no scope prompt and no tokens. |

Kept: scopes for agents, the audit log, budgets, Keychain credentials, Sample Project read-only, and no Claude co-author trailers or `claude/` branches.

## Decisions needed

1. Approve this roadmap and the two rule changes.
2. **Old surfaces.** For the task desk (plan and approve), Observatory and Workspace advice, choose one:
   - **(a)** keep them reachable under a "More" menu;
   - **(b)** hide them behind a setting;
   - **(c)** remove them.

   Recommended: (a) now and (c) later.
3. **Merge target.** Should a thread merge into your current branch, or always go through a pull request? Recommended: you choose per thread, with the pull request as the default.
4. **Zotero PDFs.** To show attachments, Interspace reads your Zotero storage folder (usually `~/Zotero/storage`). Allow read-only access to that folder for the view? Agents still need a scope grant.
5. **Session cap** for Wave 1: all 6 sessions at once, or 4?
6. **Google:** the OAuth client is still deferred. Until it exists, the Drive view only shows a sign-in screen.
