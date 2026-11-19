# Multi-provider workspace: frozen interface contracts (Wave 0A)

Date: 2026-11-15. Status: frozen by the coordinator for Wave 1, under the plan the user approved on 2026-11-15: `docs/superpowers/plans/2026-11-15-multi-provider.md`. Wave 1 is merged. Wave 2A (2026-11-19) wired the backend end to end and recorded its additions in each file, marked "Wave 2A"; `tests/test_e2e_team.py` runs the whole flow with the fake CLIs.

These contracts let the four Wave 1 streams build in parallel. Each stream codes against the shapes here and fakes everything it does not own.

| Contract | File | Producers | Consumers |
| --- | --- | --- | --- |
| Provider registry, sign-in, routing defaults | [providers.md](providers.md) | 1A | 1B, 1C, 2A |
| Orchestrator, team proposals, child runs, new events | [orchestration.md](orchestration.md) | 1B | 1C, 1D, 2A, 2B |
| Review and merge | [merge.md](merge.md) | 1D | 1C, 2A |

## Still in force from Agentic Spaces

These earlier contracts still apply, minus everything about connected apps:
- `docs/superpowers/specs/agentic-spaces/events.md`, without `app_action` and connector tools;
- `scheduler.md`, without the Spaces pool and the legacy slot;
- `scope.md`, without app scopes.

Their conventions also still apply:
- Python 3.9 and the standard library only;
- plain JSON dicts validated at each boundary;
- user-visible errors subclass `ValueError` and stay safe to show;
- `uuid4().hex` identifiers;
- ISO UTC times with a `Z` suffix;
- `"v": 1` on every persisted or streamed record;
- tokens only, never money;
- private content stays in Application Support.

`iso_time` and `parse_time` move from the deleted `spaces/base.py` to `app/backend/timeutil.py`.

## User decisions behind these contracts (2026-11-15)

1. Connected apps are deleted.
2. **Routing.** The user's per-role defaults apply. The Orchestrator may suggest a different provider or model, and the user approves the whole team, with providers, before anything runs.
3. **One task type.** Every task is a conversation with the Orchestrator. The old modes, the Observatory and Workspace advice are gone, and old tasks stay readable.
4. **Claude may write** inside its own task workspace, through scope-decided permission prompts.
5. **Merge is explicit.**
6. **Gemini later.** It becomes one more registry entry and adapter.
