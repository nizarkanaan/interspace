# Orchestrator, team proposals and child runs

Owner: 1B (`app/backend/orchestrator.py`, the `scheduler.py` changes and the orchestration tools in `runtime/mcp_bridge.py`). Conventions: [README.md](README.md).

## Shape

- **Every new task is an Orchestrator task:** `mode: 'agent'`, `role: 'orchestrator'`.
  - Its runtime session uses `routing.orchestrator`, which the user can override on New task.
  - It works in its own **read-only** workspace clone of the project.
  - Its scope is the task scope.
- **A subagent is a child task:** a normal agent task row with these extra fields:

```json
{"parent_task_id": "8c1d…", "role": "implementer", "brief": "Add input validation to …",
 "provider": "claude", "model": "claude-sonnet-5-5", "access": "write", "team_id": "a91f…", "member_id": "m2"}
```

  - A child runs through the existing `Scheduler.submit` path, so it reuses the same machinery: its own worker, its own workspace clone and `interspace/task-<id8>` branch (`scheduler.Workspaces`), events, cancel and the ask prompts.
  - **Scope.** A child's scope is derived from the parent's approved scope. `access: 'read'` removes every write and command-write permission; `access: 'write'` keeps the parent scope.
  - **Approval.** No separate scope approval is needed, because the team approval covers it. The child's scope digest records the team approval.
  - A child holds its own run slot. Children of one team run in parallel, up to `max_running`, and queue beyond that.
- **Budget.**
  - One budget per root task. Children reserve and settle against `task_id = root`. Each child is charged by its own provider's `charge_fields`, and its `budget` events go to its own stream.
  - The parent's ledger total includes every child's charges.
  - When a child's turn cannot fit the remaining budget, that child ends `budget_exhausted`. Its siblings continue.

## Orchestration tools

Interspace's MCP bridge (`runtime/mcp_bridge.py`) serves only these tools, and only to Orchestrator sessions. Every call goes through `RunContext.orchestrate(name, arguments)`, which replaces the old `app_tool` path. The tool calls are emitted as `tool_call`/`tool_result` events with `category: 'orchestrate'`.

| Tool | Arguments | Result |
| --- | --- | --- |
| `propose_team` | `{summary, members: [{role, brief, provider?, model?, access?}], reason_for_overrides?}` (1–12 members) | Blocks until the user answers. Returns `{status: 'approved', team_id, members: [{member_id, role, provider, model, access, task_id}]}`, `{status: 'changed', …}` with the user-edited team, or `{status: 'declined', note}`. |
| `team_status` | `{team_id}` | `{members: [{member_id, task_id, state, tokens_used}]}` |
| `wait_for` | `{team_id, member_ids?, timeout_s?}` (timeout 1–1800 s, default 600) | Returns when every listed member has reached `idle` or a terminal state, or on timeout: `{members: [{member_id, state, report, diff_summary}]}` |
| `message_member` | `{team_id, member_id, text}` | Starts a follow-up turn on that child. Returns `{state}`. |

Defaults and checks:
- A member without `provider` or `model` gets the routing defaults for its role.
- `access` defaults to `write` for `implementer` and `tester`, and to `read` for the other roles.
- A `write` member on a provider without `capabilities.write` is refused before the user sees the team.
- `report` is the child's last assistant `message` text, cut at 24 KB.
- `diff_summary` is `{branch, files: [{path, change, additions, deletions}]}` (merge.md) or `null`.
- Everything a child returns is wrapped as `<untrusted-content>` before it reaches the Orchestrator, as the bridge already does for reads.

**Prompt.** The Orchestrator's system prompt adds:
- the role list;
- the user's routing defaults;
- each provider's capabilities;
- the rule: "Suggest a different provider only with a one-line reason; the user approves the team."

## Approval

`propose_team` pauses the parent with status `paused_team` (a new non-terminal state) and emits a `team_proposed` event. The UI answers with the following method:

| Method | Params | Result |
| --- | --- | --- |
| `team_answer` | `{task_id, team_id, decision: 'approve'|'decline', members?: [edited members], note?}` | `{status}` |

- Edits allowed: provider, model, access and brief per member, and removing members.
- The edited team is validated again before it starts. Children are created and submitted only after approval.
- Cancelling the parent cancels every running or queued child of that task.

## New events (events.md additions)

| Kind | Stream | Data |
| --- | --- | --- |
| `team_proposed` | parent | `{team_id, summary, members: [{member_id, role, brief, provider, model, access, default: bool, reason?}], budget: {used, budget}}` |
| `team_answered` | parent | `{team_id, decision, members, note}` |
| `subagent_started` | parent | `{team_id, member_id, task_id, role, provider, model, access}` |
| `subagent_status` | parent | `{team_id, member_id, task_id, state, tokens_used}`: on each status change of the child |
| `subagent_finished` | parent | `{team_id, member_id, task_id, state, report_excerpt, diff_summary}` |

The child's own detailed stream stays in its own `tasks/<child_id>/events.jsonl`, and the UI loads it with `task_events` when the user expands a subagent card.

## Public state

`state['scheduler']['running']` and `['queued']` entries gain `parent_task_id`, `role` and `provider`, so the Running view can group children under their task.

## Restart

A parent or child that was mid-turn becomes `interrupted`, as today. An open `propose_team` becomes `interrupted` without starting children. Nothing resumes.
