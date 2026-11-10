# Interspace — Observatory design study

Date: 2026-11-10
Status: proposed visual direction; production architecture and implementation are not approved.

## Confirmed intent

Interspace is a locally installed personal interface for projects, research and specialist agents. Labmates can install the same software independently, with their own projects and AI accounts. There is no shared lab workspace requirement. The user chose the name Interspace and requested a distinctive UI and GitHub repository.

## Visual proposal

A personal observatory: a quiet, precise working environment with orbital geometry used for relationships, a warm mineral accent for decisions, muted green for available research paths, and compact monospace labels for operational context. Light mode uses warm paper surfaces; dark mode uses graphite and blue-grey surfaces. No ambient animation, fake telemetry or decorative dashboards.

The memorable interaction is the project atlas: the research question sits at the centre, with evidence, hypotheses, experiments and review surrounding it. Every node opens an ordinary, readable workspace. The map complements the list navigation.

### Accepted direction: two views of the same agent work

The user requested the stylized lab as an option alongside conventional task management. The Agents workspace now offers **Tasks** (the default) and **Observatory**. The design study opens on this workspace so both options are easy to compare.

- Tasks groups the shared sample items into Queued, Working, Needs you, and Done.
- Observatory presents the same items as Scout, Researcher, Builder, and Reviewer workstations, including their current activity and status.
- Both views use the same task projection and selected-task inspector. Switching views preserves selection, approval state, pause state, and the sample handoff. Returning from another screen preserves the selected view during the session.
- A labelled Preview handoff control demonstrates an evidence-matrix transfer from Researcher to Reviewer. The Researcher task completes and the Reviewer task becomes active in both views. Pausing disables this preview action. Reset handoff restores the sample sequence without undoing approval decisions.
- The transfer has a short, event-triggered motion in Observatory mode only. Reduced-motion users get the same state change without animation. There is no looping activity or suggestion that a real agent is running.
- The existing decision inbox remains the approval surface. Approval changes the sample experiment to Queued; it does not start a real run.

View preferences currently live only in the prototype session. Persisting a user's preferred view and connecting actual execution events are future application work.

## Surface contract

- Primary job: resume a project, see the next decision, and inspect agent work.
- Primary action: enter the project or inspect its pending proposal; the task composer prepares work rather than silently executing it.
- Hierarchy: project state first, pending decision second, agent activity third.
- Targets: 1024x900 desktop and 390x844 narrow. Also check 320px fit.
- Navigation: Overview, Projects, Agents, Knowledge, Decisions, Connections.
- Project sections: Brief, Papers, Hypotheses, Experiments, Files.
- References: user requirements in this conversation, the earlier Interface concept, and the correction that each installation is independent. No third-party UI imagery or private data was used.

## Prototype states

| State | Trigger | Feedback / next action |
| --- | --- | --- |
| Empty | Preview first launch | Choose a first project and inspect connection setup |
| Error | Submit an empty task | Visible message asks for a task or research question |
| Success | Approve or decline the sample proposal | Decision recorded in preview, with explicit no-execution notice and reset |
| Revision | Request changes | Feedback form; submit to return proposal with changes requested |
| Permission | Inspect a connection | Shows proposed source selection / account boundary; makes no connection |
| Loading | Not implemented | This static preview has no asynchronous work; production loading, cancellation and retry are unresolved |
| Partial | Not implemented | Real retrieval and connector failures are outside this preview; future UI must distinguish available evidence from missing data |

## Roles and controls

Researcher, Builder, Reviewer and Scout are templates, not fixed categories. Each eventual role specifies instructions, tool permissions, project context, output schema, execution bounds and provider configuration. Run history should record actions and outputs, not claim to expose hidden model reasoning.

Pending proposals should identify exact tool arguments, access scope, affected files, expected cost/usage where measurable, run limits and the approving user. The current sample is descriptive rather than an executable authorization.

## Local ownership

Project records and run history should be local. Credentials should use the OS credential store, not plain project files. Integrations require explicit access to chosen sources. Local installation does not mean local model inference: necessary task context will be sent to the selected provider.

No application-level account or hosted workspace service is needed for the initial personal app. Each installation owns its own provider session and usage. Remote compute can be a future connector, distinct from local installation.

## Architecture options for the next decision

1. **Desktop shell with a local backend — recommended direction.** Fits selected-folder access, background runs, OS credential storage, and an installable app. Requires packaging, signing and platform-specific testing. Exact framework remains open.
2. **Local web application.** Easier initial web iteration; users start a local service and open a browser. Adds startup and process-management friction. It can be a stepping stone to a desktop shell.
3. **Hosted multi-user service.** Not proposed: it adds accounts, server costs and data separation that the user explicitly does not need.

This document records a visual study and architecture alternatives. It is not approval to implement a production runtime.

## Candidate implementation sequence (uncommitted)

1. Agree the design and desktop/local-web delivery choice.
2. Verify one supported OpenAI authentication and bounded execution path.
3. Local project creation, selected-folder access, durable task/run records, one agent role and a real approval gate.
4. Read-only research sources and a reviewer role.
5. Additional integrations, specialist roles and provider adapters.

## Out of scope for this study

Real integrations, scraping, agent execution, email/calendar access, credentials, scheduling, usage-meter accuracy, installers, shared workspaces, live collaboration and provider subscription compatibility claims.
