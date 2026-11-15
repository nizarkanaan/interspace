# Spike 0B: Codex sign-in in an app-owned CODEX_HOME, and Claude write mode

Date: 2026-11-15. Branch `interspace/mp-0b-signin`. Facts only; no product code changed.

Versions on this Mac: `codex-cli 0.169.0-alpha.11.1` (bundled in ChatGPT.app), Claude Code `2.1.322`.

Prototype scripts (both run against scratch folders only):

- [`spike-0b/codex_account_probe.py`](spike-0b/codex_account_probe.py): drives `codex app-server` account RPCs.
- [`spike-0b/claude_permission_probe.py`](spike-0b/claude_permission_probe.py): runs the real `claude` CLI
  against a local fake Messages API, and answers its permission prompts.

## Status

| Item | Status |
|---|---|
| Find the `codex` binary | Proven |
| Status and sign-out on a scratch `CODEX_HOME` (CLI and app-server RPCs) | Proven, offline |
| Device-auth sign-in shape (CLI flag and `account/login/start` RPC) | From `--help` and the generated JSON schema. A real sign-in was NOT run. It needs the user's approval. |
| Claude permission prompts for Edit, Write and Bash; allow, deny and rewritten replies | Proven with the real CLI and a fake model (no account, no real model call) |
| Edits stay in the working directory | Proven: they do NOT, unless the host refuses them. See [Containment](#containment). |
| Real Claude model call | Not run. The fake model covers the protocol. Needs approval if wanted. |

## 1. Codex in an app-owned CODEX_HOME

### Binary

`codex` is not on PATH. The bundled one is:

```
/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex
```

This is a 328-byte `/bin/sh` wrapper. It runs
`/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex "$@"`.
`provider.find_codex()` already lists this path. `Path.resolve()` keeps the wrapper (it is not a
symlink), which is fine: the wrapper uses `exec`, so signals reach the real binary.

### Status

```bash
CODEX_HOME=<home> codex login status
```

- Signed out: prints `Not logged in`, exit code 1.
- The first run of any command creates `auth.json.lock`, `auth.lock` and `tmp/` in the home.
- `app-server` also creates `*.sqlite` state, `installation_id` and `skills/` there.

App-server form (no network):

```json
-> {"id":2,"method":"account/read","params":{"refreshToken":false}}
<- {"id":2,"result":{"account":null,"userId":null,"requiresOpenaiAuth":true,"workspaceRouting":null}}
```

When signed in, `result.account` is `{"type":"chatgpt","email":...,"planType":...}` (from the schema and
the earlier runtime spike). Interspace should keep only `type` and `planType`. Do not store or show the email.

### Sign-in (device auth)

CLI form, already the shape of `CodexProvider.sign_in`:

```bash
CODEX_HOME=<home> codex login --device-auth
```

Gap in the current code: `CodexProvider.sign_in` and `CodexProvider.status` run without `CODEX_HOME`, so
they sign in to and check the user's own `~/.codex`, not `<storage>/codex-home`. Both need
`env={..., 'CODEX_HOME': <storage>/codex-home}` (the same allowlisted env as `CodexRuntime.env()`).

App-server form (preferred: structured, no screen-scraping of ANSI output):

```json
-> {"id":2,"method":"account/login/start","params":{"type":"chatgptDeviceCode"}}
<- {"id":2,"result":{"type":"chatgptDeviceCode","loginId":"...","verificationUrl":"...","userCode":"..."}}
   ... the user opens verificationUrl and types userCode ...
<- {"method":"account/login/completed","params":{"loginId":"...","success":true,"error":null}}
<- {"method":"account/updated","params":{"authMode":"chatgpt","planType":"..."}}
```

Cancel: `{"method":"account/login/cancel","params":{"loginId":"..."}}`.

Other `type` values exist (`apiKey`, `chatgpt` browser flow with `authUrl`, `chatgptAuthTokens`,
`amazonBedrock*`). Interspace should only send `chatgptDeviceCode`.

Run the sign-in app-server with the same `CODEX_HOME` and the same `-c` overrides as task sessions, so
config load errors show up at sign-in time.

### Sign-out

```bash
CODEX_HOME=<home> codex logout
```

- Signed out already: prints `Not logged in`, exit code 0 (idempotent).
- App-server: `{"method":"account/logout"}` returns `{}` and emits
  `account/updated {"authMode":null,"planType":null}`.
- `codex app-server --startup-sign-out` also exists. Not needed.

### Credential storage (gotcha)

`cli_auth_credentials_store` accepts `file`, `keyring`, `auto`, `ephemeral` (from the load error for a bad
value). Recommendation: pin `-c cli_auth_credentials_store="file"` for every command on the app-owned home
(login, status, logout, app-server). With `keyring` or `auto`, the token could go to the macOS keychain,
where the app-owned home and the user's `~/.codex` might share or collide. Not verified which store the
default picks. Check this after the first approved real sign-in by listing file NAMES in the home
(`auth.json` present or not). Never open the file.

Also useful: `-c forced_login_method="chatgpt"` (accepted values `chatgpt`, `api`) stops an API-key login
in this home.

The runtime already denies the whole `CODEX_HOME` to agent commands (`CodexRuntime.deny_paths`), so the
token file is not readable by tasks.

### Proven commands (scratch home in the session scratchpad)

```bash
CODEX_HOME=$S/ch codex login status    # Not logged in, exit 1
CODEX_HOME=$S/ch codex logout          # Not logged in, exit 0
python3 spike-0b/codex_account_probe.py --home $S/ch status   # initialize + account/read: account null
python3 spike-0b/codex_account_probe.py --home $S/ch logout   # account/logout {} + account/updated nulls
```

`initialize` returns `codexHome`, which equals the scratch path. That confirms the env var takes effect.
`initialize` is also followed by a `remoteControl/status/changed` notification (status `disabled`):
the runtime must ignore it.

Needs approval (real sign-in, then sign-out, in a throwaway home):

```bash
python3 spike-0b/codex_account_probe.py --home <tmp>/ch device-login
python3 spike-0b/codex_account_probe.py --home <tmp>/ch logout
```

## 2. Claude write mode

### Method

`claude_permission_probe.py` starts a local HTTP server that plays the Anthropic Messages API with SSE
replies. It scripts one `tool_use` per step. The CLI runs with:

- `ANTHROPIC_BASE_URL=http://127.0.0.1:<port>` and a dummy `ANTHROPIC_API_KEY`;
- a scratch `HOME` and `CLAUDE_CONFIG_DIR`;
- `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`.

So no account, keychain or real model is used. The flags match `runtime/claude.py`: `-p`, stream-json in
and out, `--permission-mode manual`, `--permission-prompt-tool stdio`, `--permission-prompts host`,
`--setting-sources ''`, `--settings` with `permissions.ask` for every tool and the sandbox block. The cwd is
a fresh `git init` repo.

Only the main model was called (no helper calls to another model, no `count_tokens`).

### Request: can_use_tool

One request per tool call, before the tool runs:

```json
{"type":"control_request","request_id":"<uuid>","request":{
  "subtype":"can_use_tool","tool_name":"Edit","display_name":"Edit",
  "input":{"file_path":"/abs/repo/hello.txt","old_string":"hello","new_string":"hello world","replace_all":false},
  "description":"hello.txt",
  "matched_ask_rule":{"source":"flagSettings","tool_name":"Edit"},
  "tool_use_id":"toolu_02"}}
```

Write: same shape, `input` = `{file_path, content}`.

Bash:

```json
{"subtype":"can_use_tool","tool_name":"Bash","display_name":"Bash",
 "input":{"command":"echo from-bash > bash.txt","description":"write bash.txt"},
 "description":"write bash.txt",
 "blocked_path":"/abs/repo/bash.txt",
 "matched_ask_rule":{"source":"flagSettings","tool_name":"Bash"},
 "tool_use_id":"toolu_03"}
```

Optional fields seen:

- `blocked_path`: the CLI's guess of the file a Bash command writes. It was set for redirections, both
  inside and outside the cwd.
- `decision_reason: "Path is outside allowed working directories"` with `decision_reason_type: "workingDir"`:
  Write outside the cwd.
- `decision_reason_type: "rule"`, `decision_reason_rule_source`, `server_policy_ask_only`: in place of
  `matched_ask_rule` on one Bash request.

Treat all of these as hints. Do not base decisions on them.

### Reply

Allow (the CLI runs `updatedInput`, not the original input):

```json
{"type":"control_response","response":{"subtype":"success","request_id":"<same uuid>",
  "response":{"behavior":"allow","updatedInput":{...}}}}
```

Deny:

```json
{"type":"control_response","response":{"subtype":"success","request_id":"<same uuid>",
  "response":{"behavior":"deny","message":"Denied by spike host."}}}
```

After a deny, the model gets `{"type":"tool_result","content":"Denied by spike host.","is_error":true}`.
The turn continues; the model can try again. The final `result` lists every denial in
`permission_denials: [{tool_name, tool_use_id, tool_input}]`.

### Gotchas

1. **The CLI normalises input before asking.** The model sent Edit without `replace_all`; the request had
   `"replace_all": false`. Authorize and echo `request.input`, never the `tool_use` block's input. Match a
   request to its `tool_use` by `tool_use_id`, not by comparing input.
2. **`updatedInput` is honoured.** Allowing a Write with changed `content` wrote the host's content. So
   Interspace must echo exactly what it authorized. A rewrite is possible but should never be needed.
3. **`permissionMode` in `system/init` is `"default"`** when the CLI is started with
   `--permission-mode manual`. `runtime/claude.py:530` requires `permissionMode == "manual"`, so the real CLI fails the handshake. It must accept
   `default` (or compare against the observed alias).
4. **`result.modelUsage` and `total_cost_usd` are cumulative for the process.** In a 2-turn session,
   turn 1 `result.usage` = 80 in / 40 out and `modelUsage` = 80 / 40. Turn 2 `result.usage` = 10 / 5 but
   `modelUsage` = 90 / 45. `runtime/claude.py:133` sums `modelUsage`, so it over-charges from turn 2.
   Use `result.usage` (per turn), or subtract the previous `modelUsage`.
5. **The CLI creates `.claude/.cc-writes/`** (an empty directory, mode 0700) in the cwd. Git ignores empty
   directories, so it does not show in `git status`. Exclude `.claude/` from any merge or diff walk that
   lists the file system rather than using git.
6. `system/init` also lists `agents`, `plugins` (three `builtin` plugins even with `--setting-sources ''`)
   and `capabilities`. The `tools` list was exactly the `--tools` set. The API request carried one extra
   tool, `DeferredToolPlaceholder`, which never appears in init.

### Containment

Results with sandbox on (`sandbox.enabled: true`, `allowUnsandboxedCommands: false`). The outside folder was
under `~/Library/Caches` (not under TMPDIR).

| Call | Host answer | Result |
|---|---|---|
| Write `repo/hello.txt` | allow | written |
| Edit `repo/hello.txt` | deny | not changed; model gets the error |
| Edit `repo/hello.txt` | allow | changed |
| Bash `echo ... > bash.txt` (cwd) | allow | written |
| Write `<outside>/escaped.txt` | allow | **written outside the repo** |
| Bash `echo ... > <outside>/bash-escaped.txt` | allow | blocked by the OS sandbox: `operation not permitted`, exit 1 |
| Write `repo/relative-check.txt` with rewritten content | allow (modified `updatedInput`) | host content written |

With sandbox off, the outside Bash write also landed.

With the outside folder under TMPDIR (first run), the sandboxed outside Bash write also landed: the Bash
sandbox allows writes to temp folders.

Conclusions:

- **Edit, Write and NotebookEdit are not sandboxed.** The CLI only flags an outside path
  (`decision_reason_type: "workingDir"`); an allow from the host writes it. Interspace must check every
  `file_path` itself before it allows: make the path absolute against the worktree, resolve symlinks
  (`os.path.realpath` of the parent folder for a new file), require it inside the agent's worktree, and
  refuse `.git/` inside it. Not tested: a symlink inside the repo that points outside. The realpath check
  covers it.
- **Bash writes are contained by the macOS sandbox** to the cwd (plus temp folders), even when the host
  allows. Keep `sandbox.enabled: true` and `allowUnsandboxedCommands: false`. Refuse
  `dangerouslyDisableSandbox: true`. Temp-folder writes are a known gap: consider giving each agent its own
  `TMPDIR` inside its worktree's scratch folder.
- So write mode needs these changes: set `READ_ONLY = False`, map Edit/Write/NotebookEdit to a `file_write`
  scope request with the resolved path, and deny anything outside the worktree before `authorize`.

## Not done, needs the user's approval

1. A real Codex device sign-in in a throwaway home: `codex_account_probe.py --home <tmp> device-login`.
   Then `logout`, then delete the folder. This shows the real `verificationUrl` and `userCode` shapes, which
   store the token lands in, and `account/read` after sign-in. Then repeat once in the real
   `<storage>/codex-home` for actual use.
2. Optional: one real Claude turn in Snack Picker's worktree. This would only confirm model behaviour; the
   fake model already proved the protocol.
