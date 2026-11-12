"""Actual public editing projections; only disposable repositories and fake jobs/checks."""
import copy
import json
from test_change_workflow import WorkflowTests
from service import Application


def fixtures():
    case = WorkflowTests('test_complete_three_approval_lifecycle_releases_pause_and_hands_off_real_checks')
    case.setUp()
    try:
        case.setup_app()
        app = case.app
        app.handle('update_task', dict(project_id=case.pid, task_id=case.tid, title='Fix the recorded value'))
        result = {'editing': copy.deepcopy(app.public())}
        plan = case.propose()
        result['plan'] = copy.deepcopy(app.public())
        case.provider.before = lambda prompt: result.setdefault('running', copy.deepcopy(app.public())) if 'Role: Implementer' in prompt else None
        paused = case.start(plan)
        result['paused'] = copy.deepcopy(app.public())
        (case.source/'main.py').write_text('competing user edit\n')
        result['stale'] = copy.deepcopy(app.public())
        (case.source/'main.py').write_text('value = 1\n')
        original_check = case.process_mock.side_effect
        def check(*args, **kwargs):
            result.setdefault('checking', copy.deepcopy(app.public()))
            return original_check(*args, **kwargs)
        case.process_mock.side_effect = check
        ready = case.approve(paused)
        result['ready'] = copy.deepcopy(app.public())
        result['evidence'] = {}
        for source in ['original:main.py', 'candidate:main.py', 'check:baseline', 'check:regression', 'check:candidate']:
            result['evidence'][source] = app.handle('change_evidence', dict(case.ref(ready), source=source))
        (case.source/'main.py').write_text('competing user edit\n')
        result['stale_ready'] = copy.deepcopy(app.public())
        result['stale_ready_evidence'] = {source:app.handle('change_evidence',dict(case.ref(ready),source=source)) for source in result['evidence']}
        (case.source/'main.py').write_text('value = 1\n')
        app.handle('apply_changes', case.ref(ready));app.wait()
        result['applied'] = copy.deepcopy(app.public())
        reopened = Application(app.storage, provider=case.provider)
        result['reopened'] = reopened.public()
        result['reopened_evidence'] = {source:reopened.handle('change_evidence',dict(case.ref(ready),source=source)) for source in result['evidence']}
        result['source_after_apply'] = (case.source/'main.py').read_text()
        result['default'] = reopened.handle('create_task',dict(project_id=case.pid,title='Other read-only task'))
        case.setup_app();refreshed_ready=case.approve(case.start())
        selection=case.app.public()['source_selection']
        result['refreshed'] = case.app.handle('save_sources',dict(project_id=case.pid,selection_version=selection['selection_version'],revision=selection['revision'],paths=selection['paths']))
        result['refreshed_evidence'] = {source:case.app.handle('change_evidence',dict(case.ref(refreshed_ready),source=source)) for source in result['evidence']}
        case.setup_app();case.provider.verdict='revise';case.approve(case.start())
        result['revision'] = copy.deepcopy(case.app.public())
        case.setup_app();case.provider.fail='Role: Implementer';case.start()
        result['failed'] = copy.deepcopy(case.app.public())
        return result
    finally:
        if hasattr(case, 'app'):
            case.app.cancel.set()
            case.app.wait()
            if case.app.worker and case.app.worker.is_alive():
                raise AssertionError('Fixture worker did not stop; temporary storage retained')
        case.doCleanups()


if __name__ == '__main__':
    print(json.dumps(fixtures()))
