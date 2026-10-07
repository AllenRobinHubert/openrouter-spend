import importlib.util
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace


def load_plugin():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "registration_test_plugin", root / "__init__.py", submodule_search_locations=[str(root)]
    )
    import sys
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Context:
    def __init__(self):
        self.hooks = {}
        self.middleware = {}
        self.commands = {}
        self.cli = {}
        self.directory = None
        self.profile_name = "example"

    @property
    def state(self):
        if self.directory is None:
            raise AssertionError("State must not be accessed during registration")
        return SimpleNamespace(data_dir=self.directory)

    def get_config(self, key, default=None):
        return default

    def register_hook(self, name, callback):
        self.hooks[name] = callback

    def register_middleware(self, name, callback):
        self.middleware[name] = callback

    def register_command(self, name, callback, **kwargs):
        self.commands[name] = callback

    def register_cli_command(self, name, **kwargs):
        self.cli[name] = kwargs


class RegistrationTests(unittest.TestCase):
    def test_registration_is_declarative_and_first_command_opens_scoped_ledger(self):
        ctx = Context()
        load_plugin().register(ctx)
        self.assertEqual(set(ctx.hooks), {
            "pre_api_request", "api_request_error", "post_auxiliary_call", "post_tool_call"
        })
        self.assertEqual(set(ctx.middleware), {"llm_execution"})
        with tempfile.TemporaryDirectory() as directory:
            ctx.directory = Path(directory)
            result = ctx.commands["spend"]("help")
            self.assertIn("reconcile", result)
            ctx.commands["spend"]("ledger")
            self.assertTrue(any(ctx.directory.glob("*.sqlite3")))

    def test_callbacks_share_one_instance_and_forward_arguments(self):
        from unittest.mock import Mock
        from concurrent.futures import ThreadPoolExecutor
        ctx = Context()
        module = load_plugin()
        instance = Mock()
        module.SpendPlugin = Mock(return_value=instance)
        module.register(ctx)
        with tempfile.TemporaryDirectory() as directory:
            ctx.directory = Path(directory)
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda i: ctx.hooks["pre_api_request"](api_request_id=str(i)), range(12)))
            module.SpendPlugin.assert_called_once_with(ctx.directory, ctx.get_config, profile="example")
            self.assertEqual(instance.on_pre_request.call_count, 12)
            ctx.middleware["llm_execution"]("next", model="demo")
            instance.on_execution.assert_called_once_with("next", model="demo")


if __name__ == "__main__":
    unittest.main()
