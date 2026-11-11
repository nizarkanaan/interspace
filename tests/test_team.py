"""Application team runs: actual snapshots/state, controlled providers, no paid calls."""
import copy
import json
from pathlib import Path
import sys
import threading
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app/backend'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_pilot
from test_orchestration import assignment, report
from service import Application
from provider import ProviderError
import orchestration as teams
import runner


class TeamProvider:
    def __init__(self,tasks=None):
        self.tasks=tasks or [assignment('researcher'),assignment('reviewer',['researcher'])]
        self.calls=[];self.events=[];self.fail=None;self.verdict='accept';self.answer=False
        self.entered=threading.Event();self.release=threading.Event();self.block=None
        self.before=None;self.review_summary=None;self.review_claim=None
    def run(self,prompt,schema,cwd,cancel):
        self.calls.append(prompt)
        if self.before:self.before(prompt)
        if self.block and self.block in prompt:
            self.entered.set();self.release.wait(4)
        if self.fail and self.fail in prompt:raise ProviderError('Fixture failure')
        if 'Purpose: synthesis' in prompt:return report(),{'input_tokens':2}
        if 'Role: Orchestrator' in prompt:
            return {'reply':'Fixture plan ready','action':'answer' if self.answer else 'propose_plan','tasks':[] if self.answer else copy.deepcopy(self.tasks)},{'input_tokens':1}
        result=report(self.verdict) if 'Role: Reviewer' in prompt else report()
        if 'Role: Reviewer' in prompt:
            if self.review_summary:result['summary']=self.review_summary
            if self.review_claim:result['findings'][0]['claim']=self.review_claim
        return result,{'input_tokens':3}
    def search(self,prompt,schema,cwd,cancel,on_event):
        self.calls.append(prompt)
        if self.before:self.before(prompt)
        on_event({'query':'public fixture query','action':'open_page','urls':['https://example.org/paper']})
        if self.fail:raise ProviderError('Search failed')
        return {'summary':'Public search','sources':[{'url':'https://example.org/paper','title':'Fixture paper','excerpt':'Observed public evidence'}],'questions':['Full paper not checked']},{'input_tokens':4}


class TeamTests(unittest.TestCase):
    setUp=test_pilot.PilotTests.setUp
    git=test_pilot.PilotTests.git
    def setup_app(self,tasks=None):
        self.provider=TeamProvider(tasks)
        self.app=Application(self.base/'app-data',provider=self.provider)
        self.pid=test_pilot.legacy_project(self.app, self.source)['project_id']
    def propose(self):
        self.app.handle('chat',{'scope':'project','project_id':self.pid,'text':'Review PRIVATE_GOAL_MARKER'})
        self.app.wait();return self.app.public()['pending']
    def start(self,plan=None):
        plan=plan or self.app.public()['pending']
        self.app.handle('start_plan',{'project_id':self.pid,'plan_id':plan['id'],'plan_digest':plan['digest']})
        self.app.wait();return self.app.public()['run']

    def test_plan_dispatches_assignments_then_synthesis_and_preserves_source(self):
        self.setup_app();before=runner.fingerprint(self.source);plan=self.propose()
        self.assertEqual(plan['kind'],'team')
        self.assertEqual(plan['limits']['max_calls'],3)
        run=self.start(plan)
        self.assertEqual(run['stage'],'completed')
        self.assertEqual([t['status'] for t in run['tasks']],['done','done'])
        self.assertEqual(len(self.provider.calls),4)
        self.assertEqual(len(run['jobs']),3)
        self.assertTrue(all(j['status']=='completed' for j in run['jobs']))
        self.assertTrue(run['combined']);self.assertTrue(run['verification']['unchanged'])
        self.assertEqual(before,runner.fingerprint(self.source))
        ref={'project_id':self.pid,'run_id':run['id'],'artifact_id':run['artifact_id']}
        self.app.handle('accept_report',ref)
        self.assertEqual(self.app.public()['run']['stage'],'accepted')
        with self.assertRaises(ValueError):self.app.handle('revise_run',ref)
        self.assertEqual(len(self.provider.calls),4)

    def test_direct_answer_has_no_team_or_extra_jobs(self):
        self.setup_app();self.provider.answer=True
        self.assertIsNone(self.propose())
        self.assertIsNone(self.app.public()['run'])
        self.assertEqual(len(self.provider.calls),1)

    def test_invalid_model_plan_cannot_be_started(self):
        self.setup_app([assignment('web_searcher'),assignment('researcher'),assignment('reviewer',['researcher'])])
        self.assertIsNone(self.propose())
        self.assertTrue(self.app.public()['error'])
        self.assertEqual(len(self.provider.calls),1)

    def test_exact_start_rejects_mutated_plan_and_duplicate_start(self):
        self.setup_app();plan=self.propose()
        self.app.state['projects'][self.pid]['pending']['tasks'][0]['objective']='Changed scope'
        with self.assertRaisesRegex(ValueError,'changed|stale|plan'):self.start(plan)
        self.assertEqual(len(self.provider.calls),1)
        plan=self.propose();self.start(plan)
        with self.assertRaises(ValueError):self.start(plan)
        self.assertEqual(len(self.provider.calls),5)

    def test_call_reservation_is_durable_before_provider_starts(self):
        self.setup_app();self.propose();seen=[]
        def before(prompt):
            saved=json.loads((self.app.storage/'state.json').read_text())
            run=runner.load(self.app.current_run)
            self.assertEqual(saved['active_run_id'],run['id'])
            self.assertEqual(run['jobs'][-1]['status'],'reserved')
            self.assertIsNone(run['jobs'][-1]['tokens'])
            seen.append(run['jobs'][-1]['id'])
        self.provider.before=before
        run=self.start()
        self.assertEqual(seen,['researcher','reviewer','synthesis'])
        self.assertEqual(run['stage'],'completed')

    def test_web_job_receives_only_public_assignment_and_review_receives_all_ancestors(self):
        tasks=[assignment('web_searcher'),assignment('researcher',['web_searcher']),assignment('reviewer',['researcher'])]
        self.setup_app(tasks);self.propose();run=self.start()
        web=self.provider.calls[1]
        for secret in ('PRIVATE_GOAL_MARKER','Current context','Committed evidence',str(self.source),'Previous report'):
            self.assertNotIn(secret,web)
        self.assertIn('Inspect evidence for web_searcher',web)
        reviewer=next(p for p in self.provider.calls if 'Role: Reviewer' in p)
        self.assertIn('Observed public evidence',reviewer)
        self.assertIn('web:'+run['id'],reviewer)
        self.assertEqual(len(run['jobs']),4)
        self.assertEqual(run['stage'],'completed')
        self.assertTrue(any(e['status']=='search_observed' for e in run['events']))

    def test_failed_worker_blocks_dependents_and_records_unknown_consumption(self):
        self.setup_app();self.propose();self.provider.fail='Role: Researcher'
        run=self.start()
        self.assertEqual(run['stage'],'failed')
        self.assertEqual([t['status'] for t in run['tasks']],['failed','blocked'])
        self.assertEqual(len(self.provider.calls),2)
        self.assertIsNone(run['jobs'][0]['tokens'])
        self.assertEqual(self.app.public()['usage'][-1]['outcome'],'failed')

    def test_synthesis_failure_preserves_specialist_artifacts(self):
        self.setup_app();self.propose();self.provider.fail='Purpose: synthesis'
        run=self.start()
        self.assertEqual(run['stage'],'failed')
        self.assertEqual(set(run['results']),{'researcher','reviewer'})
        self.assertIsNone(run['combined'])
        self.assertEqual(run['jobs'][-1]['status'],'failed')

    def test_reviewer_objections_cannot_be_erased_by_combined_result(self):
        self.setup_app();self.provider.verdict='revise';self.propose();run=self.start()
        self.assertEqual(run['stage'],'needs_revision')
        self.assertIn('Evidence exists',run['combined']['questions'])
        ref={'project_id':self.pid,'run_id':run['id'],'artifact_id':run['artifact_id']}
        with self.assertRaises(ValueError):self.app.handle('accept_report',ref)

    def test_unreviewed_completion_cannot_be_accepted(self):
        self.setup_app([assignment('researcher')]);self.propose();run=self.start()
        self.assertEqual(run['stage'],'completed_unreviewed')
        self.assertEqual(len(self.provider.calls),3)
        with self.assertRaises(ValueError):self.app.handle('accept_report',{'project_id':self.pid,'run_id':run['id'],'artifact_id':run['artifact_id']})

    def test_cancellation_after_project_switch_keeps_owner_and_partial_work(self):
        self.setup_app();plan=self.propose();self.provider.block='Role: Reviewer'
        self.app.handle('start_plan',{'project_id':self.pid,'plan_id':plan['id'],'plan_digest':plan['digest']})
        self.assertTrue(self.provider.entered.wait(2))
        # Register a second fixture in a separate Application, then copy only its registry entry.
        other=self.base/'other';other.mkdir()
        runner.git(other,'init','-q');(other/'README.md').write_text('Other fixture')
        runner.git(other,'add','.');runner.git(other,'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','Other')
        import projects
        b=projects.new_project(other);b['context_path']='README.md';self.app.state['projects'][b['id']]=b
        self.app.handle('switch_project',{'project_id':b['id']})
        self.app.handle('cancel',{});self.provider.release.set();self.app.wait()
        self.assertIsNone(self.app.public()['run']);self.assertEqual(self.app.public()['error'],'')
        self.app.handle('switch_project',{'project_id':self.pid});run=self.app.public()['run']
        self.assertEqual(run['stage'],'cancelled')
        self.assertEqual(set(run['results']),{'researcher'})
        self.assertEqual(run['tasks'][1]['status'],'cancelled')
        self.assertTrue(all(u['project_id']==self.pid for u in self.app.public()['usage']))

    def test_restart_marks_reserved_jobs_interrupted_without_retry(self):
        self.setup_app();plan=self.propose()
        project=self.app.state['projects'][self.pid]
        run=teams.prepare(project,plan,self.app.storage/'runs')
        record=runner.load(run);record['stage']='running';record['tasks'][0]['status']='running'
        record['jobs']=[{'id':'researcher','status':'reserved','tokens':None}];runner.save(run/'run.json',record)
        project.update(run_id=run.name,run_ids=[run.name]);self.app.persist()
        reopened=Application(self.app.storage,provider=self.provider)
        self.assertEqual(reopened.public()['run']['stage'],'interrupted')
        self.assertEqual(reopened.public()['run']['jobs'][0]['status'],'interrupted')
        self.assertEqual(len(self.provider.calls),1)

    def test_source_prompt_has_no_phantom_trailing_line_and_uses_lf_boundaries(self):
        self.setup_app()
        (self.source/'README.md').write_text('One\u2028same line\nTwo\n')
        self.git('add','README.md');self.git('commit','-qm','LF fixture')
        self.propose();self.start()
        prompt=next(p for p in self.provider.calls if 'Role: Researcher' in p)
        self.assertIn('SOURCE README.md (2 LF lines)\n1 One\u2028same line\n2 Two',prompt)
        self.assertNotIn('\n3 ',prompt)

    def test_canonical_source_replacement_invalidates_start(self):
        import shutil
        self.setup_app();plan=self.propose()
        moved=self.base/'original';self.source.rename(moved)
        replacement=self.base/'replacement';shutil.copytree(moved,replacement)
        self.source.symlink_to(replacement,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'stale|changed'):self.start(plan)
        self.assertEqual(len(self.provider.calls),1)

    def test_reserved_job_cannot_be_invoked_twice(self):
        import team
        self.setup_app();self.propose();run=self.start()
        with self.assertRaisesRegex(ValueError,'reserved|ceiling'):
            team.invoke(self.app,self.app.state['projects'][self.pid],self.app.storage/'runs'/run['id'],'researcher','Researcher','No duplicate',{})
        self.assertEqual(len(self.provider.calls),4)

    def test_malformed_saved_team_is_unavailable_instead_of_breaking_ui(self):
        self.setup_app();self.propose();run=self.start()
        path=self.app.storage/'runs'/run['id']
        saved=runner.load(path);saved.pop('tasks');runner.save(path/'run.json',saved)
        public=self.app.public()
        self.assertIsNone(public['run'])
        self.assertIn('unavailable',public['error'])
        self.assertEqual(public['runs'][0]['stage'],'unavailable')

    def test_long_reviewer_objections_remain_readable_and_untruncated(self):
        self.setup_app();self.provider.verdict='revise'
        self.provider.review_summary='Summary objection '+('x'*2200)
        self.provider.review_claim='Finding objection '+('y'*2500)
        self.propose();run=self.start()
        self.assertIsNotNone(run)
        self.assertEqual(run['stage'],'needs_revision')
        self.assertIn(self.provider.review_summary,run['combined']['questions'])
        self.assertIn(self.provider.review_claim,run['combined']['questions'])
        restored=Application(self.app.storage,provider=self.provider).public()['run']
        self.assertEqual(restored['stage'],'needs_revision')

    def test_terminal_run_survives_crash_before_registry_active_flag_clears(self):
        for reviewed in (False,True):
            with self.subTest(reviewed=reviewed):
                self.setup_app(None if reviewed else [assignment('researcher')])
                self.propose();run=self.start()
                self.app.state.update(active='Orchestrator',active_project_id=self.pid,active_run_id=run['id'])
                self.app.persist()
                restored=Application(self.app.storage,provider=self.provider).public()
                self.assertEqual(restored['run']['stage'], 'completed' if reviewed else 'completed_unreviewed')
                self.assertEqual(restored['run']['combined'],run['combined'])
                self.assertEqual(restored['error'],'')
