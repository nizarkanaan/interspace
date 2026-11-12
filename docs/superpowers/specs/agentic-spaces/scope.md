# Scope schema, policy decisions and audit record

Status: approved by the user on 2026-11-12, Wave 0A. The 0B fields were reconciled in Wave 2A (2026-11-12); 0C fields await their reconciliation. Conventions and the provisional register are in [README.md](README.md).

The user approves a **scope** once per task. Inside it the agent acts without asking. Outside it, that task alone pauses and asks. A fixed always-deny list is refused whatever the scope says. 1E implements `app/backend/scope.py` and `app/backend/audit.py`; every other stream calls them through the functions below.

## Task workspace (the user's decision 1)

An agentic task with a project in its scope works in its own isolated checkout:

- Location: `~/Library/Application Support/Interspace/workspaces/<task_id>/<project_id>/`.
- Created with `git clone --local --no-checkout <user repo> <workspace>`, then `git checkout -b interspace/task-<first 8 characters of task_id> <base_commit>`, where `base_commit` is the commit the user's checkout had at task start. The clone has its own `.git` **inside** the workspace, so the agent's `git status`, `git add` and `git commit` stay inside the sandbox's only writable root. (A linked `git worktree` was considered and rejected: its index, refs and objects live in the user's `.git`, outside the sandbox.)
- After each turn, the scheduler publishes the task's branch to the user's repository under the project lock: `git -C <user repo> fetch <workspace> +interspace/task-…:refs/heads/interspace/task-…`. Only that one branch is written, and only Interspace writes it. Name collisions with an existing branch Interspace did not create add `-2`, `-3`, ….
- Interspace never writes the user's checked-out branch, working tree or other branches. The agent's commits use the user's configured git identity, with no added trailers. Uncommitted agent changes at the end of a turn stay in the workspace and appear in the cumulative diff; they are not published.
- The user merges the branch, or uses the explicit **Merge** action (scheduler.md). Discarding a task removes the workspace; the branch is deleted only if the user confirms.
- `read` access to a project still uses a clone (so commands and reads see a stable commit), but the sandbox is read-only.

- After cloning, Interspace removes the clone's `origin` remote, so the agent cannot push into the user's repository or, in v1, to any remote. Publishing the branch to GitHub is the user's action.

"Inside the workspace" below means inside this clone after resolving symlinks.

## Scope document

```json
{
  "v": 1,
  "task_id": "8c1d…",
  "version": 3,
  "projects": [
    {"project_id": "f03a…", "access": "write",
     "read": ["**"], "write": ["src/**", "tests/**"], "deny": ["secrets/**"]}
  ],
  "commands": {"workspace": "allow", "allow": [["git", "status"]], "deny": [["git", "push"]]},
  "network": {"default": "ask", "allow_hosts": ["pypi.org", "files.pythonhosted.org"], "deny_hosts": []},
  "apps": [
    {"app": "notion", "access": "write",
     "resources": [{"ref": "notion:page:1f2e…", "include_children": true}]},
    {"app": "zotero", "access": "read", "resources": "all"}
  ],
  "web_search": "allow",
  "limits": {"token_budget": 250000, "time_limit_s": 3600}
}
```

Field rules (validated by `scope.validate(document)`, which raises `ValueError` with one sentence):

- `version` is a positive integer, incremented by the backend on every edit. The UI never sets it.
- `projects`: 0–8 entries, each a registered project ID, at most once.
  - `access`: `read` | `write`. `write` lists may be non-empty only with `write` access.
  - `read`, `write`, `deny`: 0–64 glob patterns each, at most 256 characters, relative to the workspace root, POSIX `/`. `*` matches within one path segment, `**` matches any number of segments, `?` one character. No `..`, no leading `/`, no backslashes. Matching is case-sensitive.
  - Default for a new project entry: `read: ["**"]`, `write: ["**"]` when access is `write`, `deny: []`.
- `commands`:
  - `workspace`: `allow` | `ask` | `deny`. Applies to commands that run **inside the sandbox** with the workspace as their only writable root and no network (Codex's `workspace-write` behaviour), and whose `cwd` resolves inside a workspace. Default `allow` when any project has `write` access, otherwise `ask`.
  - Known limit (0B-8, confirmed): Codex's `:workspace` sandbox restricts writes and network, not reads. The Codex runtime narrows reads with deny entries in its permission profile: credential folders (`~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.codex`, `~/.config/gh`, `~/Library/Keychains`, and similar), the app-owned `CODEX_HOME`, and all of Interspace's data except the task's own workspace (other tasks' clones, events, audit, state). Any other file the user can read, including the user's own project checkouts, stays readable by a sandboxed command.
  - `allow` and `deny`: 0–64 argv prefixes, each a list of 1–8 strings. A command matches when its argv starts with the prefix exactly. `deny` wins over `allow`.
- `network` (the user's decision 3): `default` is `ask` | `deny` (`allow` is not offered in v1). `allow_hosts` and `deny_hosts` hold 0–64 hostnames, lowercase, optional leading `*.` for subdomains, no ports, no schemes. Default `{"default": "ask", "allow_hosts": [], "deny_hosts": []}`.
  - Enforcement granularity (0B-5, decided): on/off only. Interspace does not enable Codex's managed network proxy, so the sandbox cannot filter hosts. Because the sandbox has only on/off network, a command that needs network produces a `network` request with `host: null`; the ask is titled "Allow network to any host for this one command?", offers only `allow_once` and `deny`, and `allow_hosts`/`deny_hosts` are not used for commands. The scope editor then labels the network setting "Ask for each command that needs network". The user chose per-host asks; if 0B confirms on/off only, the coordinator tells the user before Wave 2.
- `apps`: 0–4 entries, one per app.
  - `access`: `read` | `write`.
  - `resources`: `"all"` or 1–64 entries `{ref, include_children}`. `include_children` covers resources whose `parent` chain reaches `ref`, as reported by the connector.
- `web_search`: `allow` | `ask` | `deny`. Default `ask`. This is Codex's hosted search, not command network.
- `limits.token_budget`: as `budget.validate`. It **is** the task's token budget: the task record and the scope hold the same value, and editing either is one scope edit.
- `limits.time_limit_s`: 60–86,400. Default 3,600. It counts wall-clock time while the task is `starting`, `running` or `waiting_lock`; time in `queued`, `paused_ask`, `paused_scope` and `idle` does not count. (Assistant's choice; coordinator may revise.)

`scope.default(task, project_ids)` builds the starting scope the scope editor shows.

## Requests

Every action the runtime, the MCP bridge or the scheduler wants to take is described as one request and passed to `scope.decide`. The field set per category is fixed. How the Codex runtime (2A) fills it from app-server approval messages (0B-1, decided):

- `item/commandExecution/requestApproval` → `command`. Codex gives a shell string such as `/bin/zsh -lc '<cmd>'`; the runtime unwraps that one shell wrapper and sends `command: "<cmd>"` with `argv: null`, so `normalize_argv` sees the real command. `cwd` is relative to the workspace that contains it (`.` for its root), otherwise absolute. `additionalPermissions.network` enabled sets `network: true` (the on/off network ask below); extra `fileSystem` permissions set `sandbox: "escalated"`. A request carrying `networkApprovalContext` (only with Codex's managed proxy, which Interspace does not enable) becomes `network` with that host, `port: null`, `via: "command"`.
- `item/fileChange/requestApproval` → `file_write`. The request carries no paths: they come from the `item/started` `fileChange` item with the same `itemId` (`changes[].path` and any `move_path`), relative to their workspace. Paths outside every workspace are sent absolute. A `grantRoot` is added as a path. An approval whose item is unknown is declined without asking.
- `mcpServer/elicitation/request` with `_meta.codex_approval_kind: "mcp_tool_call"` → for server `interspace`, accepted without a request, because `RunContext.app_tool` authorizes the exact call as an `app` request; for any other server, `mcp` with `server` and `_meta.tool_name`. Other elicitations are declined.
- `item/permissions/requestApproval` is answered with no extra permissions; dynamic tool calls, user-input requests, auth-token refresh, attestation and legacy approval methods are refused.
- Actions Codex reports only after the fact (a command or file change that completed without an approval request, a hosted web search) are recorded with `RunContext.observed` as `rule: "provider.sandbox"`, using the same request shapes.

```json
{"category": "file_read",  "project_id": "f03a…", "path": "src/parser.py"}
{"category": "file_write", "project_id": "f03a…", "paths": ["src/parser.py", "tests/test_parser.py"]}
{"category": "command", "argv": ["python3", "-m", "unittest"], "command": null, "cwd": ".",
 "sandbox": "workspace", "network": false, "project_id": "f03a…"}
{"category": "network", "host": "pypi.org", "port": 443, "via": "command"}
{"category": "web_search", "query": "python fromisoformat whitespace"}
{"category": "app", "app": "notion", "op": "update", "action": "notion.page.append", "ref": "notion:page:1f2e…"}
{"category": "mcp", "server": "…", "tool": "…"}
```

- `cwd` is resolved like a path. A command whose `cwd` resolves outside every workspace cannot match `commands.workspace` or `commands.allow`; it asks.
- `path` and `paths` are as the runtime reports them: relative to the workspace or absolute. `decide` resolves them with `os.path.realpath` against the workspace root; anything that resolves outside the workspace is treated as outside it, never trimmed.
- `command`: either `argv` (preferred) or `command` (a shell string, when the runtime only gives a string). Before any matching, `scope.normalize_argv` produces the argv that rules see:
  1. A shell string is split with `shlex.split`. If splitting fails, or the string contains `;`, `&&`, `||`, `|`, `&`, backticks, `$(`, `<`, `>` or a newline, the command is **opaque**.
  2. `argv[0]` is replaced by its basename (`/usr/bin/sudo` → `sudo`).
  3. Leading wrappers are removed, repeatedly: `env` with its options and `NAME=value` pairs, `command`, `builtin`, `exec`, `nohup`, `time`, `nice` (with `-n N`), `timeout` (with its duration), `caffeinate`, `xcrun`.
  4. For `git`, global options before the subcommand are removed: `-C <dir>`, `-c <k=v>`, `--git-dir=…`, `--work-tree=…`, `--no-pager`, `-P`, `--exec-path=…`; any `-c` value is kept separately for the bypass check.
  5. A shell or interpreter given inline code (`sh`, `bash`, `zsh`, `dash`, `fish` with `-c`; `python`, `python3`, `node`, `ruby`, `perl`, `php` with `-c`, `-e` or `-E`; `eval`; `xargs`; `find … -exec`) is **opaque**; its inline code is also normalized once, as a shell string, for the deny checks.
  - Every always-deny and scope `deny` rule is checked against the normalized argv **and** against every argument (so `security` or a bypass flag anywhere denies). An opaque command can match deny rules but never `allow` rules or `commands.workspace: allow`, so it asks.
  - This matching is a guard against accidents and obvious escapes, not a containment boundary. The sandbox is the boundary.
- `sandbox`: `workspace` (inside the sandbox) or `escalated` (the runtime asks to run it outside the sandbox).
- `app.op`: `read` | `create` | `update` | `destructive`, taken from the tool descriptor's `effect` (connectors.md), never from the agent's words. For `create`, `ref` is the parent.
- `mcp` requests are only for MCP servers other than Interspace's own (`interspace`), whose tools go through `RunContext.app_tool` as `app` requests (connectors.md).
- `request_digest(request)` is `sha256:` of the canonical JSON of the request. An ask carries it, the user's answer must repeat it, and the allowed action is exactly that request: the runtime must execute what it submitted, not a rebuilt version.

## Decisions

```python
def decide(scope, approval, request, *, workspace_roots, now) -> dict: ...
```

```json
{"decision": "allow", "rule": "projects[0].write", "reason": "Inside the task scope.",
 "scope_version": 3, "scope_digest": "sha256:…",
 "ask": null}
```

`decision` is `allow` | `ask` | `deny`. `rule` names what decided it (a fixed ID from the always lists, or a path into the scope document) so audit records are traceable. When `decision` is `ask`, `ask` holds `{"reason", "title", "detail", "options", "scope_patch", "patched_scope_digest", "request_digest"}` exactly as the `ask` event needs it (events.md). `patched_scope_digest` is the digest of the scope after applying `scope_patch` and incrementing `version`, or `null` when there is no patch.

Ask reasons by rule:

| Rule | `reason` | Options |
| --- | --- | --- |
| `always_ask.destructive` | `destructive` | `allow_once`, `deny` |
| `always_ask.escalation` | `escalation` | `allow_once`, `deny` |
| `always_ask.mcp` | `mcp_tool` | `allow_once`, `deny` |
| `always_ask.outside_read` | `outside_scope` | `allow_once`, `deny` |
| network not covered | `network_host` | `allow_once`, `add_to_scope` (per-host only), `deny` |
| anything else not covered (step 6) | `outside_scope` | `allow_once`, `add_to_scope` when a patch exists, `deny` |

`decide` is a pure function: no I/O except `realpath`, no clock except `now`. It never raises for an ordinary request. If it raises anyway, the caller treats it as `deny` with rule `policy.failed` (fail closed).

### Evaluation order

The first step that matches decides:

`decide` is given the **live** scope and approval: `RunContext.authorize` reads both from the task record under `Application.lock` on every call, never from a copy taken at turn start.

1. **Approval binding.** If `approval` is missing, or `approval.scope_digest != digest(scope)`, the decision is `ask` with reason `scope_unapproved`. The scheduler turns this into `paused_scope` for the whole task, not a per-request prompt.
2. **Always deny** (fixed in code; no scope can allow it). Rule IDs in brackets.
3. **Scope deny**: `projects[i].deny`, `commands.deny`, `network.deny_hosts`.
4. **Always ask** (fixed; no scope can allow it without asking):
   - `app` with `op: destructive` [`always_ask.destructive`] — the user's decision 2;
   - `command` with `sandbox: escalated` [`always_ask.escalation`];
   - `mcp` (any MCP tool that is not an Interspace connector tool) [`always_ask.mcp`];
   - `file_read` outside every workspace (outside reads are never in scope in v1) [`always_ask.outside_read`].
5. **Scope allow**:
   - `file_read`: project in scope and path matches its `read` list;
   - `file_write`: project `access: write` and **every** path matches its `write` list;
   - `command` inside the sandbox: `commands.workspace == allow`, or argv matches `commands.allow`;
   - `network`: host matches `allow_hosts`;
   - `web_search`: `web_search == allow`;
   - `app` `read`: app in scope (either access) and `ref` covered by `resources`;
   - `app` `create`/`update`: app `access: write` and `ref` covered.
6. **Otherwise ask**, with reason `outside_scope` (or `network_host` for network) and, where a narrow widening exists, a `scope_patch` adding exactly that path, argv prefix, host or resource. Requests that match `deny`-default settings (`commands.workspace: deny`, `network.default: deny`, `web_search: deny`) are `deny` [`scope.default_deny`] instead.

### Always-deny list

Fixed in `scope.py` as named constants. Additions need the coordinator; removals need the user.

| Rule ID | Refused |
| --- | --- |
| `always_deny.credentials` | Reading or writing credential material anywhere, including inside a workspace: the filenames `sources.py` already rejects (`.env*`, `*.key`, `*.pem`, `*.p12`, `*.pfx`, `id_rsa`, `id_dsa`, `id_ecdsa`, `id_ed25519`, `credentials`, `credentials.json`, `secrets.json`), plus `~/.ssh/`, `~/.aws/`, `~/.config/gh/`, `~/.codex/auth.json`, `~/.claude/.credentials.json`, `~/.netrc`, `~/.git-credentials`, `~/Library/Keychains/`. |
| `always_deny.keychain` | Commands whose argv starts with `security` (any subcommand), and any app request for the Keychain bridge. Only connectors reach the Keychain, through the bridge. |
| `always_deny.bypass` | Any request to run with sandbox or approvals bypassed: any argument equal to or containing `--dangerously-bypass-approvals-and-sandbox`, `--yolo`, `danger-full-access`, `--dangerously-skip-permissions`, `bypassPermissions`, `approval_policy=never`, `approval-policy=never`, `sandbox_mode=`; `-a never` or `--ask-for-approval never`; any runtime session started with an equivalent setting. |
| `always_deny.privilege` | Commands starting with `sudo`, `su`, `doas`, `osascript`, `launchctl`, `csrutil`, `spctl`, `tccutil`, `systemsetup`, `dscl`, `defaults write` (outside the workspace). |
| `always_deny.outside_write` | File writes resolving outside the task's own workspace roots and the runtime's temporary directory. This includes the user's original checkout and other tasks' workspaces. |
| `always_deny.app_data` | Reads or writes inside `~/Library/Application Support/Interspace/` other than the task's own workspace: state, audit log, journals, other tasks' events. |
| `always_deny.sharing` | App actions that change sharing, permissions, membership or ownership, invite people, or act as another account. Connectors do not offer these (connectors.md); the rule also catches any MCP or command route to them. |
| `always_deny.scope_self_edit` | Any agent attempt to change its own scope, approval, budget or time limit, through any tool. |

"Other people's data" (roadmap) is covered by `sharing` and by the single-account connectors: an agent only reaches what the user's own signed-in account reaches, and only resources the scope names.

## Approval binding and edits

```python
def digest(scope) -> str: ...   # 'sha256:' + hex of canonical JSON of the whole document, version included
```

Canonical JSON: `json.dumps(scope, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')`.

The task record gains:

```json
"scope": {Scope document},
"scope_approval": {"v": 1, "scope_version": 3, "scope_digest": "sha256:…", "approved_at": "2026-11-11T09:30:00.000Z", "by": "user"}
```

- **Approve** (`scope_approve {task_id, scope_version, scope_digest}`): succeeds only if both match the current scope. The UI sends the digest of the scope it displayed.
- **Edit** (`scope_update {task_id, base_version, scope}`): fails if `base_version` is not the current version. On success the backend sets `version = base_version + 1`, clears `scope_approval`, emits a `scope` event with `change: "edited"`, and returns the new digest. Any edit counts, including widening, narrowing and changing the budget or time limit.
- **Effect on a running task**: an action already allowed and running finishes. The next `decide` returns `scope_unapproved`, so the task enters `paused_scope` until the user approves. Nothing is retried; the paused request runs after approval if it is still allowed.
- **`add_to_scope` answer**: applies the ask's `scope_patch` (merge rules below), increments the version and records a new approval in one transaction, only if the scope has not changed since the ask and the UI-sent `scope_digest` equals the ask's `patched_scope_digest`. The UI copies that digest from the ask; it never computes one. Emits `change: "amended"`.
- **Patch merge**: list fields append missing entries; `access: read` may become `write`; nothing is removed. The patch format is a partial scope document with the same field names.
- **Agents never edit scopes.** Only the UI methods above change them.
- **Legacy tasks** (`review`, `python_fix`) keep today's exact plan and check approvals unchanged. A scope applies only to tasks in the new `agent` mode.

UI → backend methods (1F wires them to `scope.py`):

| Method | Params | Result |
| --- | --- | --- |
| `scope_get` | `{task_id}` | `{"scope", "scope_digest", "scope_approval"}` |
| `scope_update` | `{task_id, base_version, scope}` | `{"scope", "scope_digest"}` |
| `scope_approve` | `{task_id, scope_version, scope_digest}` | `{"scope_approval"}` |

## Audit record

`audit.py` appends one JSON line per record to `~/Library/Application Support/Interspace/audit/<YYYY-MM>.jsonl`, writes and fsyncs before the audited action starts, and never rewrites or deletes lines. If the write fails, the action does not run (`audit_failed`).

```json
{"v": 1, "id": "5e1b…", "at": "2026-11-11T09:31:00.100Z", "prev": "sha256:…",
 "actor": "agent", "kind": "decision",
 "task_id": "8c1d…", "project_id": "f03a…", "turn_id": "t-3", "call_id": "call_11",
 "request": {"category": "app", "app": "github", "op": "create", "action": "github.repo.create_issue", "ref": "github:repo:octo/notes"},
 "decision": "allow", "rule": "apps[1].write", "scope_version": 3, "scope_digest": "sha256:…",
 "outcome": null, "idempotency_key": null, "detail": null}
```

- `actor`: `agent` | `user` | `system`.
- `kind`:
  - `decision`: every `decide` result, including allows;
  - `action`: the outcome of an allowed action, with `outcome` `succeeded` | `failed` | `outcome_unknown` | `cancelled` and, for app writes, `idempotency_key`;
  - `answer`: the user's answer to an ask (`decision` holds `allow_once` | `add_to_scope` | `deny` | `text` | `cancelled`; `detail` holds `{"ask_id", "request_digest"}`; the free text itself is not stored);
  - `scope`: an edit, approval or amendment (`request` is `null`; `detail` holds `{"from_version", "to_version", "from_digest", "to_digest"}`);
  - `auth`: a connector sign-in or sign-out (`actor: user`; `detail` holds `{"app", "state"}`);
  - `user_write`: a write from the Spaces UI (`actor: user`, with action, ref and outcome).
- `prev` is the digest of the previous line in the same file (`sha256:` of its bytes without the newline), or `null` for the first line. It makes accidental edits detectable; it is not a security boundary.
- **What may be recorded:** IDs, refs, action names, workspace-relative paths, hosts, argv (each argument at most 200 characters, the whole list at most 2,000; values after `--token`, `--password`, `--key`, `-p` and arguments containing `=` whose name includes `TOKEN`, `SECRET`, `KEY` or `PASSWORD` replaced by `[redacted]`), resource titles at most 160 characters, error codes.
- **Never recorded:** credentials, file contents, diffs, page or document bodies, model messages, ask free text, environment variables, command output.
- `audit.read(task_id=None, since=None, limit=500)` returns records newest first for the UI's audit view.

1E also owns the durable write journal `FileJournal` (connectors.md), stored beside the audit log.
