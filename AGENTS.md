# Interspace project guidance

This repository contains the design prototype, an offline pilot and a native Mac application in `app/`. The user authorized the launchable app and read-only Orchestrator/task workflow. The runtime supports task conversations and Web searcher, Researcher and Reviewer dispatch, including repeated roles within a user-set allowance; it does not execute all catalog roles.

The user authorized the first working workflow on a branch with Sample Project as read-only input. Keep snapshot/pilot helpers under `pilot/`, native/backend/UI code under `app/`, tests under `tests/`, and development run data under ignored `workspace-data/`. App user data belongs in its Application Support directory. See `app/README.md`. Never modify, checkout or run the sample project from the pilot. Preserve existing source edits; use committed snapshots and verify integrity. Do not merge the pilot branch into main without the user accepting it. Read `pilot/README.md` for the explicit current-session bridge and its limitations.

## Product boundaries

- Each installation belongs to one person and runs on their own machine.
- Do not introduce lab membership, invitations, a hosted multi-user service, or shared provider credentials without a new request.
- Keep the UI provider-independent, initially targeting supported OpenAI integrations.
- Do not imply a consumer subscription includes arbitrary third-party API access. Verify supported authentication before implementing it.
- Keep private project data and credentials out of git. Use platform credential storage in a future application.
- No real email, calendar, filesystem, repository, or external-app writes in the design prototype.
- Agent activity, papers, hypotheses, metrics and run outcomes in the prototype must be clearly identified as sample data.
- Approval must bind to an exact proposed action and scope. Edits invalidate an approval.

## Design

Read docs/design-direction.md before changing the UI. Preserve the observatory direction, accessible controls, light/dark appearance, and responsive layout. Avoid decorative activity that implies real agent work. Agent figures stay in fixed departments; do not add walking, idle animation, or a simulation loop.

The preview sources are design/observatory.fragment.html (UI/state), design/scene/lab-scene.js (original static character artwork and hit testing), and design/agents/ (role catalog and contract data). Generate design/index.html and design/preview.fragment.html with `node scripts/build-preview.mjs`; never edit the generated page independently. Run `node scripts/build-preview.mjs --check` and `node scripts/build-role-playbooks.mjs --check` before committing preview changes. Role contract changes regenerate docs/agent-playbooks.md. Template validation is structural; never claim agent accuracy without model-backed evaluation evidence. Do not promote this throwaway UI into the production app before agreeing on architecture and scope.

## Engineering conventions

Use `interspace/` for new branch names, following the user's naming preference.

Read docs/engineering.md before implementing or debugging. Keep changes focused and follow the dependency boundaries there. Reproduce bugs and trace their cause before editing; use meaningful regression coverage for behavioral fixes. Verify the affected behavior and report actual results, including anything untested. Do not create speculative framework layers, empty application directories, or shared utilities without a concrete use.

The conventions incorporate ECC coding/design/verification guidance and Superpowers debugging/test-first/verification workflows; docs/engineering.md records the sources and adaptations. When installed, read and apply the relevant skill for the task. Keep the repository understandable and usable without requiring contributors to install those plugins. Do not claim skill compliance or successful verification merely because this guidance exists.
