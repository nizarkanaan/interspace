import base64
import hashlib
import http.client
import json
import threading
import unittest
import urllib.parse
from pathlib import Path

from . import fakehttp
from spaces import base
import spaces
from spaces import gdrive

DRIVE = 'https://www.googleapis.com/drive/v3'
UPLOAD = 'https://www.googleapis.com/upload/drive/v3'
DOCS = 'https://docs.googleapis.com/v1'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
REVOKE_URL = 'https://oauth2.googleapis.com/revoke'
FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'gdrive'
NOW = base.parse_time('2026-11-11T10:00:30.000Z')
ACCESS = 'ya29.canary-access-token-1'
ACCESS_2 = 'ya29.canary-access-token-2'
REFRESH = '1//canary-refresh-token'
CLIENT_ID = '123456789012-exampleclientid0000000000.apps.googleusercontent.com'
CLIENT_SECRET = 'GOCSPX-exampleSecretValue000000'
CLIENT = {'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET}
SIGNED_IN = dict(CLIENT, access_token=ACCESS, refresh_token=REFRESH, expires_at='2026-11-11T11:00:00.000Z',
                 scope='https://www.googleapis.com/auth/drive.file', account_id='01234567890123456789')
AUTH = {'Authorization': 'Bearer ' + ACCESS}
DOC_ID = 'docDraft000000001'
DOC_REF = 'gdrive:doc:' + DOC_ID
FOLDER_REF = 'gdrive:folder:folderReading0001'
FILE_REF = 'gdrive:file:fileNotes00000001'


def load(name):
    return json.loads((FIXTURES / (name + '.json')).read_text(encoding='utf-8'))


class FakeLoopback:
    """Stands in for the one-shot 127.0.0.1 redirect listener."""

    def __init__(self, replies=()):
        self.port = 53682
        self.replies = list(replies)
        self.closed = False
        self.waits = 0

    def wait(self, timeout_s):
        self.waits += 1
        return self.replies.pop(0) if self.replies else None

    def close(self):
        self.closed = True


class Clock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


class GdriveTestCase(unittest.TestCase):
    secret = SIGNED_IN

    def setUp(self):
        self.http = fakehttp.FakeHttp()
        self.credentials = fakehttp.MemoryCredentials(self.secret)
        self.journal = fakehttp.MemoryJournal()
        self.clock = Clock()
        self.loopback = FakeLoopback()
        self.connector = gdrive.Connector(http=self.http, credentials=self.credentials, journal=self.journal,
                                          clock=self.clock, loopback=lambda: self.loopback)

    def tearDown(self):
        self.http.assert_done()

    def assertNoSecret(self, value):
        text = json.dumps(value, default=str)
        for secret in ('canary', CLIENT_SECRET):
            self.assertNotIn(secret, text)


class RegistryTests(GdriveTestCase):
    def test_registry_builds_the_gdrive_connector(self):
        made = spaces.connector('gdrive', self.http, self.credentials, self.journal)
        self.assertIsInstance(made, gdrive.Connector)
        self.assertEqual((made.app, made.kinds), ('gdrive', ('folder', 'file', 'doc')))


class StatusTests(GdriveTestCase):
    def test_signed_in(self):
        self.http.expect('GET', DRIVE + '/about', json=load('about'), match_headers=AUTH,
                         match_params={'fields': 'user(displayName,permissionId)'})
        status = self.connector.status()
        self.assertEqual(status, {
            'v': 1, 'app': 'gdrive', 'state': 'signed_in',
            'account': {'label': 'Example Person', 'id': '01234567890123456789'},
            'granted': ['files:read', 'files:write'], 'detail': '', 'checked_at': '2026-11-11T10:00:30.000Z'})

    def test_no_client_needs_setup_and_makes_no_request(self):
        self.credentials.delete()
        status = self.connector.status()
        self.assertEqual((status['state'], status['account'], status['granted']), ('signed_out', None, []))
        self.assertIn('OAuth client', status['detail'])

    def test_client_but_no_tokens_is_signed_out(self):
        self.credentials.set(CLIENT)
        status = self.connector.status()
        self.assertEqual((status['state'], status['detail']), ('signed_out', ''))

    def test_expired_when_refresh_is_refused(self):
        self.http.expect('GET', DRIVE + '/about', status=401, json={'error': {'code': 401}})
        self.http.expect('POST', TOKEN_URL, status=400, json=load('error_invalid_grant'))
        status = self.connector.status()
        self.assertEqual(status['state'], 'expired')
        self.assertIn('Sign in', status['detail'])
        self.assertNoSecret(status)

    def test_unreachable_and_keychain_unavailable(self):
        self.http.expect('GET', DRIVE + '/about', raises='connection')
        self.assertEqual(self.connector.status()['state'], 'unavailable')

        class Broken:
            def get(self):
                raise base.CredentialStoreUnavailable('The Keychain did not answer. Try again.')
        connector = gdrive.Connector(http=self.http, credentials=Broken(), journal=self.journal, clock=self.clock)
        status = connector.status()
        self.assertEqual(status['state'], 'unavailable')
        self.assertIn('Keychain', status['detail'])


class TokenRefreshTests(GdriveTestCase):
    def test_401_refreshes_once_stores_and_repeats_the_request(self):
        self.http.expect('GET', DRIVE + '/about', status=401, json={'error': {'code': 401}}, match_headers=AUTH)
        self.http.expect('POST', TOKEN_URL, json=load('token_refreshed'))
        self.http.expect('GET', DRIVE + '/about', json=load('about'), match_headers={'Authorization': 'Bearer ' + ACCESS_2})
        self.assertEqual(self.connector.status()['state'], 'signed_in')
        refresh = self.http.calls[1]
        self.assertEqual(refresh['data'], {'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET,
                                           'refresh_token': REFRESH, 'grant_type': 'refresh_token'})
        stored = self.credentials.get()
        self.assertEqual((stored['access_token'], stored['refresh_token']), (ACCESS_2, REFRESH))
        self.assertEqual(stored['expires_at'], '2026-11-11T11:00:29.000Z')

    def test_second_401_is_auth_expired(self):
        self.http.expect('GET', DRIVE + '/files/' + DOC_ID, status=401, json={})
        self.http.expect('POST', TOKEN_URL, json=load('token_refreshed'))
        self.http.expect('GET', DRIVE + '/files/' + DOC_ID, status=401, json={})
        with self.assertRaises(base.AuthExpired):
            self.connector.read(DOC_REF)

    def test_expired_access_token_is_refreshed_before_the_call(self):
        self.credentials.set(dict(SIGNED_IN, expires_at='2026-11-11T10:00:00.000Z'))
        self.http.expect('POST', TOKEN_URL, json=dict(load('token_refreshed'), refresh_token='1//canary-rotated'))
        self.http.expect('GET', DRIVE + '/about', json=load('about'), match_headers={'Authorization': 'Bearer ' + ACCESS_2})
        self.assertEqual(self.connector.status()['state'], 'signed_in')
        self.assertEqual(self.credentials.get()['refresh_token'], '1//canary-rotated')

    def test_no_refresh_token_means_expired(self):
        self.credentials.set(dict(SIGNED_IN, refresh_token=None))
        self.http.expect('GET', DRIVE + '/about', status=401, json={})
        self.assertEqual(self.connector.status()['state'], 'expired')


class ClientSetupTests(GdriveTestCase):
    secret = None

    def test_without_a_client_sign_in_asks_for_the_client_file(self):
        step = self.connector.begin_sign_in({})
        self.assertEqual(step['kind'], 'token_entry')
        self.assertEqual(set(step), {'v', 'app', 'kind', 'label', 'help_url', 'pattern'})
        self.assertIn('OAuth client', step['label'])
        self.assertTrue(step['help_url'].startswith('https://developers.google.com/'))
        import re
        self.assertTrue(re.match(step['pattern'], json.dumps(load('client'))))

    def test_client_is_checked_with_one_call_then_stored(self):
        self.http.expect('POST', TOKEN_URL, status=400, json=load('error_invalid_grant'))
        status = self.connector.complete_sign_in({'token': json.dumps(load('client'))}, threading.Event())
        self.assertEqual(self.http.calls[0]['data']['client_id'], CLIENT_ID)
        self.assertEqual(self.http.calls[0]['data']['grant_type'], 'authorization_code')
        self.assertEqual(self.credentials.get(), CLIENT)
        self.assertEqual((status['state'], status['detail']), ('signed_out', 'Your Google OAuth client is saved. Connect again to sign in with Google.'))
        self.assertNoSecret(status)

    def test_flat_client_json_is_accepted(self):
        self.http.expect('POST', TOKEN_URL, status=400, json=load('error_invalid_grant'))
        self.connector.complete_sign_in({'token': json.dumps(CLIENT)}, None)
        self.assertEqual(self.credentials.get(), CLIENT)

    def test_unknown_client_and_bad_input_store_nothing(self):
        self.http.expect('POST', TOKEN_URL, status=401, json=load('error_invalid_client'))
        with self.assertRaises(base.InvalidRequest) as caught:
            self.connector.complete_sign_in({'token': json.dumps(load('client'))}, None)
        self.assertNoSecret(str(caught.exception))
        web = {'web': load('client')['installed']}
        for params in ({}, {'token': 'not json'}, {'token': '[]'}, {'token': json.dumps(web)},
                       {'token': json.dumps({'client_id': 'x', 'client_secret': CLIENT_SECRET})},
                       {'token': json.dumps(CLIENT), 'write_key': 'x'}):
            with self.subTest(params=params), self.assertRaises(base.InvalidRequest):
                self.connector.complete_sign_in(params, None)
        self.assertIsNone(self.credentials.get())

    def test_cancelled_client_check_stores_nothing(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(base.SignInCancelled):
            self.connector.complete_sign_in({'token': json.dumps(CLIENT)}, cancel)
        self.assertIsNone(self.credentials.get())

    def test_reads_need_sign_in(self):
        with self.assertRaises(base.NotSignedIn):
            self.connector.browse()
        with self.assertRaises(base.NotSignedIn):
            self.connector.write('gdrive.file.trash', FILE_REF, {}, 'k1')
        self.assertEqual(self.journal.records, {})


class BrowserSignInTests(GdriveTestCase):
    secret = CLIENT

    def begin(self):
        step = self.connector.begin_sign_in({})
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(step['url']).query))
        return step, query

    def test_browser_step_uses_pkce_and_the_loopback_port(self):
        step, query = self.begin()
        self.assertEqual(set(step), {'v', 'app', 'kind', 'url', 'expires_at'})
        self.assertEqual(step['kind'], 'browser')
        self.assertTrue(step['url'].startswith('https://accounts.google.com/o/oauth2/v2/auth?'))
        self.assertEqual(step['expires_at'], '2026-11-11T10:05:30.000Z')
        self.assertEqual(query['client_id'], CLIENT_ID)
        self.assertEqual(query['redirect_uri'], 'http://127.0.0.1:53682/')
        self.assertEqual(query['response_type'], 'code')
        self.assertEqual(query['scope'], 'https://www.googleapis.com/auth/drive.file')
        self.assertEqual((query['code_challenge_method'], query['access_type']), ('S256', 'offline'))
        self.assertGreaterEqual(len(query['state']), 32)
        self.assertNotIn('client_secret', query)
        self.assertNoSecret(step)

    def test_redirect_exchanges_the_code_then_stores(self):
        step, query = self.begin()
        self.loopback.replies = [None, {'code': '4/canary-code', 'state': query['state'], 'scope': 'x'}]
        self.http.expect('POST', TOKEN_URL, json=load('token'))
        self.http.expect('GET', DRIVE + '/about', json=load('about'), match_headers=AUTH)
        status = self.connector.complete_sign_in({}, threading.Event())
        self.assertEqual((status['state'], status['account']['label']), ('signed_in', 'Example Person'))
        exchange = self.http.calls[0]['data']
        verifier = exchange['code_verifier']
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode('ascii').rstrip('=')
        self.assertEqual(challenge, query['code_challenge'])
        self.assertEqual({k: exchange[k] for k in ('code', 'grant_type', 'redirect_uri', 'client_id', 'client_secret')},
                         {'code': '4/canary-code', 'grant_type': 'authorization_code',
                          'redirect_uri': 'http://127.0.0.1:53682/', 'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET})
        self.assertEqual(self.credentials.get(), dict(SIGNED_IN, expires_at='2026-11-11T11:00:29.000Z'))
        self.assertTrue(self.loopback.closed)
        self.assertNoSecret(status)

    def test_cancel_closes_the_listener(self):
        self.begin()
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(base.SignInCancelled):
            self.connector.complete_sign_in({}, cancel)
        self.assertTrue(self.loopback.closed)
        self.assertEqual(self.credentials.get(), CLIENT)

    def test_expiry(self):
        self.begin()

        class Later(FakeLoopback):
            def wait(inner, timeout_s):
                self.clock.t += 301
                return None
        self.loopback.wait = Later().wait
        with self.assertRaises(base.SignInExpired):
            self.connector.complete_sign_in({}, threading.Event())
        self.assertTrue(self.loopback.closed)

    def test_wrong_state_or_denied_consent_store_nothing(self):
        self.begin()
        self.loopback.replies = [{'code': '4/canary-code', 'state': 'forged'}]
        with self.assertRaises(base.InvalidRequest):
            self.connector.complete_sign_in({}, None)
        _, query = self.begin()
        self.loopback.replies = [{'error': 'access_denied', 'state': query['state']}]
        with self.assertRaises(base.SignInCancelled):
            self.connector.complete_sign_in({}, None)
        self.assertEqual(self.credentials.get(), CLIENT)

    def test_complete_without_begin_or_with_params(self):
        with self.assertRaises(base.InvalidRequest):
            self.connector.complete_sign_in({}, None)
        self.begin()
        with self.assertRaises(base.InvalidRequest):
            self.connector.complete_sign_in({'token': 'x'}, None)

    def test_new_begin_closes_the_previous_listener(self):
        first = self.loopback
        self.begin()
        self.loopback = FakeLoopback()
        self.begin()
        self.assertTrue(first.closed)
        self.assertFalse(self.loopback.closed)

    def test_refused_code_exchange(self):
        _, query = self.begin()
        self.loopback.replies = [{'code': '4/canary-code', 'state': query['state']}]
        self.http.expect('POST', TOKEN_URL, status=400, json=load('error_invalid_grant'))
        with self.assertRaises(base.InvalidRequest) as caught:
            self.connector.complete_sign_in({}, None)
        self.assertNoSecret(str(caught.exception))
        self.assertEqual(self.credentials.get(), CLIENT)


class LoopbackListenerTests(unittest.TestCase):
    def test_real_listener_takes_one_redirect_on_127_0_0_1(self):
        listener = gdrive.LoopbackListener()
        try:
            self.assertIsNone(listener.wait(0.05))
            results = {}

            def browser():
                connection = http.client.HTTPConnection('127.0.0.1', listener.port, timeout=5)
                connection.request('GET', '/favicon.ico')
                results['favicon'] = connection.getresponse().status
                connection.close()
                connection = http.client.HTTPConnection('127.0.0.1', listener.port, timeout=5)
                connection.request('GET', '/?code=abc&state=xyz')
                reply = connection.getresponse()
                results['status'], results['body'] = reply.status, reply.read()
                connection.close()
            thread = threading.Thread(target=browser)
            thread.start()
            got = None
            for _ in range(50):
                got = listener.wait(0.2)
                if got:
                    break
            thread.join(5)
            self.assertEqual(got, {'code': 'abc', 'state': 'xyz'})
            self.assertEqual((results['favicon'], results['status']), (404, 200))
            self.assertIn(b'Interspace', results['body'])
        finally:
            listener.close()
        listener.close()   # closing twice is harmless


class SignOutTests(GdriveTestCase):
    def test_sign_out_revokes_once_and_keeps_the_client(self):
        self.http.expect('POST', REVOKE_URL, status=200, body=b'', match_params={})
        status = self.connector.sign_out()
        self.assertEqual(self.http.calls[0]['data'], {'token': REFRESH})
        self.assertEqual(status['state'], 'signed_out')
        self.assertEqual(self.credentials.get(), CLIENT)

    def test_revocation_failure_is_ignored(self):
        self.http.expect('POST', REVOKE_URL, raises='connection')
        self.assertEqual(self.connector.sign_out()['state'], 'signed_out')
        self.assertEqual(self.credentials.get(), CLIENT)


ROOT_PARAMS = {'q': "'root' in parents and trashed = false", 'pageSize': '2', 'orderBy': 'folder,name_natural'}


class BrowseTests(GdriveTestCase):
    def test_roots_over_two_pages(self):
        self.http.expect('GET', DRIVE + '/files', json=load('files_root_1'), match_headers=AUTH, match_params=ROOT_PARAMS)
        first = self.connector.browse(limit=2)
        self.assertEqual([i['ref'] for i in first['items']], [FOLDER_REF, DOC_REF])
        self.assertEqual(first['items'][0], {
            'ref': FOLDER_REF, 'kind': 'folder', 'title': 'Reading', 'parent': 'gdrive:folder:0AExampleRootFolder00',
            'url': 'https://drive.google.com/file/d/folderReading0001/view', 'updated_at': '2026-11-10T18:02:11.123Z',
            'has_children': True, 'meta': {'mime_type': 'application/vnd.google-apps.folder'}})
        self.assertFalse(first['items'][1]['has_children'])
        self.assertTrue(first['next_cursor'])
        self.assertNotIn('page-token', first['next_cursor'])
        self.http.expect('GET', DRIVE + '/files', json=load('files_root_2'),
                         match_params=dict(ROOT_PARAMS, pageToken='page-token-2'))
        second = self.connector.browse(cursor=first['next_cursor'], limit=2)
        self.assertEqual(second['items'][0]['meta'], {'mime_type': 'text/markdown', 'size': 42})
        self.assertEqual((second['items'][0]['kind'], second['next_cursor']), ('file', None))

    def test_folder_children(self):
        self.http.expect('GET', DRIVE + '/files', json=load('files_folder'),
                         match_params={'q': "'folderReading0001' in parents and trashed = false", 'pageSize': '50'})
        page = self.connector.browse(FOLDER_REF)
        self.assertEqual([(i['kind'], i['parent']) for i in page['items']], [('doc', FOLDER_REF), ('file', FOLDER_REF)])

    def test_cursor_must_match_the_call_and_parent_must_be_a_folder(self):
        self.http.expect('GET', DRIVE + '/files', json=load('files_root_1'))
        cursor = self.connector.browse(limit=2)['next_cursor']
        for kwargs in ({'parent': FOLDER_REF, 'cursor': cursor}, {'cursor': 'garbage!'}, {'parent': DOC_REF},
                       {'parent': "gdrive:folder:x' or '1'='1"}, {'parent': 'notion:page:abc'}, {'limit': 0},
                       {'limit': 101}, {'limit': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(base.InvalidRequest):
                self.connector.browse(**kwargs)


class SearchTests(GdriveTestCase):
    def test_search_escapes_the_query_and_filters_kinds(self):
        self.http.expect('GET', DRIVE + '/files', json=load('files_search'), match_params={
            'q': "(name contains 'it\\'s a \\\\ draft' or fullText contains 'it\\'s a \\\\ draft') and trashed = false"
                 " and mimeType = 'application/vnd.google-apps.document'", 'pageSize': '25'})
        page = self.connector.search("it's a \\ draft", kinds=['doc'])
        self.assertEqual([i['ref'] for i in page['items']], [DOC_REF])

    def test_file_kind_excludes_folders_and_docs(self):
        self.http.expect('GET', DRIVE + '/files', json={'files': []}, match_params={
            'q': "(name contains 'x' or fullText contains 'x') and trashed = false and (mimeType = "
                 "'application/vnd.google-apps.folder' or (mimeType != 'application/vnd.google-apps.folder'"
                 " and mimeType != 'application/vnd.google-apps.document'))"})
        self.assertEqual(self.connector.search('x', kinds=['folder', 'file'])['items'], [])

    def test_bad_queries(self):
        for args in (('',), ('x' * 501,), (None,), ('x', ['page']), ('x', [])):
            with self.subTest(args=args), self.assertRaises(base.InvalidRequest):
                self.connector.search(*args)


class ReadTests(GdriveTestCase):
    def test_read_doc_as_markdown(self):
        self.http.expect('GET', DRIVE + '/files/' + DOC_ID, json=load('file_doc'), match_headers=AUTH)
        self.http.expect('GET', DRIVE + '/files/' + DOC_ID + '/export', body='# Draft\n\nHello.\n'.encode('utf-8'),
                         match_params={'mimeType': 'text/markdown'})
        content = self.connector.read(DOC_REF)
        self.assertEqual(content, {
            'v': 1, 'ref': DOC_REF, 'title': 'Draft chapter', 'format': 'markdown', 'text': '# Draft\n\nHello.\n',
            'truncated': False, 'next_cursor': None, 'version': '17',
            'url': 'https://docs.google.com/document/d/docDraft000000001/edit',
            'meta': {'mime_type': 'application/vnd.google-apps.document'}, 'parent': 'gdrive:folder:0AExampleRootFolder00'})

    def test_read_with_truncation_and_continuation(self):
        self.connector.max_read_chars = 10
        text = 'abcdefghijklmnopqrstuvwxy'
        self.http.expect('GET', DRIVE + '/files/' + DOC_ID, json=load('file_doc'))
        self.http.expect('GET', DRIVE + '/files/' + DOC_ID + '/export', body=text.encode())
        first = self.connector.read(DOC_REF)
        self.assertEqual((first['text'], first['truncated']), ('abcdefghij', True))
        parts = [first['text']]
        cursor = first['next_cursor']
        while cursor:
            self.http.expect('GET', DRIVE + '/files/' + DOC_ID, json=load('file_doc'))
            self.http.expect('GET', DRIVE + '/files/' + DOC_ID + '/export', body=text.encode())
            part = self.connector.read(DOC_REF, cursor)
            parts.append(part['text'])
            cursor = part['next_cursor']
        self.assertEqual(''.join(parts), text)
        self.assertEqual(len(parts), 3)

    def test_continuation_after_an_edit_is_a_conflict(self):
        self.connector.max_read_chars = 10
        self.http.expect('GET', DRIVE + '/files/' + DOC_ID, json=load('file_doc'))
        self.http.expect('GET', DRIVE + '/files/' + DOC_ID + '/export', body=b'x' * 30)
        cursor = self.connector.read(DOC_REF)['next_cursor']
        self.http.expect('GET', DRIVE + '/files/' + DOC_ID, json=load('file_doc_v18'))
        with self.assertRaises(base.Conflict):
            self.connector.read(DOC_REF, cursor)
        with self.assertRaises(base.InvalidRequest):
            self.connector.read(FILE_REF, cursor)

    def test_read_text_file(self):
        self.http.expect('GET', DRIVE + '/files/fileNotes00000001', json=load('file_text'))
        self.http.expect('GET', DRIVE + '/files/fileNotes00000001', body=b'plain notes\n', match_params={'alt': 'media'})
        content = self.connector.read(FILE_REF)
        self.assertEqual((content['format'], content['text'], content['meta']['size']), ('text', 'plain notes\n', 42))

    def test_read_sheet_exports_csv(self):
        self.http.expect('GET', DRIVE + '/files/sheetBudget000001', json=load('file_sheet'))
        self.http.expect('GET', DRIVE + '/files/sheetBudget000001/export', body=b'a,b\n1,2\n', match_params={'mimeType': 'text/csv'})
        content = self.connector.read('gdrive:file:sheetBudget000001')
        self.assertEqual((content['format'], content['text']), ('text', 'a,b\n1,2\n'))

    def test_binary_file_is_unavailable_without_download(self):
        self.http.expect('GET', DRIVE + '/files/filePaper00000001', json=load('file_pdf'))
        content = self.connector.read('gdrive:file:filePaper00000001')
        self.assertEqual((content['format'], content['text'], content['meta']['reason']),
                         ('unavailable', '', 'Interspace cannot show application/pdf files as text.'))

    def test_folder_reads_as_json_metadata(self):
        self.http.expect('GET', DRIVE + '/files/folderReading0001', json=load('file_folder'))
        content = self.connector.read(FOLDER_REF)
        self.assertEqual(content['format'], 'json')
        self.assertEqual(json.loads(content['text'])['name'], 'Reading')
        self.assertIsNone(content['url'])

    def test_kind_must_match_the_mime_type(self):
        self.http.expect('GET', DRIVE + '/files/' + DOC_ID, json=load('file_doc'))
        with self.assertRaises(base.InvalidRequest):
            self.connector.read('gdrive:folder:' + DOC_ID)

    def test_remote_shape_is_validated(self):
        for broken in ({}, {'id': DOC_ID, 'name': 3, 'mimeType': 'x'}, dict(load('file_doc'), modifiedTime='yesterday'),
                       dict(load('file_doc'), id='../etc')):
            self.http.expect('GET', DRIVE + '/files/' + DOC_ID, json=broken)
            with self.subTest(broken=broken), self.assertRaises(base.InvalidResponse):
                self.connector.read(DOC_REF)


class ActionTests(GdriveTestCase):
    def test_action_specs_and_tools(self):
        specs = self.connector.actions()
        self.assertEqual([(s['name'], s['target_kind'], s['effect'], s['requires_version']) for s in specs], [
            ('gdrive.folder.create_doc', 'folder', 'create', False),
            ('gdrive.doc.append', 'doc', 'update', False),
            ('gdrive.doc.replace_text', 'doc', 'update', True),
            ('gdrive.file.rename', 'file', 'update', False),
            ('gdrive.file.trash', 'file', 'destructive', False)])
        for spec in specs:
            schema = spec['params_schema']
            self.assertFalse(schema['additionalProperties'])
            for prop in schema['properties'].values():
                if prop.get('type') == 'string':
                    self.assertIn('maxLength', prop)
        names = [t['name'] for t in base.tools(self.connector)]
        self.assertEqual(names, ['gdrive_search', 'gdrive_browse', 'gdrive_read', 'gdrive_folder_create_doc',
                                 'gdrive_doc_append', 'gdrive_doc_replace_text', 'gdrive_file_rename', 'gdrive_file_trash'])
        specs[0]['title'] = 'changed'
        self.assertNotEqual(self.connector.actions()[0]['title'], 'changed')

    def test_create_empty_doc(self):
        self.http.expect('POST', DRIVE + '/files', json=load('created_doc'), match_json={
            'name': 'Meeting notes', 'mimeType': 'application/vnd.google-apps.document', 'parents': ['folderReading0001']})
        result = self.connector.write('gdrive.folder.create_doc', FOLDER_REF, {'title': 'Meeting notes'}, 'k1')
        self.assertEqual(result, {
            'v': 1, 'ok': True, 'action': 'gdrive.folder.create_doc', 'ref': FOLDER_REF,
            'result_ref': 'gdrive:doc:docNew00000000001',
            'url': 'https://docs.google.com/document/d/docNew00000000001/edit', 'version': '2', 'replayed': False,
            'summary': 'Created Google Doc "Meeting notes".'})

    def test_create_doc_from_markdown_is_one_multipart_upload(self):
        self.http.expect('POST', UPLOAD + '/files', json=load('created_doc'), match_params={'uploadType': 'multipart'})
        self.connector.write('gdrive.folder.create_doc', FOLDER_REF, {'title': 'Meeting notes', 'markdown': '# Agenda\n- one'}, 'k1')
        call = self.http.calls[0]
        content_type = call['headers']['Content-Type']
        self.assertTrue(content_type.startswith('multipart/related; boundary='))
        boundary = content_type.split('boundary=', 1)[1]
        body = call['data'].decode('utf-8')
        parts = body.split('--' + boundary)
        self.assertEqual(len(parts), 4)
        self.assertEqual(parts[3], '--\r\n')
        meta = json.loads(parts[1].split('\r\n\r\n', 1)[1])
        self.assertEqual(meta, {'name': 'Meeting notes', 'mimeType': 'application/vnd.google-apps.document',
                                'parents': ['folderReading0001']})
        self.assertIn('Content-Type: text/markdown; charset=UTF-8\r\n\r\n# Agenda\n- one\r\n', parts[2])

    def test_append(self):
        self.http.expect('POST', DOCS + '/documents/%s:batchUpdate' % DOC_ID, json=load('batch_append'), match_json={
            'requests': [{'insertText': {'endOfSegmentLocation': {}, 'text': '\nNew paragraph'}}]})
        result = self.connector.write('gdrive.doc.append', DOC_REF, {'text': 'New paragraph'}, 'k1')
        self.assertEqual((result['result_ref'], result['summary']), (DOC_REF, 'Appended text to the document.'))

    def test_replace_text_with_version(self):
        self.http.expect('GET', DRIVE + '/files/' + DOC_ID, json=load('file_doc'), match_params={'fields': 'version'})
        self.http.expect('POST', DOCS + '/documents/%s:batchUpdate' % DOC_ID, json=load('batch_replace'), match_json={
            'requests': [{'replaceAllText': {'containsText': {'text': 'old', 'matchCase': True}, 'replaceText': 'new'}}]})
        result = self.connector.write('gdrive.doc.replace_text', DOC_REF, {'find': 'old', 'replace': 'new', 'base_version': '17'}, 'k1')
        self.assertEqual(result['summary'], 'Replaced 2 matches.')

    def test_replace_text_conflict(self):
        self.http.expect('GET', DRIVE + '/files/' + DOC_ID, json=load('file_doc_v18'))
        with self.assertRaises(base.Conflict):
            self.connector.write('gdrive.doc.replace_text', DOC_REF, {'find': 'old', 'replace': 'new', 'base_version': '17'}, 'k1')
        self.assertEqual(self.journal.records['k1']['status'], 'failed')

    def test_rename_any_drive_item(self):
        for ref, ident in ((FILE_REF, 'fileNotes00000001'), (DOC_REF, DOC_ID)):
            self.http.expect('PATCH', DRIVE + '/files/' + ident, json=load('renamed'), match_json={'name': 'renamed.md'})
            result = self.connector.write('gdrive.file.rename', ref, {'name': 'renamed.md'}, 'k-' + ident)
            self.assertEqual((result['version'], result['summary']), ('18', 'Renamed to "renamed.md".'))

    def test_trash(self):
        self.http.expect('PATCH', DRIVE + '/files/fileNotes00000001', json=load('trashed'), match_json={'trashed': True})
        result = self.connector.write('gdrive.file.trash', FILE_REF, {}, 'k1')
        self.assertEqual(result['summary'], 'Moved "notes.md" to the Google Drive trash.')

    def test_journal_replay_makes_no_second_request(self):
        self.http.expect('PATCH', DRIVE + '/files/fileNotes00000001', json=load('trashed'))
        first = self.connector.write('gdrive.file.trash', FILE_REF, {}, 'k1')
        again = self.connector.write('gdrive.file.trash', FILE_REF, {}, 'k1')
        self.assertEqual(again, dict(first, replayed=True))
        self.assertEqual(len(self.http.calls), 1)
        with self.assertRaises(base.InvalidRequest):
            self.connector.write('gdrive.file.rename', FILE_REF, {'name': 'x'}, 'k1')

    def test_timeout_after_send_is_outcome_unknown_and_never_resent(self):
        self.http.expect('POST', DOCS + '/documents/%s:batchUpdate' % DOC_ID, raises='timeout_after_send')
        with self.assertRaises(base.OutcomeUnknown):
            self.connector.write('gdrive.doc.append', DOC_REF, {'text': 'x'}, 'k1')
        with self.assertRaises(base.OutcomeUnknown):
            self.connector.write('gdrive.doc.append', DOC_REF, {'text': 'x'}, 'k1')
        self.assertEqual(len(self.http.calls), 1)

    def test_version_check_timeout_is_not_unknown(self):
        self.http.expect('GET', DRIVE + '/files/' + DOC_ID, raises='timeout_after_send')
        with self.assertRaises(base.Unavailable):
            self.connector.write('gdrive.doc.replace_text', DOC_REF, {'find': 'a', 'replace': 'b', 'base_version': '17'}, 'k1')
        self.assertEqual(self.journal.records['k1']['status'], 'failed')

    def test_write_after_401_refreshes_and_sends_once_more(self):
        self.http.expect('PATCH', DRIVE + '/files/fileNotes00000001', status=401, json={})
        self.http.expect('POST', TOKEN_URL, json=load('token_refreshed'))
        self.http.expect('PATCH', DRIVE + '/files/fileNotes00000001', json=load('trashed'),
                         match_headers={'Authorization': 'Bearer ' + ACCESS_2})
        self.assertTrue(self.connector.write('gdrive.file.trash', FILE_REF, {}, 'k1')['ok'])

    def test_write_validation(self):
        cases = (
            ('gdrive.nope', FILE_REF, {}),
            ('gdrive.doc.append', FILE_REF, {'text': 'x'}),
            ('gdrive.doc.append', DOC_REF, {}),
            ('gdrive.doc.append', DOC_REF, {'text': ''}),
            ('gdrive.doc.append', DOC_REF, {'text': 'x', 'extra': 1}),
            ('gdrive.doc.replace_text', DOC_REF, {'find': 'a', 'replace': 'b'}),
            ('gdrive.doc.replace_text', DOC_REF, {'find': '', 'replace': 'b', 'base_version': '1'}),
            ('gdrive.folder.create_doc', DOC_REF, {'title': 'x'}),
            ('gdrive.folder.create_doc', FOLDER_REF, {'title': 'x' * 301}),
            ('gdrive.file.rename', FILE_REF, {'name': 3}),
            ('gdrive.file.trash', FILE_REF, []),
        )
        for action, ref, params in cases:
            with self.subTest(action=action, params=params), self.assertRaises(base.InvalidRequest):
                self.connector.write(action, ref, params, 'k1')
        with self.assertRaises(base.InvalidRequest):
            self.connector.write('gdrive.file.trash', FILE_REF, {}, 'bad key!')
        self.assertEqual(self.journal.records, {})


class ErrorMappingTests(GdriveTestCase):
    def read_with(self, status, json_body=None, headers=None):
        self.http.expect('GET', DRIVE + '/files/' + DOC_ID, status=status, json=json_body or {}, headers=headers)
        return lambda: self.connector.read(DOC_REF)

    def test_read_status_mapping(self):
        cases = ((403, load('error_403'), base.Forbidden), (403, load('error_403_rate'), base.RateLimited),
                 (404, load('error_404'), base.NotFound), (409, None, base.Conflict), (412, None, base.Conflict),
                 (429, None, base.RateLimited), (400, None, base.InvalidRequest), (500, None, base.Unavailable),
                 (503, None, base.Unavailable), (302, None, base.InvalidResponse))
        for status, body, error in cases:
            with self.subTest(status=status, error=error), self.assertRaises(error) as caught:
                self.read_with(status, body)()
            self.assertNotIn('File not found', str(caught.exception))

    def test_retry_after(self):
        with self.assertRaises(base.RateLimited) as caught:
            self.read_with(429, headers={'Retry-After': '7'})()
        self.assertEqual(caught.exception.retry_after_s, 7)

    def test_connection_error_is_unavailable(self):
        self.http.expect('GET', DRIVE + '/files/' + DOC_ID, raises='connection')
        with self.assertRaises(base.Unavailable):
            self.connector.read(DOC_REF)

    def test_write_server_error_is_outcome_unknown(self):
        self.http.expect('PATCH', DRIVE + '/files/fileNotes00000001', status=502, json={})
        with self.assertRaises(base.OutcomeUnknown):
            self.connector.write('gdrive.file.trash', FILE_REF, {}, 'k1')
        self.assertEqual(self.journal.records['k1']['status'], 'outcome_unknown')

    def test_write_client_errors_are_definite(self):
        for status, error in ((404, base.NotFound), (403, base.Forbidden), (400, base.InvalidRequest)):
            self.http.expect('PATCH', DRIVE + '/files/fileNotes00000001', status=status, json={})
            with self.subTest(status=status), self.assertRaises(error):
                self.connector.write('gdrive.file.trash', FILE_REF, {}, 'k%d' % status)
            self.assertEqual(self.journal.records['k%d' % status]['status'], 'failed')


class ChangesTests(GdriveTestCase):
    def test_baseline_then_batches(self):
        self.http.expect('GET', DRIVE + '/changes/startPageToken', json=load('start_token'))
        baseline = self.connector.changes()
        self.assertEqual((baseline['items'], baseline['complete']), ([], True))
        self.clock.t = base.parse_time('2026-11-11T10:10:00.000Z')
        self.http.expect('GET', DRIVE + '/changes', json=load('changes_1'),
                         match_params={'pageToken': '1001', 'pageSize': '100', 'includeRemoved': 'true'})
        first = self.connector.changes(baseline['cursor'])
        self.assertEqual(first['items'], [
            {'ref': 'gdrive:doc:docNew00000000001', 'change': 'created', 'at': '2026-11-11T10:05:00.000Z', 'title': 'Meeting notes'},
            {'ref': DOC_REF, 'change': 'updated', 'at': '2026-11-11T10:06:00.000Z', 'title': 'Draft chapter'}])
        self.assertFalse(first['complete'])
        self.http.expect('GET', DRIVE + '/changes', json=load('changes_2'), match_params={'pageToken': '1002'})
        second = self.connector.changes(first['cursor'])
        self.assertEqual(second['items'], [
            {'ref': 'gdrive:file:fileGone000000001', 'change': 'deleted', 'at': '2026-11-11T10:07:00.000Z', 'title': ''},
            {'ref': FILE_REF, 'change': 'deleted', 'at': '2026-11-11T10:08:00.000Z', 'title': 'notes.md'}])
        self.assertTrue(second['complete'])
        self.http.expect('GET', DRIVE + '/changes', json={'newStartPageToken': '1003', 'changes': []},
                         match_params={'pageToken': '1003'})
        self.assertEqual(self.connector.changes(second['cursor'])['items'], [])

    def test_bad_cursor(self):
        for cursor in ('nope', 'eyJtIjoiYnJvd3NlIn0'):
            with self.subTest(cursor=cursor), self.assertRaises(base.InvalidRequest):
                self.connector.changes(cursor)


if __name__ == '__main__':
    unittest.main()
