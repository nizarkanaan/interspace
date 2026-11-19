# Research workspace: frozen interface contracts (Wave 0A)

Date: 2026-11-19. Status: frozen by the coordinator for Wave 1, under the plan the user approved on 2026-11-19: `docs/superpowers/plans/2026-11-19-research-workspace.md`. API facts come from spike 0B (`spike-0b.md`). If a fact there contradicts a value here, the stream keeps the shape and changes the value, and reports the change.

| Contract | File | Producers | Consumers |
| --- | --- | --- | --- |
| Research tools, normalized record, source modules, citation checker | [tools.md](tools.md) | 1B (sources), 1C (tools, checker) | 1C, 1D, 2A |
| Keychain bridge, Research sources settings methods | [credentials.md](credentials.md) | 1A | 1B, 1D |
| Scope `research` key, tasks without a project, outputs, events | [tasks.md](tasks.md) | 1C | 1D, 2A, 2B |

Everything in `docs/superpowers/specs/multi-provider/` and the kept parts of `docs/superpowers/specs/agentic-spaces/` still applies.

## Rules every stream keeps

- **Keys never reach agents, the UI, logs, audit records, events, state or tool results.** Only the backend's source clients read them, from `research.credentials`. A test proves this (tasks.md, "Key safety").
- **Network only from source clients**, through `research/http.py`:
  - https only, to that source's fixed host allowlist;
  - no proxies; same-host redirects only;
  - a 10 MiB response cap;
  - a generic `User-Agent: Interspace/<version> (research)`, with no user identity except where the source's documented polite-pool or `email` parameter requires the user's own configured email.
- **All research results are untrusted.** They reach agents wrapped as `<untrusted-content>` (as the bridge does for `effect: read`), and the UI renders them as text, never as HTML. Links are shown only for `https:` URLs.
- **Routine tests never touch the network.** Source clients are tested against recorded fixtures in `tests/research/fixtures/<source>/` through a fake HTTP layer. Live calls happen only in explicitly approved steps.
- **Tokens only, never money.** Research calls cost no tokens. Interspace counts calls per source and never shows prices or remaining allowances.
- Python 3.9 and the standard library only; plain JSON dicts validated at boundaries; user-visible errors subclass `ValueError` and are safe to show.
