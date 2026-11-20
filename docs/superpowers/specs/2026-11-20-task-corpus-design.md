# Task corpus: every paper a research task found, in one place

Date: 2026-11-20
Status: proposed, awaiting approval
Size: a project, but a small one. It touches the backend, the UI and the Swift allowlist.

## Intent

Today, the papers a research task finds show up only inside the activity stream, one search card at a time. They are spread across the Orchestrator and each subagent. Citation verdicts sit in separate citation-report cards. To answer "what did this task read, and which of those did it cite and check?", you have to scroll the whole conversation.

The Corpus panel gathers this into one list per research task. It is also the foundation for a later library: a read-only index across all tasks, built from the same per-task files. The library needs no manual curation.

## Goals, non-goals, anti-goals

- **Goals:**
  - One deduplicated list of the task's papers, including those found by its subagents.
  - Each paper shows where it came from and its citation verdict, if it was checked.
  - Search, filters and sorting.
  - Works for research tasks that already exist.
  - Fully keyboard and screen-reader usable.
- **Non-goals:**
  - The cross-task library itself.
  - Tags, folders, notes or manual editing.
  - Exporting the whole corpus to BibTeX: that needs a source call per paper. `references.bib` stays the export.
  - Project tasks.
- **Anti-goals:**
  - Anything the user has to tidy or maintain.
  - Saying a paper is verified when no citation report says so.
  - Showing values from sources as anything but literal text.

## Approaches considered

1. **The backend keeps a corpus file per task (chosen).** After each research call, the scheduler merges the call's full, uncapped result into `tasks/<root_id>/corpus.json`. One new read method serves it. The data is complete, even when the event shown in the stream was cut at 48 KB. The later library is then "read every `corpus.json`".
2. Build the corpus in the UI from the stream events. This was rejected. Tool results larger than 48 KB are cut in events, so papers would silently go missing. Every view would redo the merge. A library would have to replay every task's whole log.
3. Ask the Orchestrator to write a corpus file. This was rejected: it is not deterministic and costs tokens, and agents could leave papers out.

## Design

### Storage: `tasks/<root_id>/corpus.json`

```json
{"v": 1, "updated_at": "…", "full": false, "papers": [
  {"paper": {<records.make fields>},
   "found": [{"tool": "research_search", "query": "sparse attention", "member": "Researcher", "at": "…"}],
   "check": {"status": "verified|retracted", "by": "orchestrator|member", "at": "…"} | null}
 ],
 "unverified": [
  {"reference": {<the report row's input: title, authors, year, doi, arxiv_id, raw>},
   "status": "mismatch|not_found|unchecked", "fields": ["year"], "closest": {<match record>} | null,
   "by": "orchestrator|member", "at": "…"}
 ]}
```

- **Where verdicts attach (designer's call).** A verdict says something about the reference as the agent cited it, so it attaches only where the checker confirmed which paper that is:
  - A `verified` or `retracted` row's `match` is that paper. It is merged into `papers`, with `check` set.
  - A `mismatch`, `not_found` or `unchecked` row goes to `unverified`, keyed by the normalized input title plus DOI. A mismatch's `match` is kept only as `closest`, and is never merged into `papers` or given a verdict.
  - A later `verified` or `retracted` result for the same input removes that entry from `unverified`.
- **Which verdict wins.**
  - The Orchestrator's own check beats a member's, the same rule as `_keep_report`.
  - Between checks from the same owner, the latest wins.
  - Nothing ever turns a `verified` or `retracted` paper back into unverified. A later `unchecked` row for an already-checked input is ignored.
  - Backfill replays events in time order under the same rules.
- **Writing:** `Scheduler._research`, after a successful call, takes the whole payload:
  - `research_search` and `research_citations` give `papers`;
  - `research_paper` gives `paper`;
  - `verify_citations` gives the report rows, as above.
- **Merging:** new records merge with `records.merge`/`same_paper`, so duplicates across sources and members combine. `found` entries are appended, at most 20 per paper.
- **Member name:** this is the calling run's task `role` (from `tasks.role`), shown as a title (`citation_checker` becomes "Citation checker"). The root Orchestrator's own calls say "Orchestrator". Child task rows keep `role` and `parent_task_id`, so backfill can find both.
- **Where it lives:** writes go to the root task's file. A subagent's papers belong to its parent research task.
- **Limits:** at most 2,000 papers and 500 unverified entries.
  - Once a limit is reached, new entries are dropped and `"full": true` is set.
  - Updates to entries already in the file still apply: new `found` entries, verdicts, and removals from `unverified`.
- **Concurrency:** all reads and writes go through one scheduler method under `self.lock`. That includes backfill. The file is written atomically, the same way outputs are.
- **Never stored:** keys, emails and raw upstream error text. The existing key-safety test gains `corpus.json` in its list of files to check.

### Backfill for existing tasks

`task_corpus` on a research task without `corpus.json` rebuilds (under the scheduler lock, so a running task's writes and the rebuild never interleave; once the file exists, live writes simply continue it) the corpus once from that task's `events.jsonl` and its children's, in event order. It reads `tool_result` outputs that parse as JSON, plus `citation_report` events. Unreadable or truncated results are counted. The panel then says "Some earlier results could not be read, so this list may be incomplete." The rebuilt file is saved.

### Method: `task_corpus {task_id}`

- **Returns:** `{papers: [...], unverified: [...], full: bool, incomplete: int, updated_at}`.
- **Errors:** it is refused for project tasks with `ValueError('Only research tasks have a corpus.')`.
- **Allowlist:** it is added to `METHODS` and to the Swift allowlist in `app/macos/main.swift`.
- **Live updates:** the scheduler emits a new scheduler-side event kind, `corpus` `{papers, unverified}` (counts only). It is emitted like `outputs` (not a runtime kind), is ignored by backfill and is not audited. `stream.js` stores it as `m.corpus` and draws nothing. It goes on the root task when the file changes. The UI refetches on that event, debounced to 1 second, while the panel is open.

### UI: a Corpus section in the research task view

The research task view gains a tab row, **Conversation | Corpus**, and Outputs stays above both. The Corpus tab shows:

```
Corpus  · 42 papers · 7 verified · 3 references not verified
┌ References not verified (3) ─────────────────────────────┐
│ ✗ LeCun (2012). Deep learning.   Differs in year          │
│   Closest record: LeCun, Bengio, Hinton (2015). Nature.   │
└───────────────────────────────────────────────────────────┘
[ Search titles and authors…        ]
Show: (All 42) (Checked 8) (Not checked 35) (Open access 17)
Sort: [Order found ▾]

 1  Attention is all you need                         Verified
    Vaswani, A., Shazeer, N., et al. (2017). NeurIPS.
    Semantic Scholar  OpenAlex   151,778 citations   doi:…
    Found by Researcher: search "sparse attention" · Open-access copy
```

- **Unverified references** come first, so problems are never hidden. The section is open while it has entries. Each entry shows the reference as cited, its status in words (the same labels as the citation report), the differing fields, and the closest record, labelled "Closest record".
- **Papers** use the reading-room bibliography: a numbered margin whose rule colour repeats the verdict.
  - Verified papers get green and the word "Verified".
  - Retracted papers get oxblood and the words "Retracted: do not cite".
  - Papers that were never checked get a muted rule and the words "Not checked".
- **Filters** are toggle buttons with `aria-pressed`, each showing its count:
  - All;
  - Checked: verified or retracted papers, that is, the ones a citation report confirmed. Retracted papers stay flagged. (Named "Checked", not "Verified", during build so a retracted paper is never listed under "Verified".)
  - Not checked: `check: null`;
  - Open access: the paper has an https `oa_url`.
- **Sorting:** a native `<select>`, by order found, newest or most cited.
- **Search** filters the list locally by title, authors and venue, ignoring case. The count updates in a polite live region ("Showing 5 of 42 papers").
- **Sorting:** a native `<select>`.
- **Long lists:** the first 50 papers show, then a "Show all" button, the same pattern as today's lists.
- **Paper details:** each paper's abstract is behind a `<details>`. The provenance line lists, for each finding, which member found the paper, with which tool and which query.
- **Empty state:** "No papers yet. Papers appear here as agents search."
- **Safety:** every value is set with `textContent`, and links are https only. This reuses `R.link` and the `paper()` renderer from `research-cards.js`.

### Files

- Backend:
  - `app/backend/research/corpus.py`: new; the pure functions `add(corpus, records, found, check=None)` and `rebuild(events)`.
  - `scheduler.py`: write on research calls, and emit `corpus`.
  - `outputs_api.py`: `task_corpus`, or a new `corpus_api.py`.
- Swift: `main.swift`, for the allowlist.
- UI:
  - `app/ui/corpus.js`: new; the panel.
  - `agent.js`: the tab row, on research tasks only.
  - `desk.css`.
  - `index.html`: the script tag.
- Tests:
  - `tests/test_corpus.py`: merge, limits, backfill and the truncated-result count.
  - Scheduler integration in `test_research_tasks.py`, plus key safety.
  - `tests/corpus-ui.mjs`, registered in `run-ui.cjs`.

## Designer's calls (check these)

- A paper counts as checked when a citation report confirmed it. Mentions in the report's prose don't count, because matching prose is unreliable.
- Mismatched, not-found and unchecked references are listed separately, as cited. Their verdict is never put on a candidate paper.
- The Orchestrator's verdict beats a member's, and a verdict is never downgraded.
- 2,000 papers, 500 unverified entries and 20 provenance entries per paper. Updates to existing entries still apply past those limits.
- The corpus belongs to the root research task, and subagents' papers roll up into it.
- The Conversation and Corpus tabs, with Outputs staying visible above both.

## Left to the builder

- Choosing between debouncing and throttling the `corpus` event.
- The exact wording of the provenance line.
- Whether `task_corpus` lives in `outputs_api.py` or in a new module.
