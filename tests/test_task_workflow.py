"""Task-scoped orchestration, stale actions, and asynchronous ownership."""
import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app/backend'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_pilot
from service import Application
from test_team import TeamProvider
from test_orchestration import named_assignment

class TaskWorkflowTests(unittest.TestCase):
    setUp=test_pilot.PilotTests.setUp
    git=test_pilot.PilotTests.git
    def setup_app(self):
        self.provider=TeamProvider();self.app=Application(self.base/'data',provider=self.provider)
        self.addCleanup(self.app.wait)
        self.pid=test_pilot.legacy_project(self.app,self.source)['project_id']
        self.a=self.create('Task A');self.b=self.create('Task B');self.select(self.a)
    def ref(self,tid=None,**kwargs):return dict(project_id=self.pid,task_id=tid or self.a,**kwargs)
    def create(self,title):return self.app.handle('create_task',{'project_id':self.pid,'title':title})['task_id']
    def select(self,tid):return self.app.handle('select_task',{'project_id':self.pid,'task_id':tid})
    def propose(self,text='A_PRIVATE_GOAL'):
        self.app.handle('chat',self.ref(scope='task',text=text));self.app.wait()
        return self.app.public()['pending']
    def start(self,plan=None):
        plan=plan or self.app.public()['pending']
        self.app.handle('start_plan',self.ref(plan_id=plan['id'],plan_digest=plan['digest']));self.app.wait()
        return self.app.public()['run']

    def test_task_plan_run_history_results_and_general_chat_are_separate(self):
        self.setup_app();p=self.app.state['projects'][self.pid]
        p['thread']=[{'role':'user','text':'GENERAL_SECRET'}]
        plan=self.propose();self.assertEqual(plan['policy_version'],2);self.assertEqual(plan['task_id'],self.a)
        self.assertNotIn('GENERAL_SECRET',self.provider.calls[-1])
        run=self.start();self.assertEqual(run['task_id'],self.a);self.assertEqual(run['stage'],'completed')
        self.assertEqual(p['run_ids'],[]);self.assertEqual(len(p['tasks'][self.a]['run_ids']),1)
        self.assertTrue(all(u['task_id']==self.a for u in self.app.public()['usage']))
        self.assertNotIn('assignment_id',self.app.public()['usage'][0])
        self.assertEqual(self.app.public()['tasks'][0]['status'],'completed')
        self.select(self.b);self.assertIsNone(self.app.public()['run']);self.assertEqual(self.app.public()['threads']['task'],[])
        self.app.handle('chat',self.ref(self.b,scope='task',text='B_GOAL'));self.app.wait()
        self.assertNotIn('A_PRIVATE_GOAL',self.provider.calls[-1]);self.assertNotIn('GENERAL_SECRET',self.provider.calls[-1])
        self.select(None);self.assertEqual(self.app.public()['threads']['project'],p['thread']);self.assertIsNone(self.app.public()['run'])

    def test_missing_cross_task_and_general_run_actions_are_rejected(self):
        self.setup_app();plan=self.propose();run=self.start(plan)
        methods=[('source',{'source':'README.md'}),('select_run',{}),('accept_report',{'artifact_id':run['artifact_id']}),('revise_run',{'artifact_id':run['artifact_id']})]
        for method,extra in methods:
            with self.assertRaises(ValueError):self.app.handle(method,dict(project_id=self.pid,run_id=run['id'],**extra))
        self.select(self.b)
        for method,extra in methods:
            for tid in (self.a,self.b):
                with self.assertRaises(ValueError):self.app.handle(method,self.ref(tid,run_id=run['id'],**extra))
        with self.assertRaises(ValueError):self.app.handle('chat',self.ref(self.a,scope='task',text='stale'))
        with self.assertRaises(ValueError):self.app.handle('chat',{'project_id':self.pid,'scope':'project','text':'missing task'})
        self.select(None)
        with self.assertRaises(ValueError):self.app.handle('select_run',{'project_id':self.pid,'run_id':run['id']})
        self.select(self.a);self.app.handle('accept_report',self.ref(run_id=run['id'],artifact_id=run['artifact_id']))
        self.assertEqual(self.app.public()['run']['stage'],'accepted')

    def test_browsing_during_planner_and_cancelled_execution_keeps_actual_owner(self):
        self.setup_app();self.provider.block='Role: Orchestrator'
        self.app.handle('chat',self.ref(scope='task',text='A_GOAL'))
        self.assertTrue(self.provider.entered.wait(2));self.select(self.b)
        self.assertEqual(self.app.public()['active_task_id'],self.a);self.assertEqual(self.app.public()['active_task'],'Task A')
        for method,params in [('create_task',{'project_id':self.pid}),('update_task',self.ref(self.b,title='Blocked')),('chat',self.ref(self.b,scope='task',text='Blocked'))]:
            with self.assertRaises(ValueError):self.app.handle(method,params)
        self.provider.release.set();self.app.wait();self.assertIsNone(self.app.public()['pending'])
        self.select(self.a);plan=self.app.public()['pending'];self.assertEqual(plan['task_id'],self.a)
        self.provider.entered.clear();self.provider.release.clear();self.provider.block='Role: Reviewer'
        self.app.handle('start_plan',self.ref(plan_id=plan['id'],plan_digest=plan['digest']))
        self.assertTrue(self.provider.entered.wait(2));self.select(self.b);self.app.handle('cancel',{})
        self.provider.release.set();self.app.wait()
        self.assertEqual(self.app.public()['error'],'');self.assertEqual(self.app.public()['error_task_id'],self.a)
        self.select(self.a);self.assertEqual(self.app.public()['run']['stage'],'cancelled');self.assertIn('cancel',self.app.public()['error'].lower())
        self.assertEqual(set(self.app.public()['run']['results']),{'researcher'})

    def test_limit_change_invalidates_only_owner_and_source_change_invalidates_all(self):
        self.setup_app();self.propose();self.select(self.b)
        self.app.handle('chat',self.ref(self.b,scope='task',text='B_GOAL'));self.app.wait()
        b_plan=self.app.public()['pending'];self.select(self.a)
        self.app.handle('update_task',self.ref(specialist_limit=8))
        self.assertIsNone(self.app.public()['pending']);self.assertEqual(self.app.state['projects'][self.pid]['tasks'][self.b]['pending'],b_plan)
        self.provider.tasks=[named_assignment('a'+str(i),'researcher') for i in range(7)]
        self.provider.tasks.append(named_assignment('review','reviewer',['a'+str(i) for i in range(7)]))
        plan=self.propose();self.assertEqual(len(plan['tasks']),8);self.assertEqual(plan['limits']['max_calls'],9)
        self.app.handle('save_sources',{'project_id':self.pid,'selection_version':0,'revision':self.git('rev-parse','HEAD'),'paths':['README.md']})
        self.assertTrue(all(t['pending'] is None for t in self.app.state['projects'][self.pid]['tasks'].values()))

    def test_policy_two_plan_cannot_be_rebound_to_another_task(self):
        self.setup_app();plan=self.propose();p=self.app.state['projects'][self.pid]
        p['tasks'][self.b]['pending']=copy.deepcopy(plan);self.select(self.b)
        with self.assertRaisesRegex(ValueError,'task'):
            self.app.handle('start_plan',self.ref(self.b,plan_id=plan['id'],plan_digest=plan['digest']))
        self.assertEqual(len(self.provider.calls),1)

    def test_planning_error_persists_with_task_after_other_task_runs_and_restart(self):
        self.setup_app();self.provider.fail='Role: Orchestrator';self.propose()
        self.assertIn('Fixture failure',self.app.public()['error'])
        self.assertEqual(self.app.public()['tasks'][0]['status'],'failed')
        self.select(self.b);self.provider.fail=None
        self.app.handle('chat',self.ref(self.b,scope='task',text='B_GOAL'));self.app.wait()
        self.assertEqual(self.app.public()['error'],'')
        self.app=Application(self.app.storage,provider=self.provider);self.select(self.a)
        self.assertIn('Fixture failure',self.app.public()['error']);self.assertEqual(self.app.public()['error_task_id'],self.a)
        self.propose();self.assertEqual(self.app.public()['error'],'')

    def test_restart_recovers_active_task_and_preserves_terminal_results(self):
        self.setup_app();self.propose();run=self.start();saved=copy.deepcopy(run)
        self.app.state.update(active='Orchestrator',active_project_id=self.pid,active_task_id=self.a,active_run_id=run['id'])
        self.app.persist();self.select(self.b)
        self.app=Application(self.app.storage,provider=self.provider)
        self.assertIsNone(self.app.public()['run']);self.select(self.a)
        self.assertEqual(self.app.public()['run'],saved);self.assertEqual(self.app.public()['error'],'')
        self.app.state.update(active='Orchestrator',active_project_id=self.pid,active_task_id=self.a,active_run_id=None)
        self.app.persist();self.select(self.b);self.app=Application(self.app.storage,provider=self.provider)
        self.assertEqual(self.app.public()['error'],'');self.select(self.a)
        self.assertIn('interrupted',self.app.public()['error'])
        self.assertEqual(self.app.public()['tasks'][0]['status'],'interrupted')

    def test_workspace_prompt_never_includes_task_goals_titles_or_results(self):
        self.setup_app();self.propose();self.start()
        self.app.handle('chat',{'scope':'workspace','text':'Priorities'});self.app.wait()
        prompt=self.provider.calls[-1]
        for private in ('Task A','Task B','A_PRIVATE_GOAL','Evidence exists','Committed evidence'):
            self.assertNotIn(private,prompt)

    def test_restored_proposal_cannot_bypass_changed_task_allowance(self):
        self.setup_app();plan=self.propose()
        self.app.handle('update_task',self.ref(specialist_limit=8))
        self.app.state['projects'][self.pid]['tasks'][self.a]['pending']=copy.deepcopy(plan)
        with self.assertRaisesRegex(ValueError,'limit|allowance|changed|stale'):
            self.app.handle('start_plan',self.ref(plan_id=plan['id'],plan_digest=plan['digest']))
        self.assertEqual(len(self.provider.calls),1)

    def test_failed_terminal_task_keeps_failed_status_during_recovery(self):
        self.setup_app();self.propose();self.provider.fail='Role: Researcher';run=self.start()
        self.assertEqual(run['stage'],'failed')
        self.app.state.update(active='Researcher',active_project_id=self.pid,active_task_id=self.a,active_run_id=run['id'])
        self.app.persist();self.app=Application(self.app.storage,provider=self.provider)
        self.assertEqual(self.app.public()['run']['stage'],'failed')
        self.assertEqual(self.app.public()['tasks'][0]['status'],'failed')

    def test_project_latest_run_follows_execution_order_across_tasks(self):
        self.setup_app();self.propose();self.start()
        self.select(self.b);self.app.handle('chat',self.ref(self.b,scope='task',text='B_GOAL'));self.app.wait()
        plan=self.app.public()['pending']
        self.app.handle('start_plan',self.ref(self.b,plan_id=plan['id'],plan_digest=plan['digest']));self.app.wait()
        self.select(self.a);self.propose('A_SECOND_GOAL');last=self.start()
        self.assertEqual(self.app.public()['projects'][0]['latest_run']['id'],last['id'])

    def test_task_status_tracks_latest_attempt_while_browsing_old_report(self):
        self.setup_app();self.propose();old=self.start()
        self.propose('Second attempt');self.provider.verdict='revise';self.start()
        self.app.handle('select_run',self.ref(run_id=old['id']))
        self.assertEqual(self.app.public()['run']['stage'],'completed')
        self.assertEqual(self.app.public()['tasks'][0]['status'],'needs_revision')

    def test_non_object_event_metadata_cannot_break_project_summaries(self):
        import runner
        self.setup_app();self.propose();run=self.start()
        path=self.app.storage/'runs'/run['id'];record=runner.load(path)
        record['events']=[None];runner.save(path/'run.json',record)
        self.assertEqual(self.app.public()['run']['id'],run['id'])
        self.assertEqual(self.app.public()['projects'][0]['latest_run']['id'],run['id'])

    def test_observed_selected_source_invalidation_revokes_imported_approval(self):
        import orchestration
        from test_orchestration import assignment
        for changed in ('revision','scope'):
            with self.subTest(changed=changed):
                app=Application(self.base/('selected-'+changed),provider=TeamProvider());self.addCleanup(app.wait)
                pid=app.handle('add_project',{'path':str(self.source)})['project_id']
                head=self.git('rev-parse','HEAD')
                app.handle('save_sources',{'project_id':pid,'selection_version':0,'revision':head,'paths':['README.md']})
                project=app.state['projects'][pid];selection=copy.deepcopy(project['source_selection'])
                plan=orchestration.make_plan(project,head,'Imported selected-source approval',[assignment('researcher')])
                project['pending']=copy.deepcopy(plan);app.state['version']=2;app.persist()
                app=Application(app.storage,provider=TeamProvider());tid=app.public()['task_id'];project=app.state['projects'][pid]
                provenance=copy.deepcopy(project['imported_plan_owners'])
                if changed=='revision':
                    (self.source/'new.txt').write_text('Changed committed revision\n')
                    self.git('add','new.txt');self.git('commit','-qm','Changed fixture revision')
                else:project['source_selection']['selection_version']+=1
                request={'project_id':pid,'task_id':tid,'plan_id':plan['id'],'plan_digest':plan['digest']}
                with self.assertRaisesRegex(ValueError,'changed|stale'):app.handle('start_plan',request)
                self.assertIsNone(project['tasks'][tid]['pending'])
                self.assertEqual(project['imported_plan_states'][plan['id']],'revoked')
                saved=json.loads((app.storage/'state.json').read_text())['projects'][pid]
                self.assertEqual(saved['imported_plan_states'][plan['id']],'revoked')
                self.assertEqual(project['imported_plan_owners'],provenance)
                # Restore only pending and the original source state, retaining the revocation.
                if changed=='revision':self.git('update-ref','HEAD',head)
                project['source_selection']=selection;project['tasks'][tid]['pending']=copy.deepcopy(plan);app.persist()
                app=Application(app.storage,provider=TeamProvider());project=app.state['projects'][pid]
                with self.assertRaisesRegex(ValueError,'revoked|live'):app.handle('start_plan',request)
                app.handle('select_task',{'project_id':pid,'task_id':None});project['pending']=copy.deepcopy(plan)
                with self.assertRaisesRegex(ValueError,'task|revoked|live'):
                    app.handle('start_plan',{'project_id':pid,'plan_id':plan['id'],'plan_digest':plan['digest']})
                self.assertEqual(app.provider.calls,[])

    def test_transient_selected_context_failure_keeps_imported_approval_live(self):
        from unittest.mock import patch
        from test_orchestration import assignment
        import orchestration
        app=Application(self.base/'transient',provider=TeamProvider());pid=app.handle('add_project',{'path':str(self.source)})['project_id']
        head=self.git('rev-parse','HEAD')
        app.handle('save_sources',{'project_id':pid,'selection_version':0,'revision':head,'paths':['README.md']})
        project=app.state['projects'][pid]
        plan=orchestration.make_plan(project,head,'Imported selected-source approval',[assignment('researcher')])
        project['pending']=copy.deepcopy(plan);app.state['version']=2;app.persist()
        app=Application(app.storage,provider=TeamProvider());tid=app.public()['task_id'];project=app.state['projects'][pid]
        with patch('service.sources.context',side_effect=ValueError('Temporary context read failure')):
            with self.assertRaisesRegex(ValueError,'Temporary'):
                app.handle('start_plan',{'project_id':pid,'task_id':tid,'plan_id':plan['id'],'plan_digest':plan['digest']})
        self.assertEqual(project['tasks'][tid]['pending'],plan)
        self.assertEqual(project['imported_plan_states'][plan['id']],'live');self.assertEqual(app.provider.calls,[])
