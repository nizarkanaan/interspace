"""Shared time helpers: ISO 8601 UTC with milliseconds and a Z suffix (README conventions)."""
import calendar
from datetime import datetime
import time


def iso_time(t):
    """Epoch seconds as ISO 8601 UTC with milliseconds and a Z suffix."""
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(t)) + '.%03dZ' % int(t % 1 * 1000)


def parse_time(text):
    """ISO 8601 date-time with a Z or numeric offset, as epoch seconds. Raises ValueError otherwise."""
    if not isinstance(text, str) or 'T' not in text:
        raise ValueError('The time could not be read.')
    candidate = text[:-1] + '+00:00' if text.endswith('Z') else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        parsed = None
    if parsed is None or parsed.tzinfo is None:
        raise ValueError('The time could not be read.')
    return calendar.timegm(parsed.utctimetuple()) + parsed.microsecond / 1e6
