# Saving the report on purpose

Date: 2026-11-20
Status: approved in conversation (the user saw a "please paste the papers" reply replace their literature review)
Size: small change

## Intent

Until now, the last reply of every completed Orchestrator turn in a research task was written to `report.md`. A short reply that asked the user something therefore replaced a full literature review. The report should change only when the agent means to replace it.

## Design

- **The tool.** `save_report {markdown}` (1–400,000 characters, effect `update`) is offered only to the root Orchestrator of a research task.
  - It writes `report.md` at once, inside app data, and emits `outputs`.
  - It returns `{saved: 'report.md', characters}`.
  - Wrong arguments come back as `invalid_request`, and nothing is written.
- **End of turn.** The final reply is no longer saved. `references.bib` is written at the end of a completed turn only if that turn saved a report and ran a citation check. That BibTeX still holds the references the checker verified.
- **Unchanged otherwise.** A turn without `save_report` leaves `report.md` and `references.bib` as they were, with no new `outputs` event.
- **Prompt.** The research workflow tells the Orchestrator to save the finished report with `save_report`, with a numbered References list matching its [n] citations, and says that replies asking the user something or reporting progress are never saved.
- **UI.** The save appears in the conversation as one line, "Saved the report as report.md (N characters). Open it in the Report tab." The full card says it replaces the report saved before.

## Calls made by the designer

- One explicit tool, instead of guessing from the reply's length or headings, which would fail on short reports and long questions.
- `references.bib` follows the saved report, not every citation check.
- A report replaced before this change is not recovered automatically. Its text is still in the task's conversation, so the user can ask the Orchestrator to save it again.
