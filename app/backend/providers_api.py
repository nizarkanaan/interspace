"""Backend methods for agent providers and routing defaults (multi-provider/providers.md, "Sign-in").

`service.extension_methods` registers METHODS; each handler is `(app, params)` and runs on the request pool,
never in a run slot. Runtime answers are filtered to the contract fields here, so no token, credential path or
account detail beyond the display name can reach the UI.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import re
import threading

import codex_auth
import routing
from runtime import registry
from runtime.claude import DEFAULT_EFFORT

STATES = ('signed_in', 'signed_out', 'missing_cli', 'error')
URL_RE = re.compile(r'https://[A-Za-z0-9.-]+(/[A-Za-z0-9._~/%?=&-]*)?\Z')
TERMINAL_COMMANDS = ('claude auth login',)  # Instructions the UI may show; anything else is refused.
MAX_TEXT = 300


def _text(value, limit=MAX_TEXT):
    return value[:limit] if isinstance(value, str) else ''


def _provider(params):
    return registry.get(params.get('provider'))['name']


def _error(name, detail):
    return {'provider': name, 'state': 'error', 'account': None, 'detail': detail}


def _status(app, name):
    title = registry.get(name)['title']
    try:
        result = registry.runtime_class(name).auth_status(app)
    except ValueError as error:
        return _error(name, _text(str(error)))
    except Exception:
        return _error(name, title + ' could not report its sign-in. Check its installation.')
    return _clean(name, result) or _error(name, title + ' sent a sign-in status Interspace does not understand.')


def _clean(name, result):
    """A runtime's `auth_status`-shaped answer cut to the contract fields, or None when it is not one."""
    if not isinstance(result, dict) or result.get('provider') != name or result.get('state') not in STATES:
        return None
    account = result.get('account')
    return {'provider': name, 'state': result['state'],
            'account': account[:120] if isinstance(account, str) and account else None,
            'detail': _text(result.get('detail'))}


def providers_list(app, params):
    names = registry.names()
    with ThreadPoolExecutor(max_workers=max(1, len(names)), thread_name_prefix='provider-status') as pool:
        status = list(pool.map(lambda name: _status(app, name), names))
    with app.lock:
        current = routing.current(app.state)
    return {'providers': registry.public(), 'status': status, 'routing': current}


_last_state = {}  # provider name -> the sign-in state its last status reported.


def provider_status(app, params):
    name = _provider(params)
    status = _status(app, name)
    with _models_lock:
        previous = _last_state.get(name)
        _last_state[name] = status['state']
        if previous is not None and previous != status['state']:
            _models_cache.pop(name, None)
    return status


_models_lock = threading.Lock()
_models_cache = {}  # provider name -> a success or the signed-out answer, until sign-in or sign-out clears it.


def clear_models_cache(name=None):
    with _models_lock:
        if name is None:
            _models_cache.clear()
        else:
            _models_cache.pop(name, None)


def _claude_models(record):
    return [{'id': model, 'is_default': model == record['default_model'], 'default_effort': DEFAULT_EFFORT,
             'efforts': list(record['efforts'])} for model in record['models']]


def provider_models(app, params):
    """The models and efforts a provider's pickers offer: Claude from the registry, Codex live and cached."""
    name = _provider(params)
    record = registry.get(name)
    if record['models']:
        return {'provider': name, 'models': _claude_models(record), 'error': ''}
    with _models_lock:  # Held while Codex answers (at most 10 s), so renders share one process.
        cached = _models_cache.get(name)
        if cached is None:
            keep = True  # Timeouts and start failures are never kept; the next render asks again.
            try:
                models = registry.runtime_class(name).models(app)
                cached = {'provider': name, 'error': '', 'models': [
                    {'id': m['id'], 'is_default': m['is_default'] is True, 'default_effort': m['default_effort'],
                     'efforts': list(m['efforts'])} for m in models]}
            except ValueError as error:
                cached = {'provider': name, 'models': [], 'error': _text(str(error))}
                keep = str(error) == codex_auth.SIGNED_OUT_MODELS
            except Exception:
                cached = {'provider': name, 'models': [],
                          'error': record['title'] + ' could not list its models. Check its installation.'}
                keep = False
            if keep:
                _models_cache[name] = cached
        return copy.deepcopy(cached)


def _remember(app, status):
    """Put a provider's latest status in the published state (`provider_status`), so the UI learns it there."""
    with app.lock:
        app.state.setdefault('provider_status', {})[status['provider']] = copy.deepcopy(status)
        app.publish()


def _finished(app, name):
    """A device sign-in ended (succeeded, failed or expired): read the status again and publish it."""
    def report(outcome):
        clear_models_cache(name)
        _remember(app, _status(app, name))
    return report


def provider_sign_in(app, params):
    name = _provider(params)
    title = registry.get(name)['title']
    try:
        result = registry.runtime_class(name).begin_sign_in(app, on_finish=_finished(app, name))
    except ValueError as error:
        raise ValueError(_text(str(error)) or title + ' sign-in could not start.') from None
    except Exception:
        raise ValueError(title + ' sign-in could not start. Check its installation.') from None
    kind = result.get('kind') if isinstance(result, dict) else None
    if kind == 'device':
        url, code = result.get('url'), result.get('code')
        if isinstance(url, str) and URL_RE.match(url) and len(url) <= 300 \
                and (code is None or (isinstance(code, str) and 0 < len(code) <= 40)):
            return {'provider': name, 'kind': 'device', 'url': url, 'code': code, 'detail': _text(result.get('detail'))}
    elif kind == 'terminal':
        if result.get('command') in TERMINAL_COMMANDS:
            return {'provider': name, 'kind': 'terminal', 'command': result['command'],
                    'detail': _text(result.get('detail'))}
    raise ValueError(title + ' sent a sign-in step Interspace does not understand.')


SIGN_OUT_ELSEWHERE = {'claude': 'Claude uses your own Claude Code sign-in. To sign out, run claude auth logout in Terminal.'}


def provider_sign_out(app, params):
    """Sign a provider's app-owned sign-in out; returns the `auth_status` shape and publishes it."""
    name = _provider(params)
    title = registry.get(name)['title']
    try:
        runtime = registry.runtime_class(name)
    except ValueError as error:
        raise ValueError(_text(str(error))) from None
    if not callable(getattr(runtime, 'sign_out', None)):
        raise ValueError(SIGN_OUT_ELSEWHERE.get(name, title + ' has no sign-out in Interspace.'))
    try:
        result = runtime.sign_out(app)
    except ValueError as error:
        raise ValueError(_text(str(error)) or title + ' could not sign out.') from None
    except Exception:
        raise ValueError(title + ' could not sign out. Check its installation.') from None
    clear_models_cache(name)
    status = _clean(name, result)
    if status is None:
        raise ValueError(title + ' sent a sign-in status Interspace does not understand.')
    _remember(app, status)
    return status


def routing_update(app, params):
    checked = routing.validate(params.get('routing'))
    with app.lock:
        app.state['routing'] = copy.deepcopy(checked)
        app.publish()
    return checked


METHODS = {
    'providers_list': providers_list,
    'provider_sign_in': provider_sign_in,
    'provider_models': provider_models,
    'provider_sign_out': provider_sign_out,
    'provider_status': provider_status,
    'routing_update': routing_update,
}
