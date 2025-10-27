import queue
import sys
import tempfile
import time
from pathlib import Path
from types import ModuleType


def _prepare_module_dependencies():
    # Remove previously injected stubs so we can import the real module.
    for module_name in [
        'ui_config_window',
        'ui_settings_dialog',
        'ui_undo_dialog',
        'PyQt6',
        'PyQt6.QtWidgets',
        'PyQt6.QtGui',
        'PyQt6.QtCore',
    ]:
        sys.modules.pop(module_name, None)

    # Provide lightweight stand-ins for dialog modules that require PyQt.
    settings_dialog_module = ModuleType('ui_settings_dialog')

    class SettingsDialog:
        pass

    settings_dialog_module.SettingsDialog = SettingsDialog
    sys.modules['ui_settings_dialog'] = settings_dialog_module

    undo_dialog_module = ModuleType('ui_undo_dialog')

    class UndoDialog:
        pass

    undo_dialog_module.UndoDialog = UndoDialog
    sys.modules['ui_undo_dialog'] = undo_dialog_module


def _install_pyqt6_stubs():
    """Install lightweight PyQt6 stubs so ConfigWindow can be imported in tests."""
    if 'PyQt6' in sys.modules:
        return

    qt_module = ModuleType('PyQt6')
    sys.modules['PyQt6'] = qt_module

    qtwidgets = ModuleType('PyQt6.QtWidgets')

    class _Signal:
        def connect(self, *args, **kwargs):
            return None

    class QWidget:
        def __init__(self, *args, **kwargs):
            pass

        def closeEvent(self, event):
            if hasattr(event, 'accept'):
                event.accept()

        def addAction(self, *args, **kwargs):
            return None

    class _BaseWidget(QWidget):
        def __getattr__(self, _):
            def _noop(*args, **kwargs):
                return None

            return _noop

    class QPushButton(_BaseWidget):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.clicked = _Signal()

    class QListWidget(_BaseWidget):
        currentItemChanged = _Signal()
        itemChanged = _Signal()

    class QTextEdit(_BaseWidget):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

    class QApplication:
        @staticmethod
        def instance():
            return None

    class QMenu(_BaseWidget):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

    class QDialog(_BaseWidget):
        pass

    class QDialogButtonBox(_BaseWidget):
        class StandardButton:
            Ok = object()
            Cancel = object()

        def button(self, *args, **kwargs):
            return _BaseWidget()

    qtwidgets.QWidget = QWidget
    qtwidgets.QDialog = QDialog
    qtwidgets.QDialogButtonBox = QDialogButtonBox
    qtwidgets.QVBoxLayout = _BaseWidget
    qtwidgets.QHBoxLayout = _BaseWidget
    qtwidgets.QPushButton = QPushButton
    qtwidgets.QListWidget = QListWidget
    qtwidgets.QLineEdit = _BaseWidget
    qtwidgets.QSpinBox = _BaseWidget
    qtwidgets.QLabel = _BaseWidget
    qtwidgets.QTextEdit = QTextEdit
    qtwidgets.QFileDialog = _BaseWidget
    qtwidgets.QMessageBox = _BaseWidget
    qtwidgets.QListWidgetItem = _BaseWidget
    qtwidgets.QComboBox = _BaseWidget
    qtwidgets.QCheckBox = _BaseWidget
    qtwidgets.QInputDialog = _BaseWidget
    qtwidgets.QApplication = QApplication
    qtwidgets.QMenu = QMenu
    sys.modules['PyQt6.QtWidgets'] = qtwidgets

    qtgui = ModuleType('PyQt6.QtGui')

    class QKeySequence:
        def __init__(self, *args, **kwargs):
            pass

    class QAction(_BaseWidget):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.triggered = _Signal()

    qtgui.QKeySequence = QKeySequence
    qtgui.QAction = QAction
    sys.modules['PyQt6.QtGui'] = qtgui

    qtcore = ModuleType('PyQt6.QtCore')

    class Qt:
        class Key:
            Key_Escape = object()
            Key_Delete = object()

        class ShortcutContext:
            WindowShortcut = object()

    class QTimer(_BaseWidget):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

    def pyqtSlot(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    qtcore.Qt = Qt
    qtcore.QTimer = QTimer
    qtcore.pyqtSlot = pyqtSlot
    sys.modules['PyQt6.QtCore'] = qtcore


_prepare_module_dependencies()
_install_pyqt6_stubs()

from ui_config_window import ConfigWindow
from worker import MonitoringWorker


class DummyTimer:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class DummyCloseEvent:
    def __init__(self):
        self.accepted = False

    def accept(self):
        self.accepted = True


class DummyConfigManager:
    def __init__(self, base_path: Path):
        self._base_path = base_path
        self.saved = False

    def get_config_dir_path(self) -> Path:
        self._base_path.mkdir(parents=True, exist_ok=True)
        return self._base_path

    def save_config(self):
        self.saved = True

    def get_monitored_folders(self):
        return []

    def get_dry_run_mode(self):
        return False

    def get_archive_path_template(self):
        return ''

    def get_schedule_config(self):
        return {'interval_minutes': 0}

    def get_setting(self, _key, default=None):
        return default


def _drain_queue_messages(log_queue):
    messages = []
    while True:
        try:
            messages.append(log_queue.get_nowait())
        except queue.Empty:
            break
    return messages


def test_close_event_stops_running_worker_and_logs_shutdown():
    log_queue = queue.Queue()
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_manager = DummyConfigManager(Path(tmp_dir))
        worker = MonitoringWorker(config_manager, log_queue)

        window = ConfigWindow.__new__(ConfigWindow)
        window.config_manager = config_manager
        window.log_queue = log_queue
        window.log_timer = DummyTimer()
        window.monitoring_worker = worker
        window.worker_status = "Running"

        worker.start()

        try:
            start_time = time.time()
            while not worker.running and time.time() - start_time < 2:
                time.sleep(0.01)

            event = DummyCloseEvent()
            window.closeEvent(event)

            wait_start = time.time()
            while worker.is_alive() and time.time() - wait_start < 5:
                time.sleep(0.05)

            assert not worker.is_alive(), "Worker thread should terminate after window close"
            assert window.log_timer.stopped, "Log timer should be stopped during close"
            assert config_manager.saved, "Config manager should save on close"
            assert event.accepted, "Close event should be accepted"

            # Allow worker log messages to flush
            time.sleep(0.05)
            messages = _drain_queue_messages(log_queue)
            text_messages = [msg for msg in messages if isinstance(msg, str)]

            assert "INFO: Stopping monitoring due to window close..." in text_messages
            assert "INFO: AutoTidy configuration window closed." in text_messages
            assert any(msg == "INFO: Monitoring worker stopped." for msg in text_messages)
        finally:
            if worker.is_alive():
                worker.stop()
                worker.join(timeout=1)
