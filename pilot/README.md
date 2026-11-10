# Read-only Sample Project pilot

This is the first executed Interspace workflow, isolated on `feature/readonly-pilot`. It uses the **current Codex session as an artifact bridge**, not a standalone background provider service. The controlling assistant chooses two roles and dispatches the real Researcher and Reviewer sequentially. The Python runner validates submitted artifacts and persists the state; it does not itself call a model or automatically dispatch workers.

## Run it

Python 3.11+ is sufficient; no packages or server are needed.

```sh
python3 pilot/runner.py prepare --source /path/to/source-project
```

The command prints a run directory under ignored `workspace-data/pilot/`. It copies only an explicit allowlist of committed technical files using `git show HEAD:path`, records hashes and a baseline of the input checkout, and generates `index.html`. Uncommitted source edits and private records are not copied. The source repository stays on its existing branch.

The controlling Codex session then follows this bridge protocol:

```sh
python3 pilot/runner.py start --run RUN_DIR --role researcher
# Dispatch the Researcher with RUN_DIR/sources as evidence.
python3 pilot/runner.py complete --run RUN_DIR --role researcher --result RUN_DIR/researcher-result.json
python3 pilot/runner.py start --run RUN_DIR --role reviewer
# Dispatch the Reviewer with the same snapshot plus the research result.
python3 pilot/runner.py complete --run RUN_DIR --role reviewer --result RUN_DIR/reviewer-result.json
python3 pilot/runner.py verify --run RUN_DIR
```

Open `RUN_DIR/index.html` in a browser. It displays real received artifacts, recorded events, source hashes and clickable source-line references. This is an offline view, not a live chat. `complete`, `start` and `verify` regenerate it; refresh the browser after updates. Reports can be inspected even when no local HTTP listener is allowed.

## Result format

Both workers submit JSON with `summary` (nonempty string), `findings` (1–20 entries) and `proposal` (nonempty string). Every finding contains `claim` and nonempty `evidence`: `{source: "docs/PROJECT_CONTEXT.md", start: 1, end: 10}`. Sources must be in the manifest and line ranges must exist. The Reviewer additionally supplies `verdict`: `accept`, `revise`, or `blocked`. A revision request does not mark the overall run complete.

Line-range validation establishes that the cited evidence exists, not that the claim follows from it. That is the Reviewer's task. The final integrity check compares HEAD, Git status and every tracked working file's SHA-256 against the baseline; untracked file contents are not hashed. No source scripts, hooks, build, simulation or benchmarks are executed by the runner.

## Limits and execution environment

This bridge is intended for a trusted controlling session. Workers are instructed to read only the snapshot; the runner does not create an OS sandbox for the session's tools. It must not be presented as protection against a malicious host process. No network server or untrusted artifact-submission API is exposed. The two-worker allowance is enforced by the controlling session; the runner enforces stage order and refuses duplicate starts/completions. It cannot meter session tokens or dollars, enforce a model-spend ceiling or cancel a host agent. Those controls require the future provider runtime.

During the initial run, the installed Codex CLI reported ChatGPT authentication, but nested execution failed with `Operation not permitted`; a loopback bind probe was also denied. No credentials were copied or displayed. The bridge avoids claiming a standalone service was successfully started. Official provider reference: https://developers.openai.com/codex/noninteractive/ (reviewed 2026-11-10).

No fresh web literature search is part of this bounded run. Existing related-work notes remain dated evidence. Proposed experiments require a separate resource scope and authorization; preparing a proposal never starts one.

Runtime source snapshots, reports, events and generated HTML stay local under ignored `workspace-data/`. They must not be committed. To review implementation changes, use `git diff main...feature/readonly-pilot`; do not merge until the user accepts this pilot.

## Checks

```sh
python3 -m unittest discover -s tests -v
node scripts/build-role-playbooks.mjs --check
node scripts/build-preview.mjs --check
```
