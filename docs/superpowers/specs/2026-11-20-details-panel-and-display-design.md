# Task details panel and conversation display setting

Date: 2026-11-20
Status: approved in conversation ("Yes, build both", via /frontend-design)
Size: small change

## Intent

The task's status, scope and outputs sat at the top of the conversation, so the user had to scroll up to change the scope or open a report. The conversation also showed every search result and reasoning note in full. The user wants:

- the controls kept apart from the chat;
- short summaries of thinking and of the papers searched;
- only the kinds of output they choose.

## Task details: a margin beside the conversation

This continues the reading-room idea. The task's controls become a margin note beside the text:

- **The panel.** Status, Stop, tokens, research requests, scope (chips, Edit, Approve) and Outputs move into `#agent-details`. This is a 340px column on the right. It is sticky, scrolls on its own, and is set off by a hairline rule. It uses the same leaf background as the conversation, not a card.
- **The main column** holds: back, the tabs (Conversation | Corpus), the conversation and the composer.
- **The scope editor** opens in the main column, above the conversation, where it has room. The page scrolls to it.
- **Scope waiting for approval.** While the scope is unapproved, a one-line notice sits above the conversation: "Approve the scope before the agent can start." Its **Show scope** button moves focus to the panel's Approve button, and in a narrow window it opens the Details tab first, so there is only one Approve button. No task can sit waiting unnoticed.
- **Narrow windows.** Below 1100px the panel becomes a third tab, **Details**. That tab exists for every agent task. Corpus stays research-only.

```
┌ sidebar ┬ ← Research                              ┬ Running        [Stop] │
│         │ Conversation  Corpus                    │ Tokens 0 · 30,369 res. │
│         │ You  Write a literature review…         │ Research requests …    │
│         │ Searched “fallback 112” in OpenAlex: 8  │ Scope  Approved · v1   │
│         │ Agent  The evidence on fallback…        │ [Edit scope]           │
│         │ [Message the agent…            ] [Send] │ Outputs  report.md     │
└─────────┴─────────────────────────────────────────┴────────────────────────┘
```

## Conversation display (Settings)

The setting is stored in `state['display']` (`display.py`), shown to the UI as `state.display`, and changed with `display_update {display}`. That method is added to the Swift allowlist. It applies to every task.

```json
{"v": 1, "thinking": "summary", "searches": "summary", "tools": true, "citations": true, "plans": true, "notes": true}
```

- **Thinking: Summary, Full or Hidden.** The providers already send reasoning summaries.
  - Summary shows the first 280 characters, or the first paragraph, inline, with a "Show all" control.
  - Full shows the whole note.
- **Paper searches: Summary, Full or Hidden.** This covers research tool cards, and is the default because the Corpus now holds the lists.
  - Summary is one line per call. For example: `Searched “fallback 112” in OpenAlex, Crossref: 8 papers`, `Looked up doi:…: found “Title”`, `Followed citations of arXiv:…: 12 papers`, `Checked 12 references`. Each line has a **Show details** control that expands that card in place.
- **Show or hide:** command and file activity (`tools`), citation reports (`citations`), plans (`plans`), and status notes, meaning the scope, token and status lines (`notes`).
- **Always shown:** your messages, agent replies, questions waiting for your answer, team proposals, subagents, errors, and any tool call that failed.
- No AI call is made to summarize. Summaries come only from what is already recorded.

## Also in this change

- Switching back to Conversation lands on the latest message (done earlier in this session).

## Calls made by the designer

- The panel is 340px wide, and the narrow breakpoint is 1100px.
- Summary is the default for both thinking and searches.
- The Details tab is shown only in narrow windows.
