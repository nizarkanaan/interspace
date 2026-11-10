# Interspace

A personal observatory for projects, research, knowledge, and specialist AI agents.

**Status: design study.** This repository contains a clickable UI prototype and proposed product direction. It does not run agents, authenticate AI accounts, read project folders, or connect to external apps.

## Preview

Open `design/index.html` in a modern browser. No installation, server, API key, or network requests are required. The preview follows your system's light/dark appearance.

Try the project map, project tabs, agent roles, first-launch state, connection scope previews, and the approval / request-changes flow. All content is illustrative. State resets on reload.

## Intended product

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
- [Engineering and debugging conventions](docs/engineering.md)
- [Standalone prototype](design/index.html)

Application architecture, agent execution, authentication, distribution, licensing, and integrations remain to be decided and implemented.

## Maintaining the preview

Edit `design/observatory.fragment.html`, then run:

```sh
node scripts/build-preview.mjs
node scripts/build-preview.mjs --check
git diff --check
```

The first command regenerates the standalone preview; the check fails if it has drifted from its source. These commands require Node.js and no packages. Opening the preview itself does not require Node.js.
