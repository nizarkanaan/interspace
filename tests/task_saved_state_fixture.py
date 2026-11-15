"""Disposable reopened backend states with earlier (read-only) tasks, consumed by the task-desk browser regression."""
import copy
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/backend'))
from service import Application
import projects
import tasks


class NoProvider:
    def __getattr__(self, name):
        raise AssertionError('Saved-state projection must not access a provider: ' + name)


def reopened_states(storage, malformed):
    project = projects.new_project(storage.parent / 'inert-source')
    project.update(id='fixture', name='Saved-state fixture', thread=[{'role':'user','text':'General history survives'}])
    other = projects.new_project(storage.parent / 'other-inert-source')
    other.update(id='other', name='Other healthy project')
    broken = tasks.imported('Malformed task');broken.update(id='broken', **copy.deepcopy(malformed))
    healthy = tasks.imported('Healthy task');healthy.update(id='healthy', thread=[{'role':'user','text':'Healthy conversation survives'}],
                                                           pending={'id':'plan-h','goal':'Healthy saved plan'})
    project.update(tasks={'broken':broken,'healthy':healthy}, selected_task_id='healthy')
    state = projects.empty_state();state.update(projects={'fixture':project,'other':other}, selected_project_id='fixture')
    storage.mkdir(parents=True)
    (storage/'state.json').write_text(json.dumps(state))
    app = Application(storage, provider=NoProvider())
    result = {'nonselected':app.public()}
    app.state['projects']['fixture']['selected_task_id']='broken';app.persist()
    app = Application(storage, provider=NoProvider())
    result['selected'] = app.public()
    result['healthy'] = app.handle('select_task', {'project_id':'fixture','task_id':'healthy'})
    result['general'] = app.handle('select_task', {'project_id':'fixture','task_id':None})
    result['other'] = app.handle('switch_project', {'project_id':'other'})
    saved = json.loads((storage/'state.json').read_text())
    result['raw_preserved'] = (app.state['projects']['fixture']['tasks']['broken'] == broken
                               and saved['projects']['fixture']['tasks']['broken'] == broken)
    app.scheduler.shutdown(5)
    return result


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='interspace-saved-task-') as folder:
        base = Path(folder)
        print(json.dumps([reopened_states(base/'status', {'error':'Saved failure','error_status':7}),
                          reopened_states(base/'message', {'thread':[None]})]))
