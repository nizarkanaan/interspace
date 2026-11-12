# Claude Code as a second provider

Date: 2026-11-11. Status: draft; the user answered the four open decisions on 2026-11-11 (recorded below). Not yet approved for commit; nothing implemented.
Base: this branch (`57eaa4f`), which contains the approved [token budget spec](2026-11-11-token-budgets-design.md) and `app/backend/budget.py`. Implementation waits until token budgets land on `interspace/token-budgets` and is stacked on top of them.

## Intent

The user compared Interspace with Paperclip and chose to stay single-person and local. Their feature order is: per-task token budgets, then **Claude Code as a second model provider**, then goals, more roles, approved routines, skills and evals, and read-only integrations.

This spec covers only the second item. Each Claude job is an ephemeral `claude -p` process, run under the user's own credentials. It mirrors the existing `codex exec` jobs:
- text-only;
- a JSON result validated against a schema;
- one job per call, with no retries;
- a four-minute deadline;
- cancellation by process group.

Interspace never reads, stores or relays Anthropic credentials.

## User decisions (2026-11-11)

1. **Sign-in: the user's own Claude subscription only.** Interspace jobs run only when `claude auth status` reports `authMethod` `claude.ai`. API keys, API key helpers, long-lived tokens and cloud providers are shown as connected but **not enabled for Interspace jobs**. The assistant had recommended API key or cloud provider only. See the residual risk below.
2. **Sign-in UI: the app launches the CLI's own login.** Interspace runs `claude auth login` as it runs Codex's device flow, within the limits under Connection check and sign-in.
3. **First-version scope: read-only roles plus the Web searcher.** Planner, Researcher, Reviewer, synthesis and Web searcher can run on Claude Code. The Fix & test (Python) roles stay on Codex.
4. **Choice granularity: per assignment.** Each task has a default provider and model, each assignment can override it, and mixed teams are allowed from the start.

The default model and effort are still the assistant's proposal: a full model ID chosen at task creation from a short list (`claude-sonnet-5-5`, `claude-opus-5-5`, `claude-haiku-5-5`), with default effort `low` for parity with Codex jobs. Everything else in this spec is also the assistant's proposal, open to amendment.

**Residual risk of decisions 1 and 2.** Anthropic's terms were verified on 2026-11-11 (sources below). They allow an end user to sign in to the unmodified Claude Code binary with their own subscription. They also say developers' products should use API keys, and that third-party developers may not "offer Claude.ai login into their own applications". Interspace launching the CLI's login is closest to the first case, because the binary, the browser flow and the account all belong to the user. But the documentation does not settle it. Anthropic "reserves the right to take measures to enforce these restrictions", and subscription usage limits assume "ordinary, individual usage". So:
- Interspace does not claim that the subscription covers its automated jobs.
- Settings says this plainly (see Disclosure).
- The user may ask Anthropic for a definitive answer.
- If Anthropic's terms or the CLI change, the API-key route can be enabled later by a new decision, without other design changes.

## Verified facts (checked 2026-11-11)

These facts come from official Anthropic documentation and from local `claude --help` of Claude Code `2.1.322`. Implementation must recheck them against the installed version, because these flags change quickly.

### Authentication and terms

Sources:
- [Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance), section "Authentication and credential use";
- [Authentication](https://code.claude.com/docs/en/authentication);
- [Run Claude Code programmatically](https://code.claude.com/docs/en/headless).

All were checked on 2026-11-11.

- **Subscription sign-in (OAuth).** The legal page says it "is intended exclusively for purchasers of Claude Free, Pro, Max, Ultra, Team, and Enterprise subscription plans and is designed to support ordinary use of Claude Code and other native Anthropic applications".
- **Developers' products.** On the same page, developers "should use API key authentication through Claude Console or a supported cloud provider". Anthropic "does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, Max, or Ultra plan credentials on behalf of their users". Developers "may not collect, store, or intermediate Claude.ai credentials or session tokens".
- **The end-user carve-out.** The same section says the restriction does not "prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription".
- **Usage limits.** Advertised Pro/Max/Ultra usage limits "assume ordinary, individual usage of Claude Code and the Agent SDK".
- **Products that run Claude Code.** Running Claude Code inside a product requires an unmodified binary. It must not remove or restrict any built-in authentication method. Each end user must authenticate with their own key, subscription or cloud credential, billed to them.
- **Credential precedence.** In order:
  1. cloud provider (`CLAUDE_CODE_USE_BEDROCK`/`_VERTEX`/`_FOUNDRY`);
  2. `ANTHROPIC_AUTH_TOKEN`;
  3. `ANTHROPIC_API_KEY`, always used in `-p` mode when present;
  4. `apiKeyHelper`;
  5. `CLAUDE_CODE_OAUTH_TOKEN`;
  6. Anthropic profiles;
  7. the subscription login from `/login`.

  On macOS, credentials are stored in the Keychain.
- **Status check.** `claude auth status` prints JSON and exits 0 when signed in and 1 when not. Its `authMethod` field is one of `none`, `claude.ai`, `oauth_token`, `api_key`, `api_key_helper` or `third_party`.
- **Sign-in commands.** `claude auth login` signs in with a subscription. `claude auth login --console` signs in "with Anthropic Console for API usage billing instead of a Claude subscription". Both complete in the browser through Anthropic's own flow.
- **`--bare` mode.** In bare mode the CLI "never reads OAuth credentials or the system keychain". So `--bare` works only with `ANTHROPIC_API_KEY` or `apiKeyHelper`, or with a cloud provider.
- **`claude setup-token`.** It prints a one-year subscription token for the caller to store. Interspace must never run it, because it would then be collecting a Claude.ai credential.

**Interpretation, and the limit of what was verified.** Interspace is a local app for one person on their own machine. It would drive the user's own unmodified `claude` binary under the user's own sign-in, and never touch the token. That is closest to the documented end-user carve-out. However, the terms also say developers' products should use API keys, and Interspace is a product that labmates may build for themselves. The documentation does not settle this case explicitly, so **this spec does not claim that a Claude subscription covers Interspace's automated jobs**. The only methods documented for programmatic use by a product are:
- an Anthropic API key, through `claude auth login --console`, `ANTHROPIC_API_KEY` or `apiKeyHelper`;
- a supported cloud provider: Bedrock, Google Cloud's Agent Platform (Vertex) or Foundry.

For a definitive answer, the user can ask Anthropic, as the legal page suggests. The user chose subscription only; see User decisions above.

### Headless invocation

Sources:
- [CLI reference](https://code.claude.com/docs/en/cli-reference);
- [headless](https://code.claude.com/docs/en/headless);
- [structured outputs](https://code.claude.com/docs/en/agent-sdk/structured-outputs);
- [tools reference](https://code.claude.com/docs/en/tools-reference).

All were checked on 2026-11-11.

| Need | Flag or mechanism | Notes |
| --- | --- | --- |
| Non-interactive | `-p` (`--print`), with the prompt on stdin | Stdin is capped at 10 MB, far above Interspace's 240,000-character context. |
| Streamed JSON events | `--output-format stream-json --verbose` | Emits `system/init` first, then `assistant`/`user` messages and a final `result`. |
| Schema-constrained output | `--json-schema '<schema>'` | The result carries `structured_output`. This uses an internal tool named `StructuredOutput`: the stream shows a `tool_use`/`tool_result` pair, and the CLI re-prompts on schema mismatch. If it fails, the subtype is `error_max_structured_output_retries`. A `success` result without `structured_output`, or with `is_error: true`, is a failure. The schema is validated as draft-07. |
| No built-in tools | `--tools ""` | This does not remove MCP tools. |
| No MCP | `--strict-mcp-config` with no `--mcp-config`, plus `--disallowedTools "mcp__*"` | Belt and braces. |
| No settings or CLAUDE.md | `--safe-mode` and `--setting-sources ""`, or alternatively `--restricted` | `--safe-mode` disables CLAUDE.md, skills, plugins, hooks, MCP servers, custom agents, output styles and auto memory, while auth works normally. `--restricted` removes code-running tools and WebFetch, ignores user/project/local settings and confines file tools. Managed (policy) settings still apply under both. Implementation must check that `--setting-sources ""` is accepted. |
| No skills or commands | `--disable-slash-commands` | |
| Own instructions only | `--system-prompt '<Interspace role preamble>'` | Replaces Claude Code's default coding-agent prompt. That removes its environment, git and working-directory sections, and lowers fixed overhead. |
| No session saved | `--no-session-persistence` | Print mode only. |
| Nothing prompts | `--permission-mode dontAsk --permission-prompts none` | Anything that would ask is denied, and the denial appears in `permission_denials`. |
| Bounded turns | `--max-turns N` | Leaves room for `StructuredOutput` re-prompts and, for search, a few `WebSearch` calls. The exact value comes from implementation measurement. |
| Model | `--model <full model ID>` | Use a full ID such as `claude-sonnet-5-5`, never an alias, so an approval binds an exact model. Do not pass `--fallback-model`. |
| Effort | `--effort low` to `max` | Plays the role of Codex's `model_reasoning_effort="low"`. |
| Working directory | A fresh, empty, app-owned directory per job | Unlike Codex, which runs every non-search job in one shared `storage/provider` directory. The empty directory gives no project `.claude/`, `.mcp.json` or CLAUDE.md even if a flag is missed. |
| Cancellation | SIGINT ends the turn; SIGTERM exits 143 with no result | See Cancellation below. |
| Web search | `--tools "WebSearch" --allowedTools "WebSearch"`, Web searcher only | `WebSearch` runs on Anthropic's backend and "returns result titles and URLs" without fetching pages. It is not available on Amazon Bedrock. WebFetch stays off: it would fetch pages from the user's machine. |

**Invocation for a text-only job** (planner, Researcher, Reviewer, synthesis):

```
claude -p --output-format stream-json --verbose \
  --json-schema <schema> --model <approved model ID> --effort <level> \
  --system-prompt <role preamble> --tools "" --disallowedTools "mcp__*" \
  --strict-mcp-config --safe-mode --setting-sources "" --disable-slash-commands \
  --no-session-persistence --permission-mode dontAsk --permission-prompts none \
  --max-turns <N>
```

It runs with `cwd` set to a new empty directory, the prompt on stdin, `start_new_session=True` and an allowlisted environment.

The Web searcher uses the same command, with `--tools "WebSearch" --allowedTools "WebSearch"` in place of `--tools ""`.

**Environment.** Pass only an explicit allowlist: `HOME`, `PATH`, `TMPDIR`, `LANG`, `USER`, and no credential variables. A subscription login is read from the Keychain by the CLI itself. `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CODE_USE_*` and `ANTHROPIC_PROFILE` are never passed, so they cannot outrank the subscription login. Because subscription login is required, `--bare` cannot be used: it never reads OAuth credentials. A Finder-launched app does not inherit shell variables. This allowlist also stops a stray `ANTHROPIC_API_KEY` from silently changing which account is billed.

**Binary discovery.** Look for `claude` in `~/.local/bin` (the native installer), `/opt/homebrew/bin`, `/usr/local/bin` and on `PATH`, then resolve the path. Only an official installation is supported, as for Codex.

## Event validation

The adapter checks the stream as strictly as the Codex adapter does:

1. **`system/init`, before any model request.**
   - `tools` must be exactly the expected set: `StructuredOutput` for text jobs, plus `WebSearch` for the Web searcher.
   - `mcp_servers` must be empty.
   - `model` must equal the approved model ID.

   Any difference stops the process before it makes a model request, so no tokens are spent.
2. **`assistant` messages.** A `tool_use` block named anything other than `StructuredOutput` (or `WebSearch` for the Web searcher) fails the job with "Unexpected tool activity". So does a `parent_tool_use_id` other than `null`, which would mean a subagent.
3. **`result`.**
   - The job is accepted only when `subtype == "success"`, `is_error` is false, `permission_denials` is empty and `structured_output` is a JSON object.
   - `error_max_structured_output_retries`, `error_max_turns` and `error_during_execution` all fail the job, with no retry.
   - `modelUsage` must name only the approved model. Any other model, for example from an automatic model fallback, fails the job closed. Implementation must confirm whether Claude Code makes helper requests to other models under these flags.
4. **`system/api_retry`.** Claude Code retries some failed API requests itself, within the same job. These retries are recorded as Activity events and stay inside the four-minute deadline. Interspace's own "no retries" rule is about re-dispatching a job, and is unchanged. Codex also retries transport internally.
5. **Limits.** The existing caps carry over: 2,000,000 bytes of output and 100 search events. URL validation reuses the existing `search_event` and `orchestration.py` checks.

**Search provenance.** Each `WebSearch` `tool_use` gives the query. The matching `tool_result` gives the result titles and URLs. Only URLs from those results count as observed URLs, as with Codex's `web_search` items. The `tool_result` text format is not documented as stable, so:
- parse it defensively with bounded size and nesting;
- fail closed when it cannot be parsed;
- keep the parser covered by a fixture recorded from one approved live call.

## Usage and the token budget charge

Sources:
- [Track cost and usage](https://code.claude.com/docs/en/agent-sdk/cost-tracking);
- [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).

Both were checked on 2026-11-11.

Anthropic's usage fields are **disjoint**. `input_tokens` counts only uncached input, the tokens "after the last cache breakpoint". The documented total is `cache_read_input_tokens + cache_creation_input_tokens + input_tokens`. Output tokens, including thinking, are `output_tokens`.

That differs from Codex, where cached input is already inside `input_tokens`. If Interspace reused `budget.charge()` as written, it would undercount Claude calls badly, because Claude Code caches its prompt prefix automatically.

**Proposed rule.** It counts each token exactly once:

```
claude charge = input_tokens + cache_creation_input_tokens + cache_read_input_tokens + output_tokens
```

- **Source of the numbers.** Read them from the `result` message, summing `modelUsage` entries (`inputTokens`, `cacheCreationInputTokens`, `cacheReadInputTokens`, `outputTokens`). `modelUsage` includes every request in the job. Fall back to `result.usage` only when `modelUsage` is absent.
- **Do not sum per-message usage.** Per-message `output_tokens` is a placeholder, and messages repeat when one response produces several parts.
- **Unknown usage.**
  - A result with zeroed usage after `error_during_execution` counts as **unknown** and is charged its estimate, per the budget rule.
  - A process killed before `result` also has unknown usage and is charged its estimate.
  - A missing field, or a negative or non-integer value, makes the whole charge unknown. No partial sum is used.
- **Cache tokens count in full**, like Codex cached input. Anthropic prices cache reads lower, but budgets count tokens, not money.
- **Cost fields are discarded.** `total_cost_usd` and `costUSD` are never stored or shown. The budget spec forbids money figures, and these are client-side estimates.
- **Web searches are not tokens.** `server_tool_use.web_search_requests` is recorded as a count. It is not charged as tokens, and the UI does not claim a price for it.

**Changes to `budget.py`.**
- `charge(usage)` becomes `charge(usage, provider)`, with a `codex` rule and a `claude_code` rule.
- Each ledger entry stores `provider`, `model` and `charge_rule` (`codex:input+output` or `claude_code:input+cache_creation+cache_read+output`), so old entries stay interpretable.
- Entries without `provider` are Codex.
- `estimate()` gets a per-provider overhead constant. Until calibrated from approved live calls, `claude_code` uses the Codex value of 12,000 tokens, which over-estimates. With `--system-prompt` replacing the default prompt, the real overhead should be lower. The calibration evidence will be recorded.

## Product shape

### Provider and model choice

- **Settings → Connections** lists **Codex (OpenAI)** and **Claude Code (Anthropic)**, each with its own status and controls.
- **Each task has a default provider and model,** chosen on the New task form next to the allowance and budget. The initial default is Codex, so existing behaviour is unchanged.
- **Planning.** The task's planning and conversation calls use the task default.
- **Each assignment has a provider and model.** The Orchestrator proposes them from the task default. The user changes them by asking in chat, which produces a new proposal, as with any plan change. That allows mixed-model teams, for example a Claude Reviewer checking Codex Researchers. Per-assignment choice ships in the first version (user decision 4). Only read-only roles may name Claude Code; the Fix & test roles are Codex-only (user decision 3).
- **Untouched by this feature:** project conversation, Workspace advice and legacy two-stage reviews stay on Codex. Their scope does not grow.
- **No silent switching.** If a provider is not connected, its jobs fail. Nothing falls back to the other provider.

### Binding into exact approvals

- Every new plan task carries `provider` and `model`, and plan `limits` carries the default `effort` per provider. These fields are inside the existing `plan_digest`, so changing any of them invalidates Start.
- A change run's check approval re-binds the remaining calls' providers and models, with `token_budget`.
- Changing a task's default provider or model clears an unstarted plan, as changing the allowance or budget does.
- `team.invoke` dispatches each job to the provider named in its plan task. Before launch, it checks that this provider is connected and that the CLI reports the approved model in `system/init`.
- **Existing records keep their digests.** Plans without `provider` are Codex, and are validated exactly as saved. The new fields appear only in newly created plans, under `policy_version` 3.
- **Plan rows** show provider and model per assignment. **Activity and Result** show, for each call, its provider, model and charge, with the charge rule available on inspection.

### Connection check and sign-in

- **Check connection** runs `claude --version` and `claude auth status` with a 10-second timeout, never a model call. It shows:
  - whether the CLI was found;
  - signed in or not;
  - the `authMethod` in plain words: "Claude subscription", "Anthropic API key (Console)", "API key helper", "Cloud provider" or "Long-lived token".

  It never shows the email or organisation. The JSON is reduced to `authMethod` and the exit code before anything is stored or logged.
- **Accepted method.** Only `authMethod` `claude.ai` enables Claude jobs (user decision 1). Any other method is shown as connected but **not enabled for Interspace jobs**, with the reason. Each job re-checks this before launch, because the sign-in can change between check and Start.
- **Sign-in.** **Sign in to Claude** runs the unmodified `claude auth login`, with no `--console` and no `--email`, in its own process group (user decision 2). Interspace shows the CLI's ANSI-stripped output, as it does for Codex, so the user can open the printed Anthropic URL. Sign-in completes in Anthropic's own browser flow. Interspace has a 180-second deadline and a Cancel action, then runs Check connection.
- **Limits on the launched login.** Interspace does not intermediate credentials:
  - If the CLI asks for a pasted login code, Interspace does not accept or relay it. It stops the process and tells the user to run `claude auth login` in Terminal instead.
  - Interspace never runs `setup-token`, never reads the Keychain or `~/.claude/.credentials.json`, never stores a token and never passes `--email`.
  - Implementation must first confirm, without a model call, that `claude auth login` completes its browser redirect with stdin closed and no terminal. If it does not, the button becomes the Terminal instructions.
- **Disclosure** in Settings: "Claude jobs use the Claude subscription that Claude Code is signed into, and count against its usage limits. Anthropic's terms do not confirm that a subscription covers automated jobs from third-party apps such as Interspace. Interspace shows tokens only, never money or remaining allowance."

### Failure and cancellation

- **Failures** behave like Codex failures: the job is reserved before launch, there is no retry, the run stops at a required failure, completed artifacts are kept, and unknown usage is charged its estimate. Error messages are mapped from the `api_retry`/`result` categories:
  - `authentication_failed`, or `Login expired`: sign in again;
  - `rate_limit` or `billing_error`: account limit or billing;
  - `model_not_found`: the model is not available to this account.

  No raw output is stored.
- **Cancellation, timeout and Quit.** Send SIGINT to the owned process group so Claude Code ends the turn and may still emit a `result` with usage. Wait at most 2 seconds, then send SIGTERM and SIGKILL as the Codex adapter does now. A `result` captured inside that grace period settles the reservation with reported counts; otherwise the estimate is charged. The job is still recorded as cancelled, and the result is never accepted.
- **Restart** marks the job interrupted and charges the estimate, unchanged.

### What stays Codex-only

- Project conversation, Workspace advice and legacy revision rounds.
- Fix & test (Python) roles in the first version (user decision 3). All editing roles are text-only JSON jobs, so they could move later without changes to checks or Apply.
- Nothing about checks, the restricted Python runtime, Apply or journals changes. The provider never executes or writes.

## Code ownership

- `provider.py` keeps `CodexProvider` and gains `ClaudeCodeProvider` with the same `status`/`run`/`search` interface. The process loop (deadline, selector, output cap, group stop) is now needed by two adapters, so it moves into one private helper that both adapters use. No generic plugin framework is added.
- `service.py` holds one provider per name in a small dict, built at the composition root, instead of the single `self.provider`.
- `team.invoke`, `Application.call` and `change_team` pass the plan task's provider name.
- `budget.py` gains the per-provider charge and estimate described above.
- The UI adds the Connections row, the New task provider/model fields and the per-assignment labels. Projections from the backend carry provider/model names only, never raw CLI output.

## Out of scope

- Direct Anthropic API or SDK calls. Interspace drives only the user's own `claude` CLI, so it adds no SDK dependency and stores no key.
- Shared or app-owned credentials.
- Money figures, `--max-budget-usd`, prices or remaining-allowance claims.
- Claude Code's own tools, MCP, subagents, skills, sessions or `--resume`.
- Automatic provider fallback, retries and resume.
- Changing the call ceilings or deadlines.
- Providers other than Codex and Claude Code.

## Verification

**Test-first, with fake providers only.** A fake `claude` executable replays recorded `stream-json` fixtures. The tests cover:
- the exact flag list and the allowlisted environment;
- refusal at `system/init` on unexpected tools, MCP servers or model;
- tool-use rejection;
- `structured_output` failure subtypes;
- `permission_denials`;
- the model mismatch in `modelUsage`;
- the 2 MB output cap;
- the deadline;
- the SIGINT grace period followed by group kill;
- the charge rule, including disjoint cache fields, zeroed and missing usage, and no double count across repeated message IDs;
- search provenance parsing, and refusal of malformed results;
- plan digest binding for provider/model/effort, and unchanged digests for existing plans;
- mixed-provider team dispatch;
- a disconnected provider failing with no fallback;
- auth-method gating (only `claude.ai` enables jobs) and the re-check before each launch;
- the launched login: deadline, cancel, and stopping on a pasted-code prompt;
- the absence of credential-file reads, which is checked by an assertion over every path the adapter opens.

Browser journeys cover the Connections row, the New task fields, plan labels, light/dark appearance and widths 320–1280. Both backend suites run on Python 3.14 and Apple 3.9.

**Live acceptance**, only with calls the user approves at that time:
- one connection check;
- one text-only Reviewer job;
- one Web searcher job, to record the provenance fixture and calibrate overhead;
- one cancellation, to confirm whether usage arrives after SIGINT.
