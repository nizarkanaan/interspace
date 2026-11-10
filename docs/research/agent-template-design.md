# Agent template research and design

## Charter

- Goal: replace Interspace's short role sketches (initially 21, expanded to 22 with Code reviewer) with specific, inspectable role contracts and evaluation cases; preserve the expandable local design prototype.
- Knowledge depth: working knowledge of the prototype; external template quality and general effectiveness remain unverified.
- Scope / Object / Subject: reliable specialist-agent workflows / Interspace role definitions / official agent design and evaluation guidance, ECC specialist prompts, and maintained open-source examples.
- Type: descriptive — known UI and use cases need explicit role boundaries and acceptance criteria.
- Q1: Which fields and boundaries make roles specific and distinguishable?
- Q2: What should be reused from existing designs, and under what attribution/license conditions?
- Q3: What evaluation evidence is needed before calling a role accurate?
- Q4: How should the templates cover research, software, analysis, writing and personal operations without overlapping responsibilities?
- Authorized outcome: researched template design and prototype integration. No live provider execution, email/calendar writes, credentials, or paid evaluations.

## Canonical sources

Intended source ranking, recorded before external collection:
1. Rank 1: OpenAI and Anthropic's own agent design/evaluation documentation — intended patterns and limitations.
2. Rank 1: ECC and other agent-template maintainers' repositories and license files — actual role definitions and reuse terms.
3. Rank 3: Installed ECC 2.2.3 prompt files and Interspace source — exact available implementation, not independent proof of quality.
4. Primary domain guidance, where needed, for review reproducibility and statistical reporting.

## Findings ledger

| ID | Finding | Evidence | Rank | Questions |
| --- | --- | --- | --- | --- |
| F1 | Instructions should specify actionable steps and failure paths; extra agents should address demonstrated task/tool complexity. | OpenAI practical guide, opened 2026-11-10, Configuring instructions / Orchestration: https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/ | 1 | Q1, Q4 |
| F2 | Composable workflows, environmental feedback and bounded stopping rules are useful patterns; added autonomy carries cost and error risks. | Anthropic Building effective agents, 2024-12-19; page notes evolving tooling: https://www.anthropic.com/research/building-effective-agents | 1 | Q1, Q4 |
| F3 | Evaluation should check actual outcomes over repeated trials. Research grading needs claim grounding, coverage and source quality; expert calibration matters. | Anthropic Demystifying evals, 2026-01-09, evaluation structure / research agents: https://www.anthropic.com/research/demystifying-evals-for-ai-agents | 1 | Q3 |
| F4 | ECC code review asks for exact locations, concrete failure scenarios and surrounding context, and permits a clean review. Its agent-evaluator separates assessment from doing the original task. | Installed ECC 2.2.3 agents/code-reviewer.md lines 24–85; agents/agent-evaluator.md; upstream https://github.com/affaan-m/ECC | 3 / 1 | Q1, Q2, Q4 |
| F5 | ECC chief-of-staff includes automatic archiving and calendar changes; those defaults conflict with Interspace's proposed-change approval model. | Installed ECC 2.2.3 agents/chief-of-staff.md, triage execution and post-send follow-through sections | 3 | Q2, Q4 |
| F6 | Installed ECC is MIT-licensed, copyright Affaan Mustafa. Reuse of substantial source requires preserving the notice. | Installed ECC 2.2.3 LICENSE | 3 | Q2 |
| F7 | PRISMA offers reporting checklists with CC BY 4.0 terms. A reporting checklist alone is not proof a review is systematic or complete. | https://www.prisma-statement.org/prisma-2020-checklist, opened 2026-11-10; limitation is an Interspace design inference | 1 / inference | Q1, Q4 |

| F8 | Agency Agents has broad role templates and an MIT license. Its Reality Checker requires screenshots and defaults to needs-work; this is an example of a specialized workflow, not evidence of general accuracy. | https://github.com/msitarzewski/agency-agents/blob/main/testing/testing-reality-checker.md and LICENSE, opened 2026-11-10 | 1 | Q1, Q2 |
| F9 | OpenAI's skill-evaluation guide recommends targeted cases that test both intended activation and non-activation. | https://developers.openai.com/blog/eval-skills, opened 2026-11-10 | 1 | Q3 |
| F10 | ECC eval-harness distinguishes deterministic, model and human graders. The installed utilities explicitly do not establish runtime containment or candidate quality. | Installed ECC 2.2.3 skills/eval-harness/SKILL.md | 3 | Q3 |

## Scope filter

Discarded claims of universal production readiness, personality-based expertise, and preset self-confidence percentages as quality evidence. Retained bounded workflows and observable checks (F1–F4, F9–F10). Domain-specific requirements below are Interspace design proposals, not claims that a general agent framework validates scientific methods.

## Object filter

Excluded automatic archiving/calendar mutation from ECC chief-of-staff (F5): Interspace prepares proposed actions for approval. Excluded Agency Agents' fixed QA scripts, automatic needs-work verdict, and assumed revision count (F8). Adopted ECC's evidence requirement and acceptance of zero findings (F4), with a read-only Code reviewer separate from the research Reviewer. Did not import model names, installation commands or a multi-agent runtime. A role catalog is not an instruction to run every role on every task.

## Conclusions

- Use a common contract with a narrow mission, routing conditions, required inputs, ordered workflow, expected output fields, forbidden actions, handoffs and stop conditions. Each specialty supplies different content. [F1, F2, F4]
- Keep the software role broad enough to implement a bounded task, while separating evidence review, code review, experiment execution and statistical interpretation. Department grouping is a UI decision, not an execution topology. [F1, F2; Interspace proposal]
- Provide candidate templates and adversarial test cases, with an explicit not-evaluated status. Test real outputs and tool effects, repeat trials, and use a subject expert to calibrate research judgments. Static validation only confirms the template structure. [F3, F9, F10]
- Adapt design ideas rather than importing a prompt library unchanged. ECC attribution and its MIT notice accompany the code-review adaptation; Agency Agents was comparison material only. [F4–F6, F8]
- A coordinator proposes the smallest required set of specialists, passes structured artifacts rather than unrestricted conversation histories, and never silently expands permissions or budget. [F1, F2, F5; Interspace proposal]

### Approaches considered

1. Import an agent collection wholesale: quick initial coverage, but mismatched tool names, permissions, personality assumptions and evaluation claims.
2. Write every role independently: flexible, but likely to duplicate safety rules and produce inconsistent handoffs.
3. Common Interspace contract plus focused specialty instructions: chosen implementation proposal because it keeps permissions, budgets and evidence reporting consistent while allowing meaningful role-specific workflows.

### Acceptance criteria

- Every shipped template identifies its boundaries, input requirements, workflow, output fields, quality checks, blocked conditions, proposed handoffs and at least one normal, edge and scope-boundary evaluation case.
- Source and evaluation status are visible from Role library and selected-agent inspector.
- Different instances retain independent tasks; custom templates remain possible and are explicitly less reviewed drafts.
- No model/provider is invoked by browsing or adding role templates; the UI does not claim tested accuracy.
- Mechanical validation and browser workflows pass; actual model evaluations remain explicitly unexecuted.

## Next steps / Risks

Research review outcome: supported as a design recommendation, not an empirical accuracy finding. Source claims were checked by the same assistant; this was not an independent review. Original role-specific instructions are explicitly design proposals. Comparative template inspection covered ECC and Agency Agents, not an exhaustive survey of all agent repositories.

Delivered: 22 contracts, 66 seed evaluation scenarios, a generated playbook collection and inspectable prototype integration. Structural and browser checks are recorded separately.

Model-backed accuracy evaluations have not been run. Prompt specificity alone cannot establish reliability. Runtime enforcement of permissions, budgets, structured outputs and approval gates remains future work.
