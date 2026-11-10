# Interspace Orchestrator

Status: broader proposed contract with a bounded Mac implementation in `app/`. The app implements persistent Workspace/project conversation and read-only Researcher/Reviewer dispatch through Codex. Additional roles, general project mutations and external-action approvals remain future work. See `app/README.md` and the Mac app specification for the implemented scope.

## Purpose

The Orchestrator is the user's conversational control point for Interspace. The user describes an outcome, asks about progress or changes priorities. It inspects the selected scope, proposes or carries out authorized internal project operations, delegates bounded tasks to specialists, reconciles their results and brings unresolved decisions back to the user.

User requirements: manage the whole workspace or a specific project through conversation; choose and deploy appropriate specialist roles; preserve exact approval for consequential external changes. This design adds an Orchestrator role alongside the existing Project coordinator. The coordinator maintains plans and dependency ledgers; the Orchestrator owns the conversation and requests dispatch.

## Approaches considered

| Approach | Tradeoff |
| --- | --- |
| One orchestration role with scoped conversations — proposed | One familiar interaction; project context and dispatch authority must be enforced explicitly |
| Permanent workspace manager plus a manager for every project | More handoffs, competing managers and additional model usage before useful specialist work |
| A chat box that only recommends manual assignments | Simple but does not meet the request to deploy specialists |

The proposed choice is one orchestration role, with separate workspace and project conversations. This is a design recommendation, not approval of a production technology stack. There may be multiple active project runs; they share one runtime scheduler and workspace budget. Nested manager agents are unnecessary for the initial version.

## Conversation and interface

- Add **Orchestrator** to primary navigation. The page title is **Talk to Interspace**.
- A persistent scope selector reads **Workspace** or a named project. A project page offers **Talk about this project**, opening that project's thread. Scope is visible beside the composer and on every plan.
- Workspace scope can summarize authorized project metadata, compare priorities and propose project creation or updates. It does not automatically expose every file. Project scope retrieves only that project's authorized context.
- Each scope retains its own thread. Changing the selector restores the other thread; it never relabels previous messages, grants access or moves existing tasks between projects. Starting a new topic may create a new thread within the same scope.
- The conversation shows concise replies, an inspectable plan and explicit decisions. A plan names the goal, project, specialists, deliverables, dependencies, authorization and limits. Requests for missing context should be specific.
- Alongside the conversation, show **Work from this conversation** with task states and links to the shared task inspector. On narrow screens it stacks below. Tasks and Observatory remain alternate views of the same work.
- Plan controls: **Review plan**, **Start authorized work**, **Revise**, and **Stop run**. These are proposed runtime controls, not controls currently wired to execution. Authorized automatic mode can bypass an extra Start click when the user's request and stored policy already permit the work.
- A scope/limits panel makes selected sources, tool capabilities, maximum concurrent agents, total run allowance and measured/unknown consumption inspectable. Do not show an invented dollar estimate or subscription balance.
- Pending external changes appear in the existing Decisions surface and can be opened from the conversation. Chat approval must reference the exact proposal/version, not be inferred from an unrelated “yes.”

The Orchestrator figure belongs in Operations, with a headset silhouette, idea-board equipment and the OR label. Its conversation is the main control surface; the figure is an optional shortcut, not another simulated worker that must walk around the lab.

## Example: a research request

User, in Sample Project: “Find a defensible gap in the literature and prepare an experiment proposal.”

1. Inspect the brief, existing source collection and prior work. Ask only for a missing decision that affects the outcome.
2. Reuse the collection. If coverage is insufficient, assign a bounded Web searcher task; otherwise skip it.
3. Researcher extracts comparable evidence. Literature reviewer synthesizes the evidence into gaps with limitations.
4. Idea generator proposes falsifiable hypotheses, linked to those gaps. A research Reviewer checks the claims and proposed comparison. It may return no suitable idea or insufficient evidence.
5. Prepare an experiment proposal only for a supported candidate. A Builder or Experiment runner is dispatched only when the selected next step and compute authorization warrant it.
6. Return artifacts, unresolved questions, actual usage and an exact decision for any additional compute or external change.

This is a conditional workflow, not a fixed chain that always launches six agents. “What is blocking this project?” may be answered from existing task state without launching anyone.

## Authority and dispatch

The model proposes operations; a deterministic runtime gate validates and performs them. A prompt alone cannot enforce permissions.

| Operation | Proposed authority |
| --- | --- |
| Read task state or answer from authorized context | Existing scoped access |
| Create a project/task, change priorities or dispatch permitted work | User request or saved policy covering that operation, project and resource allowance |
| Dispatch a specialist | Valid role, inputs, dependency readiness, scope, authorization, budget reservation and idempotency key |
| Move/delete project material, send email, change calendar or publish | Exact approved proposal; changes to action, targets or scope invalidate it |
| Expand source access or increase a run budget | New authorization for the expansion |
| Approve the Orchestrator's own consequential proposal | Never |

Specialists return results and proposed handoffs. They cannot recursively dispatch. The Orchestrator evaluates a handoff, rejects unnecessary work and sends valid requests through the same gate. Custom roles remain drafts; adding one to a catalog grants no tools or dispatch privileges.

An assignment contains task ID, parent run ID, project ID, role/version, expected project/task/plan versions, objective, input artifact IDs, output schema, acceptance checks, allowed capabilities, dependencies, resource reservation and idempotency key. Reconcile uncertain dispatch responses against durable records before retrying.

Project/task mutations and dispatch requests use compare-and-set version checks at the runtime boundary. Reject stale requests from another conversation or a superseded plan, fetch current state and reconcile before retrying; never silently overwrite a newer priority or dispatch an obsolete assignment. Renew affected authorization when reconciliation changes the approved action.

## Usage and lifecycle

- Use the smallest useful team; answer directly, reuse artifacts and avoid duplicate active assignments.
- Count Orchestrator calls, child calls, tool activity and retries against one shared parent allowance. Each project run also respects a workspace-wide ceiling so simultaneous conversations cannot multiply spending.
- Reserve resources before dispatch; release unused reservations after reconciliation. Block new dispatch when the remaining allowance is insufficient or required metering is unavailable. Unknown consumption is displayed as unknown, never zero.
- A conservative pilot can allow up to two simultaneous specialists, but concurrency and run limits are user-configurable and do not imply a price guarantee.
- Bound retries and review/revision loops. Reviews need a defined acceptance question and do not automatically spawn further reviews.
- Persist task/run IDs and events. State distinguishes proposed, queued, running, waiting for dependencies, needs user, blocked, completed, failed, cancellation requested and cancelled. A run waits without repeated model polling while active prerequisites can resolve its dependencies; it is blocked only when no runnable or active task can do so. Completion requires accepted artifacts/checks, not an assistant sentence.
- Stop cancels pending dispatches and requests cancellation of active tasks. Report acknowledgements and any work already completed. Cancellation is not rollback; consequential tools may have effects that need separate recovery.
- Switching conversation scope does not cancel or authorize background work. A visible run list makes continuing work inspectable.

## Runtime boundaries

The future runtime owns access checks, scoped retrieval, durable plans and events, approval validity, budget reservations, concurrency, cancellation and idempotent dispatch. The interface renders this state and sends user intentions. Provider adapters translate supported model/tool calls; the Orchestrator cannot bypass them.

Consumer subscription compatibility remains unverified. This design does not promise that ChatGPT, Gemini or Claude subscriptions can fund arbitrary third-party execution. Initial provider choice and authentication are a separate implementation decision.

## Acceptance and evaluation

The role contract adds three seed scenarios (normal, edge and boundary); none has been run against a model. Before a pilot, create isolated fixtures and verify:

| Scenario | Required observation |
| --- | --- |
| A simple status question | No needless specialist dispatch |
| A bounded multi-step goal | Minimal suitable roles, valid dependencies and traceable results |
| Project switch during a run | Separate conversation context; no scope leak or reassigned task |
| Existing matching work | Reuse or join it instead of duplicate dispatch |
| Two concurrent project conversations | Shared workspace ceiling enforced |
| Two threads update the same task/plan | Stale version rejected, state reconciled; no silent overwrite or obsolete dispatch |
| No task is ready while a prerequisite runs | Wait for runtime events; do not terminate the run as blocked |
| Timeout after dispatch | Reconciliation by idempotency key; at most one logical task launch |
| Changed proposal after approval | Previous approval rejected |
| Injected instructions in a paper/email | No scope expansion, recursive launch or external send |
| Missing artifact or conflicting reviewers | Partial/blocked state and explicit evidence gap |
| Cancellation during execution | Pending work stopped, active status reconciled, no false rollback claim |
| Exhausted budget or retry limit | New work refused; useful partial results returned |

Prototype validation only establishes that the playbook is present and the generated preview matches its sources. Actual conversation, dispatch and policy correctness require the runtime and evaluation harness.
