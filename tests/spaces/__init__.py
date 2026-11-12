"""Tests for app/backend/spaces.

`python3 -m unittest tests.spaces.test_notion` imports this directory as the
package `tests.spaces`. `python3 -m unittest discover -s tests` imports it as
the top-level package `spaces`, the same name as app/backend/spaces. In that
case this package also searches app/backend/spaces and runs the backend
registry, so `spaces.base`, `spaces.notion` and `spaces.connector` stay the
backend's own code.
"""
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2] / 'app' / 'backend'
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

if __name__ == 'spaces':
    _REAL_INIT = _BACKEND / 'spaces' / '__init__.py'
    __path__.append(str(_REAL_INIT.parent))
    exec(compile(_REAL_INIT.read_text(encoding='utf-8'), str(_REAL_INIT), 'exec'))
