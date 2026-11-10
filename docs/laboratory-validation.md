# Static laboratory validation

Historical four-agent scene checked 2026-11-10 in Chromium against the generated standalone preview. All tasks, activity, artifacts, approval decisions and provider connections are sample state.

## Observed behavior

- Tasks remains the initial view; Observatory is optional. Four fixed departments contain distinct original Scout, Researcher, Builder and Reviewer figures.
- Clicking each figure at its Canvas coordinates selected the correct assigned task and matching roster button. Native roster buttons also work with Enter, exposing pressed selection.
- Selection survives switching views and all three palette changes. Approval changes the Builder task to Queued without execution. Returning to Agents preserves the view.
- Preview review stage completes the Researcher sample task and activates Reviewer. Pause changes the active task label and disables stage progression. Reset preserves the independent Builder approval.
- The inspector includes current activity, expected output, next step/blocker, role, tools, provider connection status, scope, deliverable and dependencies. No generated artifact files or hidden model reasoning are claimed.
- The walking API, frame scheduling, animation state and motion listeners have been removed. Stage changes work under reduced-motion settings without moving figures. This scene consumes no model calls and has no autonomous simulation loop.
- View disposal disconnects the ResizeObserver and pointer/theme handlers. The two source files are bundled into the generated fragment and standalone page with a drift check.
- Both views were checked at 1280, 1024, 390 and 320 CSS-pixel widths without horizontal document overflow. The final desktop breakpoint keeps the inspector beside the map at 1024 and above; smaller screens stack it. Mobile roster buttons retain readable task labels and larger character portraits.
- Browser workflows returned no page errors. Light/dark renders and three palette choices were inspected. This is a scoped prototype accessibility check, not a complete accessibility audit.

## Reproduction

1. Run `node scripts/build-preview.mjs --check` and open `design/index.html`.
2. Switch to Observatory; select all four figures, then select a roster button with the keyboard.
3. Select Builder, switch to Tasks, inspect the proposal and approve it. Return to Agents: Builder is Queued, with no execution.
4. Preview review stage, pause/resume, then reset. Verify both projections and the inspector agree.
5. Select each palette and resize through 1280, 1024, 390 and 320 pixels. Inspect light and dark appearances and expand both inspector detail sections.

Evidence is recorded in `design/evidence/laboratory-report.json` with screenshots. Earlier reports and images describe historical versions and are retained as such.

## Limits

This historical check used one illustrative agent per department. The later expandable Role library is covered in role-library-validation.md. Agent creation, multiple concurrent runs, real event logs, provider usage/cost accounting, persistent preferences, connectors and actual output opening remain application work. State resets on reload. The canvas and roster provide alternative selection surfaces; the roster is the keyboard-accessible equivalent.
