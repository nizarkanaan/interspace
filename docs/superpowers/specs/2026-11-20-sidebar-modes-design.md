# Sidebar: Research and Code modes

Date: 2026-11-20
Status: approved in conversation (direction 2 on the canvas "Interspace task view")
Size: small change (one backend row field, UI)

## Intent

The old sidebar mixed three ideas:

- **Tasks:** the code tasks of whichever project the dropdown picked;
- **Running:** a grid of everything active;
- **Research:** a separate list;

plus a project dropdown and a footer of notes. The user found it unclear. The sidebar should say where you are, what needs you, and how to start something.

## Design

- **Mode switch.** A two-way switch at the top: **Research | Code**.
  - The buttons keep `data-view="research"` and `data-view="tasks"`, so they open the same pages as before.
  - Research shows the research-task count (`#research-nav-count`).
  - The mode follows the page: a research page or research task means Research, and a project page or code task means Code. Settings and Running keep the last mode.
- **New button.** One button for the mode: **New research question** or **New code task**. It opens the New task form with that kind chosen.
- **Code mode only:** a **Project** picker, the same `#project-picker`, with **Add project folder** under it.
- **The mode's root tasks, grouped by what they need from you.** Each task shows its title and one line of state, in words. Subagents and saved data that can't be read are left out.
  - **Needs you:**
    - `paused_ask`: Answer a question.
    - `paused_scope`: Approve a scope change.
    - `paused_team`: Approve the team.
    - `draft` without an approved scope: Approve the scope to start.
    - `draft` with an approved scope: Send the first message.
  - **Working:**
    - `queued`: Queued.
    - `starting`: Starting.
    - `running`: Working.
    - `waiting_lock`: Waiting for the project.
    - `cancelling`: Stopping.
  - **Done:**
    - `idle` or `completed`: Report ready (research with `report.md`), otherwise Waiting for your message.
    - `failed`: Stopped after an error.
    - `interrupted`: Interrupted.
    - `cancelled`: Stopped.
    - Read-only tasks: Earlier task, read only.
  - Each group shows up to 8 tasks and a "Show all N" toggle. Groups with no tasks are left out.
  - The open task is highlighted.
- **Bottom of the sidebar:**
  - **Running now · N** opens the existing Running page, which still lists running tasks across both modes.
  - **Settings.**
  - The footer notes are gone.
- **Backend.** Task rows gain `scope_approved` (bool), and research rows gain `has_report` (bool), meaning `report.md` exists.

## Calls made by the designer

- Running stays as a small link, because it is the only view across both modes.
- 8 tasks are shown per group.
- Idle and completed tasks go under Done.
