# Role library and playbook validation

Checked 2026-11-10 in Chromium. This is prototype behavior verification, not model/agent accuracy evaluation.

## Executed checks

- Catalog initially exposes 22 built-in templates. Search, department filtering and the no-results state work.
- Every template was added through the UI, producing 26 independent sample instances including the original four. No agents or provider calls run.
- Multiple Inbox assistants retain independent task assignments. New instances begin Unassigned; saving a task sets Queued with an explicit no-execution message.
- Whitespace-only tasks and duplicate role names are rejected. Custom role names, instructions, expected outputs and task titles are escaped. HTML/script test strings displayed literally, created no image element and executed no script.
- Custom templates can create additional instances. Removing added instances and empty department selection are handled without a selected-task crash.
- Department filters scope both projections. Dynamic multi-row Canvas layout and a second-row figure hit target were exercised. Selection persists across task/lab views.
- Full built-in playbooks are readable from the catalog and selected-agent inspector. Custom templates explicitly state they have no reviewed workflow or evaluation cases.
- All three views fit 1280, 1024, 390 and 320 CSS-pixel widths without horizontal document overflow. Light/dark renders were inspected. Browser flows returned no page errors.
- Preview and generated-playbook drift checks, script syntax checks, whitespace validation and structural contract validation pass. The latter checks 22 contracts and 66 seed scenarios; it does not execute those scenarios against a model.

## Limitations

All state resets on reload. Tool labels are requested capabilities, not granted access. Playbooks are provider-independent draft specifications. The 66 scenarios still need concrete fixtures, a sandboxed runtime, independent expected results, repeated model trials and calibrated expert grading. No accuracy percentage, reliability certification or production readiness is claimed.

Evidence is recorded in design/evidence/role-library-report.json. Earlier screenshots/reports describe prior prototype versions.

## Orchestrator addition — 2026-11-10

The catalog now contains 23 roles and 69 seed evaluation scenarios. Chromium checks confirmed the Orchestrator can be found by search, its full playbook opens, and Add agent creates an unassigned sample instance with focus in the task field. The playbook fits 1280px and 390px viewports without horizontal document overflow; no page errors were observed. Structural contract, generated-preview and syntax checks pass. The first browser-check attempt used an unavailable locator helper; the corrected check inspected the focused element directly and passed. Evidence: design/evidence/orchestrator-role.png.

This addition defines an orchestration contract and proposed conversation interface. It does not implement chat, dispatch, authorization gates, budgets or cancellation. No model evaluation was run; earlier 22-role browser records remain historical.

## Sample Project pilot correction — 2026-11-10

The user selected a sample research project as the first working project. Updated the current sample brief, project navigation, hypotheses, comparison proposal and Orchestrator scenario to an illustrative research domain. Historical screenshots and archived previews retain their original examples. Chromium checks opened the project and all five sections, inspected the revised proposal and exercised sample approval at 390px. No page errors or horizontal overflow were observed. Generated-preview and structural playbook checks pass; this did not execute the proposed research or simulation.
