"""Task outputs: list, read and save a research task's report and BibTeX (research/tasks.md "Outputs").

The scheduler writes `<storage>/tasks/<task_id>/outputs/report.md` and `references.bib`. These methods list them
and hand one to the Swift save panel (`app.bridge.save_panel`, research/credentials.md "Save panel"), which copies
it where the user picks. The backend itself never writes outside app data.
"""
import os
from pathlib import Path
import re

import scheduler

NAMES = dict(scheduler.OUTPUT_NAMES)
MAX_READ_BYTES = 1024 * 1024  # task_output_read returns at most 1 MiB of text (research/tasks.md).


def _folder(app, task_id):
    with app.lock:
        task = app.store.task(task_id)  # Unknown or damaged tasks raise ValueError('Unknown task.').
        title = task.get('title') if isinstance(task.get('title'), str) else ''
    return Path(app.events.root) / task['id'] / 'outputs', title


def task_outputs(app, params):
    """`{task_id}` -> `{outputs: [{name, kind, bytes, updated_at}]}`."""
    folder, _ = _folder(app, params.get('task_id'))
    return {'outputs': scheduler.list_outputs(folder)}


def _output_path(app, params):
    """The listed output file `name` of the task, a regular file inside app data; ValueError otherwise."""
    name = params.get('name')
    if name not in NAMES:
        raise ValueError('Unknown output.')
    folder, title = _folder(app, params.get('task_id'))
    if name not in [o['name'] for o in scheduler.list_outputs(folder)]:
        raise ValueError('This output does not exist yet.')
    path = folder / name
    storage = os.path.realpath(str(app.storage))
    real = os.path.realpath(str(path))
    if os.path.commonpath([real, storage]) != storage or path.is_symlink() or not path.is_file():
        raise ValueError('This output cannot be read.')
    return name, real, title


def task_output_read(app, params):
    """`{task_id, name}` -> `{name, kind, text, truncated}`: UTF-8 text, at most 1 MiB."""
    name, real, _ = _output_path(app, params)
    with open(real, 'rb') as handle:
        raw = handle.read(MAX_READ_BYTES + 1)
    return {'name': name, 'kind': NAMES[name], 'text': raw[:MAX_READ_BYTES].decode('utf-8', 'ignore'),
            'truncated': len(raw) > MAX_READ_BYTES}


def suggested_name(title, name):
    stem = re.sub(r'[^a-z0-9]+', '-', (title or '').lower()).strip('-')[:60].strip('-') or 'research'
    return stem + ('.bib' if name.endswith('.bib') else '.md')


def task_output_save(app, params):
    """`{task_id, name}` -> `{saved: bool}`: the user picks where to save a copy in a save panel."""
    name, real, title = _output_path(app, params)
    save = getattr(getattr(app, 'bridge', None), 'save_panel', None)
    if not callable(save):
        raise ValueError('Saving needs the Interspace app window.')
    result = save(real, suggested_name(title, name))
    saved = result.get('ok') if isinstance(result, dict) else result
    return {'saved': saved is True}


METHODS = {'task_outputs': task_outputs, 'task_output_read': task_output_read, 'task_output_save': task_output_save}
