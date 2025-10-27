import sys
from types import ModuleType


def _prepare_module_dependencies():
    for module_name in [
        "ui_config_window",
        "ui_settings_dialog",
        "PyQt6",
        "PyQt6.QtWidgets",
        "PyQt6.QtGui",
        "PyQt6.QtCore",
    ]:
        sys.modules.pop(module_name, None)


def _install_pyqt6_stubs():
    if "PyQt6" in sys.modules:
        return

    qt_module = ModuleType("PyQt6")
    sys.modules["PyQt6"] = qt_module

    qtwidgets = ModuleType("PyQt6.QtWidgets")

    class _BaseWidget:
        def __init__(self, *args, **kwargs):  # pragma: no cover - helper stub
            pass

        def __getattr__(self, _):  # pragma: no cover - helper stub
            def _noop(*_args, **_kwargs):
                return None

            return _noop

        def setEnabled(self, *_args, **_kwargs):  # pragma: no cover - helper stub
            return None

        def setToolTip(self, *_args, **_kwargs):  # pragma: no cover - helper stub
            return None

    class QWidget(_BaseWidget):
        pass

    qtwidgets.QWidget = QWidget
    qtwidgets.QDialog = _BaseWidget
    class QDialogButtonBox(_BaseWidget):
        class StandardButton:
            Ok = object()
            Cancel = object()

        def button(self, *_args, **_kwargs):
            return _BaseWidget()

    qtwidgets.QDialogButtonBox = QDialogButtonBox
    qtwidgets.QVBoxLayout = _BaseWidget
    qtwidgets.QHBoxLayout = _BaseWidget
    qtwidgets.QGroupBox = _BaseWidget
    qtwidgets.QFormLayout = _BaseWidget
    qtwidgets.QPushButton = _BaseWidget
    qtwidgets.QListWidget = _BaseWidget
    qtwidgets.QLineEdit = _BaseWidget
    qtwidgets.QSpinBox = _BaseWidget
    qtwidgets.QLabel = _BaseWidget
    qtwidgets.QTextEdit = _BaseWidget
    qtwidgets.QFileDialog = _BaseWidget
    qtwidgets.QMessageBox = _BaseWidget
    qtwidgets.QListWidgetItem = _BaseWidget
    qtwidgets.QComboBox = _BaseWidget
    qtwidgets.QCheckBox = _BaseWidget
    qtwidgets.QInputDialog = _BaseWidget
    qtwidgets.QApplication = _BaseWidget
    qtwidgets.QMenu = _BaseWidget
    class QHeaderView(_BaseWidget):
        class ResizeMode:
            Stretch = object()
            Interactive = object()

    qtwidgets.QHeaderView = QHeaderView
    qtwidgets.QTableWidgetItem = _BaseWidget
    qtwidgets.QTableWidget = _BaseWidget
    sys.modules["PyQt6.QtWidgets"] = qtwidgets

    qtgui = ModuleType("PyQt6.QtGui")

    class QKeySequence:  # pragma: no cover - helper stub
        def __init__(self, *args, **kwargs):
            pass

    class QAction(_BaseWidget):  # pragma: no cover - helper stub
        pass

    qtgui.QKeySequence = QKeySequence
    qtgui.QAction = QAction
    sys.modules["PyQt6.QtGui"] = qtgui

    qtcore = ModuleType("PyQt6.QtCore")

    class Qt:  # pragma: no cover - helper stub
        class Key:
            Key_Delete = object()
            Key_Escape = object()

        class ShortcutContext:
            WindowShortcut = object()

        class ItemDataRole:
            UserRole = 0

    class QTimer(_BaseWidget):  # pragma: no cover - helper stub
        pass

    def pyqtSlot(*_args, **_kwargs):  # pragma: no cover - helper stub
        def decorator(func):
            return func

        return decorator

    class QVariant:  # pragma: no cover - helper stub
        pass

    qtcore.Qt = Qt
    qtcore.QTimer = QTimer
    qtcore.pyqtSlot = pyqtSlot
    qtcore.QVariant = QVariant
    sys.modules["PyQt6.QtCore"] = qtcore


class DummyConfigManager:
    def __init__(self, dry_run_mode: bool = False):
        self._dry_run_mode = dry_run_mode

    def get_setting(self, key, default=None):
        if key == "dry_run_mode":
            return self._dry_run_mode
        return default

    def get_dry_run_mode(self):
        return self._dry_run_mode

    def set_dry_run_mode(self, value: bool):
        self._dry_run_mode = value


class DummyButton:
    def __init__(self):
        self.text = ""
        self.tooltip = ""
        self.enabled = True

    def setText(self, value):
        self.text = value

    def setToolTip(self, value):
        self.tooltip = value

    def setEnabled(self, value):
        self.enabled = value


class DummyWidget:
    def __init__(self):
        self.enabled = True

    def setEnabled(self, value):
        self.enabled = value


class DummyListWidget(DummyWidget):
    def currentItem(self):
        return None


def _create_window(config_window_cls):
    window = config_window_cls.__new__(config_window_cls)
    window.config_manager = DummyConfigManager()
    window.worker_status = "Stopped"
    window.start_button = DummyButton()
    window.stop_button = DummyWidget()
    window.add_folder_button = DummyWidget()
    window.apply_template_button = DummyWidget()
    window.remove_folder_button = DummyWidget()
    window.settings_button = DummyWidget()
    window.folder_list_widget = DummyListWidget()
    window.age_spinbox = DummyWidget()
    window.pattern_lineedit = DummyWidget()
    window.rule_logic_combo = DummyWidget()
    window.useRegexCheckbox = DummyWidget()
    window.actionComboBox = DummyWidget()
    window.enabledCheckbox = DummyWidget()
    window.exclusion_list_widget = DummyWidget()
    window.add_exclusion_button = DummyWidget()
    window.remove_exclusion_button = DummyWidget()
    window.exclusion_help_button = DummyWidget()
    window._update_destination_enabled_state = lambda *args, **kwargs: None
    return window


def test_settings_dialog_updates_start_button_text(monkeypatch):
    _prepare_module_dependencies()
    _install_pyqt6_stubs()

    import ui_config_window
    ConfigWindow = ui_config_window.ConfigWindow

    class DummySettingsDialog:
        def __init__(self, config_manager, _parent):
            self.config_manager = config_manager

        def exec(self):
            self.config_manager.set_dry_run_mode(True)

    monkeypatch.setattr(ui_config_window, "SettingsDialog", DummySettingsDialog)

    window = _create_window(ConfigWindow)
    window._update_ui_for_status_and_mode()
    assert window.start_button.text == "&Start Monitoring"

    window.open_settings_dialog()

    assert window.start_button.text == "&Start Dry Run"
    assert "Dry Run" in window.start_button.tooltip
