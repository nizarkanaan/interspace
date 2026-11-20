# Report reader

Date: 2026-11-20
Status: approved in conversation ("Yes, report reader")
Size: small change (UI only)

## Intent

Moving Outputs into the Task details panel made `report.md` open in a 340px column, which is too narrow for a literature review. The report should read like a paper. Its citations should lead to the references, and each reference should say whether the citation checker confirmed it.

## Design

- **A Report tab.** Research tasks gain a **Report** tab beside Conversation and Corpus, shown once `report.md` exists.
  - In the panel, report.md's **View** button becomes **Read**. It opens the tab; it no longer expands inline. BibTeX keeps its inline view in the panel, where its monospace lines scroll.
- **Reading measure.** The report is set in the serif at 17px with a line height of 1.7, capped at 68ch and left-aligned. The rendering is the existing text-safe Markdown: https-only links, the real host shown, every value literal.
- **A toolbar above the text:** the file name, its size, and a **Save report** button. Save goes through the existing save panel. If the file was cut at 1 MiB, the toolbar says so.
- **Citations become links.**
  - An inline `[n]`, `[n, m]` or `[n–m]` links to reference *n* in the report's own reference list. That list is the `ol`/`ul` under a heading named References, Bibliography or Works cited.
  - Activating the link scrolls to that reference and focuses it. Each reference has a **Back to text** link that returns to the citation you came from.
- **References carry the verdict in the margin.** This repeats the bibliography margin from the Corpus.
  - Each reference is matched to the task's corpus by DOI, then by arXiv ID, then by the corpus paper's normalized title appearing in the reference text.
  - The margin rule and a word show the result: **Verified**, **Retracted: do not cite**, **Not verified** (the reference matched an unverified entry), **Not checked** (in the corpus but never checked), or **Not in the corpus**.
  - Matching is local and exact. Nothing is guessed: an unmatched reference says "Not in the corpus".
- **Live updates.** A new `outputs` event, meaning the report changed, refetches the report while the tab is open.

## Calls made by the designer

- The tab is named "Report", and the panel's button is named "Read".
- BibTeX stays inline in the panel.
- A title only matches when the corpus title is at least 20 characters long, so short titles such as "Deep learning" don't match by accident.
