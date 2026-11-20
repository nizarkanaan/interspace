# Provider usage limits in the sidebar

Date: 2026-11-20
Status: approved in conversation. The user lifted the AGENTS.md rule against showing remaining account allowance, for provider-reported limits only.
Size: small change

## Intent

Show, in the sidebar, how much of each provider's usage limits is used, the way the providers' own apps do. This lets you see when you are close to a limit before starting work.

## What the providers report

The runtimes already received these readings and dropped them.

- **Codex** sends the `account/rateLimits/updated` notification. It carries `rateLimits.primary` and `rateLimits.secondary`, each a window with `usedPercent`, `windowDurationMins` and `resetsAt` (epoch seconds).
- **Claude Code** sends the `rate_limit_event` message. It carries a `rate_limit_info` with:
  - `status`: `allowed`, `allowed_warning` or `rejected`;
  - `rateLimitType`, for example `five_hour` or `seven_day`;
  - `resetsAt` (epoch seconds);
  - optionally `utilization`.

Both arrive only while an agent of that provider runs. The sidebar therefore shows the latest reading and its time, never a live figure.

## Design

- **Capture.**
  - The runtimes pass each reading to `ctx.report_limits(raw)`.
  - `limits.py` turns it into a list of windows, `{label, used_percent?, status?, resets_at?}`, and keeps only values the provider gave. Values that are out of range or of the wrong type are dropped.
  - The scheduler stores the reading as `state['provider_limits'][provider] = {at, windows}`, keeping the latest reading for each window label, and publishes it as `state.provider_limits`.
- **Sidebar.** A **Usage** block above Running now and Settings shows, for each provider with a reading:
  - its name and "as of 2:14 pm";
  - each window on one line, for example "5-hour limit · 42% used · resets 5:10 pm", with a thin bar when a percentage was reported;
  - Claude statuses in words: Within the limit, Near the limit, Limit reached.

  The bar turns oxblood at 80% used, or at Near the limit or Limit reached. With no reading yet, it says "Shows after an agent runs."
- **Never shown:** money, a limit's absolute size, or any figure the provider did not send.

## Calls made by the designer

- Claude's `utilization` is read as a fraction of 1 when it is between 0 and 1, and as a percentage when it is between 1 and 100.
- Readings are kept across restarts, with their time shown.
- The bar turns oxblood at 80% used.
