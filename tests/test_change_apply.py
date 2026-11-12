"""Real temporary filesystem exchanges, conflicts, rollback and inspection."""
import copy
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app/backend'),str(ROOT/'pilot'),str(ROOT/'tests')]
import changes
import runner
import test_changes
try:
    import change_apply
except ImportError:
    change_apply=None


class ApplyTests(test_changes.ChangeFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.assertIsNotNone(change_apply,'Guarded atomic source application is missing')
    def ready(self,new=False):
        tasks=self.team()
        if new:tasks[0]['write_paths'].append('package/new.py')
        run=changes.prepare(self.p,self.plan(tasks),self.base/'runs');r=changes.load(run)
        files=[dict(path=p,content='value = 2\n' if p=='main.py' else 'assert True\n') for p in tasks[0]['write_paths']]
        artifact=changes.stage_candidate(run,r,r['tasks'][0],test_changes.report(files))
        r['results']={'edit':artifact,'test':test_changes.report(),'review':test_changes.report(verdict='accept')}
        for t in r['tasks']:t['status']='done'
        r['jobs']=[dict(id=t['id'],role=t['role'],status='completed',tokens=None) for t in r['tasks']]+[dict(id='synthesis',role='Orchestrator',status='completed',tokens=None)]
        r['candidate']['frozen']=True;r['test_approval']={'candidate_digest':r['candidate']['digest'],'plan_digest':r['plan']['digest'],'recipe':r['plan']['recipe'],'runtime':{'executable':'/fixture/python','sha256':'fixture-runtime','framework_root':'/fixture/framework','version':'3.9','recipe':changes.RECIPE}}
        r['checks']['reservations']=[{'id':k,'status':'completed'} for k in changes.CHECKS]
        r['checks']['results']={k:dict(status='failed' if k=='regression' else 'passed',exit_code=1 if k=='regression' else 0,tests=2,failures=1 if k=='regression' else 0,errors=0,stdout='real fixture output',stderr='',duration=0.1,runtime={'executable':'/fixture/python','sha256':'fixture-runtime','framework_root':'/fixture/framework','version':'3.9','recipe':changes.RECIPE}) for k in changes.CHECKS}
        r['combined']=test_changes.report();r['stage']='ready_to_apply'
        r['application_approval']=dict(artifact_id=changes.artifact_id(r),candidate_digest=r['candidate']['digest'],plan_digest=r['plan']['digest'])
        runner.save(run/'run.json',r);return run,r
    def test_exact_atomic_swap_and_exclusive_creation_are_retained_and_not_replayed(self):
        run,r=self.ready(new=True);before=(self.source/'main.py').stat().st_ino
        result=change_apply.apply(run,r,threading.Event())
        self.assertEqual(result['status'],'applied');self.assertEqual((self.source/'main.py').read_text(),'value = 2\n');self.assertTrue((self.source/'package/new.py').exists())
        old=[p for p in (run/'application').rglob('*') if p.is_file() and p.stat().st_ino==before]
        self.assertEqual(len(old),1);self.assertEqual(old[0].read_text(),'value = 1\n')
        with self.assertRaises(ValueError):change_apply.apply(run,changes.load(run),threading.Event())
    def test_stale_approval_and_changed_candidate_fail_before_writes(self):
        run,r=self.ready();r['application_approval']['artifact_id']='wrong'
        with self.assertRaises(ValueError):change_apply.apply(run,r,threading.Event())
        self.assertEqual((self.source/'main.py').read_text(),'value = 1\n')
    def test_symlink_hardlink_dirty_and_new_file_conflicts_are_rejected(self):
        for kind in ('symlink','hardlink','dirty','new'):
            with self.subTest(kind=kind):
                run,r=self.ready(new=True);path=self.source/'main.py'
                if kind=='symlink':path.unlink();path.symlink_to(self.source/'other.py')
                elif kind=='hardlink':os.link(path,self.source/'linked.py')
                elif kind=='dirty':path.write_text('competing\n')
                else:(self.source/'package').mkdir();(self.source/'package/new.py').write_text('untracked\n')
                with self.assertRaises(ValueError):change_apply.apply(run,r,threading.Event())
                if path.is_symlink():path.unlink();path.write_text('value = 1\n')
                if kind=='hardlink':(self.source/'linked.py').unlink()
                if kind=='dirty':path.write_text('value = 1\n')
                if kind=='new':(self.source/'package/new.py').unlink();(self.source/'package').rmdir()
    def test_unsupported_device_or_primitive_never_falls_back(self):
        run,r=self.ready()
        with patch.object(change_apply,'_supported',return_value=False):result=change_apply.apply(run,r,threading.Event())
        self.assertEqual(result['status'],'unavailable');self.assertEqual((self.source/'main.py').read_text(),'value = 1\n')
        run,r=self.ready()
        with patch.object(change_apply,'_same_device',return_value=False):result=change_apply.apply(run,r,threading.Event())
        self.assertEqual(result['status'],'unavailable');self.assertEqual((self.source/'main.py').read_text(),'value = 1\n')
    def test_failure_after_first_replacement_rolls_back_owned_files(self):
        run,r=self.ready(new=True)
        def fail(event,path):
            if event=='after-replacement' and path=='main.py':raise OSError('injected failure')
        result=change_apply.apply(run,r,threading.Event(),fail)
        self.assertEqual(result['status'],'rolled_back');self.assertEqual((self.source/'main.py').read_text(),'value = 1\n');self.assertFalse((self.source/'package/new.py').exists())
    def test_competing_edit_at_exchange_is_retained_and_never_applied(self):
        run,r=self.ready()
        def compete(event,path):
            if event=='pre-replacement' and path=='main.py':(self.source/'main.py').write_text('COMPETING\n')
        result=change_apply.apply(run,r,threading.Event(),compete)
        self.assertNotEqual(result['status'],'applied');self.assertEqual((self.source/'main.py').read_text(),'COMPETING\n')
        self.assertTrue(any(p.is_file() and p.read_bytes()==b'COMPETING\n' for p in (run/'application').rglob('*')))
    def test_competing_edit_after_exchange_blocks_rollback_and_preserves_bytes(self):
        run,r=self.ready()
        def compete(event,path):
            if event=='after-replacement' and path=='main.py':
                (self.source/'main.py').write_text('AFTER\n');raise OSError('stop')
        result=change_apply.apply(run,r,threading.Event(),compete)
        self.assertEqual(result['status'],'recovery_required');self.assertEqual((self.source/'main.py').read_text(),'AFTER\n')
        self.assertTrue(any(p.is_file() and p.read_bytes()==b'value = 1\n' for p in (run/'application').rglob('*')))
    def test_unfinished_journal_recovery_only_inspects_and_never_rewrites(self):
        run,r=self.ready()
        class Crash(BaseException):pass
        def crash(event,path):
            if event=='after-replacement':raise Crash()
        with self.assertRaises(Crash):change_apply.apply(run,r,threading.Event(),crash)
        (self.source/'main.py').write_text('POST CRASH\n');before=runner.fingerprint(self.source)
        result=change_apply.recover(run,changes.load(run))
        self.assertEqual(result['status'],'recovery_required');self.assertEqual(runner.fingerprint(self.source),before);self.assertEqual((self.source/'main.py').read_text(),'POST CRASH\n')
    def test_check_runtime_or_recipe_binding_cannot_be_swapped_before_application(self):
        for mutate in (lambda r:r['test_approval'].update(recipe={}),lambda r:r['checks']['results']['candidate'].update(runtime={'sha256':'other'})):
            run,r=self.ready();mutate(r)
            r['application_approval']['artifact_id']=changes.artifact_id(r)
            with self.assertRaises(ValueError):change_apply.apply(run,r,threading.Event())
            self.assertEqual((self.source/'main.py').read_text(),'value = 1\n')
    def test_new_target_competition_uses_exclusive_creation_and_keeps_competing_file(self):
        run,r=self.ready(new=True)
        def compete(event,path):
            if event=='pre-replacement' and path=='package/new.py':(self.source/'package/new.py').write_text('COMPETING NEW\n')
        result=change_apply.apply(run,r,threading.Event(),compete)
        self.assertNotEqual(result['status'],'applied');self.assertEqual((self.source/'package/new.py').read_text(),'COMPETING NEW\n')
        self.assertEqual((self.source/'main.py').read_text(),'value = 1\n')
    def test_cancellation_after_first_exchange_rolls_back_and_preserves_file_mode(self):
        (self.source/'main.py').chmod(0o755);self.git('add','main.py');self.git('commit','-qm','Executable fixture')
        self.head=self.git('rev-parse','HEAD');self.p['source_selection']['revision']=self.head
        run,r=self.ready();cancel=threading.Event()
        def stop(event,path):
            if event=='after-replacement':cancel.set()
        result=change_apply.apply(run,r,cancel,stop)
        self.assertEqual(result['status'],'rolled_back');self.assertEqual((self.source/'main.py').read_text(),'value = 1\n');self.assertEqual((self.source/'main.py').stat().st_mode & 0o777,0o755)
    def test_parent_symlink_race_is_rejected_without_following_alias(self):
        run,r=self.ready()
        outside=self.base/'outside';outside.mkdir();(outside/'test_main.py').write_text('OUTSIDE\n')
        def alias(event,path):
            if event=='pre-replacement' and path=='tests/test_main.py':
                (self.source/'tests').rename(self.source/'old-tests');(self.source/'tests').symlink_to(outside,target_is_directory=True)
        result=change_apply.apply(run,r,threading.Event(),alias)
        self.assertNotEqual(result['status'],'applied');self.assertEqual((outside/'test_main.py').read_text(),'OUTSIDE\n')

