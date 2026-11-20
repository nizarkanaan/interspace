# Task corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a per-research-task Corpus: a stored, deduplicated paper list with citation verdicts, and a Corpus tab that shows it.

**Architecture:**
- The pure merge logic lives in `app/backend/research/corpus.py`.
- The scheduler feeds it the whole result of every research call and owns `tasks/<root_id>/corpus.json` under its lock.
- `task_corpus` serves the file and backfills old tasks from `events.jsonl`.
- `app/ui/corpus.js` renders the tab.

**Tech Stack:** Python stdlib with unittest; plain JS; Playwright UI suites.

**Spec:** `docs/superpowers/specs/2026-11-20-task-corpus-design.md`

## Global Constraints

- Limits: 2,000 papers, 500 unverified entries and 20 `found` entries per paper.
- Updates to existing entries still apply past those limits.
- Verdict precedence: the Orchestrator's check beats a member's. Within the same owner, the latest wins. `verified` and `retracted` are never downgraded.
- Only `verified` and `retracted` rows attach to papers. `mismatch`, `not_found` and `unchecked` rows go to `unverified`, and their `match` is kept only as `closest`.
- Status in words. Every UI value is set with `textContent`. Links are https only.

## Review Focus

- A truncated or unparseable `tool_result` in backfill increments `incomplete` and never raises.
- A project task calling `task_corpus` is refused with `Only research tasks have a corpus.`
- Two members' results for the same DOI merge into one paper with two `found` entries.
- A later member `unchecked` row for an input the Orchestrator verified changes nothing.
- No key or email reaches `corpus.json`. Only paper records and queries are stored, and the key-safety test scans the file.

---

### Task 1: `research/corpus.py`

**Interfaces (produces):**
- `empty() -> dict`
- `add_papers(corpus, records: list, found: dict) -> bool`
- `add_report(corpus, rows: list, by: str, at: str) -> bool`
- `rebuild(event_lists: list[tuple[str, list]]) -> (corpus, incomplete: int)`

Each `add_*` function returns whether anything changed.

**Tests:** `tests/test_corpus.py`
- merging across sources and members;
- the `found` cap and the paper cap, with updates still applying;
- verified attaching and removing an `unverified` entry;
- a mismatch goes to `unverified` with `closest`;
- precedence and no downgrade;
- backfill counts truncated results.

### Task 2: Scheduler, method and allowlist

- `Scheduler._research`: after a successful non-quiet call, call `self._corpus_add(run, name, arguments, whole)`.
- `Scheduler.corpus(task_id) -> dict`: under the lock, refuse non-research tasks, load the corpus or rebuild it, and return it.
- `_corpus_add` writes atomically, then emits `corpus {papers, unverified}` on the root task.
- Add `task_corpus` to `outputs_api.METHODS`, and to the `main.swift` allowlist.
- Extend the key-safety test to scan `corpus.json`.
- **Tests:** integration tests in `tests/test_research_tasks.py`, in a new `CorpusTests` class.

### Task 3: UI

- `app/ui/corpus.js` exports `window.interspaceCorpus.render(container, data, state, refresh)`.
- `agent.js`: on research tasks, add a Conversation | Corpus tab row. Fetch `task_corpus` when the Corpus tab opens, and on `corpus` events.
- `stream.js`: handle `case 'corpus'`.
- Styles go in `desk.css`. Add the script tag to `index.html`.
- **Test:** `tests/corpus-ui.mjs`, registered in `run-ui.cjs`.

### Task 4: Verify

- Run `python3 -m unittest discover -s tests` and `node tests/run-ui.cjs`.
- Take screenshots in light, dark and at 320px.
