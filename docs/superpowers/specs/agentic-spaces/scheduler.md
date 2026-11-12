# Scheduler, task runner and runtime adapter

Status: approved by the user on 2026-11-12, Wave 0A. Provisional fields await the 0B and 0C reconciliation. Conventions and the provisional register are in [README.md](README.md).

1F owns `app/backend/scheduler.py` and the `service.py` changes for parallel tasks. 2A (Codex app-server) and 2B (Claude Code) implement the runtime adapter against this file. 1F tests with a fake runtime; it never needs a real provider.

## What changes from today

Today `Application` has one `worker` thread, one `cancel` event and one global `state['active']` slot: one interaction at a time.

After Wave 1:

- **Agentic tasks** (new task mode `agent`) run through the `Scheduler`, up to `max_running` at once (default 4, the user's decision 4; range 1–16; Settings → `scheduler_settings`). Each has its own thread, cancel event, deadline, budget ledger view and event stream.
- **Legacy interactions** (project chat, Workspace advice, read-only plans, Python fix runs, report revisions) keep their exact current code paths and approvals. They share **one legacy slot**: `state['active']` and its fields keep today's meaning, so `team.py`, `change_team.py` and the existing UI keep working. A running legacy interaction counts as one of the `max_running` slots.
- **Spaces UI requests** never take a run slot. They run on a separate pool of 4 threads, so browsing never blocks behind a task. Scope and `agent_*` requests are answered from a third small pool and never wait for a running turn. See connectors.md for the stdin reader thread that feeds these pools.
- Recovery on restart: every agentic task that was `starting`, `running`, `waiting_lock`, `paused_*` or `cancelling` becomes `interrupted`, with a `status` event. Nothing resumes. Worktrees and branches stay. `budget.recover` charges open reservations their estimate, as today. An `idle` task stays `idle`; the next user message starts a new runtime session.

## Public state

The `state` projection gains, next to the unchanged `active`, `active_project_id`, `active_task_id`, `active_run_id`:

```json
"scheduler": {
  "max_running": 4,
  "running": [{"task_id": "8c1d…", "project_id": "f03a…", "state": "running", "started_at": "…",
               "tokens": {"used": 61204, "budget": 250000}, "lock": null}],
  "queued": [{"task_id": "77ab…", "project_id": "f03a…", "position": 1}],
  "legacy_active": true
}
```

`state` updates stay coarse: published on status changes, throttled to at most 4 per second. Fine-grained progress goes through events (events.md), which are not part of `state.json`.

## Scheduler API (`scheduler.py`)

```python
class Scheduler:
    def __init__(self, *, max_running, runtime_factory, policy, audit, events, budget_gate, locks, clock): ...

    def submit(self, task_id, project_id, text, client_id) -> dict: ...   # {'task_id', 'state': 'queued'|'starting', 'position'}
    def cancel(self, task_id) -> bool: ...                                # True if something was running or queued
    def answer(self, task_id, ask_id, decision, text=None, scope_digest=None): ...
    def scope_changed(self, task_id): ...       # called after scope_update/scope_approve
    def set_max_running(self, value): ...
    def snapshot(self) -> dict: ...             # the "scheduler" block above
    def shutdown(self, timeout_s=30): ...       # cancel all, join workers
```

- `submit` starts a **turn**: the user's message to an `agent` task. A task has at most one turn in flight; `submit` on a task that is not `idle` or terminal fails with `ValueError('This task is already working. Wait or stop it first.')`.
- Queueing is FIFO by submit time. A queued task starts when a slot frees.
- `submit` requires a current scope approval (`scope.md`); without one it fails before queueing.
- Every public method is thread-safe and returns quickly. Long work happens on the task's worker thread.
- The scheduler holds `Application.lock` only to read or change shared state (task records, the usage ledger, `state.json`), never across a runtime call, a connector call or a lock wait.

## Task runner lifecycle

One worker thread per running task:

1. `starting`: reserve the slot; create or reuse the workspace clone (scope.md) under the project lock; start or reuse the runtime session.
2. Budget gate: reserve the turn estimate (below). If it does not fit, the task ends `budget_exhausted` and nothing starts.
3. `running`: `session.run_turn(text, ctx)` blocks until the turn ends. The runtime calls back into `ctx` for every action, ask, event and usage report.
4. Settle the budget reservation with the reported usage, or charge the estimate.
5. Publish the task branch to the user's repository under the project lock (scope.md), emit the cumulative diff, then `idle`. The slot is released.

The time limit is checked by the scheduler, not the runtime. The scheduler keeps each task's active time with `time.monotonic`, adding only intervals spent in `starting`, `running` and `waiting_lock`, and persists the total in the task record at each status change. When it reaches `limits.time_limit_s`, the scheduler cancels the turn and the task ends `time_limit`.

### Cancel (per task)

UI → backend: `agent_cancel {task_id}` → `{"cancellation_requested": bool}`.

- A queued task leaves the queue and ends `cancelled`.
- A running task: status `cancelling`, set the task's cancel event, call `session.interrupt()`. If the turn has not ended 10 s later, call `session.kill()`, which terminates the runtime's process group. `PROVISIONAL(0B-3)`.
- A paused task (`paused_ask`, `paused_scope`): the open ask closes with `cancelled`; the turn is interrupted as above.
- An app write already sent is not undone. If its result never arrives it is recorded as `outcome_unknown`.
- The existing `cancel` method keeps cancelling only the legacy slot.

## Runtime adapter API (2A, 2B implement)

```python
class Runtime:
    name = 'codex'                  # 'codex' | 'claude'
    def open(self, ctx) -> 'Session': ...

class Session:
    def run_turn(self, text, ctx) -> dict: ...   # TurnResult; blocks
    def interrupt(self): ...                     # ask the turn to stop; returns at once
    def kill(self): ...                          # terminate the provider process group
    def close(self): ...                         # end the session cleanly
```

`TurnResult`: `{"status": "completed" | "failed" | "cancelled", "usage": {...} or None, "error": {"code", "message"} or None}`. `usage` is the provider's raw token counts for the turn, interpreted by `budget.charge(usage, provider)`.

### `RunContext` (passed by the scheduler)

```python
class RunContext:
    task_id: str
    project_ids: list
    workspaces: dict          # project_id -> absolute workspace path
    primary_workspace: str    # cwd for the session
    scope: dict               # copy at turn start, for prompts and display only; never used for decisions
    model: str or None        # PROVISIONAL(0B-7); None = provider default
    cancel: threading.Event

    def authorize(self, request, call_id) -> dict: ...   # final {'decision': 'allow'|'deny', 'rule', ...}
    def emit(self, kind, data, *, turn_id=None, item_id=None): ...
    def app_tool(self, name, arguments, call_id) -> dict: ...   # run a connector tool after authorization
    def report_usage(self, usage): ...                    # optional mid-turn usage; PROVISIONAL(0B-2)
```

- **`authorize` is the only policy entry point.** It reads the task's **live** scope and approval under `Application.lock`, calls `scope.decide`, writes the audit record and returns `allow` or `deny`. On `ask`, it emits `tool_call`/`ask`, sets `paused_ask`, blocks until the user answers or the task is cancelled, records the answer, then returns the final decision. A runtime never sees `ask`.
  - It translates provider approval requests into scope requests and passes the answer back. With `codex app-server`, every command and file-change approval request goes through `authorize`. `PROVISIONAL(0B-1)`.
  - It must also be called for actions the provider would run without asking (for example in-sandbox commands), when the provider exposes them before they run, so audit and `always_deny` apply. Where the provider only reports such actions after the fact, the runtime emits them with `decision.rule: "provider.sandbox"` and the audit record says so.
- **`app_tool`** is how connector tools run (through the Interspace MCP bridge, `PROVISIONAL(0B-4)`). It looks up the tool descriptor, builds the `app` request from the descriptor's `effect` and `ref_param`, calls `authorize`, takes the resource lock for writes, calls the connector with idempotency key `agent_key(task_id, turn_id, call_id)`, emits `tool_call`/`tool_result` for reads or `app_action` for writes, and returns the tool result JSON (connectors.md). The runtime never calls connectors directly.
- **`emit`** assigns `seq`, persists and forwards the event. Which component emits which kind is fixed in events.md ("Who emits what").
- A runtime must:
  - start its provider in a sandboxed, approval-requesting mode (Codex `workspace-write` with approvals routed to Interspace) and never in a bypass mode (`always_deny.bypass`);
  - not load user-level or project-level provider configuration that could widen permissions; Interspace passes all settings explicitly, as `provider.py` does today;
  - treat all connector content and file content as data;
  - reject provider messages that do not match its validated shapes (`runtime_protocol` error), as `provider.py` rejects unexpected events today.

## Budgets

The budget stays per task, tokens only, gated before work starts.

- `budget.reserve` gains an `estimate` override and `provider`, `turn_id` parameters. An agent turn reserves `estimate_turn(prompt_chars)`, a fixed per-turn allowance that 1F sets from 0B's measured turns; it is `PROVISIONAL(0B-2)`.
- Ledger entries gain `provider` (`codex` | `claude`), `charge_rule` (for example `codex.input+output`), `turn_id` and `call_kind: "agent_turn"`. Entries without `provider` are Codex, as the Claude Code provider spec requires.
- `budget.charge(usage, provider='codex')`: Codex keeps `input_tokens + output_tokens`; Claude follows its approved spec (`input + cache_creation + cache_read + output`). 2B adds the Claude rule.
- Mid-turn: if `report_usage` shows `used + reserved` beyond the budget, the scheduler interrupts the turn and the task ends `budget_exhausted` with its work kept. A turn already started may overshoot; the overshoot is shown, as today.
- Concurrent tasks use separate task IDs in the same `state['usage']` list. All ledger changes happen under `Application.lock`, so totals stay consistent.

## Locks

Each task works in its own clone, so two tasks editing files in the same project do not touch the same files. Locks serialise only operations on shared state:

| Lock key | Held while | Max hold |
| --- | --- | --- |
| `project:<project_id>` | cloning from or removing a task's workspace; publishing or deleting its branch in the user's repository; **Merge** | the operation |
| `app:<ref>` | one connector write to that resource; for creates, the parent `ref` | the single write |

(The roadmap says "writes to the same project are serialised". This contract reads that as: writes to the user's repository itself are serialised, while edits inside separate task clones run in parallel. Assistant's interpretation; the coordinator should confirm it with the user if in doubt.)

```python
class Locks:
    def acquire(self, key, task_id, cancel, timeout_s=300) -> None: ...  # raises LockTimeout(ValueError)
    def release(self, key, task_id): ...
    def holders(self) -> dict: ...
```

- FIFO per key. In-process only; the existing `app.lock` file already ensures one backend per data directory.
- **A task holds at most one lock at a time.** It acquires, acts and releases. This rules out deadlock without ordering rules.
- Waiting shows `waiting_lock` with the key in `detail`. Waiting time counts against the time limit. Cancel ends the wait at once.
- UI Spaces writes take the same `app:<ref>` lock (with `task_id: null`), so a user edit and an agent edit to one page do not interleave.

## Merge (the user's decision 1)

UI → backend: `workspace_merge {task_id, project_id, branch, base_commit}` → `{"merged": true, "commit": "…"}`.

- The user's action only. Agents cannot merge.
- Requires the task to be `idle` or terminal, takes `project:<project_id>`, and refuses (with a sentence saying why) when the user's checkout has uncommitted changes, is in a merge or rebase, or is not on the branch it was on at task start.
- Fast-forward when possible, otherwise a normal merge commit; on conflict it aborts the merge and leaves everything as it was. Never force, never rebase, never push.
- Audited with `actor: user`, `kind: action`.
- Scheduled for Wave 2C; listed here so 1F reserves the method and lock.

## Methods summary (UI → backend)

| Method | Params | Owner |
| --- | --- | --- |
| `agent_create` | `{project_id, title, scope}` → `{task_id, scope_digest}` (creates an `agent` task, unapproved) | 1F |
| `agent_message` | `{task_id, text, client_id}` → `{"state", "position"}` (calls `submit`) | 1F |
| `agent_answer` | events.md | 1F |
| `agent_cancel` | `{task_id}` | 1F |
| `task_events`, `task_blob` | events.md | 1F |
| `scope_get`, `scope_update`, `scope_approve` | scope.md | 1F wires, 1E implements |
| `scheduler_settings` | `{max_running}` → `{"max_running"}` | 1F |
| `workspace_merge` | above | 2C |
| `spaces_*` | connectors.md | 1F wires, 1A–1D implement |

Each new method must also be added to the `main.swift` allowlist by its owner (README, shared-file ownership).
