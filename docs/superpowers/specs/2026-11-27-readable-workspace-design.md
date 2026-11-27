# A readable workspace: evidence table, sidebar, focus and a simpler conversation

## Intent

After the first live rehearsal the user found the research workspace hard to read, even with the window maximized:

- The **evidence table** cannot be seen whole, and scrolling it left and right is awkward.
- The **left sidebar** always takes 205px. The user wants to move it out of the way, and bring it back when they want to switch to another chat.
- The **conversation** shows a lot of machinery: proposed team cards with full member editors, subagent cards with briefs and token counts, and "Orchestration · Wait for" tool cards with raw `{"members": …}` output. A colleague watching would be confused. That detail should only show when someone clicks to expand it. **Team approval must stay**: a person still approves every team.

The user asked for these to be built now. They also asked for further ideas; the extra ones adopted here are marked *(my call)*.

## Why it is hard today (what the code does)

- `app/ui/evidence.js` renders a `table.ev-table` inside `.ev-wrap` (`max-height:70vh`, scrolls both ways). The paper column is sticky at `min-width:220px`, and every other column is `min-width:170px; max-width:280px` (`app/ui/desk.css`).
- A **disagree** cell renders both providers' values, both full quotes and three buttons (**Use Claude's**, **Use Codex's**, **Type my own**), so rows grow very tall. Agree cells carry a "Quote" disclosure.
- The table sits in the split reader's right pane (`#agent-results`), beside the conversation (default 420px, the divider is draggable) and the sidebar (`aside`, 205px, sticky, no collapse).
- The conversation is rendered by `app/ui/stream.js` `build()`. Team cards (`team-card.js` `teamCard`) and subagent cards (`subagentCard`) always show (`visible()` in `stream.js`). Orchestration tool calls (`category: 'orchestrate'`) render as ordinary tool cards (`toolCard`) with a pairs list and the raw output, and they are hidden only by the "Commands and file changes" switch in Settings → Conversation display.

## Goals

1. **Focus mode for the results pane.** A **Focus** button on the results tab row (Report, Corpus, Evidence, Scope and outputs) makes the results pane take the whole window: the conversation and the sidebar are hidden. **Exit focus** and the Esc key return. It works for every tab, not only Evidence *(my call: one mechanism, and the Report and Corpus benefit too)*.
2. **A compact evidence table.**
   - Each cell shows only its value and a coloured status word: Agree, Check, Disagree, Not reported, Waiting or Decided.
   - A **disagree** cell shows both short values on two lines, "Claude: DQN" and "Codex: other", with its red edge, but no quotes and no buttons.
   - **Clicking a cell** (or Enter on a focused cell) opens a **cell drawer** on the right of the evidence area. It shows the paper, the column and its instruction, each provider's value with its full quote, and, for a disagreement, **Use Claude's**, **Use Codex's** and **Type my own**. Close it with ×, with Esc, or by clicking another cell. *(my call: a drawer, not inline expansion, so rows stay short)*
   - The **paper column** shows a short label: the first author's surname, plus "et al." when there are several authors, then the year (for example "Zangooei et al. 2024"). Without authors it shows the title, clamped to two lines. The full title is in a tooltip and in the drawer. The column is narrower (about 170px) and stays sticky.
   - Value columns get `min-width:120px; max-width:220px`, with long values clamped to three lines (the full value is in the drawer).
   - The table wrapper fills the available height of the pane (or the window in Focus), not a fixed `70vh`, so its horizontal scrollbar stays on screen.
   - Arrow keys move between cells. Shift plus mouse wheel and trackpad sideways swipes already scroll it sideways; that is unchanged.
3. **A collapsible sidebar.** A collapse button (◀) at the top of the sidebar hides it down to a thin rail (about 44px), which keeps only an expand button (☰). ⌘\ (Ctrl+\ elsewhere) toggles it. The choice is remembered across launches (localStorage). In the narrow layout (≤600px), where the sidebar already sits on top, the control is not shown.
4. **A simpler conversation**, with nothing lost.
   - A new display setting, **Conversation detail: Simple / Detailed**, sits in Settings → Conversation display. A one-click toggle for the same setting sits in the conversation header (next to the task's status line). **Simple is the default.**
   - In **Simple**:
     - **Subagent cards** collapse to one line: provider badge, role, state, plus "▸ Details". Expanding shows today's full card (brief, tokens, latest activity, report, Show activity, Open). The expansion is per card and remembered for the session.
     - **A team awaiting approval** shows a short card: "Proposed team: Codex researcher (reads)", one line per member, the team summary if any, and the **Approve team** and **Decline** buttons. An **Edit team** button reveals today's member editors (provider, model, access, brief, remove). Approval works exactly as today.
     - **An answered team** shows one line, for example "Team approved · Codex researcher ▸", which expands to today's answered card.
     - **Orchestration tool cards** (`category === 'orchestrate'`) are not shown, unless they failed (a failed call always shows, as today).
   - **Detailed** shows everything as it is today.
   - The existing switches (thinking, searches, commands, citations, plans, notes) still apply in both modes.
   - **Research tasks** go further in Simple (amended by `2026-11-27-simple-chat-view-design.md`): each turn reads as your message, one work line that folds and counts the agents' work, then the reply. An earlier message or reply over 600 characters shows its first lines with **Show whole message ▾** / **Show whole reply ▾**. A citation report with a problem becomes one warn line, **Citations: V of N verified · …**, that opens a brief card of the problem rows. Beside the switch, a note says how many steps are folded.
5. **Small fix found in the rehearsal.** The Evidence tab's "Approve the team in the conversation" note shows only while the fill is waiting for a team approval, not after the table is filled.

## Non-goals

- No change to what the backend records, to the evidence data, or to how agreement is computed.
- No new libraries or build tools. The UI stays plain JS and CSS.
- No new icons beyond plain text glyphs (◀, ☰, ▸, ×).
- No redesign of the Report, Corpus or Scope tabs beyond Focus.

## Anti-goals

- Hiding anything that needs the user: team approvals, questions for the user ("asks"), errors and failed calls always show in full, in both modes.
- Any detail becoming unreachable. Everything Simple hides is one click away, or one switch to Detailed.
- Breaking keyboard use or screen-reader labels. The existing code labels controls carefully, and new controls must too.
- Breaking the narrow (≤600px) tab layout or dark mode.

## Constraints

- Display settings are validated in `app/backend/display.py`, which refuses unknown keys. The new `detail` key (`'simple' | 'detailed'`, default `'simple'`) must be added there, to `default()`, and to the UI's `valid()` in `app/ui/display.js`. Settings saved earlier, without the key, load as Simple.
- The split reader's scroll guard (`placed` in `agent.js`) and its `split` class must keep working. Focus is an extra state on top of the split, not a replacement for it.
- Tests run with `python3 -m unittest discover -s tests -q` and `node tests/run-ui.cjs <suite>` (21 suites in `tests/run-ui.cjs`). All must pass. Suites that assert today's full team or subagent cards must set Detailed, or be updated to expand first.
- After the change: rebuild with `python3 scripts/build-macos-app.py` and run `graphify update .`.

## Approaches

1. **Extend the existing renderers in place (chosen).** Add the Simple/Detailed branch inside `stream.js` `build()` and `team-card.js`. Add the drawer and the compact cells to `evidence.js`. Focus and the sidebar rail are CSS classes toggled from `agent.js` and `app.js`. This is the least code, and it reuses the tested approval and resolve paths unchanged.
2. **A separate "presentation" layer** that post-processes the rendered conversation, hiding nodes by class. It would not touch the renderers, but it is brittle: it hides by DOM shape, double-renders on every update, and breaks keyboard focus.
3. **A modal dialog for the evidence cell** instead of a drawer. It is simpler to place, but it blocks the table, so you cannot compare neighbouring cells while deciding one.

The user asked for these to be built now and left the "how" to me. Approach 1 is my call.

## Settled in review *(my calls)*

- **Author format.** `row.paper.authors` is a list of "Given Surname" strings (checked on the rehearsal's evidence rows, e.g. `['Han Zhang', 'Hao Zhou', 'Melike Erol-Kantarci']`).
  - The surname is the first author's last word, or the text before a comma if a string reads "Surname, Given".
  - One author gives "Zhang 2022", two give "Zhang & Zhou 2022", three or more give "Zhang et al. 2022".
  - Missing, empty or non-list authors fall back to the title clamped to two lines. The year is left out when missing.
- **Simple and the display switches.** Simple hides `category === 'orchestrate'` cards whatever the "Commands and file changes" switch says.
  - "Failed" means a result whose `status` is present and not `'ok'`, the same test `visible()` uses today. A call still waiting (no result yet) is hidden in Simple.
  - Every other category follows the existing switches, unchanged.
- **Focus while something needs the user.** If a team proposal awaiting approval, a question for the user, or a scope approval appears while Focus is on, Focus stays on. A banner at the top of the focused pane names it and offers **Go to conversation**, which exits Focus and scrolls to it. This keeps the anti-goal: nothing that needs the user is hidden.
- **Evidence note.** "Asked the Orchestrator to fill the table…" clears as soon as any cell has a value, or the task is no longer running. Other notes ("Saved evidence.csv.", "Not saved.") behave as today.
- **Drawer and live data.** The drawer follows its cell by row id and column id, and updates when the table re-renders. It closes if the row or column is gone. Esc closes the drawer first, then exits Focus on a second press.
- **Shortcut.** Only the split handle has a keydown handler today (`agent.js`), so ⌘\ / Ctrl+\ is free. Ignore it while typing in an input, textarea or select.
- **The research chat view** (`2026-11-27-simple-chat-view-design.md`):
  - **Research tasks only.** Code tasks, the Running view's compact copy and a subagent's nested "Show activity" stream keep the Simple above.
  - **What `stays()` keeps outside the work line, in full:** your messages, the reply, messages still streaming, asks, errors and blob errors, any call whose result status is present and not `ok`, open or unanswered teams, subagents that are not cleanly finished, every status, gap and unsupported row, the newest scope row while it is `edited`, plans, diffs, non-research calls, and a citation report with any problem (as its warn line).
  - **Interim messages** (a final assistant message with a later one in the same turn) fold only once that later reply exists, so nothing disappears just as it finishes.
  - **Long means over 600 characters.** Only earlier turns are cut: about 240 characters of your message, about 300 of a reply. The newest turn and pending, failed or streaming messages are never cut.
  - **The display switches still decide what exists and is counted;** Simple decides only how it is folded. With Thinking hidden, reasoning is neither shown nor counted.

## Left to the builder

- Exact spacing, colours (use the existing CSS variables) and the drawer's width (about 360px; full width under 600px).
- Where exactly the Simple/Detailed header toggle sits in the topbar, as long as it is visible in both split and narrow layouts.
- How the per-card expansion state is kept (a `Set` of keys in the stream module is fine).
- The test changes needed to keep existing suites green, plus new UI tests for:
  - Focus on and off, including Esc;
  - sidebar collapse persisting across a reload;
  - compact cells and the drawer (open, resolve from the drawer, Esc);
  - short paper labels;
  - Simple mode collapsing subagent, team and orchestration cards while approval still works;
  - Detailed restoring today's view;
  - old display settings loading as Simple.
