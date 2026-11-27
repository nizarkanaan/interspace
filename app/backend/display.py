"""Conversation display preferences (docs/superpowers/specs/2026-11-20-details-panel-and-display-design.md).

Stored in `state['display']`; the defaults apply while nothing valid is stored. They only change what the UI shows:
every event is still recorded in full.
"""
import copy

LEVELS = ('summary', 'full', 'hidden')
DETAILS = ('simple', 'detailed')
SWITCHES = ('tools', 'citations', 'plans', 'notes')


def default():
    return {'v': 1, 'thinking': 'summary', 'searches': 'summary', 'tools': True, 'citations': True, 'plans': True,
            'notes': True, 'detail': 'simple'}


def validate(value):
    if not isinstance(value, dict):
        raise ValueError('Display settings must be an object.')
    unknown = set(value) - set(default())
    if unknown:
        raise ValueError('Unknown display setting: ' + sorted(unknown)[0] + '.')
    checked = default()
    for key in ('thinking', 'searches'):
        if key in value:
            if value[key] not in LEVELS:
                raise ValueError(key.capitalize() + ' must be summary, full or hidden.')
            checked[key] = value[key]
    if 'detail' in value:
        if value['detail'] not in DETAILS:
            raise ValueError('Detail must be simple or detailed.')
        checked['detail'] = value['detail']
    for key in SWITCHES:
        if key in value:
            if not isinstance(value[key], bool):
                raise ValueError(key.capitalize() + ' must be on or off.')
            checked[key] = value[key]
    return checked


def current(state):
    try:
        return validate(copy.deepcopy(state.get('display')))
    except ValueError:
        return default()


def display_update(app, params):
    """`{display}` -> the stored display settings."""
    checked = validate(params.get('display'))
    with app.lock:
        app.state['display'] = copy.deepcopy(checked)
        app.publish()
    return checked


METHODS = {'display_update': display_update}
