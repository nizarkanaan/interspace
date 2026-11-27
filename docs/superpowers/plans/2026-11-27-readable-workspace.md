# Readable Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the research workspace readable. It adds a compact evidence table with a cell drawer, a Focus mode for the results pane, a collapsible sidebar, and a Simple/Detailed conversation with Simple as the default.

**Architecture:** Extend the existing plain-JS renderers in place: `stream.js`/`team-card.js` for the conversation, `evidence.js` for the table, `agent.js` for Focus, `app.js` for the sidebar. Styles go in `desk.css`. One backend change adds the `detail` display key in `display.py`.

**Tech Stack:** Plain JS and CSS in a WKWebView (`app/ui/`), Python stdlib backend, UI tests through `node tests/run-ui.cjs <suite>` (Playwright and Chrome), Python tests through `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-27-readable-workspace-design.md`

## Global Constraints

- No new libraries or build tools. Only plain text glyphs: ◀, ☰, ▸, ×.
- Use existing CSS variables (`--bg`, `--surface`, `--line`, `--accent`, `--warn`, `--muted`, `--ink`, `--subtle`). Light and dark must both work.
- Team approvals, questions for the user, errors and failed calls always show in full, in both Simple and Detailed.
- Everything Simple hides is one click away.
- Every new control is a `<button type="button">` (or a native input) with a visible label or `aria-label`; expanders carry `aria-expanded`.
- The narrow layout (≤600px) and the existing split reader (`split` class, the `placed` scroll guard in `agent.js`) keep working.
- Display `detail`: `'simple' | 'detailed'`, default `'simple'`. Settings saved without it load as Simple.
- Paper label: the surname is the first author's last word, or the text before a comma. One author gives `Zhang 2022`, two give `Zhang & Zhou 2022`, three or more give `Zhang et al. 2022`. No usable authors means the title, clamped to 2 lines. No year means no year.
- Simple hides `category === 'orchestrate'` tool cards regardless of the "Commands and file changes" switch, unless `result.status` is present and not `'ok'`.
- Esc closes the evidence drawer first, then exits Focus.
- The sidebar shortcut is ⌘\ on macOS and Ctrl+\ elsewhere. It is ignored while focus is in an input, textarea or select. The localStorage key is `interspace.sidebarCollapsed` (`'1'` or `'0'`).
- Commit messages: one plain sentence, no attribution trailers.
- Python tests: `python3 -m unittest discover -s tests -q`. UI: every suite listed in `tests/run-ui.cjs`.

## Review Focus

1. **Approving a team in Simple:** **Approve team** must send exactly the proposed members, with nothing edited, and `team_answer` must carry the same payload as in Detailed. Test in Task 2.
2. **Resolving a disagreement from the drawer while the table re-renders** (a live fill): the drawer must stay on the same cell, and **Use Claude's** must resolve that cell, not another. Test in Task 5.
3. **Focus with the sidebar already collapsed, then exit:** the sidebar must come back collapsed, not expanded. Focus must not change the saved sidebar choice. Test in Task 4.
4. **Old display settings stored without `detail`:** they load as Simple, and Settings shows Simple selected. Test in Task 1.
5. **A paper whose authors entry is a single string, or contains empty strings:** the label must fall back to the title, never `undefined` or ` et al.`. Test in Task 5.

---

### Task 1: The `detail` display setting

**Files:**
- Modify: `app/backend/display.py` (`default()`, `validate()`)
- Modify: `app/ui/display.js` (`DEFAULT`, `valid()`, `renderSettings`, exports)
- Test: `tests/test_display.py`, `tests/display-ui.mjs`

**Interfaces:**
- Produces: `state.display.detail ∈ {'simple','detailed'}`.
- Produces: `window.interspaceDisplay.get().detail`.
- Produces: `window.interspaceDisplay.setDetail(value: 'simple'|'detailed') -> void`. It saves through the existing `display_update` path, the same way a Settings change does.

- [ ] **Step 1: Write the failing tests**
  - `tests/test_display.py`:
    - `default()['detail'] == 'simple'`;
    - `validate({'detail': 'detailed'})['detail'] == 'detailed'`;
    - `validate({'detail': 'loud'})` raises `ValueError` with "Detail must be simple or detailed.";
    - `validate({'thinking': 'full'})['detail'] == 'simple'` (old settings).
  - `tests/display-ui.mjs`:
    - Settings → Conversation display shows a fieldset "Conversation detail" with radios Simple (checked by default) and Detailed;
    - choosing Detailed sends `display_update` with `detail: 'detailed'`;
    - with a fixture `display` that has no `detail`, Simple is checked.
- [ ] **Step 2: Run them and see them fail**
  `python3 -m unittest tests.test_display -v` and `node tests/run-ui.cjs display-ui`, both FAIL.
- [ ] **Step 3: Implement**
  - Add `'detail': 'simple'` to `default()` and validate it with that message.
  - In `display.js`, add `detail` to `DEFAULT` and `valid()`.
  - Add the radio fieldset first in the form, with help text: "Simple folds team and subagent details into one line you can open. Detailed shows everything."
  - Export `setDetail`.
- [ ] **Step 4: Run them and see them pass**, the same commands.
- [ ] **Step 5: Commit** — "Add a Simple or Detailed conversation setting".

---

### Task 2: Simple conversation

**Files:**
- Modify: `app/ui/stream.js` (`visible()`, `build()`, the subagent card path)
- Modify: `app/ui/team-card.js` (`teamCard`, `subagentCard`)
- Modify: `app/ui/agent.js` and `app/ui/index.html` (header toggle in `#agent-head` area)
- Modify: `app/ui/desk.css`
- Modify: existing UI suites that assert full team or subagent cards, so their fixtures set `display.detail: 'detailed'`. Find them by running every suite after the change.
- Test: `tests/team-card-ui.mjs`, `tests/subagents-ui.mjs`

**Interfaces:**
- Consumes: `window.interspaceDisplay.get().detail` and `setDetail` (Task 1).
- Produces these DOM contracts for tests:
  - The header toggle is `button#agent-detail-toggle`, with text `Simple view` when detail is simple and `Detailed view` when detailed, and `aria-pressed` set to `"true"` when detailed. Clicking it calls `setDetail` with the other value.
  - The Simple subagent line is `article.card.subagent.is-line`. It contains the provider badge, the role title, the state word, and `button.sub-details` (text `Details ▸`, `aria-expanded="false"`). Clicking it renders today's full card in place and keeps that open for the session (a module-level `Set` of item keys).
  - The Simple pending team card is `article.card.team.is-simple`. It shows the title "Proposed team", the summary if any, one `li` per member ("Codex researcher · reads"), and **Approve team**, **Decline** and `button.team-edit` (text `Edit team`). **Edit team** reveals today's member editors in the same card.
  - The Simple answered team is `article.card.team.is-line`, with the text `Team approved · <members>` or `Team declined`, and `button.team-details` (`Details ▸`) that expands today's answered card.
  - Simple hides orchestrate tool cards, as in Global Constraints.

- [ ] **Step 1: Write the failing tests**
  - In `team-card-ui.mjs`, with default display (Simple):
    - a pending proposal shows `.team.is-simple` with **Approve team** visible and no member editor inputs;
    - **Approve team** sends `team_answer` deep-equal to the payload the Detailed path sends for the same untouched proposal;
    - **Edit team** shows the editors;
    - after the answer the card is `.team.is-line` with text starting `Team approved`.
  - In `subagents-ui.mjs`, Simple:
    - a subagent renders as `.subagent.is-line` without its brief text;
    - `Details ▸` expands it to show the brief and the `Open` button;
    - an orchestrate tool card with `result.status: 'ok'` is absent;
    - one with `result.status: 'error'` is present.
  - Detailed (fixture `display.detail='detailed'` or the header toggle): today's assertions hold unchanged.
  - The header toggle flips the view and sends `display_update` with the new `detail`.
- [ ] **Step 2: Run and see them fail:** `node tests/run-ui.cjs team-card-ui` and `node tests/run-ui.cjs subagents-ui`.
- [ ] **Step 3: Implement** to the DOM contracts above. Asks, errors and failed calls are never affected.
- [ ] **Step 4: Run every UI suite.** Set `detail: 'detailed'` in the fixtures of any suite that breaks only because it expects today's full cards. Then run `python3 -m unittest discover -s tests -q`. Everything must pass.
- [ ] **Step 5: Commit** — "Fold team, subagent and orchestration details into one line in a Simple conversation".

---

### Task 3: Collapsible sidebar

**Files:**
- Modify: `app/ui/index.html` (a collapse button at the top of `aside`, an expand button for the rail)
- Modify: `app/ui/app.js` (toggle, persistence, shortcut)
- Modify: `app/ui/desk.css`
- Test: `tests/sidebar-ui.mjs`

**Interfaces:**
- Produces: `document.body.classList` contains `sidebar-collapsed` while collapsed.
- Produces: `button#sidebar-collapse` (`aria-label="Hide sidebar"`, text `◀`) and `button#sidebar-expand` (`aria-label="Show sidebar"`, text `☰`, shown only while collapsed).
- Produces: `window.interspaceSidebar = {collapsed(): boolean, set(collapsed: boolean, {persist=true}={}): void}`, which Task 4 uses to hide it during Focus without saving.

- [ ] **Step 1: Write the failing test** in `sidebar-ui.mjs`:
  - clicking `#sidebar-collapse` adds `body.sidebar-collapsed`;
  - the `aside` measures ≤ 48px wide and the main area grows by at least 150px;
  - `localStorage['interspace.sidebarCollapsed']==='1'`;
  - after `page.reload()` it is still collapsed;
  - `#sidebar-expand` restores it;
  - `ControlOrMeta+Backslash` toggles it;
  - the same key while typing in `#agent-message` does not;
  - at 390px width neither button is visible.
- [ ] **Step 2: Run and see it fail:** `node tests/run-ui.cjs sidebar-ui`.
- [ ] **Step 3: Implement.** The rail keeps the `aside` element but hides its children except `#sidebar-expand`. The grid column becomes 44px. `set(v, {persist:false})` changes the class without writing localStorage.
- [ ] **Step 4: Run** `sidebar-ui` and `reader-ui` (split widths must still compute). PASS.
- [ ] **Step 5: Commit** — "Let the sidebar collapse to a thin rail and remember it".

---

### Task 4: Focus mode for the results pane

**Files:**
- Modify: `app/ui/agent.js` (button, state, Esc, banner)
- Modify: `app/ui/index.html` (a `#agent-focus-banner` container in the results pane)
- Modify: `app/ui/desk.css`
- Test: `tests/research-task-ui.mjs` (or `reader-ui.mjs` if its fixture fits better)

**Interfaces:**
- Consumes: `window.interspaceSidebar.collapsed()` and `.set(v, {persist:false})` (Task 3).
- Produces: `button#agent-focus` in the results tab row, shown only while the split reader is placed. Its text is `Focus` / `Exit focus`, and it carries `aria-pressed`.
- Produces: `#agent-view.focus` while focused.
- Produces: `window.interspaceAgent.focus(on: boolean): void` and `window.interspaceAgent.isFocused(): boolean`.
- Needs-user rule: the task row state is one of `paused_ask`, `paused_scope` or `paused_team`. These are the same states `sidebar.js` `NEEDS` uses, with the same wording: "Answer a question", "Approve a scope change", "Approve the team".

- [ ] **Step 1: Write the failing test:**
  - `#agent-focus` toggles `#agent-view.focus`;
  - while focused, the conversation column and the `aside` are not visible, and the results pane is at least 90% of the viewport width;
  - Esc exits;
  - when the evidence drawer is open, the first Esc closes the drawer and the second exits Focus (this check moves to Task 5's suite if the drawer is not built yet: Task 5 owns it);
  - Focus on → push a row state `paused_team` → `#agent-focus-banner` is visible with the text "Approve the team" and a `Go to conversation` button, which exits Focus and scrolls the team card into view;
  - collapse the sidebar, enter and exit Focus → the sidebar is still collapsed and `localStorage` is unchanged;
  - leaving the task (navigating to Settings) also exits Focus.
- [ ] **Step 2: Run and see it fail.**
- [ ] **Step 3: Implement.**
  - Focus is a class on top of `split`. CSS hides `.agent-main` (the conversation) and the `aside`, and widens `#agent-results` to the full width.
  - `place(false)` and `renderAgent`'s hidden path also exit Focus.
  - Esc handling goes through one document `keydown` listener in `agent.js`. It asks evidence first, through `window.interspaceEvidence.closeDrawer(): boolean` (Task 5; until then, treat it as absent).
- [ ] **Step 4: Run** this suite plus `reader-ui`, `corpus-ui` and `evidence-ui`. PASS.
- [ ] **Step 5: Commit** — "Add a Focus mode that gives the results pane the whole window".

---

### Task 5: Compact evidence table, cell drawer and labels

**Files:**
- Modify: `app/ui/evidence.js` (`cell`, `render`, new `paperLabel`, the drawer)
- Modify: `app/ui/agent.js` (`evidenceArea` note clearing, around line 241)
- Modify: `app/ui/desk.css` (`.ev-*` rules)
- Test: `tests/evidence-ui.mjs`

**Interfaces:**
- Consumes: Focus Esc ordering (Task 4).
- Produces:
  - `window.interspaceEvidence.paperLabel(paper: {authors?, title?, year?}) -> {label: string, clamp: boolean}`, where `clamp` is true when it fell back to the title;
  - `window.interspaceEvidence.closeDrawer(): boolean`, which returns true if a drawer was open.
- Cell DOM:
  - `td.ev-cell.is-<status>` holds `span.ev-word` and the value. A disagree cell holds two `span.ev-pair` lines, `Claude: <value>` and `Codex: <value>`.
  - There are no quotes or buttons inside cells.
  - The whole `td` is focusable (`tabIndex=0`) and opens the drawer on click or Enter.
- Drawer: `aside#ev-drawer[role=region][aria-label="Cell details"]` inside the evidence container. It shows the paper's full title and year, the column name and instruction, each provider's value and quote, and for disagree cells **Use Claude's**, **Use Codex's** and **Type my own**, through the existing `onResolve` path. Resolved cells show **Undo**. It has a `button.ev-drawer-close` (×). It is identified by `rowId:colId` and kept in `ui.drawer`.

- [ ] **Step 1: Write the failing tests** in `evidence-ui.mjs`:
  - `paperLabel` table test:
    - `{authors:['Han Zhang'],year:2022}` gives `Zhang 2022`;
    - `['Han Zhang','Hao Zhou']` gives `Zhang & Zhou 2022`;
    - three authors give `Zhang et al. 2022`;
    - `['Zhang, Han','Zhou, Hao','X Y']` gives `Zhang et al. 2022`;
    - `{authors:'Han Zhang',title:'T'}` gives `{label:'T',clamp:true}`;
    - `{authors:['',''],title:'T',year:null}` gives `{label:'T',clamp:true}`.
  - The table shows these labels in the paper column, with the full title in the `title` attribute.
  - A disagree cell has two `.ev-pair` lines, no `blockquote` and no buttons.
  - Clicking it opens `#ev-drawer` with both quotes. **Use Claude's** sends `table_resolve` with that cell's `row`, `column` and Claude's value.
  - A re-render from a pushed table update while the drawer is open keeps it on the same `rowId:colId`.
  - Esc closes the drawer.
  - The note "Asked the Orchestrator…" disappears once any cell has a value.
  - `.ev-wrap` has no fixed `max-height: 70vh`; its bottom edge is within the viewport at 1280×800.
- [ ] **Step 2: Run and see them fail:** `node tests/run-ui.cjs evidence-ui`.
- [ ] **Step 3: Implement.**
  - Paper column 170px, value columns `min-width:120px; max-width:220px`, values clamped to 3 lines (`-webkit-line-clamp`).
  - `.ev-wrap` height comes from the pane: CSS `max-height: calc(100vh - <top offset>)`, measured once on render, or flex in the split column. Either is fine if the test passes.
  - Arrow keys move focus between cell `td`s.
- [ ] **Step 4: Run** `evidence-ui`, `research-e2e-ui` and `reader-ui`. PASS.
- [ ] **Step 5: Commit** — "Show the evidence table compactly, with details in a drawer and short paper labels".

---

### Task 6: Full suite, docs, build

**Files:**
- Modify: `app/README.md` (a short paragraph covering the split reader, Focus, the sidebar collapse and ⌘\, Simple/Detailed, and the evidence drawer)

- [ ] **Step 1:** Run `python3 -m unittest discover -s tests -q`, then every suite in `tests/run-ui.cjs`. All PASS.
- [ ] **Step 2:** Update the README paragraph in plain sentences, and commit — "Describe Focus, the sidebar rail, Simple conversations and the evidence drawer".
- [ ] **Step 3:** The controller runs `python3 scripts/build-macos-app.py`, then `graphify update .`, after merging.
