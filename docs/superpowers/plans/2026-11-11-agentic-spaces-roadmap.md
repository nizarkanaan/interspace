# Agentic Spaces roadmap (parallel execution)

Date: 2026-11-11. Status: approved by the user on 2026-11-11; Wave 0 started. Branch: `interspace/agentic-spaces`, from `main` (`b6bd066`).

## What the user asked for (2026-11-11)

- **Feel like Claude Code or Codex.** Agents get computer access like their *auto* modes, not the bypass-permissions mode.
- **Autonomous within scopes the user specifies.**
- **One app for many spaces.** Connect Notion, GitHub, Google Drive/Docs and Zotero, so you can see and manage everything in Interspace without opening those apps, and without paying extra. The user said this is the point of Interspace and something Codex and Claude cannot do.
- **The app runs several tasks and agents at the same time.**
- **The work itself is planned for parallel sessions, not one task after another.**

It stays single-person and local, with your own accounts and no shared credentials. Per-task token budgets stay, and nothing implies money.

## Rules this changes

These `AGENTS.md` rules change with approval of this roadmap. The text is updated in Wave 0.

| Today | Becomes |
| --- | --- |
| Jobs are text-only. The source checkout is never executed, except fixed Python checks in a sandbox. | Agents read, write and run commands inside a task workspace (an isolated git worktree of the selected project), like Codex's `workspace-write` auto mode. Anything outside the workspace follows the task scope. |
| Each plan needs an exact approval. No external-app writes. | You approve a **scope** once per task: which projects, apps and resources, read or write, commands, network, token budget and time limit. Inside the scope the agent acts without asking. Outside it, the agent pauses that task only and asks. Some things are always refused (credential files, bypass modes, other people's data). |
| One interaction at a time. | Many tasks run at once. Independent assignments in a plan also run at once. Each task keeps its own budget, and writes to the same project are serialised. |

Kept: the exact binding of approvals, now binding the scope, with any edit to the scope invalidating it. Also kept: no automatic retries of failed external writes, a full audit trail, budgets, and the provider-independent UI.

## Architecture

1. **Spaces hub.** One connector per app, under `app/backend/spaces/`. Each connector provides sign-in and status, browse/search/read, defined write actions, and a way to notice changes. Credentials live in the macOS Keychain, through the Swift bridge. The same connector code serves two consumers:
   - the **Spaces UI**, where you browse and edit without any model call or token cost;
   - **agent tools**.
2. **Agent runtime.** A long-lived agent session per task, run by Codex.
   - Preferred route: `codex app-server`, the JSON-RPC protocol the ChatGPT app uses. Interspace receives each approval request and answers it from the scope, which avoids the headless `codex exec` tool cancellation and the bypass flag.
   - Connector tools reach the agent through an MCP server that Interspace itself owns.
   - Claude Code joins later through its existing spec, `2026-11-11-claude-code-provider-design.md`.
3. **Scope and policy engine.** It turns every file, command, network or app action into one of three decisions:
   - **allow**: inside scope;
   - **ask**: pauses that task;
   - **deny**: never allowed.

   Every decision and action goes into a durable audit log. The engine sits beside the budget gate and replaces the per-plan approval for agentic tasks. Today's read-only and Python-fix modes keep working.
4. **Concurrency.** A scheduler runs N tasks at once. Each gets its own worker, cancel token, budget ledger and event stream, with one write lock per project and per app resource. This replaces the global `active` slot, and the UI shows every running task.
5. **Coding-agent UI.**
   - A chat-first task view that streams messages, tool calls, diffs and app actions as cards.
   - Scope chips and a scope editor; inline ask prompts (Allow once, Add to scope, Deny).
   - A keyboard-first composer with `/commands` and `@mentions` of files, pages, issues, documents and papers.
   - A **Spaces** sidebar to browse Notion, GitHub, Drive and Zotero inside Interspace.
   - The Observatory and task desk remain as views.

## No-extra-cost connections (verify in Wave 0)

Model calls keep using your own ChatGPT or Claude sign-in. The connectors use free APIs with your own accounts.

| App | Route | Cost and setup |
| --- | --- | --- |
| **Notion** | Hosted MCP (`mcp.notion.com`), with browser sign-in; or an integration token | Third-party sources say free on all plans. Not yet confirmed from Notion's own docs. |
| **GitHub** | OAuth device flow or a fine-grained token | Free |
| **Google Drive/Docs** | Google APIs with OAuth for desktop apps | Free, but needs a one-time OAuth client in your own Google Cloud project. This is the main setup step. |
| **Zotero** | Local API on `localhost:23119`, enabled in Zotero settings; the free web API key for writes | Free. The local API reads only; whether local writes are now supported is unconfirmed. |

## Waves

Each stream runs in its **own session and git worktree** with a declared set of files it owns. Streams in the same wave run in parallel. A wave starts only after the merges it needs, and the only fully sequential step is the short Wave 0 contract freeze.

### Wave 0: contracts and spikes (3 sessions at once, about 1 day)

| Stream | Output |
| --- | --- |
| **0A Contracts** | Short frozen interface specs that every later stream codes against: the Connector API, the agent event stream (event types and payloads), the Scope schema and policy decisions, and the scheduler and task-runner API. Also the `AGENTS.md` and `docs/engineering.md` boundary updates. |
| **0B Runtime spike** | Prove `codex app-server`: a session, streamed events, approval callbacks, a `workspace-write` sandbox, a tool from an MCP server we own, cancellation, and usage counts. If it fails, fall back to `codex exec` with an Interspace-side tool loop. Records the facts and a tiny prototype; no product code. |
| **0C Auth spike** | Keychain storage through the Swift bridge, and real sign-in for Notion, GitHub, Google desktop OAuth and Zotero, each against your own account and only with your approval. Confirms the free-cost claims above. |

### Wave 1: build in parallel (7 sessions)

| Stream | Owns |
| --- | --- |
| **1A Notion connector** | `spaces/notion.py`, its tests and its UI panel `ui/spaces/notion.js` |
| **1B GitHub connector** | `spaces/github.py`, tests, `ui/spaces/github.js` |
| **1C Google Drive connector** | `spaces/gdrive.py`, tests, `ui/spaces/gdrive.js` |
| **1D Zotero connector** | `spaces/zotero.py`, tests, `ui/spaces/zotero.js` |
| **1E Scope engine and audit** | `scope.py`, `audit.py` and their tests |
| **1F Scheduler and concurrency** | `scheduler.py`; owns `service.py` changes for parallel tasks; concurrency tests |
| **1G Coding-agent UI shell** | Chat stream, cards, scope editor, ask prompts, Spaces sidebar frame, composer. Owns `index.html`, `app.js` and the new `ui/stream.js`. Built against fixture events from the 0A contract. |

Connectors build against the 0A Connector API and fake HTTP fixtures, so they don't wait for each other. The UI builds against fixture event streams.

### Wave 2: integrate (3 sessions at once)

| Stream | Work |
| --- | --- |
| **2A Agent runtime** | `runtime/` adapter for `codex app-server`, the MCP bridge exposing connector tools, and scope enforcement on every tool call, wired into the scheduler. |
| **2B Claude Code provider** | Implementation of the approved spec as a second runtime adapter. |
| **2C UI integration** | Live streams, multiple running tasks, ask prompts answered through policy, Spaces browsing through the real connectors. |

### Wave 3: closeout (parallel)

- One independent whole-feature review per area (runtime and scope, connectors, UI), run as parallel review sessions. Critical and Important findings are fixed test-first.
- Live acceptance with your exact approval: a scoped task that reads a Zotero paper, writes a Notion page and opens a GitHub issue, alongside a second task running at the same time.

## Parallel working rules

- A new worktree per stream, cut from the latest integration point. Owned files are declared in each session's brief. Two sessions never edit the same file in the same wave. A stream that needs a change outside its files asks the coordinator, which is this session.
- Shared files (`service.py`, `index.html`, `app.js`) each have one owner per wave. Other streams register through a one-line import or hook that the owner adds.
- Each stream is test-first, with fake providers and fake HTTP in routine tests, and runs its own suite plus the full backend suite before reporting.
- The coordinator merges each wave into `interspace/agentic-spaces` in dependency order, runs the full verification once per wave, and fans out the next wave.
- Real accounts, real model calls and real app writes happen only with your explicit approval at the time.
- **Cost:** about 7 sessions at once use your Claude usage several times faster than one. The full plan is roughly 13–16 sessions across four waves.

## Decisions still needed

1. Approve this roadmap and the rule changes above.
2. Google: are you willing to create a free OAuth client in your own Google Cloud project? If not, Drive waits or uses a read-only alternative.
3. Session cap: run Wave 1 with all 7 sessions at once, or a smaller cap such as 4?
