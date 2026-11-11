# Evidence response contract fix — 2026-11-11

Branch: `codex/evidence-contract-fix`, based on `8c8b14c`.

## Reproduction and correction

A live read-only task returned a Researcher proposal with an empty evidence array. The provider response schema allowed that value, but the application validator required 1–10 citations for every classified finding. Replaying the saved response reproduced the failure. The run stopped before Reviewer or synthesis; it was not resumed or repaired in place.

The team response schema now declares the same minimum and maximum evidence counts as runtime validation. Shared guidance in the schema, specialist prompts and synthesis prompt explains that proposal citations identify motivating source context, rather than proving implementation or validation. Ideas without relevant supplied evidence belong in unresolved questions; citations must never be invented. The runtime error now explains this requirement.

Source-ID and LF-range validation, role verdicts, call reservations, dependency ordering, exact approvals and the no-retry policy are unchanged. Legacy report schemas and the pilot are unchanged. This fix does not add a new run or enlarge a source scope.

The [official OpenAI structured-output documentation](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas) lists `minItems` and `maxItems` as supported array constraints, with separate restrictions for fine-tuned models. This is documentation evidence, not a live provider acceptance test.

## Verification

- The new schema/runtime regression failed before the fix: empty and eleven-item evidence arrays were advertised as valid for facts, interpretations and proposals. It passes after the correction; one and ten citations remain valid.
- Application workflow checks use disposable repositories and controlled providers. Cited proposals reach Reviewer and synthesis. Uncited proposals stop before dependencies, without a retry, stored artifact or source change.
- Focused suites: 11 orchestration tests and 20 team tests passed.
- Complete Python 3.14.6 suite: 104/104 passed.
- Complete Apple Python 3.9.6 suite: 104/104 passed.
- Native app rebuilt; strict signature verification passed. Both changed backend files in the bundle match the source files.
- Generated preview and role-contract checks passed; these do not establish model accuracy.
- A separate read-only code review found no actionable issues.

## Limits

No real provider calls were used to verify this fix. The prior failed task remains failed, with its original call count and artifacts. Sample Project HEAD, status and tracked-file hashes still match its baseline. No Sample Project edits, API calls, simulation or experiment occurred.

The Mac remains locked, so native interaction was not checked. This backend-only change does not alter UI files. Citation structure and workflow tests do not establish semantic evidence quality or guarantee future model adherence.
