"""Per-task token budgets: estimates, a durable usage ledger and the pre-call gate.

Budgets count tokens only. Interspace cannot know money or remaining account allowance.
"""
import uuid

MAX_BUDGET = 2 ** 53 - 1
DEFAULT_BUDGET = 250000
# Estimates deliberately over-estimate. English prose averages about four characters per
# token; three leaves room for code and JSON. Recorded live calls reported 14,193-21,719
# input tokens, most of it the provider's own instructions plus our context.
CHARS_PER_TOKEN = 3
PROVIDER_OVERHEAD_TOKENS = 12000
OUTPUT_RESERVE = {'Orchestrator': 4000, 'Implementer': 8000}
DEFAULT_OUTPUT_RESERVE = 4000
# Agent turns (codex app-server) reserve a fixed allowance per turn. The 0B spike measured about
# 21,000 tokens for a minimal turn; 30,000 leaves room for a few tool steps. PROVISIONAL(0B-2):
# longer turns overshoot and the overshoot is shown, and mid-turn usage reports stop a turn at the cap.
AGENT_TURN_ALLOWANCE = 30000
PROVIDERS = ('codex', 'claude')
# Entries without a provider are Codex (the Claude Code provider spec requires this reading).
CHARGE_RULES = {'codex': 'codex.input+output', 'claude': 'claude.input+cache_creation+cache_read+output'}
CHARGE_FIELDS = {
    'codex': ('input_tokens', 'output_tokens'),
    # Anthropic's input_tokens excludes cache writes and reads, so the four counts are disjoint.
    'claude': ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens'),
}


class Exhausted(ValueError):
    """A call was refused before launch because its estimate does not fit the task budget."""


def validate(value):
    if value is None:
        return None
    if type(value) is not int or value <= 0 or value > MAX_BUDGET:
        raise ValueError('Token budget must be a positive whole number of tokens.')
    return value


def charge(usage, provider='codex'):
    """Tokens charged for one call, or None when no complete count was returned.

    Only providers with a rule in CHARGE_RULES are counted; any other provider's usage is
    unknown and the call is charged its estimate.

    Codex TokenUsage: cached_input_tokens is a subset of input_tokens, and reasoning output
    is part of output_tokens (its own blended total is non-cached input + output_tokens).
    So input_tokens + output_tokens counts every token exactly once, cached input included.

    Claude (runtime.claude.turn_usage): input, cache creation, cache read and output are disjoint, so all
    four are added. Any missing, negative or non-integer field makes the count unknown.
    """
    if provider not in CHARGE_RULES or not isinstance(usage, dict):
        return None
    values = [usage.get(name) for name in CHARGE_FIELDS[provider]]
    if any(type(v) is not int or v < 0 for v in values):
        return None
    return sum(values)


def estimate_chars(chars, role):
    return PROVIDER_OVERHEAD_TOKENS + -(-chars // CHARS_PER_TOKEN) + OUTPUT_RESERVE.get(role, DEFAULT_OUTPUT_RESERVE)


def estimate(prompt, role):
    return estimate_chars(len(prompt), role)


_estimate_prompt = estimate  # reserve's `estimate` parameter shadows the function name.


def estimate_turn(prompt_chars):
    """The reservation for one agent turn: a fixed allowance plus the user's message."""
    return AGENT_TURN_ALLOWANCE + -(-prompt_chars // CHARS_PER_TOKEN)


def _amount(value):
    return value if type(value) is int and value >= 0 else None


def _entry_charge(entry):
    kind = entry.get('charge_kind')
    if kind == 'reserved':
        return None
    if kind in ('reported', 'estimated'):
        return _amount(entry.get('charge'))  # A malformed saved charge counts as unknown, never as zero.
    return charge(entry.get('tokens'), entry.get('provider', 'codex'))  # Entries recorded before budgets existed.


def ledger(state, task_id, token_budget=None):
    used = reserved = estimated = unknown = 0
    entries = []
    for entry in state.get('usage', []):
        if not isinstance(entry, dict) or entry.get('task_id') != task_id:
            continue
        entries.append(entry)
        if entry.get('charge_kind') == 'reserved':
            held = _amount(entry.get('estimate'))
            if held is None:
                unknown += 1
            else:
                reserved += held
            continue
        amount = _entry_charge(entry)
        if amount is None:
            unknown += 1
            continue
        used += amount
        if entry.get('charge_kind') == 'estimated':
            estimated += amount
    totals = {'budget': token_budget, 'used': used, 'reserved': reserved, 'estimated': estimated,
              'unknown': unknown, 'entries': entries}
    totals['remaining'] = None if token_budget is None else token_budget - used - reserved
    totals['overshoot'] = 0 if token_budget is None else max(0, used - token_budget)
    return totals


def reserve(state, task, *, role, prompt, project_id, run_id=None, assignment_id=None,
            estimate=None, provider=None, turn_id=None, call_kind=None):
    """Hold an estimate before a call. Agent turns pass `estimate`, `provider`, `turn_id` and `call_kind`."""
    need = _estimate_prompt(prompt, role) if estimate is None else estimate
    if type(need) is not int or need <= 0:
        raise ValueError('Token estimate must be a positive whole number.')
    if provider is not None and provider not in PROVIDERS:
        raise ValueError('Unknown model provider.')
    limit = validate(task.get('token_budget'))
    if limit is not None:
        totals = ledger(state, task['id'], limit)
        if totals['used'] + totals['reserved'] + need > limit:
            left = max(0, totals['remaining'])
            raise Exhausted('Token budget exhausted: the next ' + role + ' call needs about ' + format(need, ',')
                            + ' tokens, but only ' + format(left, ',') + ' of ' + format(limit, ',')
                            + ' remain. No call was started. Raise the task budget, then request a new plan or approval.')
    entry = {'id': uuid.uuid4().hex, 'role': role, 'project_id': project_id, 'task_id': task['id'],
             'tokens': None, 'outcome': 'reserved', 'estimate': need, 'charge_kind': 'reserved', 'charge': None,
             'prompt_chars': len(prompt)}
    if run_id is not None:
        entry['run_id'] = run_id
    if assignment_id is not None:
        entry['assignment_id'] = assignment_id
    if provider is not None:
        entry.update(provider=provider, charge_rule=CHARGE_RULES.get(provider), turn_id=turn_id, call_kind=call_kind)
    state.setdefault('usage', []).append(entry)
    return entry['id']


def _reserved_entry(state, entry_id):
    entry = next((e for e in state.get('usage', []) if isinstance(e, dict) and e.get('id') == entry_id), None)
    if entry is None or entry.get('charge_kind') != 'reserved':
        raise ValueError('Unknown or already settled token reservation.')
    return entry


def settle(state, entry_id, usage, outcome):
    entry = _reserved_entry(state, entry_id)
    amount = charge(usage, entry.get('provider', 'codex'))
    entry.update(tokens=usage, outcome=outcome)
    if amount is None:
        entry.update(charge_kind='estimated', charge=entry['estimate'])
    else:
        entry.update(charge_kind='reported', charge=amount)
    return entry


def release(state, entry_id):
    """Drop a reservation whose call was never launched (its setup failed before dispatch)."""
    entry = _reserved_entry(state, entry_id)
    state['usage'].remove(entry)


def recover(state):
    """A reservation that survived a restart is charged its estimate; it is never released."""
    for entry in state.get('usage', []):
        if isinstance(entry, dict) and entry.get('charge_kind') == 'reserved':
            entry.update(charge_kind='estimated', charge=_amount(entry.get('estimate')), outcome='interrupted')


def typical_prompt_chars(state, task_id):
    """The task's most recent recorded prompt size: a rough proxy before exact prompts exist."""
    for entry in reversed(state.get('usage', [])):
        if isinstance(entry, dict) and entry.get('task_id') == task_id and type(entry.get('prompt_chars')) is int:
            return entry['prompt_chars']
    return 0


def projection(state, task, roles):
    """Projected use for planned calls (role names); None when the task has no budget.

    `fits` uses the task's typical prompt size and is advisory. `first_fits` uses the smallest
    possible call, so it is False only when the next call certainly cannot fit.
    """
    limit = validate(task.get('token_budget'))
    if limit is None:
        return None
    totals = ledger(state, task['id'], limit)
    chars = typical_prompt_chars(state, task['id'])
    projected = sum(estimate_chars(chars, role) for role in roles)
    base = totals['used'] + totals['reserved']
    return {'budget': limit, 'used': totals['used'], 'reserved': totals['reserved'], 'remaining': totals['remaining'],
            'projected': projected, 'calls': len(roles), 'fits': base + projected <= limit,
            'first_fits': not roles or base + estimate_chars(0, roles[0]) <= limit}
