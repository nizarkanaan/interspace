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

    def test_cited_proposal_reaches_reviewer_and_synthesis(self):
        self.setup_app()
        original=self.provider.run
        def propose(prompt,*args):
            result,usage=original(prompt,*args)
            if 'Role: Researcher' in prompt:
                result['findings'][0].update(kind='proposal',claim='Proposed change motivated by the source')
            return result,usage
        self.provider.run=propose
        self.propose();run=self.start()
        self.assertEqual(run['stage'],'completed')
        self.assertEqual(run['results']['researcher']['findings'][0]['kind'],'proposal')
        reviewer=next(p for p in self.provider.calls if 'Role: Reviewer' in p)
        self.assertIn('Proposed change motivated by the source',reviewer)
        self.assertEqual([j['id'] for j in run['jobs']],['researcher','reviewer','synthesis'])

    def test_uncited_proposal_stops_without_retry_or_dependent_calls(self):
        self.setup_app();before=runner.fingerprint(self.source)
        original=self.provider.run
        def propose(prompt,*args):
            result,usage=original(prompt,*args)
            if 'Role: Researcher' in prompt:
                result['findings'][0].update(kind='proposal',evidence=[])
            return result,usage
        self.provider.run=propose
        self.propose();run=self.start()
        self.assertEqual(run['stage'],'failed')
        self.assertEqual([t['status'] for t in run['tasks']],['failed','blocked'])
        self.assertEqual(len(self.provider.calls),2)
        self.assertEqual(len(run['jobs']),1)
        self.assertEqual(run['results'],{})
        self.assertIsNone(run['combined'])
        self.assertEqual(before,runner.fingerprint(self.source))

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


class ExpandedTeamTests(unittest.TestCase):
    setUp=test_pilot.PilotTests.setUp
    git=test_pilot.PilotTests.git

    def setup_team(self,verdicts=('accept','accept'),limit=8):
        from types import SimpleNamespace
        from test_orchestration import named_assignment
        self.provider=TeamProvider()
        self.project={'id':'project-a','name':'Fixture','source_path':str(self.source),
                      'context_path':'docs/PROJECT_CONTEXT.md','run_id':None,'run_ids':[],'thread':[]}
        self.task={'id':'user-task-a','run_id':None,'run_ids':[],'thread':[]}
        self.storage=self.base/'app-data';self.storage.mkdir()
        self.app=SimpleNamespace(storage=self.storage,lock=threading.RLock(),cancel=threading.Event(),
                                 state={'usage':[]},provider=self.provider,current_run=None,publish=lambda:None)
        tasks=[named_assignment('search_a','web_searcher'),named_assignment('search_b','web_searcher'),
               named_assignment('analysis_a','researcher',['search_a']),named_assignment('analysis_b','researcher',['search_b']),
               named_assignment('review_a','reviewer',['analysis_a','analysis_b']),
               named_assignment('review_b','reviewer',['analysis_a','analysis_b'])]
        tasks[-1]['objective']='Review second branch'
        self.plan=teams.make_plan(self.project,self.git('rev-parse','HEAD'),'Private fixture goal',tasks,
                                  specialist_limit=limit,task_id=self.task['id'])
        original_run=self.provider.run
        def run(prompt,*args):
            result,usage=original_run(prompt,*args)
            if 'Role: Reviewer' in prompt:
                # Objectives distinguish independent reviewers without relying on runtime call order.
                identity='review_b' if 'Assignment: Review second branch' in prompt else 'review_a'
                result.update(verdict=verdicts[1 if identity=='review_b' else 0],summary='Objection '+identity)
                result['findings'][0]['claim']='Finding '+identity
            return result,usage
        self.provider.run=run
        def search(prompt,schema,cwd,cancel,on_event):
            self.provider.calls.append(prompt)
            identity='search_b' if 'search_b' in prompt else 'search_a'
            urls=['https://example.org/'+identity+'/'+str(i) for i in range(10)]
            on_event({'query':'public fixture','action':'open_page','urls':urls})
            return {'summary':identity,'sources':[{'url':u,'title':'Paper','excerpt':'Excerpt '+identity} for u in urls],
                    'questions':[]},{'input_tokens':4}
        self.provider.search=search

    def execute(self):
        import team
        team.execute(self.app,self.project,self.plan,task=self.task)
        return runner.load(self.app.current_run)

    def test_repeated_roles_are_task_owned_durable_and_reloadable(self):
        import team
        self.setup_team();before=runner.fingerprint(self.source);record=self.execute()
        self.assertEqual(record['stage'],'completed')
        self.assertEqual(record['task_id'],'user-task-a')
        self.assertEqual(len(record['evidence']),20)
        self.assertEqual([j['id'] for j in record['jobs']],['search_a','search_b','analysis_a','analysis_b','review_a','review_b','synthesis'])
        self.assertEqual(self.task['run_ids'],[record['id']]);self.assertEqual(self.project['run_ids'],[])
        self.assertEqual(len(self.task['thread']),1);self.assertEqual(self.project['thread'],[])
        self.assertTrue(all(u['task_id']=='user-task-a' for u in self.app.state['usage']))
        self.assertEqual([u['assignment_id'] for u in self.app.state['usage']],['search_a','search_b','analysis_a','analysis_b','review_a','review_b','synthesis'])
        analysis_a=next(p for p in self.provider.calls if 'Role: Researcher' in p and 'Inspect evidence for researcher' in p)
        self.assertIn('Excerpt search_a',analysis_a);self.assertNotIn('Excerpt search_b',analysis_a)
        teams.validate_record(runner.load(self.app.current_run))
        with self.assertRaises(ValueError):team.invoke(self.app,self.project,self.app.current_run,'analysis_a','Researcher','duplicate',{})
        self.assertEqual(before,runner.fingerprint(self.source))
        self.assertTrue(teams.accept(self.app.current_run,{'run_id':record['id'],'artifact_id':teams.artifact_id(record)}))

    def test_all_reviewers_aggregate_with_blocked_then_revise_precedence(self):
        for verdicts,want in ((('blocked','accept'),'blocked'),(('revise','accept'),'needs_revision'),
                              (('accept','blocked'),'blocked'),(('blocked','revise'),'blocked')):
            with self.subTest(verdicts=verdicts):
                self.setup_team(verdicts);record=self.execute()
                self.assertEqual(record['stage'],want)
                for index,verdict in enumerate(verdicts):
                    if verdict!='accept':
                        identity=('review_a','review_b')[index]
                        self.assertIn('Objection '+identity,record['combined']['questions'])
                        self.assertIn('Finding '+identity,record['combined']['questions'])
                teams.validate_record(record)
                # Next subcase gets separate disposable app storage.
                self.storage.rename(self.base/('used-'+str(len(list(self.base.glob('used-*'))))))

    def test_repeated_role_failure_and_cancellation_never_retry_or_reserve_later_jobs(self):
        self.setup_team();original=self.provider.run
        def fail_second(prompt,*args):
            if 'Role: Researcher' in prompt and 'search_b' in prompt:raise ProviderError('Second researcher failed')
            return original(prompt,*args)
        self.provider.run=fail_second
        with self.assertRaises(ProviderError):self.execute()
        record=runner.load(self.app.current_run);teams.interrupt(record,'failed','Second researcher failed')
        self.assertEqual([j['id'] for j in record['jobs']],['search_a','search_b','analysis_a','analysis_b'])
        self.assertEqual(record['jobs'][-1]['status'],'failed')
        self.assertEqual(set(record['results']),{'search_a','search_b','analysis_a'})
        self.assertEqual([t['status'] for t in record['tasks']][-3:],['failed','blocked','blocked'])
        runner.save(self.app.current_run/'run.json',record);teams.validate_record(record)
        self.storage.rename(self.base/'failed-data');self.setup_team();original=self.provider.run
        def cancel_second(prompt,*args):
            result=original(prompt,*args)
            if 'Role: Researcher' in prompt and 'search_b' in prompt:self.app.cancel.set()
            return result
        self.provider.run=cancel_second
        with self.assertRaises(ProviderError):self.execute()
        record=runner.load(self.app.current_run);teams.interrupt(record,'cancelled','User stopped')
        self.assertEqual(record['jobs'][-1]['status'],'cancelled')
        self.assertEqual(set(record['results']),{'search_a','search_b','analysis_a'})
        self.assertEqual(len(record['jobs']),4)

    def test_mismatched_task_identity_is_rejected_before_snapshot_or_dispatch(self):
        import team
        self.setup_team();self.task['id']='another-user-task'
        with self.assertRaisesRegex(ValueError,'task'):
            team.execute(self.app,self.project,self.plan,task=self.task)
        self.assertEqual(self.provider.calls,[])
        self.assertEqual(self.task['run_ids'],[])
        self.assertFalse((self.storage/'runs').exists())

    def test_raised_allowance_executes_eight_assignments_without_expanding_approved_calls(self):
        from test_orchestration import named_assignment
        self.setup_team()
        tasks=[named_assignment('analysis_'+str(i),'researcher') for i in range(7)]
        tasks.append(named_assignment('review','reviewer',[t['id'] for t in tasks]))
        self.plan=teams.make_plan(self.project,self.git('rev-parse','HEAD'),'Expanded review',tasks,
                                  specialist_limit=8,task_id=self.task['id'])
        record=self.execute()
        self.assertEqual(record['stage'],'completed')
        self.assertEqual(len(record['tasks']),8)
        self.assertEqual(len(record['jobs']),9)
        self.assertEqual(len(self.provider.calls),9)
        teams.validate_record(record)

    def test_all_reviewer_objections_survive_more_than_legacy_question_ceiling(self):
        from test_orchestration import named_assignment
        self.setup_team()
        tasks=[named_assignment('analysis','researcher')]+[
            dict(named_assignment('review_'+str(i),'reviewer',['analysis']),objective='review_'+str(i)) for i in range(5)]
        self.plan=teams.make_plan(self.project,self.git('rev-parse','HEAD'),'Preserve every objection',tasks,
                                  specialist_limit=6,task_id=self.task['id'])
        def extensive_review(prompt,schema,cwd,cancel):
            self.provider.calls.append(prompt)
            if 'Purpose: synthesis' in prompt:return report(),None
            identity=prompt.split('\nAssignment: ',1)[1].split('\n',1)[0]
            reviewer='Role: Reviewer' in prompt
            result=report('revise' if reviewer else 'not_reviewed')
            result['summary']='Objection '+identity
            result['questions']=[identity+' question '+str(i) for i in range(20)]
            result['findings']=[dict(copy.deepcopy(report()['findings'][0]),claim=identity+' finding '+str(i)) for i in range(20)]
            return result,None
        self.provider.run=extensive_review
        record=self.execute()
        self.assertEqual(record['stage'],'needs_revision')
        self.assertEqual(len(record['combined']['questions']),226)
        teams.validate_record(runner.load(self.app.current_run))

    def test_imported_policy_one_plan_keeps_approval_while_running_under_task_owner(self):
        self.setup_team()
        self.plan=teams.make_plan(self.project,self.git('rev-parse','HEAD'),'Imported review',
                                  [assignment('researcher'),assignment('reviewer',['researcher'])])
        original=copy.deepcopy(self.plan)
        record=self.execute()
        self.assertEqual(record['stage'],'completed')
        self.assertEqual(record['task_id'],'user-task-a')
        self.assertEqual(record['plan'],original)
        self.assertEqual(self.plan,original)
        self.assertEqual(self.project['run_ids'],[])
        self.assertEqual(self.task['run_ids'],[record['id']])
        self.assertTrue(all(u['task_id']=='user-task-a' and 'assignment_id' in u for u in self.app.state['usage']))
        teams.validate_record(record)
        changed=copy.deepcopy(record);changed['task_id']='other-user-task'
        self.assertNotEqual(teams.artifact_id(changed),teams.artifact_id(record))
