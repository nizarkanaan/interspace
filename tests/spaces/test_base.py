import hashlib
import io
import json
import socket
import unittest
import urllib.error
import urllib.request

from . import fakehttp
from spaces import base
import spaces


class FakeChannel:
    """Stands in for 1F's stdin reader: records messages, returns queued replies."""

    def __init__(self, ready=True, replies=None):
        self._ready = ready
        self.replies = list(replies or [])
        self.sent = []

    def ready(self):
        return self._ready

    def exchange(self, message, timeout_s):
        self.sent.append((message, timeout_s))
        if not self.replies:
            return None
        reply = self.replies.pop(0)
        if callable(reply):
            return reply(message)
        return reply


def reply_to(**fields):
    return lambda message: dict({'keychain_reply': message['id']}, **fields)


class RegistryTests(unittest.TestCase):
    def test_registry_lists_four_apps_and_rejects_others(self):
        self.assertEqual(spaces.APPS, ('notion', 'github', 'gdrive', 'zotero'))
        self.assertEqual(spaces.TITLES['gdrive'], 'Google Drive')
        with self.assertRaisesRegex(ValueError, 'Unknown app.'):
            spaces.connector('slack', None, None, None)


class ErrorTests(unittest.TestCase):
    def test_codes_and_value_error_base(self):
        expected = {
            'NotSignedIn': 'not_signed_in', 'AuthExpired': 'auth_expired',
            'SignInCancelled': 'sign_in_cancelled', 'SignInExpired': 'sign_in_expired',
            'CredentialStoreUnavailable': 'credential_store_unavailable', 'Forbidden': 'forbidden',
            'NotFound': 'not_found', 'Conflict': 'conflict', 'RateLimited': 'rate_limited',
            'InvalidRequest': 'invalid_request', 'InvalidResponse': 'invalid_response',
            'Unavailable': 'unavailable', 'OutcomeUnknown': 'outcome_unknown', 'Unsupported': 'unsupported',
        }
        for name, code in expected.items():
            cls = getattr(base, name)
            self.assertTrue(issubclass(cls, base.SpaceError))
            self.assertTrue(issubclass(cls, ValueError))
            self.assertEqual(cls.code, code)
        self.assertEqual(base.SpaceError.code, 'space_error')
        error = base.RateLimited('Slow down.', retry_after_s=30)
        self.assertEqual(str(error), 'Slow down.')
        self.assertEqual(error.retry_after_s, 30)
        self.assertIsNone(base.NotFound('Gone.').retry_after_s)


class TimeTests(unittest.TestCase):
    def test_iso_time_has_milliseconds_and_z(self):
        self.assertEqual(base.iso_time(1762853400.25), '2025-11-11T09:30:00.250Z')

    def test_parse_time_accepts_z_and_offsets(self):
        self.assertEqual(base.parse_time('2025-11-11T09:30:00.250Z'), 1762853400.25)
        self.assertEqual(base.parse_time('2025-11-11T10:30:00+01:00'), 1762853400.0)
        for bad in ('', 'yesterday', None, 5, '2025-11-11'):
            with self.subTest(bad=bad), self.assertRaises(base.InvalidResponse):
                base.parse_time(bad)


class RefTests(unittest.TestCase):
    def test_round_trip(self):
        ref = base.make_ref('github', 'issue', 'octo/repo#12')
        self.assertEqual(ref, 'github:issue:octo/repo#12')
        self.assertEqual(base.parse_ref(ref), ('github', 'issue', 'octo/repo#12'))
        self.assertEqual(base.parse_ref('github:file:o/n@main:src/a.py', 'github'), ('github', 'file', 'o/n@main:src/a.py'))

    def test_rejects_malformed_refs(self):
        bad = ['', 'notion', 'notion:page', 'slack:page:1', 'notion:Page:1', 'notion:page:', 'notion:page:a\nb',
               'notion:page:' + 'x' * 513, 'notion:' + 'k' * 33 + ':1', 5, None]
        for ref in bad:
            with self.subTest(ref=ref), self.assertRaises(base.InvalidRequest):
                base.parse_ref(ref)
        with self.assertRaises(base.InvalidRequest):
            base.parse_ref('github:repo:o/n', 'notion')
        with self.assertRaises(base.InvalidRequest):
            base.make_ref('notion', 'page', '')


class DigestAndKeyTests(unittest.TestCase):
    def test_params_digest_is_canonical(self):
        one = base.params_digest({'b': 1, 'a': 'é'})
        two = base.params_digest({'a': 'é', 'b': 1})
        self.assertEqual(one, two)
        canonical = '{"a":"é","b":1}'.encode('utf-8')
        self.assertEqual(one, 'sha256:' + hashlib.sha256(canonical).hexdigest())

    def test_agent_key(self):
        task = 'a' * 32
        key = base.agent_key(task, 'turn-1', 'call-9')
        digest = hashlib.sha256(b'turn-1:call-9').hexdigest()[:32]
        self.assertEqual(key, task + ':' + digest)
        self.assertEqual(len(key), 65)
        base.check_idempotency_key(key)
        for bad in ('', 'a b', 'x' * 129, None, 'é'):
            with self.subTest(bad=bad), self.assertRaises(base.InvalidRequest):
                base.check_idempotency_key(bad)


class JournaledWriteTests(unittest.TestCase):
    def setUp(self):
        self.journal = base.MemoryJournal()
        self.calls = 0

    def write(self, key='k1', params=None, outcome=None, action='notion.page.append'):
        def perform():
            self.calls += 1
            if outcome is not None:
                raise outcome
            return {'v': 1, 'ok': True, 'action': action, 'ref': 'notion:page:1', 'result_ref': None,
                    'url': None, 'version': 'v2', 'replayed': False, 'summary': 'Done.'}
        return base.journaled_write(self.journal, key=key, app='notion', action=action, ref='notion:page:1',
                                    params={'markdown': 'hi'} if params is None else params, perform=perform)

    def test_success_then_replay_without_remote_call(self):
        first = self.write()
        self.assertFalse(first['replayed'])
        self.assertEqual(self.journal.records['k1']['status'], 'succeeded')
        again = self.write()
        self.assertTrue(again['replayed'])
        self.assertEqual(self.calls, 1)
        self.assertEqual(again['summary'], 'Done.')

    def test_same_key_different_params_is_invalid(self):
        self.write()
        with self.assertRaises(base.InvalidRequest):
            self.write(params={'markdown': 'other'})
        with self.assertRaises(base.InvalidRequest):
            self.write(action='notion.page.comment')
        self.assertEqual(self.calls, 1)

    def test_started_record_raises_outcome_unknown(self):
        digest = base.params_digest({'markdown': 'hi'})
        self.assertIsNone(self.journal.begin('k1', 'notion', 'notion.page.append', 'notion:page:1', digest))
        with self.assertRaises(base.OutcomeUnknown):
            self.write()
        self.assertEqual(self.calls, 0)

    def test_failure_is_stored_and_raised_again_without_a_call(self):
        with self.assertRaises(base.Forbidden):
            self.write(outcome=base.Forbidden('No access.'))
        self.assertEqual(self.journal.records['k1']['status'], 'failed')
        self.assertEqual(self.journal.records['k1']['error_code'], 'forbidden')
        with self.assertRaises(base.Forbidden):
            self.write()
        self.assertEqual(self.calls, 1)

    def test_transport_failure_after_send_is_unknown_forever(self):
        error = base.Unavailable('Lost.')
        error.request_sent = True
        with self.assertRaises(base.OutcomeUnknown):
            self.write(outcome=error)
        self.assertEqual(self.journal.records['k1']['status'], 'outcome_unknown')
        with self.assertRaises(base.OutcomeUnknown):
            self.write()
        self.assertEqual(self.calls, 1)

    def test_unreadable_reply_to_a_write_is_unknown(self):
        with self.assertRaises(base.OutcomeUnknown):
            self.write(outcome=base.InvalidResponse('Bad reply.'))
        self.assertEqual(self.journal.records['k1']['status'], 'outcome_unknown')

    def test_connection_failure_before_send_is_a_definite_failure(self):
        with self.assertRaises(base.Unavailable):
            self.write(outcome=base.Unavailable('Offline.'))
        self.assertEqual(self.journal.records['k1']['status'], 'failed')

    def test_unexpected_error_marks_unknown_and_propagates(self):
        with self.assertRaises(KeyError):
            self.write(outcome=KeyError('bug'))
        self.assertEqual(self.journal.records['k1']['status'], 'outcome_unknown')

    def test_bad_key_is_rejected_before_the_journal(self):
        with self.assertRaises(base.InvalidRequest):
            self.write(key='bad key')
        self.assertEqual(self.journal.records, {})


class CredentialsTests(unittest.TestCase):
    def test_without_bridge_hello_nothing_is_sent(self):
        channel = FakeChannel(ready=False)
        credentials = base.Credentials('notion', channel)
        for call in (credentials.get, lambda: credentials.set({'a': 1}), credentials.delete):
            with self.assertRaises(base.CredentialStoreUnavailable):
                call()
        self.assertEqual(channel.sent, [])

    def test_read_write_delete_messages(self):
        secret = {'access_token': 'canary-token-1'}
        channel = FakeChannel(replies=[
            reply_to(ok=True, secret=json.dumps(secret)),
            reply_to(ok=True),
            reply_to(ok=True),
        ])
        credentials = base.Credentials('notion', channel)
        self.assertEqual(credentials.get(), secret)
        credentials.set({'access_token': 'canary-token-2'})
        credentials.delete()
        (read, t1), (write, _), (delete, _) = channel.sent
        self.assertEqual(t1, 10)
        self.assertEqual(set(read), {'type', 'id', 'op', 'account'})
        self.assertEqual((read['type'], read['op'], read['account']), ('keychain', 'read', 'notion'))
        self.assertRegex(read['id'], '^kc-[0-9a-f]{32}$')
        self.assertEqual(write['op'], 'write')
        self.assertEqual(json.loads(write['secret']), {'access_token': 'canary-token-2'})
        self.assertEqual(set(delete), {'type', 'id', 'op', 'account'})
        self.assertEqual(delete['op'], 'delete')
        self.assertEqual(len({read['id'], write['id'], delete['id']}), 3)

    def test_not_found_and_failures(self):
        channel = FakeChannel(replies=[reply_to(ok=False, error='not_found'), reply_to(ok=False, error='not_found')])
        credentials = base.Credentials('notion', channel)
        self.assertIsNone(credentials.get())
        credentials.delete()
        for reply in (reply_to(ok=False, error='denied'), reply_to(ok=False, error='unavailable'), None,
                      reply_to(ok=True, secret='not json'), reply_to(ok=True, secret='[1]'),
                      lambda m: {'keychain_reply': 'kc-other', 'ok': True, 'secret': '{}'}):
            with self.subTest(reply=reply), self.assertRaises(base.CredentialStoreUnavailable) as caught:
                base.Credentials('notion', FakeChannel(replies=[reply] if reply else [])).get()
            self.assertNotIn('not json', str(caught.exception))

    def test_write_not_found_is_a_failure(self):
        channel = FakeChannel(replies=[reply_to(ok=False, error='not_found')])
        with self.assertRaises(base.CredentialStoreUnavailable):
            base.Credentials('notion', channel).set({'a': 1})

    def test_rejects_unknown_account(self):
        with self.assertRaises(ValueError):
            base.Credentials('slack', FakeChannel())


class FakeResponse(io.BytesIO):
    def __init__(self, status, body, headers):
        super().__init__(body)
        self.status = status
        self.headers = headers

    def getcode(self):
        return self.status


class FakeOpener:
    def __init__(self, outcome):
        self.outcome = outcome
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class HttpTests(unittest.TestCase):
    def test_sends_json_with_fixed_user_agent(self):
        opener = FakeOpener(FakeResponse(200, b'{"ok": true}', {'Content-Type': 'application/json'}))
        response = base.Http(opener=opener).request('POST', 'https://api.example.test/v1/x', headers={'X-Key': 'a'},
                                                    params={'q': 'a b'}, json={'b': 1}, timeout_s=5)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.json(), {'ok': True})
        self.assertEqual(response.headers, {'content-type': 'application/json'})
        request, timeout = opener.requests[0]
        self.assertEqual(timeout, 5)
        self.assertEqual(request.full_url, 'https://api.example.test/v1/x?q=a+b')
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.get_header('User-agent'), 'Interspace')
        self.assertEqual(request.get_header('Content-type'), 'application/json')
        self.assertEqual(json.loads(request.data), {'b': 1})

    def test_rejects_plain_http_except_zotero_local(self):
        for url in ('http://api.example.test/', 'ftp://x/', 'http://127.0.0.1:8080/', 'https:///nohost'):
            with self.subTest(url=url), self.assertRaises(base.InvalidRequest):
                base.Http(opener=FakeOpener(None)).request('GET', url)
        opener = FakeOpener(FakeResponse(200, b'[]', {}))
        base.Http(opener=opener).request('GET', 'http://127.0.0.1:23119/api/users/0/items')

    def test_http_errors_become_responses(self):
        error = urllib.error.HTTPError('https://a.test/', 404, 'Not Found', {'Retry-After': '3'}, io.BytesIO(b'{}'))
        response = base.Http(opener=FakeOpener(error)).request('GET', 'https://a.test/')
        self.assertEqual((response.status, response.headers['retry-after']), (404, '3'))

    def test_transport_errors(self):
        refused = urllib.error.URLError(ConnectionRefusedError())
        with self.assertRaises(base.Unavailable) as caught:
            base.Http(opener=FakeOpener(refused)).request('GET', 'https://a.test/')
        self.assertFalse(caught.exception.request_sent)
        with self.assertRaises(base.Unavailable) as caught:
            base.Http(opener=FakeOpener(socket.timeout('timed out'))).request('POST', 'https://a.test/')
        self.assertTrue(caught.exception.request_sent)

    def test_response_size_cap(self):
        big = FakeResponse(200, b'x' * (base.MAX_RESPONSE_BYTES + 1), {})
        with self.assertRaises(base.InvalidResponse):
            base.Http(opener=FakeOpener(big)).request('GET', 'https://a.test/')

    def test_redirects_stay_on_the_same_host(self):
        handler = base._SameHostRedirect()
        request = urllib.request.Request('https://a.test/x')
        self.assertIsNone(handler.redirect_request(request, None, 302, 'Found', {}, 'https://evil.test/x'))
        self.assertIsNone(handler.redirect_request(request, None, 302, 'Found', {}, 'http://a.test/x'))
        same = handler.redirect_request(request, None, 302, 'Found', {}, 'https://a.test/y')
        self.assertEqual(same.full_url, 'https://a.test/y')

    def test_bad_json_is_invalid_response(self):
        with self.assertRaises(base.InvalidResponse):
            base.Response(200, {}, b'{nope').json()
        self.assertEqual(base.Response(200, {'X-A': '1'}, 'é'.encode()).text(), 'é')
        self.assertEqual(base.Response(200, {'X-A': '1'}, b'').headers, {'x-a': '1'})


class StubConnector:
    app = 'notion'
    kinds = ('page', 'database', 'block')

    def __init__(self, actions):
        self._actions = actions

    def actions(self):
        return self._actions


APPEND = {'name': 'notion.page.append', 'title': 'Append to page', 'target_kind': 'page', 'effect': 'update',
          'params_schema': {'type': 'object', 'additionalProperties': False,
                            'description': 'Append Markdown blocks to the end of a Notion page.',
                            'properties': {'markdown': {'type': 'string', 'maxLength': 100000}},
                            'required': ['markdown']},
          'requires_version': False}


class ToolTests(unittest.TestCase):
    def test_standard_and_action_tools(self):
        tools = base.tools(StubConnector([APPEND]))
        by_name = {tool['name']: tool for tool in tools}
        self.assertEqual(list(by_name), ['notion_search', 'notion_browse', 'notion_read', 'notion_page_append'])
        append = by_name['notion_page_append']
        self.assertEqual(append, {
            'v': 1, 'name': 'notion_page_append', 'app': 'notion', 'title': 'Append to page',
            'description': 'Append Markdown blocks to the end of a Notion page.',
            'input_schema': {'type': 'object', 'additionalProperties': False,
                             'properties': {'ref': {'type': 'string', 'maxLength': 600},
                                            'markdown': {'type': 'string', 'maxLength': 100000}},
                             'required': ['ref', 'markdown']},
            'effect': 'update', 'action': 'notion.page.append', 'ref_param': 'ref'})
        self.assertEqual(by_name['notion_search']['ref_param'], None)
        self.assertEqual(by_name['notion_search']['effect'], 'read')
        self.assertEqual(by_name['notion_search']['input_schema']['properties']['kinds']['items']['enum'],
                         ['page', 'database', 'block'])
        self.assertEqual(by_name['notion_browse']['ref_param'], 'parent')
        self.assertEqual(by_name['notion_read']['input_schema']['required'], ['ref'])
        for tool in tools:
            self.assertRegex(tool['name'], '^[a-z][a-z0-9_]{0,63}$')
            self.assertFalse(tool['input_schema']['additionalProperties'])
            self.assertIsNone(tool['action'] if tool['effect'] == 'read' else None)

    def test_rejects_action_that_shadows_ref(self):
        bad = dict(APPEND, params_schema={'type': 'object', 'additionalProperties': False,
                                          'properties': {'ref': {'type': 'string', 'maxLength': 5}}})
        with self.assertRaises(ValueError):
            base.tools(StubConnector([bad]))


class FakeHttpTests(unittest.TestCase):
    def test_in_order_matching_and_assert_done(self):
        http = fakehttp.FakeHttp()
        http.expect('POST', 'https://a.test/v1/search', json={'results': []}, match_json={'query': 'x'},
                    match_params={'page': '2'}, match_headers={'Authorization': 'Bearer t'})
        http.expect('GET', 'https://a.test/v1/x', status=404)
        response = http.request('POST', 'https://a.test/v1/search?page=2', headers={'Authorization': 'Bearer t'},
                                json={'query': 'x', 'page_size': 5})
        self.assertEqual(response.json(), {'results': []})
        with self.assertRaises(AssertionError):
            http.assert_done()
        self.assertEqual(http.request('GET', 'https://a.test/v1/x').status, 404)
        http.assert_done()
        self.assertEqual([c['method'] for c in http.calls], ['POST', 'GET'])

    def test_mismatch_and_unexpected_requests_fail(self):
        http = fakehttp.FakeHttp()
        http.expect('GET', 'https://a.test/a', match_params={'x': '1'})
        with self.assertRaisesRegex(AssertionError, 'https://a.test/b'):
            http.request('GET', 'https://a.test/b')
        http = fakehttp.FakeHttp()
        with self.assertRaises(AssertionError):
            http.request('GET', 'https://a.test/a')

    def test_raises(self):
        http = fakehttp.FakeHttp()
        http.expect('GET', 'https://a.test/a', raises='connection')
        http.expect('POST', 'https://a.test/a', raises='timeout_after_send')
        with self.assertRaises(base.Unavailable) as caught:
            http.request('GET', 'https://a.test/a')
        self.assertFalse(caught.exception.request_sent)
        with self.assertRaises(base.Unavailable) as caught:
            http.request('POST', 'https://a.test/a')
        self.assertTrue(caught.exception.request_sent)

    def test_memory_credentials_and_journal(self):
        credentials = fakehttp.MemoryCredentials({'access_token': 'x'})
        self.assertEqual(credentials.get(), {'access_token': 'x'})
        credentials.set({'access_token': 'y'})
        self.assertEqual(credentials.get(), {'access_token': 'y'})
        credentials.delete()
        self.assertIsNone(credentials.get())
        self.assertIs(fakehttp.MemoryJournal, base.MemoryJournal)


if __name__ == '__main__':
    unittest.main()
