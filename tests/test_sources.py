"""Committed source boundaries on disposable Git repositories, never personal data."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app/backend'),str(ROOT/'pilot'),str(ROOT/'tests')]
import test_pilot
import runner
import sources


class SourceTests(unittest.TestCase):
    setUp=test_pilot.PilotTests.setUp
    git=test_pilot.PilotTests.git
    def project(self):
        return {'id':'a','name':'Fixture','source_path':str(self.source),'context_path':'docs/PROJECT_CONTEXT.md'}
    def commit_files(self,files):
        for name,body in files.items():
            path=self.source/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(body if isinstance(body,bytes) else body.encode())
        self.git('add','.');self.git('commit','-qm','Source fixtures')
    def test_catalog_and_preview_use_commit_not_dirty_working_files(self):
        self.commit_files({'notes/design.txt':'COMMITTED DESIGN\nSecond\n'})
        (self.source/'notes/design.txt').write_text('PRIVATE DIRTY EDIT')
        project=self.project();catalog=sources.catalog(project)
        self.assertIn('notes/design.txt',[f['path'] for f in catalog['files']])
        preview=sources.preview(project,catalog['revision'],'notes/design.txt')
        self.assertEqual(preview['text'],'1 COMMITTED DESIGN\n2 Second')
        self.assertFalse(preview['omitted'])
        self.assertNotIn('PRIVATE',json.dumps(catalog))
    def test_preview_is_lf_numbered_and_explicitly_limited(self):
        self.commit_files({'long.txt':'One\u2028same line\n'+('Line\n'*205)})
        c=sources.catalog(self.project());p=sources.preview(self.project(),c['revision'],'long.txt')
        self.assertEqual(p['lines'],206);self.assertTrue(p['omitted']);self.assertEqual(p['end'],200)
        self.assertTrue(p['text'].startswith('1 One\u2028same line\n2 Line'))
    def test_excluded_names_links_submodules_binary_and_utf8_are_rejected(self):
        self.commit_files({'.env':'secret','private.key':'key','blob.bin':b'A\0B','invalid.txt':b'\xff'})
        (self.source/'link.txt').symlink_to('README.md');self.git('add','link.txt');self.git('commit','-qm','Link')
        self.git('update-index','--add','--cacheinfo','160000,'+self.git('rev-parse','HEAD')+',module')
        self.git('commit','-qm','Submodule entry')
        c=sources.catalog(self.project());by={f['path']:f for f in c['files']}
        for name in ('.env','private.key','link.txt','module'):
            self.assertFalse(by[name]['eligible']);self.assertTrue(by[name]['reason'])
        for name in ('.env','private.key','link.txt','module','blob.bin','invalid.txt','../README.md','/etc/passwd','.git/config'):
            with self.subTest(path=name),self.assertRaises(ValueError):sources.validate_selection(self.project(),c['revision'],[name])
    def test_selection_limits_and_empty_evidence_fail_before_scope_exists(self):
        self.commit_files({**{'f'+str(i)+'.txt':'Line\n' for i in range(17)},'large.txt':'x'*250001,'empty.txt':'','numbered.txt':'x\n'*40000})
        head=self.git('rev-parse','HEAD')
        for paths in ([],['f'+str(i)+'.txt' for i in range(17)],['large.txt'],['empty.txt'],['numbered.txt'],['README.md','README.md']):
            with self.subTest(paths=paths),self.assertRaises(ValueError):sources.validate_selection(self.project(),head,paths)
        with patch.object(sources,'MAX_TREE_ENTRIES',2),self.assertRaisesRegex(ValueError,'tree|entries'):sources.catalog(self.project())
    def test_selected_context_excludes_unselected_files_and_labels_omissions(self):
        self.commit_files({'selected.txt':'CHOSEN\n'+('Long line\n'*4000),'unselected.txt':'UNSELECTED_SECRET'})
        p=self.project();head=self.git('rev-parse','HEAD');scope=sources.validate_selection(p,head,['selected.txt'])
        p['source_selection']=dict(scope,mode='selected',selection_version=1)
        revision,captured,context=sources.context(p)
        self.assertEqual(revision,head);self.assertEqual(captured['paths'],['selected.txt'])
        self.assertIn('CHOSEN',context);self.assertNotIn('UNSELECTED_SECRET',context)
        self.assertIn('omitted',context.lower());self.assertLessEqual(len(context),24000)
    def test_malformed_unconfirmed_and_stale_selection_never_fall_back(self):
        p=self.project();self.assertEqual(sources.selection(p)['mode'],'legacy')
        for value in (None,{}, {'mode':'selected','paths':['README.md']},{'mode':'unconfirmed','selection_version':0}):
            p['source_selection']=value
            with self.subTest(value=value),self.assertRaises(ValueError):sources.context(p)
        p['source_selection']={'mode':'selected','version':1,'selection_version':1,'revision':self.git('rev-parse','HEAD'),'paths':['README.md']}
        self.commit_files({'new.txt':'Change'})
        with self.assertRaisesRegex(ValueError,'revision|changed'):sources.context(p)
    def test_selected_snapshot_loads_outside_old_allowlist_and_detects_tampering(self):
        self.commit_files({'notes/new.txt':'Allowed committed note\n'})
        p=self.project();head=self.git('rev-parse','HEAD')
        scope=sources.validate_selection(p,head,['notes/new.txt']);scope['selection_version']=1
        p['source_selection']=dict(scope,mode='selected')
        plan={'source_scope':scope,'revision':head,'project_id':p['id']}
        before=runner.fingerprint(self.source)
        run=sources.prepare(p,plan,self.base/'runs')
        record=sources.load(run)
        self.assertEqual(set(record['sources']),{'notes/new.txt'})
        self.assertEqual((run/'sources/notes/new.txt').read_text(),'Allowed committed note\n')
        self.assertTrue(sources.verify(run)['unchanged']);self.assertEqual(before,runner.fingerprint(self.source))
        (run/'sources/notes/new.txt').write_text('Tampered')
        with self.assertRaisesRegex(ValueError,'hash'):sources.load(run)
    def test_snapshot_scope_and_symlink_ancestors_are_validated(self):
        self.commit_files({'notes/new.txt':'Note\n'})
        p=self.project();head=self.git('rev-parse','HEAD');scope=sources.validate_selection(p,head,['notes/new.txt']);scope['selection_version']=1
        p['source_selection']=dict(scope,mode='selected')
        run=sources.prepare(p,{'source_scope':scope,'revision':head,'project_id':p['id']},self.base/'runs')
        record=sources.load(run);record['plan']['source_scope']['paths']=['README.md'];runner.save(run/'run.json',record)
        with self.assertRaises(ValueError):sources.load(run)
        record['plan']['source_scope']=copy.deepcopy(scope);runner.save(run/'run.json',record)
        (run/'sources/notes').rename(run/'outside');(run/'sources/notes').symlink_to(run/'outside',target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'symlink|escapes'):sources.load(run)
    def test_legacy_snapshot_loader_is_preserved(self):
        run=runner.prepare(self.source,self.base/'runs')
        self.assertEqual(sources.load(run),runner.load(run))
        self.assertTrue(sources.verify(run)['unchanged'])
