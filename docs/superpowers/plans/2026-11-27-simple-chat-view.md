# Simple Chat View, Back to the Parent, and Stable Reply Ids Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A research task's Simple conversation reads as a chat (your message, one work line, the reply), Back from a subagent returns to its parent where you left it, and replies keep their place after an app restart.

**Architecture:** One pass inside `stream.js` `render()` groups the visible items into turns and emits synthetic work-line entries. It reuses the existing per-item renderers and the node cache. A single `stays()` rule decides what never folds. Back-navigation state lives in `agent.js` (a `returns` map, restored after `S.render`). The id collision is fixed at both ends: the Claude runtime makes ids unique per task, and the UI turn-scopes colliding keys in old logs.

**Tech Stack:** Plain JS and CSS in a WKWebView (`app/ui/`), Python stdlib backend, UI suites through `node tests/run-ui.cjs <suite>` (Playwright and Chrome), Python tests through `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-27-simple-chat-view-design.md`. Line-level notes from the judge and the back-navigation analysis are in the controller's findings file `simple-chat-findings.json` (`judge.synthesis.code_changes`, `back_navigation.fix_proposal`). The line numbers below were checked against this branch (main + the spec commit).

**Task order:** 1 and 2 fix the bugs the digest depends on. 3 adds the pure helpers the digest calls. 4 is the digest. 5 and 6 refine it. 7 adds the header note, Settings text and docs, and runs the full gate. Each task updates the existing suites its own change breaks, so every suite is green at the end of every task. Only `display-ui` and `research-cards-ui` read per-step research cards in Simple; Task 4 fixes them. The other research suites either install Detailed (`research-task-ui`; `research-e2e-ui` through `tests/e2e/research_backend.py:313`) or hold no foldable items (`reader-ui`, `evidence-ui`, `claims-ui`, `corpus-ui`).

## Global Constraints

- Work only in the worktree `/Users/nizarkanaan/Documents/Projects/interspace-simple-chat` (branch `simple-chat-view`). Do not push, merge or switch branches. Do not run `graphify update`, `scripts/build-macos-app.py`, or anything that touches the running app or `~/Library/Application Support/Interspace`.
- Commits: one plain descriptive sentence, in the style of `git log`. No attribution and no co-author trailers.
- Tests: `python3 -m unittest discover -s tests -q`, and `node tests/run-ui.cjs <suite>`. A suite passes when its last line is a JSON `{"suite":…}`.
- Plain JS and CSS. Use only the existing CSS variables (`--bg --leaf --surface --subtle --ink --muted --line --accent --on-accent --warn`), so dark mode follows. No horizontal page overflow at 320, 390 or 600px, in light or dark.
- Every control is a `<button type="button">`. Buttons that open and close carry `aria-expanded`. An accessible name starts with the visible text. Arrow glyphs (▸ ▾ ▴ ›) go in an `aria-hidden="true"` span, as `detailsButton()` does (`team-card.js:95`).
- **Where the chat view applies:** `!options.compact && !options.nested && display().detail!=='detailed' && interspaceAgent.isResearch(taskId)`. Code tasks, the Running view's compact copy and a subagent's nested "Show activity" stream keep today's Simple. Detailed is unchanged apart from the two bug fixes.
- **Turns:** split the visible list (Map insertion order) at each user message, pending ones included. Items before the first user message join turn 1. A turn's lead is its user message; turn 1 without one uses the lead key `start`.
- **Folds into the work line** (counted as one step each): a research call (`call.category==='research'`) with no result or `result.status==='ok'`; reasoning; budget rows; scope rows, except the newest scope row while its `change==='edited'`; a team with `it.team.answered`; a subagent whose state is `completed`, or `idle` with `sub.finished`; a citation report with zero problems; an interim assistant message (final, with a later assistant message in the same turn). Everything else stays outside, in full. That includes user messages, the reply, non-final messages, asks, errors, blob errors, any result with a status that is not `ok`, open or closed-unanswered teams, every other subagent, all status, gap and unsupported rows, plans, diffs and non-research calls. Ok orchestration calls stay hidden by `visible()` and are not counted. The display switches decide what exists and is counted; Simple decides only how it is folded.
- **Long messages:** over **600** characters (`text.length>600`). An earlier-turn user message shows about its first **240** characters, then **Show whole message ▾**. An earlier-turn reply shows about its first **300**, then **Show whole reply ▾**. **Show less ▴** folds it back. Blocks past the cut get `hidden`. The block that crosses the cut gets `.is-cut` (**3**-line clamp), and its links get `tabindex="-1"`. A list that crosses the cut is cut per `li`. Never cut: the newest turn, non-final (streaming), pending or failed messages.
- **Work line:** `div.card.work-line`, `role="group"`, `aria-label="Agent work"`, `data-item="work:<lead>"`, placed right after the turn's lead. Part order, joined by " · ": `Team approved` | `Team declined`; `<names> finished` (each name from `workerName`, joined by ", "); `Searched S sources T times` (`once` when T is 1; `Searched T times` when no source is known); `P papers`; `looked up L`; `saved report.md`; `recorded V claim verdicts`; `recorded E evidence values`; `N references checked: all verified`; and always last `K steps` (`1 step`). While the newest turn's task state is in `queued starting running waiting_lock cancelling`, the text starts `Working · <summaryText of the newest folded research call with no result>` (just `Working` when there is none). The line has up to **2** **Open <Provider> <role>** buttons, for the first finished children, then **Details ▸** / **Hide details ▾**. Opened, the folded items follow the line in their original order with `.in-work`, then a closing **Hide details ▴**.
- **Citation pointer:** a report with any problem (mismatch, not found, unchecked, unknown or retracted) is one warn line. Its text is `Citations: <verified> of <total> verified`, then ` · N mismatch`, ` · N not found`, ` · N unchecked`, ` · N unknown`, and last ` · N retracted: do not cite`. Its buttons are **Show citation report ▸** / **Hide citation report ▾** and, on a root research task only, **Open Corpus ›** (accessible name `Open Corpus tab`). The brief card shows the counts, the retracted alert, only the problem rows (problems first, at most **10**), and today's **Show all N references**.
- **Header note:** `#agent-detail-note` says `N steps folded` (`1 step folded`). The switch group has `aria-describedby="agent-detail-note"`, and the note moves with the switch. It is hidden in Detailed, at 0, and in Focus.
- **Settings → Conversation detail help text**, exactly: `Simple shows your messages, the replies and anything that needs you; each turn's agent work folds into one line you can open. Detailed shows every step.`
- **Back:** inside a child whose parent row exists and is not `unavailable`, the label is `'← '+title(parent)`. The full title goes in `title`, and the label is cut with an ellipsis. A root task keeps `← Research` / `← Tasks`. If the parent is gone, Back falls back to the list and no "Part of" link is offered. Esc is not bound to Back.
- **Ids:** the backend uses `msg_<turn_id>_<n>` and `rs_<turn_id>_<n>`. The UI's turn-scoped key for a collision is `<key>@<turn_id>`. DOM ids: `work-<task8>-<lead>`, `work-end-<task8>-<lead>`, `work-open-<child>`, `more-<task8>-<key>`, `msg-<task8>-<key>`, `cite-<task8>-<key>`, `cite-box-<task8>-<key>`. Here `task8` is the first 8 characters of the task id, and every part goes through `safe=s=>String(s).replace(/[^A-Za-z0-9_-]/g,'_')`.
- Opened work lines, whole messages and opened cards are kept for the session in module-level Sets keyed `taskId+'|'+key`, like `unfolded` (`stream.js:232`).

## Review Focus

1. **Live events while a work line is open:** a search finishes and another starts. The line must stay open, the new item must appear last among the `.in-work` items, before **Hide details ▴**, and keyboard focus must stay on the line's button. Pinned in Task 4.
2. **The parent's stream grows above the subagent card while the child is shown,** for example a streaming message above it gets longer. Back must put the card back where it was. A stale pixel offset or the bottom is wrong. Pinned in Task 2.
3. **A mouse click that never focuses the Open button.** WKWebView does not focus clicked buttons, so `document.activeElement` is `BODY`. On return, focus must still land on the child's Open button, found from the child id. Pinned in Task 2 (`sub-open-…`) and Task 4 (`work-open-…`).
4. **An earlier reply that is one long paragraph, or whose cut falls inside a list:** the first lines still show (the crossing block is clamped, never hidden), and nothing past the cut is focusable. Pinned in Task 5.
5. **Switching to Detailed and back while a work line and a whole reply are open:** Detailed shows no work line and no `.in-work` node (no stale class on reused nodes). Simple comes back with both still open. Pinned in Task 4 (line) and Task 5 (reply).

## File map

- `app/backend/runtime/claude.py`: message and reasoning item ids (Task 1).
- `app/ui/stream.js`: turn-scoped keys and per-task cache (1); digest, `stays`, work line (4); previews (5); citation pointer (6); `folded()` export (4).
- `app/ui/research-cards.js`: `summaryText`, `workParts`, `workerName`, `citationCounts`, `citationPointerText`, brief `citationCard` (3).
- `app/ui/agent.js`: Back target, label and return restore (2); `showTab` and `isRoot` for the stream (6); header note (7).
- `app/ui/app.js`: sidebar current row is the root task (2).
- `app/ui/index.html`, `app/ui/display.js`, `app/ui/desk.css`, `app/README.md`, `docs/superpowers/specs/2026-11-27-readable-workspace-design.md`.
- Tests: `tests/runtime/test_claude.py`, `tests/research-fixture.mjs`, `tests/research-task-ui.mjs`, `tests/subagents-ui.mjs`, `tests/research-cards-ui.mjs`, `tests/display-ui.mjs`, the new `tests/simple-view-ui.mjs`, and `tests/run-ui.cjs`.

---

### Task 1: Replies keep their place, and each task keeps its own cards

**Files:**
- Modify: `app/backend/runtime/claude.py:779-785` (`ClaudeSession._assistant`); the counter stays at `:436`.
- Modify: `app/ui/stream.js:40-42` (`apply` message, delta and reasoning cases), `:260-267` (`render` cache).
- Modify: `tests/research-fixture.mjs` (add `evFor`).
- Test: `tests/runtime/test_claude.py` (`TurnTests`), `tests/research-task-ui.mjs` (new last block).

**Interfaces:**
- Produces: `ClaudeSession._item_id(self, prefix: str, ctx) -> str`. It increments `self._counter` and returns `'%s_%s_%d' % (prefix, ctx.turn_id, n)`, or `'%s_%d'` when `ctx.turn_id` is falsy.
- Produces: `turnKey(m, key: string, e) -> string` in `stream.js`. It returns `key+'@'+e.turn_id` when `m.items.get(key)` exists with a `turn` set, `e.turn_id` is a non-empty string, and the two differ. Otherwise it returns `key`. Items created by these three cases store `it.turn=e.turn_id??null` once.
- Produces: `views.get(container)` is `{task, cache: Map}`. It is reset when the container shows another task.
- Produces: `evFor(task) -> (kind, data, item=null, turn='u1') => event` in `research-fixture.mjs`. It gives each task its own seq from 1; `ev()` shares one counter across tasks and would leave a gap row.

- [ ] **Step 1: Write the failing tests**
  - `tests/runtime/test_claude.py`, `TurnTests.test_item_ids_stay_unique_after_a_restart`:
    - Use `first = FakeContext(self.root)` with `first.turn_id='u1'`, and run `self.turn({'turns': [simple_turn('one')]}, ctx=first)`.
    - Then `second = FakeContext(self.root)` with `second.turn_id='u2'`, and a new `self.turn` whose turn is `[INIT, <the thinking emit from test_reasoning_event>, assistant_text('two'), result()]`. A new runtime means a new session, like an app restart.
    - Assert `[i for c in (first, second) for k, _, i in c.events if k in ('message', 'reasoning')] == ['msg_u1_1', 'rs_u2_1', 'msg_u2_2']`.
  - `tests/research-task-ui.mjs`: a new block before the final `pwned` / `errors` asserts. It re-installs with `display:{detail:'detailed'}` and research rows:
    - `R`: root, title `R_TITLE='Deep reinforcement learning for RAN slice resource allocation in O-RAN networks'`, status idle.
    - `C`: `kind:'research'`, `project_id:null`, `parent_task_id:'R'`, `role:'citation_checker'`, `provider:'codex'`, title `Citation checker: Call claims_pending, judge every claim only against its source abstract`, status completed.
    - `X`: root, title `Restarted reply`.
    - Histories built with `evFor`, so each task starts at seq 1.
      - R: user `R question` (`user_u1`), a reported budget at seq 2 (`Reported 100 tokens`), then `subagent_started` and `subagent_finished` for C (state completed).
      - C: user `CHILD BRIEF` (`user_u1`), a reported budget at seq 2 (`Reported 999 tokens`).
      - X: `user_u1` and `msg_1` (`First answer`) in turn `u1`; `user_u4` and `msg_1` (`Fourth answer`) in turn `u4`.
    - Collision: open X. The `#agent-stream [data-item]` list is `['user_u1','msg_1','user_u4','msg_1@u4']`; `[data-item=msg_1]` reads `First answer`; `[data-item="msg_1@u4"]` reads `Fourth answer`.
    - Push a user message `user_u7` and a `message_delta` for `msg_1` in turn `u7`. `msg_1@u7` is last and shows `Writing…`, and `msg_1` still reads `First answer`.
    - Cache: open R, click `#sub-open-C`, wait for `CHILD BRIEF`, then go back to R through the Research list (`[data-open-task=R]`).
    - Assert `[data-item=user_u1]` contains `R question` and not `CHILD BRIEF`, and `[data-item="seq:2"]` contains `100` and not `999`.
- [ ] **Step 2: Run them and see them fail.** Run `python3 -m unittest tests.runtime.test_claude -q`; it fails on the ids. Run `node tests/run-ui.cjs research-task-ui`; it fails with a turn-4 reply drawn over turn 1, or R showing `CHILD BRIEF`.
- [ ] **Step 3: Implement**
  - Add `_item_id` and use it at `claude.py:779-785` (`'msg'`, `'rs'`).
  - Add `turnKey` and use it in the `message_delta`, `message` and `reasoning` cases. Keys that do not collide stay as they are.
  - Change `render()`'s first line to `let v=views.get(container);if(!v||v.task!==taskId){v={task:taskId,cache:new Map()};views.set(container,v);}const cache=v.cache;`.
  - Add `evFor`.
- [ ] **Step 4: Run them and see them pass.** Run `python3 -m unittest discover -s tests -q`, then `node tests/run-ui.cjs research-task-ui subagents-ui team-card-ui research-e2e-ui`.
- [ ] **Step 5: Commit:** "Give Claude replies and reasoning ids that stay unique after a restart, keep a reply whose id collides in its own turn, and keep each task's cached cards to that task".

---

### Task 2: Back returns to the parent, where you left it

**Files:**
- Modify: `app/ui/agent.js`:
  - `:16-24`: add `backTo`, `rootOf` and `anchorOf` next to `parentOf`.
  - `:70`: the "Part of" link.
  - `:90`: the Back label.
  - `:104-108`: restore, and skip stick-to-bottom.
  - `:384`: the Back handler.
  - `:386-389`: the `rootOf` export, and recording in `open()`.
- Modify: `app/ui/app.js:72` (sidebar `currentId`).
- Modify: `app/ui/desk.css` (`#agent-back` at `:15` and `.agent-topbar #agent-back` at `:314`).
- Modify: `tests/research-fixture.mjs` (`fit` widths).
- Test: `tests/research-task-ui.mjs` (extend Task 1's block), `tests/subagents-ui.mjs`.

**Interfaces:**
- Consumes: Task 1's per-task cache (without it the parent shows the child's nodes on return) and `evFor`.
- Produces in `agent.js`:
  - `backTo(id) -> string|null`: the parent id when `row(parent)` exists and its status is not `'unavailable'`.
  - `rootOf(id) -> string`: walks `parentOf`, at most 8 steps.
  - `anchorOf(stream, childId) -> Element|null`: `stream.querySelector('[data-child="'+CSS.escape(childId)+'"]')?.closest('.card')`. This is the subagent card, or the work line whose Open button carries `data-child` (Task 4).
  - `returns: Map<parentId, {child, offset: number|null, scroll: number, focusId: string}>`.
  - `window.interspaceAgent.rootOf`.
- Produces: `fit(page, label, show, shots, widths=[320,390,760,1024,1280])` in `research-fixture.mjs`.

- [ ] **Step 1: Write the failing tests**
  - `tests/research-task-ui.mjs`, Task 1's block. After R's seq-2 budget row, give R's history 30 final assistant messages and one streaming message (`message_delta`, item `grow`) before C's card, and 10 messages after it. Task 1's assertions keep holding.
    - At 1280 (split), open R and click `[data-agent-tab=details]`. Scroll `.agent-main` so the card `[data-child=C]` sits about 300px below the column top, and record its offset from the column top.
    - Open C with `page.evaluate(()=>document.getElementById('sub-open-C').click())`. This click does not focus the button.
    - Assert `#agent-back` text is `'← '+R_TITLE` and its `title` is `R_TITLE`.
    - Assert `[data-sidebar-task=R]` has `aria-current="page"` and `[data-sidebar-task=C]` count is 0.
    - Press Escape: the heading is still C's title.
    - While on C, push a `message_delta` adding 10 lines to `grow` in R.
    - Click Back. Assert:
      - `#agent-view.split` is there, and `#heading` is `R_TITLE`;
      - `[data-agent-tab=details]` is `aria-pressed="true"`;
      - the card's offset is within 4px of the recorded one;
      - `document.activeElement.id === 'sub-open-C'`.
    - Repeat the round trip through the button named `Part of “`+R_TITLE+`”`, and through `[data-sidebar-task=R]`. The same position and focus checks hold.
    - At 900px, open C. Only the Conversation and Details tabs show, Back still reads `'← '+R_TITLE`, and clicking it shows R.
    - Run `fit(page,'back-title',()=>open C,false,[320,390,600])`. At 320, `#agent-back` has `scrollWidth>clientWidth`, and its `textContent` is still the whole `'← '+R_TITLE`.
    - Parent gone, last: with C shown, run `rFixture.research.splice(<R's index>,1); rFixture.setState()`. Back reads `← Research`, no button starts with `Part of`, and clicking Back shows the heading `Research`.
  - `tests/subagents-ui.mjs`, after the `'Focus not returned to Review changes'` assert (about `:189`), in T (Detailed at that point):
    - Run `evaluate(()=>document.getElementById('sub-open-C1').click())`. Back reads `← Add input validation`. Click it: the heading includes `Add input validation`, and `activeElement.id==='sub-open-C1'`.
    - By keyboard: focus `#sub-open-C1` and press Enter, then focus `#agent-back` and press Enter. Focus is back on `sub-open-C1`.
    - From the Running view's `.child-row[data-child="C1"]` Open: Back reads `← Add input validation`, and clicking it lands on T.
- [ ] **Step 2: Run them and see them fail:** `node tests/run-ui.cjs research-task-ui subagents-ui`. Back reads `← Research` / `← Tasks`.
- [ ] **Step 3: Implement**
  - Label (`:90`): `const up=backTo(id)`. Set `textContent` to `'← '+title(up)` or today's text, and set or remove the `title` attribute.
  - Handler (`:384`): `const up=current&&backTo(current); if(up)host.openAgent(up); else host.navigate(isResearch(current)?'research':'tasks')`.
  - "Part of" (`:70`): build it only when `backTo(id)` is set.
  - `open(id)`, before `current=id`: when `view==='agent'&&current&&parentOf(id)===current`, record `returns.set(current,…)`.
    - `chat` is `.agent-main` when `placed`, else the window.
    - `offset` is the anchor's top minus the chat's top (null without an anchor).
    - `scroll` is `chat.scrollTop` or `scrollY`.
    - `focusId` is `document.activeElement.id` only when the stream contains it.
  - `renderAgent`, right after `S.render(stream,id)`: when `returns.has(id)`, delete the entry and skip the stick step at `:108`.
    - Scroll so the anchor sits at `offset`. With no anchor, use `scroll`.
    - Focus, with `{preventScroll:true}`, the first that exists: `focusId`, `#work-open-<safe(child)>`, `#sub-open-<safe(child)>`, the anchor's `.sub-details`, or the anchor itself with `tabIndex=-1`.
  - `app.js:72`: use `A.rootOf(A.current())` when `view==='agent'`.
  - CSS:
    - `#agent-back{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}`;
    - `.agent-topbar #agent-back{flex:0 1 auto;min-width:0}`. A cap such as `max-width:40ch` there is the builder's call.
  - Add the `widths` parameter to `fit`.
- [ ] **Step 4: Run them and see them pass:** `node tests/run-ui.cjs research-task-ui subagents-ui team-card-ui research-cards-ui sidebar-ui research-e2e-ui`.
- [ ] **Step 5: Commit:** "Name the parent task on a subagent's Back button and return to it where you left it, with focus on the Open button that led there".

---

### Task 3: Research-card helpers for the work line and the citation pointer

**Files:**
- Modify: `app/ui/research-cards.js`:
  - `:122-139`: `citationCard` and `citationCounts`.
  - `:224-248`: `toolSummary` and `summaryText`.
  - `:250`: exports.
- Test: `tests/research-cards-ui.mjs`.

**Interfaces** (all on `window.interspaceResearchCards`):
- `summaryText({call, result, output}) -> string`: exactly the text `toolSummary` renders today. `toolSummary` calls it.
- `citationCounts(report) -> {total, counts:{verified, mismatch, not_found, retracted, unchecked}, other, problems}`, where `problems = total - counts.verified`. `citationCard` uses it in place of `:124-125`.
- `citationPointerText(report) -> string`: the format in Global Constraints.
- `workerName(sub) -> string`: `P.title(sub.provider)+' '+P.roleTitle(sub.role||'subagent').toLowerCase()`, with `P=window.interspaceProviders`, for example `Codex citation checker`.
- `workParts(items) -> string[]`, in the Global Constraints order. It trusts the caller: every `sub` passed is finished, every `team` is answered, every `citation` is all verified.
  - Searches are `research_search` calls with an ok result.
  - Sources are the union of their `data.searched`.
  - Papers are distinct across the `papers` of `research_search` and `research_citations` results. The key is the lowercased `doi`, else `'arxiv:'+arxiv_id`, else the lowercased trimmed title. The part is left out when any of those outputs does not parse, or is truncated with no `fullOutput`.
  - Output text is `it.fullOutput ?? it.result?.output?.text ?? ''`.
  - Look-ups are `research_paper` ok results.
  - Verdicts sum `record_claim_support` `data.recorded`; values sum `record_table_cells` `data.recorded`.
  - Steps is `items.length`.
- `citationCard(card, report, {state, bump, brief=false})`. When `brief && !state.refs`:
  - the footnote keeps only its first sentence;
  - the list shows `Math.min(problems, 10)` rows;
  - `Checked at` is not shown;
  - `Show all N references` stays.

- [ ] **Step 1: Write the failing tests** in `research-cards-ui.mjs`, through `page.evaluate` on `window.interspaceResearchCards`:
  - `summaryText` of a running `research_search` with query `x` is `Searching “x”`. For an ok result with `searched:['semantic_scholar']` and 2 papers, it is `Searched “x” in Semantic Scholar: 2 papers`.
  - `citationCounts(report)` on the suite's 12-reference report deep-equals `{total:12,counts:{verified:7,mismatch:1,not_found:1,retracted:1,unchecked:1},other:1,problems:5}`.
  - `citationPointerText(report)` is `Citations: 7 of 12 verified · 1 mismatch · 1 not found · 1 unchecked · 1 unknown · 1 retracted: do not cite`.
  - `workParts` on these items, where `ok(tool,input,data)` builds an ok research call:
    - `ok('research_search',{query:'a'},{searched:['semantic_scholar','arxiv'],papers:[{doi:'10.1/A',title:'A'},{doi:'10.1/b',title:'B'}]})`;
    - `ok('research_search',{query:'b'},{searched:['arxiv','openalex'],papers:[{doi:'10.1/a',title:'A again'},{arxiv_id:'2401.1',title:'C'}]})`;
    - `ok('research_paper',{id:'doi:10.1/a'},{paper:{title:'A'}})`;
    - `ok('save_report',{},{saved:'report.md',characters:10})`;
    - `{sub:{task_id:'c1',provider:'codex',role:'citation_checker'}}`;
    - `{team:{answered:{decision:'approve'}}}`;
    - `{citation:{references:[{status:'verified'},{status:'verified'},{status:'verified'}]}}`;
    - `{reasoning:'x'}` and `{row:'budget',text:'t'}`.

    The result deep-equals `['Team approved','Codex citation checker finished','Searched 3 sources 2 times','3 papers','looked up 1','saved report.md','3 references checked: all verified','9 steps']`.
  - The same items with the second search's `output.truncated:true` give no `papers` part.
  - Only the first search gives `['Searched 2 sources once','2 papers','1 step']`.
  - `ok('record_claim_support',{},{recorded:4})` with `ok('record_table_cells',{},{recorded:12})` gives `['recorded 4 claim verdicts','recorded 12 evidence values','2 steps']`.
  - The brief card on the 12-reference report shows:
    - 5 `.reference` rows, with `Retracted: do not cite` first;
    - its footnote is exactly `5 references are not verified.`;
    - no text `Checked at`;
    - a button `Show all 12 references`, which shows 12 rows.
- [ ] **Step 2: Run it and see it fail:** `node tests/run-ui.cjs research-cards-ui`.
- [ ] **Step 3: Implement** the signatures above. `toolSummary` keeps its DOM exactly as today.
- [ ] **Step 4: Run them and see them pass:** `node tests/run-ui.cjs research-cards-ui display-ui research-e2e-ui`.
- [ ] **Step 5: Commit:** "Add research-card helpers for one-line summaries, work-line counts, citation counts and a brief citation card".

---

### Task 4: Simple reads as a chat for research tasks

**Files:**
- Modify: `app/ui/stream.js`:
  - `apply` `:51`: scope rows also store `change:d.change`.
  - `build` `:209`: add an `entry` parameter.
  - `subContext` `:249` and `childChanged` `:257`: pass `{nested:true}`.
  - `render` `:260-271`.
  - exports `:284-293`.
- Modify: `app/ui/desk.css` (after `:547`).
- Create: `tests/simple-view-ui.mjs`. Modify: `tests/run-ui.cjs:7` (add `'simple-view-ui'` to `SUITES`).
- Modify: `tests/display-ui.mjs`; `tests/research-cards-ui.mjs` (install `display:{…, detail:'detailed'}`, since it checks each card in full).

**Interfaces:**
- Consumes: Task 3's `summaryText`, `workParts`, `workerName`, `citationCounts`; Task 2's `returns` and focus fallbacks; Task 1's per-task cache and `evFor`.
- Produces in `stream.js`:
  - `LIVE=new Set(['queued','starting','running','waiting_lock','cancelling'])`.
  - `simpleOn(m, options) -> boolean` (the gate in Global Constraints).
  - `stays(m, it, {interim, newestScope}) -> boolean` (the rules in Global Constraints; anything not listed stays).
  - `digest(m, list) -> {entries, folded: number}`. Item entries are `{key, it, inWork?, preview?, pointer?}`. The work entry is `{key:'work:'+lead, work:true, lead, items, open, live, text, children}`. The end entry is `{key:'work-end:'+lead, end:true, lead}`.
    - Per turn, emit the lead, then the work line (only if anything folded), then, when open, the folded items with `inWork`, then the end entry. Then emit the turn's other kept items in their original order (the reply included).
  - `workLine(m, entry) -> HTMLElement` and `workEnd(m, entry) -> HTMLElement`.
  - `entryVersion(m, entry) -> string`: the digest's part of a cached node's version. For a work entry it is the text, the open state and the children. Tasks 5 and 6 extend it.
  - `openWork=new Set()`.
  - `window.interspaceStream.folded(id) -> number`: `m.folded`, set only by a render that is neither compact nor nested.
- `render(container, taskId, {compact, nested})`:
  - Build entries from `digest` when `simpleOn`, else one entry per visible item (Detailed and code tasks are unchanged).
  - The version is `stamp(m,it)+'|'+shownKey+'|'+entryVersion(m,entry)`.
  - Toggle `.in-work` on every reuse.
  - The prune keeps this render's synthetic keys: `if(!m.items.has(key)&&!live.has(key))cache.delete(key)`.
- Work-line controls:
  - **Details** has id `work-<task8>-<lead>`, `aria-expanded`, and `aria-label` `Details of this work, K steps` or `Hide details of this work, K steps`.
  - Open buttons have class `work-open`, id `work-open-<safe(child)>`, `data-child=<child>`, text `Open `+`workerName(sub)`, and call `open(child)`.
  - The closing button has id `work-end-<task8>-<lead>` and text `Hide details ▴`. It focuses the line's Details button after `changed()`.

- [ ] **Step 1: Write the failing tests** in the new `tests/simple-view-ui.mjs`. Use `install` with the default display (Simple) and `evFor` histories.
  - **R** (root, title `DRL for RAN slice resource allocation`, idle) has three turns:
    - Turn u1:
      - a scope row (`approved`) at seq 1;
      - `user_u1`, 700 characters (two paragraphs of 200 and 500);
      - `rs_1` reasoning;
      - `s1` `research_search` `DRL RAN slicing`, ok, `searched:['semantic_scholar','openalex']`, papers doi `10.1/a` and `10.1/b`;
      - `s2` `research_search` `O-RAN xApp slicing`, ok, `searched:['arxiv','openalex']`, papers doi `10.1/B` and arXiv `2401.1`;
      - `p1` `research_paper`, ok;
      - `msg_a` `I'll start by searching three sources.`;
      - `sv` `save_report`, ok;
      - a reported budget row;
      - `msg_b`, more than 600 characters: a 200-character paragraph, a list of three 80-character items, a 100-character paragraph with `[paper](https://example.org/p)`, and a 200-character paragraph.
    - Turn u2:
      - `user_u2` `Check the claims in the saved report.`;
      - team `tm1` proposed and answered approve;
      - sub `C` (codex, citation_checker), started and finished completed;
      - `cite_1` with 3 verified references;
      - `msg_c`, one 1500-character paragraph.
    - Turn u3:
      - `user_u3` `Fill the evidence table.`;
      - team `tm2` answered;
      - subs `E` (claude, extractor), `F` (codex, extractor) and `G` (codex, reviewer), all finished completed;
      - `t1` `record_table_cells`, ok, `recorded:12`;
      - `cite_2` with 2 verified references and 1 `mismatch` (fields `['year']`);
      - `msg_d`, 900 characters.
  - **C**: a row (child of R, as in Task 1) and a history: `user_u1` `Check every reference.`, `v1` `verify_citations` ok, `cite_c` (2 verified and 1 `not_found`), and `cm` `Checked.`.
  - **L** (root, running): `user_u1` `Find sources.`, status running, and `l1` `research_search` `O-RAN xApp slicing` with no result.
  - **X**: as in Task 1, but its turn-1 `msg_1` is exactly 600 characters and starts with `First answer`.
  - Assertions:
    - *Turns (T0):* R's `#agent-stream>[data-item]` list is `['user_u1','work:user_u1','msg_b','user_u2','work:user_u2','msg_c','user_u3','work:user_u3','cite_2','msg_d']`. The line texts start with:
      - `Searched 3 sources 2 times · 3 papers · looked up 1 · saved report.md · 8 steps`;
      - `Team approved · Codex citation checker finished · 3 references checked: all verified · 3 steps`;
      - `Team approved · Claude extractor, Codex extractor, Codex reviewer finished · recorded 12 evidence values · 5 steps`.

      `window.interspaceStream.folded('R')===16`. Turn 3's line has exactly 2 `.work-open` buttons, `Open Claude extractor` and `Open Codex extractor`.
    - *Keyboard (T1):*
      - Focus `#work-R-user_u1` and press Enter. It is `aria-expanded="true"` and still `document.activeElement`.
      - The items after it are `seq:1, rs_1, s1, s2, p1, msg_a, sv, seq:<budget>`, each `.in-work`, then `work-end:user_u1`.
      - `[data-item=s1]` has its own `Show details` button.
      - Press **Hide details ▴**: the line is closed, and focus is on `#work-R-user_u1`.
    - *Never folded (T2/T3):*
      - L's line reads `Working · Searching “O-RAN xApp slicing” · 1 step`.
      - Push into L one after another:
        - a running sub `L1`;
        - an open team `tm3`;
        - an `ask` (`agent_question`);
        - an `error`;
        - a failed `research_search` (`status:'error'`);
        - a sub `L2` with `subagent_status` `paused_ask`;
        - status `waiting_lock`, then `queued`;
        - a scope `edited` event.
      - Each renders as a direct child of `#agent-stream` without `.in-work` while the line is closed. **Approve team** on `tm3` sends `team_answer` `{task_id:'L',team_id:'tm3',decision:'approve'}`.
      - Push scope `approved`: both scope rows fold.
    - *Review Focus 1:*
      - Open L's line and focus its button.
      - Push an ok result for `l1` (`searched:['arxiv']`, 1 paper), then a running `research_search` `l2` with query `second query`.
      - The line stays `aria-expanded="true"`, `l2` is the last `.in-work` before `work-end:user_u1`, and focus is still on `work-L-user_u1`.
      - The line text starts `Working · Searching “second query” · Searched 1 source once · 1 paper`.
    - *Per task:* opening R's turn-1 line leaves `#work-L-user_u1` at `aria-expanded="false"`.
    - *Open and Review Focus 3:*
      - Run `evaluate(()=>document.getElementById('work-open-C').click())`. The heading is C's title.
      - Back returns to R, with `activeElement.id==='work-open-C'` and `[data-item="work:user_u2"]` within 4px of its offset before.
    - *Untouched copies:*
      - Running view: `.task-column[data-task="R"] .work-line` count is 0.
      - In R's opened turn-2 line, open C's card (`Citation checker details`), then **Show Citation checker activity**. `#child-C` has a `.card.research` and no `.work-line`.
    - *Collision in Simple:* X's list is `['user_u1','msg_1','user_u4','msg_1@u4']`, with no `.work-line`.
    - *Detailed parity (T9) and Review Focus 5 (line):*
      - With R's turn-1 line open, `setDetail('detailed')`. There is no `.work-line` and no `.in-work`.
      - The `[data-item]` list equals `DETAILED_R`: the 23 item keys of R's history in event order, written out literally, with the scope and budget rows as `seq:<n>`.
      - Back to Simple: `#work-R-user_u1` is still `aria-expanded="true"`.
    - *Layout:* push `l9` with a 150-character query without spaces. `fit(page,'simple-view-live',()=>open L,false,[320,390,600])` passes.
  - `tests/display-ui.mjs`: before `// Default display` (about `:69`), click the button in `#agent-stream .work-line` whose accessible name starts with `Details`. The existing `s1 s2 s5 s4 think1` checks then read the opened items unchanged.
- [ ] **Step 2: Run them and see them fail:** `node tests/run-ui.cjs simple-view-ui` (no `.work-line`).
- [ ] **Step 3: Implement** the interfaces above.
  - `stays` reads the subagent state as `childStatus(child, it.sub.state)`.
  - The newest scope row is the last item with `row==='scope'`.
  - An assistant message is interim when it is final and a later assistant message exists in its turn.
  - CSS, with exact spacing the builder's call:
    - `.card.work-line` uses the `.card.is-line` look (`:531`), `display:block`, 13.5px `--muted` text, `overflow-wrap:anywhere`;
    - `.work-open`, the line's Details button and `.work-hide` look like `.sub-details` (`:538`);
    - `.stream>.in-work{margin-left:14px}`, 8px at `max-width:600px`.
- [ ] **Step 4: Run them and see them pass:** `node tests/run-ui.cjs simple-view-ui display-ui research-cards-ui research-task-ui reader-ui evidence-ui claims-ui corpus-ui team-card-ui subagents-ui agent-ui hardening-ui`.
- [ ] **Step 5: Commit:** "Show a research task's Simple conversation as a chat: your message, one work line for the turn's agent work, then the reply".

---

### Task 5: Earlier long messages show their first lines

**Files:**
- Modify: `app/ui/stream.js`: `digest` sets `entry.preview`, `entryVersion`, and the `build` message branch `:211`.
- Modify: `app/ui/desk.css`.
- Test: `tests/simple-view-ui.mjs`.

**Interfaces:**
- Consumes: Task 4's `digest`, `entryVersion`, and `build(m,it,compact,entry)`.
- Produces:
  - `entry.preview ∈ {'message','reply',null}`. It is set on the lead and on the reply (the last assistant message) of every turn but the newest, when the message is final, not pending, not failed, and more than 600 characters.
  - `cut(box: HTMLElement, limit: number) -> boolean`. It walks `box.children`, and the `li`s of a list that crosses the limit, adding up `textContent.length`.
  - `openMsgs=new Set()`.
- Markup: the `.md` box gets id `msg-<task8>-<key>`. A `button.more` with id `more-<task8>-<key>` has text `Show whole message ▾` or `Show whole reply ▾` (`Show less ▴` when open), plus `aria-expanded` and `aria-controls`. The toggle bumps `it.version` and calls `changed(m.id)`, so the focus restore by id (`stream.js:271`) keeps focus.

- [ ] **Step 1: Write the failing tests** in `simple-view-ui.mjs`, using Task 4's fixture:
  - `[data-item=user_u1]`: the first paragraph is visible, the second has `.is-cut`, and no block is `hidden`. `#more-R-user_u1` reads `Show whole message ▾`, has `aria-expanded="false"`, and its `aria-controls` equals the id of its `.md`.
  - `[data-item=msg_b]`:
    - its first paragraph is visible, the list is visible, `li` 1 is visible, `li` 2 has `.is-cut`, and `li` 3, paragraph 3 and paragraph 4 are `hidden`;
    - `evaluateAll` over its `a` elements: every one is inside `[hidden]` or has `tabIndex===-1`.
  - Focus `#more-R-msg_b` and press Enter:
    - no `[hidden]` and no `.is-cut` remain inside the `.md`;
    - the link's `tabIndex` is 0;
    - the button reads `Show less ▴` with `aria-expanded="true"`, and it is still `document.activeElement`;
    - after Enter again, the reply is cut again.
  - Review Focus 4: `[data-item=msg_c]` (one paragraph) has a visible `p.is-cut`, no hidden block, and a `Show whole reply ▾` button.
  - `msg_d` (newest) and X's 600-character `msg_1` have no `.more`, no `.is-cut` and no `[hidden]`.
  - Push a 900-character `message_delta` into L: no `.more`.
  - `window.interspaceStream.optimistic('X','y'.repeat(700),'c1')`, then `failed('X','c1','Offline')`: the message is whole in both states.
  - Kept for the session: open `msg_b`, go to the Research list and back to R, and it is still whole.
  - Review Focus 5 (reply): with `msg_b` whole and the turn-1 line open, switch to Detailed and back. Both are still open.
- [ ] **Step 2: Run it and see it fail:** `node tests/run-ui.cjs simple-view-ui`.
- [ ] **Step 3: Implement**
  - The limit is 240 for `'message'` and 300 for `'reply'`.
  - The block that crosses the limit keeps showing, with `.is-cut` and its links at `tabindex="-1"`.
  - CSS: `.message .is-cut{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:3;overflow:hidden}`, and `.message .more` copies `.sub-details` (`desk.css:538`).
- [ ] **Step 4: Run them and see them pass:** `node tests/run-ui.cjs simple-view-ui display-ui reader-ui research-task-ui`.
- [ ] **Step 5: Commit:** "Show earlier long messages and replies as their first lines with Show whole message or Show whole reply".

---

### Task 6: A citation report with problems becomes one warn line

**Files:**
- Modify: `app/ui/stream.js`:
  - `digest`: set `entry.pointer` on a citation item that stays;
  - `entryVersion`;
  - the `build` citation branch `:220`;
  - `init` `:285`.
- Modify: `app/ui/agent.js:358` (`S.init` options).
- Modify: `app/ui/desk.css`.
- Test: `tests/simple-view-ui.mjs`.

**Interfaces:**
- Consumes: Task 3's `citationPointerText`, `citationCounts`, and `citationCard(…, {brief:true})`; Task 4's `digest` entries.
- Produces:
  - `citationPointer(m, it, card)`. The card gets classes `citation-pointer is-line`, a `p` with the pointer text, a button `cite-<task8>-<key>` (`Show citation report ▸` or `Hide citation report ▾`, `aria-expanded`, `aria-controls=cite-box-…`), and, when `isRoot(m.id)` and `showTab` exist, a button `Open Corpus ›` with `aria-label="Open Corpus tab"`.
  - The open state is `it.briefOpen`; the toggle bumps `it.version`.
  - Opened, `div#cite-box-…` holds `citationCard(box, it.citation, {state:it, bump, brief:true})`.
  - New `S.init` options: `showTab(tab: string): void` and `isRoot(id: string): boolean`. `agent.js` passes:
    - `showTab:tab=>{const b=$('agent-tabs').querySelector('[data-agent-tab='+tab+']');b?.click();b?.focus();}`;
    - `isRoot:id=>isResearch(id)&&!parentOf(id)`.

- [ ] **Step 1: Write the failing tests** in `simple-view-ui.mjs`:
  - `[data-item=cite_2]` has `.citation-pointer`. Its text includes `Citations: 2 of 3 verified · 1 mismatch`, and it holds 0 `.reference` rows.
  - It has a button named `Show citation report` (`aria-expanded="false"`, with `aria-controls`) and a button named `Open Corpus tab`.
  - Click Show:
    - one `.reference`, containing `Not verified: differs from the published record in year`;
    - the footnote `1 reference is not verified.`;
    - no `Checked at`;
    - `Show all 3 references`, which gives 3 rows;
    - the toggle reads `Hide citation report ▾` with `aria-expanded="true"`, and keeps focus by id.
  - In L, push a report of 1 verified and 1 retracted reference. The pointer reads `Citations: 1 of 2 verified · 1 retracted: do not cite`.
  - Click R's `Open Corpus tab`. `[data-agent-tab=corpus]` is `aria-pressed="true"` and is `document.activeElement`, and a `task_corpus` request for R was sent.
  - Open C's own view through `#work-open-C`. Its pointer reads `Citations: 2 of 3 verified · 1 not found`, and there is no `Open Corpus` button.
  - In Detailed, `[data-item=cite_2]` is `.citation-report` with 3 `.reference` rows, and there is no `.citation-pointer`.
- [ ] **Step 2: Run it and see it fail:** `node tests/run-ui.cjs simple-view-ui`.
- [ ] **Step 3: Implement.** CSS: `.citation-pointer` uses `color:var(--warn)` and `border-left-color:var(--warn)`, and its buttons wrap inline.
- [ ] **Step 4: Run them and see them pass:** `node tests/run-ui.cjs simple-view-ui research-cards-ui corpus-ui display-ui research-task-ui`.
- [ ] **Step 5: Commit:** "Show a citation report with problems as one warn line that opens a brief card of the problem rows, with Open Corpus on root research tasks".

---

### Task 7: Folded-steps note, Settings text, docs, and the full gate

**Files:**
- Modify: `app/ui/index.html`: after `#agent-detail-toggle`, add `<span id="agent-detail-note" class="view-note footnote" hidden></span>`, and add `aria-describedby="agent-detail-note"` to the toggle group.
- Modify: `app/ui/agent.js`:
  - `detailToggle` `:244-247`;
  - `place` `:193-194`: move the note after the toggle in both branches;
  - `renderAgent`: call the note update after `S.render` at `:106`.
- Modify: `app/ui/desk.css`: `.view-note{font-size:12.5px;color:var(--muted);white-space:nowrap}`, and add `#agent-view.focus #agent-detail-note` to the hide rule at `:568`.
- Modify: `app/ui/display.js:44` (the help text).
- Modify: `app/README.md`:
  - `:77`: the Simple and Detailed paragraph describes the research chat view, the work line, earlier-message previews, the citation line and the folded-steps note.
  - `:39`: one sentence saying Back in a subagent names and returns to its task.
- Modify: `docs/superpowers/specs/2026-11-27-readable-workspace-design.md`:
  - In Goal 4, add a bullet for research tasks: the turn digest, the earlier-message previews and the citation pointer, pointing to the new spec.
  - Under "Settled in review", add:
    - what `stays()` keeps;
    - interim messages fold only after a later reply exists;
    - the 600-character threshold;
    - the display switches still decide what exists and is counted, and Simple decides only how it is folded;
    - research tasks only.
- Test: `tests/simple-view-ui.mjs`, `tests/display-ui.mjs`.

**Interfaces:**
- Consumes: `window.interspaceStream.folded(id)` (Task 4).
- Produces: `detailNote(id, talk)` in `agent.js`. The text is `n+' step'+(n===1?'':'s')+' folded'`. The note is hidden when `!talk`, when detail is `detailed`, or when `n===0`; in Focus, CSS hides it.

- [ ] **Step 1: Write the failing tests**
  - `simple-view-ui.mjs`:
    - On R at 1280 (Simple), `#agent-detail-note` reads `16 steps folded`.
    - `#agent-detail-toggle` has `aria-describedby="agent-detail-note"`, and `nextElementSibling` is the note, inside `#agent-topbar`.
    - At 800px, the note is the toggle's `nextElementSibling` inside `.agent-main`.
    - The note is hidden in Detailed, on X (0 folded), and with Focus on.
    - C's own view (one folded step, `v1`) reads `1 step folded`.
    - Set Thinking to Hidden through `display_update`. R reads `15 steps folded`, and turn 1's line ends `· 7 steps`.
    - With R's turn-1 line, `msg_b` and the `cite_2` brief card open, `fit(page,'simple-view',…,false,[320,390,600])` passes in light and dark.
  - `display-ui.mjs`: replace the help-text assertion at about `:91` with the exact text from Global Constraints.
- [ ] **Step 2: Run them and see them fail:** `node tests/run-ui.cjs simple-view-ui display-ui`.
- [ ] **Step 3: Implement** the files above. The docs say what the code now does, in the spec's words.
- [ ] **Step 4: Run the full gate:** `python3 -m unittest discover -s tests -q`, then `node tests/run-ui.cjs` (every suite, `simple-view-ui` included). Every suite's last line is its JSON result.
- [ ] **Step 5: Commit:** "Say how many steps Simple folded beside the switch, explain Simple in Settings, and describe the chat view and Back to the parent in the README and the readable-workspace spec".
