# Research tools, sources and the citation checker

Owners:
- **1B:** source clients, `research/http.py`, `cache.py`, `records.py`, `research/__init__.py`.
- **1C:** `research/citations.py`, tool descriptors in `runtime/mcp_bridge.py`, dispatch in `scheduler.py`.

Conventions: [README.md](README.md).

## Normalized paper record (`research/records.py`)

```json
{"v": 1, "title": "…", "authors": ["Ashish Vaswani", "…"], "year": 2017, "venue": "NeurIPS",
 "doi": "10.48550/arxiv.1706.03762", "arxiv_id": "1706.03762", "s2_id": "…", "openalex_id": "W…",
 "abstract": "…", "citation_count": 1234, "url": "https://…", "oa_url": "https://…|null",
 "retracted": false, "sources": ["semantic_scholar", "openalex"]}
```

Field rules:
- **`doi`:** lower case, with no `https://doi.org/` prefix.
- **`arxiv_id`:** no version suffix (`1706.03762`, never `1706.03762v5`).
- **Missing values:** `null`; `authors` is `[]` when unknown.
- **Text limits:** `abstract` at most 4,000 characters, and every other text field at most 1,000, cut with `…`. Control characters are stripped.
- **`retracted`:** `true` only on a positive signal; `null` when a source cannot tell.

Functions:
- `records.normalize_title(text)`: NFKD normalization, lower case, punctuation and extra whitespace removed.
- `records.title_similarity(a, b)`: a 0–1 ratio from `difflib.SequenceMatcher` on the normalized titles.
- `records.merge(list_of_records)`: removes duplicates. Two records are the same paper when they share a `doi`, else an `arxiv_id`, else their normalized titles are equal and their years are within ±1. Merged records keep the first non-null value of each field in source priority order `crossref > openalex > semantic_scholar > arxiv`, and the union of `sources`.

## Source modules (`app/backend/research/<source>.py`)

`SOURCES = ('semantic_scholar', 'openalex', 'arxiv', 'crossref', 'unpaywall')`. Each module defines a `Source` class:

```python
class Source:
    name = 'openalex'; title = 'OpenAlex'
    hosts = ('api.openalex.org',)
    credential = 'openalex'            # Keychain account (credentials.md) or None
    credential_kind = 'api_key'        # 'api_key' | 'email' | None
    required = True                    # False when the source works without the credential
    capabilities = ('search', 'paper', 'citations', 'retraction')   # subset of the tool verbs below
    help_url = 'https://…'             # where the user gets a free key; https only

    def __init__(self, *, http, credentials, cache, clock=time.time): ...
    def search(self, query, *, year_from=None, year_to=None, limit=10) -> list   # records
    def paper(self, identifier) -> dict | None
    def citations(self, identifier, direction, limit=25) -> list                 # 'citations' | 'references'
    def fulltext(self, identifier) -> dict | None   # {'oa_url', 'license', 'version', 'host_type'}
    def bibtex(self, identifier) -> str | None
    def status(self, test=False) -> dict            # {'source','configured','required','state','detail'}
```

- `status` states are `ready`, `needs_key`, `error` or `unchecked`. `test=True` makes one cheap, free call: a lookup by a fixed DOI.
- A method a source does not support raises `ValueError('<Title> cannot <verb>.')`.
- Identifiers accepted everywhere:
  - a DOI (with or without the `https://doi.org/` prefix);
  - `arXiv:1706.03762` or a bare new-style arXiv ID;
  - `s2:<id>`;
  - `openalex:W…`.

  `research.parse_id(text)` returns `('doi'|'arxiv'|'s2'|'openalex', value)`, or raises `ValueError`.
- **Errors** (in `research/http.py`, restored from the deleted `spaces/base.py`): `ResearchError(ValueError)` with subclasses `NotConfigured`, `RateLimited(retry_after_s)`, `Unavailable`, `BadResponse` and `NotFound`. They map to tool error codes `not_configured`, `rate_limited`, `unavailable`, `bad_response` and `not_found`.
- **Spike 0B corrections (binding):**
  - OpenAlex works without a key on a small shared per-IP budget. Its credential is optional (`required: False`), and a missing key shows as reduced quota, not as unusable.
  - Upstream error bodies are NEVER passed to agents or the UI. OpenAlex's 429 body addresses AI agents and asks for an email. Errors carry only the code and a fixed Interspace message.
  - Crossref retraction data also contains corrections, so only an update whose `type` is `retraction` counts.
  - arXiv BibTeX reports the latest version's year. `research_bibtex` replaces the year with the v1 publication year from the arXiv record.
  - Semantic Scholar misses some DOIs, so lookups fall back to OpenAlex and then to title matching.
  - Crossref allows only one connection at a time: 1 request/s for list queries and 5/s for single lookups. Semantic Scholar sends 429 without `Retry-After`, so the client waits 2 s and then 4 s.
- **Rate limits:** one token bucket per source, using the spike-0b values (defaults: Semantic Scholar 1/s, arXiv 1 per 3 s, the others 5/s). On a 429, the client honours `Retry-After` up to 10 s, retries once, then raises `RateLimited`. Values come from `spike-0b.md`.
- **Cache** (`research/cache.py`): keyed by `(source, method, canonical args)`, stored under `<storage>/research-cache/`. Each entry has a TTL of 7 days and is at most 2 MiB; the whole cache is LRU-pruned to 200 MiB. Keys and emails are never part of a cache key or entry.

## Registry and dispatch (`research/__init__.py`)

- `research.sources(app)`: the `Source` instances, built from `app.http`, `research.credentials` and the cache.
- `research.enabled(scope)`: the source names whose scope setting is not `off` (tasks.md).
- `research.dispatch(app, ctx, name, arguments) -> dict` runs one tool call. Before each source call it runs `ctx.authorize({'category': 'research', 'source': name_of_source, 'tool': tool_name})`. A source that is denied or `off` is skipped, and its name goes into `skipped`. `research_search` without `sources` names every search-capable source that is `off` in `skipped` (reason `off`) and never calls it (Wave 2A clarification).
- Metering (Wave 2A): each request a source client sends calls `ctx.note_call(source)` and each answer the response cache gives calls `ctx.note_cached(source)`, through a context variable (`research.http.METER`) that `dispatch` sets for the call and passes to its worker threads. The scheduler counts these on the root task (`research_usage`).

## Tools (served by the bridge, `effect: 'read'`)

| Tool | Arguments | Result |
| --- | --- | --- |
| `research_search` | `{query (1–500 chars), sources? [names], year_from?, year_to?, limit? (1–50, default 10)}` | `{papers: [record], searched: [names], skipped: [{source, reason}]}` |
| `research_paper` | `{id}` | `{paper: record\|null, sources: [names]}`, merged across every enabled source that can look the ID up |
| `research_citations` | `{id, direction: 'citations'\|'references', limit? (1–100, default 25)}` | `{papers: [record], source}` (Semantic Scholar first, OpenAlex as fallback) |
| `research_fulltext` | `{id}` | `{oa_url, license, version, host_type, source}\|{oa_url: null}`. A link only; nothing is downloaded |
| `research_bibtex` | `{ids: [id] (1–100)}` | `{entries: [{id, bibtex\|null, error\|null}]}` (Crossref for DOIs, arXiv for arXiv IDs) |
| `verify_citations` | `{references: [{title?, authors?, year?, doi?, arxiv_id?, raw?}] (1–200)}` | the citation report (below) |

- **Who gets them:** every session of a task whose scope enables at least one source, which covers the Orchestrator and every child, read or write. `verify_citations` is always served when any source is enabled.
- **Results:** wrapped as untrusted, like other read tools. A tool fails as a whole only for bad arguments; per-source failures go into `skipped`.
- **Results per call are capped at 64 KB of JSON.** When a result is cut, the list is shortened and the result carries `truncated: true`.

## Citation checker (`research/citations.py`)

`check(references, lookup) -> report`, where `lookup` is the dispatch layer, so the checker can be tested with fakes. For each reference:

1. **Normalize the reference.** If it only has `raw` (a pasted bibliography line), pull out a DOI or arXiv ID with a regular expression, and take the text in quotes, or the longest sentence-like run, as the title.
2. **Find a candidate.**
   - With a DOI: `paper(doi)` from Crossref, then OpenAlex.
   - With an arXiv ID: `paper` from arXiv, then Semantic Scholar.
   - Otherwise: `search(title, limit=5)` on Semantic Scholar and OpenAlex, keeping the candidate with the highest `title_similarity`.
3. **Compare and decide:**

| Status | When |
| --- | --- |
| `retracted` | the matched record has `retracted: true` (this overrides every other status) |
| `verified` | title similarity of at least 0.90, the year matches within ±1 when given, and the first author's surname matches (case and diacritics ignored) when given |
| `mismatch` | a candidate with similarity of at least 0.75, or found by its exact DOI or arXiv ID, but some fields differ; `fields` lists them (`title`, `year`, `authors`, `doi`) |
| `not_found` | no candidate reaches 0.75 |
| `unchecked` | every source that could check it was skipped (not configured, denied or failed); `reason` says which |

4. **The report:**

```json
{"v": 1, "checked_at": "…Z", "summary": {"verified": 7, "mismatch": 1, "not_found": 1, "retracted": 0, "unchecked": 0},
 "references": [{"index": 0, "input": {…}, "status": "mismatch", "fields": ["year"], "match": record|null,
                 "similarity": 0.97, "source": "crossref"}]}
```

Retraction signals:
- Crossref: `update-to` or `updated-by` with type `retraction`, including the Retraction Watch data Crossref exposes.
- OpenAlex: `is_retracted`.
- Exact field names come from spike 0B.

The checker never calls a model and never changes the agent's text. It reports only.
