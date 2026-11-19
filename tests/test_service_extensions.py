import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))

import service  # noqa: E402


class FakeAuth:
    def status(self):
        return {'state': 'signed_out'}


class ExtensionMethodTests(unittest.TestCase):
    def test_missing_extension_modules_are_skipped(self):
        self.assertEqual(service.extension_methods(('no_such_extension_module',)), {})

    def test_methods_register_and_dispatch_on_the_agent_pool(self):
        module = types.ModuleType('fake_extension')
        module.METHODS = {'fake_echo': lambda app, params: {'echo': params.get('text'), 'storage': str(app.storage)}}
        with mock.patch.dict(sys.modules, {'fake_extension': module}), \
                mock.patch.object(service, 'EXTENSIONS', ('fake_extension',)):
            with tempfile.TemporaryDirectory() as folder:
                app = service.Application(folder, provider=FakeAuth())
                try:
                    self.assertEqual(app.handle('fake_echo', {'text': 'hi'})['echo'], 'hi')
                    router = service.Router(app, lambda message: None)
                    self.assertEqual(router.route('{"id": 1, "method": "fake_echo", "params": {}}'), 'agent')
                finally:
                    app.scheduler.shutdown(timeout_s=5)

    def test_duplicate_or_core_method_names_fail_startup(self):
        module = types.ModuleType('fake_extension')
        module.METHODS = {'state': lambda app, params: None}
        with mock.patch.dict(sys.modules, {'fake_extension': module}):
            with self.assertRaises(RuntimeError):
                service.extension_methods(('fake_extension',))

    def test_a_broken_extension_is_not_silently_skipped(self):
        module = types.ModuleType('fake_extension')

        def broken():
            raise ModuleNotFoundError("No module named 'missing_dependency'", name='missing_dependency')
        with mock.patch('importlib.import_module', side_effect=lambda name: broken()):
            with self.assertRaises(ModuleNotFoundError):
                service.extension_methods(('fake_extension',))


class BridgeRoutingTests(unittest.TestCase):
    def test_bridge_messages_go_to_the_bridge_and_never_to_handlers(self):
        with tempfile.TemporaryDirectory() as folder:
            app = service.Application(folder, provider=FakeAuth())
            try:
                received = []
                app.bridge = types.SimpleNamespace(deliver=received.append)
                router = service.Router(app, lambda message: None)
                for kind in service.BRIDGE_TYPES:
                    self.assertEqual(router.route('{"type": "%s", "id": "kc-1"}' % kind), 'bridge')
                self.assertEqual([m['type'] for m in received], list(service.BRIDGE_TYPES))
                app.bridge = None
                self.assertEqual(router.route('{"type": "keychain_reply", "id": "kc-2"}'), 'bridge')
            finally:
                app.scheduler.shutdown(timeout_s=5)


if __name__ == '__main__':
    unittest.main()
