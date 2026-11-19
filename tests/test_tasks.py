"""Task storage: agent-only new tasks, non-destructive migration and the read-only history of earlier tasks."""
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
import tasks
import test_pilot
from service import Application


class NoProvider:
    """Loading and showing earlier tasks never reaches a provider or a sign-in."""
    calls = []

    def __getattr__(self, name):
        raise AssertionError('Unexpected provider access: ' + name)


def earlier(title, **fields):
    task = tasks.imported(title)
    task.update(fields)
    return task


def team_record(run_id, project, task_id, stage='completed'):
    return {'id': run_id, 'format': 'team-v2', 'project_id': project['id'], 'task_id': task_id, 'goal': 'Compare sources',
            'stage': stage, 'revision': 'abc', 'source_path': project['source_path'],
            'plan': {'goal': 'Compare sources', 'tasks': [
                {'id': 'r1', 'role': 'researcher', 'label': 'Researcher 1', 'objective': 'Read the README',
                 'expected_output': 'Claims with citations', 'dependencies': []},
                {'id': 'v1', 'role': 'reviewer', 'objective': 'Check the claims', 'expected_output': 'A verdict',
                 'dependencies': ['r1']}]},
            'results': {}, 'events': [],
            'combined': {'summary': 'Two sources agree.', 'findings': [{'claim': 'The README documents setup.'}],
                         'questions': ['Is the benchmark current?'], 'verdict': 'accept'}}


def review_record(run_id, project):
    return {'id': run_id, 'goal': 'Review evidence', 'stage': 'researcher', 'revision': 'abc',
            'source_path': project['source_path'], 'events': [],
            'results': {'researcher': {'summary': 'Evidence reviewed', 'findings': [{'claim': 'Documented'}],
                                       'proposal': 'A bounded check'}}}


class TaskStorageTests(unittest.TestCase):
    setUp=test_pilot.PilotTests.setUp
    git=test_pilot.PilotTests.git

    def app(self, storage=None):
        return Application(storage or self.base/'data', provider=NoProvider())

    def seeded(self, *saved, selected=None):
        """A project holding the given saved task rows, persisted and reopened."""
        app=self.app();project=projects.new_project(self.source);app.state['projects'][project['id']]=project
        app.state['selected_project_id']=project['id']
        for task in saved:project['tasks'][task['id']]=task
        project['selected_task_id']=selected;app.persist()
        return Application(app.storage,provider=NoProvider()),project

    def write_run(self, storage, record):
        folder=storage/'runs'/record['id'];folder.mkdir(parents=True)
        (folder/'run.json').write_text(json.dumps(record))
        return folder/'run.json'

    def test_new_tasks_are_agent_tasks_only(self):
        task=tasks.create('Fix it',project_id='p1')
        self.assertEqual((task['mode'],task['provider'],task['agent']['project_id']),('agent','claude','p1'))
        self.assertEqual(tasks.MODES,('agent',))
        tasks.validate(task,task['id'])
        with self.assertRaises(ValueError):tasks.create('Fix it',project_id=None)
        with self.assertRaises(TypeError):tasks.create('Fix it',mode='review',project_id='p1')
        app=self.app();pid=test_pilot.legacy_project(app,self.source)['project_id']
        for method in ('create_task','update_task','chat','start_plan','start_review','start_change','approve_checks',
                       'apply_changes','revise_run','accept_report','select_run','source','save_sources','list_sources'):
            with self.subTest(method=method):
                with self.assertRaisesRegex(ValueError,'Unknown method'):app.handle(method,{'project_id':pid})

    def test_new_tasks_are_orchestrator_tasks_and_subagents_are_child_rows(self):
        parent=tasks.create('Fix it',project_id='p1',token_budget=90000)
        self.assertEqual(parent['role'],'orchestrator')
        self.assertIsNone(parent.get('parent_task_id'))
        child=tasks.child(parent,role='implementer',brief_text='  Add input validation.  ',provider='claude',
                          model='claude-sonnet-5-5',access='write',team_id='t1',member_id='m2')
        self.assertEqual({k:child[k] for k in ('parent_task_id','role','brief','provider','model','access','team_id','member_id')},
                         {'parent_task_id':parent['id'],'role':'implementer','brief':'Add input validation.','provider':'claude',
                          'model':'claude-sonnet-5-5','access':'write','team_id':'t1','member_id':'m2'})
        self.assertEqual((child['title'],child['token_budget'],child['agent']['project_id'],child['mode']),
                         ('Implementer: Add input validation.',90000,'p1','agent'))
        self.assertNotEqual(child['id'],parent['id'])
        tasks.validate(child,child['id'])
        paused=dict(parent,agent=dict(parent['agent'],state='paused_team'))
        tasks.validate(paused,parent['id'])
        legacy=dict(parent);legacy.pop('role')
        tasks.validate(legacy,parent['id'])  # Agent tasks saved before the Orchestrator still load.
        for bad in (dict(child,role='orchestrator'),dict(child,access='admin'),dict(child,brief=''),dict(child,member_id=None),
                    dict(parent,role='boss'),dict(parent,team_id='t1')):
            with self.assertRaises(ValueError):tasks.validate(bad,bad['id'])
        for kwargs in (dict(role='orchestrator'),dict(access='none'),dict(brief_text='x'*6001)):
            arguments=dict(role='reviewer',brief_text='b',provider='codex',model=None,access='read',team_id='t',member_id='m1')
            arguments.update(kwargs)
            with self.assertRaises(ValueError):tasks.child(parent,**arguments)
        self.assertEqual(len(tasks.child(parent,role='writer',brief_text='w'*300,provider='codex',model=None,access='read',
                                         team_id='t',member_id='m1')['title']),160)

    def test_earlier_tasks_load_read_only_with_conversation_plan_and_report(self):
        storage=self.base/'data'
        project=projects.new_project(self.source)
        old=earlier('Compare sources',thread=[{'role':'user','text':'Compare the sources'},{'role':'assistant','text':'Here is a plan.'}],
                    run_ids=['run-team','run-review','run-missing'],run_id='run-team',error='Stopped early',error_status='failed')
        fixed=earlier('Fix value',mode='python_fix',pending={'id':'plan-1','goal':'Fix the value','tasks':[
            {'id':'i1','role':'implementer','objective':'Change main.py','expected_output':'A patch'}]})
        storage.mkdir()
        saved=[self.write_run(storage,team_record('run-team',project,old['id'])),self.write_run(storage,review_record('run-review',project))]
        before=[p.read_bytes() for p in saved]
        app,project=self.seeded(old,fixed,selected=old['id'])
        public=app.public()
        rows={t['id']:t for t in public['tasks']}
        self.assertEqual(rows[old['id']]['status'],'read_only');self.assertTrue(rows[old['id']]['read_only'])
        self.assertEqual(rows[fixed['id']]['mode'],'python_fix')
        history=public['task']['history']
        self.assertEqual(history['label'],'Earlier task (read-only)')
        self.assertEqual([m['text'] for m in history['messages']],['Compare the sources','Here is a plan.'])
        self.assertIn('Goal: Compare sources',history['plan']);self.assertIn('- Researcher 1: Read the README',history['plan'])
        self.assertEqual([r['run_id'] for r in history['reports']],['run-missing','run-review','run-team'])
        missing,review,team=history['reports']
        self.assertEqual(missing['stage'],'unavailable')
        self.assertEqual(review['stage'],'interrupted')  # Cut off by an earlier version; shown, never resumed.
        self.assertIn('Research report',review['text']);self.assertIn('Proposal (not executed): A bounded check',review['text'])
        self.assertEqual(team['stage'],'completed')
        for part in ('Combined result · accept','Two sources agree.','- The README documents setup.','Is the benchmark current?'):
            self.assertIn(part,team['text'])
        self.assertEqual(history['error'],'Stopped early')
        self.assertEqual(public['error'],'')  # A task's old error belongs to its history, not the app banner.
        self.assertNotIn('pending',public);self.assertNotIn('run',public)
        self.assertEqual([p.read_bytes() for p in saved],before)  # Showing history never rewrites a run.
        selected=app.handle('select_task',{'project_id':project['id'],'task_id':fixed['id']})
        self.assertIn('- Implementer: Change main.py (expected: A patch)',selected['task']['history']['plan'])
        self.assertEqual(selected['task']['history']['reports'],[])

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
        app=self.app(storage);public=app.public()
        self.assertEqual(public['version'],4);self.assertEqual(len(public['tasks']),2)
        self.assertTrue(all(t['status']=='read_only' and t['mode']=='review' for t in public['tasks']))
        history=public['task']['history']
        self.assertEqual(history['plan'],'Goal: Revise')
        self.assertEqual([r['goal'] for r in history['reports']],['Old goal 0'])
        saved=app.state['projects'][project['id']]
        self.assertEqual(saved['run_ids'],[]);self.assertIsNone(saved['pending'])
        self.assertEqual(saved['thread'],project['thread'])  # Kept in the saved state, no longer shown.
        task=saved['tasks'][public['task_id']]
        self.assertEqual(task['pending'],pending)
        self.assertEqual(saved['imported_plan_owners']['original-approval']['task_id'],task['id'])
        self.assertEqual((storage/'state.v2-backup.json').read_bytes(),original)
        self.assertEqual(self.app(storage).public()['task']['history'],history)
        self.assertEqual((storage/'state.v2-backup.json').read_bytes(),original)

    def test_migration_isolates_malformed_historical_run_metadata(self):
        storage=self.base/'data';storage.mkdir();project=projects.new_project(self.source)
        run=runner.prepare(self.source,storage/'runs');(run/'run.json').write_text('[]')
        project.update(run_ids=[run.name],run_id=run.name)
        state=projects.empty_state();state.update(version=2,projects={project['id']:project},selected_project_id=project['id'])
        (storage/'state.json').write_text(json.dumps(state))
        app=self.app(storage)
        self.assertEqual(app.public()['task']['title'],'Imported review')
        self.assertEqual(app.public()['task']['history']['reports'][0]['stage'],'unavailable')
        self.assertEqual((run/'run.json').read_text(),'[]')

    def test_malformed_task_stays_saved_and_other_tasks_remain_usable(self):
        healthy=earlier('Healthy')
        raw={'id':'broken','title':['invalid'],'specialist_limit':False,'private':'preserve'}
        app,project=self.seeded(healthy,copy.deepcopy(raw),selected=healthy['id'])
        self.assertEqual(app.state['projects'][project['id']]['tasks']['broken'],raw)
        self.assertEqual(app.public()['task_id'],healthy['id'])
        self.assertEqual(next(t for t in app.public()['tasks'] if t['id']=='broken')['status'],'unavailable')
        with self.assertRaises(ValueError):app.handle('select_task',{'project_id':project['id'],'task_id':'broken'})

    def test_reopened_malformed_presentation_fields_are_isolated_without_rewriting(self):
        from task_saved_state_fixture import reopened_states
        invalid = [{'error':'Saved failure','error_status':7}, {'error':None}, {'error':False},
                   {'error':[]}, {'error_status':False}, {'error_status':[]}, {'error_status':''},
                   {'error_status':'invented'}, {'thread':[None]}, {'thread':['message']},
                   {'thread':[{}]}, {'thread':[{'role':'user','text':None}]},
                   {'thread':[{'role':7,'text':'Text'}]}, {'thread':[{'role':'system','text':'Text'}]},
                   {'thread':[{'role':'assistant'}]}, {'mode':'invented'}, {'specialist_limit':0}]
        for index, malformed in enumerate(invalid):
            with self.subTest(malformed=malformed):
                states=reopened_states(self.base/('saved-'+str(index)),malformed)
                for name in ('nonselected','selected','healthy','general'):
                    self.assertEqual(states[name]['tasks'][0]['status'],'unavailable')
                    self.assertEqual(states[name]['tasks'][1]['status'],'read_only')
                    self.assertTrue(all(isinstance(t['status'],str) for t in states[name]['tasks']))
                self.assertTrue(states['raw_preserved'])
                self.assertIsNone(states['selected']['task'])
                self.assertIn('unavailable',states['selected']['error'])
                self.assertEqual(states['healthy']['task']['title'],'Healthy task')
                self.assertEqual(states['healthy']['task']['history']['messages'][0]['text'],'Healthy conversation survives')
                self.assertIsNone(states['general']['task'])
                self.assertEqual(states['other']['project'],'Other healthy project')

    def test_old_optional_fields_and_finished_statuses_remain_usable(self):
        task=earlier('Old task')
        for field in ('draft','error','error_status'):task.pop(field)
        raw=copy.deepcopy(task)
        app,project=self.seeded(task,selected=task['id'])
        self.assertEqual(app.public()['tasks'][0]['status'],'read_only')
        self.assertEqual(app.state['projects'][project['id']]['tasks'][task['id']],raw)
        saved=app.state['projects'][project['id']]['tasks'][task['id']]
        for status in (None,*tasks.FINISHED_STAGES):
            with self.subTest(status=status):
                saved.update(error='Saved failure',error_status=status);app.persist()
                restored=Application(app.storage,provider=NoProvider())
                self.assertEqual(restored.public()['tasks'][0]['status'],'read_only')
                self.assertEqual(restored.public()['task']['history']['error'],'Saved failure')

    def test_malformed_selected_task_reference_and_collection_remain_isolated(self):
        app=self.app();pid=test_pilot.legacy_project(app,self.source)['project_id']
        app.state['projects'][pid]['selected_task_id']=['not a task ID'];app.persist()
        app=self.app(app.storage)
        self.assertIn('unavailable',app.public()['error'])
        self.assertEqual(app.state['projects'][pid]['selected_task_id'],['not a task ID'])
        self.assertIsNone(app.public()['task_id'])
        app.handle('select_task',{'project_id':pid,'task_id':None})
        app.state['projects'][pid]['tasks']=['malformed collection'];app.persist()
        app=self.app(app.storage)
        self.assertIn('unavailable',app.public()['error'])
        self.assertEqual(app.state['projects'][pid]['tasks'],['malformed collection'])

    def test_interaction_active_at_quit_is_cleared_without_touching_saved_tasks(self):
        for pending in ({'id':[]},{},{'id':''},{'id':'kept','goal':'Old proposal'}):
            with self.subTest(pending=pending):
                storage=self.base/('active-'+str(len(list(self.base.glob('active-*')))))
                task=earlier('Old task',pending=copy.deepcopy(pending))
                app=Application(storage,provider=NoProvider());project=projects.new_project(self.source)
                project['tasks'][task['id']]=task;project['pending']={'id':'keep-general','goal':'General proposal'}
                app.state['projects'][project['id']]=project
                app.state.update(selected_project_id=project['id'],active='Orchestrator',active_project_id=project['id'],
                                 active_task_id=task['id'],active_run_id='run-x')
                app.persist();raw=copy.deepcopy(task)
                restored=Application(storage,provider=NoProvider())
                self.assertIsNone(restored.public()['active'])
                self.assertEqual((restored.state['active_task_id'],restored.state['active_run_id']),(None,None))
                self.assertEqual(restored.state['projects'][project['id']]['tasks'][task['id']],raw)
                self.assertEqual(restored.state['projects'][project['id']]['pending'],{'id':'keep-general','goal':'General proposal'})
                self.assertEqual(restored.public()['error'],'')


if __name__ == '__main__':
    unittest.main()
