"""Conversation display preferences (2026-11-20-details-panel-and-display-design.md)."""
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))

import display


class FakeApp:
    def __init__(self, state=None):
        self.lock = threading.RLock()
        self.state = state if state is not None else {}
        self.published = 0

    def publish(self):
        self.published += 1


class DisplayTests(unittest.TestCase):
    def test_defaults_apply_while_nothing_valid_is_stored(self):
        self.assertEqual(display.current({}), display.default())
        self.assertEqual(display.current({'display': {'thinking': 'loud'}}), display.default())
        self.assertEqual(display.default()['searches'], 'summary')

    def test_update_stores_merges_with_defaults_and_publishes(self):
        app = FakeApp()
        saved = display.display_update(app, {'display': {'thinking': 'hidden', 'tools': False}})
        self.assertEqual(saved, dict(display.default(), thinking='hidden', tools=False))
        self.assertEqual(app.state['display'], saved)
        self.assertEqual(display.current(app.state), saved)
        self.assertEqual(app.published, 1)

    def test_bad_values_are_refused_and_nothing_changes(self):
        app = FakeApp({'display': dict(display.default(), plans=False)})
        for bad, message in (({'thinking': 'some'}, 'Thinking must be summary, full or hidden.'),
                             ({'notes': 'yes'}, 'Notes must be on or off.'),
                             ({'colour': 'red'}, 'Unknown display setting: colour.'), ('all', None)):
            with self.assertRaises(ValueError) as caught:
                display.display_update(app, {'display': bad})
            if message:
                self.assertEqual(str(caught.exception), message)
        self.assertFalse(app.state['display']['plans'])
        self.assertEqual(app.published, 0)

    def test_detail_defaults_to_simple_and_validates(self):
        self.assertEqual(display.default()['detail'], 'simple')
        self.assertEqual(display.validate({'detail': 'detailed'})['detail'], 'detailed')
        self.assertEqual(display.validate({'thinking': 'full'})['detail'], 'simple')
        with self.assertRaises(ValueError) as caught:
            display.validate({'detail': 'loud'})
        self.assertEqual(str(caught.exception), 'Detail must be simple or detailed.')


if __name__ == '__main__':
    unittest.main()
