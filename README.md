# Interspace

A personal observatory for projects, research, knowledge, and specialist AI agents.

**Status: design study with a read-only workflow pilot.** The clickable prototype remains illustrative. The isolated [pilot](pilot/README.md) reviews a committed Sample Project snapshot through real specialist sessions dispatched by the controlling Codex chat and displays their recorded results. Standalone chat, automatic provider dispatch and external-app integrations are not implemented.

## Preview

Open `design/index.html` in a modern browser. No installation, server, API key, or network requests are required. The preview follows your system's light/dark appearance.

Try the project map, project tabs, agent roles, first-launch state, connection scope previews, and the approval / request-changes flow. All content is illustrative. State resets on reload.

The preview opens in **Agents → Tasks**. Switch to **Observatory** for the optional research-lab view. Both views share task selection and status. Characters stay at workstations grouped into departments as the team grows. Click a figure or its keyboard-accessible roster button to inspect its task, activity, output, blockers, and permissions. **Preview review stage** changes sample task status without moving characters. Choose Blueprint, Fieldwork, or Printshop to compare palettes. No real agents run.

**Role library** contains 23 specialist templates across Discovery, Research, Engineering, Analysis, Review, Writing, and Operations. Read each role playbook, add multiple instances, assign separate sample tasks, or create a custom role. Department filters keep larger teams manageable. The 23 playbooks include 69 seed evaluation scenarios; model evaluations have **not** been run. Custom roles are user-written drafts without reviewed playbooks. The new Orchestrator playbook defines scoped conversation and bounded specialist dispatch; those runtime capabilities are not implemented.

Earlier conversation previews are preserved in [design/archive](design/archive/README.md). All Interspace project files now live within this repository; the archive is historical. Current sources are the UI in `design/observatory.fragment.html`, the scene in `design/scene/lab-scene.js`, and the role definitions in `design/agents/`.

## Intended product

The first working workflow will target **a sample research project**. Sample project screens use an illustrative research domain.

Each person installs Interspace on their own machine and uses their own files, projects, and AI connections. Sharing the application does not share a workspace, credentials, or an AI usage allowance.

- Projects connect research questions, papers, hypotheses, experiments, files, and decisions.
- Configurable specialist agents have explicit tools, context, outputs, and run limits.
- A decision inbox shows proposed actions before execution.
- Local project history and selected-folder access are the default.
- OpenAI is the first proposed provider; other providers can be added later.
- Subscription authentication must be verified against the provider's supported integration path. API access is a separate billing path; this prototype promises neither subscription coverage nor unlimited usage.

## Design

- [Design direction and boundaries](docs/design-direction.md)
- [Preview validation](docs/validation.md)
- [Agent views validation](docs/agent-views-validation.md)
- [Static laboratory validation](docs/laboratory-validation.md)
- [Agent playbooks](docs/agent-playbooks.md)
- [Orchestrator design](docs/orchestrator-design.md)
- [Template research and design](docs/research/agent-template-design.md)
- [Role library validation](docs/role-library-validation.md)
- [Engineering and debugging conventions](docs/engineering.md)
- [Standalone prototype](design/index.html)

Application architecture, agent execution, authentication, distribution, licensing, and integrations remain to be decided and implemented.

## Maintaining the preview

Edit `design/observatory.fragment.html` for the UI and sample state, or `design/scene/lab-scene.js` for the static department scene. Role metadata lives in `design/agents/role-catalog.js`; workflows, boundaries, outputs, and evaluation scenarios live in `design/agents/role-contracts.json`. Then run:

```sh
node scripts/build-role-playbooks.mjs
node scripts/build-role-playbooks.mjs --check
node scripts/build-preview.mjs
node scripts/build-preview.mjs --check
git diff --check
```

The preview build regenerates both the standalone preview and the bundled `design/preview.fragment.html`; the check fails if it has drifted from its source. These commands require Node.js and no packages. Opening the preview itself does not require Node.js.
