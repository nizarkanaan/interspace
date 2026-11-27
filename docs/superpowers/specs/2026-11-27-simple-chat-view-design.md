# Simple as a chat, Back to the parent, and replies that keep their place

## Intent

After the first two rounds of the readable workspace, the user ran the full demo again and reported three problems:

- **Back from a subagent goes to the wrong place.** "When you open a research activity like the citation checker, if I try to go back or close it, it takes me back to the list of research tasks, not the one I was actually working in."
- **Simple and Detailed look the same.** "I don't see the difference between simple and detailed view."
- **Simple still needs far too much scrolling.** "Simple view has a lot and lot of scrolling downwards; it becomes a pain for the user."

The user leads a live demo of the Research tab for a networking lab. The presenter must be able to show a whole research chat with little scrolling, and must never lose their place when they look inside a subagent.

The user approved building all three, plus a reply-id bug found while measuring.

## What we measured (real runs, 2026-11-27)

The measurements below come from replaying each task's real `events.jsonl` into the UI test page. The full numbers, screenshots and the three competing designs are in the workflow findings: `simple-chat-findings.json` (the controller hands its path to builders).

| Run | Simple | Detailed | What Simple folded |
|---|---|---|---|
| New demo run (`baa91790…`, 2 turns when measured) | 6,667px (11.4 screens) | 7,617px | 4 of 36 items (2 orchestration cards, 1 team card, 1 subagent card) |
| Rehearsal (`1f73d019…`) | 9,869px (12.8 screens) | 14,783px | team, subagent and orchestration cards |

Simple never touches what makes a research chat long:

- the citation report card listing every reference (2,251px in the new run, 3,345px in the rehearsal);
- the Orchestrator's long replies (1,980px and 4,736px);
- the paper-search summary cards (20 of them, 1,391px);
- reasoning summaries, budget and scope rows.

## Goals

### 1. Back returns to the parent

- Inside a subagent's task (one with a parent), the Back button names the parent: "← DRL for RAN slice resource allocation". The full title is in its `title`; the label is cut with an ellipsis so it never overflows at 320px.
- Back opens the parent task. A root task keeps "← Research" / "← Tasks" and its list, as today.
- If the parent is gone (no row, or its row is unavailable), Back falls back to today's list, and the "Part of “…”" link is not offered. Nothing opens an empty "Agent task xxxx" view.
- On any return to the parent (Back, the "Part of" link, or the parent's sidebar row), the parent's conversation is scrolled so the subagent card (or the work line holding it) sits where it was. It does not jump to the bottom. Keyboard focus goes back to the control that opened the child (its Open button), with `preventScroll`.
- While a child is shown, the parent's sidebar row stays marked current (`aria-current`).
- Esc is not bound to Back (the Esc order stays: drawer, then Focus).

### 2. Replies keep their place after a restart

- Today the Claude runtime numbers its items `msg_N` from 1 in every new session (`app/backend/runtime/claude.py`, `_counter` reset per `ClaudeSession`). After an app restart, the next reply in an existing task reuses `msg_1`, and the UI, which keys items by `item_id`, draws it over that task's first reply.
- Fix both ends:
  - **Backend:** item ids for messages and reasoning are unique per task across sessions (for example by including the turn id), so new logs never collide.
  - **UI:** for logs already written, a `message`, `message_delta` or `reasoning` event whose key already belongs to a different turn is stored under a turn-scoped key. Keys that do not collide stay as they are.
- **The stream's node cache is per task.** Today `render()` caches nodes per container only, and the parent and child share `#agent-stream`, so after visiting a child the parent can show the child's nodes (item keys like `user_u1`, `seq:N` and `cumulative` repeat across tasks). The cache is reset when the container shows a different task.

### 3. Simple reads as a chat (research tasks only)

The design is the judge panel's synthesis (findings file, `judge.synthesis`): each turn is **your message, one work line, the reply**.

- **Where it applies:** research tasks in Simple, in the main conversation. Code tasks, the Running view's compact copy, and a subagent's nested "Show activity" stream keep today's Simple.
- **Turns:** the conversation splits at each of your messages. Items before the first one join turn 1.
- **Your message:** in full in the newest turn, and while pending or failed. In an earlier turn, one over 600 characters shows about its first 240 characters, then **Show whole message ▾**.
- **The reply** (the last assistant message of a turn): in full in the newest turn and while streaming. In an earlier turn, one over 600 characters shows about its first 300 characters, then **Show whole reply ▾**; **Show less ▴** folds it back. Blocks past the cut get `hidden`, the block that crosses it is clamped to 3 lines, and links inside a cut block are not focusable. The choice is kept for the session.
- **Interim assistant messages** ("I'll start by searching…") fold into the work line only once a later assistant message exists in the same turn, so nothing disappears just as it finishes.
- **The work line**, one per turn that has folded items, placed after your message: a quiet line such as "Searched 4 sources 11 times · 196 papers · saved report.md · 25 steps   Details ▸".
  - It counts what it folded: sources searched, distinct papers, look-ups, report saved, claim verdicts and table values recorded, finished subagents, an answered team, a fully verified citation report, and the step count.
  - While the turn runs it starts with "Working ·" and the newest step ("Working · Searching “O-RAN xApp slicing”").
  - Up to 2 **Open <provider> <role>** buttons open finished subagents directly.
  - **Details ▸ / Hide details ▾** (with `aria-expanded`) puts the folded items back in place, in order, indented, each with its own controls, followed by a closing **Hide details ▴**. The choice is kept for the session.
- **Folds into the work line:** research calls that are ok or still running, reasoning (counted only when Thinking is not Hidden), budget rows, settled scope rows, an answered team, cleanly finished subagents, a citation report with every reference verified ("17 references checked: all verified"), ok orchestration calls (hidden and not counted, as today).
- **Stays outside, in full (never folded):**
  - an open team proposal (today's short card with Approve team, Decline, Edit team);
  - questions for the user (asks), open or answered;
  - the newest scope row while it still needs approval, and every other scope-approval control;
  - error cards, blob errors, the stream load error;
  - any call whose result status is present and not `ok`;
  - every notable status row (queued, waiting for a lock, paused for scope, cancelling, failed, cancelled, budget exhausted, time limit, interrupted), plus gap and unsupported rows;
  - subagents that are running, queued, starting, waiting, paused, or that ended badly (today's one-line card);
  - plans, command cards and diffs, governed by their switches as today.
- **A citation report with any problem** (mismatch, not found, unchecked or retracted) stays outside as one warn-coloured line: "Citations: 48 of 49 verified · 1 mismatch" (plus "· 1 retracted: do not cite"), with **Show citation report ▸** and, on a root research task, **Open Corpus ›** (switches the results tab). Show opens a brief card in place: the counts, the retracted alert, only the problem rows (problems first, at most 10) and today's **Show all N references**.
- **The display switches still decide what exists and is counted.** Simple only decides how it is folded.
- **Seeing that Simple is on:** the header keeps the **Simple | Detailed** switch. Beside it, a quiet note says how many steps are folded ("31 steps folded"), linked with `aria-describedby`. It moves with the switch between the split top bar and the narrow layout, and is hidden in Detailed, when nothing is folded, and in Focus.
- **Settings → Conversation detail** help text: "Simple shows your messages, the replies and anything that needs you; each turn's agent work folds into one line you can open. Detailed shows every step."
- **Detailed is unchanged**, apart from the two bug fixes.

## Non-goals

- No change to what the backend records, except the unique item ids.
- No new libraries or build tools. Plain JS and CSS.
- No change to code tasks' Simple view, to the results pane, or to Focus.
- Esc does not go Back.

## Anti-goals

- Hiding anything that needs the user, in either view.
- Any detail becoming unreachable: everything folded is one click away in place, or one switch to Detailed.
- Breaking keyboard use or screen-reader labels. Buttons that open and close carry `aria-expanded`; their accessible names start with their visible text.
- Breaking the narrow (≤600px) layout or dark mode. No horizontal overflow at 320, 390 or 600px.
- A newest reply, or a reply still streaming, being cut.

## Constraints

- Tests: `python3 -m unittest discover -s tests -q` and `node tests/run-ui.cjs <suite>` for every suite listed in `tests/run-ui.cjs`. All must pass. Suites that read per-step cards in a research task's stream must either install Detailed or open the work line first.
- New UI suite for the chat view, registered in `tests/run-ui.cjs`.
- After the change: `graphify update .`, then rebuild with `python3 scripts/build-macos-app.py` (the controller does this, after merging).
- Commits: no Claude attribution or co-author lines.

## Approaches

1. **Turn digest built inside `stream.js` render (chosen).** One pass over the visible items groups them into turns and emits synthetic work-line entries, reusing the existing per-item renderers and node cache. It is the judge's winner: Simple becomes structurally different from Detailed, and nothing that needs the user can be swallowed because a single `stays()` rule decides.
2. **Fold each long card in place.** Least code, but Simple keeps 36 separate items and still needs about 3 screens; the user would still find it hard to tell from Detailed.
3. **Turn digests that point to the results tabs, and cut every reply.** Shortest (about 1.4 screens), but it cuts the newest reply the presenter just asked for, and claims and evidence events carry no turn id, so their pointers would rely on guessing.

## Left to the builder

- Exact spacing and colours (existing CSS variables only).
- How the turn grouping, the open sets and the counts are stored, as long as reconciliation keeps focus, opened details and scroll position across new events.
- Which existing tests need Detailed installed and which should open the work line.
