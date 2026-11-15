# Agentic Spaces: frozen interface contracts (Wave 0A)

Date: 2026-11-11. Status: approved by the user on 2026-11-12. The 0B fields were reconciled in Wave 2A (2026-11-12); 0C fields await their reconciliation. Roadmap: `docs/superpowers/plans/2026-11-11-agentic-spaces-roadmap.md` (approved 2026-11-11).

These contracts let the seven Wave 1 streams build in parallel without talking to each other. Each stream codes against the shapes here, with fakes for everything it does not own. Nothing here exists in code yet.

| Contract | File | Main producers | Main consumers |
| --- | --- | --- | --- |
| Connector API, Keychain bridge, fake-HTTP harness | [connectors.md](connectors.md) | 1A–1D | 1F (protocol), 1G (Spaces panels), 2A (agent tools) |
| Agent event stream (backend → UI) | [events.md](events.md) | 1F, 2A, 2B | 1G, 2C |
| Scope schema, policy decisions, audit record | [scope.md](scope.md) | 1E | 1F, 2A, 1G (scope editor, ask prompts) |
| Scheduler, task runner, runtime adapter, locks | [scheduler.md](scheduler.md) | 1F | 2A, 2B, 2C |

## User decisions behind these contracts (2026-11-11)

Asked during Wave 0A and answered by the user:

1. **Code changes land on a branch the user merges.** Each agentic task works in its own isolated checkout of the project (a local `git clone`, see scope.md) and its work appears in the user's repository as its own `interspace/task-…` branch. Interspace never writes the user's checked-out branch or working files. The user merges, or presses an explicit **Merge** action.
2. **Destructive app actions always ask.** Delete, archive, close, trash and whole-document replacement pause the task and ask, even inside a write scope. Creates and edits inside scope run without asking.
3. **Network for commands defaults to ask per host.** Off by default; the first request to a host not in the scope pauses and asks. Connected apps go through Interspace connectors and do not need command network access.
4. **At most 4 tasks run at once by default**, changeable in Settings. Further tasks queue.

The assistant made the remaining design choices. Each is marked where it appears, and the coordinator may revise them before freeze.

## Conventions shared by every contract

- **Python 3.9 compatible, standard library only.** The app supports Apple's Python 3.9. No `match`, no `X | Y` annotations evaluated at runtime, no new third-party packages.
- **Plain JSON-compatible dicts** cross module boundaries, validated by a function at the boundary, as in today's `tasks.validate` and `budget.validate`. No shared base classes except the error types and `spaces/base.py` defined in connectors.md.
- **Errors users may see subclass `ValueError`.** The existing request loop in `service.main` shows `str(error)` for `ValueError` and replaces anything else with a generic message. Messages must be safe to show: no tokens, no file contents, no response bodies.
- **Identifiers** are opaque strings. New identifiers are `uuid.uuid4().hex` (32 lowercase hex characters), like existing task IDs. Runtime-originated identifiers (`call_id`, `turn_id`, `item_id`) are passed through unchanged after a check that they are non-empty strings of at most 128 characters.
- **Times** are ISO 8601 UTC strings with milliseconds and a `Z` suffix: `"2026-11-11T09:30:00.000Z"`. Durations are whole milliseconds (`_ms`) or seconds (`_s`), as named. Python 3.9's `datetime.fromisoformat` rejects `Z`, so every module formats with `time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(t)) + '.%03dZ' % int(t % 1 * 1000)` and parses by replacing a trailing `Z` with `+00:00` first. These two helpers live in `spaces/base.py` as `iso_time(t)` and `parse_time(text)`, and other modules import them from there.
- **Clocks.** Injected `clock` arguments return wall-clock epoch seconds as a float (`time.time`). Durations and time limits are measured with `time.monotonic` inside the scheduler only.
- **Resource references** have one string form: `<app>:<kind>:<id>`, for example `notion:page:1f2e…`, `github:issue:octo/repo#12`. See connectors.md.
- **Contract version.** Every persisted or streamed record carries `"v": 1`. A consumer rejects an unknown `v` instead of guessing.
- **No money.** Budgets are tokens only. No contract field holds prices, costs or remaining account allowance.
- **Private content stays local.** Events and audit records live in Application Support, never in git or logs. Secrets never appear in any event, audit record, state projection or error message.

## Provisional fields

Wave 0B (the `codex app-server` runtime spike) and Wave 0C (the connector auth spike) run in parallel with this work. Fields that depend on their findings are marked in the text as:

- `PROVISIONAL(0B-n)`: depends on the runtime spike;
- `PROVISIONAL(0C-n)`: depends on the auth spike.

A provisional field keeps its name and position. Only its value set, timing or transport may change when the coordinator reconciles it. Wave 1 streams code against the shape as written and keep the dependent logic behind one function, so a reconciliation edits one place.

| ID | Question for the spike | Where it lands | Assumption until reconciled |
| --- | --- | --- | --- |
| 0B-1 | Exact shape of app-server approval requests for commands and file changes (argv vs. string, cwd, paths, patch) | scope.md request kinds; events.md `tool_call.input` | Command approvals carry `argv` or a shell string plus `cwd`; file-change approvals carry the changed paths. |
| 0B-2 | Usage granularity: per model call, per turn, or streamed | events.md `budget`; scheduler.md budget hooks | Usage arrives at the end of each turn with Codex's `input_tokens`/`output_tokens`. |
| 0B-3 | Cancellation: does `turn/interrupt` stop running commands, and how fast? | scheduler.md cancel | Interrupt stops the turn and its child processes within 10 s; otherwise the session process group is killed. |
| 0B-4 | How Codex reaches an MCP server Interspace owns, and whether MCP tool calls raise approval requests | scheduler.md runtime; connectors.md tool descriptors | Codex spawns an Interspace stdio MCP server; it reaches the backend through a Unix socket in Application Support; Interspace authorizes every tool call itself. |
| 0B-5 | Can the sandbox enforce network per host, or only on/off? | scope.md network | Only on/off. Sandbox network stays off; a command needing network asks, and an approved command runs with network on **to every host** for that command only. The ask says so. `allow_hosts` is then unused. If 0B finds per-host control, the per-host rules in scope.md apply as written. |
| 0B-8 | Can the sandbox deny **reads** of paths outside the workspace (credential directories, other tasks' clones, Interspace app data)? | scope.md always-deny | No. Codex `workspace-write` lets sandboxed commands read any file the user can read. `always_deny.credentials` and `always_deny.app_data` are then enforced for agent file tools and visible argv only, not for every byte a command reads. The coordinator must tell the user this before Wave 2 if 0B confirms it. |
| 0B-6 | Are reasoning summaries and plan (to-do) updates streamed? | events.md `reasoning`, `plan_update` | Both exist and are optional to render. |
| 0B-7 | Is a per-task model or provider choice exposed by app-server? | scheduler.md `RunContext.model` | One default model; field reserved. |
| 0C-1 | Keychain bridge: item class, service name, access prompts, and whether the backend may block waiting for a reply | connectors.md Keychain bridge | Generic password items, service `app.interspace.spaces`, account = app name; replies within 10 s. |
| 0C-2 | Per-app sign-in method | connectors.md sign-in steps | Notion: browser OAuth to hosted MCP, else an integration token. GitHub: device flow. Google: desktop OAuth with loopback redirect. Zotero: local API check, plus a web API key for writes. |
| 0C-3 | OAuth redirect: a single-use loopback listener in Python, or `ASWebAuthenticationSession` in Swift | connectors.md `browser` step | Single-use listener on `127.0.0.1`, random port, closed after one redirect or 5 minutes. |
| 0C-4 | Zotero: can the local API write? | connectors.md Zotero action set | No. Writes use the web API key; without one, Zotero is read-only. |
| 0C-5 | Notion: hosted MCP or REST API as the data route | connectors.md | Either is allowed behind the same Connector API; the connector hides the route. |

**0B reconciliation (Wave 2A, 2026-11-12).** Every `0B` marker in these contracts is replaced by the decided behaviour, built in `app/backend/runtime/` (`codex.py`, `mcp_bridge.py`):

- **0B-1** Approval shapes: commands carry a shell string, unwrapped from Codex's `/bin/zsh -lc` wrapper; file-change approvals carry no paths, so paths come from the started `fileChange` item. Full mapping in scope.md, Requests.
- **0B-2** Usage arrives after every model request; the runtime reports the turn's cumulative usage each time, so the budget can stop a turn mid-way.
- **0B-3** `turn/interrupt` stopped a live turn in about 0.1 s. The 10 s kill backstop stays; kill also stops the MCP bridge.
- **0B-4** Connector tools reach the provider through the Interspace MCP bridge: a stdio relay to a private Unix socket in the backend; Interspace authorizes every call in `RunContext.app_tool` (scheduler.md, "MCP bridge API").
- **0B-5** Network is on/off only (no managed proxy), as assumed: a command that needs network asks for any host, for that command only.
- **0B-6** Reasoning summaries and plan updates are streamed and emitted.
- **0B-7** A per-task model is supported: the task row's `model` (an id from the signed-in account's model list) is passed to `thread/start`; otherwise the provider default.
- **0B-8** Confirmed: the sandbox does not deny reads by default. The runtime's profile denies credential folders, the app-owned `CODEX_HOME` and Interspace's own data except the task workspace; other readable files stay readable (scope.md). The coordinator tells the user before agent tasks ship.
- Beyond the register: the runtime launches Codex with an app-owned `CODEX_HOME`, so agent tasks need a one-time Codex sign-in into that home (not built in 2A), and it disables Codex features that act outside the sandbox or load outside code (computer use, browser use, ChatGPT apps, plugins, hooks, sub-agents, shell snapshots).

## Shared-file ownership in Wave 1

The roadmap gives each shared file one owner per wave. These contracts add four small files that several streams import. The **coordinator** creates them verbatim from this spec when it fans out Wave 1, before any stream starts, and owns them for the wave:

- `app/backend/spaces/__init__.py`: the app registry (connectors.md);
- `app/backend/spaces/base.py`: error types, `Http`, `Credentials`, `MemoryJournal`, standard tool generation (connectors.md);
- `tests/spaces/fakehttp.py`: the fake-HTTP harness (connectors.md);
- `tests/fixtures/events/basic-task.jsonl`: the example event stream in events.md, saved one event per line.

Other ownership, in addition to the roadmap table:

- **1F** also owns `tasks.py` (new `agent` mode) and `budget.py` (provider-aware charge rule, new ledger fields), because both change with concurrency.
- **1E** owns `app/backend/scope.py`, `app/backend/audit.py` and the durable write journal in `audit.py`.
- **`app/macos/main.swift`** (Keychain bridge, `open_url`, the `bridge_hello` handshake, new allowed methods) has no Wave 1 owner in the roadmap. The coordinator must assign it before Wave 1 starts; the recommendation is a small Wave 1 stream, or 1F, built from the 0C spike's findings. Until it merges, the backend never sends a Keychain message (connectors.md handshake), so an old shell cannot leak a secret to the WebView.

**Coordinator ruling (2026-11-12, Wave 1 start).** The user chose to start Wave 1 with four streams (1A, 1E, 1F, 1G); 1B–1D start after 1A merges. So `app/backend/spaces/__init__.py`, `app/backend/spaces/base.py` and `tests/spaces/fakehttp.py` are owned by **1A** for this round. 1A writes them exactly as connectors.md specifies, with their own tests. 1B–1D then reuse them unchanged. The coordinator created `tests/fixtures/events/basic-task.jsonl`. `app/macos/main.swift` (Keychain bridge, `open_url`, `bridge_hello`, new allowed methods) is owned by **1F**.

**Coordinator ruling (2026-11-12, asked by 1E).** These are additive and optional; no existing shape changes.
- App requests to `scope.decide` may carry `parents`: a list of refs, nearest first, as the connector reports them. `RunContext.app_tool` (1F, and the real adapter in 2A) fills it when the connector knows the ancestry. Without it, `include_children` matches only the exact ref, so a child resource asks instead of being allowed.
- `scope.decide` gains optional keyword arguments `app_data`, `home` and `temp_roots`. They default to `~/Library/Application Support/Interspace`, `~` and `()`, so tests and the `Application` data directory can pass their own.
- `scope.validate(document, *, project_ids=None)` checks registered projects when `project_ids` is given.
- `Journal.begin` returns the stored record, or `None` after durably recording `started`, and never raises. `spaces.base.journaled_write` (1A) alone decides replay, `OutcomeUnknown` and `InvalidRequest` from that record. `FileJournal` (1E) and `MemoryJournal` (1A) both behave this way.

**Coordinator rulings (2026-11-12, after the first four Wave 1 streams merged).**
- **Task rows** carry `mode` (`review`, `python_fix` or `agent`), as `task_summaries` already does. The UI identifies agent tasks by `mode == "agent"`.
- **Default scope.** A new method `scope_default {project_id}` returns a validated default scope document for a new agent task, without creating anything. The new agent task form calls it, lets the user edit the scope, then calls `agent_create` with that scope. This is built in Wave 2C: backend and UI together.
- **Mentions.** For v1, `@mentions` are plain text in the message, as `@<ref>` for app resources and `@<path>` for workspace files. The runtime passes them through unchanged; no structured encoding.
- **Opening an agent task** loads history with `task_events` and the scope with `scope_get`; it does not need `select_task`.
- **Answer path.** `scheduler._amend` repeats the checks in `scope.apply_answer` instead of calling it. They are equivalent today. Wave 2 should make the scheduler call `scope.apply_answer`, so the checks live in one place.

A stream that needs a change to a contract asks the coordinator. It never changes the shape locally.
