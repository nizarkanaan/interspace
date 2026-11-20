# Two-agent evidence table

Date: 2026-11-20
Status: approved in conversation ("Yes, build it")
Size: project

## Intent

When Claude and Codex extracted the same fields independently, the cells where they agreed were 94% accurate. Where they disagreed, each alone was about 45% accurate (Khan et al., JAMIA 2025), so disagreement is a strong "check this" signal. Interspace already runs both providers. The Evidence tab therefore has them fill a table independently and shows the user where they agree, where they disagree, and which numbers to check.

## Model (`research/evidence.py`, `tasks/<id>/evidence.json`)

- **Columns.** 1 to 10, each `{id, name (1–60), instruction (1–300), numeric}`.
  - Presets: Study design; Sample size (numeric); Setting or population; Method; Main outcome; Key finding.
- **Rows.** `rows: 'cited'` (the default) takes the papers cited in the saved report. Each reference in the report's list is matched to the corpus the claim check's way, by DOI, arXiv ID or title. `rows: 'checked'` takes every corpus paper the citation checker verified or flagged as retracted. Either way, at most 50, with duplicates removed.
- **Cells.** Each cell holds `{values: {provider: {value, quote, at}}, resolved: {value, at} | null}`.
  - A value is 1–300 characters, or "Not reported".
  - Any other value needs a quote, and the quote must appear in the row's source text (whitespace and case don't matter), the claim check's rule.
- **Status of a cell:**
  - `waiting`: fewer than two providers have answered. When only one provider is signed in, its single answer counts as `one source`.
  - `agree`: the values are equal once case, whitespace, punctuation at the ends and thousands separators are ignored, and numbers are compared as numbers.
  - `disagree`: anything else.
  - `not_reported`: both said "Not reported".
  - **Numbers:** a numeric column's `agree` is shown as **check**. It counts as agree in the totals but is flagged for the user.
  - `resolved`: the user picked or typed a value. That status overrides all others.
- **Source text for a row:**
  - the abstract;
  - plus, when the full text is available (the same fetcher, permission and cache as the claim check), up to 6 passages of about 1,200 characters: the best 2 for each column's name and instruction, with duplicates removed;
  - capped at 9,000 characters.

  The source is built the first time `table_pending` hands the row out.

## Flow

1. **Setting up.** In the Evidence tab the user picks columns, from presets or their own, and the rows, cited or checked. **Fill table** calls `table_start {task_id, columns, rows}`, then sends the Orchestrator "Fill the evidence table." Starting again replaces the earlier table, after the user confirms.
2. **Two independent extractors.** The Orchestrator rule: propose two `researcher` members, one on Claude and one on Codex, as independent extractors, with this brief:
   - call `table_pending`;
   - fill every column for every row from that row's source text alone;
   - record values with exact quotes using `record_table_cells`;
   - repeat until nothing is pending;
   - never ask for or look at another member's values.

   Then the Orchestrator calls `wait_for` and reports the counts.
3. **The tools,** offered to every session of a research task:
   - `table_pending {limit 1–10 rows}` returns `{columns, rows: [{id, title, source: {kind, text}}], counts}`. It lists only rows this session's provider has not yet filled.
   - `record_table_cells {results: [{row, column, value, quote?}]}`, up to 100 results, stores them under the session's provider. It rejects, one by one: an unknown row or column; a cell this provider has already filled; a value of the wrong size; a missing quote; a quote that isn't in the source.
4. **Resolving.** For a cell, `table_resolve {task_id, row, column, value}` takes the user's choice: one provider's value, or their own text. A null value clears it.
5. **Export.** `table_export {task_id}` writes `outputs/evidence.csv`, a new output kind `table`.
   - Columns: Paper, then each column's value, then a Status column per cell.
   - The value is the resolved value, else the agreed value, else blank.
   - CSV cells that start with `=`, `+`, `-` or `@` get a leading apostrophe, so spreadsheets can't run them as formulas.

   The UI then saves it through the save panel.
6. **Live updates.** The `evidence` event carries the counts, and the tab refetches after each one.

## Evidence tab

- **Before any table:** a column picker, with preset checkboxes and an "Add a column" row (name, instruction, Number checkbox); the rows choice; and **Fill table**.
- **With a table:**
  - a summary, for example "60 cells: 48 agree (6 numbers to check), 9 disagree, 3 not reported, 0 waiting";
  - a **Needs you** filter, for cells that disagree or numbers to check;
  - **Export CSV**, and **Start a new table**.
- **The grid:** one row per paper, one column per field. Each cell shows its value and status in words:
  - an agreed cell shows the value;
  - a number to check shows the value with "Check";
  - a disagreement shows both values with their provider names, buttons **Use Claude's**, **Use Codex's** and **Type my own**, and each quote under the value it supports.
- The grid scrolls sideways inside its own box.

## Calls made by the designer

- Rows default to the papers cited in the report, with at most 50.
- Up to 10 columns.
- Agreement is checked by normalization only, with no AI judge, so it is predictable.
- A numeric agreement still says "Check".
- An extractor sees only its own provider's slot.
- Full text is fetched per row through the claim check's fetcher.
