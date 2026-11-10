# Agent workspace view validation

Checked 2026-11-10 in Chromium. This extends the earlier static design study; there is no agent backend.

## Behavior exercised

- Tasks is the initial view. The conventional board and optional Observatory each display the same four tasks.
- Selecting the Builder task, switching views, and inspecting its details preserves selection.
- Approving its sample experiment in the decision inbox changes it to Queued in both views without claiming execution.
- Preview handoff completes the Researcher task and starts the sample Reviewer task. Both projections agree, and the reviewer becomes the selected task.
- Pausing displays Paused for the active task and disables handoff progression; resuming restores the control.
- Reset handoff restores the sample research/review states without undoing an approval decision.
- Keyboard focus remains on the view switch after switching; Tab reaches the next control with a visible outline.
- Both views fit 1024, 390, and 320 CSS-pixel widths without horizontal overflow. Light and dark screenshots were visually inspected.
- Browser execution produced no page errors in these flows.

## Scope

Task records, handoffs, filenames, status and approvals are illustrative. View state is session-only. There is no drag-and-drop, persistent preference, real output file, provider activity, or runtime scheduling.

The source uses one shared task projection for the task board, workstation view, inspector, and activity rail. Rendering does not execute agent work. The handoff transition is deliberately user-triggered and is suppressed under reduced motion.

Evidence: `design/evidence/agent-tasks-dark.png`, `agent-observatory-dark.png`, `agent-observatory-light.png`, and `agent-observatory-mobile.png`.
