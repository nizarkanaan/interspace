# Archive and delete tasks

Date: 2026-11-20
Status: approved in conversation ("both permanent delete and archive; when deleting, prompt me to merge and tell me the branch will be deleted")
Size: small project (backend methods, UI, Swift allowlist)

## Intent

Research questions and code tasks pile up in the sidebar. You should be able to:

- **archive** a task: hide it and restore it later;
- **delete** it permanently.

Deleting a code task must not lose unmerged work silently. It offers a review-and-merge first, and says plainly that the task's branch will be deleted.

## Behaviour

- **A working task can't be archived or deleted.** That means queued, starting, running, waiting for the project, stopping, or paused waiting on you. The app says "Stop this task first." Restoring is always allowed.
- **Archive** (`task_archive {task_id, archived}`) applies to a root task only:
  - it sets or clears `archived_at` and keeps everything;
  - archived tasks leave their mode's Needs you, Working and Done groups;
  - they appear in a collapsed **Archived · N** group at the bottom of the sidebar list, and open read-only as usual;
  - a **Restore** button brings a task back.
- **Delete check** (`task_delete_check {task_id}`) returns `{working, subagents, branches: [{project, name, exists, ahead, into, checked_out}]}`.
  - Branches are only ever the task's own published `target_branch` values, as the scheduler recorded them.
  - `ahead` is the number of commits on the branch that are not in the repository's current branch, `into`.
- **Delete** (`task_delete {task_id, branches: 'delete'|'keep'}`) refuses a working task, then removes:
  - the task and its subagents;
  - their saved records, events, attachments, outputs and corpus;
  - their private project copies (`workspaces/<id>`);
  - research scratch folders (`research-runs/<id>`);
  - any selection pointing at them.

  With `branches: 'delete'`, each branch is deleted with `git branch -D <name>` under the project lock, with one audit record per branch. A branch that is checked out in your working copy is never deleted; it is reported as kept. The method returns `{deleted_branches, kept_branches: [{name, reason}]}`.

  Token usage records and the audit log stay.

## UI

- **Buttons.** At the bottom of the task's details (the side panel, Scope and outputs, or Details): **Archive** (or **Restore**) and **Delete…**.
- **Confirmation.** Delete opens a confirmation in place. It loads `task_delete_check` and says what will be deleted, including the number of subagents.
  - **A code task with unmerged commits.** "Branch `interspace/task-…` has N commits not merged into `<into>`." The buttons are:
    - **Review and merge first**, which opens Review changes;
    - **Delete task and branch**, the danger button;
    - **Delete task, keep branch**;
    - **Cancel**.
  - **A merged branch.** "Branch `…` is fully merged into `<into>` and will be deleted with the task." The buttons are **Delete task and branch** and **Cancel**.
  - **A branch that is checked out.** The confirmation says the branch stays because it is checked out.
  - **A research task, or no branch.** The buttons are **Delete permanently** and **Cancel**.
- **After deleting:** you land on the mode's list, and a notice says what was deleted and which branches were kept.

## Calls made by the designer

- Archive and delete are refused while a task is working, instead of stopping it automatically.
- "Merged" means "has no commits that are not in the repository's current branch".
- A checked-out branch is never deleted.
- Archived tasks are hidden from the main Research and Tasks pages too.

## Task menu (revised 2026-11-20)

The user wanted the actions on the task itself, not under Scope and outputs.

- **Opening the menu.** Right-click a task in the sidebar, or press the context-menu key or Shift+F10 on a focused task.
- **The menu:** **Open**; **Stop** (only while the task is working); **Archive** or **Restore**; **Delete…**.
  - Archive and Delete are disabled while the task is working, with "Stop this task to archive or delete it."
  - The arrow keys, Home and End move through the menu. Escape or Tab closes it and returns focus to the task.
- **Delete…** opens a modal dialog with the same confirmation as before:
  - what will be removed;
  - the branch lines;
  - Review and merge first, Delete task and branch, Delete task, keep branch, and Cancel, with Cancel focused first.
- **After archiving or deleting,** a note at the top of the page says what happened. Deleting the task you are viewing returns you to its mode's list.
- **The details panel** no longer has Archive or Delete.
