# Research scope, tasks without a project, outputs and events

Owner: 1C (`scope.py`, `audit.py`, `scheduler.py`, `tasks.py`, `orchestrator.py`, `routing.py`, `runtime/mcp_bridge.py`). Conventions: [README.md](README.md).

## Scope

New optional top-level key:

```json
"research": {"sources": {"semantic_scholar": "allow", "openalex": "allow", "arxiv": "allow", "crossref": "allow", "unpaywall": "ask"}}
```

- Each value is `allow`, `ask` or `off`; a source left out counts as `off`.
- A scope without the key means research is off, so existing scopes and their digests stay valid unchanged.
- `scope.default` and `project_default` (and a new `research_default` for tasks without a project) set `allow` for every source that `research.sources` reports as usable. Usable means `configured`, or the source has `required: False`.
- **New request category** `research`: `{"category": "research", "source": "<name>", "tool": "<tool name>"}`.
  - `decide`: `allow` maps to allow (rule `research.allow`), `ask` to ask (rule `research.ask`), and `off` or missing to deny (rule `research.off`).
  - `research` is a read category, so read-access runs may use it.
  - `amend` (Add to scope) may set a source from `ask` to `allow`.
- **Audit:** `REQUEST_FIELDS['research'] = ('source', 'tool')`. The query text, IDs and results are never in the audit record. Each call gets the usual `decision` record plus an `action` record with `outcome`.

## Tasks without a project

- `agent_create` accepts `project_id: null` together with `kind: 'research'`. Tasks that have a project default to `kind: 'project'`.
- **No workspace:** a research task has no workspace clone, no `Workspaces` work and no branch publishing.
- **Scope:**
  - `projects: []`, so no file or command access;
  - `network: off`;
  - `research` from `research_default`.
- **Teams:** every member is `access: 'read'`. A write role is refused at `propose_team` with `ValueError('Research tasks have no project to write to. Use a project task for code.')`.
- **Runtimes:** start in an empty, app-owned scratch folder, `<storage>/research-runs/<task_id>/`, which is not a git repo. Claude gets no file tools; Codex runs read-only.
- **Locks:** no project lock is ever taken.
- **State:** these tasks are stored under a synthetic `state['research']['tasks']` collection, shown in the sidebar's **Research** entry, and listed in `state.tasks` when `project_id` is `null`. Each row has `kind: 'research'`.

## Outputs

- When a research task's Orchestrator ends a turn with a final answer, the scheduler writes:
  - `tasks/<id>/outputs/report.md`: the answer text;
  - `tasks/<id>/outputs/references.bib`, but only if a `verify_citations` report exists for that turn. It holds the `research_bibtex` entries for the references marked `verified` (and `mismatch` ones marked as such in a BibTeX comment). `not_found` and `retracted` references are left out and listed in a header comment.
- **Methods**, both in the Swift allowlist:
  - `task_outputs {task_id}` returns `{outputs: [{name, kind: 'report'|'bibtex', bytes, updated_at}]}`.
  - `task_output_save {task_id, name}` asks Swift for a save panel and returns `{saved: bool}`. The backend never writes outside app data.
- **Project tasks** may also produce outputs. Writing a report into the repository is done by a write member through the normal Review and Merge path.

## Roles

- Add `citation_checker`: a read role with default routing `{"provider": "codex", "model": null}`. It goes everywhere the role list is copied: `routing.ROLES` and its defaults, `tasks.TEAM_ROLES`, `orchestrator.py`, the `_MEMBER` enum in `mcp_bridge.py`, and `app/ui/providers.js`.
- Stored routing that lacks the new role is completed from the defaults. It must never be refused.
- **The Orchestrator prompt gains:**
  - a research workflow: search → read → snowball with `research_citations` → synthesize → `verify_citations` → final answer;
  - a rule: "Never cite a paper you did not retrieve with a research tool; run `verify_citations` before any answer that cites papers, and say which references were not verified."

## Events (events.md additions)

| Kind | Stream | Data |
| --- | --- | --- |
| `tool_call` / `tool_result` with `category: 'research'` | the calling task | as today; `input` is `{tool, source?, query?, id?}`; the result output is the tool JSON, truncated per events.md |
| `citation_report` | the calling task | the citation report (tools.md), emitted after each `verify_citations` |
| `research_usage` | the root task | `{calls: {source: n}, cached: {source: n}}`, emitted at most once per second while calls happen |
| `outputs` | the root task | `{outputs: [{name, kind, bytes}]}` when outputs change |

## Key safety (test required)

A backend test stores fake keys for every account through a fake channel. It then runs a team that calls every tool, and asserts that no key or email string appears in:
- `state.json` or any task's `events.jsonl`;
- the audit log;
- stdout messages to the UI;
- tool results;
- the cache files.
