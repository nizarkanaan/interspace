# Read-only pilot validation

Checked 2026-11-10 on feature/readonly-pilot. This branch is not merged into main.

## Executed

- Prepared the allowlisted committed Sample Project snapshot and retained its source revision and hashes in ignored local run storage.
- The controlling Codex session dispatched a real Researcher, accepted its structurally validated artifact, then dispatched an independent Reviewer. The Reviewer accepted the bounded repository review. Neither worker performed a fresh literature search, executed an experiment or changed the source project.
- The post-run integrity check compared source HEAD, Git status and SHA-256 of all tracked working files. It matched the baseline, including the two pre-existing edits. Untracked contents were not hashed.
- Nine standard-library unit tests pass: committed/dirty separation, required inputs, citation source/range checks, completion order, review outcomes, snapshot tampering, direct/ancestor/snapshot-root symlinks, relocated runs inside the protected source, LF line semantics and markup injection.
- Three regression tests failed before the final path/newline fixes and passed afterward. The macOS test fixture path was canonicalized to avoid the system /var symlink masking the intended relocation case.
- Chromium opened the real run's report, review, five recorded events and source manifest; citation buttons exposed source lines. Widths 1280, 1024, 390 and 320 had no horizontal document overflow. Fresh file navigations showed no page errors. An earlier browser check reused a document's JavaScript context and timed out; fresh navigations passed.
- Existing preview/playbook generation and whitespace checks pass. The 69 playbook seed scenarios remain unexecuted; this pilot is not their benchmark.

## Boundaries

The execution bridge is the current Codex session. The runner itself has no model API or auto-dispatch integration, and cannot meter session cost or cancel host workers. Local loopback binding and nested Codex startup were blocked by the current environment. The final viewer is an offline, inspectable record, not a streaming service. Runtime snapshots/reports stay ignored and are not included in the implementation commit.

No simulation or benchmark was started. The generated experiment remains a proposal needing a separate resource scope and authorization. Passing the software checks and receiving reviewer acceptance do not establish the scientific validity of the sample project's model.
