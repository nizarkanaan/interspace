"""The backend side of the Swift bridge (docs/superpowers/specs/research/credentials.md).

Swift sends `bridge_hello` as the first stdin line. The backend then writes `keychain` and `save_panel` lines to
stdout; Swift consumes them before anything reaches the WebView and answers on stdin with `keychain_reply` and
`save_panel_reply`. `service.Router` hands those three message types to `Bridge.deliver`.

A request blocks its own thread until the matching reply arrives, the timeout passes or the bridge closes. Replies
are matched by id and kind; anything else is ignored. Nothing here logs, and secrets only pass through.
"""
import threading
import uuid

KEYCHAIN_OPS = ('read', 'write', 'delete')
KEYCHAIN_TIMEOUT_S = 10
SAVE_PANEL_TIMEOUT_S = 600  # The user is choosing a place to save.
MAX_NAME = 255
REPLY_TYPES = {'keychain_reply': 'kc-', 'save_panel_reply': 'sp-'}


class Bridge:
    def __init__(self, emit):
        self._emit = emit
        self._lock = threading.Lock()
        self._pending = {}  # id -> [threading.Event, reply or None]
        self._keychain = False
        self._save_panel = False

    @property
    def ready(self):
        """True once Swift's handshake said it handles Keychain requests."""
        return self._keychain

    def deliver(self, message):
        """One `bridge_hello`, `keychain_reply` or `save_panel_reply` line from Swift."""
        if not isinstance(message, dict):
            return
        kind = message.get('type')
        if kind == 'bridge_hello':
            with self._lock:
                self._keychain = message.get('keychain') == 1
                self._save_panel = message.get('save_panel') == 1
            return
        prefix = REPLY_TYPES.get(kind)
        identity = message.get('id')
        if prefix is None or not isinstance(identity, str) or not identity.startswith(prefix):
            return
        with self._lock:
            slot = self._pending.pop(identity, None)
        if slot is not None:
            slot[1] = message
            slot[0].set()

    def keychain(self, op, account, secret=None, timeout_s=KEYCHAIN_TIMEOUT_S):
        """Swift's `keychain_reply` dict, or None when there is no handshake, no reply in time or the bridge closed."""
        if op not in KEYCHAIN_OPS or not isinstance(account, str) or not account:
            raise ValueError('Unsupported Keychain request.')
        if op == 'write' and not isinstance(secret, str):
            raise ValueError('Unsupported Keychain request.')
        if not self._keychain:
            return None
        message = {'type': 'keychain', 'id': 'kc-' + uuid.uuid4().hex, 'op': op, 'account': account}
        if op == 'write':
            message['secret'] = secret
        return self._exchange(message, timeout_s)

    def save_panel(self, path, suggested_name, timeout_s=SAVE_PANEL_TIMEOUT_S):
        """Asks Swift to copy `path` (inside app data; Swift checks) to where the user picks. The reply, or None."""
        if not isinstance(path, str) or not path.startswith('/'):
            raise ValueError('Unsupported save request.')
        if (not isinstance(suggested_name, str) or not suggested_name or len(suggested_name) > MAX_NAME
                or '/' in suggested_name or suggested_name in ('.', '..')):
            raise ValueError('Unsupported save request.')
        if not self._save_panel:
            return None
        message = {'type': 'save_panel', 'id': 'sp-' + uuid.uuid4().hex, 'suggested_name': suggested_name,
                   'path': path}
        return self._exchange(message, timeout_s)

    def close(self):
        """Shutdown: forget the handshake and release every waiting request with no reply."""
        with self._lock:
            self._keychain = self._save_panel = False
            pending, self._pending = self._pending, {}
        for slot in pending.values():
            slot[0].set()

    def _exchange(self, message, timeout_s):
        slot = [threading.Event(), None]
        with self._lock:
            self._pending[message['id']] = slot
        try:
            self._emit(message)
            slot[0].wait(timeout_s)
        finally:
            with self._lock:
                self._pending.pop(message['id'], None)
        return slot[1]
