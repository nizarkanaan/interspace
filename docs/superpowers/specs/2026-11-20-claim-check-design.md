# Claim check: does each cited source support its sentence?

Date: 2026-11-20
Status: approved in conversation (research ranked it first; the user chose "only when I press Check claims")
Size: project

## Intent

The citation checker shows that a reference exists and isn't retracted. Studies show that real citations are often attached to sentences the source does not support:

- 50–90% of AI answers were not fully supported by their sources (SourceCheckup, Nature Communications 2025);
- about 30% of statements were unsupported even with retrieval.

The claim check judges each cited sentence against its source's text, with an independent model, and shows the result in the Report tab.

## Flow

1. **The button.** In the Report tab the user presses **Check claims**. It is enabled when a report exists and the task is not working.
2. **Preparing the claims.** The UI calls `claims_start {task_id}`. The backend reads `report.md` and splits it into claims, one per sentence-and-reference pair, then saves `tasks/<id>/claims.json` with every claim pending.
   - Each claim is matched to its reference in the report's own list, and the reference to a corpus paper by DOI, then arXiv ID, then title.
   - Claims whose reference has no corpus paper, or no abstract, are stored as **Can't tell** with the reason "No source text to judge against."
3. **The request.** The UI sends the Orchestrator the fixed message "Check the claims in the saved report."
4. **Delegation.** The Orchestrator's prompt tells it to propose one `citation_checker` member on the provider other than its own, as an independent judge. The member works in a loop:
   - call `claims_pending`;
   - judge each claim against the source text it is given, and only that text;
   - call `record_claim_support`;
   - repeat until nothing is pending.

   The Orchestrator never judges claims itself. As with any team, the user approves this one.
5. **The tools.** Two read/update tools are offered to every session of a research task:
   - `claims_pending {limit?}` returns up to 20 pending claims: `{id, sentence, reference, source: {title, abstract}}`.
   - `record_claim_support {results: [{id, verdict, reason, quote?}]}` takes:
     - `verdict`: `supported`, `partly`, `not_supported` or `cannot_tell`;
     - `reason`: 1–300 characters;
     - `quote`: optional, but required unless the verdict is `cannot_tell`. It must appear in the source text, after collapsing whitespace and ignoring case. A quote that isn't there rejects that one result with "The quote is not in the source text", so the agent cannot invent evidence.

     Each stored verdict records which provider and role judged it, and when.
6. **A changed report.** If the report has changed since `claims_start`, recorded results for the old version are refused. The stored report hash no longer matches, and the user presses Check claims again.

## Claim splitting (`research/claims.py`)

- Fenced code is skipped, and so is everything from the References heading on. That heading is References, Bibliography, Works cited or Reference list, at any level.
- Text is split into sentences on `.`, `?` or `!` followed by a space and a capital letter, or at a line break between paragraphs and list items. Abbreviations such as "et al.", "e.g." and "i.e." do not end a sentence.
- Each `[n]`, `[n, m]` or `[n–m]` in a sentence makes one claim per number that is in the reference list. A range counts its two ends.
- `id` is `"<n>:<k>"`: reference n, its k-th citation in the text, counted from 1. The reader numbers citation links the same way, so marks land on the right link.
- At most 400 claims are kept, and the reading text of each sentence at most 600 characters.

## Report tab

- **Toolbar.** **Check claims** sits next to Save report. Below it, a summary line: "24 claims: 19 supported, 3 partly, 1 not supported, 1 can't tell". While the check runs it reads "Checking claims: 12 of 24 done".
- **Citation links** are coloured by their claim's verdict, which is repeated in their accessible name ("Reference 3, partly supported"):
  - supported: green;
  - partly: underlined with dots;
  - not supported: oxblood;
  - can't tell: muted.
- **A "Claims to look at" list** above the report shows not supported, then partly, then can't tell. Each entry has the sentence, the reference, the reason, the quote, and a **Show in text** link to the sentence.
- **References.** The marker for a reference that isn't in the corpus already says "Not in the corpus". Its wording becomes "Not found by the agents: possibly cited from memory".

## Calls made by the designer

- Claims are judged from abstracts only for now; full text comes later.
- The existing `citation_checker` role does the judging, on the other provider.
- A quote is required for every verdict except can't tell, and must appear in the source.
- 20 claims are handed out per call, with at most 400 per report.
