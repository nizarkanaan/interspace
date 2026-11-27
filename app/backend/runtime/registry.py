"""Provider registry: one record per agent provider (docs/superpowers/specs/multi-provider/providers.md).

It replaces the hard-coded provider tuples in the runtime factory, the task rows and the budget charge rules.
Records are plain data; the runtime class named by `runtime` ('module:Class') is imported only when asked for.
A later provider (Gemini) is one more `register(record)` and one adapter module.
"""
import copy
import importlib
import re
import threading

MODEL_RE = r'[A-Za-z0-9._:-]{1,64}\Z'
EFFORT_RE = r'[a-z]{1,16}\Z'
NAME_RE = r'[a-z][a-z0-9_]{0,31}\Z'
CAPABILITIES = ('write', 'web_search', 'approvals')

PROVIDERS = {
    'claude': {
        'name': 'claude', 'title': 'Claude',
        'models': ('claude-sonnet-5-5', 'claude-opus-5-5', 'claude-haiku-5-5'),  # Full IDs only, never aliases.
        'default_model': 'claude-sonnet-5-5',
        'efforts': ('low', 'medium', 'high', 'xhigh', 'max'),
        'capabilities': {'write': True, 'web_search': True, 'approvals': True},
        # Anthropic's input_tokens excludes cache writes and reads, so the four counts are disjoint.
        'charge_fields': ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens'),
        'runtime': 'runtime.claude:ClaudeRuntime',
    },
    'codex': {
        'name': 'codex', 'title': 'Codex',
        'models': (),          # Empty: a free-text model name, checked by MODEL_RE.
        'default_model': None,  # None: the CLI's own default.
        'efforts': (),          # Empty: a free-text effort word, checked by EFFORT_RE.
        'capabilities': {'write': True, 'web_search': True, 'approvals': True},
        # Codex TokenUsage: cached input is part of input_tokens and reasoning is part of output_tokens.
        'charge_fields': ('input_tokens', 'output_tokens'),
        'runtime': 'runtime.codex:CodexRuntime',
    },
}
DEFAULT_PROVIDER = 'claude'

_lock = threading.Lock()


def _model_ok(model):
    return isinstance(model, str) and re.match(MODEL_RE, model) is not None


def _effort_ok(effort):
    return isinstance(effort, str) and re.match(EFFORT_RE, effort) is not None


def _check_record(record):
    """The record as stored (tuples, copied), or ValueError naming what is wrong."""
    if not isinstance(record, dict):
        raise ValueError('A provider record must be an object.')
    name = record.get('name')
    if not isinstance(name, str) or not re.match(NAME_RE, name):
        raise ValueError('A provider needs a lower-case name.')
    title = record.get('title')
    if not isinstance(title, str) or not title.strip() or len(title) > 40:
        raise ValueError('A provider needs a title.')
    models = record.get('models')
    if not isinstance(models, (tuple, list)) or not all(_model_ok(m) for m in models) or len(set(models)) != len(models):
        raise ValueError('Provider models must be distinct model names.')
    default = record.get('default_model')
    if default is not None and (not _model_ok(default) or (models and default not in models)):
        raise ValueError('The default model must be one of the provider models.')
    efforts = record.get('efforts', ())
    if not isinstance(efforts, (tuple, list)) or not all(_effort_ok(e) for e in efforts) or len(set(efforts)) != len(efforts):
        raise ValueError('Provider efforts must be distinct short lowercase words.')
    capabilities = record.get('capabilities')
    if not isinstance(capabilities, dict) or set(capabilities) != set(CAPABILITIES) \
            or not all(type(v) is bool for v in capabilities.values()):
        raise ValueError('Provider capabilities must say write, web_search and approvals.')
    fields = record.get('charge_fields')
    if not isinstance(fields, (tuple, list)) or not fields or not all(isinstance(f, str) and f for f in fields):
        raise ValueError('A provider without charge_fields cannot be registered.')
    runtime = record.get('runtime')
    if not isinstance(runtime, str) or runtime.count(':') != 1 or not all(runtime.split(':')):
        raise ValueError("A provider runtime must be 'module:Class'.")
    return {'name': name, 'title': title, 'models': tuple(models), 'default_model': default,
            'efforts': tuple(efforts), 'capabilities': dict(capabilities), 'charge_fields': tuple(fields), 'runtime': runtime}


for _record in PROVIDERS.values():
    _check_record(_record)


def register(record):
    """Add a provider at the end of the registry order."""
    checked = _check_record(record)
    with _lock:
        if checked['name'] in PROVIDERS:
            raise ValueError('That provider is already registered.')
        PROVIDERS[checked['name']] = checked


def unregister(name):
    """Remove a provider added with `register` (tests). The built-in providers stay."""
    if name in ('claude', 'codex'):
        raise ValueError('Built-in providers cannot be removed.')
    with _lock:
        PROVIDERS.pop(name, None)


def get(name):
    record = PROVIDERS.get(name) if isinstance(name, str) else None
    if record is None:
        raise ValueError('Unknown provider.')
    return copy.deepcopy(record)


def names():
    return tuple(PROVIDERS)


def runtime_class(name):
    """The provider's runtime class, imported now. ValueError when it is not in this build."""
    module_name, class_name = get(name)['runtime'].split(':')
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        raise ValueError('The ' + get(name)['title'] + ' runtime is not in this build yet.') from None
    found = getattr(module, class_name, None)
    if found is None:
        raise ValueError('The ' + get(name)['title'] + ' runtime is not in this build yet.')
    return found


def check_model(name, model):
    """The model to run: `model` when the provider accepts it, the provider default for None."""
    record = get(name)
    if model is None:
        return record['default_model']
    if record['models']:
        if model not in record['models']:
            raise ValueError('Choose one of the ' + record['title'] + ' models.')
        return model
    if not _model_ok(model):
        raise ValueError('The model must be a name of at most 64 letters, digits and . _ : -.')
    return model


def check_effort(name, effort):
    """The effort to run: None passes through; otherwise one of the provider's levels, or a short word if it lists none."""
    record = get(name)
    if effort is None:
        return None
    if record['efforts']:
        if effort not in record['efforts']:
            raise ValueError('Choose one of the ' + record['title'] + ' effort levels.')
        return effort
    if not _effort_ok(effort):
        raise ValueError('The effort must be a short lowercase word.')
    return effort


def charge_rule(name):
    """A short label for the provider's charge rule, kept on each ledger entry: 'codex.input+output'."""
    parts = []
    for field in get(name)['charge_fields']:
        for suffix in ('_input_tokens', '_tokens'):
            if field.endswith(suffix) and field != suffix[1:]:
                field = field[:-len(suffix)]
                break
        parts.append(field)
    return name + '.' + '+'.join(parts)


def public():
    """JSON-safe provider list for the UI."""
    return [{'name': r['name'], 'title': r['title'], 'models': list(r['models']), 'default_model': r['default_model'],
             'capabilities': dict(r['capabilities'])} for r in (get(n) for n in names())]
