"""Read-only repository review pilot. No provider secrets or project-write tools."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ('README.md', 'docs/PROJECT_CONTEXT.md', 'docs/BACKEND_AND_SCALING.md',
             'docs/LIVE_INSIGHTS.md', 'docs/NOVELTY_AND_RELATED_WORK.md',
             'app/convex/agent/memory.ts', 'app/convex/simulation/schedule.ts',
             'app/convex/simulation/agentOperations.ts')
REQUIRED = ALLOWLIST[:2]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(source, *args):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0')
    return subprocess.check_output(['git', '-c', 'core.fsmonitor=false', '-c',
                                   'core.hooksPath=/dev/null', '-C', str(source), *args], env=env)


def fingerprint(source):
    """Hash tracked working files, not just their Git status; never change the index."""
    entries = {}
    for raw in git(source, 'ls-files', '-z').split(b'\0'):
        if not raw:
            continue
        name = os.fsdecode(raw)
        path = source / name
        if path.is_symlink():
            entries[name] = digest(os.readlink(path).encode())
        elif path.is_file():
            entries[name] = digest(path.read_bytes())
        else:
            entries[name] = 'missing'
    return {'head': git(source, 'rev-parse', 'HEAD').decode().strip(),
            'status': git(source, 'status', '--porcelain=v1', '-z').decode(),
            'tracked_hash': digest(json.dumps(entries, sort_keys=True).encode())}


def save(path, value):
    if path.is_symlink():
        raise ValueError('symlink output is not allowed')
    temporary = path.with_name(path.name + '.tmp')
    if temporary.is_symlink():
        raise ValueError('symlink temporary output is not allowed')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)


def load(run):
    run = Path(run)
    if any(path.is_symlink() for path in (run.absolute(), *run.absolute().parents)) or (run / 'run.json').is_symlink():
        raise ValueError('symlink run is not allowed')
    data = json.loads((run / 'run.json').read_text())
    if run.resolve().is_relative_to(Path(data['source_path']).resolve()):
        raise ValueError('run must remain outside the source project')
    if data['id'] != run.name:
        raise ValueError('run identity mismatch')
    snapshot = run / 'sources'
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise ValueError('symlink or missing snapshot root')
    for source in data['sources']:
        if source not in ALLOWLIST:
            raise ValueError('unknown source')
        path = run / 'sources' / source
        if not path.resolve().is_relative_to((run / 'sources').resolve()) or path.is_symlink():
            raise ValueError('source escapes snapshot')
        if digest(path.read_bytes()) != data['sources'][source]['sha256']:
            raise ValueError('source hash mismatch')
    return data


def event(data, role, status, detail):
    data['events'].append({'time': datetime.now(timezone.utc).isoformat(),
                           'role': role, 'status': status, 'detail': detail, 'round':data.get('revision_round',0)})


def prepare(source, storage):
    source, storage = Path(source).resolve(), Path(storage).resolve()
    if storage.is_relative_to(source):
        raise ValueError('storage must be outside the source project')
    baseline = fingerprint(source)
    blobs, missing = {}, []
    for name in ALLOWLIST:
        exists = subprocess.run(['git', '-C', str(source), 'cat-file', '-e', baseline['head'] + ':' + name],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        if not exists:
            missing.append(name)
            continue
        data = git(source, 'show', baseline['head'] + ':' + name)
        if len(data) > 250_000 or b'\0' in data:
            raise ValueError('unsupported source size or format: ' + name)
        data.decode('utf-8')
        blobs[name] = data
    if any(name not in blobs for name in REQUIRED):
        raise ValueError('missing required committed context')
    if fingerprint(source) != baseline:
        raise ValueError('source changed during snapshot; retry after reconciling')
    run = storage / ('pilot-' + uuid.uuid4().hex[:12])
    run.mkdir(parents=True)
    manifest = {}
    for name, blob in blobs.items():
        target = run / 'sources' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        # Citations use LF-delimited lines, matching the browser; ignore a trailing empty segment.
        manifest[name] = {'sha256': digest(blob), 'lines': len(blob.decode().split('\n')) - int(blob.endswith(b'\n'))}
    record = {'id': run.name, 'project': 'Sample Project', 'source_path': str(source),
              'revision': baseline['head'], 'baseline': baseline, 'sources': manifest, 'missing': missing,
              'stage': 'researcher', 'provider': 'Current Codex session · artifact bridge',
              'usage': 'Token usage and monetary cost unavailable for this bridge; two specialist sessions maximum.',
              'goal': 'Identify a consequential validation gap in existing technical evidence and prepare a bounded experiment proposal.',
              'plan': ['Researcher: review the committed technical snapshot and cite exact lines.',
                       'Reviewer: check the report against the same snapshot and flag unsupported conclusions.'],
              'results': {}, 'events': []}
    event(record, 'Orchestrator', 'planned', 'Selected two specialists; source is a committed snapshot, not the dirty checkout. No simulation or project writes.')
    save(run / 'run.json', record)
    render(run)
    return run


def validate_result(data, role, result):
    if not isinstance(result, dict) or not isinstance(result.get('summary'), str) or not result['summary'].strip():
        raise ValueError('summary required')
    if not isinstance(result.get('proposal'), str) or not result['proposal'].strip():
        raise ValueError('proposal required')
    if not isinstance(result.get('findings'), list) or not 1 <= len(result['findings']) <= 20:
        raise ValueError('one to twenty findings required')
    for finding in result['findings']:
        if not isinstance(finding, dict) or not isinstance(finding.get('claim'), str) or not finding['claim'].strip():
            raise ValueError('finding claim required')
        if not isinstance(finding.get('evidence'), list) or not finding['evidence']:
            raise ValueError('evidence required')
        for citation in finding['evidence']:
            if not isinstance(citation, dict) or citation.get('source') not in data['sources']:
                raise ValueError('unknown citation source')
            start, end = citation.get('start'), citation.get('end')
            if type(start) is not int or type(end) is not int or not 1 <= start <= end <= data['sources'][citation['source']]['lines']:
                raise ValueError('invalid citation line range')
    if role == 'reviewer' and result.get('verdict') not in ('accept', 'revise', 'blocked'):
        raise ValueError('review verdict required')


def start(run, role):
    data = load(run)
    if data['stage'] != role or role not in ('researcher', 'reviewer'):
        raise ValueError('worker order does not match active stage')
    if any(e['role'] == role and e['status'] == 'started' and e.get('round',0)==data.get('revision_round',0) for e in data['events']):
        raise ValueError('worker already started')
    event(data, role, 'started', 'Dispatched by the controlling Codex session against snapshot files only.')
    save(Path(run) / 'run.json', data)
    render(run)


def complete(run, role, result):
    run = Path(run)
    data = load(run)
    if role not in ('researcher', 'reviewer') or data['stage'] != role:
        raise ValueError('completion order does not match active stage')
    validate_result(data, role, result)
    data['results'][role] = result
    data['stage'] = 'reviewer' if role == 'researcher' else {'accept': 'completed', 'revise': 'needs_revision', 'blocked': 'blocked'}[result['verdict']]
    event(data, role, 'completed', 'Artifact received; source IDs and citation line ranges validated. Semantic support requires the reviewer.')
    save(run / 'run.json', data)
    render(run)


def verify(run):
    data = load(run)
    result = {'unchanged': fingerprint(Path(data['source_path'])) == data['baseline'],
              'checked': 'HEAD, Git status and SHA-256 of every tracked working file; untracked contents are not hashed.'}
    data['verification'] = result
    save(Path(run) / 'run.json', data)
    render(run)
    return result


def render(run):
    run = Path(run)
    data = load(run)
    public = {key: value for key, value in data.items() if key not in ('source_path', 'baseline')}
    public['texts'] = {name: (run / 'sources' / name).read_text() for name in data['sources']}
    payload = json.dumps(public, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    template = (ROOT / 'pilot/view.html').read_text()
    target = run / 'index.html'
    if target.is_symlink():
        raise ValueError('symlink viewer output is not allowed')
    target.write_text(template.replace('/*RUN_DATA*/null', payload))
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--storage', type=Path, default=ROOT / 'workspace-data/pilot')
    for name in ('start', 'complete', 'render', 'verify'):
        p = sub.add_parser(name)
        p.add_argument('--run', type=Path, required=True)
        if name in ('start', 'complete'):
            p.add_argument('--role', choices=('researcher', 'reviewer'), required=True)
        if name == 'complete':
            p.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        print(prepare(args.source, args.storage))
    elif args.command == 'start':
        start(args.run, args.role)
    elif args.command == 'complete':
        complete(args.run, args.role, json.loads(args.result.read_text()))
    elif args.command == 'verify':
        print(json.dumps(verify(args.run)))
    else:
        print(render(args.run))


if __name__ == '__main__':
    main()
