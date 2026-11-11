"""Project registry and cross-project isolation; never uses personal repositories or models."""
import copy
import json
from pathlib import Path
import shutil
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'app/backend'))
sys.path.insert(0, str(ROOT/'tests'))
import test_pilot
from service import Application
import runner


class RecordingProvider:
    def __init__(self):
        self.prompts = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False
    def run(self, prompt, schema, cwd, cancel):
        self.prompts.append(prompt)
        if self.block:
            self.entered.set()
            self.release.wait(3)
        if 'Role: Orchestrator' in prompt:
            return {'reply':'Review available', 'action':'propose_review'}, {'input_tokens':1}
        result = {'summary':'Saved result', 'proposal':'Proposal only', 'findings':[{'claim':'Evidence', 'evidence':[{'source':'README.md','start':1,'end':1}]}]}
        if 'Role: Reviewer' in prompt:
            result['verdict'] = 'accept'
        return result, {'input_tokens':1}


class ProjectTests(unittest.TestCase):
    setUp = test_pilot.PilotTests.setUp
    git = test_pilot.PilotTests.git

    def setup_app(self):
        self.provider = RecordingProvider()
        self.storage = self.base/'app-data'
        self.app = Application(self.storage, provider=self.provider)
        self.a = test_pilot.legacy_project(self.app, self.source)['project_id']
        self.other = self.base/'other'
        shutil.copytree(self.source, self.other)
        (self.other/'README.md').write_text('B_SOURCE_MARKER\n')
        runner.git(self.other,'add','README.md')
        runner.git(self.other,'commit','-qm','Other project')
        self.b = test_pilot.legacy_project(self.app, self.other)['project_id']

    def switch(self, project):
        return self.app.handle('switch_project', {'project_id':project})

    def chat(self, project, text):
        self.app.handle('chat', {'scope':'project','text':text,'project_id':project})
        self.app.wait()

    def start(self, project):
        self.app.handle('start_review', {'project_id':project,'plan_id':self.app.public()['pending']['id']})
        self.app.wait()

    def test_registry_retains_threads_plans_runs_and_deduplicates_paths(self):
        self.setup_app()
        self.switch(self.a); self.chat(self.a,'A_THREAD_MARKER'); self.start(self.a)
        a_run = self.app.public()['run']['id']
        self.switch(self.b); self.chat(self.b,'B_THREAD_MARKER'); self.start(self.b)
        b_run = self.app.public()['run']['id']
        self.assertNotEqual(a_run,b_run)
        self.switch(self.a)
        self.assertEqual(self.app.public()['run']['id'],a_run)
        self.assertNotIn('B_THREAD_MARKER',json.dumps(self.app.public()['threads']))
        self.chat(self.a,'Another A plan')
        plan = copy.deepcopy(self.app.public()['pending'])
        self.switch(self.b); self.switch(self.a)
        self.assertEqual(self.app.public()['pending'],plan)
        test_pilot.legacy_project(self.app, self.source/'.')
        self.assertEqual(len(self.app.public()['projects']),2)
        reopened=Application(self.storage,provider=self.provider)
        self.assertEqual(reopened.public()['threads'],self.app.public()['threads'])
        self.assertEqual(reopened.public()['pending'],plan)

    def test_workspace_metadata_excludes_source_reports_and_project_threads(self):
        self.setup_app()
        self.app.handle('update_project',{'project_id':self.b,'name':'Project B','brief':'B_BRIEF_MARKER','priority':'high','next_action':'Compare options'})
        self.chat(self.b,'B_THREAD_MARKER'); self.start(self.b)
        self.app.handle('chat',{'scope':'workspace','text':'Prioritize my projects'})
        self.app.wait()
        prompt = self.provider.prompts[-1]
        self.assertIn('B_BRIEF_MARKER',prompt)
        self.assertIn('high',prompt)
        for secret in ('B_SOURCE_MARKER','B_THREAD_MARKER','Saved result','UNCOMMITTED'):
            self.assertNotIn(secret,prompt)
        self.assertIsNone(self.app.public()['pending'])
        self.switch(self.a); self.chat(self.a,'A_THREAD_MARKER')
        for secret in ('B_BRIEF_MARKER','B_SOURCE_MARKER','B_THREAD_MARKER'):
            self.assertNotIn(secret,self.provider.prompts[-1])

    def test_active_chat_and_review_remain_owned_after_switch(self):
        self.setup_app(); self.switch(self.a)
        self.provider.block=True
        self.app.handle('chat',{'scope':'project','project_id':self.a,'text':'A_WORKER_MARKER'})
        self.assertTrue(self.provider.entered.wait(1))
        self.switch(self.b)
        self.assertEqual(self.app.public()['active_project_id'],self.a)
        self.provider.release.set(); self.app.wait()
        self.assertEqual(self.app.public()['threads']['project'],[])
        self.assertIsNone(self.app.public()['pending'])
        self.switch(self.a)
        self.assertEqual(self.app.public()['pending']['project_id'],self.a)
        self.provider.entered.clear(); self.provider.release.clear()
        self.app.handle('start_review',{'project_id':self.a,'plan_id':self.app.public()['pending']['id']})
        self.assertTrue(self.provider.entered.wait(1)); self.switch(self.b)
        self.provider.release.set(); self.app.wait()
        self.assertIsNone(self.app.public()['run'])
        self.assertEqual(self.app.public()['threads']['project'],[])
        self.switch(self.a)
        self.assertEqual(self.app.public()['run']['stage'],'completed')
        self.assertTrue(all(u['project_id']==self.a for u in self.app.public()['usage']))

    def test_cancelled_review_keeps_failure_and_partial_work_with_owner(self):
        self.setup_app(); self.switch(self.a); self.chat(self.a,'Review A')
        self.provider.block=True
        self.app.handle('start_review',{'project_id':self.a,'plan_id':self.app.public()['pending']['id']})
        self.assertTrue(self.provider.entered.wait(1))
        self.switch(self.b)
        self.app.handle('cancel',{})
        self.provider.release.set(); self.app.wait()
        self.assertIsNone(self.app.public()['run'])
        self.assertEqual(self.app.public()['error'],'')
        self.assertEqual(self.app.public()['threads']['project'],[])
        self.switch(self.a)
        self.assertEqual(self.app.public()['run']['stage'],'cancelled')
        self.assertIn('cancel',self.app.public()['error'].lower())
        self.assertNotIn('reviewer',self.app.public()['run']['results'])
        self.assertEqual(len(self.provider.prompts),2)

    def test_stale_cross_project_actions_and_unknown_run_rejected(self):
        self.setup_app(); self.switch(self.a); self.chat(self.a,'Review'); self.start(self.a)
        run=self.app.public()['run']; self.switch(self.b)
        for method, params in (
            ('chat',{'scope':'project','text':'Wrong destination'}),
            ('start_review',{'plan_id':'old'}),
            ('accept_report',{'run_id':run['id'],'artifact_id':run['artifact_id']}),
            ('revise_run',{'run_id':run['id'],'artifact_id':run['artifact_id']}),
            ('source',{'run_id':run['id'],'source':'README.md'}),
            ('select_run',{'run_id':run['id']}),
            ('update_project',{'brief':'Wrong project'})):
            with self.subTest(method=method), self.assertRaisesRegex(ValueError,'project|selected|stale'):
                self.app.handle(method,dict(params,project_id=self.a))
        with self.assertRaises(ValueError):
            self.app.handle('source',{'project_id':self.b,'run_id':run['id'],'source':'README.md'})
        self.assertEqual(self.app.public()['threads']['project'],[])
        with self.assertRaises(ValueError):
            self.app.handle('chat',{'scope':'project','text':'Missing identity'})

    def test_run_history_and_source_are_scoped_to_selected_project(self):
        self.setup_app(); self.switch(self.a); self.chat(self.a,'First'); self.start(self.a)
        old=self.app.public()['run']['id']
        self.chat(self.a,'Second'); self.start(self.a)
        self.assertEqual(len(self.app.public()['runs']),2)
        self.app.handle('select_run',{'project_id':self.a,'run_id':old})
        self.assertEqual(self.app.public()['run']['id'],old)
        content=self.app.handle('source',{'project_id':self.a,'run_id':old,'source':'README.md'})
        self.assertNotIn('UNCOMMITTED',content['text'])
        self.switch(self.b)
        self.assertEqual(self.app.public()['runs'],[])

    def test_readme_only_repository_supports_bounded_review(self):
        self.setup_app()
        runner.git(self.other,'rm','docs/PROJECT_CONTEXT.md')
        runner.git(self.other,'commit','-qm','README-only context')
        # Re-register refreshes the committed context choice without clearing data.
        test_pilot.legacy_project(self.app, self.other)
        self.chat(self.b,'Review README'); self.start(self.b)
        run=self.app.public()['run']
        self.assertEqual(run['stage'],'completed')
        self.assertEqual(run['project'],self.other.name)
        self.assertNotIn('docs/PROJECT_CONTEXT.md',run['sources'])

    def test_recovery_targets_active_owner_instead_of_browsed_project(self):
        self.setup_app(); self.switch(self.a)
        run=runner.prepare(self.source,self.storage/'runs')
        project=self.app.state['projects'][self.a]
        project.update(run_id=run.name,run_ids=[run.name])
        self.app.state.update(active='Researcher',active_project_id=self.a,active_run_id=run.name)
        self.app.persist(); self.switch(self.b)
        reopened=Application(self.storage,provider=self.provider)
        self.assertIsNone(reopened.public()['run'])
        self.assertEqual(runner.load(run)['stage'],'interrupted')
        reopened.handle('switch_project',{'project_id':self.a})
        self.assertIn('interrupted',reopened.public()['error'])

    def test_v1_migration_preserves_backup_threads_plan_and_usage(self):
        storage=self.base/'legacy'; storage.mkdir()
        run=runner.prepare(self.source,storage/'runs')
        legacy={'version':1,'project_path':str(self.source),'threads':{'workspace':[{'role':'user','text':'Workspace history'}],'project':[{'role':'user','text':'Private history'}]},'pending':{'id':'kept','goal':'Review'},'run_id':run.name,'active':None,'error':'','usage':[{'role':'Researcher','run_id':run.name,'tokens':{}}],'connection':{'ready':True,'message':'Connected'}}
        original=json.dumps(legacy).encode(); (storage/'state.json').write_bytes(original)
        app=Application(storage,provider=RecordingProvider())
        self.assertEqual(app.public()['version'],2)
        self.assertEqual(app.public()['threads'],legacy['threads'])
        self.assertEqual(app.public()['pending']['id'],'kept')
        self.assertEqual(app.public()['run']['id'],run.name)
        self.assertEqual((storage/'state.v1-backup.json').read_bytes(),original)
        Application(storage,provider=RecordingProvider())
        self.assertEqual((storage/'state.v1-backup.json').read_bytes(),original)
        self.assertEqual(app.public()['usage'][0]['project_id'],app.public()['project_id'])

    def test_unreadable_snapshot_does_not_block_other_projects_or_restart(self):
        self.setup_app(); self.switch(self.a); self.chat(self.a,'Review A'); self.start(self.a)
        run_id=self.app.public()['run']['id']
        (self.storage/'runs'/run_id/'sources/README.md').write_text('Corrupted snapshot')
        self.app.state.update(active='Researcher',active_project_id=self.a,active_run_id=run_id)
        self.app.state['selected_project_id']=self.b
        self.app.persist()
        reopened=Application(self.storage,provider=self.provider)
        self.assertEqual(reopened.public()['project_id'],self.b)
        self.assertEqual(reopened.public()['projects'][0]['latest_run']['stage'],'unavailable')
        reopened.handle('chat',{'scope':'project','project_id':self.b,'text':'Review B'})
        reopened.wait()
        self.assertIsNotNone(reopened.public()['pending'])
        reopened.handle('switch_project',{'project_id':self.a})
        self.assertIsNone(reopened.public()['run'])
        self.assertIn('unavailable',reopened.public()['error'].lower())
        with self.assertRaises(ValueError):
            reopened.handle('source',{'project_id':self.a,'run_id':run_id,'source':'README.md'})

    def test_missing_and_malformed_run_metadata_remain_isolated(self):
        self.setup_app(); self.switch(self.a); self.chat(self.a,'Review A'); self.start(self.a)
        run=self.storage/'runs'/self.app.public()['run']['id']
        record=runner.load(run)
        record.pop('goal')
        runner.save(run/'run.json',record)
        self.app.state['selected_project_id']=self.b
        self.assertEqual(self.app.public()['projects'][0]['latest_run']['stage'],'unavailable')
        self.switch(self.a)
        self.assertIsNone(self.app.public()['run'])
        self.switch(self.b)
        (run/'run.json').unlink()
        self.assertEqual(self.app.public()['projects'][0]['latest_run']['stage'],'unavailable')
        self.switch(self.a)
        self.assertIsNone(self.app.public()['run'])

    def test_unknown_schema_does_not_overwrite_state(self):
        storage=self.base/'future';storage.mkdir()
        original='{"version":999,"important":"preserve me"}'
        (storage/'state.json').write_text(original)
        with self.assertRaisesRegex(ValueError,'version|schema'):
            Application(storage,provider=RecordingProvider())
        self.assertEqual((storage/'state.json').read_text(),original)

    def test_metadata_validation_is_atomic(self):
        self.setup_app()
        before=copy.deepcopy(self.app.public()['projects'])
        with self.assertRaises(ValueError):
            self.app.handle('update_project',{'project_id':self.b,'name':'new','priority':'urgent'})
        self.assertEqual(self.app.public()['projects'],before)
        with self.assertRaises(ValueError):
            self.app.handle('update_project',{'project_id':self.b,'brief':'x'*1201})
