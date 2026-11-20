"""The backend side of the Swift bridge (research/credentials.md): handshake, Keychain and save-panel requests."""
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))

import bridge  # noqa: E402

HELLO = {'type': 'bridge_hello', 'keychain': 1, 'save_panel': 1}


class FakeSwift:
    """Captures what the backend writes to stdout and answers the way the Swift shell would, on another thread."""

    def __init__(self, answer=None):
        self.sent = []
        self.answer = answer
        self.bridge = bridge.Bridge(self.emit)

    def emit(self, message):
        self.sent.append(message)
        if self.answer is not None:
            reply = self.answer(message)
            if reply is not None:
                threading.Thread(target=self.bridge.deliver, args=(reply,)).start()


class HandshakeTests(unittest.TestCase):
    def test_not_ready_until_bridge_hello_with_keychain_support(self):
        swift = FakeSwift()
        self.assertFalse(swift.bridge.ready)
        swift.bridge.deliver({'type': 'bridge_hello', 'keychain': 0})
        self.assertFalse(swift.bridge.ready)
        swift.bridge.deliver(HELLO)
        self.assertTrue(swift.bridge.ready)

    def test_requests_before_the_handshake_send_nothing(self):
        swift = FakeSwift()
        self.assertIsNone(swift.bridge.keychain('read', 'openalex', timeout_s=0.05))
        self.assertIsNone(swift.bridge.save_panel('/tmp/x.bib', 'x.bib', timeout_s=0.05))
        self.assertEqual(swift.sent, [])

    def test_save_panel_needs_its_own_handshake_flag(self):
        swift = FakeSwift()
        swift.bridge.deliver({'type': 'bridge_hello', 'keychain': 1})
        self.assertTrue(swift.bridge.ready)
        self.assertIsNone(swift.bridge.save_panel('/tmp/x.bib', 'x.bib', timeout_s=0.05))
        self.assertEqual(swift.sent, [])


class KeychainTests(unittest.TestCase):
    def test_read_sends_the_contract_message_and_returns_the_matching_reply(self):
        swift = FakeSwift(lambda m: {'type': 'keychain_reply', 'id': m['id'], 'ok': True, 'secret': 'fake-key-123'})
        swift.bridge.deliver(HELLO)
        reply = swift.bridge.keychain('read', 'openalex')
        self.assertEqual(reply['secret'], 'fake-key-123')
        sent = swift.sent[0]
        self.assertEqual(set(sent), {'type', 'id', 'op', 'account'})
        self.assertEqual((sent['type'], sent['op'], sent['account']), ('keychain', 'read', 'openalex'))
        self.assertTrue(sent['id'].startswith('kc-'))
        self.assertLessEqual(len(sent['id']), 64)

    def test_secret_is_sent_only_on_write(self):
        swift = FakeSwift(lambda m: {'type': 'keychain_reply', 'id': m['id'], 'ok': True})
        swift.bridge.deliver(HELLO)
        swift.bridge.keychain('write', 'openalex', 'fake-key-123')
        swift.bridge.keychain('delete', 'openalex', 'ignored')
        self.assertEqual(swift.sent[0]['secret'], 'fake-key-123')
        self.assertNotIn('secret', swift.sent[1])

    def test_ids_are_unique(self):
        swift = FakeSwift(lambda m: {'type': 'keychain_reply', 'id': m['id'], 'ok': True})
        swift.bridge.deliver(HELLO)
        for _ in range(5):
            swift.bridge.keychain('read', 'openalex')
        self.assertEqual(len({m['id'] for m in swift.sent}), 5)

    def test_timeout_returns_none_and_a_late_reply_is_ignored(self):
        swift = FakeSwift()
        swift.bridge.deliver(HELLO)
        self.assertIsNone(swift.bridge.keychain('read', 'openalex', timeout_s=0.05))
        swift.bridge.deliver({'type': 'keychain_reply', 'id': swift.sent[0]['id'], 'ok': True, 'secret': 'late'})
        self.assertEqual(swift.bridge._pending, {})

    def test_replies_with_unknown_or_wrong_kind_ids_are_ignored(self):
        def answer(message):
            # A save-panel reply carrying the keychain id, then an unknown id: neither may answer the request.
            swift.bridge.deliver({'type': 'save_panel_reply', 'id': message['id'], 'ok': True})
            swift.bridge.deliver({'type': 'keychain_reply', 'id': 'kc-unknown', 'ok': True, 'secret': 'x'})
            return None
        swift = FakeSwift(answer)
        swift.bridge.deliver(HELLO)
        self.assertIsNone(swift.bridge.keychain('read', 'openalex', timeout_s=0.1))

    def test_bad_requests_are_refused_without_sending(self):
        swift = FakeSwift()
        swift.bridge.deliver(HELLO)
        for op, account in (('list', 'openalex'), ('read', ''), ('read', None)):
            with self.assertRaises(ValueError):
                swift.bridge.keychain(op, account)
        with self.assertRaises(ValueError):
            swift.bridge.keychain('write', 'openalex')
        self.assertEqual(swift.sent, [])

    def test_close_releases_waiting_requests(self):
        swift = FakeSwift()
        swift.bridge.deliver(HELLO)
        results = []
        waiter = threading.Thread(target=lambda: results.append(swift.bridge.keychain('read', 'openalex', timeout_s=5)))
        waiter.start()
        while not swift.sent:
            pass
        swift.bridge.close()
        waiter.join(2)
        self.assertEqual(results, [None])
        self.assertFalse(swift.bridge.ready)


class SavePanelTests(unittest.TestCase):
    def test_save_panel_round_trip(self):
        swift = FakeSwift(lambda m: {'type': 'save_panel_reply', 'id': m['id'], 'ok': False, 'error': 'cancelled'})
        swift.bridge.deliver(HELLO)
        reply = swift.bridge.save_panel('/data/tasks/t1/outputs/references.bib', 'references.bib')
        self.assertEqual(reply, {'type': 'save_panel_reply', 'id': swift.sent[0]['id'], 'ok': False, 'error': 'cancelled'})
        self.assertEqual(swift.sent[0], {'type': 'save_panel', 'id': swift.sent[0]['id'],
                                         'suggested_name': 'references.bib',
                                         'path': '/data/tasks/t1/outputs/references.bib'})
        self.assertTrue(swift.sent[0]['id'].startswith('sp-'))

    def test_pdf_text_round_trip_needs_its_handshake_flag(self):
        swift = FakeSwift(lambda m: {'type': 'pdf_text_reply', 'id': m['id'], 'ok': True, 'text': 'Full text.'})
        swift.bridge.deliver(HELLO)
        self.assertIsNone(swift.bridge.pdf_text('/data/tasks/t1/fulltext/a.pdf'))  # No flag: no request.
        self.assertEqual(swift.sent, [])
        swift.bridge.deliver(dict(HELLO, pdf_text=1))
        reply = swift.bridge.pdf_text('/data/tasks/t1/fulltext/a.pdf')
        self.assertEqual((reply['ok'], reply['text']), (True, 'Full text.'))
        self.assertEqual(swift.sent[0], {'type': 'pdf_text', 'id': swift.sent[0]['id'], 'path': '/data/tasks/t1/fulltext/a.pdf'})
        self.assertTrue(swift.sent[0]['id'].startswith('pt-'))
        with self.assertRaises(ValueError):
            swift.bridge.pdf_text('relative.pdf')

    def test_save_panel_needs_an_absolute_path_and_a_plain_name(self):
        swift = FakeSwift()
        swift.bridge.deliver(HELLO)
        for path, name in (('relative.bib', 'a.bib'), ('/abs.bib', ''), ('/abs.bib', '../a.bib'), ('/abs.bib', None)):
            with self.assertRaises(ValueError):
                swift.bridge.save_panel(path, name)
        self.assertEqual(swift.sent, [])


class SwiftContractTests(unittest.TestCase):
    """The Swift side cannot run in tests; these pin the contract values it must keep (research/credentials.md)."""

    def test_keychain_settings_and_handshake(self):
        swift = (ROOT / 'app/macos/main.swift').read_text()
        for text in ('"app.interspace.research"', 'kSecAttrAccessibleWhenUnlockedThisDeviceOnly',
                     'kSecAttrSynchronizable as String: kCFBooleanFalse', '64 * 1024', '"Interspace: \\(title)"',
                     '["type": "bridge_hello", "keychain": 1, "save_panel": 1, "pdf_text": 1]',
                     '"semantic_scholar"', '"openalex"', '"crossref_email"', '"unpaywall_email"',
                     'bridgeTypes.contains(type)', 'appDataFile(path)'):
            self.assertIn(text, swift)


if __name__ == '__main__':
    unittest.main()
