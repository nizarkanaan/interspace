"""Durable task ownership and non-destructive legacy migration."""
import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app/backend'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"pilot"))

import projects
import runner
import test_pilot
from service import Application
from test_team import TeamProvider

class TaskStorageTests(unittest.TestCase):
    setUp=test_pilot.PilotTests.setUp
    git=test_pilot.PilotTests.git

    def test_new_task_is_local_durable_and_validated_atomically(self):
        provider=TeamProvider();app=Application(self.base/'data',provider=provider)
        pid=test_pilot.legacy_project(app,self.source)['project_id']
        self.assertEqual(app.public().get('tasks'),[])
        state=app.handle('create_task',{'project_id':pid})
        self.assertEqual(state['task']['title'],'New task');self.assertEqual(state['task']['specialist_limit'],6)
        tid=state['task_id'];self.assertEqual(provider.calls,[])
        self.assertEqual(state['tasks'][0]['status'],'draft')
        app.handle('update_task',{'project_id':pid,'task_id':tid,'specialist_limit':12,'title':'Expanded'})
        before=copy.deepcopy(app.public())
        for invalid in (0,-1,True,1.5,2**53,'8'):
            with self.assertRaises(ValueError):app.handle('update_task',{'project_id':pid,'task_id':tid,'title':'Wrong','specialist_limit':invalid})
        self.assertEqual(app.public(),before)
        restored=Application(app.storage,provider=provider).public()
        self.assertEqual(restored['task'],before['task']);self.assertEqual(restored['version'],3)
        test_pilot.legacy_project(app,self.source)
        self.assertEqual(app.public()['task_id'],tid)

    def test_v2_migration_moves_runs_and_exact_revision_approval_preserving_general_chat(self):
        storage=self.base/'data';storage.mkdir()
        project=projects.new_project(self.source)
        runs=[runner.prepare(self.source,storage/'runs') for _ in range(2)]
        for i,run in enumerate(runs):
            data=runner.load(run);data['goal']='Old goal '+str(i);runner.save(run/'run.json',data)
        pending={'id':'original-approval','kind':'revision','run_id':runs[0].name,'artifact_id':'unchanged','goal':'Revise','project_id':project['id']}
        project.update(run_ids=[r.name for r in runs],run_id=runs[1].name,pending=pending,thread=[{'role':'user','text':'General history'}])
        project.pop('tasks',None);project.pop('selected_task_id',None)
        state=projects.empty_state();state.update(version=2,projects={project['id']:project},selected_project_id=project['id'])
        original=json.dumps(state).encode();(storage/'state.json').write_bytes(original)
        app=Application(storage,provider=TeamProvider());public=app.public()
        self.assertEqual(public['version'],3);self.assertEqual(len(public['tasks']),2)
        self.assertEqual(public['pending'],pending);self.assertEqual(public['run']['id'],runs[0].name)
        self.assertEqual(public['threads']['task'],[]);self.assertEqual(public['threads']['project'],project['thread'])
        saved=app.state['projects'][project['id']]
        self.assertEqual(saved['run_ids'],[]);self.assertIsNone(saved['pending'])
        self.assertEqual((storage/'state.v2-backup.json').read_bytes(),original)
        self.assertEqual(Application(storage,provider=TeamProvider()).public()['pending'],pending)
        self.assertEqual((storage/'state.v2-backup.json').read_bytes(),original)

    def test_malformed_task_stays_saved_and_other_tasks_remain_usable(self):
        app=Application(self.base/'data',provider=TeamProvider());pid=test_pilot.legacy_project(app,self.source)['project_id']
        self.assertTrue(hasattr(app,'handle'))
        state=app.handle('create_task',{'project_id':pid});tid=state['task_id']
        raw={'id':'broken','title':['invalid'],'specialist_limit':False,'private':'preserve'}
        app.state['projects'][pid]['tasks']['broken']=copy.deepcopy(raw);app.persist()
        restored=Application(app.storage,provider=TeamProvider())
        self.assertEqual(restored.state['projects'][pid]['tasks']['broken'],raw)
        self.assertEqual(restored.public()['task_id'],tid)
        self.assertEqual(next(t for t in restored.public()['tasks'] if t['id']=='broken')['status'],'unavailable')
        with self.assertRaises(ValueError):restored.handle('select_task',{'project_id':pid,'task_id':'broken'})

    def test_imported_policy_one_approval_executes_unchanged_only_in_its_task(self):
        from test_orchestration import assignment
        import orchestration
        app=Application(self.base/'data',provider=TeamProvider())
        pid=test_pilot.legacy_project(app,self.source)['project_id'];project=app.state['projects'][pid]
        plan=orchestration.make_plan(project,self.git('rev-parse','HEAD'),'Imported approval',[assignment('researcher'),assignment('reviewer',['researcher'])])
        project['pending']=copy.deepcopy(plan);app.state['version']=2;app.persist()
        app=Application(app.storage,provider=TeamProvider());tid=app.public()['task_id']
        self.assertEqual(app.public()['pending'],plan)
        other=app.handle('create_task',{'project_id':pid,'title':'Other'})['task_id']
        app.state['projects'][pid]['tasks'][other]['pending']=copy.deepcopy(plan)
        with self.assertRaisesRegex(ValueError,'task'):
            app.handle('start_plan',{'project_id':pid,'task_id':other,'plan_id':plan['id'],'plan_digest':plan['digest']})
        self.assertEqual(app.provider.calls,[])
        app.handle('select_task',{'project_id':pid,'task_id':tid})
        app.handle('start_plan',{'project_id':pid,'task_id':tid,'plan_id':plan['id'],'plan_digest':plan['digest']});app.wait()
        self.assertEqual(app.public()['run']['plan'],plan);self.assertEqual(app.public()['run']['stage'],'completed')
        self.assertEqual(app.public()['run']['task_id'],tid)

    def test_imported_revision_approval_and_accepted_artifact_ids_survive(self):
        from test_revision import result, Scripted
        import revisions
        app=Application(self.base/'data',provider=Scripted());pid=test_pilot.legacy_project(app,self.source)['project_id']
        project=app.state['projects'][pid];run=runner.prepare(self.source,app.storage/'runs')
        runner.start(run,'researcher');runner.complete(run,'researcher',result())
        runner.start(run,'reviewer');runner.complete(run,'reviewer',result('Review feedback','revise'))
        record=runner.load(run);identity=revisions.artifact_id(record)
        plan={'id':'revision-plan','kind':'revision','goal':'Address feedback','project_id':pid,'source_path':str(self.source),
              'revision':record['revision'],'run_id':run.name,'artifact_id':identity}
        project.update(run_ids=[run.name],run_id=run.name,pending=plan);app.state['version']=2;app.persist()
        app=Application(app.storage,provider=Scripted());tid=app.public()['task_id']
        self.assertEqual(app.public()['run']['artifact_id'],identity);self.assertEqual(app.public()['pending'],plan)
        app.handle('start_review',{'project_id':pid,'task_id':tid,'plan_id':plan['id']});app.wait()
        public=app.public();self.assertEqual(public['run']['revision_round'],1);self.assertEqual(public['run']['stage'],'completed')
        self.assertEqual(public['run']['id'],run.name);self.assertEqual(len(public['threads']['task']),1)
        self.assertEqual(public['threads']['project'],[])
        app.handle('accept_report',{'project_id':pid,'task_id':tid,'run_id':run.name,'artifact_id':public['run']['artifact_id']})
        accepted=app.public()['run'];reopened=Application(app.storage,provider=Scripted()).public()['run']
        self.assertEqual(reopened['artifact_id'],accepted['artifact_id']);self.assertEqual(reopened['user_acceptance'],accepted['user_acceptance'])

    def test_imported_approval_cannot_escape_to_general_project_context(self):
        from test_orchestration import assignment
        import orchestration
        app=Application(self.base/'data',provider=TeamProvider());self.addCleanup(app.wait)
        pid=test_pilot.legacy_project(app,self.source)['project_id'];project=app.state['projects'][pid]
        plan=orchestration.make_plan(project,self.git('rev-parse','HEAD'),'Imported approval',[assignment('researcher')])
        project['pending']=copy.deepcopy(plan);app.state['version']=2;app.persist()
        app=Application(app.storage,provider=TeamProvider());self.addCleanup(app.wait)
        app.handle('select_task',{'project_id':pid,'task_id':None})
        app.state['projects'][pid]['pending']=copy.deepcopy(plan)
        with self.assertRaisesRegex(ValueError,'task|imported'):
            app.handle('start_plan',{'project_id':pid,'plan_id':plan['id'],'plan_digest':plan['digest']})
        self.assertEqual(app.provider.calls,[])

    def test_migration_isolates_malformed_historical_run_metadata(self):
        storage=self.base/'data';storage.mkdir();project=projects.new_project(self.source)
        run=runner.prepare(self.source,storage/'runs');(run/'run.json').write_text('[]')
        project.update(run_ids=[run.name],run_id=run.name)
        state=projects.empty_state();state.update(version=2,projects={project['id']:project},selected_project_id=project['id'])
        (storage/'state.json').write_text(json.dumps(state))
        app=Application(storage,provider=TeamProvider())
        self.assertEqual(app.public()['tasks'][0]['status'],'unavailable')
        self.assertEqual((run/'run.json').read_text(),'[]')

    def test_malformed_selected_task_reference_and_collection_remain_isolated(self):
        app=Application(self.base/'data',provider=TeamProvider());pid=test_pilot.legacy_project(app,self.source)['project_id']
        app.state['projects'][pid]['selected_task_id']=['not a task ID'];app.persist()
        app=Application(app.storage,provider=TeamProvider())
        self.assertIn('unavailable',app.public()['error'])
        self.assertEqual(app.state['projects'][pid]['selected_task_id'],['not a task ID'])
        self.assertIsNone(app.public()['task_id'])
        app.handle('select_task',{'project_id':pid,'task_id':None})
        app.state['projects'][pid]['tasks']=['malformed collection'];app.persist()
        app=Application(app.storage,provider=TeamProvider())
        self.assertIn('unavailable',app.public()['error'])
        self.assertEqual(app.state['projects'][pid]['tasks'],['malformed collection'])

    def test_imported_approval_restoration_rejects_revoked_and_consumed_plans(self):
        from test_orchestration import assignment
        import orchestration
        for trigger in ('allowance','chat','sources','start'):
            with self.subTest(trigger=trigger):
                app=Application(self.base/('data-'+trigger),provider=TeamProvider());self.addCleanup(app.wait)
                pid=test_pilot.legacy_project(app,self.source)['project_id'];project=app.state['projects'][pid]
                plan=orchestration.make_plan(project,self.git('rev-parse','HEAD'),'Exact imported approval',
                                              [assignment('researcher'),assignment('reviewer',['researcher'])])
                project['pending']=copy.deepcopy(plan);app.state['version']=2;app.persist()
                app=Application(app.storage,provider=TeamProvider());self.addCleanup(app.wait)
                tid=app.public()['task_id'];project=app.state['projects'][pid]
                provenance=copy.deepcopy(project['imported_plan_owners'])
                ref={'project_id':pid,'task_id':tid}
                start=dict(ref,plan_id=plan['id'],plan_digest=plan['digest'])
                if trigger=='allowance':app.handle('update_task',dict(ref,specialist_limit=1))
                elif trigger=='chat':
                    app.handle('chat',dict(ref,scope='task',text='Replace the old proposal'));app.wait()
                elif trigger=='sources':
                    app.handle('save_sources',{'project_id':pid,'selection_version':0,
                                              'revision':self.git('rev-parse','HEAD'),'paths':['README.md']})
                else:
                    app.handle('start_plan',start);app.wait()
                    self.assertEqual(app.public()['run']['plan'],plan)
                calls=len(app.provider.calls)
                # Only pending is restored; neither immutable provenance nor lifecycle status is altered.
                project['tasks'][tid]['pending']=copy.deepcopy(plan)
                with self.assertRaisesRegex(ValueError,'revoked|consumed|live'):
                    app.handle('start_plan',start)
                app.handle('select_task',{'project_id':pid,'task_id':None})
                project['pending']=copy.deepcopy(plan)
                with self.assertRaisesRegex(ValueError,'task|revoked|consumed|live'):
                    app.handle('start_plan',{'project_id':pid,'plan_id':plan['id'],'plan_digest':plan['digest']})
                self.assertEqual(len(app.provider.calls),calls)
                self.assertEqual(project['imported_plan_owners'],provenance)
                self.assertEqual(project['tasks'][tid]['pending'],plan)
                self.assertEqual(project['imported_plan_states'][plan['id']],'consumed' if trigger=='start' else 'revoked')
                app.persist()
                restored=Application(app.storage,provider=TeamProvider())
                restored.handle('select_task',ref)
                with self.assertRaisesRegex(ValueError,'revoked|consumed|live'):
                    restored.handle('start_plan',start)
                self.assertEqual(restored.provider.calls,[])
