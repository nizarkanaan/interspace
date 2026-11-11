"""Version-bound report revisions and acceptance. No provider calls or source writes."""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import runner

MAX_REVISIONS = 1


def artifact_id(record):
    content = {key:record.get(key) for key in ('id','revision','sources','goal','results')}
    content['round'] = record.get('revision_round',0)
    if record.get('revision_instructions'):
        content['revision_instructions']=record['revision_instructions']
    return hashlib.sha256(json.dumps(content,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def validate_reference(record, reference):
    if reference.get('run_id') != record['id'] or reference.get('artifact_id') != artifact_id(record):
        raise ValueError('The report changed; this action is stale. Review the current artifact.')


def check_source(run, record):
    source = Path(record['source_path'])
    if runner.git(source,'rev-parse','HEAD').decode().strip() != record['revision']:
        raise ValueError('Source revision changed; start a new review instead of revising stale evidence.')
    if not runner.verify(run)['unchanged']:
        raise ValueError('Source checkout changed since this review; start a new review with its current baseline.')


def can_revise(record):
    return record['stage']=='needs_revision' and record.get('revision_round',0)<MAX_REVISIONS


def check_revision(record):
    if record.get('revision_round',0)>=MAX_REVISIONS:
        raise ValueError('The one-round revision limit is reached. Inspect the results or explicitly start a new review.')
    if record['stage']!='needs_revision' or record['results'].get('reviewer',{}).get('verdict')!='revise':
        raise ValueError('This review is not awaiting a report revision.')


def begin_revision(run, instructions=''):
    if not isinstance(instructions,str) or len(instructions)>6000:
        raise ValueError('Revision instructions must be text of up to 6000 characters.')
    record=runner.load(run)
    check_revision(record)
    check_source(run,record)
    previous={'round':record.get('revision_round',0),'stage':record['stage'],
              'artifact_id':artifact_id(record),'results':copy.deepcopy(record['results'])}
    record.setdefault('previous_attempts',[]).append(previous)
    record['revision_instructions']=instructions
    record['revision_feedback']=copy.deepcopy(record['results']['reviewer'])
    record['revision_round']=record.get('revision_round',0)+1
    record['results']={}
    record['stage']='researcher'
    record.pop('verification',None)
    runner.event(record,'Orchestrator','revision_reserved','One revision round reserved before dispatch; two sequential worker jobs, no automatic retry.')
    runner.save(run/'run.json',record)
    return record


def accept_report(run, reference):
    record=runner.load(run)
    validate_reference(record,reference)
    if record['stage']=='accepted' and record.get('user_acceptance',{}).get('artifact_id')==reference['artifact_id']:
        return False
    if record['stage']!='completed' or record['results'].get('reviewer',{}).get('verdict')!='accept':
        raise ValueError('A report needs reviewer acceptance before you can accept it.')
    check_source(run,record)
    record=runner.load(run)
    validate_reference(record,reference)
    record['stage']='accepted'
    record['user_acceptance']={'artifact_id':reference['artifact_id'],'scope':'report_only',
                               'time':datetime.now(timezone.utc).isoformat()}
    runner.event(record,'User','accepted','Accepted this report version only. No experiment or project change is authorized.')
    runner.save(run/'run.json',record)
    return True
