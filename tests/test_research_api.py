"""Settings → Research sources methods (research/credentials.md), on a real Application with a fake Keychain."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
sys.path.insert(0, str(ROOT / 'tests'))

import research  # noqa: E402
import research_api  # noqa: E402
import service  # noqa: E402
from research import credentials  # noqa: E402
from test_research_credentials import FakeChannel  # noqa: E402

SECRETS = {'semantic_scholar': 'fake-s2-key-AAAA1111', 'openalex': 'fake-openalex-key-BBBB2222',
           'crossref': 'crossref-person@example.org', 'unpaywall': 'unpaywall-person@example.org'}
ROW_FIELDS = {'source', 'title', 'credential_kind', 'required', 'configured', 'state', 'detail', 'help_url',
              'capabilities'}


class FakeAuth:
    def status(self):
        return {'state': 'signed_out'}


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.published = []
        self.app = service.Application(folder.name, provider=FakeAuth(), emit=self.published.append)
        self.addCleanup(self.app.scheduler.shutdown, timeout_s=5)
        self.channel = FakeChannel()
        self.app.bridge = self.channel

    def call(self, method, params=None):
        return self.app.handle(method, params or {})

    def rows(self):
        return {row['source']: row for row in self.call('research_sources')['sources']}


class RegistrationTests(ApiTestCase):
    def test_methods_are_registered_through_the_extension_hook(self):
        for method in ('research_sources', 'research_credential_set', 'research_credential_delete', 'research_test',
                       'research_usage'):
            self.assertIn(method, self.app.extensions)

    def test_methods_are_in_the_swift_allowlist(self):
        swift = (ROOT / 'app/macos/main.swift').read_text()
        for method in list(research_api.METHODS) + ['task_outputs', 'task_output_save']:
            self.assertIn('"%s"' % method, swift)


class SourcesTests(ApiTestCase):
    def test_every_source_with_the_contract_fields(self):
        rows = self.rows()
        self.assertEqual(list(rows), ['semantic_scholar', 'openalex', 'arxiv', 'crossref', 'unpaywall'])
        for row in rows.values():
            self.assertEqual(set(row), ROW_FIELDS)
            self.assertTrue(row['help_url'].startswith('https://'))
            self.assertIsInstance(row['capabilities'], list)

    def test_fallback_facts_match_the_spike(self):
        rows = self.rows()
        facts = {name: (row['credential_kind'], row['required']) for name, row in rows.items()}
        self.assertEqual(facts, {'semantic_scholar': ('api_key', False), 'openalex': ('api_key', False),
                                 'arxiv': (None, False), 'crossref': ('email', False), 'unpaywall': ('email', True)})
        self.assertEqual(rows['unpaywall']['state'], 'needs_key')
        self.assertEqual(rows['openalex']['state'], 'ready')
        self.assertFalse(rows['openalex']['configured'])

    def test_set_returns_the_row_without_the_value_and_delete_removes_it(self):
        row = self.call('research_credential_set', {'source': 'unpaywall', 'value': SECRETS['unpaywall']})
        self.assertEqual(set(row), ROW_FIELDS)
        self.assertTrue(row['configured'])
        self.assertEqual(row['state'], 'ready')
        self.assertEqual(self.channel.items, {'unpaywall_email': SECRETS['unpaywall']})
        row = self.call('research_credential_delete', {'source': 'unpaywall'})
        self.assertFalse(row['configured'])
        self.assertEqual(row['state'], 'needs_key')
        self.assertEqual(self.channel.items, {})

    def test_bad_requests(self):
        for method, params in (('research_credential_set', {'source': 'nowhere', 'value': 'x' * 10}),
                               ('research_credential_set', {'source': 'arxiv', 'value': 'x' * 10}),
                               ('research_credential_set', {'source': 'openalex'}),
                               ('research_credential_set', {'source': 'openalex', 'value': 'short'}),
                               ('research_credential_delete', {'source': 'arxiv'}),
                               ('research_test', {'source': None}),
                               ('research_usage', {'task_id': 5})):
            with self.assertRaises(ValueError):
                self.call(method, params)

    def test_without_the_handshake_credential_sources_report_the_store_unavailable(self):
        self.channel.ready = False
        rows = self.rows()
        for name in ('semantic_scholar', 'openalex', 'crossref', 'unpaywall'):
            self.assertEqual(rows[name]['state'], 'credential_store_unavailable')
            self.assertFalse(rows[name]['configured'])
        self.assertEqual(rows['arxiv']['state'], 'ready')
        with self.assertRaises(credentials.CredentialStoreUnavailable):
            self.call('research_credential_set', {'source': 'openalex', 'value': SECRETS['openalex']})

    def test_test_returns_one_row(self):
        row = self.call('research_test', {'source': 'arxiv'})
        self.assertEqual((row['source'], row['state']), ('arxiv', 'ready'))

    def test_usage_counts_are_numbers_only(self):
        usage = self.call('research_usage')
        self.assertEqual(set(usage), {'calls', 'cached'})
        self.assertEqual(usage['calls']['openalex'], 0)


class StreamOneBSourcesTests(ApiTestCase):
    """Once stream 1B's `research.sources(app)` exists, its sources and their `status` are used."""

    class Source:
        name, title, credential, credential_kind, required = 'openalex', 'OpenAlex', 'openalex', 'api_key', False
        capabilities, help_url = ('search', 'paper'), 'https://openalex.example/key'

        def __init__(self, app):
            self.store = credentials.for_app(app)
            self.tests = []

        def status(self, test=False):
            self.tests.append(test)
            configured = self.store.configured('openalex')
            return {'source': 'openalex', 'configured': configured, 'required': False,
                    'state': 'ready' if test and configured else 'unchecked', 'detail': 'From the client.'}

    def test_registry_sources_and_status_are_used(self):
        source = self.Source(self.app)
        with mock.patch.object(research, 'sources', lambda app: [source], create=True):
            rows = self.rows()
            self.assertEqual(list(rows), ['openalex'])
            self.assertEqual(rows['openalex']['detail'], 'From the client.')
            self.assertEqual(rows['openalex']['help_url'], 'https://openalex.example/key')
            self.call('research_credential_set', {'source': 'openalex', 'value': SECRETS['openalex']})
            self.assertEqual(self.call('research_test', {'source': 'openalex'})['state'], 'ready')
        self.assertEqual(source.tests[-1], True)

    def test_a_failing_status_becomes_an_error_row(self):
        source = self.Source(self.app)
        source.status = mock.Mock(side_effect=RuntimeError('upstream said: ' + SECRETS['openalex']))
        with mock.patch.object(research, 'sources', lambda app: [source], create=True):
            row = self.rows()['openalex']
        self.assertEqual(row['state'], 'error')
        self.assertNotIn(SECRETS['openalex'], json.dumps(row))

    def test_registry_usage_is_used_and_cleaned(self):
        usage = lambda app, task_id: {'calls': {'openalex': 3, 'bad': 'x'}, 'cached': {'openalex': 1}, 'extra': 1}
        with mock.patch.object(research, 'usage', usage, create=True):
            self.assertEqual(self.call('research_usage', {'task_id': 't1'}),
                             {'calls': {'openalex': 3}, 'cached': {'openalex': 1}})


class KeySafetyTests(ApiTestCase):
    def test_stored_secrets_never_leave_the_backend(self):
        seen = []
        for source, secret in SECRETS.items():
            seen.append(self.call('research_credential_set', {'source': source, 'value': secret}))
        seen.append(self.call('research_sources'))
        for source in research_api.SOURCE_NAMES:
            seen.append(self.call('research_test', {'source': source}))
        seen.append(self.call('research_usage'))
        seen.append(self.app.public())
        seen.append([m for m in self.published if m.get('type') != 'keychain'])
        for name in ('semantic_scholar', 'openalex', 'crossref', 'unpaywall'):
            try:
                self.call('research_credential_set', {'source': name, 'value': SECRETS[name] + ' with space'})
            except ValueError as error:
                seen.append(str(error))
        self.channel.error = 'denied'
        credentials.for_app(self.app).clear()
        seen.append(self.call('research_sources'))
        state_files = ''.join(p.read_text(errors='replace') for p in Path(self.app.storage).rglob('*') if p.is_file())
        text = json.dumps(seen) + state_files
        for secret in SECRETS.values():
            self.assertNotIn(secret, text)
            self.assertNotIn(secret.split('@')[0], text)


if __name__ == '__main__':
    unittest.main()
