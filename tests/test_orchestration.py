"""Team policy, provenance and approvals, using only disposable repositories."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'app/backend'))
sys.path.insert(0, str(ROOT/'tests'))
sys.path.insert(0, str(ROOT/'pilot'))
import test_pilot
import runner
import orchestration as teams


def assignment(role, dependencies=()):
    return {'id':role, 'role':role, 'objective':'Inspect evidence for '+role,
            'expected_output':'A concise evidenced result', 'dependencies':list(dependencies)}


def report(verdict='not_reviewed', source='README.md'):
    return {'summary':'Evidence summary', 'findings':[{'claim':'Evidence exists', 'kind':'fact',
            'evidence':[{'source':source,'start':1,'end':1}]}], 'questions':['What remains unknown?'], 'verdict':verdict}


class PolicyTests(unittest.TestCase):
    def test_minimal_graph_and_transitive_review_coverage(self):
        tasks=[assignment('web_searcher'),assignment('researcher',['web_searcher']),assignment('reviewer',['researcher'])]
        self.assertEqual([t['id'] for t in teams.validate_tasks(tasks)], ['web_searcher','researcher','reviewer'])
        self.assertEqual(teams.validate_tasks([assignment('researcher')])[0]['role_version'],1)
        bad_cases=[[],tasks+[assignment('researcher')], [assignment('builder')],
                   [assignment('reviewer')], [assignment('researcher',['missing'])],
                   [assignment('researcher',['researcher'])],
                   [assignment('researcher',['reviewer']),assignment('reviewer',['researcher'])],
                   [assignment('web_searcher'),assignment('researcher'),assignment('reviewer',['researcher'])],
                   [assignment('researcher'),assignment('web_searcher',['researcher'])]]
        for bad in bad_cases:
            with self.subTest(tasks=bad),self.assertRaises(ValueError): teams.validate_tasks(bad)

    def test_model_cannot_grant_capabilities_or_supply_unbounded_fields(self):
        task=assignment('researcher'); task['capabilities']=['shell']
        with self.assertRaises(ValueError): teams.validate_tasks([task])
        for key,value in [('objective','x'*2001),('id','../escape'),('dependencies','researcher'),('role',True),('role',[])]:
            task=assignment('researcher');task[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError): teams.validate_tasks([task])

    def test_public_urls_reject_credentials_private_literals_and_local_names(self):
        for value in ['file:///etc/passwd','https://user:secret@example.org/','http://127.0.0.1/',
                      'http://[::1]/','https://10.1.2.3/','https://localhost/','https://foo.local/',
                      'https://2130706433/','https://127.1/','javascript:alert(1)','https://example.org/\n']:
            with self.subTest(value=value),self.assertRaises(ValueError): teams.public_url(value)
        self.assertEqual(teams.public_url('https://example.org/paper'), 'https://example.org/paper')


class ArtifactTests(unittest.TestCase):
    setUp=test_pilot.PilotTests.setUp
    git=test_pilot.PilotTests.git

    def prepare(self, tasks=None):
        self.project={'id':'project-a','name':'Fixture','source_path':str(self.source),'context_path':'docs/PROJECT_CONTEXT.md'}
        self.plan=teams.make_plan(self.project,self.git('rev-parse','HEAD'),'Review fixture',tasks or [assignment('researcher'),assignment('reviewer',['researcher'])])
        self.run=teams.prepare(self.project,self.plan,self.base/'runs')
        return runner.load(self.run)

    def test_plan_digest_covers_assignments_limits_and_scope(self):
        self.prepare()
        self.assertEqual(self.plan['digest'],teams.plan_digest(self.plan))
        for field in ('goal','revision','project_id','tasks','limits'):
            changed=copy.deepcopy(self.plan)
            changed[field]='changed'
            self.assertNotEqual(self.plan['digest'],teams.plan_digest(changed))

    def test_snapshot_and_run_format_preserve_dirty_source_and_legacy_helpers(self):
        before=runner.fingerprint(self.source);record=self.prepare()
        self.assertEqual(record['format'],'team-v1')
        self.assertEqual(record['stage'],'queued')
        self.assertEqual(record['plan']['digest'],self.plan['digest'])
        self.assertEqual(record['tasks'][1]['status'],'waiting')
        self.assertEqual(record['limits']['max_calls'],3)
        self.assertEqual(before,runner.fingerprint(self.source))
        self.assertNotIn('UNCOMMITTED',(self.run/'sources/README.md').read_text())

    def test_artifacts_reject_unknown_evidence_and_invalid_lines(self):
        record=self.prepare();task=record['tasks'][0]
        valid=teams.validate_artifact(record,task,report())
        self.assertEqual(valid['summary'],'Evidence summary')
        for value in (report(source='../private'),report(source='web:another-run:0')):
            with self.assertRaises(ValueError): teams.validate_artifact(record,task,value)
        value=report(); value['findings'][0]['evidence'][0]['end']=999
        with self.assertRaises(ValueError): teams.validate_artifact(record,task,value)
        with self.assertRaises(ValueError): teams.validate_artifact(record,record['tasks'][1],report())

    def test_web_sources_need_observed_public_provenance_before_becoming_evidence(self):
        record=self.prepare([assignment('web_searcher')]);task=record['tasks'][0]
        value={'summary':'Search result','sources':[{'url':'https://example.org/paper','title':'Paper','excerpt':'Observed supporting excerpt'}],'questions':[]}
        with self.assertRaisesRegex(ValueError,'observed|provenance'): teams.validate_artifact(record,task,value)
        self.assertEqual(record['evidence'],{})
        artifact=teams.validate_artifact(record,task,value,['https://example.org/paper'])
        source_id=artifact['web_sources'][0]
        self.assertIn(record['id'],source_id)
        self.assertEqual(record['evidence'][source_id]['url'],'https://example.org/paper')
        self.assertTrue(record['evidence'][source_id]['retrieved_at'])
        self.assertEqual(teams.validate_artifact(record,{'role':'researcher'},report(source=source_id))['summary'],'Evidence summary')
        value['sources'][0]['url']='http://localhost/'
        with self.assertRaises(ValueError): teams.validate_artifact(record,task,value,['http://localhost/'])

    def test_acceptance_binds_plan_evidence_results_and_combined_content(self):
        record=self.prepare()
        record.update(stage='completed',results={'researcher':report(),'reviewer':report('accept')},combined=report())
        runner.save(self.run/'run.json',record)
        reference={'run_id':record['id'],'artifact_id':teams.artifact_id(record)}
        self.assertTrue(teams.accept(self.run,reference))
        self.assertFalse(teams.accept(self.run,reference))
        changed=runner.load(self.run);changed['combined']['summary']='Changed'
        runner.save(self.run/'run.json',changed)
        with self.assertRaisesRegex(ValueError,'stale|changed'): teams.accept(self.run,reference)
        changed['stage']='completed_unreviewed'; changed['results'].pop('reviewer'); runner.save(self.run/'run.json',changed)
        reference['artifact_id']=teams.artifact_id(changed)
        with self.assertRaises(ValueError): teams.accept(self.run,reference)

    def test_interrupt_preserves_done_artifacts_and_blocks_future_jobs(self):
        record=self.prepare();record['tasks'][0]['status']='running'
        record['jobs']=[{'id':'researcher','status':'reserved','tokens':None}]
        teams.interrupt(record,'cancelled','User stopped')
        self.assertEqual(record['tasks'][0]['status'],'cancelled')
        self.assertEqual(record['tasks'][1]['status'],'blocked')
        self.assertEqual(record['stage'],'cancelled')
        self.assertIsNone(record['jobs'][0]['tokens'])
