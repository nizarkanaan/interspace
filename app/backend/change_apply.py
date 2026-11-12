"""Descriptor-relative macOS exchanges with retained displaced entries and journal.

No source write fallback exists. Recovery is an inspection, never an automatic replay.
"""
import copy
import ctypes
import errno
import json
import os
from pathlib import Path
import stat
import sys
import uuid

import changes
import runner
import sources

RENAME_SWAP=2
RENAME_EXCL=4
DIRECTORY=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
LIBC=ctypes.CDLL(None,use_errno=True)
RENAME=getattr(LIBC,'renameatx_np',None)
if RENAME is not None:
    RENAME.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    RENAME.restype=ctypes.c_int


def _supported():
    return sys.platform=='darwin' and RENAME is not None


def _same_device(left,right):
    return os.fstat(left).st_dev==os.fstat(right).st_dev


def _rename(source_fd,source,target_fd,target,flags):
    if not _supported():raise OSError(errno.ENOTSUP,'Atomic exchange unavailable')
    if RENAME(source_fd,os.fsencode(source),target_fd,os.fsencode(target),flags)!=0:
        number=ctypes.get_errno();raise OSError(number,os.strerror(number))


def _open_directory(path):
    """Pin each path component without traversing symlinks, including ancestors."""
    path=Path(path)
    if not path.is_absolute():raise ValueError('Directory must be canonical and absolute.')
    fd=os.open('/',DIRECTORY)
    try:
        for component in path.parts[1:]:
            new=os.open(component,DIRECTORY,dir_fd=fd);os.close(fd);fd=new
        return fd
    except BaseException:
        os.close(fd);raise


def _sync(fd):
    os.fsync(fd)


def _write(fd,name,raw,mode=0o600):
    output=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode,dir_fd=fd)
    try:
        with os.fdopen(output,'wb',closefd=False) as stream:
            stream.write(raw);stream.flush();os.fchmod(output,mode);_sync(output)
        meta=os.fstat(output)
    finally:os.close(output)
    _sync(fd)
    return meta


def _durable(path,value):
    directory=_open_directory(Path(path).parent)
    temporary='journal-'+uuid.uuid4().hex+'.tmp'
    try:
        _write(directory,temporary,(json.dumps(value,sort_keys=True,indent=2)+'\n').encode())
        # The journal is app-owned; source files are replaced only with _rename.
        os.replace(temporary,Path(path).name,src_dir_fd=directory,dst_dir_fd=directory);_sync(directory)
    finally:os.close(directory)


def _info(fd,name):
    try:meta=os.stat(name,dir_fd=fd,follow_symlinks=False)
    except FileNotFoundError:return None
    info=dict(device=meta.st_dev,inode=meta.st_ino,mode=stat.S_IMODE(meta.st_mode),links=meta.st_nlink,type=stat.S_IFMT(meta.st_mode))
    if stat.S_ISREG(meta.st_mode):
        handle=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
        try:
            actual=os.fstat(handle)
            if (actual.st_dev,actual.st_ino)!=(meta.st_dev,meta.st_ino):raise ValueError('Source changed while opening it.')
            chunks=[];size=0
            while True:
                raw=os.read(handle,65536)
                if not raw:break
                size+=len(raw)
                if size>sources.MAX_FILE_BYTES:raise ValueError('Displaced source exceeds its approved limit.')
                chunks.append(raw)
            info['sha256']=runner.digest(b''.join(chunks))
        finally:os.close(handle)
    elif stat.S_ISLNK(meta.st_mode):info['link']=os.readlink(name,dir_fd=fd)
    return info


def _same_entry(info,expected):
    return info is not None and all(info.get(k)==expected.get(k) for k in ('device','inode','mode','links','type','sha256'))


def _parent(root_fd,name,journal,journal_path,create=False):
    fd=os.dup(root_fd);relative=[]
    try:
        for component in name.split('/')[:-1]:
            relative.append(component)
            try:new=os.open(component,DIRECTORY,dir_fd=fd)
            except FileNotFoundError:
                if not create:raise
                # Persist intent before a source directory creation as well.
                journal['directories'].append({'path':'/'.join(relative),'created':False})
                _durable(journal_path,journal)
                os.mkdir(component,0o755,dir_fd=fd);_sync(fd)
                new=os.open(component,DIRECTORY,dir_fd=fd)
                journal['directories'][-1].update(created=True,device=os.fstat(new).st_dev,inode=os.fstat(new).st_ino)
                _durable(journal_path,journal)
            os.close(fd);fd=new
        return fd
    except BaseException:
        os.close(fd);raise


def _binding(root,root_fd,name,parent_fd):
    fresh=_open_directory(root)
    try:
        if (os.fstat(fresh).st_dev,os.fstat(fresh).st_ino)!=(os.fstat(root_fd).st_dev,os.fstat(root_fd).st_ino):raise ValueError('Source root changed.')
        for component in name.split('/')[:-1]:
            child=os.open(component,DIRECTORY,dir_fd=fresh);os.close(fresh);fresh=child
        if (os.fstat(fresh).st_dev,os.fstat(fresh).st_ino)!=(os.fstat(parent_fd).st_dev,os.fstat(parent_fd).st_ino):raise ValueError('Source parent changed.')
    finally:os.close(fresh)


def _ready(record):
    if record['stage']!='ready_to_apply' or record['application'] is not None:raise ValueError('Application is unavailable or already consumed.')
    expected=dict(artifact_id=changes.artifact_id(record),candidate_digest=record['candidate']['digest'],plan_digest=record['plan']['digest'])
    if record.get('application_approval')!=expected:raise ValueError('The exact final application approval is stale or missing.')
    if not record['candidate']['frozen'] or not isinstance(record['test_approval'],dict) or record['test_approval'].get('candidate_digest')!=record['candidate']['digest']:raise ValueError('Exact candidate test approval is missing.')
    if set(record['candidate']['replacements'])!=set(changes.write_paths(record['plan'])):raise ValueError('Candidate is incomplete.')
    if set(record['results'])!={t['id'] for t in record['tasks']} or any(t['status']!='done' for t in record['tasks']) or record['combined'] is None:raise ValueError('Specialist work and synthesis must be complete.')
    if any(record['results'][t['id']]['verdict']!='accept' for t in record['tasks'] if t['role']=='reviewer'):raise ValueError('Every Reviewer must accept.')
    if not any(j['id']=='synthesis' and j['status']=='completed' for j in record['jobs']):raise ValueError('Synthesis did not finish.')
    if {r['id'] for r in record['checks']['reservations']}!=set(changes.CHECKS) or set(record['checks']['results'])!=set(changes.CHECKS):raise ValueError('All three checks are required.')
    for name,value in record['checks']['results'].items():
        if value.get('runtime')!=record['test_approval']['runtime']:raise ValueError('Check runtime differs from approved runtime.')
        if type(value.get('tests')) is not int or value['tests']<1 or value.get('errors')!=0 or type(value.get('exit_code')) is not int:raise ValueError('Checks do not qualify for application.')
        if name=='regression':
            if value.get('status')!='failed' or value['exit_code']==0 or type(value.get('failures')) is not int or value['failures']<1:raise ValueError('Regression must fail by assertion.')
        elif value.get('status')!='passed' or value['exit_code']!=0 or value.get('failures')!=0:raise ValueError('Original and candidate suites must pass.')


def _finish(run,record,journal,status,detail):
    journal.update(status=status,detail=detail)
    _durable(Path(run)/'application/journal.json',journal)
    outcome=dict(status=status,detail=detail,files=copy.deepcopy(journal['files']),directories=copy.deepcopy(journal['directories']))
    record['application']=outcome;record['stage']={'rolled_back':'application_failed','unavailable':'application_failed'}.get(status,status)
    runner.event(record,'Application',status,detail);runner.save(Path(run)/'run.json',record)
    return outcome


def _rollback(root,root_fd,stage_fd,journal,journal_path):
    safe=True
    for item in reversed(journal['files']):
        if item['status'] not in ('replaced','conflict'):continue
        parent=None
        try:
            parent=_parent(root_fd,item['path'],journal,journal_path)
            _binding(root,root_fd,item['path'],parent)
            current=_info(parent,item['path'].split('/')[-1])
            if not _same_entry(current,item['installed']):
                item['status']='rollback_conflict';safe=False;_durable(journal_path,journal);continue
            retained='rollback-'+item['slot']
            # Retain any displaced competing bytes even when restoring the entry itself.
            if item['original'] is not None:
                displaced=_info(stage_fd,item['slot'])
                if displaced and displaced.get('type')==stat.S_IFREG:
                    fd=os.open(item['slot'],os.O_RDONLY|os.O_NOFOLLOW,dir_fd=stage_fd)
                    try:
                        with os.fdopen(fd,'rb',closefd=False) as body:_write(stage_fd,'retained-'+item['slot'],body.read(),displaced['mode'])
                    finally:os.close(fd)
                item['status']='rolling_back';_durable(journal_path,journal)
                _rename(stage_fd,item['slot'],parent,item['path'].split('/')[-1],RENAME_SWAP)
                _sync(parent);_sync(stage_fd)
                displaced_now=_info(stage_fd,item['slot'])
                if not _same_entry(displaced_now,item['installed']):
                    # An edit won the narrow rollback race. Keep those bytes in staging;
                    # source restoration is recorded as a conflict, never a clean rollback.
                    item['status']='rollback_conflict';safe=False
                else:item['status']='rolled_back'
            else:
                item['status']='rolling_back';_durable(journal_path,journal)
                _rename(parent,item['path'].split('/')[-1],stage_fd,retained,RENAME_EXCL)
                _sync(parent);_sync(stage_fd)
                moved=_info(stage_fd,retained)
                if not _same_entry(moved,item['installed']):
                    # Restore only into an absent destination; never overwrite a new editor entry.
                    try:_rename(stage_fd,retained,parent,item['path'].split('/')[-1],RENAME_EXCL)
                    except OSError:pass
                    item['status']='rollback_conflict';safe=False
                else:item['status']='rolled_back'
            _durable(journal_path,journal)
        except (OSError,ValueError) as error:
            item['status']='rollback_conflict';item['error']=type(error).__name__;safe=False;_durable(journal_path,journal)
        finally:
            if parent is not None:os.close(parent)
    for directory in reversed(journal['directories']):
        if not directory.get('created'):continue
        parent=None
        try:
            parent=_parent(root_fd,directory['path'],journal,journal_path)
            _binding(root,root_fd,directory['path'],parent)
            meta=os.stat(directory['path'].split('/')[-1],dir_fd=parent,follow_symlinks=False)
            if (meta.st_dev,meta.st_ino)==(directory['device'],directory['inode']):os.rmdir(directory['path'].split('/')[-1],dir_fd=parent);_sync(parent)
        except OSError:pass # A populated or renamed directory belongs to the user now.
        except ValueError:safe=False
        finally:
            if parent is not None:os.close(parent)
    return safe


def apply(run,record,cancel,hook=None):
    run=Path(run);changes.validate_record(record,run);_ready(record)
    project=dict(id=record['project_id'],name=record['project'],source_path=record['source_path'],source_selection=dict(record['source_scope'],mode='selected'))
    changes.check_current(project,run,record)
    if cancel.is_set():raise ValueError('Application cancelled before reservation.')
    application=run/'application'
    # O_EXCL directory reservation consumes this approval even after a crash.
    run_fd=_open_directory(run)
    try:
        try:os.mkdir('application',0o700,dir_fd=run_fd)
        except FileExistsError:raise ValueError('Application was already reserved; inspect its journal.')
        # Persist the new entry in its parent before source writes can be durable.
        _sync(run_fd)
    finally:os.close(run_fd)
    journal_path=application/'journal.json'
    journal=dict(version=1,run_id=record['id'],approval=copy.deepcopy(record['application_approval']),status='preparing',files=[],directories=[])
    _durable(journal_path,journal)
    root=Path(record['source_path']);root_fd=_open_directory(root);stage_fd=_open_directory(application)
    try:
        if not _supported() or not _same_device(root_fd,stage_fd):return _finish(run,record,journal,'unavailable','Same-filesystem atomic exchange and exclusive creation are required.')
        # Verify both filesystem primitives in app-owned storage before a source write.
        try:
            _write(stage_fd,'probe-a',b'a');_write(stage_fd,'probe-b',b'b')
            _rename(stage_fd,'probe-a',stage_fd,'probe-b',RENAME_SWAP)
            _rename(stage_fd,'probe-a',stage_fd,'probe-c',RENAME_EXCL)
        except OSError:return _finish(run,record,journal,'unavailable','Filesystem does not support required atomic primitives.')
        # Backups and complete replacement entries are durable before the first source write.
        for index,name in enumerate(changes.write_paths(record['plan'])):
            parent=None
            try:
                try:parent=_parent(root_fd,name,journal,journal_path);original=_info(parent,name.split('/')[-1])
                except FileNotFoundError:original=None
                expected=record['sources'].get(name,{}).get('sha256')
                if expected is None and original is not None:raise ValueError('New source target appeared.')
                if expected is not None and (original is None or original.get('sha256')!=expected or original['links']!=1 or original['type']!=stat.S_IFREG):raise ValueError('Source target changed during preparation.')
                if parent is not None and not _same_device(parent,stage_fd):raise ValueError('Source target is on an unsupported device.')
                slot='entry-'+str(index);mode=original['mode'] if original else 0o644
                _write(stage_fd,slot,record['candidate']['replacements'][name].encode('utf-8'),mode)
                if expected is not None:_write(stage_fd,'backup-'+str(index),(run/'sources'/name).read_bytes(),mode)
                journal['files'].append(dict(path=name,slot=slot,original=original,installed=_info(stage_fd,slot),status='prepared'))
                _durable(journal_path,journal)
            finally:
                if parent is not None:os.close(parent)
        journal['status']='applying';_durable(journal_path,journal)
        record['stage']='applying';record['application']={'status':'applying'};runner.save(run/'run.json',record)
        try:
            for item in journal['files']:
                if cancel.is_set():raise ValueError('Application cancelled.')
                parent=_parent(root_fd,item['path'],journal,journal_path,create=True)
                try:
                    if not _same_device(parent,stage_fd):raise ValueError('Source target is on an unsupported device.')
                    if hook:hook('pre-replacement',item['path'])
                    _binding(root,root_fd,item['path'],parent)
                    item['status']='replacing';_durable(journal_path,journal)
                    try:_rename(stage_fd,item['slot'],parent,item['path'].split('/')[-1],RENAME_SWAP if item['original'] is not None else RENAME_EXCL)
                    except OSError:
                        item['status']='prepared';_durable(journal_path,journal);raise
                    item['status']='replaced'
                    _sync(parent);_sync(stage_fd);_durable(journal_path,journal)
                    if item['original'] is not None and not _same_entry(_info(stage_fd,item['slot']),item['original']):
                        item['status']='conflict';_durable(journal_path,journal);raise ValueError('Competing source entry was displaced; its bytes are retained.')
                    if hook:hook('after-replacement',item['path'])
                    if not _same_entry(_info(parent,item['path'].split('/')[-1]),item['installed']):raise ValueError('Source changed after replacement.')
                finally:os.close(parent)
            if cancel.is_set():raise ValueError('Application cancelled.')
            for item in journal['files']:
                parent=_parent(root_fd,item['path'],journal,journal_path)
                try:
                    _binding(root,root_fd,item['path'],parent)
                    if not _same_entry(_info(parent,item['path'].split('/')[-1]),item['installed']):raise ValueError('Source changed before completion.')
                finally:os.close(parent)
            return _finish(run,record,journal,'applied','Exact reviewed replacements applied; files remain uncommitted.')
        except (OSError,ValueError) as error:
            safe=_rollback(root,root_fd,stage_fd,journal,journal_path)
            return _finish(run,record,journal,'rolled_back' if safe else 'recovery_required',str(error))
    except (OSError,ValueError) as error:
        # Preflight failures occur before replacements, and never infer a retry.
        status='recovery_required' if any(i['status'] not in ('prepared','rolled_back') for i in journal['files']) else 'application_failed'
        return _finish(run,record,journal,status,str(error))
    finally:os.close(root_fd);os.close(stage_fd)


def recover(run,record):
    """Read an unfinished journal and current entries. No source or journal writes."""
    run=Path(run);changes.validate_record(record,run)
    path=run/'application/journal.json'
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('Symlink application journal.')
    journal=json.loads(path.read_text())
    if journal.get('version')!=1 or journal.get('run_id')!=record['id'] or not isinstance(journal.get('files'),list):raise ValueError('Invalid application journal.')
    terminal={'applied','rolled_back','unavailable','application_failed','recovery_required'}
    result=dict(status=journal['status'] if journal['status'] in terminal else 'recovery_required',journal_status=journal['status'],files=[],detail='Inspection only; no project entries were changed.')
    root_fd=_open_directory(record['source_path'])
    try:
        for item in journal['files']:
            if item.get('path') not in changes.write_paths(record['plan']):raise ValueError('Journal path outside approved scope.')
            row=copy.deepcopy(item);parent=None
            try:
                parent=_parent(root_fd,item['path'],journal,path);row['current']=_info(parent,item['path'].split('/')[-1])
            except (OSError,ValueError):row['current']={'unavailable':True}
            finally:
                if parent is not None:os.close(parent)
            result['files'].append(row)
    finally:os.close(root_fd)
    return result
