import importlib
import platform
import sys


def test_startup_manager_import_on_non_windows(monkeypatch):
    """Importing startup_manager should work without winreg on non-Windows systems."""

    module_name = "startup_manager"
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    sys.modules.pop(module_name, None)

    module = importlib.import_module(module_name)

    assert hasattr(module, "set_autostart")
    assert callable(module.set_autostart)
