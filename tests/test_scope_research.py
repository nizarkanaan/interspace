"""The scope `research` key, its decisions, defaults and Add to scope (research/tasks.md "Scope")."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
sys.path.insert(0, str(ROOT / 'tests'))

import audit  # noqa: E402
import budget  # noqa: E402
import scope  # noqa: E402
from test_scope import NOW, approval_for, base_scope  # noqa: E402

USABLE = {'semantic_scholar': True, 'openalex': True, 'arxiv': True, 'crossref': True, 'unpaywall': False}


def research_scope(sources):
    document = base_scope()
    document['research'] = {'sources': dict(sources)}
    return document


def request(source='crossref', tool='research_search'):
    return {'category': 'research', 'source': source, 'tool': tool}


def decide(document, req):
    return scope.decide(document, approval_for(document), req, workspace_roots={}, now=NOW)


class ValidateTests(unittest.TestCase):
    def test_the_key_is_optional_and_old_digests_are_unchanged(self):
        document = base_scope()
        before = scope.digest(document)
        self.assertIs(scope.validate(document), document)
        self.assertNotIn('research', document)
        self.assertEqual(scope.digest(document), before)

    def test_valid_research_key(self):
        document = research_scope({'semantic_scholar': 'allow', 'unpaywall': 'ask', 'arxiv': 'off'})
        self.assertIs(scope.validate(document), document)
        self.assertNotEqual(scope.digest(document), scope.digest(base_scope()))

    def test_bad_research_values_are_refused(self):
        bad = [None, [], {}, {'sources': []}, {'sources': {'crossref': 'deny'}}, {'sources': {'Cross Ref': 'allow'}},
               {'sources': {'crossref': 'allow'}, 'extra': 1}, {'sources': {('s%d' % i): 'off' for i in range(33)}}]
        for value in bad:
            document = base_scope()
            document['research'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                scope.validate(document)


class DecideTests(unittest.TestCase):
    def test_allow_ask_off_and_missing(self):
        document = research_scope({'crossref': 'allow', 'unpaywall': 'ask', 'arxiv': 'off'})
        allowed = decide(document, request('crossref'))
        self.assertEqual((allowed['decision'], allowed['rule']), ('allow', 'research.allow'))
        asked = decide(document, request('unpaywall', 'research_fulltext'))
        self.assertEqual((asked['decision'], asked['rule']), ('ask', 'research.ask'))
        self.assertEqual(asked['ask']['options'], ['allow_once', 'add_to_scope', 'deny'])
        self.assertEqual(asked['ask']['scope_patch'], {'research': {'sources': {'unpaywall': 'allow'}}})
        self.assertIn('Unpaywall', asked['ask']['title'])
        for source in ('arxiv', 'openalex'):
            denied = decide(document, request(source))
            self.assertEqual((denied['decision'], denied['rule']), ('deny', 'research.off'))

    def test_a_scope_without_the_key_denies_research(self):
        denied = decide(base_scope(), request())
        self.assertEqual((denied['decision'], denied['rule']), ('deny', 'research.off'))

    def test_malformed_requests_are_denied(self):
        document = research_scope({'crossref': 'allow'})
        for bad in ({'category': 'research', 'source': 'crossref'}, {'category': 'research', 'tool': 'x'},
                    {'category': 'research', 'source': '', 'tool': 'x'}, request(tool='x' * 200)):
            self.assertEqual(decide(document, bad)['rule'], scope.RULE_INVALID)

    def test_unapproved_scope_still_asks_for_approval(self):
        document = research_scope({'crossref': 'allow'})
        result = scope.decide(document, None, request(), workspace_roots={}, now=NOW)
        self.assertEqual(result['ask']['reason'], 'scope_unapproved')


class AmendTests(unittest.TestCase):
    def test_add_to_scope_turns_ask_into_allow(self):
        document = research_scope({'unpaywall': 'ask', 'crossref': 'allow'})
        approval = approval_for(document)
        req = request('unpaywall', 'research_fulltext')
        asked = scope.decide(document, approval, req, workspace_roots={}, now=NOW)['ask']
        outcome = scope.apply_answer(document, approval, dict(asked, ask_id='a1'),
                                     {'ask_id': 'a1', 'request_digest': asked['request_digest'],
                                      'decision': 'add_to_scope', 'scope_digest': asked['patched_scope_digest']},
                                     now=NOW)
        self.assertEqual(outcome['change'], 'amended')
        self.assertEqual(outcome['scope']['research']['sources'], {'unpaywall': 'allow', 'crossref': 'allow'})
        self.assertEqual(outcome['scope']['version'], document['version'] + 1)
        self.assertEqual(scope.decide(outcome['scope'], outcome['approval'], req, workspace_roots={},
                                      now=NOW)['decision'], 'allow')

    def test_patches_never_turn_on_an_off_source(self):
        for current in ({'crossref': 'off'}, {}, None):
            document = base_scope() if current is None else research_scope(current)
            with self.subTest(current=current), self.assertRaises(ValueError):
                scope.merge_patch(document, {'research': {'sources': {'crossref': 'allow'}}})
        with self.assertRaises(ValueError):
            scope.merge_patch(research_scope({'crossref': 'ask'}), {'research': {'sources': {'crossref': 'ask'}}})


class DefaultTests(unittest.TestCase):
    def test_defaults_allow_every_usable_source(self):
        expected = {'semantic_scholar': 'allow', 'openalex': 'allow', 'arxiv': 'allow', 'crossref': 'allow',
                    'unpaywall': 'off'}
        project = scope.project_default('p1', research_sources=USABLE)
        self.assertEqual(project['research'], {'sources': expected})
        task = {'id': 't1', 'token_budget': 1000}
        self.assertEqual(scope.default(task, ['p1'], research_sources=USABLE)['research'], {'sources': expected})
        self.assertNotIn('research', scope.project_default('p1'))
        self.assertNotIn('research', scope.default(task, ['p1']))

    def test_research_default_has_no_project_files_commands_or_network(self):
        document = scope.research_default(research_sources=USABLE)
        self.assertIs(scope.validate(document, project_ids=[]), document)
        self.assertEqual(document['projects'], [])
        self.assertEqual(document['commands'], {'workspace': 'deny', 'allow': [], 'deny': []})
        self.assertEqual(document['network'], {'default': 'deny', 'allow_hosts': [], 'deny_hosts': []})
        self.assertEqual(document['web_search'], 'deny')
        self.assertEqual(document['research']['sources']['crossref'], 'allow')
        self.assertEqual(document['limits']['token_budget'], budget.DEFAULT_BUDGET)
        self.assertEqual(scope.research_default(token_budget=5000)['limits']['token_budget'], 5000)
        self.assertEqual(scope.research_default()['research'], {'sources': {}})

    def test_no_project_commands_and_files_are_denied(self):
        document = scope.research_default(research_sources=USABLE)
        document['task_id'] = 't1'
        approval = approval_for(document)
        command = {'category': 'command', 'argv': ['ls'], 'command': None, 'cwd': '.', 'sandbox': 'workspace',
                   'network': False, 'project_id': None}
        self.assertEqual(scope.decide(document, approval, command, workspace_roots={}, now=NOW)['decision'], 'deny')


class AuditTests(unittest.TestCase):
    def test_research_requests_keep_source_and_tool_only(self):
        clean = audit.sanitize_request({'category': 'research', 'source': 'crossref', 'tool': 'research_search',
                                      'query': 'my private question', 'id': '10.1/x'})
        self.assertEqual(clean, {'category': 'research', 'source': 'crossref', 'tool': 'research_search'})
        self.assertEqual(audit.REQUEST_FIELDS['research'], ('source', 'tool'))


if __name__ == '__main__':
    unittest.main()
