"""Source-consent workflow with real state/snapshots and controlled model boundaries."""
import copy
import json
from pathlib import Path
import sys
import threading
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app/backend'),str(ROOT/'tests')]
import test_pilot
from service import Application
from test_team import TeamProvider
from test_orchestration import assignment,report
import sources
import runner


class SelectedProvider(TeamProvider):
    def run(self,prompt,schema,cwd,cancel):
        result,usage=super().run(prompt,schema,cwd,cancel)
        if 'Role: Orchestrator' not in prompt or 'Purpose: synthesis' in prompt:
            for finding in result['findings']:
                for citation in finding['evidence']:citation['source']='notes/selected.txt'
        return result,usage


class SourceWorkflowTests(unittest.TestCase):
    setUp=test_pilot.PilotTests.setUp
    git=test_pilot.PilotTests.git
    def setup_app(self,tasks=None):
        (self.source/'notes').mkdir()
        (self.source/'notes/selected.txt').write_text('SELECTED_COMMITTED_MARKER\nEvidence line\n')
        (self.source/'notes/private.txt').write_text('UNSELECTED_COMMITTED_MARKER\n')
        self.git('add','notes');self.git('commit','-qm','Selection fixture')
        (self.source/'notes/selected.txt').write_text('DIRTY_SELECTED_DRAFT')
        self.provider=SelectedProvider(tasks)
        self.app=Application(self.base/'app-data',provider=self.provider)
        self.pid=self.app.handle('add_project',{'path':str(self.source)})['project_id']
    def save(self,chosen=None,catalog=None):
        c=catalog or self.app.handle('list_sources',{'project_id':self.pid})
        return self.app.handle('save_sources',{'project_id':self.pid,'revision':c['revision'],
          'selection_version':c['selection']['selection_version'],'paths':chosen or ['notes/selected.txt']})
    def chat(self):
        self.app.handle('chat',{'project_id':self.pid,'scope':'project','text':'Review selected evidence'})
        self.app.wait();return self.app.public()['pending']
    def start(self,plan):
        self.app.handle('start_plan',{'project_id':self.pid,'plan_id':plan['id'],'plan_digest':plan['digest']})
        self.app.wait();return self.app.public()['run']
    def test_new_project_needs_explicit_save_without_consuming_a_model_call(self):
        self.setup_app()
        with self.assertRaisesRegex(ValueError,'Save|Sources'):self.chat()
        self.assertEqual(self.provider.calls,[])
        self.assertEqual(self.app.public()['threads']['project'],[])
        self.save();plan=self.chat()
        self.assertEqual(plan['source_scope']['paths'],['notes/selected.txt'])
        self.assertEqual(plan['source_scope']['selection_version'],1)
        prompt=self.provider.calls[0]
        self.assertIn('SELECTED_COMMITTED_MARKER',prompt)
        for secret in ('UNSELECTED_COMMITTED_MARKER','DIRTY_SELECTED_DRAFT','Current context','UNCOMMITTED secret'):
            self.assertNotIn(secret,prompt)
    def test_selected_team_snapshot_and_accepted_report_survive_source_edits(self):
        self.setup_app();self.save();run=self.start(self.chat())
        self.assertEqual(run['format'],'team-v2');self.assertEqual(run['stage'],'completed')
        self.assertEqual(set(run['sources']),{'notes/selected.txt'})
        ref={'project_id':self.pid,'run_id':run['id'],'artifact_id':run['artifact_id']}
        self.app.handle('accept_report',ref)
        self.save(['README.md'])
        self.assertEqual(self.app.public()['run']['stage'],'accepted')
        self.assertEqual(self.app.public()['run']['artifact_id'],ref['artifact_id'])
        self.assertEqual(self.app.handle('source',dict(ref,source='notes/selected.txt'))['text'],'SELECTED_COMMITTED_MARKER\nEvidence line\n')
        restored=Application(self.app.storage,provider=self.provider)
        self.assertEqual(restored.public()['run']['stage'],'accepted')
        self.assertEqual(restored.public()['source_selection']['paths'],['README.md'])
    def test_save_is_compare_and_set_and_invalidates_pending_plan(self):
        self.setup_app();c=self.app.handle('list_sources',{'project_id':self.pid});self.save(catalog=c)
        plan=self.chat();self.save(['README.md'])
        self.assertIsNone(self.app.public()['pending'])
        with self.assertRaisesRegex(ValueError,'stale|changed'):self.save(catalog=c)
        with self.assertRaises(ValueError):self.start(plan)
        self.assertEqual(len(self.provider.calls),1)
    def test_commit_changes_require_reconfirmation_before_chat_or_start(self):
        self.setup_app();self.save();plan=self.chat()
        (self.source/'notes/selected.txt').write_text('New committed version\n');self.git('add','notes/selected.txt');self.git('commit','-qm','Change')
        with self.assertRaises(ValueError):self.start(plan)
        with self.assertRaises(ValueError):self.chat()
        self.assertEqual(len(self.provider.calls),1)
        c=self.app.handle('list_sources',{'project_id':self.pid});self.save(catalog=c)
        self.assertIsNotNone(self.chat())
    def test_workspace_and_web_prompts_exclude_selected_source_bodies(self):
        tasks=[assignment('web_searcher'),assignment('researcher',['web_searcher']),assignment('reviewer',['researcher'])]
        self.setup_app(tasks);self.save();run=self.start(self.chat())
        self.assertEqual(run['stage'],'completed')
        web=self.provider.calls[1]
        self.assertNotIn('SELECTED_COMMITTED_MARKER',web);self.assertNotIn('notes/selected.txt',web)
        self.provider.answer=True
        self.app.handle('chat',{'scope':'workspace','text':'Prioritize metadata'});self.app.wait()
        self.assertNotIn('SELECTED_COMMITTED_MARKER',self.provider.calls[-1])
    def test_source_saving_is_blocked_during_active_work_but_preview_is_readable(self):
        self.setup_app();self.save();c=self.app.handle('list_sources',{'project_id':self.pid})
        self.provider.block='Role: Orchestrator'
        self.app.handle('chat',{'project_id':self.pid,'scope':'project','text':'Review'})
        self.assertTrue(self.provider.entered.wait(2))
        try:
            with self.assertRaisesRegex(ValueError,'active'):self.save(catalog=c)
            p=self.app.handle('preview_source',{'project_id':self.pid,'revision':c['revision'],'path':'notes/selected.txt'})
            self.assertIn('SELECTED_COMMITTED_MARKER',p['text'])
        finally:self.provider.release.set();self.app.wait()
    def test_malformed_source_settings_do_not_fall_back_or_break_other_state(self):
        self.setup_app();self.app.state['projects'][self.pid]['source_selection']={'mode':'selected'}
        state=self.app.public()
        self.assertTrue(state['source_error'])
        with self.assertRaises(ValueError):self.chat()
        self.assertEqual(len(self.provider.calls),0)
        self.app.persist();restored=Application(self.app.storage,provider=self.provider)
        self.assertTrue(restored.public()['source_error'])
    def test_old_projects_and_team_v1_reports_remain_usable(self):
        self.setup_app();self.app.state['projects'][self.pid].pop('source_selection',None)
        self.provider=TeamProvider();self.app.provider=self.provider
        run=self.start(self.chat());self.assertEqual(run['format'],'team-v1')
        self.save()
        self.assertEqual(self.app.public()['run']['format'],'team-v1')
        self.app.handle('accept_report',{'project_id':self.pid,'run_id':run['id'],'artifact_id':run['artifact_id']})
        self.assertEqual(self.app.public()['run']['stage'],'accepted')

    def test_restored_stale_proposal_cannot_bypass_changed_selection(self):
        self.setup_app();self.save();old=self.chat();self.save(['README.md'])
        self.app.state['projects'][self.pid]['pending']=copy.deepcopy(old)
        with self.assertRaisesRegex(ValueError,'selection|stale'):self.start(old)
        self.assertEqual(len(self.provider.calls),1)
        self.assertIsNone(self.app.public()['run'])

    def test_source_actions_reject_requests_for_another_selected_project(self):
        import shutil
        self.setup_app();catalog=self.app.handle('list_sources',{'project_id':self.pid})
        other=self.base/'other';shutil.copytree(self.source,other)
        self.app.handle('add_project',{'path':str(other)})
        for method,params in [('list_sources',{}),('preview_source',{'revision':catalog['revision'],'path':'notes/selected.txt'}),('save_sources',{'revision':catalog['revision'],'selection_version':0,'paths':['notes/selected.txt']})]:
            with self.subTest(method=method),self.assertRaisesRegex(ValueError,'selected|stale'):
                self.app.handle(method,dict(params,project_id=self.pid))
        self.assertEqual(self.provider.calls,[])
