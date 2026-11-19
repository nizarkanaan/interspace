"""Routing defaults: which provider and model each role uses (multi-provider/providers.md).

Stored in `state['routing']`. The defaults below apply while nothing valid is stored; the user may change them.
"""
import copy

from runtime import registry

ROLES = ('researcher', 'implementer', 'reviewer', 'tester', 'writer', 'citation_checker')
WRITE_ROLES = ('implementer', 'tester')  # These need a provider with `capabilities.write`.

DEFAULT_ROUTING = {
    'v': 1, 'orchestrator': {'provider': 'claude', 'model': None},
    'roles': {'researcher': {'provider': 'codex', 'model': None},
              'implementer': {'provider': 'claude', 'model': None},
              'reviewer': {'provider': 'codex', 'model': None},
              'tester': {'provider': 'claude', 'model': None},
              'writer': {'provider': 'claude', 'model': None},
              'citation_checker': {'provider': 'codex', 'model': None}},
}


def default():
    return copy.deepcopy(DEFAULT_ROUTING)


def _choice(value, label, write=False):
    if not isinstance(value, dict) or set(value) != {'provider', 'model'}:
        raise ValueError('Routing for ' + label + ' needs a provider and a model.')
    provider, model = value['provider'], value['model']
    record = registry.get(provider)
    if model is not None:
        registry.check_model(provider, model)
    if write and not record['capabilities']['write']:
        raise ValueError(record['title'] + ' cannot write files, so it cannot be the ' + label + '.')
    return {'provider': provider, 'model': model}


def validate(value):
    """A clean copy of a routing document, or ValueError with a message safe to show.

    A stored `model` of None means the provider's default at run time, so it is kept as None.
    """
    if not isinstance(value, dict):
        raise ValueError('Routing must be an object.')
    if value.get('v', 1) != 1 or set(value) - {'v', 'orchestrator', 'roles'}:
        raise ValueError('Routing has fields this version does not know.')
    roles = value.get('roles')
    if not isinstance(roles, dict) or set(roles) - set(ROLES):
        raise ValueError('Routing must name a provider for each role: ' + ', '.join(ROLES) + '.')
    # Routing saved before a role existed (citation_checker, research/tasks.md) is completed from the defaults.
    roles = dict({role: DEFAULT_ROUTING['roles'][role] for role in ROLES if role not in roles}, **roles)
    return {'v': 1, 'orchestrator': _choice(value.get('orchestrator'), 'orchestrator'),
            'roles': {role: _choice(roles[role], role, role in WRITE_ROLES) for role in ROLES}}


def current(state):
    """The stored routing when it is still valid (a provider may have gone), else the defaults."""
    try:
        return validate(state.get('routing'))
    except ValueError:
        return default()
