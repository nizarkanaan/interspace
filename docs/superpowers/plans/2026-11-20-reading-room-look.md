# Reading-room look Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restyle the Mac app UI in `app/ui/` to the reading-room look.

**Architecture:** Change the tokens and type in `desk.css` in place. Add one "Reading room" block at the end of the stylesheet for the structural rules (gutter, serif reading, sentence-case badges). Make small markup edits in `research-cards.js` for citation-style metadata and the reference gutter.

**Tech Stack:** Plain CSS and JS; the Playwright UI suites in `tests/*-ui.mjs`, run with `tests/run-ui.cjs`.

**Spec:** `docs/superpowers/specs/2026-11-20-reading-room-look-design.md`

## Global Constraints

- Use only system fonts: `ui-serif`, `system-ui`, `ui-monospace`. Do not change the CSP.
- The token values are exactly as in the spec's table.
- State status in words. Colour only repeats it.
- Keep existing visible text that the tests assert. Reference rows keep the text `Reference N`, and status labels stay unchanged.

## Review Focus

- Long titles, author lists and DOIs in the gutter layout must wrap; there must be no horizontal scroll at 320–600px.
- Dark mode, and browsers without `light-dark()` (the `@supports` fallback), must get the new palette.
- Keyboard focus must stay visible against the new green accent.
- The retracted alert and error notices must stay oxblood and readable in both themes.
- Code blocks, diffs and tool output must stay monospace and must not become serif.

---

### Task 1: Tokens and type

**Files:** Modify `app/ui/desk.css` lines 1–3 (tokens, the `@supports` fallback, `body` font).

- [ ] Replace the token values with the spec's palette in both `light-dark()` and the fallback.
- [ ] Set the body font to `system-ui`. Add `--serif: ui-serif, 'New York', Georgia, serif`.
- [ ] Run `node tests/run-ui.cjs`. Expected: every suite reports a pass.

### Task 2: Reading-room block and research markup

**Files:** Modify the end of `app/ui/desk.css`, and the `paper()`, `referenceRow()` and `toolCard()` functions in `app/ui/research-cards.js`.

- [ ] Use serif headings at the 13/15/17/21/27/34 scale. Use serif for `.md`, the stream messages, paper titles and reference input. Cap reading width near 70ch.
- [ ] Use a 4px radius for cards and controls. Remove uppercase from `.badge` and `.paper-flag`.
- [ ] Paper metadata: `Authors (Year). Venue.` Paper lists get a numbered gutter through a CSS counter.
- [ ] Reference rows get a two-column grid. The left gutter holds `Reference N`, with "Reference" visually hidden, and a status-coloured rule.
- [ ] Run `node tests/run-ui.cjs`. Expected: every suite reports a pass.

### Task 3: Visual check

- [ ] Screenshot Tasks, Research, a citation report, Settings and the agent stream in light, dark and 390px widths. Fix any overflow or contrast problems.
