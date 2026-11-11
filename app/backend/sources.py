"""Explicit committed-source access and selected snapshots. Never executes project code."""
import copy
import json
from pathlib import Path
import subprocess
import unicodedata
import uuid

import runner

FORMAT='team-v2'
MAX_FILES=16
MAX_FILE_BYTES=250000
MAX_CORPUS=240000
MAX_TREE_ENTRIES=5000
MAX_TREE_BYTES=24_000_000
CHAT_LIMIT=24000


def root(project):
    path=Path(project['source_path'])
    if not path.is_absolute() or path.resolve()!=path or not path.is_dir():
        raise ValueError('The canonical project folder changed; select the project again.')
    actual=Path(runner.git(path,'rev-parse','--show-toplevel').decode().strip()).resolve()
    if actual!=path:raise ValueError('The selected folder is no longer the project root.')
    return path


def revision(project, expected=None):
    head=runner.git(root(project),'rev-parse','HEAD').decode().strip()
    if expected is not None and expected!=head:
        raise ValueError('The committed revision changed. Refresh Sources and save the selection again.')
    return head


def path_reason(name):
    if not isinstance(name,str) or not name or len(name)>4096 or name.startswith('/') or '\\' in name or any(ord(c)<32 or ord(c)==127 for c in name):
        return 'Unsupported source path'
    parts=name.split('/')
    if any(p in ('','.','..') or p.lower()=='.git' for p in parts):return 'Path escapes the allowed source namespace'
    leaf=parts[-1].lower()
    if leaf.startswith('.env') or leaf.endswith(('.key','.pem','.p12','.pfx')) or leaf in ('id_rsa','id_dsa','id_ecdsa','id_ed25519','credentials.json','credentials','secrets.json'):
        return 'Credential or private-key filename excluded'
    return ''


def paths(value):
    if not isinstance(value,list) or not 1<=len(value)<=MAX_FILES or any(path_reason(p) for p in value):
        raise ValueError('Choose 1–16 valid committed source paths; excluded names cannot be selected.')
    normalized=[unicodedata.normalize('NFC',p).casefold() for p in value]
    if len(set(normalized))!=len(value) or any(a.startswith(b+'/') for a in normalized for b in normalized if a!=b):
        raise ValueError('Duplicate or colliding source paths are not allowed.')
    return sorted(value)


def selection(project):
    if 'source_selection' not in project:return {'mode':'legacy','selection_version':0,'version':1,'paths':[]}
    value=project['source_selection']
    required={'mode','version','selection_version','revision','paths'}
    if not isinstance(value,dict) or set(value)!=required or value['version']!=1 or type(value['selection_version']) is not int or value['selection_version']<0:
        raise ValueError('Saved source selection is malformed; preserve app data before recovery.')
    if value['mode']=='unconfirmed':
        if value['selection_version']!=0 or value['paths'] or value['revision'] is not None:raise ValueError('Invalid unconfirmed source selection.')
    elif value['mode']=='selected':
        if value['selection_version']<1 or not isinstance(value['revision'],str) or paths(value['paths'])!=value['paths']:
            raise ValueError('Invalid saved source selection.')
    else:raise ValueError('Unknown source selection mode.')
    return copy.deepcopy(value)


def tree(project, head):
    source=root(project)
    command=['git','-c','core.fsmonitor=false','-c','core.hooksPath=/dev/null','-C',str(source),'ls-tree','-r','-z','-l','--full-tree',head]
    process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    try:
        data=process.stdout.read(MAX_TREE_BYTES+1)
        if len(data)>MAX_TREE_BYTES:raise ValueError('Committed source tree exceeds the supported size.')
        if process.wait(timeout=10)!=0:raise ValueError('Unable to list committed source files.')
    finally:
        if process.poll() is None:process.kill();process.wait()
        process.stdout.close()
    rows=data.split(b'\0');rows=[r for r in rows if r]
    if len(rows)>MAX_TREE_ENTRIES:raise ValueError('Committed tree exceeds 5,000 entries; source selection is unavailable for this tree.')
    result={}
    for row in rows:
        header,raw_name=row.split(b'\t',1)
        try:name=raw_name.decode('utf-8')
        except UnicodeDecodeError as error:raise ValueError('Committed tree contains unsupported non-UTF-8 filenames.') from error
        mode,kind,oid,size=header.decode('ascii').split()
        size=None if size=='-' else int(size)
        reason=path_reason(name)
        if not reason and (kind!='blob' or mode not in ('100644','100755')):reason='Symlink, submodule or nonregular entry excluded'
        if not reason and size>MAX_FILE_BYTES:reason='File exceeds 250,000 bytes'
        result[name]={'path':name,'mode':mode,'blob':oid,'bytes':size,'eligible':not bool(reason),'reason':reason}
    return result


def catalog(project):
    head=revision(project);files=tree(project,head);saved=selection(project)
    suggested=[p for p in ('README.md','docs/PROJECT_CONTEXT.md') if p in files and files[p]['eligible']]
    size=None
    if saved['mode']=='selected' and saved['revision']==head:
        _,bodies=selected_blobs(project,head,saved['paths'],files)
        size=len(numbered(bodies))
    return {'project_id':project['id'],'revision':head,'selection':saved,'suggested':suggested,
            'files':list(files.values()),'context_characters':size,
            'limits':{'files':MAX_FILES,'file_bytes':MAX_FILE_BYTES,'context_characters':MAX_CORPUS,'preview_lines':200}}


def blob(project, info):
    if not info['eligible']:raise ValueError(info['path']+': '+info['reason'])
    body=runner.git(root(project),'cat-file','blob',info['blob'])
    if len(body)>MAX_FILE_BYTES or len(body)!=info['bytes'] or b'\0' in body:raise ValueError(info['path']+': unsupported binary or source size.')
    try:return body.decode('utf-8')
    except UnicodeDecodeError as error:raise ValueError(info['path']+': source must be UTF-8 text.') from error


def lf_lines(body):
    return body.split('\n')[:-1] if body.endswith('\n') else (body.split('\n') if body else [])


def section(name, body):
    lines=lf_lines(body)
    return 'SOURCE '+name+' ('+str(len(lines))+' LF lines)\n'+'\n'.join(str(i+1)+' '+line for i,line in enumerate(lines))


def numbered(bodies):return '\n\n'.join(section(name,body) for name,body in bodies.items())


def selected_blobs(project, head, chosen, entries=None):
    chosen=paths(chosen);entries=tree(project,head) if entries is None else entries
    bodies={}
    for name in chosen:
        if name not in entries:raise ValueError('Selected committed source disappeared: '+name)
        bodies[name]=blob(project,entries[name])
    if not any(bodies.values()):raise ValueError('Selected sources contain no evidence; choose a nonempty text file.')
    if len(numbered(bodies))>MAX_CORPUS:raise ValueError('Numbered selected context exceeds 240,000 characters; choose fewer or shorter files.')
    return entries,bodies


def validate_selection(project, head, chosen):
    revision(project,head);_,bodies=selected_blobs(project,head,chosen)
    revision(project,head)
    return {'version':1,'revision':head,'paths':list(bodies)}


def validate_scope(scope):
    if not isinstance(scope,dict) or set(scope)!={'version','revision','paths','selection_version'} or scope['version']!=1 or type(scope['selection_version']) is not int or scope['selection_version']<1 or not isinstance(scope['revision'],str) or paths(scope['paths'])!=scope['paths']:
        raise ValueError('Invalid selected-source plan scope.')
    return scope


def scope(project):
    saved=selection(project)
    if saved['mode']=='legacy':return None
    if saved['mode']!='selected':raise ValueError('Save this project’s Sources before starting project chat.')
    value={k:v for k,v in saved.items() if k!='mode'}
    validate_scope(value)
    return value


def preview(project, head, name):
    revision(project,head)
    if path_reason(name):raise ValueError('Unsupported preview path.')
    entries=tree(project,head)
    if name not in entries:raise ValueError('Unknown committed preview source.')
    body=blob(project,entries[name]);lines=lf_lines(body)
    return {'project_id':project['id'],'revision':head,'path':name,'start':1 if lines else 0,'end':min(len(lines),200),
            'lines':len(lines),'omitted':len(lines)>200,'text':'\n'.join(str(i+1)+' '+line for i,line in enumerate(lines[:200]))}


def context(project):
    head=revision(project);selected=scope(project)
    if selected is None:
        return head,None,runner.git(root(project),'show',head+':'+project['context_path']).decode()[:CHAT_LIMIT]
    revision(project,selected['revision']);_,bodies=selected_blobs(project,head,selected['paths'])
    full=numbered(bodies)
    if len(full)<=CHAT_LIMIT:return head,selected,full
    # Keep complete LF lines and leave space for an explicit omission marker.
    kept=[];used=0
    for line in full.split('\n'):
        if used+len(line)+1>CHAT_LIMIT-160:break
        kept.append(line);used+=len(line)+1
    return head,selected,'\n'.join(kept)+'\n[Selected source context omitted beyond the 24,000-character chat allowance; specialists receive the approved full snapshot.]'


def prepare(project, plan, storage):
    selected=validate_scope(plan['source_scope'])
    if selected!=scope(project) or plan['revision']!=selected['revision'] or plan['project_id']!=project['id']:
        raise ValueError('The source selection changed; this plan is stale.')
    source=root(project);storage=Path(storage).resolve()
    if storage.is_relative_to(source):raise ValueError('Snapshot storage must be outside the source project.')
    baseline=runner.fingerprint(source)
    revision(project,selected['revision']);entries,bodies=selected_blobs(project,selected['revision'],selected['paths'])
    if runner.fingerprint(source)!=baseline:raise ValueError('Source changed while preparing the snapshot.')
    run=storage/('review-'+uuid.uuid4().hex[:12]);run.mkdir(parents=True)
    manifest={}
    for name,body in bodies.items():
        target=run/'sources'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body.encode())
        manifest[name]={'sha256':runner.digest(body.encode()),'lines':len(lf_lines(body)),'bytes':len(body.encode()),'blob':entries[name]['blob']}
    record={'id':run.name,'format':FORMAT,'project_id':project['id'],'project':project['name'],'source_path':str(source),
            'revision':selected['revision'],'baseline':baseline,'sources':manifest,'source_scope':copy.deepcopy(selected),
            'plan':copy.deepcopy(plan),'goal':plan.get('goal','Selected-source review'),'stage':'queued','results':{},'events':[]}
    runner.save(run/'run.json',record)
    return run


def load(run):
    run=Path(run)
    if any(p.is_symlink() for p in (run.absolute(),*run.absolute().parents)) or (run/'run.json').is_symlink():
        raise ValueError('Symlink run is not allowed.')
    data=json.loads((run/'run.json').read_text())
    if data.get('format')!=FORMAT:return runner.load(run)
    try:
        selected=validate_scope(data['source_scope'])
        if selected!=data['plan']['source_scope'] or data['revision']!=selected['revision'] or data['id']!=run.name:
            raise ValueError('Selected snapshot scope or identity changed.')
        if run.resolve().is_relative_to(Path(data['source_path']).resolve()):raise ValueError('Snapshot must stay outside its source project.')
        if not isinstance(data['sources'],dict) or set(data['sources'])!=set(selected['paths']):raise ValueError('Snapshot manifest differs from approved source paths.')
        snapshot=run/'sources'
        if not snapshot.is_dir() or snapshot.is_symlink():raise ValueError('Invalid snapshot root.')
        bodies={}
        for name,meta in data['sources'].items():
            target=snapshot/name
            if not target.resolve().is_relative_to(snapshot.resolve()) or any(p.is_symlink() for p in (target,*target.parents)):
                raise ValueError('Source escapes snapshot through a symlink.')
            if not target.is_file() or target.stat().st_size>MAX_FILE_BYTES:raise ValueError('Invalid snapshot source size.')
            raw=target.read_bytes()
            if runner.digest(raw)!=meta['sha256'] or len(raw)!=meta['bytes']:raise ValueError('Selected snapshot hash mismatch.')
            body=raw.decode('utf-8')
            if b'\0' in raw or meta['lines']!=len(lf_lines(body)):raise ValueError('Invalid snapshot source lines.')
            bodies[name]=body
        if len(numbered(bodies))>MAX_CORPUS:raise ValueError('Selected snapshot context exceeds its limit.')
    except (KeyError,TypeError,UnicodeDecodeError) as error:raise ValueError('Selected snapshot metadata is malformed.') from error
    return data


def verify(run):
    data=load(run)
    if data.get('format')!=FORMAT:return runner.verify(run)
    result={'unchanged':runner.fingerprint(Path(data['source_path']))==data['baseline'],
            'checked':'Local HEAD/status/tracked-file integrity hashes; unselected content is not model evidence.'}
    data['verification']=result;runner.save(Path(run)/'run.json',data)
    return result
