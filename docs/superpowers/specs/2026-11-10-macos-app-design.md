# Launchable Interspace Mac app

The user authorized moving beyond the offline pilot to a launchable app, with Sample Project protected and all implementation on the existing feature branch. This delivers a Mac application window, persistent scoped conversation, real Codex dispatch and read-only Researcher/Reviewer work. No external writes, simulation execution, arbitrary tools or other providers are part of this first runtime.

## Implementation choice

Use AppKit + WKWebView and a Python JSON-lines subprocess over pipes. This is the selected engineering default: it uses the installed Mac toolchain, retains the web UI style and needs no listener/server. Electron would add an unnecessary runtime dependency; Tauri requires another toolchain. Other OS packaging is deferred. The build produces an ad-hoc signed local Interspace.app; this is not a notarized installer or a portable Python distribution.

## Interaction

Launch Interspace.app, choose a Sample Project checkout using a native folder picker, check Codex sign-in and talk to the Orchestrator. Workspace and project conversations persist separately. The model can answer or propose a bounded read-only review; a visible Start review action authorizes the proposal. Researcher then Reviewer execute through the CLI automatically, with observed progress, results and cancellation. Tasks and an optional static Observatory share the same run. Existing source citations and integrity checks remain available.

## Architecture and limits

- The native shell allows only bundled local UI and opens external links in the default browser. It owns folder selection and a strictly enumerated request bridge.
- The backend persists app state atomically, owns scope/plan versions and dispatch, and reuses pilot committed snapshots outside the selected project. It rejects source folders containing app storage and prevents source changes from being hidden by resuming stale state.
- Codex exec is invoked without a shell, user config, MCP configuration or web search; read-only sandbox and never-approve policy, with shell and multi-agent features disabled. Only selected context is passed. The adapter stops if command/file/MCP execution events appear. It does not claim this replaces the CLI's OS sandbox.
- Model sessions are bounded by elapsed time, cancellation and at most three sequential jobs per interaction (Orchestrator, Researcher, Reviewer); no retries. Actual returned token usage is shown; money/subscription balance remains unknown. A deadline is not a dollar cap.
- Credentials remain in Codex's own store. Sign-in status is queried, never read from credential files. A missing CLI/auth or provider failure is an actionable error, never a sample answer. One-click sign-in opens the CLI's normal device flow; auth output is transient.
- A single active interaction prevents duplicate dispatch. Quitting cancels the provider process group; reopening marks interrupted work explicitly. No automatic rerun of interrupted work.
- Native dependencies: macOS 13+, Python 3.9+ and Codex CLI (the ChatGPT app's bundled CLI is discovered when available). Packaging verifies dependencies and reports missing ones in the window.

## Verification

Tests cover provider event parsing/nonzero exits, process timeout/cancel, allowed actions, durable conversations, stale plan versions, duplicate starts, malformed model JSON, semantic result schema/citation gates and source protection. No paid calls in routine tests. Build/typecheck the Swift app, inspect the bundled resources/signature, browser-test the real UI bridge with synthetic responses, and attempt an actual app launch/provider run. Record unavailable target checks without claiming success. A final independent code review checks boundaries. Main stays unmerged.
