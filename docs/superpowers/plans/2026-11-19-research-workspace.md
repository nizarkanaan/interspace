# Research workspace: research sources and citation checking

Date: 2026-11-19. Status: approved by the user on 2026-11-19. Branch: `interspace/research-workspace`, from `main` (`ceba452`).

## Context

Interspace (local Mac app; `main` at `ceba452`, pushed) runs Claude Code and Codex agents under one Orchestrator. The Orchestrator proposes mixed-provider teams, you approve them, and they run in parallel, with Review and Merge for code.

The user now wants it to **feel like a research environment** while **keeping coding**:
- Agents search and read scholarly sources.
- Each user enters their **own API keys**.
- References are checked automatically, to reduce hallucinated citations. This was asked for by the user's professor for a talk next week.

User decisions (2026-11-19):
1. **Coding stays.**
2. **First sources:** Semantic Scholar, OpenAlex, arXiv, Crossref, Unpaywall, plus a built-in **citation checker**. More sources follow later as more modules of the same shape: CORE, PubMed/Europe PMC, DBLP, OpenReview, ORCID, Zotero, Hugging Face/Zenodo, bioRxiv.
3. **Tasks without a project.** Research tasks may start with no project folder. Coding tasks still need a project.
4. **Saving results.** A finished research task gives you a report plus a verified BibTeX file in the app, viewable and downloadable.

API facts, to confirm in the 0B spike:
- **Semantic Scholar:** key optional, sent in the `x-api-key` header, about 1 request/s with a key; the shared pool without a key is often throttled.
- **OpenAlex:** an API key is needed since February 2026, with a free daily usage allowance. Lookup by DOI or ID is free; search is metered.
- **Crossref and Unpaywall:** an email address only.
- **arXiv:** no key, about one request per 3 s.

## Design

**Keys never reach agents.** The backend calls the research APIs itself. Agents get Interspace tools through the existing MCP bridge (`runtime/mcp_bridge.py`), and every result comes back wrapped as `<untrusted-content>`.

**Research tools** (all `effect: read`, served to the Orchestrator *and* to every subagent when the task scope enables research):

| Tool | Does |
|---|---|
| `research_search {query, sources?, year_from?, year_to?, limit}` | Searches the enabled sources and returns one list of papers, merged and de-duplicated by DOI, arXiv ID or normalized title |
| `research_paper {id}` | Full record for a DOI, arXiv, Semantic Scholar or OpenAlex ID: abstract, venue, counts, links |
| `research_citations {id, direction: citations\|references, limit}` | Snowballing, from Semantic Scholar with OpenAlex as fallback |
| `research_fulltext {id}` | A legal open PDF or landing link, from Unpaywall or arXiv. Links only; no downloading in v1 |
| `research_bibtex {ids}` | BibTeX for each ID, from Crossref (DOI content negotiation) or arXiv |
| `verify_citations {references: [{title, authors?, year?, doi?, raw?}]}` | **Citation checker** (below) |

**Normalized paper record** (`research/records.py`): `{title, authors, year, venue, doi, arxiv_id, s2_id, openalex_id, abstract, citation_count, url, oa_url, sources:[…]}`.

**Citation checker** (`research/citations.py`) is deterministic and uses no model. For each reference:
1. If it has a DOI, look it up in Crossref and OpenAlex. Otherwise search by title in Semantic Scholar and OpenAlex.
2. Compare: normalized title similarity of at least 0.9, year within ±1, first-author surname matching.
3. Report one of `verified`, `mismatch` (listing which fields), `not_found`, or `retracted` (from Crossref `update-to` and OpenAlex `is_retracted`), together with the matched record.

The Orchestrator prompt requires calling it before any answer that cites papers. The result appears as a **citation report card** and feeds the verified BibTeX.

**Sources** (`app/backend/research/`): one module per source, all following the same pattern:
- `search`, `paper`, `citations` where the source supports them;
- `status()` reporting whether its key or email is set and whether a test call succeeds.

Shared pieces:
- `research/http.py`: restores the deleted `Http` client from `git show fe65e32^:app/backend/spaces/base.py` (https only, no proxies, same-host redirects, 10 MiB cap, error types), plus a per-source rate limiter and 429/Retry-After backoff.
- **A local response cache:** under Application Support `research-cache/`, 7-day TTL, so repeated calls don't use up your quota.

**Credentials.** The Keychain bridge is restored from `fe65e32` with:
- Swift `ResearchKeychain`, service `app.interspace.research`;
- accounts `semantic_scholar`, `openalex`, `crossref_email`, `unpaywall_email`;
- the `keychain`/`keychain_reply` pipe messages and the `bridge_hello` handshake;
- a 64 KiB cap, kept on this device only;
- backend `research/credentials.py`.

Keys are write-only from the UI. They are never sent back to the UI, logged, audited, or included in events.

**Scope and audit:**
- New category `research`: the request is `{source, tool}`, and the query text is left out of the audit record.
- New scope key `research: {sources: {name: allow|ask|off}}`. A scope with the key missing counts as "off", so old digests stay valid.
- New scopes default to `allow` for every source you have configured.
- `scheduler._authorize` decides each research call. The audit log gets a `decision` record plus an `action` record with the outcome.
- `REQUEST_FIELDS` gains `research: ('source','tool')`.
- No tokens are used, so there's no budget charge. Each task shows a count of research calls per source, never money.

**Tool dispatch.** `RunContext.tools()` becomes a list built per session:
- orchestration tools for the root Orchestrator;
- research tools when `scope.research` enables any source;
- Claude file tools stay as they are.

A single `RunContext.call_tool(name, args)` routes to `orchestrate`, to `research.dispatch`, or to file tools. Today's dispatch is in `scheduler._orchestrate` (`scheduler.py:1268`) and the Claude `_BridgeTarget` (`claude.py:1050`). Codex already passes `ctx.tools()` through (`codex.py:283`).

**Tasks without a project.**
- A task with `project_id: null` runs research-only: no workspace clone, no file or command tools, and no write roles in its teams.
- The scheduler skips `Workspaces` for it, and Review/Merge are hidden.
- These tasks sit under a **Research** entry in the sidebar, next to projects.

**Outputs.** The scheduler stores the final report and the verified `.bib` under `tasks/<id>/outputs/`. New methods `task_outputs` and `task_output_save` handle viewing and saving: saving goes through a save panel in Swift, and the backend never writes outside app data.

**Roles.** Keep the current five roles and add **`citation_checker`**, a read role whose default provider is Codex. It is added in all six places the role list is copied: `routing.py:9` and its defaults, `tasks.py:33`, `orchestrator.py:38`, `mcp_bridge.py:41` and `providers.js:6`. The Orchestrator prompt gains a research workflow: search → read → snowball → synthesize → `verify_citations` → report. A reviewer can judge the claims against the sources it fetched.

**UI (research feel):**
- **Settings → Research sources**, modelled on `providers.js`/`providers_api.py`: status for each source, enter or replace a key or email, Test, Remove, and a "Get a free key" help link for each source.
- **New task:** a choice of *Research question* (no project needed) or *Project task*, with presets: Literature review, Related work, Verify my references (paste a bibliography).
- **Research tool cards:** paper lists showing title, authors, year, venue, source badges and links, all rendered text-safe.
- **Citation report card:** verified, mismatch, not found or retracted for each reference.
- **Outputs panel:** the report and BibTeX, with View and Save.
- **Scope editor:** a research section with each source set to allow, ask or off.

## Waves

Same working rules as before:
- a worktree per stream with declared files;
- test-first, with fake HTTP fixtures and fake CLIs;
- the coordinator merges and runs full verification;
- branch `interspace/research-workspace`, cut from `main`.

**Wave 0 (coordinator plus 1 spike):**
- **0A Contracts.** `docs/superpowers/specs/research/`, covering:
  - the tool shapes and the normalized record;
  - the citation-check algorithm and its outcomes;
  - the scope `research` key and request;
  - the Keychain bridge;
  - the no-project task and outputs;
  - new events (`citation_report`, `research_usage`).

  `AGENTS.md` and `engineering.md` get the research rules.
- **0B API spike.** Real keyless calls to arXiv, Crossref, Unpaywall (with an email you approve) and the free Semantic Scholar pool. It records real response shapes as anonymized fixtures. OpenAlex is checked with your key, only after your approval and only if you choose to enter it.

**Wave 1 (4 sessions in parallel):**

| Stream | Owns |
|---|---|
| **1A Keys and settings** | `main.swift` (Keychain bridge, handshake, allowlist, save panel), `research/credentials.py`, `research_api.py` (Settings methods), `service.py` stdin bridge-line handling |
| **1B Source clients** | `research/http.py`, `cache.py`, `records.py`, `semantic_scholar.py`, `openalex.py`, `arxiv.py`, `crossref.py`, `unpaywall.py`, `research/__init__.py` (registry and `dispatch`), all tested with fake HTTP |
| **1C Tools, policy, checker, no-project** | `research/citations.py`, `mcp_bridge.py` (descriptors), `scheduler.py` (tool list, `call_tool`, `research` authorize and audit, no-project runs, outputs), `scope.py`, `audit.py`, `orchestrator.py` prompt and roles, `tasks.py`, `routing.py` |
| **1D UI** | `app/ui/*`: Settings → Research sources, New task modes and presets, paper cards, citation report, outputs panel, scope research section, the Research sidebar entry, plus their browser suites |

**Wave 2 (2 sessions):** end-to-end wiring:
- a fake-HTTP research team: search → snowball → synthesize → verify → BibTeX;
- a browser end-to-end of a no-project literature review.

Then a live check with your keys, only with your approval.

**Wave 3:** independent reviews (keys and network safety, policy and checker, UI), Critical and Important findings fixed test-first, and a live demo rehearsal.

**Size:** about 9 sessions. Wave 1 runs 4 at once.

## Verification

- **Backend:** `python3 -m unittest discover -s tests` and `/usr/bin/python3 -m unittest discover -s tests`, with no skips. The source clients run against recorded fixtures; the checker is tested on verified, mismatch, not-found and retracted cases.
- **Browser:** `NODE_PATH=…/node_modules node tests/run-ui.cjs`, also with `INTERSPACE_PYTHON=/usr/bin/python3`, including the new research-settings, paper-cards, citation-report and no-project end-to-end suites.
- **Key safety:** a test proves a stored key never appears in state, events, audit, logs or tool results.
- **App:** `python3 scripts/build-macos-app.py`, launched with `--data-root` set to a scratch folder.
- **Live** (with your approval): enter your Semantic Scholar and OpenAlex keys, run "Related work on X" with no project, and check that every reference in the report is marked verified and the BibTeX opens in Zotero.
