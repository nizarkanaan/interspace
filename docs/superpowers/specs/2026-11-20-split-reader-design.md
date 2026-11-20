# Split reader for research tasks

Date: 2026-11-20
Status: approved in conversation (direction B on the canvas "Interspace task view")
Size: small change (UI only)

## Intent

In a research task you mostly read the report and check references while you talk to the agent. The task view should show both at once: the conversation on the left and the results on the right.

## Design

- **Research root tasks in windows of 1100px or wider** get two columns under a compact header:
  - **Left: the conversation.** About 420px wide on the board ground. It holds the activity (with the display settings applied), the scope notice and the message box, which stays pinned at the column's bottom.
  - **Right: the results.** Tabs for **Report** (when report.md exists), **Corpus** and **Scope and outputs**. That last tab holds the former Task details panel: status, Stop, tokens, requests, scope and outputs. The scope editor opens there too.
  - **Default results tab:** Scope and outputs while the scope waits for approval, else Report once it exists, else Corpus.
- **The header compacts.** The title drops to 22px and New task is hidden. A bar under it carries the back link, the status, a **Scope** button that opens Scope and outputs, and **Stop**.
- **Scrolling.** The page itself no longer scrolls. Each column scrolls on its own, so you can read the report while new messages arrive. The results column's scrollbar sits at the window edge and the conversation's at its own border, never side by side.
- **Unchanged:**
  - Project tasks keep the side-panel layout.
  - Windows narrower than 1100px keep the tabs: Conversation, Report, Corpus and Details.
  - The sidebar stays as it is. The icon rail from the mockup is a separate, whole-app change and is left for later.

## Calls made by the designer

- The split applies only to research tasks, and the sidebar is unchanged.
- The default results tab follows the rule above.
- The conversation column is 420px wide, and the narrow breakpoint stays at 1100px.
