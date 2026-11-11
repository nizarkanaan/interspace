import copy
import json
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'app/backend'))
sys.path.insert(0, str(ROOT/'tests'))
import test_pilot
from service import Application
from provider import ProviderError
import runner


def result(summary='Original', verdict=None):
    value = {'summary':summary,'findings':[{'claim':'Committed evidence','evidence':[{'source':'README.md','start':1,'end':1}]}], 'proposal':'A proposal only; no experiment executed.'}
    if verdict:
        value['verdict'] = verdict
    return value


class Scripted:
    def __init__(self, verdict='accept'):
        self.prompts = []
        self.verdict = verdict
    def run(self,prompt,schema,cwd,cancel):
        self.prompts.append(prompt)
        if 'Role: Orchestrator' in prompt:
            return {'reply':'Revise the current report using its reviewer feedback.','action':'propose_revision'}, {}
        return result('Revised' if 'Role: Researcher' in prompt else 'Rechecked', self.verdict if 'Role: Reviewer' in prompt else None), {'input_tokens':2,'output_tokens':1}


class RevisionTests(unittest.TestCase):
    setUp = test_pilot.PilotTests.setUp
    git = test_pilot.PilotTests.git

    def seed(self, verdict='revise', provider=None):
        self.provider = provider or Scripted()
        self.app = Application(self.base/'app-state',provider=self.provider)
        self.run = runner.prepare(self.source,self.app.storage/'runs')
        runner.start(self.run,'researcher')
        runner.complete(self.run,'researcher',result())
        runner.start(self.run,'reviewer')
        runner.complete(self.run,'reviewer',result('Define contact events precisely before acceptance.',verdict))
        self.app.state.update(project_path=str(self.source),run_id=self.run.name)
        self.app.persist()
        return self.app.public()['run']

    def reference(self, record):
        return {'run_id':record['id'],'artifact_id':record.get('artifact_id','MISSING')}

    def test_revision_preserves_previous_artifacts_and_transfers_feedback(self):
        original = self.seed()
        original_results = copy.deepcopy(original['results'])
        self.app.handle('revise_run', self.reference(original))
        self.app.wait()
        current = self.app.public()['run']
        self.assertEqual(current['stage'],'completed')
        self.assertEqual(current['revision_round'],1)
        self.assertEqual(current['previous_attempts'][0]['results'],original_results)
        self.assertNotEqual(current['artifact_id'],original.get('artifact_id'))
        self.assertIn('Define contact events precisely',self.provider.prompts[0])
        self.assertIn('Original',self.provider.prompts[0])
        self.assertNotIn('UNCOMMITTED secret draft',self.provider.prompts[0])
        self.assertEqual(len(self.provider.prompts),2)
        self.assertTrue(current['verification']['unchanged'])
        self.assertEqual(len([e for e in current['events'] if e.get('round',0)==1 and e['status']=='started']),2)

    def test_one_revision_round_is_durable_and_cannot_repeat(self):
        original=self.seed(provider=Scripted('revise'))
        self.app.handle('revise_run',self.reference(original));self.app.wait()
        restarted=Application(self.app.storage,provider=self.provider)
        current=restarted.public()['run']
        with self.assertRaisesRegex(ValueError,'limit'):
            restarted.handle('revise_run',self.reference(current))
        self.assertEqual(len(self.provider.prompts),2)
        self.assertEqual(current['stage'],'needs_revision')

    def test_acceptance_is_content_bound_and_not_an_experiment_approval(self):
        record=self.seed('accept')
        with self.assertRaisesRegex(ValueError,'stale'):
            self.app.handle('accept_report',{'run_id':record['id'],'artifact_id':'wrong'})
        self.app.handle('accept_report',self.reference(record))
        current=self.app.public()['run']
        self.assertEqual(current['stage'],'accepted')
        self.assertTrue(current['verification']['unchanged'])
        self.assertEqual(current['user_acceptance']['artifact_id'],record.get('artifact_id'))
        count=len(current['events'])
        self.app.handle('accept_report',self.reference(record))
        self.assertEqual(len(self.app.public()['run']['events']),count)
        self.assertEqual(len(self.provider.prompts),0)
        self.assertEqual(current['user_acceptance']['scope'],'report_only')

    def test_report_needing_revision_cannot_be_accepted(self):
        record=self.seed()
        with self.assertRaisesRegex(ValueError,'review'):
            self.app.handle('accept_report',self.reference(record))
        self.assertEqual(len(self.provider.prompts),0)

    def test_modified_artifact_and_changed_source_reject_stale_revision(self):
        record=self.seed()
        raw=json.loads((self.run/'run.json').read_text())
        raw['results']['researcher']['summary']='Different artifact'
        runner.save(self.run/'run.json',raw)
        with self.assertRaisesRegex(ValueError,'stale'):
            self.app.handle('revise_run',self.reference(record))
        current=self.app.public()['run']
        (self.source/'README.md').write_text('A changed working tree')
        with self.assertRaisesRegex(ValueError,'changed'):
            self.app.handle('revise_run',self.reference(current))
        self.assertEqual(len(self.provider.prompts),0)

    def test_failure_keeps_previous_attempt_and_spends_round_without_reviewer(self):
        class Invalid(Scripted):
            def run(self,*args):
                self.prompts.append(args[0])
                return {'summary':'Broken','findings':[],'proposal':'Missing evidence'}, {}
        record=self.seed(provider=Invalid())
        self.app.handle('revise_run',self.reference(record));self.app.wait()
        current=self.app.public()['run']
        self.assertEqual(current['stage'],'failed')
        self.assertEqual(current['revision_round'],1)
        self.assertEqual(current['previous_attempts'][0]['results']['researcher']['summary'],'Original')
        self.assertEqual(len(self.provider.prompts),1)

    def test_cancelled_revision_retains_history_and_never_dispatches_reviewer(self):
        entered=threading.Event()
        class Slow(Scripted):
            def run(self,prompt,schema,cwd,cancel):
                self.prompts.append(prompt);entered.set();cancel.wait(2)
                raise ProviderError('cancelled')
        record=self.seed(provider=Slow())
        self.app.handle('revise_run',self.reference(record))
        self.assertTrue(entered.wait(2))
        with self.assertRaisesRegex(ValueError,'active'):
            self.app.handle('revise_run',self.reference(record))
        self.app.handle('cancel',{});self.app.wait()
        current=self.app.public()['run']
        self.assertEqual(current['stage'],'cancelled')
        self.assertEqual(current['revision_round'],1)
        self.assertEqual(len(current['previous_attempts']),1)
        self.assertEqual(len(self.provider.prompts),1)

    def test_active_revision_restart_preserves_spent_round_and_old_results(self):
        import revisions
        self.seed()
        revisions.begin_revision(self.run)
        self.app.state['active']='Researcher'
        self.app.persist()
        restored=Application(self.app.storage,provider=self.provider)
        current=restored.public()['run']
        self.assertEqual(current['stage'],'interrupted')
        self.assertEqual(current['revision_round'],1)
        self.assertEqual(len(current['previous_attempts']),1)
        self.assertEqual(len(self.provider.prompts),0)
        with self.assertRaisesRegex(ValueError,'limit'):
            restored.handle('revise_run',self.reference(current))

    def test_changed_source_cannot_be_accepted(self):
        record=self.seed('accept')
        (self.source/'README.md').write_text('Changed after review')
        with self.assertRaisesRegex(ValueError,'changed'):
            self.app.handle('accept_report',self.reference(record))
        self.assertNotIn('user_acceptance',self.app.public()['run'])
        self.assertEqual(len(self.provider.prompts),0)

    def test_orchestrator_can_propose_version_bound_revision(self):
        record=self.seed()
        self.app.handle('chat',{'scope':'project','text':'Address reviewer feedback and include a numbered correction log.'})
        self.app.wait()
        pending=self.app.public()['pending']
        self.assertIsNotNone(pending)
        self.assertEqual(pending['kind'],'revision')
        self.assertEqual(pending['artifact_id'],record.get('artifact_id'))
        self.app.handle('start_review',{'plan_id':pending['id']});self.app.wait()
        self.assertEqual(self.app.public()['run']['stage'],'completed')
        self.assertEqual(len(self.provider.prompts),3)
        self.assertIn('include a numbered correction log',self.provider.prompts[1])
        self.assertIn('include a numbered correction log',self.provider.prompts[2])


if __name__=='__main__':
    unittest.main()
