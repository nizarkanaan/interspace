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

    def test_internal_job_and_tab_names_cannot_be_task_ids(self):
        for name in ('synthesis','combined','sources','events'):
            task=assignment('researcher');task['id']=name
            with self.subTest(identity=name),self.assertRaises(ValueError):teams.validate_tasks([task])

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

    def test_provider_schema_and_runtime_agree_on_evidence_count_for_every_kind(self):
        record=self.prepare()
        evidence_schema=teams.RESULT_SCHEMA['properties']['findings']['items']['properties']['evidence']
        for kind in ('fact','interpretation','proposal'):
            for count,allowed in ((0,False),(1,True),(10,True),(11,False)):
                with self.subTest(kind=kind,count=count):
                    value=report();finding=value['findings'][0]
                    finding.update(kind=kind,evidence=finding['evidence']*count)
                    # Check the array limits advertised to the provider, independently
                    # of the application validator which originally rejected its output.
                    schema_allows=(evidence_schema.get('minItems',0)<=count<=
                                   evidence_schema.get('maxItems',float('inf')))
                    self.assertEqual(schema_allows,allowed)
                    if allowed:
                        self.assertEqual(teams.validate_artifact(record,record['tasks'][0],value),value)
                    else:
                        with self.assertRaises(ValueError):
                            teams.validate_artifact(record,record['tasks'][0],value)

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


def named_assignment(identity, role, dependencies=()):
    return dict(assignment(role, dependencies), id=identity)


class ExpandedPolicyTests(unittest.TestCase):
    def test_explicit_policy_allows_repeated_roles_and_independent_reviewers(self):
        tasks=[named_assignment('search_a','web_searcher'),named_assignment('search_b','web_searcher'),
               named_assignment('analysis','researcher',['search_a','search_b']),
               named_assignment('review_a','reviewer',['analysis']),named_assignment('review_b','reviewer',['analysis'])]
        self.assertEqual([t['id'] for t in teams.validate_tasks(tasks,policy_version=2,specialist_limit=6)],
                         ['search_a','search_b','analysis','review_a','review_b'])
        with self.assertRaises(ValueError):teams.validate_tasks(tasks)
        with self.assertRaises(ValueError):teams.validate_tasks(tasks[:2])
        with self.assertRaises(ValueError):teams.validate_tasks(tasks,policy_version=2,specialist_limit=4)

    def test_raised_allowance_bounds_actual_dependencies_instead_of_six_roles(self):
        tasks=[named_assignment('analysis_'+str(i),'researcher') for i in range(7)]
        tasks.append(named_assignment('review','reviewer',[t['id'] for t in tasks]))
        self.assertEqual(len(teams.validate_tasks(tasks,policy_version=2,specialist_limit=8)),8)
        for changed in ([named_assignment('review','reviewer')],
                        [named_assignment('a','researcher'),named_assignment('a','researcher')],
                        [named_assignment('a','researcher',['b']),named_assignment('b','researcher',['a'])],
                        [named_assignment('a','researcher'),named_assignment('b','researcher'),named_assignment('r','reviewer',['a'])],
                        [named_assignment('synthesis','researcher')]):
            with self.subTest(tasks=changed),self.assertRaises(ValueError):
                teams.validate_tasks(changed,policy_version=2,specialist_limit=8)

    def test_allowance_requires_positive_javascript_safe_integer_and_schema_is_copied(self):
        for invalid in (True,False,0,-1,1.0,1.5,'6',None,9007199254740992):
            with self.subTest(value=invalid),self.assertRaises(ValueError):teams.validate_specialist_limit(invalid)
        self.assertEqual(teams.validate_specialist_limit(9007199254740991),9007199254740991)
        schema=teams.chat_schema(8)
        self.assertEqual(schema['properties']['tasks']['maxItems'],8)
        self.assertEqual(schema['properties']['tasks']['items']['properties']['dependencies']['maxItems'],7)
        schema['properties']['tasks']['items']['properties']['dependencies']['maxItems']=0
        self.assertNotIn('maxItems',teams.TASK_SCHEMA['properties']['dependencies'])


class ExpandedArtifactTests(unittest.TestCase):
    setUp=test_pilot.PilotTests.setUp
    git=test_pilot.PilotTests.git
    def expanded(self,tasks,limit=6):
        self.project={'id':'project-a','name':'Fixture','source_path':str(self.source),'context_path':'docs/PROJECT_CONTEXT.md'}
        self.plan=teams.make_plan(self.project,self.git('rev-parse','HEAD'),'Review fixture',tasks,
                                  specialist_limit=limit,task_id='user-task-a')
        self.run=teams.prepare(self.project,self.plan,self.base/'runs')
        return runner.load(self.run)

    def test_exact_allowance_task_identity_and_policy_are_approval_bound(self):
        record=self.expanded([named_assignment('analysis','researcher')],8)
        self.assertEqual(self.plan['policy_version'],2)
        self.assertEqual(record['task_id'],'user-task-a')
        self.assertEqual(self.plan['limits']['specialist_limit'],8)
        teams.validate_record(record)
        for field,value in (('specialist_limit',9),('stage_seconds',241)):
            changed=copy.deepcopy(self.plan);changed['limits'][field]=value
            with self.assertRaises(ValueError):teams.validate_plan(changed)
        changed=copy.deepcopy(self.plan);changed['task_id']='other'
        with self.assertRaises(ValueError):teams.validate_plan(changed)
        record['task_id']='other'
        with self.assertRaises(ValueError):teams.validate_record(record)

    def test_two_searchers_retain_twenty_sources_and_reject_cross_branch_citations(self):
        record=self.expanded([named_assignment('search_a','web_searcher'),named_assignment('search_b','web_searcher'),
                              named_assignment('analysis','researcher',['search_a'])])
        for task in record['tasks'][:2]:
            value={'summary':'Search result','sources':[{'url':'https://example.org/'+task['id']+'/'+str(i),
                   'title':'Paper','excerpt':'Observed excerpt'} for i in range(10)],'questions':[]}
            result=teams.validate_artifact(record,task,value,[s['url'] for s in value['sources']])
            record['results'][task['id']]=result
        self.assertEqual(len(record['evidence']),20)
        teams.validate_record(record)
        a=record['results']['search_a']['web_sources'][0];b=record['results']['search_b']['web_sources'][0]
        self.assertIn(':search_a:0',a)
        teams.validate_artifact(record,record['tasks'][2],report(source=a))
        with self.assertRaisesRegex(ValueError,'dependency|ancestor|branch'):
            teams.validate_artifact(record,record['tasks'][2],report(source=b))
        record['evidence'][a]['task_id']='analysis'
        with self.assertRaises(ValueError):teams.validate_record(record)

    def test_acceptance_requires_all_reviewers_accept(self):
        record=self.expanded([named_assignment('analysis','researcher'),named_assignment('review_a','reviewer',['analysis']),
                              named_assignment('review_b','reviewer',['analysis'])])
        record.update(stage='completed',results={'analysis':report(),'review_a':report('accept'),'review_b':report('revise')},combined=report())
        runner.save(self.run/'run.json',record)
        reference={'run_id':record['id'],'artifact_id':teams.artifact_id(record)}
        with self.assertRaises(ValueError):teams.accept(self.run,reference)
        record['results']['review_b']=report('accept');runner.save(self.run/'run.json',record)
        reference['artifact_id']=teams.artifact_id(record)
        self.assertTrue(teams.accept(self.run,reference))
