"""Tests for app/backend/research.

`python3 -m unittest tests.research.test_http` imports this directory as the package `tests.research`.
`python3 -m unittest discover -s tests` imports it as the top-level package `research`, the same name as
app/backend/research. In that case this package also searches app/backend/research and runs the backend
package's own `__init__`, so `research.http` and the source modules stay the backend's code (the same
arrangement as tests/runtime).
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _ROOT / 'app' / 'backend'
# Appended, never prepended: under discovery `tests` must stay ahead of app/backend.
for _path in (_ROOT / 'tests', _BACKEND):
    if str(_path) not in sys.path:
        sys.path.append(str(_path))

if __name__ == 'research':
    _REAL_INIT = _BACKEND / 'research' / '__init__.py'
    __path__.append(str(_REAL_INIT.parent))
    exec(compile(_REAL_INIT.read_text(encoding='utf-8'), str(_REAL_INIT), 'exec'))
