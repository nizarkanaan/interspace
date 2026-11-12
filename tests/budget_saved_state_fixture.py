"""Actual public token-budget projections; disposable repositories and fake jobs/checks only."""
import copy
import json
from test_change_workflow import WorkflowTests
from test_budget_workflow import consume_all_but


def fixtures():
    case = WorkflowTests('test_complete_three_approval_lifecycle_releases_pause_and_hands_off_real_checks')
    case.setUp()
    try:
        result = {}
        case.setup_app();app = case.app
        app.handle('update_task', dict(project_id=case.pid, task_id=case.tid, title='Fix within budget'))
        result['editing'] = copy.deepcopy(app.public())
        case.propose()
        result['plan_fits'] = copy.deepcopy(app.public())
        consume_all_but(app, case.tid, 30000)
        result['plan_tight'] = copy.deepcopy(app.public())

        case.setup_app();app = case.app
        app.handle('update_task', dict(project_id=case.pid, task_id=case.tid, title='Fix within budget'))
        paused = case.start()
        result['paused'] = copy.deepcopy(app.public())
        case.provider.before = lambda prompt: consume_all_but(app, case.tid, 1) if 'Role: Tester' in prompt else None
        app.handle('approve_checks', copy.deepcopy(app.public()['run']['action_refs']['approve_checks']));app.wait()
        result['exhausted'] = copy.deepcopy(app.public())

        case.setup_app();app = case.app
        app.handle('update_task', dict(project_id=case.pid, task_id=case.tid, title='Older task'))
        app.state['projects'][case.pid]['tasks'][case.tid]['token_budget'] = None
        case.propose()
        result['legacy'] = copy.deepcopy(app.public())
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
