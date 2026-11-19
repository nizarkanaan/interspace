"""Research credentials through a fake Keychain channel (research/credentials.md). Never the real Keychain."""
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))

from research import credentials  # noqa: E402

KEY = 'fake-openalex-key-0123456789'
EMAIL = 'someone@example.org'


class FakeChannel:
    """The `bridge.Bridge` surface, backed by a dict. `error` makes every request fail with that Keychain error."""

    def __init__(self, ready=True):
        self.ready = ready
        self.items = {}
        self.calls = []
        self.error = None
        self.silent = False

    def keychain(self, op, account, secret=None, timeout_s=10):
        self.calls.append((op, account))
        if self.silent:
            return None
        reply = {'type': 'keychain_reply', 'id': 'kc-1'}
        if self.error:
            return dict(reply, ok=False, error=self.error)
        if op == 'write':
            self.items[account] = secret
            return dict(reply, ok=True)
        if account not in self.items:
            return dict(reply, ok=False, error='not_found')
        if op == 'delete':
            del self.items[account]
            return dict(reply, ok=True)
        return dict(reply, ok=True, secret=self.items[account])


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def store(channel=None, clock=None):
    return credentials.Credentials(channel or FakeChannel(), clock=clock or Clock())


class ValidationTests(unittest.TestCase):
    def test_only_the_four_accounts_are_allowed(self):
        self.assertEqual(set(credentials.ACCOUNTS),
                         {'semantic_scholar', 'openalex', 'crossref_email', 'unpaywall_email'})
        creds = store()
        for method, args in (('get', ()), ('delete', ()), ('configured', ()), ('set', (KEY,))):
            with self.assertRaises(ValueError):
                getattr(creds, method)('github', *args)

    def test_api_keys_are_8_to_256_printable_characters(self):
        creds = store()
        for bad in ('short', 'x' * 257, 'has space inside', 'tab\there12', 'é' * 10, '', None, 12345678):
            with self.assertRaises(ValueError):
                creds.set('openalex', bad)
        creds.set('openalex', 'x' * 8)
        creds.set('semantic_scholar', '  ' + 'y' * 256 + '\n')  # surrounding whitespace from a paste is dropped
        self.assertEqual(creds.get('semantic_scholar'), 'y' * 256)

    def test_emails_are_rfc_ish_and_at_most_254(self):
        creds = store()
        for bad in ('no-at-sign', 'two@@example.org', 'a@b', 'sp ace@example.org', '@example.org',
                    'a@' + 'x' * 250 + '.org', KEY):
            with self.assertRaises(ValueError):
                creds.set('unpaywall_email', bad)
        creds.set('crossref_email', EMAIL)
        self.assertEqual(creds.get('crossref_email'), EMAIL)

    def test_validation_errors_never_contain_the_value(self):
        creds = store()
        for account, bad in (('openalex', 'bad key with spaces 1234'), ('unpaywall_email', 'private-name@nowhere')):
            with self.assertRaises(ValueError) as caught:
                creds.set(account, bad)
            self.assertNotIn(bad, str(caught.exception))
            self.assertNotIn('private-name', str(caught.exception))


class StoreTests(unittest.TestCase):
    def test_set_get_delete_round_trip(self):
        channel = FakeChannel()
        creds = store(channel)
        self.assertIsNone(creds.get('openalex'))
        self.assertFalse(creds.configured('openalex'))
        creds.set('openalex', KEY)
        self.assertEqual(channel.items, {'openalex': KEY})
        self.assertTrue(creds.configured('openalex'))
        self.assertEqual(creds.get('openalex'), KEY)
        creds.delete('openalex')
        self.assertEqual(channel.items, {})
        self.assertIsNone(creds.get('openalex'))
        creds.delete('openalex')  # already gone is fine

    def test_reads_are_cached_for_ten_minutes(self):
        channel, clock = FakeChannel(), Clock()
        channel.items['openalex'] = KEY
        creds = store(channel, clock)
        creds.get('openalex')
        creds.configured('openalex')
        clock.now += 599
        creds.get('openalex')
        self.assertEqual(channel.calls, [('read', 'openalex')])
        clock.now += 2
        creds.get('openalex')
        self.assertEqual(channel.calls, [('read', 'openalex')] * 2)

    def test_set_and_delete_drop_the_cache(self):
        channel = FakeChannel()
        creds = store(channel)
        creds.set('openalex', KEY)
        self.assertEqual(creds.get('openalex'), KEY)
        channel.items['openalex'] = 'changed-elsewhere-123'
        creds.set('openalex', 'second-key-12345')
        self.assertEqual(creds.get('openalex'), 'second-key-12345')
        creds.delete('openalex')
        self.assertFalse(creds.configured('openalex'))

    def test_clear_drops_every_cached_secret(self):
        channel = FakeChannel()
        channel.items['openalex'] = KEY
        creds = store(channel)
        creds.get('openalex')
        creds.clear()
        self.assertEqual(creds._cache, {})
        creds.get('openalex')
        self.assertEqual(len(channel.calls), 2)


class UnavailableTests(unittest.TestCase):
    def assert_unavailable(self, channel):
        creds = store(channel)
        for call in (lambda: creds.get('openalex'), lambda: creds.configured('openalex'),
                     lambda: creds.set('openalex', KEY), lambda: creds.delete('openalex')):
            with self.assertRaises(credentials.CredentialStoreUnavailable) as caught:
                call()
            self.assertIsInstance(caught.exception, ValueError)
            self.assertNotIn(KEY, str(caught.exception))

    def test_no_handshake(self):
        channel = FakeChannel(ready=False)
        self.assert_unavailable(channel)
        self.assertEqual(channel.calls, [])

    def test_timeout(self):
        channel = FakeChannel()
        channel.silent = True
        self.assert_unavailable(channel)

    def test_denied_and_unavailable(self):
        for error in ('denied', 'unavailable', 'something_new'):
            channel = FakeChannel()
            channel.error = error
            self.assert_unavailable(channel)

    def test_a_failed_read_is_not_cached_as_missing(self):
        channel = FakeChannel()
        creds = store(channel)
        channel.error = 'denied'
        with self.assertRaises(credentials.CredentialStoreUnavailable):
            creds.get('openalex')
        channel.error = None
        channel.items['openalex'] = KEY
        self.assertEqual(creds.get('openalex'), KEY)


class ForAppTests(unittest.TestCase):
    def test_one_store_per_app_on_its_bridge(self):
        channel = FakeChannel()
        app = types.SimpleNamespace(bridge=channel)
        first = credentials.for_app(app)
        self.assertIs(first, credentials.for_app(app))
        first.set('openalex', KEY)
        self.assertEqual(channel.items, {'openalex': KEY})

    def test_an_app_without_a_bridge_is_unavailable(self):
        creds = credentials.for_app(types.SimpleNamespace(bridge=None))
        with self.assertRaises(credentials.CredentialStoreUnavailable):
            creds.get('openalex')


if __name__ == '__main__':
    unittest.main()
