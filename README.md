# Interspace

A personal observatory for projects, research, knowledge, and specialist AI agents.

**Status: native Mac development app.** Launch `dist/Interspace.app` after [building](app/README.md).
- **Agents.** Claude Code and Codex run as agents under one Orchestrator; Gemini comes later. Every task is a conversation with the Orchestrator, which can propose a team of subagents on mixed providers. You approve each team before it runs.
- **Code.** Each writing subagent works in its own copy of the project and commits to its own `interspace/task-…` branch, which you review and merge.
- **Research.** Research questions need no project. Agents search scholarly sources with keys you enter yourself, and every saved report can be checked claim by claim against its sources.
- **Earlier work.** Tasks from the earlier Read-only review and Fix & test modes stay readable but no longer run. The design preview and earlier offline pilot remain separate.

## Mac app

Double-click `dist/Interspace.app` and sign in to your providers under **Settings → Providers**. The sidebar switches between **Research** and **Code**:
- **New research question** or **New code task** starts a task.
- Your tasks are listed under **Needs you**, **Working** and **Done**, each with its state in words.
- **Right-click** a task, or press Shift+F10 on it, to open, stop, archive, restore or delete it.

**Usage** at the bottom of the sidebar shows Claude Code's and Codex's usage limits as each provider reports them, with the time of the reading.

For code, add a Git project folder. Approve the task scope, describe the outcome, approve the team the Orchestrator proposes, follow the subagents as they work, and use **Review changes → Merge**. Deleting a code task tells you whether its branch has unmerged commits, and offers to review and merge first.

**Research.** Under **Settings → Research sources**, add your own free keys or contact email for Semantic Scholar, OpenAlex, Crossref and Unpaywall; arXiv needs none. They stay in your Mac's Keychain and never reach agents.

In a wide window a research task opens as a split reader: the conversation on the left, and resizable tabs on the right.
- **Report.** The saved report, with each `[n]` linked to its reference and each reference marked with the citation checker's verdict. **Check claims** has an independent model, on the other provider, judge whether each cited source supports its sentence. It reads the abstract and, when an open-access copy exists, the most relevant passages of the full paper.
- **Corpus.** Every paper the agents found, with duplicates merged and each one's verdict.
- **Evidence.** A table that Claude and Codex fill in separately. Cells show where they agree and where they disagree, and numbers are flagged to check. You decide the disagreements and export the result as CSV.
- **Scope and outputs.** The task's scope, `report.md`, `references.bib` and `evidence.csv`.

Only a finished report, with a title and a numbered References list, can become `report.md`. Research requests are counted per source, never priced.

Everything above is tested with recorded source replies and fake agents. Live runs inside the app have only just started. See [Research](app/README.md#research).

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
- Claude Code and Codex are the first providers, each on your own sign-in; Gemini can be added later.
- Scholarly sources (Semantic Scholar, OpenAlex, arXiv, Crossref, Unpaywall) use your own keys or email; more sources can be added later.
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
- [Split reader](docs/superpowers/specs/2026-11-20-split-reader-design.md), [sidebar modes](docs/superpowers/specs/2026-11-20-sidebar-modes-design.md) and [archive and delete](docs/superpowers/specs/2026-11-20-archive-delete-design.md)
- [Task corpus](docs/superpowers/specs/2026-11-20-task-corpus-design.md), [report reader](docs/superpowers/specs/2026-11-20-report-reader-design.md) and [saving only finished reports](docs/superpowers/specs/2026-11-20-save-report-design.md)
- [Claim check](docs/superpowers/specs/2026-11-20-claim-check-design.md), [full text for it](docs/superpowers/specs/2026-11-20-claim-fulltext-design.md) and [two-agent evidence table](docs/superpowers/specs/2026-11-20-evidence-table-design.md)
- [Provider usage limits](docs/superpowers/specs/2026-11-20-usage-limits-design.md)
- [Standalone prototype](design/index.html)

The Mac app runs Orchestrator tasks with approved teams of Claude Code and Codex subagents, and reviews and merges their branches. Research questions without a project, research sources and the citation checker are being built. Gemini, notarized distribution and additional-platform packaging remain future work.

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

The native app keeps a local project registry. Each project has its own tasks, and its name, brief and priority are saved locally. Several tasks, in one project or across projects, can run at once. Existing single-project state migrates with a backup. See [the Mac app guide](app/README.md#projects-and-tasks).
