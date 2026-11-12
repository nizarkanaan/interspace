# Codex app-server as the Interspace agent runtime (Wave 0B spike)

Date: 2026-11-11. Roadmap: `docs/superpowers/plans/2026-11-11-agentic-spaces-roadmap.md`, stream 0B.

**Verdict: proven, with conditions.** `codex app-server` lets Interspace answer every command, file-write, network and MCP-tool approval itself. No bypass flag is needed and MCP tool calls are not cancelled headlessly. Use it as the Wave 2 runtime with the conditions in [Recommendation](#recommendation).

## Evidence base

- **Installed CLI:** `codex-cli 0.167.0-alpha.4.1`, bundled at `/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex`. That is a shell wrapper around `../CodexCLI.app/Contents/MacOS/codex`. No `codex` is on `PATH`. `app-server` is labelled `[experimental]` in `codex --help`.
- **Protocol schema:** generated from this exact binary with `codex app-server generate-json-schema --out …` and `generate-ts --out …`, plus `--experimental` variants. The copies are in ignored `workspace-data/spikes/app-server/{schema,schema-exp,ts,ts-exp}/`. The official docs say the generated bundle matches each Codex version exactly. Interspace should regenerate it at build time and pin against it.
- **Official docs:**
  - [App Server](https://learn.chatgpt.com/docs/app-server) (formerly developers.openai.com/codex/app-server). It says to use the app server "when you want a deep integration inside your own product: authentication, conversation history, approvals, and streamed agent events."
  - [Permissions](https://learn.chatgpt.com/docs/permissions.md). Permission profiles are labelled beta there.
- **Issue:** [openai/codex#24135](https://github.com/openai/codex/issues/24135) is still open, and no maintainer has replied. Under `codex exec` with stdin closed, MCP calls fail with "user cancelled MCP tool call". The thread's only reliable workaround is the bypass flag, which is forbidden here.
- **Spike prototype:** in ignored `workspace-data/spikes/app-server/`.
  - `client.py`: a JSON-RPC client.
  - `mcp_server.py`: a stdio MCP server owned by the spike.
  - `probe_offline.py`, `probe_sandbox.py` and `probe_roots*.py`: zero-model-call probes.
  - `probe_live.py`: the live probe.
  - Transcripts are under `runs/`. The live run is `runs/live-235156/`.
- **Real calls:** the user approved 4 model turns. All 4 ran, in a disposable git repo `testrepo/`, with a spike-only `CODEX_HOME` signed in through device auth. Turns 3 and 4 failed: the spike picked a model the account cannot use (see [Model selection](#model-selection)). No further calls were made. One rate-limit event during the run reported the weekly Codex window nearly used, so more live checks should wait for the user.

## Facts

### Transport and handshake

- `codex app-server` defaults to `--listen stdio://`, which carries newline-delimited JSON-RPC 2.0 without the `"jsonrpc"` field. Requests have `id` and `method`, notifications have only `method`, and server→client requests have both and need a response.
- Handshake: send one `initialize` per connection, then the `initialized` notification. Requests sent before it fail with `Not initialized` (docs).

```json
{"id":1,"method":"initialize","params":{"clientInfo":{"name":"interspace","title":"Interspace","version":"0.x"},"capabilities":{"experimentalApi":true,"requestAttestation":false}}}
{"method":"initialized"}
```

- Response, observed in about 380 ms on a cold process: `{"userAgent":"interspace_spike/0.167.0-alpha.4.1 (Mac OS 26.6.0; arm64) …","codexHome":"…","platformFamily":"unix","platformOs":"macos"}`.
- `experimentalApi: true` is required for the fields Interspace needs: `permissions` (named profile), `dynamicTools`, and `runtimeWorkspaceRoots` on `thread/start`.

### App-owned session, user config and project instructions ignored

- `app-server` has **no `--ignore-user-config`** flag; only `codex exec` has one. The supported isolation is an **app-owned `CODEX_HOME`**: Interspace creates the directory and writes its own `config.toml` there, and the user signs in once into that home.
  - `CODEX_HOME=<app dir> codex login --device-auth` is already the shape of `CodexProvider.sign_in`.
  - With an empty home, `initialize` reports the new `codexHome`, and `account/read` returns `{"account":null,"requiresOpenaiAuth":true}`.
  - After device auth it returns `account.type == "chatgpt"`.
  - None of the user's `~/.codex/config.toml`, plugins, hooks, MCP servers, rules, memories or global `AGENTS.md` load.
  - **Never copy `~/.codex/auth.json`.** It is a credential file.
- Project instructions:
  - `thread/start` returns `instructionSources`. In the test repo it was `[".../testrepo/AGENTS.md"]` by default.
  - With `config: {"project_doc_max_bytes": 0}` it was `[]`. Both were verified live.
- **Side effect:** `thread/start` appended `[projects."<cwd>"] trust_level = "trusted"` to the app-owned `config.toml`. Interspace must treat that file as Codex-managed state, not as hand-written config.
- `thread/start` and `turn/start` latency was 4–29 ms. Neither makes a model call.

### Starting a thread (exact request used live)

```json
{"id":3,"method":"thread/start","params":{
  "cwd":"/…/testrepo",
  "permissions":"interspace-task",
  "approvalPolicy":"untrusted",
  "approvalsReviewer":"user",
  "ephemeral":true,
  "serviceName":"interspace",
  "developerInstructions":"…",
  "config":{"project_doc_max_bytes":0,"model_reasoning_effort":"low",
            "mcp_servers":{"interspace":{"command":"/usr/bin/python3","args":["-I","…/mcp_server.py"],
                                         "env":{"…":"…"},"default_tools_approval_mode":"prompt"}}},
  "dynamicTools":[{"type":"function","name":"interspace_scope","description":"…",
                   "inputSchema":{"type":"object","properties":{},"additionalProperties":false}}]}}
```

- The response has `thread.id`, `model`, `cwd`, `instructionSources`, `approvalPolicy`, `approvalsReviewer`, a legacy `sandbox` echo and `activePermissionProfile`. Live, this was `{"id":"interspace-task","extends":":workspace"}`.
- `approvalsReviewer` must be `"user"`. The `"auto_review"` and `"guardian_subagent"` options hand decisions to a Codex subagent instead of Interspace.
- `approvalPolicy` values are `"untrusted" | "on-request" | "never" | {granular:{…}}`. With `"untrusted"`, every non-trivial command asked, including `ls -a` and `cat`. That suits "Interspace decides everything". The scope engine can answer known-safe reads at once.

### Turns and streamed events

Start a turn:

```json
{"id":4,"method":"turn/start","params":{"threadId":"…","input":[{"type":"text","text":"…","text_elements":[]}]}}
```

- The response is `{turn:{id,status:"inProgress",…}}`.
- Optional per-turn overrides are `model`, `effort`, `cwd`, `approvalPolicy`, `sandboxPolicy` and `outputSchema`. They stick for later turns, except `outputSchema` (docs).

Notifications seen in the live run, from 266 transcript lines:

| Purpose | Method | Payload (key fields) |
| --- | --- | --- |
| Lifecycle | `turn/started`, `turn/completed` | `turn.status`: `completed`, `interrupted` or `failed`; `turn.error.{message,codexErrorInfo}`; `durationMs` |
| Item lifecycle | `item/started`, `item/completed` | `item.type`: `userMessage`, `agentMessage`, `reasoning`, `commandExecution`, `fileChange`, `mcpToolCall`, `dynamicToolCall` and others |
| Assistant text | `item/agentMessage/delta` | `{threadId,turnId,itemId,delta}` |
| Command output | `item/commandExecution/outputDelta` | `{…,itemId,delta}`. The completed item carries `aggregatedOutput`, `exitCode` and `durationMs` |
| File edits | `fileChange` item | `changes:[{path,kind:{type:"add"|"delete"|"update",move_path},diff}]`, `status`: `completed`, `failed` or `declined` |
| Turn diff | `turn/diff/updated` | `{threadId,turnId,diff}`: the full aggregated unified diff for the turn, re-sent after each step |
| MCP tool | `mcpToolCall` item | `server`, `tool`, `arguments`, `readOnlyHint`, `result.content`, `error.message` |
| Thread state | `thread/status/changed` | `{type:"active",activeFlags:["waitingOnApproval"]}` while an approval is pending |
| Approval cleared | `serverRequest/resolved` | `{threadId,requestId}` |
| Usage | `thread/tokenUsage/updated` | See [Usage](#usage-and-budgetcharge) |
| Other | `account/rateLimits/updated`, `turn/moderationMetadata`, `mcpServer/startupStatus/updated`, `warning`, `error`, `remoteControl/status/changed` | — |

- **Ordering, verified:** `item/started` (status `inProgress`) → server request `…/requestApproval` → client response → `serverRequest/resolved` → `item/completed`.
- **Gap:** a command that was approved but then blocked by the sandbox (`echo x > ../escape-shell.txt`) produced `item/started` and an approval, but **no `item/completed`**. The adapter must close any item still open when `turn/completed` arrives.
- **Shell:** commands run as `/bin/zsh -lc '<cmd>'`. That is a login shell, so the user's shell profile runs inside the sandbox. The config key `allow_login_shell` exists in the binary, but setting it to `false` was not tested live. Set it and confirm in Wave 2. Also review `shell_environment_policy`, so that secrets in the user's environment do not reach agent commands.

### Approvals: requests and responses

All arrive as JSON-RPC requests from the server. Interspace replies with `{"id":<same>,"result":…}`. Approval requests block only the thread that sent them: the thread shows `waitingOnApproval`, and other threads keep running.

**Commands:** `item/commandExecution/requestApproval`, observed live:

```json
{"kind":"command","threadId":"…","turnId":"…","itemId":"exec-…","startedAtMs":1794459122372,"environmentId":"local",
 "command":"/bin/zsh -lc 'ls -a'","cwd":"/…/testrepo",
 "commandActions":[{"type":"listFiles","command":"ls -a","path":null}],
 "proposedExecpolicyAmendment":["ls","-a"],
 "availableDecisions":["accept",{"acceptWithExecpolicyAmendment":{"execpolicy_amendment":["ls","-a"]}},"cancel"]}
```

- Response: `{"decision": "accept" | "acceptForSession" | {"acceptWithExecpolicyAmendment":{…}} | {"applyNetworkPolicyAmendment":{…}} | "decline" | "cancel"}`.
- Live, `"decline"` was accepted even though `availableDecisions` did not list it. The `curl` item completed with `status:"declined"`, the turn continued, and the model reported the step as refused.
- `kind` can be `"command"`, `"humanCommand"` or `"writeStdin"`.
- Interspace should never answer with `acceptForSession` or an execpolicy amendment. Those widen Codex-side state behind the scope engine. Answer each request with `accept` or `decline`, and keep "add to scope" in Interspace.

**Network:** the same method, but with `networkApprovalContext: {host, protocol}` and optional `proposedNetworkPolicyAmendments`.

- The docs say to show a network-specific prompt, and that concurrent requests for the same host are grouped.
- With network off in the profile, the agent's `curl` was answered `decline` by Interspace. Offline, curl inside the sandbox failed DNS (`Could not resolve host`).
- A request carrying `networkApprovalContext` was **not** observed live. It needs the managed network proxy (`features.network_proxy`) and was out of scope here.

**File writes:** `item/fileChange/requestApproval`, observed live:

```json
{"threadId":"…","turnId":"…","itemId":"exec-…","startedAtMs":1794459124378,"reason":null,"grantRoot":null}
```

- Response: `{"decision":"accept"|"acceptForSession"|"decline"|"cancel"}`.
- **The request carries no paths.** The paths and diff come from the earlier `item/started` `fileChange` item with the same `itemId`. The scope engine must correlate the two, and the spike did.
- `../escape-live.txt` was declined from scope, giving `status:"declined"` and no file written. `hello.txt` was accepted and written.

**MCP tools:** `mcpServer/elicitation/request`, with `_meta.codex_approval_kind == "mcp_tool_call"`. Observed live:

```json
{"threadId":"…","turnId":"…","serverName":"interspace","mode":"form",
 "_meta":{"codex_approval_kind":"mcp_tool_call","tool_name":"note_write",
          "tool_annotations":{"readOnlyHint":false,"destructiveHint":false},
          "tool_description":"Append a line to the spike note store.",
          "tool_params":{"text":"spike"},
          "tool_params_display":[{"name":"text","value":"spike","display_name":"text"}]},
 "message":"Allow the interspace MCP server to run tool \"note_write\"?",
 "requestedSchema":{"type":"object","properties":{}}}
```

- Response: `{"action":"accept"|"decline"|"cancel","content":{}|null,"_meta":null}`.
- `accept` ran `note_read`: the server log shows one `tools/call`.
- `decline` gave `mcpToolCall` `status:"failed"`, `error.message:"user rejected MCP tool call"`, and the MCP server never received the call.
- The request carries the exact arguments (`tool_params`), so Interspace can bind the approval to them.
- This only happens because the server config has `default_tools_approval_mode = "prompt"`. The values are `"auto" | "prompt" | "writes" | "approve"` (`AppToolApproval`). Per-tool `tools.<name>.approval_mode` also exists.
- Interspace must set `"prompt"` on every MCP server it attaches, so that each call reaches the scope engine.
- Elicitations that are not approvals (no `codex_approval_kind`) are real MCP forms and should be routed to the user.

**Dynamic tools (experimental):** `item/tool/call`, observed live. These tools are hosted by Interspace itself, with no MCP process.

```json
{"threadId":"…","turnId":"…","callId":"exec-…","namespace":null,"tool":"interspace_scope","arguments":{}}
```

- Response: `{"contentItems":[{"type":"inputText","text":"…"}],"success":true}`. The item completed as `dynamicToolCall`.
- Interspace executes the tool, so this route has no approval step. Scope is enforced in Interspace's own handler.

**Other server requests** in the schema:

- `item/permissions/requestApproval`: the built-in `request_permissions` tool. The response is `{permissions:{network?,fileSystem?},scope:"turn"|"session"}`. Grant `{}` unless the scope allows it.
- `item/tool/requestUserInput` (experimental).
- `account/chatgptAuthTokens/refresh`.
- `attestation/generate`: off when `requestAttestation:false`.
- Legacy `applyPatchApproval` and `execCommandApproval`.

The adapter must answer each of these, or fail closed with a JSON-RPC error.

### Sandbox confinement

Use **permission profiles**, not the legacy `sandbox`/`sandboxPolicy`.

- Profile defined in the app-owned `config.toml`, verified:

```toml
default_permissions = "interspace-task"

[permissions.interspace-task]
description = "Interspace task: write the task worktree only, no network."
extends = ":workspace"

[permissions.interspace-task.filesystem]
"/absolute/secret/dir" = "deny"     # deny wins over read/write

[permissions.interspace-task.network]
enabled = false
```

- `permissionProfile/list` showed `:read-only`, `:workspace`, `:danger-full-access` and `interspace-task`. `thread/start {"permissions":"interspace-task"}` reported it as active.
- Results through `command/exec` and live turns:

| Action | Outcome |
| --- | --- |
| Write inside the worktree | ok |
| Write outside, via the agent's patch tool | declined by the scope engine |
| Write outside, via shell after Interspace said `accept` | blocked by Seatbelt (`Operation not permitted`), no file |
| Write to `.git/` | `Operation not permitted` |
| Network | `curl: (6) Could not resolve host` |
| Read a denied path | `Operation not permitted` |

- **Reads are wide by default.** `:workspace` and legacy `workspaceWrite` allow reading the whole disk, `~/.codex` included. The profile must add `deny` entries for credential and private locations: `~/.codex`, `~/.ssh`, Keychains, the user's other projects, Sample Project, and the app's own Application Support data except the task worktree. The docs list globs and `:minimal` for building an allow-list read set. Wave 1E should design this as allow-list reads, not a deny-list.
- **Pitfall 1:** an explicit legacy `sandboxPolicy` (on `command/exec` or `turn/start`) **overrides the profile**. With it, the denied decoy file was readable again. The docs confirm that profiles and legacy `sandbox_mode` do not combine. Never send `sandbox`/`sandboxPolicy` from Interspace.
- **Pitfall 2:** with legacy `workspaceWrite`, `command/exec` made the **app-server process's own working directory** writable as well as `writableRoots`. A sibling directory was writable only while it was the server's cwd; this was reproduced by changing the launch cwd. Launch each app-server with cwd set to the task worktree or an empty app-owned directory.
- **Never call `thread/shellCommand`.** Its schema says it "runs unsandboxed with full access".
- Seatbelt nests correctly inside another sandboxed process. The probes ran under the Claude Code sandbox and still showed denials.

### Attaching an Interspace-owned MCP server

- Pass it per thread in `thread/start.config.mcp_servers.<name>` (`command`, `args`, `env`, `default_tools_approval_mode`), or in the app-owned `config.toml`.
- Codex starts one MCP process per thread, and the startup is reported in `mcpServer/startupStatus/updated`.
- `mcpServerStatus/list {threadId}` returned `runtimeStatus:"connected"` and our tools.
- The docs say a *required* MCP server that fails to initialize makes `thread/start` fail.
- Calls go through the elicitation approval above, so every connector write passes the scope engine with its exact arguments.
- **Dynamic tools are a simpler alternative** for connector tools that live inside the Interspace backend: there is no extra process, and the call reaches Interspace directly.
  - Prefer them for Spaces connectors.
  - Keep MCP for tools that already ship as MCP servers, such as hosted Notion MCP.
  - Dynamic tools are `experimental`, so pin the CLI version.

### Cancellation and process cleanup

- `{"method":"turn/interrupt","params":{"threadId":…,"turnId":…}}` returned `{}`. The turn ended with `status:"interrupted"` **106 ms** later, and the approved `sleep 60` process was gone (`pgrep` empty).
- `serverRequest/resolved` also clears any pending approval when a turn is interrupted (docs).
- The app-server runs in its own session when launched with `start_new_session=True`, as `provider.py` already does. Commands run under it.
- **MCP server processes get their own process group** (`pgid == pid`), so `killpg(app_server)` does not reach them.
  - They exited when the app-server closed their stdin, and none remained after stop.
  - A hung MCP server would survive. The adapter should record MCP child pids from the MCP server's own startup report or from `ps` by parent pid, and kill them on shutdown.
- Thread-level cleanup: use `thread/unsubscribe` or `thread/archive`, and `ephemeral:true` for no persisted history. Whether `ephemeral` avoids every sqlite write was not checked.

### Usage and `budget.charge`

- `thread/tokenUsage/updated` arrives after **each model request** inside a turn: 10 times in the 9-step turn.

```json
{"threadId":"…","turnId":"…","tokenUsage":{
  "total":{"totalTokens":158624,"inputTokens":158257,"cachedInputTokens":140928,"cacheWriteInputTokens":0,"outputTokens":367,"reasoningOutputTokens":0},
  "last": {"totalTokens":16237,"inputTokens":16189,"cachedInputTokens":16000,"cacheWriteInputTokens":0,"outputTokens":48,"reasoningOutputTokens":0},
  "modelContextWindow":…}}
```

- `total` is cumulative for the thread, and `last` covers the latest request.
- Field semantics match `codex exec` (`cached` ⊂ `input`; `reasoning` ⊂ `output`), and `totalTokens == inputTokens + outputTokens` held in every event. So `budget.charge({"input_tokens": inputTokens, "output_tokens": outputTokens})` maps directly.
- **Per-turn charge** = sum of `last` over the turn's events, or `total` at `turn/completed` minus `total` before the turn.
- **Charge as events arrive**, not at the end. The live 9-step turn reached 158,624 tokens: each tool step re-sends about 16k of context, mostly cached. The probe's 150k cap did not stop it, because the cap was only checked between events and the turn ended on the event that crossed it.
- The budget gate must:
  1. reserve before `turn/start`;
  2. charge on every `thread/tokenUsage/updated`;
  3. send `turn/interrupt` the moment the next request could exceed the budget. Allow one request of overshoot, about `last.totalTokens`.
- Interrupted turns still report usage: 22,822 tokens for the cancelled turn. Failed turns before any request reported none.
- `account/rateLimits/updated` exposes plan usage percentages. **Do not surface it**: AGENTS.md forbids showing remaining account allowance. Drop it in the adapter.

### Several sessions at once

- One app-server process held 3 threads at once (`thread/loaded/list`). A second app-server process with its own home ran at the same time.
- Live: two threads on one process sent `turn/start` within the same millisecond. Both were processed independently. Both failed for the model reason below, so **parallel completed turns are not yet shown live**.
- Approvals are per thread: a pending approval blocks only its thread.
- Recommended shape: **one app-server process per task**. That gives clean cancellation, cwd confinement (pitfall 2), per-task MCP children and simple crash isolation. Processes start in about 0.4 s and use one shared `CODEX_HOME`. Sharing one process across tasks is possible, but loses the per-process cwd protection.

### Model selection

- `model/list` returns the models for the **signed-in** account: `id`, `isDefault`, `defaultReasoningEffort` and `supportedReasoningEfforts`.
  - Signed-in list: `gpt-6.1-sol` (default), `gpt-6-astra`, `gpt-6.1-terra`, `gpt-6-sol`, `gpt-6-luna`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`.
  - The signed-out list also showed `gpt-5.5`.
- The spike picked `gpt-5.5` from the signed-out list. Both turns failed in 1.7–2.5 s with `codexErrorInfo:"modelNotFound"` ("not supported when using Codex with a ChatGPT account"), plus a `warning` about missing model metadata.
- Choose models only from the signed-in `model/list`. Map `modelNotFound` to a clear UI error. Never retry automatically.
- The model is set by `thread/start.model` or `turn/start.model`, and effort by `config.model_reasoning_effort` or `turn/start.effort`.

### First-call stall

- Cold process to first thread: `initialize` took 380 ms and `thread/start` took 6–29 ms.
- First live turn on a fresh thread:
  - first event: 7 ms;
  - first model usage event: about 5.3 s;
  - first assistant text: 3.6 s;
  - whole 9-step turn: 24 s.
- Second turn on the same thread: first text after 2.0 s.
- **No 45 s stall and no multi-minute first call.** The app-server prewarms a Responses WebSocket at `thread/start`; a signed-out run logged `failed to connect to Responses WebSocket`. That is a plausible reason the long-lived session starts faster.
- The spike did not reproduce the stall under `codex exec` for comparison, so the cause of the old stall is unconfirmed. A long-lived session amortises process start, MCP start and WebSocket setup either way.

## Recommendation

Adopt `codex app-server` for Wave 2A with these rules:

1. **App-owned `CODEX_HOME`** under Application Support, with Interspace's own `config.toml` and a one-time device-auth sign-in. Keep the generated JSON schema for the pinned CLI version in the test fixtures, and fail closed on an unknown version.
2. **One process per task.** Launch with `start_new_session=True`, cwd set to the task worktree, `initialize` with `experimentalApi:true`, and `thread/start` with:
   - `permissions:"<task profile>"`, `approvalPolicy:"untrusted"` and `approvalsReviewer:"user"`;
   - `project_doc_max_bytes:0`, unless the scope opts in to project instructions;
   - `ephemeral:true`;
   - attached MCP servers with `default_tools_approval_mode:"prompt"`;
   - Interspace connector tools as `dynamicTools`.
3. **Per-task permission profile** generated from the scope: worktree writable; network per scope; allow-list reads with deny entries for credentials, other projects, Sample Project and app data. Never send legacy `sandbox`/`sandboxPolicy`. Never call `thread/shellCommand`. Never answer with `acceptForSession` or policy amendments.
4. **Approval bridge.** Map every server request to the scope engine (allow, ask or deny). Correlate file paths through `itemId`, bind MCP approvals to `_meta.tool_params`, and answer unknown request methods with an error. "Ask" leaves the JSON-RPC request pending while the task is paused.
5. **Event mapping into the 0A contract:** turn and item lifecycle, deltas, `turn/diff/updated`, and approvals with `serverRequest/resolved`. Synthesize completion for items still open at `turn/completed`.
6. **Budget** charges on each `thread/tokenUsage/updated` (`input+output`) and interrupts at the cap. Drop `account/rateLimits/updated`.
7. **Cleanup:** `turn/interrupt`, then close stdin, then `killpg`, then kill any MCP child pids that remain.

### Provisional runtime fields for 0A

- **`runtime`:** `"codex-app-server"`.
- **`cli_version`.**
- **`thread_id`, `turn_id`, `item_id`:** strings, UUIDv7.
- **`item.kind`:** `agent_message`, `reasoning`, `command`, `file_change`, `mcp_tool`, `dynamic_tool` or `plan`.
- **`approval.kind`:** `command`, `network`, `file_change`, `mcp_tool` or `permissions`. Each approval also carries `approval.request_id`, `approval.item_id`, and `approval.subject` (command and cwd, or paths and diff, or server, tool and args).
- **`approval.decision`:** `allow_once` or `deny`, mapped to `accept`/`decline` or `accept`/`decline` with `content:null`.
- **`usage`:** `{input, cached_input, output, reasoning_output}` per model request, plus a per-turn sum.
- **`turn.status`:** `completed`, `interrupted` or `failed`, with `error.code` taken from `codexErrorInfo`.

## Open items (not verified)

- Parallel turns that complete successfully on two threads. Re-run turns 3 and 4 with a model from the signed-in list, after the usage window resets and with the user's approval.
- `allow_login_shell=false`, `shell_environment_policy`, and a network-proxy approval with `networkApprovalContext`.
- Behaviour when an MCP server hangs, and when the app-server crashes mid-approval (whether pending requests replay).
- Version drift: app-server is experimental, and dynamic tools and profiles are experimental or beta. Each CLI update needs a schema diff in CI.

## Fallback if app-server becomes unsuitable

Use `codex exec` with an **Interspace-side tool loop**. Keep Codex's own shell and MCP tools disabled; Codex only proposes actions, and Interspace executes them after the scope engine approves.

- Run each step as `codex exec --ignore-user-config --ignore-rules --sandbox read-only -c features.shell_tool=false --json --output-schema <action schema>`. This is today's `provider.py` invocation.
- The model returns either a typed action (`run_command`, `write_file`, `connector_call` with exact arguments) or `final`.
- Interspace evaluates each action against the scope. It runs commands itself under `codex sandbox -P <profile> -C <worktree> -- …`; that Seatbelt confinement was verified in this spike. It applies writes itself, and calls connectors directly.
- Interspace feeds the observations back with `codex exec resume <session>`, or a fresh call with a running transcript.

Costs:

- One process start per step, so no long-lived session and no streaming tool events.
- More tokens per step.
- Interspace must maintain its own tool prompt.

It avoids issue #24135 because Codex never makes an MCP call, and it never needs the bypass flag.
