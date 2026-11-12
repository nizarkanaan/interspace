"""Tests for app/backend/runtime.

`python3 -m unittest tests.runtime.test_codex` imports this directory as the package `tests.runtime`.
`python3 -m unittest discover -s tests` imports it as the top-level package `runtime`, the same name as
app/backend/runtime. In that case this package also searches app/backend/runtime and runs the backend
package's own `__init__`, so `runtime.codex` and `runtime.mcp_bridge` stay the backend's code (the same
arrangement as tests/spaces).
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _ROOT / 'app' / 'backend'
for _path in (_BACKEND, _ROOT / 'tests'):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

if __name__ == 'runtime':
    _REAL_INIT = _BACKEND / 'runtime' / '__init__.py'
    __path__.append(str(_REAL_INIT.parent))
    exec(compile(_REAL_INIT.read_text(encoding='utf-8'), str(_REAL_INIT), 'exec'))
