"""Research tools in the scheduler, tasks without a project and their outputs (research/tasks.md, tools.md).

Fake runtimes and a fake research dispatch over fake sources: no provider, no network, no Keychain.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
sys.path.insert(0, str(ROOT / 'tests'))

import scheduler
from research import citations
from runtime import mcp_bridge
from agent_fakes import FakeAudit, FakeRuntime, FakeScope, FakeWorkspaces, MemoryStore, default_script, wait_for

USAGE = {'input_tokens': 100, 'output_tokens': 20}
LECUN = {'v': 1, 'title': 'Deep learning', 'authors': ['Yann LeCun', 'Yoshua Bengio'], 'year': 2015, 'venue': 'Nature',
         'doi': '10.1038/nature14539', 'arxiv_id': None, 's2_id': None, 'openalex_id': None, 'abstract': None,
         'citation_count': 1, 'url': None, 'oa_url': None, 'retracted': False, 'sources': ['crossref']}
VASWANI = dict(LECUN, title='Attention Is All You Need', authors=['Ashish Vaswani'], year=2017, venue=None,
               doi='10.48550/arxiv.1706.03762', arxiv_id='1706.03762', sources=['arxiv'])
WAKEFIELD = dict(LECUN, title='RETRACTED: Ileal-lymphoid-nodular hyperplasia', authors=['A. J. Wakefield'], year=1998,
                 doi='10.1016/s0140-6736(97)11096-0', retracted=True)
BIBTEX = {'10.1038/nature14539': '@article{LeCun_2015, title={Deep learning}, year={2015}}',
          'arxiv:1706.03762': '@misc{vaswani2017, title={Attention Is All You Need}, year={2017}}'}


class FakeSource:
    def __init__(self, name):
        self.name = name

    def paper(self, identifier):
        known = {('crossref', '10.1038/nature14539'): LECUN, ('crossref', '10.1016/s0140-6736(97)11096-0'): WAKEFIELD,
                 ('arxiv', 'arXiv:1706.03762'): VASWANI}
        return known.get((self.name, identifier))

    def search(self, query, *, limit=10, **kwargs):
        return []


class FakeResearch:
    """The 1B `research.dispatch` shape, over fake sources. Records what it saw."""

    def __init__(self):
        self.calls = []
        self.fail = None
        self.result = None
        self.cached = ()

    def __call__(self, ctx, name, arguments):
        self.calls.append((name, arguments))
        if self.fail is not None:
            raise self.fail
        if self.result is not None:
            return self.result
        if name == 'verify_citations':
            sources = {n: FakeSource(n) for n in ('crossref', 'openalex', 'arxiv', 'semantic_scholar')}
            lookup = citations.source_lookup(
                sources, lambda source: ctx.authorize({'category': 'research', 'source': source,
                                                       'tool': name})['decision'] == 'allow')
            return citations.check(arguments['references'], lookup)
        searched, skipped = [], []
        for source in arguments.get('sources') or ['crossref', 'arxiv']:
            decision = ctx.authorize({'category': 'research', 'source': source, 'tool': name})
            if decision['decision'] != 'allow':
                skipped.append({'source': source, 'reason': 'denied'})
                continue
            searched.append(source)
            if source in self.cached:
                ctx.note_cached(source)  # The cache answered: no request went out.
            else:
                ctx.note_call(source)
        if name == 'research_bibtex':
            return {'entries': [{'id': i, 'bibtex': BIBTEX.get(i.lower()), 'error': None} for i in arguments['ids']]}
        return {'papers': [LECUN], 'searched': searched, 'skipped': skipped}


class ResearchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.results = []

    def make(self, parent_script, child=None, usage_interval_s=0.2):
        self.scope = FakeScope()
        self.audit = FakeAudit()
        self.store = MemoryStore(self.scope)
        self.store.add_project('p1')
        self.emitted = []
        self.events = scheduler.EventLog(self.root / 'tasks', forward=self.emitted.append)
        self.research = FakeResearch()
        self.parent_runtime = FakeRuntime(parent_script)
        self.parent_runtime.name = 'claude'
        self.child_runtime = FakeRuntime(child or default_script)
        self.locks = scheduler.Locks()
        self.workspaces = FakeWorkspaces(self.root / 'workspaces')

        def factory(task_id):
            return self.parent_runtime if self.store.task(task_id).get('role') == 'orchestrator' else self.child_runtime
        self.sched = scheduler.Scheduler(
            max_running=4, runtime_factory=factory, policy=self.scope, audit=self.audit, events=self.events,
            budget_gate=scheduler.BudgetGate(self.store), locks=self.locks, clock=time.time, tasks=self.store,
            workspaces=self.workspaces, interrupt_grace_s=0.2, tick_s=0.01,
            research_dispatch=self.research, scratch_root=self.root / 'research-runs',
            research_usage_interval_s=usage_interval_s)
        self.addCleanup(self.sched.shutdown, 5)
        return self.sched

    def run_task(self, task_id='r1', project_id=None, text='Related work on deep learning'):
        self.sched.submit(task_id, project_id, text, None)
        wait_for(lambda: self.store.task(task_id)['agent']['state'] in scheduler.TERMINAL + ('idle',),
                 message=task_id + ' finished')

    def events_of(self, task_id, kind=None):
        found = self.events.read(task_id, 0, 1000)['events']
        return [e for e in found if kind is None or e['kind'] == kind]


def answering(results, calls, text='Answer citing [1].'):
    def script(session, text_in, ctx):
        for name, arguments in calls:
            results.append(ctx.call_tool(name, arguments))
        ctx.emit('message', {'role': 'assistant', 'text': text, 'final': True}, item_id='m-final')
        return {'status': 'completed', 'usage': dict(USAGE), 'error': None}
    return script


class ToolListTests(ResearchCase):
    def test_research_task_sessions_get_research_tools(self):
        seen = {}

        def parent(session, text, ctx):
            seen['parent'] = ([t['name'] for t in ctx.tools()], ctx.access, ctx.workspaces, ctx.primary_workspace,
                              ctx.scratch, ctx.research_only)
            return answering(self.results, [])(session, text, ctx)
        self.make(parent)
        self.store.add_research_task('r1')
        self.run_task()
        names, access, workspaces, primary, scratch, research_only = seen['parent']
        self.assertEqual(names, ['propose_team', 'team_status', 'wait_for', 'message_member']
                         + list(mcp_bridge.RESEARCH_TOOL_NAMES))
        self.assertEqual((access, workspaces, research_only), ('read', {}, True))
        self.assertEqual(primary, str(self.root / 'research-runs' / 'r1'))
        self.assertEqual(scratch, primary)
        self.assertTrue(os.path.isdir(scratch))
        self.assertFalse(os.path.exists(os.path.join(scratch, '.git')))
        self.assertEqual(self.workspaces.prepared, [])
        self.assertEqual(self.workspaces.published, [])

    def test_project_task_with_research_on_gets_research_tools_and_without_does_not(self):
        seen = []

        def parent(session, text, ctx):
            seen.append(([t['name'] for t in ctx.tools()], ctx.research_only, ctx.scratch))
            return answering(self.results, [])(session, text, ctx)
        self.make(parent)
        plain = self.store.add_task('t1', 'p1')
        plain.update(role='orchestrator')
        self.run_task('t1', 'p1')
        task = self.store.add_task('t2', 'p1')
        task.update(role='orchestrator')
        task['scope']['research'] = {'sources': {'crossref': 'ask', 'arxiv': 'off'}}
        task['scope_approval']['scope_digest'] = self.scope.digest(task['scope'])
        self.run_task('t2', 'p1')
        self.assertEqual(seen[0], (['propose_team', 'team_status', 'wait_for', 'message_member'], False, None))
        self.assertEqual(seen[1][0][4:], list(mcp_bridge.RESEARCH_TOOL_NAMES))
        off = self.store.add_task('t3', 'p1')
        off['scope']['research'] = {'sources': {'crossref': 'off'}}
        off['scope_approval']['scope_digest'] = self.scope.digest(off['scope'])
        names = []
        self.parent_runtime.script = lambda s, t, ctx: (names.append([x['name'] for x in ctx.tools()]),
                                                        default_script(s, t, ctx))[1]
        self.child_runtime.script = self.parent_runtime.script
        self.run_task('t3', 'p1')
        self.assertEqual(names, [[]])

    def test_unknown_and_unoffered_tools_are_refused(self):
        errors = []

        def parent(session, text, ctx):
            for name in ('rm_rf', 'research_search'):
                try:
                    ctx.call_tool(name, {'query': 'x'})
                except ValueError as error:
                    errors.append(str(error))
            return default_script(session, text, ctx)
        self.make(parent, child=parent)
        self.store.add_task('t1', 'p1')  # No research key, not an Orchestrator.
        self.run_task('t1', 'p1')
        self.assertEqual(errors, ['Unknown tool.', 'Unknown tool.'])
        self.assertEqual(self.research.calls, [])


class CallTests(ResearchCase):
    def test_a_research_call_is_authorized_audited_counted_and_shown(self):
        self.make(answering(self.results, [('research_search', {'query': 'deep learning', 'limit': 5})]))
        self.store.add_research_task('r1', sources={'crossref': 'allow', 'arxiv': 'allow'})
        self.research.cached = ('arxiv',)
        self.run_task()
        result = self.results[0]
        self.assertTrue(result['ok'])
        self.assertEqual((result['searched'], result['papers'][0]['title']), (['crossref', 'arxiv'], 'Deep learning'))
        decisions = [r for r in self.audit.records if r['kind'] == 'decision' and (r['request'] or {}).get('category') == 'research']
        self.assertEqual([r['request'] for r in decisions],
                         [{'category': 'research', 'source': 'crossref', 'tool': 'research_search'},
                          {'category': 'research', 'source': 'arxiv', 'tool': 'research_search'}])
        actions = [r for r in self.audit.records if r['kind'] == 'action']
        self.assertEqual([(r['request']['source'], r['outcome']) for r in actions],
                         [('crossref', 'succeeded'), ('arxiv', 'succeeded')])
        self.assertTrue(all(r['call_id'] == decisions[0]['call_id'] for r in decisions + actions))
        call = self.events_of('r1', 'tool_call')[0]['data']
        self.assertEqual((call['category'], call['tool'], call['input']),
                         ('research', 'research_search', {'tool': 'research_search', 'query': 'deep learning'}))
        shown = self.events_of('r1', 'tool_result')[0]['data']
        self.assertEqual(shown['status'], 'ok')
        self.assertEqual(json.loads(shown['output']['text'])['searched'], ['crossref', 'arxiv'])
        wait_for(lambda: self.events_of('r1', 'research_usage'), message='research_usage')
        wait_for(lambda: self.events_of('r1', 'research_usage')[-1]['data'] ==
                 {'calls': {'crossref': 1}, 'cached': {'arxiv': 1}}, message='final usage')
        self.assertEqual(self.store.task('r1')['agent']['research_usage'],
                         {'calls': {'crossref': 1}, 'cached': {'arxiv': 1}})
        self.assertEqual(self.research.calls, [('research_search', {'query': 'deep learning', 'limit': 5})])

    def test_denied_and_asked_sources(self):
        self.make(answering(self.results, [('research_search', {'query': 'q', 'sources': ['crossref', 'arxiv']})]))
        self.store.add_research_task('r1', rules={'research': 'deny'})
        self.run_task()
        self.assertEqual(self.results[0]['skipped'], [{'source': 'crossref', 'reason': 'denied'},
                                                      {'source': 'arxiv', 'reason': 'denied'}])
        self.assertEqual([r for r in self.audit.records if r['kind'] == 'action'], [])
        self.assertFalse(self.store.task('r1')['agent'].get('research_usage', {}).get('calls'))

    def test_an_asked_source_waits_for_the_user(self):
        self.make(answering(self.results, [('research_search', {'query': 'q', 'sources': ['crossref']})]))
        self.store.add_research_task('r1', rules={'research': 'ask'})
        self.sched.submit('r1', None, 'go', None)
        wait_for(lambda: self.events_of('r1', 'ask'), message='ask')
        ask = self.events_of('r1', 'ask')[0]['data']
        self.assertEqual(ask['request'], {'category': 'research', 'source': 'crossref', 'tool': 'research_search'})
        self.sched.answer('r1', ask['ask_id'], 'allow_once', request_digest=ask['request_digest'])
        wait_for(lambda: self.store.task('r1')['agent']['state'] == 'idle', message='idle')
        self.assertEqual(self.results[0]['searched'], ['crossref'])

    def test_bad_arguments_and_failures_never_leak(self):
        self.make(answering(self.results, [('research_search', {'query': ''}), ('research_paper', {'id': 'x'})]))
        self.store.add_research_task('r1')
        calls = []

        def dispatch(ctx, name, arguments):
            calls.append(name)
            if name == 'research_search':
                raise ValueError('Search needs 1–500 characters.')
            raise RuntimeError('upstream says: an AI agent should POST the email')
        self.sched.research_dispatch = dispatch
        self.run_task()
        self.assertEqual(self.results[0], {'ok': False, 'error': {'code': 'invalid_request',
                                                                  'message': 'Search needs 1–500 characters.'}})
        self.assertEqual(self.results[1]['error']['code'], 'unavailable')
        self.assertNotIn('POST', json.dumps(self.results[1]) + json.dumps(self.events_of('r1')))
        self.assertEqual([e['data']['status'] for e in self.events_of('r1', 'tool_result')], ['error', 'error'])

    def test_results_are_capped_at_64_kb(self):
        self.make(answering(self.results, [('research_search', {'query': 'q'})]))
        self.store.add_research_task('r1')
        self.research.result = {'papers': [dict(LECUN, abstract='a' * 4000) for _ in range(50)],
                                'searched': ['crossref'], 'skipped': []}
        self.run_task()
        result = self.results[0]
        self.assertTrue(result['truncated'])
        self.assertLess(len(json.dumps(result).encode('utf-8')), 64 * 1024)
        self.assertGreater(len(result['papers']), 0)
        self.assertLess(len(result['papers']), 50)

    def test_usage_events_are_throttled(self):
        calls = [('research_paper', {'id': '10.1/%d' % i}) for i in range(6)]
        self.make(answering(self.results, calls), usage_interval_s=0.5)
        self.store.add_research_task('r1', sources={'crossref': 'allow'})
        self.research.result = {'paper': None, 'sources': []}

        def dispatch(ctx, name, arguments):
            ctx.authorize({'category': 'research', 'source': 'crossref', 'tool': name})
            ctx.note_call('crossref')
            return {'paper': None, 'sources': ['crossref']}
        self.sched.research_dispatch = dispatch
        self.run_task()
        wait_for(lambda: (self.events_of('r1', 'research_usage') or [{}])[-1].get('data', {}).get('calls')
                 == {'crossref': 6}, message='trailing usage')
        self.assertLessEqual(len(self.events_of('r1', 'research_usage')), 3)

    def test_children_are_counted_on_the_root_task(self):
        def child(session, text, ctx):
            ctx.call_tool('research_search', {'query': 'q', 'sources': ['crossref']})
            return default_script(session, text, ctx)

        def parent(session, text, ctx):
            proposed = ctx.call_tool('propose_team', {'summary': 's', 'members': [
                {'role': 'researcher', 'brief': 'Search.'}]})
            self.results.append(proposed)
            ctx.call_tool('wait_for', {'team_id': proposed['team_id'], 'timeout_s': 10})
            return answering(self.results, [])(session, text, ctx)
        self.make(parent, child=child)
        self.store.add_research_task('r1')
        self.sched.submit('r1', None, 'go', None)
        wait_for(lambda: self.events_of('r1', 'team_proposed'), message='proposal')
        team = self.events_of('r1', 'team_proposed')[0]['data']
        self.sched.orchestrator.answer({'task_id': 'r1', 'team_id': team['team_id'], 'decision': 'approve'})
        wait_for(lambda: self.store.task('r1')['agent']['state'] == 'idle', message='idle')
        children = [t for t in self.store.agent_tasks() if t.get('parent_task_id') == 'r1']
        self.assertEqual(len(children), 1)
        self.assertEqual((children[0]['kind'], children[0]['agent']['project_id'], children[0]['access']),
                         ('research', None, 'read'))
        self.assertIn(children[0]['id'], self.store.state['research']['tasks'])
        self.assertTrue(os.path.isdir(self.root / 'research-runs' / children[0]['id']))
        self.assertEqual(self.store.task('r1')['agent']['research_usage']['calls'], {'crossref': 1})
        self.assertEqual(self.locks.holders(), {})


class NoProjectTests(ResearchCase):
    def test_write_members_are_refused(self):
        def parent(session, text, ctx):
            self.results.append(ctx.call_tool('propose_team', {'summary': 's', 'members': [
                {'role': 'implementer', 'brief': 'Edit.'}]}))
            return default_script(session, text, ctx)
        self.make(parent)
        self.store.add_research_task('r1')
        self.run_task()
        self.assertEqual(self.results[0]['error']['message'],
                         'Research tasks have no project to write to. Use a project task for code.')
        self.assertEqual(self.events_of('r1', 'team_proposed'), [])

    def test_no_scratch_root_fails_closed(self):
        self.make(answering(self.results, []))
        self.sched.scratch_root = None
        self.store.add_research_task('r1')
        self.run_task()
        self.assertEqual(self.store.task('r1')['agent']['reason'], 'workspace_failed')


class OutputTests(ResearchCase):
    REFS = [{'title': 'Deep learning', 'doi': '10.1038/nature14539', 'year': 2015},
            {'title': 'Attention is all you need', 'arxiv_id': '1706.03762', 'year': 2019},
            {'title': 'Ileal-lymphoid-nodular hyperplasia', 'doi': '10.1016/s0140-6736(97)11096-0'},
            {'title': 'Quantum llamas in practice', 'doi': '10.9999/none'}]

    def outputs(self, task_id='r1'):
        return self.root / 'tasks' / task_id / 'outputs'

    def test_final_answer_writes_report_and_verified_bibtex(self):
        self.make(answering(self.results, [('research_bibtex', {'ids': ['10.1038/nature14539']}),
                                           ('verify_citations', {'references': self.REFS})],
                            text='# Related work\n\nDeep learning [1].'))
        self.store.add_research_task('r1', sources={'crossref': 'allow', 'arxiv': 'allow', 'openalex': 'allow',
                                                    'semantic_scholar': 'allow'})
        self.run_task()
        report = self.results[1]
        self.assertEqual(report['summary'], {'verified': 1, 'mismatch': 1, 'not_found': 1, 'retracted': 1,
                                             'unchecked': 0})
        card = self.events_of('r1', 'citation_report')
        self.assertEqual(len(card), 1)
        self.assertEqual(card[0]['data']['summary'], report['summary'])
        self.assertEqual((self.outputs() / 'report.md').read_text(), '# Related work\n\nDeep learning [1].')
        bib = (self.outputs() / 'references.bib').read_text()
        self.assertIn(BIBTEX['10.1038/nature14539'], bib)
        self.assertIn(BIBTEX['arxiv:1706.03762'], bib)  # Fetched at the end for the mismatch reference.
        self.assertIn('% mismatch (year): Attention is all you need', bib)
        self.assertIn('% Left out, retracted: Ileal-lymphoid-nodular hyperplasia', bib)
        self.assertIn('% Left out, not found: Quantum llamas in practice', bib)
        self.assertNotIn('Wakefield', bib)
        self.assertEqual(self.research.calls[-1], ('research_bibtex', {'ids': ['arXiv:1706.03762']}))
        outputs = self.events_of('r1', 'outputs')[-1]['data']['outputs']
        self.assertEqual([(o['name'], o['kind']) for o in outputs], [('report.md', 'report'), ('references.bib', 'bibtex')])
        self.assertEqual(outputs[1]['bytes'], len(bib.encode('utf-8')))

    def test_without_a_citation_report_only_the_report_is_written(self):
        self.make(answering(self.results, [], text='No papers needed.'))
        self.store.add_research_task('r1')
        self.run_task()
        self.assertEqual(sorted(os.listdir(self.outputs())), ['report.md'])
        self.assertEqual([o['name'] for o in self.events_of('r1', 'outputs')[-1]['data']['outputs']], ['report.md'])

    def test_a_bibtex_entry_the_sources_cannot_give_is_built_from_the_verified_record(self):
        self.make(answering(self.results, [('verify_citations', {'references': self.REFS[:1]})]))
        self.store.add_research_task('r1', sources={'crossref': 'allow'})
        original = self.research.__call__

        def dispatch(ctx, name, arguments):
            if name == 'research_bibtex':
                return {'entries': [{'id': i, 'bibtex': None, 'error': 'not_found'} for i in arguments['ids']]}
            return original(ctx, name, arguments)
        self.sched.research_dispatch = dispatch
        self.run_task()
        bib = (self.outputs() / 'references.bib').read_text()
        self.assertIn('% Built by Interspace from the verified record', bib)
        self.assertIn('title = {Deep learning}', bib)
        self.assertIn('doi = {10.1038/nature14539}', bib)

    def test_the_schedulers_own_bibtex_fetch_is_no_agent_tool_card_but_is_audited(self):
        self.make(answering(self.results, [('verify_citations', {'references': self.REFS[:2]})]))
        self.store.add_research_task('r1', sources={'crossref': 'allow', 'arxiv': 'allow'})
        self.run_task()
        self.assertEqual(self.research.calls[-1][0], 'research_bibtex')  # Fetched at the end, for references.bib.
        tools = [e['data'].get('tool') for e in self.events_of('r1', 'tool_call')]
        self.assertEqual(tools, ['verify_citations'])
        self.assertEqual(len(self.events_of('r1', 'tool_result')), 1)
        bibtex = [r for r in self.audit.records if (r.get('request') or {}).get('tool') == 'research_bibtex']
        self.assertEqual({r['kind'] for r in bibtex}, {'decision', 'action'})
        self.assertIn(BIBTEX['10.1038/nature14539'], (self.outputs() / 'references.bib').read_text())

    def test_a_report_too_large_for_the_agent_still_gives_every_reference_to_references_bib(self):
        refs = [{'title': 'Deep learning', 'doi': '10.1038/nature14539', 'year': 2015, 'raw': 'r%d ' % i + 'x' * 3900}
                for i in range(60)] + [{'title': 'Quantum llamas in practice', 'doi': '10.9999/none'}]
        self.make(answering(self.results, [('verify_citations', {'references': refs})]))
        self.store.add_research_task('r1', sources={'crossref': 'allow'})
        self.run_task()
        result = self.results[0]
        self.assertTrue(result['truncated'])
        self.assertLessEqual(len(json.dumps(result).encode('utf-8')), 64 * 1024)
        self.assertEqual(result['summary']['verified'], 60)
        card = self.events_of('r1', 'citation_report')[0]['data']
        self.assertEqual(card['summary'], result['summary'])
        self.assertTrue(card['truncated'])
        self.assertIn('references', card)
        bib = (self.outputs() / 'references.bib').read_text()
        self.assertIn('% Verified: 60.', bib)
        self.assertIn('% Left out, not found: Quantum llamas in practice', bib)

    def test_a_long_final_answer_is_saved_whole(self):
        text = '# Review\n\n' + ('A long paragraph of findings. ' * 4000)
        self.make(answering(self.results, [], text=text))
        self.store.add_research_task('r1')
        self.run_task()
        self.assertEqual((self.outputs() / 'report.md').read_text(), text)

    def test_project_tasks_and_children_write_no_outputs(self):
        self.make(answering(self.results, []))
        task = self.store.add_task('t1', 'p1')
        task.update(role='orchestrator')
        self.run_task('t1', 'p1')
        self.assertFalse(self.outputs('t1').exists())

    def test_failed_turns_write_no_outputs(self):
        def parent(session, text, ctx):
            ctx.emit('message', {'role': 'assistant', 'text': 'Half', 'final': True}, item_id='m1')
            return {'status': 'failed', 'usage': None, 'error': {'code': 'runtime_exited', 'message': 'x'}}
        self.make(parent)
        self.store.add_research_task('r1')
        self.run_task()
        self.assertFalse(self.outputs().exists())


if __name__ == '__main__':
    unittest.main()
