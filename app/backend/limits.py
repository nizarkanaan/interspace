"""Provider usage-limit readings (docs/superpowers/specs/2026-11-20-usage-limits-design.md).

Pure functions: a raw reading from a runtime becomes a list of windows, `{label, used_percent?, status?, resets_at?}`,
holding only what the provider reported. Nothing is estimated, and money is never involved.
"""
from timeutil import iso_time

CLAUDE_TYPES = {'five_hour': '5-hour limit', 'seven_day': 'Weekly limit', 'seven_day_opus': 'Weekly Opus limit',
                'seven_day_sonnet': 'Weekly Sonnet limit', 'overage': 'Extra usage'}
CLAUDE_STATUS = ('allowed', 'allowed_warning', 'rejected')
MAX_WINDOWS = 6


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _percent(value):
    value = _number(value)
    return round(float(value), 1) if value is not None and 0 <= value <= 100 else None


def _reset(value):
    """An epoch time (seconds, or milliseconds when very large) as an ISO time; anything else is dropped."""
    value = _number(value)
    if value is None or value <= 0:
        return None
    if value > 1e12:
        value = value / 1000
    try:
        return iso_time(value)
    except (OverflowError, OSError, ValueError):
        return None


def _minutes_label(minutes):
    minutes = _number(minutes)
    if minutes is None or minutes <= 0:
        return None
    minutes = int(minutes)
    if minutes == 10080:
        return 'Weekly limit'
    if minutes % 1440 == 0:
        return '%d-day limit' % (minutes // 1440)
    if minutes % 60 == 0:
        return '%d-hour limit' % (minutes // 60)
    return '%d-minute limit' % minutes


def codex(raw):
    """`account/rateLimits/updated` params: `{rateLimits: {primary, secondary}}`."""
    limits = raw.get('rateLimits') if isinstance(raw, dict) else None
    if not isinstance(limits, dict):
        return []
    windows = []
    for key, fallback in (('primary', 'Short-term limit'), ('secondary', 'Long-term limit')):
        window = limits.get(key)
        if not isinstance(window, dict):
            continue
        used = _percent(window.get('usedPercent'))
        if used is None:
            continue
        entry = {'label': _minutes_label(window.get('windowDurationMins')) or fallback, 'used_percent': used}
        resets = _reset(window.get('resetsAt'))
        if resets:
            entry['resets_at'] = resets
        windows.append(entry)
    return windows


def claude(raw):
    """`rate_limit_event.rate_limit_info`: `{status, rateLimitType?, resetsAt?, utilization?}`."""
    if not isinstance(raw, dict) or raw.get('status') not in CLAUDE_STATUS:
        return []
    entry = {'label': CLAUDE_TYPES.get(raw.get('rateLimitType'), 'Usage limit'), 'status': raw['status']}
    utilization = _number(raw.get('utilization'))
    if utilization is not None:
        used = _percent(utilization * 100 if 0 <= utilization <= 1 else utilization)
        if used is not None:
            entry['used_percent'] = used
    resets = _reset(raw.get('resetsAt'))
    if resets:
        entry['resets_at'] = resets
    return [entry]


READERS = {'codex': codex, 'claude': claude}


def merge(previous, windows, at):
    """The stored reading for one provider: the newest window per label, at most MAX_WINDOWS."""
    kept = {}
    if isinstance(previous, dict):
        for window in previous.get('windows') or []:
            if isinstance(window, dict) and isinstance(window.get('label'), str):
                kept[window['label']] = window
    for window in windows:
        kept[window['label']] = window
    return {'at': at, 'windows': list(kept.values())[-MAX_WINDOWS:]}


def public(state):
    """`state.provider_limits` for the UI: only well-formed readings of known providers."""
    stored = state.get('provider_limits')
    if not isinstance(stored, dict):
        return {}
    return {name: {'at': value.get('at'), 'windows': [dict(w) for w in value.get('windows') or [] if isinstance(w, dict)]}
            for name, value in stored.items() if name in READERS and isinstance(value, dict)}
