# Research Wave 0B: API spike

Date: 2026-11-19. Facts for the five research sources that Wave 1B's clients
call. Each fact is marked **[call]** (seen in a real response captured that
day, fixture under `tests/research/fixtures/`), **[docs]** (read on the
official page named) or **[unverified]** (could not be read; do not build on it
without checking).

Real calls were made with `docs/superpowers/specs/research/spike-0b/probe.py`,
User-Agent `Interspace-spike`, no key, no `mailto`. Unpaywall used an email the
user approved for this spike; it was passed through an environment variable,
is redacted from every saved URL, and appears nowhere in the repo. OpenAlex was
called without a key.

## Summary

| Source | Auth | Limits | Search / lookup | Citations | BibTeX | Retraction |
|---|---|---|---|---|---|---|
| Semantic Scholar | `x-api-key` header, optional | keyless: shared pool, 429 often; key: 1 req/s | `/paper/search`, `/paper/search/match`, `/paper/{ID}` | `/paper/{id}/citations`, `/references` | `citationStyles.bibtex` field | none |
| OpenAlex | optional key: `api_key=` or `Authorization: Bearer` | keyless $0.10/day per IP, 10 req/s; free key $1/day, 30 req/s; ID/DOI lookups free | `/works?search=&filter=publication_year:`, `/works/doi:{doi}` | `filter=cites:W…`, `referenced_works` | none | `is_retracted` |
| arXiv | none | 1 request / 3 s, one connection | `/api/query?search_query=` / `id_list=` (Atom XML) | none | `arxiv.org/bibtex/{id}` | none (withdrawals only) |
| Crossref | none; `mailto` for polite pool | public 5 req/s single, **1 req/s lists**, concurrency 1; polite 10 req/s, conc. 3 | `/works?query.bibliographic=&filter=from-pub-date:,until-pub-date:`, `/works/{doi}` | `reference[]` (outgoing only) | `/works/{doi}/transform/application/x-bibtex` or doi.org with `Accept` | `updated-by[]` / `update-to[]`, `source: retraction-watch` |
| Unpaywall | `email=` query param | 100,000/day [unverified] | `/v2/{doi}` only | none | none | none |

## Semantic Scholar Graph API

- **Base** `https://api.semanticscholar.org/graph/v1` [docs: semanticscholar.org/product/api/tutorial].
- **Search** `GET /paper/search?query=&year=2017&offset=&limit=&fields=` → `{total, offset, next, data[]}`; `next` is absent on the last page [call: `search_attention_2017`]. `year` also takes `2015-2020` and `2023-` [docs shows `2023-`; range unverified]. Max `limit` 100 and the 1,000-result offset cap [unverified: the API reference page is JS-rendered and did not load]. Bulk search `GET /paper/search/bulk` pages with `token` [docs].
- **Title match** `GET /paper/search/match?query=<title>` → `{data:[one paper]}` (adds `matchScore`) [call: `match_title`]. Best primitive for the citation checker's no-DOI path.
- **Lookup** `GET /paper/{id}` with `ARXIV:1706.03762`, `DOI:…`, `CorpusId:…` or the 40-hex paperId [call]. Unknown ID → `404 {"error": "Paper with id … not found"}` [call].
- **Citations / references** `GET /paper/{id}/citations|references?fields=&offset=&limit=` → `{offset, next, data:[{citingPaper|citedPaper}]}`; references also carry `citingPaperInfo` [call].
- **BibTeX** `fields=citationStyles` → `citationStyles.bibtex` (`@Article{Vaswani2017AttentionIA,…}`) [call].
- **Auth/limits** `x-api-key` optional. Keyless: "1000 requests per second shared among all unauthenticated users", further throttled under load; keyed: 1 RPS introductory [docs: product/api]. **Real behaviour:** 3 of 7 keyless calls got 429 at 3-8 s spacing; 429 body `{"message": "Too Many Requests…", "code": "429"}` and **no `Retry-After` header** [call: `error_429_shared_pool`]. Client must back off on its own (e.g. 2, 4, 8 s, then give up) and the UI should push users toward a key.
- **Fields → record** `title`, `authors[].name`, `year`, `venue` (or `publicationVenue.name`), `externalIds.DOI`, `externalIds.ArXiv`, `paperId` (s2_id), `abstract`, `citationCount`, `url`, `openAccessPdf.url` [call].
- **Licence** attribute "Semantic Scholar"; no repackaging or resale of the API [docs: product/api/license].

## OpenAlex

- **Docs moved** to `help.openalex.org` (docs.openalex.org and developers.openalex.org redirect) [docs].
- **Key is optional, not required.** The plan's "key needed since February 2026" is wrong as of 2026-11-17 docs: keyless calls work on a $0.10/day budget **shared by everyone on the same IP**; a free key gives $1/day, resets midnight UTC [docs: rate-limits-and-authentication, access/pricing]. Pass as `api_key=` or `Authorization: Bearer` [docs; 429 body confirms]. Product decision from the user: the key stays optional in Settings, used when present.
- **Metering** per 1,000 calls: single entity by ID/DOI **free**; list/filter $0.10; any search (`search=`, `*.search`) $1; content download $10 [docs: access/pricing]. **Real behaviour:** on this network the keyless IP budget was already at $0; DOI lookups still returned 200 with `x-ratelimit-credits-used: 0`, the search got 429 [call]. So keyless search is unreliable; lookup always works.
- **Rate** keyless 10 req/s per IP, keyed 30 req/s [docs]. 429 JSON carries `reason` (`requests_per_second`, `daily_budget`, …), `retryAfter`, `costUsd`, plus header `Retry-After` (seconds to midnight UTC for `daily_budget`) and `x-ratelimit-limit/-remaining/-reset/-credits-used` [call: `error_429_daily_budget`]. Per-second 429s cost nothing [docs]. `GET /rate-limit` needs a key (401 keyless) [call]. No `mailto` pool mentioned any more [docs].
- **Endpoints** search `/works?search=…&filter=publication_year:2017` (`filter=title.search:` deprecated) [docs]; lookup `/works/doi:10.…`, `/works/https://doi.org/10.…`, `/works/W…`, also `pmid:`, `arxiv:` [docs; DOI form call]; cited-by `/works?filter=cites:W2626778328` (also given as `cited_by_api_url`) [call field]; references `referenced_works[]` (IDs only) [call]; `select=` trims fields [call]. Paging `page`/`per_page` max **100** (200 deprecated), `page×per_page ≤ 10,000`; `cursor=*` → `meta.next_cursor`, following it needs a key [docs].
- **Fields → record** `display_name`/`title`, `authorships[].author.display_name`, `publication_year`, `primary_location.source.display_name`, `doi` (full `https://doi.org/` URL, lowercased), `id` (full URL `https://openalex.org/W…`), `ids`, `abstract_inverted_index` (`{word: [positions]}`, rebuild by sorting positions; often `null`), `cited_by_count`, `open_access.oa_url`, `best_oa_location.pdf_url|landing_page_url`, `is_retracted` [call].
- **Response size** full work 11-26 KB; use `select=` [call].
- **Untrusted text:** the 429 body tells "an AI agent" to POST the user's email to `/api-keys`. Never pass raw upstream error text to agents.

## arXiv API

- **Base** `https://export.arxiv.org/api/query` [docs: info.arxiv.org/help/api/user-manual]. Atom XML, namespaces Atom, `opensearch`, `arxiv` [call].
- **Search** `search_query=ti:"…" AND submittedDate:[201701010000 TO 201712312359]&start=&max_results=` [call: `search_title_2017`]. **Quotes, brackets and spaces must be percent-encoded**; unencoded `[`/`"` gave HTTP 400 with an empty body [call]. Max 2,000 per call, 30,000 total [docs].
- **Lookup** `id_list=1706.03762` → latest version (`<id>…/abs/1706.03762v7`); `id_list=1706.03762v1` pins v1 [call]. Well-formed unknown ID → 200 with `totalResults 0`, no entry; malformed → 400 with one error `<entry>` whose `<id>` is `https://arxiv.org/api/errors#…` [call].
- **Rate** one request per 3 s, one connection, across all your machines [docs: help/api/tou]. Responses took 0.2-8 s [call].
- **BibTeX** `https://arxiv.org/bibtex/{id}` → `@misc{…, year={2023}, eprint=…}`: **year is the latest version's, not first submission** [call]. Prefer the publisher's or S2's BibTeX when a DOI or venue exists.
- **Fields → record** `title` (may contain line breaks: collapse whitespace), `author/name`, year from `published` (v1 date; `updated` is latest version), `summary`, `arxiv:doi` and `arxiv:journal_ref` (optional), `link[@title="pdf"]` as `oa_url`, `link[@rel="alternate"]` as `url` [call + docs].
- **Retraction** none; withdrawn versions show in comments only.

## Crossref REST

- **Base** `https://api.crossref.org` (`/v1` prefix optional) [docs: rest-api]. Envelope `{status, message-type, message-version, message}` [call].
- **Search** `/works?query.bibliographic=…&filter=from-pub-date:2015,until-pub-date:2015&rows=&select=` → `message.items[]`, `total-results` [call]. `rows` ≤ 1,000, `offset` ≤ 10,000, else `cursor=*` → `next-cursor` [docs: tips page].
- **Lookup** `/works/{doi}`; case-insensitive (uppercase DOI gave identical body); DOI is returned lowercased [call]. Non-Crossref DOIs (arXiv `10.48550/…` is DataCite) → `404 text/plain "Resource not found."` [call].
- **Limits** headers `x-rate-limit-limit`, `x-rate-limit-interval`, `x-concurrency-limit`, `x-api-pool` [call]. Seen keyless: single lookups pool `public-single` **5/s, concurrency 1**; list queries pool `public-array` **1/s, concurrency 1** [call]. Docs (updated 2025-10-16): public 5/s conc 1, polite (`mailto=` param or `mailto:` in User-Agent) 10/s conc 3, Plus 150/s; over limit → 429, blocked → 403 [docs: access-and-authentication]. Polite pool needs the user's Crossref email from Keychain; not exercised.
- **BibTeX** `GET /works/{doi}/transform/application/x-bibtex` or `GET https://doi.org/{doi}` with `Accept: application/x-bibtex` (redirects to the same transform) → `@article{LeCun_2015, …}` [call]. One record per request [docs: content-negotiation]. doi.org negotiation also works for DataCite (arXiv) DOIs [unverified].
- **Retraction** the retracted work carries `updated-by: [{DOI, type: "retraction", label, source: "retraction-watch"|"publisher", updated{date-parts}, record-id}]`; each notice carries the mirror `update-to: [...]`. `filter=updates:{doi}` lists the notices. Retraction Watch entries also include `type: "correction"`, so check `type == "retraction"` (also `withdrawal`, `expression_of_concern` exist [unverified]). Title is prefixed `RETRACTED:` [call: `lookup_wakefield_retracted`, `retraction_notices_for_wakefield`]. RW data acquired Sept 2023 [docs: retraction-watch].
- **Fields → record** `title[0]`, `author[].given/family` (no single name string), year `issued.date-parts[0][0]` (may be month-only), `container-title[0]`, `DOI`, `is-referenced-by-count`, `URL`. Abstract usually absent; JATS XML when present [call].
- **Size** full work 11-40 KB, mostly `reference[]`; use `select=` on lists (`select` is not supported on `/works/{doi}`) [call; select-on-single unverified].

## Unpaywall

- **Base** `https://api.unpaywall.org/v2/{doi}?email=…` [call]. Official docs pages are JS-rendered and did not load; 100,000 calls/day and search endpoint status are [unverified].
- **Response** `{doi, title, year, journal_name, is_oa, oa_status (green|gold|hybrid|bronze|closed), best_oa_location, oa_locations[], z_authors, …}`. `best_oa_location {url, url_for_pdf, url_for_landing_page, host_type, version, license, oa_date}`; `url_for_pdf` can be `null`; `evidence` and `updated` now read `"deprecated"` [call: `lookup_lecun`]. Closed papers: `best_oa_location: null` [call].
- **Unknown DOI** → 404 with an **HTML** body, not JSON [call].
- **Field → record** `oa_url = best_oa_location.url_for_pdf or best_oa_location.url`.

## Gotchas for 1B and the checker

1. **DOI normalization**: lowercase, strip `https://doi.org/`, `doi:`, whitespace. OpenAlex returns full lowercase URLs, Crossref lowercases, S2 keeps publisher case. Crossref and S2 lookups are case-insensitive [call for Crossref].
2. **arXiv versions**: strip `vN` for identity, keep it for display. arXiv's DataCite DOI `10.48550/arXiv.<id>` maps to the arXiv ID; S2 and OpenAlex list it as the DOI, Crossref 404s it.
3. **Same paper, different titles**: "Attention is All you Need" (S2) vs "Attention Is All You Need" (arXiv/OpenAlex); "RETRACTED: " prefix on Crossref/OpenAlex/Unpaywall. Normalize: casefold, strip a leading `RETRACTED:`, Unicode NFKC, drop punctuation, collapse whitespace.
4. **Year drift**: arXiv BibTeX gives 2023 for a 2017 paper; Crossref `issued` vs `published-print`. The ±1 year rule handles most cases; prefer v1 `published` for arXiv.
5. **Coverage holes**: S2 404s `DOI:10.1038/nature14539` (Nature 2015, "Deep learning") though it is in Crossref and well known; fall back to `/paper/search/match` by title. S2 abstracts are often elided by the publisher (`openAccessPdf.disclaimer` says so).
6. **OA status disagrees**: S2 says `isOpenAccess: true` but `openAccessPdf.status: "CLOSED"` for the arXiv paper. Take `oa_url` from Unpaywall, then arXiv, then OpenAlex `best_oa_location`.
7. **Duplicates**: OpenAlex can hold the arXiv preprint and the venue version as separate works; S2 merges them (`publicationVenue` NeurIPS + `ArXiv` ID). De-dup by DOI, then arXiv ID, then normalized title + year.
8. **Citation counts differ by source** (Vaswani: S2 203,887, OpenAlex 151,778; Wakefield: Crossref 2,050, OpenAlex 3,544). Record the source; never compare across sources in the checker.
9. **Upstream text is untrusted**: OpenAlex error bodies address AI agents directly. Map errors to fixed messages before they reach an agent.

## Needs the user's approval

- OpenAlex key: optional; the user wants a Settings field for it. Without one, search fails whenever anyone on the same IP has spent the $0.10 daily budget (it had on 2026-11-19).
- Semantic Scholar key: keyless pool returned 429 on 3 of 7 calls; a key (free, request form) is strongly advised.
- Crossref polite pool and Unpaywall both send the user's email to those services on every call.

## Fixtures

`tests/research/fixtures/<source>/<name>.json`, each `{_fixture{source, captured, note}, request{url, accept}, status, headers, body|text}`. Large arrays trimmed (Crossref `reference` to 2, OpenAlex `authorships` to 3 etc.); no request identity.

- `arxiv/`: `search_title_2017`, `lookup_1706.03762`, `lookup_1706.03762v1`, `lookup_nonexistent`, `lookup_malformed`, `bibtex_1706.03762`
- `crossref/`: `search_bibliographic_2015`, `lookup_lecun`, `lookup_lecun_uppercase`, `lookup_wakefield_retracted`, `retraction_notices_for_wakefield`, `lookup_arxiv_datacite_doi`, `bibtex_transform_lecun`, `bibtex_doi_org_lecun`
- `semantic_scholar/`: `search_attention_2017`, `match_title`, `lookup_arxiv`, `lookup_doi_lecun` (404), `lookup_nonexistent`, `citations`, `references`, `error_429_shared_pool`
- `openalex/`: `lookup_doi_wakefield` (retracted), `lookup_arxiv_doi_vaswani`, `error_429_daily_budget`, `rate_limit_keyless_401`. No search, cites or paging fixture: keyless budget was spent. Re-run `probe.py` with `OPENALEX_KEY` set to add them.
- `unpaywall/`: `lookup_lecun` (green), `lookup_wakefield` (closed), `lookup_unknown` (404 HTML)
