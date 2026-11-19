"""Research API keys and contact emails in the macOS Keychain (docs/superpowers/specs/research/credentials.md).

Secrets travel only through the Swift bridge (`bridge.Bridge`, service `app.interspace.research`). They are held
in memory for at most ten minutes and are never logged, audited, persisted, returned to the UI or put in an error
message. Only the source clients read them, with `get`.
"""
import re
import threading
import time

# Keychain account -> credential kind. Swift keeps the same allowlist and refuses any other account.
ACCOUNTS = {'semantic_scholar': 'api_key', 'openalex': 'api_key',
            'crossref_email': 'email', 'unpaywall_email': 'email'}
CACHE_TTL_S = 600
KEYCHAIN_TIMEOUT_S = 10
API_KEY_RE = re.compile(r'[\x21-\x7e]{8,256}\Z')  # printable ASCII, no spaces
EMAIL_RE = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+\Z")
MAX_EMAIL = 254


class CredentialStoreUnavailable(ValueError):
    """The Keychain cannot be used right now. The message is safe to show and never holds a secret."""


class _NoBridge:
    ready = False

    def keychain(self, op, account, secret=None, timeout_s=KEYCHAIN_TIMEOUT_S):
        return None


class Credentials:
    """`channel` is a `bridge.Bridge` (or a fake): `ready` and `keychain(op, account, secret, timeout_s)`."""

    def __init__(self, channel, timeout_s=KEYCHAIN_TIMEOUT_S, *, clock=time.monotonic):
        self._channel = channel
        self._timeout_s = timeout_s
        self._clock = clock
        self._lock = threading.Lock()
        self._cache = {}  # account -> (secret or None, read at)

    def get(self, account):
        """The stored secret, or None when it is not set."""
        _account(account)
        with self._lock:
            cached = self._cache.get(account)
        if cached is not None and self._clock() - cached[1] < CACHE_TTL_S:
            return cached[0]
        reply = self._call('read', account)
        secret = reply.get('secret') if reply is not None else None
        if reply is not None and not isinstance(secret, str):
            raise CredentialStoreUnavailable('The Keychain sent an answer Interspace does not understand. Try again.')
        with self._lock:
            self._cache[account] = (secret, self._clock())
        return secret

    def set(self, account, secret):
        kind = _account(account)
        secret = _validated(kind, secret)
        with self._lock:
            self._cache.pop(account, None)
        if self._call('write', account, secret) is None:
            raise CredentialStoreUnavailable('The Keychain could not store it. Try again.')

    def delete(self, account):
        _account(account)
        with self._lock:
            self._cache.pop(account, None)
        self._call('delete', account)  # not_found means it is already gone

    def configured(self, account):
        return self.get(account) is not None

    def clear(self):
        """Drops every cached secret (shutdown)."""
        with self._lock:
            self._cache.clear()

    def _call(self, op, account, secret=None):
        """The `ok` reply, None for `not_found`, or CredentialStoreUnavailable."""
        if not self._channel.ready:
            raise CredentialStoreUnavailable('Interspace cannot reach the Keychain. Restart the app and try again.')
        reply = self._channel.keychain(op, account, secret, timeout_s=self._timeout_s)
        if not isinstance(reply, dict):
            raise CredentialStoreUnavailable('The Keychain did not answer. Try again.')
        if reply.get('ok') is True:
            return reply
        error = reply.get('error')
        if error == 'not_found':
            return None
        if error == 'denied':
            raise CredentialStoreUnavailable('Interspace was not allowed to use the Keychain. Allow access and try again.')
        raise CredentialStoreUnavailable('The Keychain is unavailable. Try again.')


def _account(account):
    kind = ACCOUNTS.get(account) if isinstance(account, str) else None
    if kind is None:
        raise ValueError('Unknown research credential.')
    return kind


def _validated(kind, secret):
    """The secret without surrounding whitespace, or ValueError with a message that never repeats it."""
    value = secret.strip() if isinstance(secret, str) else None
    if kind == 'email':
        if value is None or len(value) > MAX_EMAIL or not EMAIL_RE.match(value):
            raise ValueError('Enter a valid email address.')
    elif value is None or not API_KEY_RE.match(value):
        raise ValueError('An API key is 8 to 256 printable characters without spaces.')
    return value


_for_app_lock = threading.Lock()


def for_app(app):
    """The one `Credentials` store of an `Application`, on its bridge (unavailable when it has none)."""
    with _for_app_lock:
        store = getattr(app, 'research_credentials', None)
        if store is None:
            store = Credentials(getattr(app, 'bridge', None) or _NoBridge())
            app.research_credentials = store
        return store
