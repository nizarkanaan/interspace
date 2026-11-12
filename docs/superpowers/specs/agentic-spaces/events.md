# Agent event stream (backend → UI)

Status: approved by the user on 2026-11-12, Wave 0A. Provisional fields await the 0B and 0C reconciliation. Conventions and the provisional register are in [README.md](README.md).

The task view streams what an agent does as cards: messages, tool calls and results, diffs, app actions, ask prompts, budget charges, status and errors. Events travel over the existing JSON-lines bridge (backend stdout → Swift → `window.interspaceReceive`). The full `state` projection still exists and stays the source of truth for task lists and status; events carry the detail.

## Transport

Today the backend sends three unsolicited message types (`state`, `auth`, `fatal`) and replies `{id, result}` or `{id, error}`. This contract adds one type:

```json
{"type": "event", "event": Event}
```

Swift forwards it unchanged, like `state`. `app.js` routes `type === "event"` to `ui/stream.js` (owned by 1G).

## Event envelope

```json
{"v": 1, "task_id": "8c1d…", "project_id": "f03a…", "seq": 17,
 "at": "2026-11-11T09:31:02.412Z", "kind": "tool_call",
 "turn_id": "t-3", "item_id": "call_7", "data": {…}}
```

- `seq` is per task, starts at 1 and increases by exactly 1. It is assigned by the backend when the event is persisted, never by the runtime.
- `turn_id` groups the events of one agent turn (the reply to one user message). `null` for task-level events (`status`, `scope`, `answer`).
- `item_id` groups events about one card (a message and its deltas, a tool call and its output and result). `null` when not applicable.
- `data` depends on `kind`. Unknown `kind` values are shown as a plain "Unsupported event" row; the UI never fails on them.
- An event is at most 64 KB of JSON. Larger text is cut, with `truncated: true` and a `blob_id` the UI can fetch with `task_blob`.

## Persistence and replay

- Every event is appended to `tasks/<task_id>/events.jsonl` under Application Support **before** it is emitted. Delta events (`message_delta`, `tool_output_delta`) are persisted too, but may be coalesced: the backend may merge deltas of one item arriving within 100 ms into one event.
- Large payloads go to `tasks/<task_id>/blobs/<blob_id>` (a `uuid4().hex`).
- The UI recovers after a reload or a missed message with:

| Method | Params | Result |
| --- | --- | --- |
| `task_events` | `{task_id, after_seq, limit?}` (`limit` 1–1,000, default 500) | `{"events": [Event, …], "last_seq": 42, "complete": true}` |
| `task_blob` | `{task_id, blob_id}` | `{"blob_id": "…", "text": "…"}` (at most 2 MB) |

- On receiving an event with `seq` greater than `last_seen + 1`, the UI calls `task_events` from `last_seen` before rendering. Duplicate `seq` values are ignored.
- Events are local data. They may contain model text, file paths, diffs and connector content, but never credentials, Keychain replies or environment variables.

## Event kinds

### Who emits what

| Emitter | Kinds |
| --- | --- |
| Runtime adapter (2A, 2B) | `message_delta`, `message` (assistant), `reasoning`, `plan_update`, `tool_call`, `tool_output_delta`, `tool_result` and per-call `diff`, for its own tools only |
| `RunContext` and scheduler (1F) | `status`, `budget`, `scope`, `ask`, `answer`, `error`, `message` (the user's echo), the cumulative `diff`, and every event of connector tools (`tool_call`, `tool_result`, `app_action`) |

### `status`

```json
{"state": "running", "detail": "", "queue_position": null, "reason": null}
```

`state` is one of:

| State | Meaning | Terminal |
| --- | --- | --- |
| `queued` | waiting for a run slot; `queue_position` from 1 | no |
| `starting` | creating the workspace and runtime session | no |
| `running` | the agent is working on a turn | no |
| `waiting_lock` | waiting for a project or resource lock; `detail` names it | no |
| `paused_ask` | waiting for the user to answer an `ask` | no |
| `paused_scope` | the scope was edited and needs approval before the next action | no |
| `idle` | the turn finished; the task waits for the user's next message | no |
| `cancelling` | cancel requested; stopping the runtime | no |
| `completed` | the user closed the task, or a one-shot task finished | yes |
| `failed` | `reason` is an error code (see `error`) | yes |
| `cancelled` | stopped by the user | yes |
| `budget_exhausted` | the token budget cannot fit the next turn | yes |
| `time_limit` | the scope's time limit ran out | yes |
| `interrupted` | the app quit or crashed mid-task; nothing resumes automatically | yes |

A task in a terminal state can be continued only by a new user message with a re-approved scope, which starts a new turn (scheduler.md).

### `message` and `message_delta`

```json
{"kind": "message_delta", "item_id": "msg_4", "data": {"role": "assistant", "text_delta": "I'll start by "}}
{"kind": "message", "item_id": "msg_4", "data": {"role": "assistant", "text": "I'll start by reading the tests.", "final": true}}
```

- `role`: `user` | `assistant`. The user's own message is echoed as a `message` event when the backend accepts it, carrying `client_id` from the request so the UI can replace its optimistic bubble.
- The closing `message` carries the full text and replaces the deltas. Text is Markdown, rendered as text-safe Markdown (no raw HTML, no images loaded from remote hosts).

### `reasoning` and `plan_update` — `PROVISIONAL(0B-6)`

```json
{"kind": "reasoning", "item_id": "rs_2", "data": {"text": "Summary of the agent's reasoning…"}}
{"kind": "plan_update", "data": {"steps": [{"text": "Read failing test", "status": "completed"}, {"text": "Fix parser", "status": "in_progress"}]}}
```

Both are optional to render. `status` is `pending` | `in_progress` | `completed`.

### `tool_call`, `tool_output_delta`, `tool_result`

```json
{"kind": "tool_call", "item_id": "call_7", "data": {
  "call_id": "call_7", "category": "command", "tool": "shell", "app": null,
  "title": "python3 -m unittest tests.test_parser",
  "input": {"argv": ["python3", "-m", "unittest", "tests.test_parser"], "cwd": "."},
  "decision": {"decision": "allow", "rule": "commands.workspace", "scope_version": 2}}}
{"kind": "tool_output_delta", "item_id": "call_7", "data": {"call_id": "call_7", "stream": "stdout", "text": "..F.\n"}}
{"kind": "tool_result", "item_id": "call_7", "data": {
  "call_id": "call_7", "status": "error", "exit_code": 1, "duration_ms": 812,
  "output": {"text": "FAIL: test_dates …", "truncated": false, "blob_id": null}, "error": null}}
```

- `category`: `file_read` | `file_write` | `command` | `network` | `app` | `web_search` | `mcp`. It matches the scope request categories (scope.md), including `web_search` (Codex's hosted search, governed by the scope's `web_search` setting, not by command network) and `mcp` (an MCP server other than Interspace's own, which always asks in v1).
- `tool` is the runtime's tool name (`shell`, `apply_patch`, `read_file`, a connector tool name such as `notion_page_append`, …). `title` is one line for the card, at most 200 characters.
- `input` is the call's arguments, bounded to 8 KB (longer values are cut and marked). The exact fields for commands and file changes are `PROVISIONAL(0B-1)`; the UI shows unknown fields as a key–value list.
- `decision` is the **final** decision that let the call run or stopped it: `allow` or `deny`, never `ask`. The runtime calls `RunContext.authorize` first and emits `tool_call` after it returns. If the policy asked, the `ask` and `answer` events come before the `tool_call`, and `decision.rule` is `ask.allow_once`, `ask.add_to_scope` or `ask.deny`. A denied call gets a `tool_call` and a `tool_result` with `status: "denied"`.
- **Connector tools are the exception:** `RunContext.app_tool` emits all of their events itself — `tool_call`/`tool_result` for reads, a single `app_action` card for writes. The runtime emits nothing for them.
- `tool_result.status`: `ok` | `error` (ran and failed) | `denied` (policy or user refused; it never ran) | `cancelled`. `exit_code` only for commands. `error` is `{"code", "message"}` or `null`.
- Output shown in the card is at most 16 KB; the rest is in the blob.

### `diff`

```json
{"kind": "diff", "item_id": "call_9", "data": {
  "call_id": "call_9", "workspace": {"project_id": "f03a…", "branch": "interspace/task-8c1d", "base_commit": "b6bd066"},
  "files": [{"path": "app/parser.py", "change": "modify", "old_path": null, "additions": 4, "deletions": 1, "binary": false}],
  "patch": "diff --git a/app/parser.py b/app/parser.py\n…", "truncated": false, "blob_id": null,
  "cumulative": false}}
```

- `change`: `add` | `modify` | `delete` | `rename`. Paths are relative to the workspace root, POSIX separators.
- `cumulative: false` is the change made by one call. After each turn the backend also emits a `cumulative: true` diff of the whole workspace against `base_commit` (`call_id: null`), which the task view shows as the task's current change.
- `patch` is unified diff text, at most 48 KB in the event.

### `app_action`

```json
{"kind": "app_action", "item_id": "call_11", "data": {
  "call_id": "call_11", "app": "github", "action": "github.repo.create_issue", "effect": "create",
  "ref": "github:repo:octo/notes", "title": "Create issue \"Track reading list\"",
  "idempotency_key": "8c1d…:call_11", "status": "succeeded",
  "result_ref": "github:issue:octo/notes#41", "url": "https://github.com/octo/notes/issues/41",
  "summary": "Created issue #41 \"Track reading list\"", "error": null}}
```

- Emitted with `status: "pending"` when the write starts and again with the final status: `succeeded` | `failed` | `outcome_unknown` | `denied`. Same `item_id`, so the UI updates one card.
- `outcome_unknown` is shown with the warning that the action may have happened and will not be retried.
- App **reads** by agents appear as ordinary `tool_call`/`tool_result` pairs with `category: "app"`; only writes get an `app_action` card.

### `ask` and `answer`

```json
{"kind": "ask", "item_id": "ask_1f…", "data": {
  "ask_id": "1f…", "call_id": "call_12", "reason": "destructive",
  "title": "Close GitHub issue #38?", "detail": "Destructive app actions always ask, even inside the scope.",
  "request": {Request (scope.md)},
  "options": ["allow_once", "deny"],
  "scope_patch": null, "patched_scope_digest": null, "request_digest": "sha256:…"}}
{"kind": "answer", "item_id": "ask_1f…", "data": {
  "ask_id": "1f…", "decision": "allow_once", "text": null, "scope_version": 2}}
```

- `reason`: `outside_scope` | `destructive` | `network_host` | `escalation` (a command asked to leave the sandbox) | `mcp_tool` | `agent_question` (the agent asked the user something).
- `options` is the subset allowed for this ask:
  - `allow_once`: run this one request;
  - `add_to_scope`: apply `scope_patch` (a scope edit computed by the policy engine, shown to the user), approve the new scope version, then run. Offered only when `scope_patch` is set. Never offered for `destructive`, `escalation` or `mcp_tool`. Options per reason are fixed in scope.md;
  - `deny`: refuse this request; the agent is told it was refused and continues;
  - `text`: only for `agent_question`; the user's free-text reply goes back to the agent.
- Only one `ask` per task is open at a time. While open, the task is `paused_ask`; other tasks keep running.
- An ask has no timeout. Cancelling the task closes it with `answer.decision: "cancelled"`.
- `answer.scope_version` is the scope version in force after the answer (incremented after `add_to_scope`).

UI → backend:

| Method | Params | Result |
| --- | --- | --- |
| `agent_answer` | `{task_id, ask_id, request_digest, decision, text?, scope_digest?}` | `{"accepted": true}` |

`request_digest` is copied from the ask and must match it, so the answer binds the exact request shown. `scope_digest` is required with `add_to_scope` and must equal the ask's `patched_scope_digest`; the UI copies it, never computes it. Any mismatch fails, so the user only approves what they saw.

### `budget`

```json
{"kind": "budget", "turn_id": "t-3", "data": {
  "charge_kind": "reported", "tokens": 18342, "provider": "codex",
  "used": 61204, "reserved": 0, "remaining": 188796, "budget": 250000, "overshoot": 0}}
```

- `charge_kind`: `reserved` (an estimate held before a turn), `reported` (the provider's counts), `estimated` (the turn ended without counts and is charged its estimate). Same meaning as `budget.py`.
- `used`, `reserved`, `remaining`, `overshoot` are the task's ledger totals after this charge.
- When usage arrives is `PROVISIONAL(0B-2)`; the shape does not change.
- Tokens only. No field ever holds money or account allowance.

### `scope`

```json
{"kind": "scope", "data": {"scope_version": 3, "scope_digest": "sha256:…", "change": "approved", "by": "user", "summary": "Added write access to notion:page:1f2e…"}}
```

`change`: `approved` | `edited` (unapproved; the task pauses at its next action) | `amended` (edited and approved in one step through `add_to_scope`).

### `error`

```json
{"kind": "error", "data": {"code": "runtime_exited", "message": "The Codex session stopped unexpectedly.", "recoverable": false, "call_id": null}}
```

Codes: `runtime_unavailable`, `runtime_exited`, `runtime_protocol` (an invalid or unexpected runtime message), `workspace_failed`, `lock_timeout`, `policy_failed` (the policy engine itself failed: fail closed), `audit_failed` (an audit write failed: the action does not run), `budget_exhausted`, `time_limit`, plus any connector error code from connectors.md. `recoverable: true` means the task stays usable (for example one tool failed); `false` precedes a terminal `status`.

## Example stream

The coordinator saves this as `tests/fixtures/events/basic-task.jsonl` (one envelope per line; the `type: "event"` wrapper is omitted in the fixture). 1G builds and tests the stream view against it.

```json
{"v":1,"task_id":"t1","project_id":"p1","seq":1,"at":"2026-11-11T09:30:00.000Z","kind":"scope","turn_id":null,"item_id":null,"data":{"scope_version":1,"scope_digest":"sha256:aa","change":"approved","by":"user","summary":"Write src/ and tests/; read notion:page:n1"}}
{"v":1,"task_id":"t1","project_id":"p1","seq":2,"at":"2026-11-11T09:30:00.100Z","kind":"status","turn_id":null,"item_id":null,"data":{"state":"starting","detail":"","queue_position":null,"reason":null}}
{"v":1,"task_id":"t1","project_id":"p1","seq":3,"at":"2026-11-11T09:30:01.000Z","kind":"message","turn_id":"u1","item_id":"m0","data":{"role":"user","text":"Fix the date parser and note it in the reading log.","final":true,"client_id":"c1"}}
{"v":1,"task_id":"t1","project_id":"p1","seq":4,"at":"2026-11-11T09:30:01.200Z","kind":"status","turn_id":null,"item_id":null,"data":{"state":"running","detail":"","queue_position":null,"reason":null}}
{"v":1,"task_id":"t1","project_id":"p1","seq":5,"at":"2026-11-11T09:30:01.300Z","kind":"budget","turn_id":"u1","item_id":null,"data":{"charge_kind":"reserved","tokens":30000,"provider":"codex","used":0,"reserved":30000,"remaining":220000,"budget":250000,"overshoot":0}}
{"v":1,"task_id":"t1","project_id":"p1","seq":6,"at":"2026-11-11T09:30:03.000Z","kind":"message_delta","turn_id":"u1","item_id":"m1","data":{"role":"assistant","text_delta":"I'll run the parser tests first."}}
{"v":1,"task_id":"t1","project_id":"p1","seq":7,"at":"2026-11-11T09:30:03.500Z","kind":"message","turn_id":"u1","item_id":"m1","data":{"role":"assistant","text":"I'll run the parser tests first.","final":true}}
{"v":1,"task_id":"t1","project_id":"p1","seq":8,"at":"2026-11-11T09:30:04.000Z","kind":"tool_call","turn_id":"u1","item_id":"c1","data":{"call_id":"c1","category":"command","tool":"shell","app":null,"title":"python3 -m unittest tests.test_parser","input":{"argv":["python3","-m","unittest","tests.test_parser"],"cwd":"."},"decision":{"decision":"allow","rule":"commands.workspace","scope_version":1}}}
{"v":1,"task_id":"t1","project_id":"p1","seq":9,"at":"2026-11-11T09:30:04.900Z","kind":"tool_result","turn_id":"u1","item_id":"c1","data":{"call_id":"c1","status":"error","exit_code":1,"duration_ms":880,"output":{"text":"FAIL: test_iso_dates","truncated":false,"blob_id":null},"error":null}}
{"v":1,"task_id":"t1","project_id":"p1","seq":10,"at":"2026-11-11T09:30:08.000Z","kind":"tool_call","turn_id":"u1","item_id":"c2","data":{"call_id":"c2","category":"file_write","tool":"apply_patch","app":null,"title":"Edit src/parser.py","input":{"paths":["src/parser.py"]},"decision":{"decision":"allow","rule":"projects[0].write","scope_version":1}}}
{"v":1,"task_id":"t1","project_id":"p1","seq":11,"at":"2026-11-11T09:30:08.200Z","kind":"diff","turn_id":"u1","item_id":"c2","data":{"call_id":"c2","workspace":{"project_id":"p1","branch":"interspace/task-t1","base_commit":"b6bd066"},"files":[{"path":"src/parser.py","change":"modify","old_path":null,"additions":2,"deletions":1,"binary":false}],"patch":"diff --git a/src/parser.py b/src/parser.py\n--- a/src/parser.py\n+++ b/src/parser.py\n@@ -10,1 +10,2 @@\n-    return date.fromisoformat(text)\n+    text = text.strip()\n+    return date.fromisoformat(text)\n","truncated":false,"blob_id":null,"cumulative":false}}
{"v":1,"task_id":"t1","project_id":"p1","seq":12,"at":"2026-11-11T09:30:08.300Z","kind":"tool_result","turn_id":"u1","item_id":"c2","data":{"call_id":"c2","status":"ok","exit_code":null,"duration_ms":40,"output":{"text":"Applied 1 file.","truncated":false,"blob_id":null},"error":null}}
{"v":1,"task_id":"t1","project_id":"p1","seq":13,"at":"2026-11-11T09:30:12.010Z","kind":"ask","turn_id":"u1","item_id":"a1","data":{"ask_id":"a1","call_id":"c3","reason":"outside_scope","title":"Append to the Notion page \"Reading log\"?","detail":"The scope gives read access to this page, not write.","request":{"category":"app","app":"notion","op":"update","action":"notion.page.append","ref":"notion:page:n1"},"options":["allow_once","add_to_scope","deny"],"scope_patch":{"apps":[{"app":"notion","access":"write","resources":[{"ref":"notion:page:n1","include_children":false}]}]},"request_digest":"sha256:b9da1ab1f88322d30e12e4c809bba534170556b7e4ba08beac673a908b89a1a4","patched_scope_digest":"sha256:bb"}}
{"v":1,"task_id":"t1","project_id":"p1","seq":14,"at":"2026-11-11T09:30:12.020Z","kind":"status","turn_id":null,"item_id":null,"data":{"state":"paused_ask","detail":"Append to the Notion page \"Reading log\"?","queue_position":null,"reason":null}}
{"v":1,"task_id":"t1","project_id":"p1","seq":15,"at":"2026-11-11T09:31:00.000Z","kind":"answer","turn_id":null,"item_id":"a1","data":{"ask_id":"a1","decision":"allow_once","text":null,"scope_version":1}}
{"v":1,"task_id":"t1","project_id":"p1","seq":16,"at":"2026-11-11T09:31:00.010Z","kind":"status","turn_id":null,"item_id":null,"data":{"state":"running","detail":"","queue_position":null,"reason":null}}
{"v":1,"task_id":"t1","project_id":"p1","seq":17,"at":"2026-11-11T09:31:00.100Z","kind":"app_action","turn_id":"u1","item_id":"c3","data":{"call_id":"c3","app":"notion","action":"notion.page.append","effect":"update","ref":"notion:page:n1","title":"Append to \"Reading log\"","idempotency_key":"t1:79c67376b298880dd5c477305a86ffcc","status":"pending","result_ref":null,"url":null,"summary":null,"error":null}}
{"v":1,"task_id":"t1","project_id":"p1","seq":18,"at":"2026-11-11T09:31:01.000Z","kind":"app_action","turn_id":"u1","item_id":"c3","data":{"call_id":"c3","app":"notion","action":"notion.page.append","effect":"update","ref":"notion:page:n1","title":"Append to \"Reading log\"","idempotency_key":"t1:79c67376b298880dd5c477305a86ffcc","status":"succeeded","result_ref":"notion:page:n1","url":"https://www.notion.so/n1","summary":"Appended 1 block to \"Reading log\"","error":null}}
{"v":1,"task_id":"t1","project_id":"p1","seq":19,"at":"2026-11-11T09:31:05.000Z","kind":"message","turn_id":"u1","item_id":"m2","data":{"role":"assistant","text":"Fixed `parse_date` to strip whitespace; tests pass. Noted it in the reading log.","final":true}}
{"v":1,"task_id":"t1","project_id":"p1","seq":20,"at":"2026-11-11T09:31:05.100Z","kind":"budget","turn_id":"u1","item_id":null,"data":{"charge_kind":"reported","tokens":21480,"provider":"codex","used":21480,"reserved":0,"remaining":228520,"budget":250000,"overshoot":0}}
{"v":1,"task_id":"t1","project_id":"p1","seq":21,"at":"2026-11-11T09:31:05.200Z","kind":"status","turn_id":null,"item_id":null,"data":{"state":"idle","detail":"","queue_position":null,"reason":null}}
```
