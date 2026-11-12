# Interspace

A personal observatory for projects, research, knowledge, and specialist AI agents.

**Status: native Mac development app with a task desk, controlled Python editing and per-task token budgets.** Launch `dist/Interspace.app` after [building](app/README.md). Tasks have separate conversations, plans and results. The Orchestrator can assign multiple Web searchers, Researchers and Reviewers within a user-set allowance, with the exact team and call limit approved before Start. The design preview and earlier offline pilot remain separate. Fix & test tasks add bounded Implementer/Tester/Reviewer work behind separate generation, check and application approvals. Other catalog roles and external-app integrations do not execute.

## Mac app

Double-click `dist/Interspace.app`. Add or select a Git project, save its committed source selection in **Settings**, then choose **New task**. Describe the outcome, adjust the specialist allowance if needed, inspect the proposed plan and Start it. Six is the initial allowance, not a fixed maximum; assignments execute sequentially. Read-only review is the default. Choose **Fix & test (Python)** for bounded replacement proposals: inspect the candidate, separately approve fixed checks, then separately apply the exact reviewed changes. Only that final action writes the displayed paths, uncommitted. See [app setup and limits](app/README.md), [task-desk verification](docs/task-desk-validation.md) and [controlled-editing validation](docs/controlled-editing-validation.md).

## Design preview

Open `design/index.html` in a modern browser. No installation, server, API key, or network requests are required. The preview follows your system's light/dark appearance.

Try the project map, project tabs, agent roles, first-launch state, connection scope previews, and the approval / request-changes flow. All content is illustrative. State resets on reload.

The preview opens in **Agents → Tasks**. Switch to **Observatory** for the optional research-lab view. Both views share task selection and status. Characters stay at workstations grouped into departments as the team grows. Click a figure or its keyboard-accessible roster button to inspect its task, activity, output, blockers, and permissions. **Preview review stage** changes sample task status without moving characters. Choose Blueprint, Fieldwork, or Printshop to compare palettes. No real agents run.

**Role library** contains 23 specialist templates across Discovery, Research, Engineering, Analysis, Review, Writing, and Operations. Read each role playbook, add multiple instances, assign separate sample tasks, or create a custom role. Department filters keep larger teams manageable. The 23 playbooks include 69 seed evaluation scenarios; model evaluations have **not** been run. Custom roles are user-written drafts without reviewed playbooks. This design preview does not execute agents; the separate native app executes only its supported bounded roles.

Earlier conversation previews are preserved in [design/archive](design/archive/README.md). All Interspace project files now live within this repository; the archive is historical. Current sources are the UI in `design/observatory.fragment.html`, the scene in `design/scene/lab-scene.js`, and the role definitions in `design/agents/`.

## Intended product

Sample project screens use an illustrative research domain.

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

The Mac app implements bounded read-only review, controlled Python editing and a Codex connection. Broader role execution, external integrations, notarized distribution and additional-platform packaging remain future work.

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

### Multi-project workspaces

The native app now keeps a local project registry with separate conversations, proposals and review histories. Add a Git project, set its brief and priority, then use Workspace scope to compare next actions across projects. Detailed evidence stays project-scoped; one interaction runs at a time, even when browsing another project. Existing single-project state migrates with a backup. See [the Mac app guide](app/README.md#multiple-projects) for source-selection and runtime limits.
