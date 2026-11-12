"""Controlled editing policies on disposable repositories; no provider jobs."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app/backend'),str(ROOT/'pilot'),str(ROOT/'tests')]
import runner
import sources
import test_sources
try:
    import changes
except ImportError:
    changes=None


def assignment(identity,role,paths=(),deps=()):
    return dict(id=identity,role=role,objective='Fix the defect',expected_output='Evidence',dependencies=list(deps),write_paths=list(paths))


def report(files=(),verdict='not_reviewed',evidence=None):
    return dict(summary='Checked',findings=[] if evidence is None else [dict(claim='Observed',kind='fact',evidence=[evidence])],questions=[],verdict=verdict,files=list(files))


class ChangeFixture:
    git=test_sources.SourceTests.git
    project=test_sources.SourceTests.project
    commit_files=test_sources.SourceTests.commit_files
    def setUp(self):
        test_sources.SourceTests.setUp(self)
        self.assertIsNotNone(changes,'Controlled editing policy is missing')
        self.commit_files({'main.py':'value = 1\n','tests/test_main.py':'assert True\n','other.py':'other = 1\n'})
        self.p=self.project();self.head=self.git('rev-parse','HEAD')
        scope=sources.validate_selection(self.p,self.head,['main.py','tests/test_main.py']);scope['selection_version']=1
        self.p['source_selection']=dict(scope,mode='selected')
    def team(self):
        return [assignment('edit','implementer',['main.py','tests/test_main.py']),assignment('test','tester',deps=['edit']),assignment('review','reviewer',deps=['test'])]
    def plan(self,tasks=None):
        return changes.make_plan(self.p,self.head,'Fix value',tasks or self.team(),6,'owner')
    def prepared(self):
        run=changes.prepare(self.p,self.plan(),self.base/'runs');return run,changes.load(run)
    def staged(self):
        run,record=self.prepared();changes.stage_candidate(run,record,record['tasks'][0],report([dict(path='main.py',content='value = 2\n'),dict(path='tests/test_main.py',content='assert 2 == 2\n')]))
        return run,record


class ChangeTests(ChangeFixture,unittest.TestCase):
    def test_repeated_roles_must_have_disjoint_scopes_and_full_handoffs(self):
        team=[assignment('a','implementer',['main.py']),assignment('b','implementer',['tests/test_main.py']),assignment('t','tester',deps=['a','b']),assignment('t2','tester',deps=['a','b']),assignment('r','reviewer',deps=['t','t2'])]
        self.assertEqual(len(self.plan(team)['tasks']),5)
        for mutate in (lambda x:x[1]['write_paths'].append('main.py'),lambda x:x[2].update(dependencies=['a']),lambda x:x[4].update(dependencies=['a'])):
            invalid=copy.deepcopy(team);mutate(invalid)
            with self.assertRaises(ValueError):self.plan(invalid)
    def test_write_paths_reject_unsafe_scope_and_existing_unselected_or_untracked(self):
        for path in ('../bad.py','.git/x.py','Tests/test_main.py','private/.env.py','bad.txt','bad\x00.py','other.py','untracked.py'):
            (self.source/'untracked.py').write_text('private')
            team=self.team();team[0]['write_paths']=['main.py','tests/test_main.py',path]
            with self.subTest(path=path),self.assertRaises(ValueError):self.plan(team)
        p=copy.deepcopy(self.p);p['source_selection']['selection_version']=2
        with self.assertRaises(ValueError):changes.prepare(p,self.plan(),self.base/'runs')
    def test_candidate_is_complete_bounded_and_cannot_be_replaced_or_tampered(self):
        run,r=self.prepared();task=r['tasks'][0]
        for files in ([dict(path='main.py',content='x')],[dict(path='main.py',content='é'*50001),dict(path='tests/test_main.py',content='x')],[dict(path='main.py',content='\x00'),dict(path='tests/test_main.py',content='x')]):
            with self.assertRaises(ValueError):changes.stage_candidate(run,r,task,report(files))
        changes.stage_candidate(run,r,task,report([dict(path='main.py',content='value = 2\n'),dict(path='tests/test_main.py',content='assert True\n')]))
        self.assertIn('-value = 1',r['candidate']['diff']);self.assertIn('+value = 2',r['candidate']['diff'])
        before=changes.candidate_digest(run,r)
        with self.assertRaises(ValueError):changes.stage_candidate(run,r,task,report([dict(path='main.py',content='x'),dict(path='tests/test_main.py',content='y')]))
        self.assertEqual(changes.candidate_digest(run,r),before)
        (run/'candidate/main.py').write_text('tampered')
        with self.assertRaises(ValueError):changes.load(run)
    def test_evidence_keeps_original_ids_and_limits_candidate_and_check_visibility(self):
        run,r=self.staged();e=changes.evidence(run,r)
        self.assertEqual(e['original:main.py'],'value = 1\n');self.assertEqual(e['candidate:main.py'],'value = 2\n');self.assertEqual(e['main.py'],'value = 1\n')
        for identity,start,end in [('original:main.py',1,2),('candidate:main.py',1,1),('check:candidate',1,1)]:
            with self.subTest(identity=identity),self.assertRaises(ValueError):changes.validate_result(run,r,r['tasks'][0],report(evidence=dict(source=identity,start=start,end=end)))
        valid=report(evidence=dict(source='candidate:main.py',start=1,end=1))
        self.assertEqual(changes.validate_result(run,r,r['tasks'][1],valid),valid)
    def test_saved_record_and_candidate_scope_tampering_fail_closed(self):
        run,r=self.staged()
        for mutate in (lambda x:x.update(task_id='elsewhere'),lambda x:x['limits'].update(max_calls=100),lambda x:x['candidate']['replacements'].update({'other.py':'x'}),lambda x:x['tasks'][0].update(write_paths=['other.py']),lambda x:x['checks'].update(reservations=[dict(id='baseline')]*4)):
            invalid=copy.deepcopy(r);mutate(invalid)
            with self.assertRaises(ValueError):changes.validate_record(invalid,run)
    def test_current_source_checks_catch_dirty_existing_and_new_targets(self):
        run,r=self.staged();changes.check_current(self.p,run,r)
        (self.source/'main.py').write_text('competing')
        with self.assertRaises(ValueError):changes.check_current(self.p,run,r)
    def test_unicode_normalization_aliases_cannot_expand_write_scope(self):
        team=self.team();team[0]['write_paths']+=['caf\u00e9.py','cafe\u0301.py']
        with self.assertRaises(ValueError):self.plan(team)
        self.commit_files({'caf\u00e9.py':'committed\n'})
        self.head=self.git('rev-parse','HEAD');self.p['source_selection']['revision']=self.head
        team=self.team();team[0]['write_paths'].append('cafe\u0301.py')
        with self.assertRaises(ValueError):self.plan(team)
    def test_saved_record_rejects_result_candidate_mismatch_and_unreserved_checks(self):
        run,r=self.staged()
        invalid=copy.deepcopy(r)
        invalid['results']['edit']=report([dict(path='main.py',content='DIFFERENT'),dict(path='tests/test_main.py',content='assert True\n')])
        with self.assertRaises(ValueError):changes.validate_record(invalid,run)
        invalid=copy.deepcopy(r);invalid['checks']['results']['baseline']={'status':'passed'}
        with self.assertRaises(ValueError):changes.validate_record(invalid,run)
    def test_unexpected_candidate_file_and_original_manifest_tampering_are_rejected(self):
        run,r=self.staged();(run/'candidate/unapproved.py').write_text('unapproved')
        with self.assertRaises(ValueError):changes.validate_record(r,run)
        (run/'candidate/unapproved.py').unlink();r['sources']['main.py']['sha256']='wrong'
        with self.assertRaises(ValueError):changes.validate_record(r,run)
    def test_overlapping_file_directory_paths_and_saved_malformed_results_are_rejected(self):
        team=self.team();team[0]['write_paths']+=['new.py','new.py/child.py']
        with self.assertRaises(ValueError):self.plan(team)
        run,r=self.staged();r['results']['test']={'summary':'incomplete'}
        with self.assertRaises(ValueError):changes.validate_record(r)
    def test_preparation_rechecks_existing_selected_scope_even_for_rehashed_plan(self):
        plan=self.plan();plan['tasks'][0]['write_paths'].append('other.py');plan['tasks'][0]['write_paths'].sort()
        import orchestration
        plan['digest']=orchestration.plan_digest(plan)
        with self.assertRaises(ValueError):changes.prepare(self.p,plan,self.base/'runs')
    def test_malformed_saved_checks_and_negative_manifest_lines_are_rejected(self):
        run,r=self.staged();r['checks']['reservations']=[{'id':'baseline'}]
        r['checks']['results']['baseline']={'status':'invented','tests':True}
        with self.assertRaises(ValueError):changes.validate_record(r)
        r['checks']['results']={};r['sources']['main.py']['lines']=-1
        with self.assertRaises(ValueError):changes.validate_record(r)
    def test_total_bytes_and_write_count_are_bounded(self):
        team=self.team();team[0]['write_paths']+=['new'+str(i)+'.py' for i in range(7)]
        with self.assertRaises(ValueError):self.plan(team)
        team=self.team();team[0]['write_paths'].append('new.py')
        run=changes.prepare(self.p,self.plan(team),self.base/'runs');r=changes.load(run)
        with self.assertRaises(ValueError):changes.stage_candidate(run,r,r['tasks'][0],report([dict(path=p,content='x'*70000) for p in team[0]['write_paths']]))

