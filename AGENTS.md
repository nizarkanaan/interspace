# Interspace project guidance

This is currently a design repository, not an implemented agent application.

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

Read docs/design-direction.md before changing the UI. Preserve the observatory direction, accessible controls, light/dark appearance, and responsive layout. Avoid decorative activity that implies real agent work.

The preview source is design/observatory.fragment.html. Generate design/index.html with `node scripts/build-preview.mjs`; never edit the generated page independently. Run `node scripts/build-preview.mjs --check` before committing preview changes. Do not promote this throwaway UI into the production app before agreeing on architecture and scope.

## Engineering conventions

Read docs/engineering.md before implementing or debugging. Keep changes focused and follow the dependency boundaries there. Reproduce bugs and trace their cause before editing; use meaningful regression coverage for behavioral fixes. Verify the affected behavior and report actual results, including anything untested. Do not create speculative framework layers, empty application directories, or shared utilities without a concrete use.
