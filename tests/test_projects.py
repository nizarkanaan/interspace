"""Project registry: registration, switching, metadata and saved-state migrations."""
import copy
import json
from pathlib import Path
import shutil
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/backend'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pilot'))

import test_pilot
from service import Application
import runner
import tasks


class NoProvider:
    def status(self):
        return {'ready': True, 'message': 'Test connection'}

    def __getattr__(self, name):
        raise AssertionError('Unexpected provider access: ' + name)


class ProjectTests(unittest.TestCase):
    setUp = test_pilot.PilotTests.setUp
    git = test_pilot.PilotTests.git

    def setup_app(self):
        self.storage = self.base/'app-data'
        self.app = Application(self.storage, provider=NoProvider())
        self.addCleanup(self.app.scheduler.shutdown, 5)
        self.a = test_pilot.legacy_project(self.app, self.source)['project_id']
        self.other = self.base/'other'
        shutil.copytree(self.source, self.other)
        (self.other/'README.md').write_text('B_SOURCE_MARKER\n')
        runner.git(self.other,'add','README.md')
        runner.git(self.other,'commit','-qm','Other project')
        self.b = test_pilot.legacy_project(self.app, self.other)['project_id']

    def switch(self, project):
        return self.app.handle('switch_project', {'project_id':project})

    def test_registry_switches_projects_and_deduplicates_paths(self):
        self.setup_app()
        self.assertEqual(self.app.public()['project_id'], self.b)
        self.assertEqual(self.switch(self.a)['project'], 'source')
        test_pilot.legacy_project(self.app, self.source/'.')
        self.assertEqual(len(self.app.public()['projects']), 2)
        self.assertEqual(sorted(p['id'] for p in self.app.public()['projects']), sorted([self.a, self.b]))
        reopened = Application(self.storage, provider=NoProvider())
        self.addCleanup(reopened.scheduler.shutdown, 5)
        self.assertEqual(reopened.public()['project_id'], self.a)
        with self.assertRaisesRegex(ValueError, 'Unknown project'):
            self.app.handle('switch_project', {'project_id':'missing'})
        with self.assertRaises(ValueError):
            self.app.handle('add_project', {'path':str(self.base/'missing')})

    def test_project_summaries_hold_only_metadata(self):
        self.setup_app()
        self.app.handle('update_project',{'project_id':self.b,'name':'Project B','brief':'B_BRIEF_MARKER','priority':'high','next_action':'Compare options'})
        summary = next(p for p in self.app.public()['projects'] if p['id'] == self.b)
        self.assertEqual(summary, {'id':self.b,'name':'Project B','brief':'B_BRIEF_MARKER','priority':'high','next_action':'Compare options'})
        self.assertNotIn('B_SOURCE_MARKER', json.dumps(self.app.public()))

    def test_metadata_validation_is_atomic(self):
        self.setup_app()
        before=copy.deepcopy(self.app.public()['projects'])
        with self.assertRaises(ValueError):
            self.app.handle('update_project',{'project_id':self.b,'name':'new','priority':'urgent'})
        self.assertEqual(self.app.public()['projects'],before)
        with self.assertRaises(ValueError):
            self.app.handle('update_project',{'project_id':self.b,'brief':'x'*1201})
        self.assertEqual(self.app.public()['projects'],before)

    def test_v1_migration_preserves_backup_threads_plan_and_usage(self):
        storage=self.base/'legacy'; storage.mkdir()
        run=runner.prepare(self.source,storage/'runs')
        legacy={'version':1,'project_path':str(self.source),'threads':{'workspace':[{'role':'user','text':'Workspace history'}],'project':[{'role':'user','text':'Private history'}]},'pending':{'id':'kept','goal':'Review'},'run_id':run.name,'active':None,'error':'','usage':[{'role':'Researcher','run_id':run.name,'tokens':{}}],'connection':{'ready':True,'message':'Connected'}}
        original=json.dumps(legacy).encode(); (storage/'state.json').write_bytes(original)
        app=Application(storage,provider=NoProvider())
        self.addCleanup(app.scheduler.shutdown, 5)
        public=app.public()
        self.assertEqual(public['version'],4)
        project=app.state['projects'][public['project_id']]
        self.assertEqual(app.state['threads']['workspace'],legacy['threads']['workspace'])  # Kept, no longer shown.
        self.assertEqual(project['thread'],legacy['threads']['project'])
        self.assertTrue(all(t['token_budget'] is None for t in project['tasks'].values()))
        self.assertTrue(all(t['status']=='read_only' for t in public['tasks']))
        self.assertEqual(public['task']['history']['plan'],'Goal: Review')
        run_task=next(t for t in project['tasks'].values() if run.name in t['run_ids'])
        self.assertEqual(run_task['run_id'],run.name)
        self.assertTrue((storage/'state.v2-backup.json').exists())
        self.assertEqual((storage/'state.v1-backup.json').read_bytes(),original)
        again=Application(storage,provider=NoProvider())
        self.addCleanup(again.scheduler.shutdown, 5)
        self.assertEqual((storage/'state.v1-backup.json').read_bytes(),original)
        self.assertEqual(app.state['usage'][0]['project_id'],public['project_id'])

    def test_unknown_schema_does_not_overwrite_state(self):
        storage=self.base/'future';storage.mkdir()
        original='{"version":999,"important":"preserve me"}'
        (storage/'state.json').write_text(original)
        with self.assertRaisesRegex(ValueError,'version|schema'):
            Application(storage,provider=NoProvider())
        self.assertEqual((storage/'state.json').read_text(),original)

    def test_v3_migration_adds_null_budgets_once_and_preserves_usage(self):
        self.setup_app();self.switch(self.a)
        project=self.app.state['projects'][self.a]
        task=tasks.imported('Existing task');project['tasks'][task['id']]=task;tid=task['id']
        for saved in project['tasks'].values():saved.pop('token_budget')
        self.app.state['version']=3
        self.app.state['usage'].append({'role':'Orchestrator','task_id':tid,'project_id':self.a,'tokens':{'input_tokens':10,'output_tokens':2}})
        self.app.persist();original=(self.app.storage/'state.json').read_bytes()
        migrated=Application(self.app.storage,provider=NoProvider())
        self.addCleanup(migrated.scheduler.shutdown, 5)
        self.assertEqual(migrated.state['version'],4)
        self.assertIsNone(migrated.state['projects'][self.a]['tasks'][tid]['token_budget'])
        self.assertEqual((self.app.storage/'state.v3-backup.json').read_bytes(),original)
        self.assertEqual(migrated.state['usage'][-1]['tokens'],{'input_tokens':10,'output_tokens':2})
        migrated.handle('switch_project',{'project_id':self.a});migrated.handle('select_task',{'project_id':self.a,'task_id':tid})
        self.assertEqual(migrated.public()['task']['tokens']['used'],12);self.assertIsNone(migrated.public()['task']['tokens']['budget'])
        again=Application(self.app.storage,provider=NoProvider())
        self.addCleanup(again.scheduler.shutdown, 5)
        self.assertEqual((self.app.storage/'state.v3-backup.json').read_bytes(),original)

    def test_malformed_budget_isolates_only_its_task(self):
        self.setup_app();self.switch(self.a)
        project=self.app.state['projects'][self.a]
        bad,good=tasks.imported('Bad budget'),tasks.imported('Good budget')
        bad['token_budget']='lots';project['tasks'].update({bad['id']:bad,good['id']:good});self.app.persist()
        reopened=Application(self.app.storage,provider=NoProvider())
        self.addCleanup(reopened.scheduler.shutdown, 5)
        reopened.handle('switch_project',{'project_id':self.a})
        statuses={t['id']:t['status'] for t in reopened.public()['tasks']}
        self.assertEqual(statuses[bad['id']],'unavailable');self.assertEqual(statuses[good['id']],'read_only')
        self.assertEqual(reopened.handle('select_task',{'project_id':self.a,'task_id':good['id']})['task']['token_budget'],250000)


if __name__ == '__main__':
    unittest.main()
