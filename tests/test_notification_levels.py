import queue
import tempfile
from pathlib import Path
from types import ModuleType
import sys
from unittest.mock import patch

from constants import (
    NOTIFICATION_LEVEL_NONE,
    NOTIFICATION_LEVEL_ERROR,
    NOTIFICATION_LEVEL_SUMMARY,
    NOTIFICATION_LEVEL_ALL,
)


def _prepare_module_dependencies():
    for module_name in [
        'ui_config_window',
        'PyQt6',
        'PyQt6.QtWidgets',
        'PyQt6.QtGui',
        'PyQt6.QtCore',
    ]:
        sys.modules.pop(module_name, None)


def _install_pyqt6_stubs():
    if 'PyQt6' in sys.modules:
        qtwidgets = sys.modules['PyQt6.QtWidgets']
        return qtwidgets

    qt_module = ModuleType('PyQt6')
    sys.modules['PyQt6'] = qt_module

    qtwidgets = ModuleType('PyQt6.QtWidgets')

    class _Signal:
        def connect(self, *args, **kwargs):  # pragma: no cover - stub
            return None

    class QWidget:
        def __init__(self, *args, **kwargs):
            pass

        def addAction(self, *args, **kwargs):
            return None

    class _BaseWidget(QWidget):
        def __getattr__(self, _):
            def _noop(*args, **kwargs):  # pragma: no cover - stub
                return None

            return _noop

    class QApplication:
        @staticmethod
        def instance():  # pragma: no cover - stub
            return None

    class QDialog(_BaseWidget):
        pass

    class QDialogButtonBox(_BaseWidget):
        class StandardButton:
            Ok = object()
            Cancel = object()

        def button(self, *_args, **_kwargs):
            return _BaseWidget()

    qtwidgets.QWidget = QWidget
    qtwidgets.QDialog = QDialog
    qtwidgets.QDialogButtonBox = QDialogButtonBox
    qtwidgets.QVBoxLayout = _BaseWidget
    qtwidgets.QHBoxLayout = _BaseWidget
    qtwidgets.QPushButton = _BaseWidget
    qtwidgets.QListWidget = _BaseWidget
    qtwidgets.QLineEdit = _BaseWidget
    qtwidgets.QSpinBox = _BaseWidget
    qtwidgets.QLabel = _BaseWidget
    qtwidgets.QTextEdit = _BaseWidget
    qtwidgets.QFileDialog = _BaseWidget
    class QMessageBox(_BaseWidget):
        class StandardButton:
            Yes = 1
            No = 2

        @staticmethod
        def critical(*_args, **_kwargs):
            return QMessageBox.StandardButton.No

        @staticmethod
        def warning(*_args, **_kwargs):
            return QMessageBox.StandardButton.No

        @staticmethod
        def information(*_args, **_kwargs):
            return QMessageBox.StandardButton.No

        @staticmethod
        def question(*_args, **_kwargs):
            return QMessageBox.StandardButton.No

    qtwidgets.QMessageBox = QMessageBox
    qtwidgets.QListWidgetItem = _BaseWidget
    qtwidgets.QComboBox = _BaseWidget
    qtwidgets.QCheckBox = _BaseWidget
    qtwidgets.QInputDialog = _BaseWidget
    qtwidgets.QApplication = QApplication
    qtwidgets.QMenu = _BaseWidget
    class _Header:
        def setSectionResizeMode(self, *_args, **_kwargs):
            return None

    class QHeaderView(_BaseWidget):
        class ResizeMode:
            Stretch = object()
            Interactive = object()

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

    class QTableWidgetItem(_BaseWidget):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._data = {}

        def setData(self, role, value):
            self._data[role] = value

        def data(self, role):
            return self._data.get(role)

    class QTableWidget(_BaseWidget):
        class SelectionBehavior:
            SelectRows = object()

        class EditTrigger:
            NoEditTriggers = object()

        class SelectionMode:
            SingleSelection = object()

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._items = {}
            self._row_count = 0

        def setColumnCount(self, _count):
            return None

        def setHorizontalHeaderLabels(self, _labels):
            return None

        def horizontalHeader(self):
            return _Header()

        def setColumnHidden(self, *_args, **_kwargs):
            return None

        def setSelectionBehavior(self, *_args, **_kwargs):
            return None

        def setEditTriggers(self, *_args, **_kwargs):
            return None

        def setSelectionMode(self, *_args, **_kwargs):
            return None

        def setRowCount(self, count):
            self._row_count = count
            self._items = {}

        def setItem(self, row, column, item):
            self._items[(row, column)] = item

        def selectedItems(self):
            return []

        def currentRow(self):
            return -1

        def item(self, row, column):
            return self._items.get((row, column))

    qtwidgets.QHeaderView = QHeaderView
    qtwidgets.QTableWidget = QTableWidget
    qtwidgets.QTableWidgetItem = QTableWidgetItem
    sys.modules['PyQt6.QtWidgets'] = qtwidgets

    qtgui = ModuleType('PyQt6.QtGui')

    class QKeySequence:
        def __init__(self, *args, **kwargs):  # pragma: no cover - stub
            pass

    class QAction(_BaseWidget):
        triggered = _Signal()

    qtgui.QKeySequence = QKeySequence
    qtgui.QAction = QAction
    sys.modules['PyQt6.QtGui'] = qtgui

    qtcore = ModuleType('PyQt6.QtCore')

    class QTimer(_BaseWidget):
        pass

    def pyqtSlot(*_args, **_kwargs):
        def decorator(func):
            return func

        return decorator

    class Qt:
        class Key:
            Key_Escape = object()
            Key_Delete = object()
            Key_F5 = object()

        class ItemDataRole:
            UserRole = 0

        class ShortcutContext:
            WindowShortcut = object()

        class KeyboardModifier:
            ControlModifier = object()

    qtcore.QTimer = QTimer
    qtcore.pyqtSlot = pyqtSlot
    qtcore.Qt = Qt
    class QVariant:
        def __init__(self, value=None):  # pragma: no cover - stub
            self.value = value

    qtcore.QVariant = QVariant
    sys.modules['PyQt6.QtCore'] = qtcore

    return qtwidgets


_prepare_module_dependencies()
qtwidgets_module = _install_pyqt6_stubs()

import ui_config_window
from ui_config_window import ConfigWindow
from worker import MonitoringWorker


class DummyApplication:
    notifications = []

    @classmethod
    def reset(cls):
        cls.notifications.clear()

    @classmethod
    def instance(cls):
        return cls

    @classmethod
    def show_system_notification(cls, title, message):
        cls.notifications.append((title, message))


# Ensure the module uses the dummy application for notification delivery.
ui_config_window.QApplication = DummyApplication
qtwidgets_module.QApplication = DummyApplication


class DummyScrollBar:
    def __init__(self):
        self.value = 0

    def maximum(self):
        return 0

    def setValue(self, value):
        self.value = value


class DummyLogView:
    def __init__(self):
        self.messages = []
        self._scroll_bar = DummyScrollBar()

    def append(self, text):
        self.messages.append(text)

    def verticalScrollBar(self):
        return self._scroll_bar


class WindowConfigManager:
    def __init__(self, level):
        self._level = level

    def get_notification_level(self):
        return self._level


def _create_config_window(level):
    window = ConfigWindow.__new__(ConfigWindow)
    window.config_manager = WindowConfigManager(level)
    window.log_queue = queue.Queue()
    window.log_view = DummyLogView()
    window._update_ui_for_status_and_mode = lambda: None
    window.monitoring_worker = None
    window.worker_status = "Stopped"
    return window


def test_config_window_notification_levels():
    scenarios = [
        (NOTIFICATION_LEVEL_NONE, False, False),
        (NOTIFICATION_LEVEL_ERROR, False, True),
        (NOTIFICATION_LEVEL_SUMMARY, True, True),
        (NOTIFICATION_LEVEL_ALL, True, True),
    ]

    for level, summary_expected, error_expected in scenarios:
        DummyApplication.reset()
        window = _create_config_window(level)
        window.log_queue.put({
            "type": "SHOW_NOTIFICATION",
            "title": "Summary",
            "message": "Processed files",
            "category": "summary",
        })
        window.check_log_queue()
        assert bool(DummyApplication.notifications) == summary_expected

        DummyApplication.reset()
        window.log_queue.put({
            "type": "SHOW_NOTIFICATION",
            "title": "Error",
            "message": "Something went wrong",
            "category": "error",
        })
        window.check_log_queue()
        assert bool(DummyApplication.notifications) == error_expected


class SingleCycleStopEvent:
    def __init__(self):
        self._is_set = False

    def is_set(self):
        return self._is_set

    def wait(self, _timeout):
        self._is_set = True
        return True

    def set(self):
        self._is_set = True


class WorkerConfigManager:
    def __init__(self, monitored_path: Path, config_dir: Path, level: str):
        self._monitored_path = monitored_path
        self._config_dir = config_dir
        self._level = level

    def get_monitored_folders(self):
        return [{
            'path': str(self._monitored_path),
            'age_days': 0,
            'pattern': '*.*',
            'use_regex': False,
            'rule_logic': 'OR',
            'action': 'move',
            'destination_folder': '',
            'exclusions': [],
            'enabled': True,
        }]

    def get_dry_run_mode(self):
        return True

    def get_archive_path_template(self):
        return "{YYYY}/{MM}/{DD}"

    def get_schedule_config(self):
        return {'interval_minutes': 0}

    def get_notification_level(self):
        return self._level

    def get_config_dir_path(self):
        self._config_dir.mkdir(parents=True, exist_ok=True)
        return self._config_dir


def _run_worker_once(config_manager):
    log_queue = queue.Queue()
    worker = MonitoringWorker(config_manager, log_queue)
    worker._stop_event = SingleCycleStopEvent()
    with patch('worker.check_file', return_value=True), patch('worker.process_file_action') as process_mock:
        process_mock.return_value = (True, 'processed')
        worker.run()
    notifications = []
    while True:
        try:
            item = log_queue.get_nowait()
        except queue.Empty:
            break
        else:
            if isinstance(item, dict) and item.get('type') == 'SHOW_NOTIFICATION':
                notifications.append(item)
    return notifications


def test_worker_summary_notifications_respect_level():
    scenarios = [
        (NOTIFICATION_LEVEL_NONE, False),
        (NOTIFICATION_LEVEL_ERROR, False),
        (NOTIFICATION_LEVEL_SUMMARY, True),
        (NOTIFICATION_LEVEL_ALL, True),
    ]

    with tempfile.TemporaryDirectory() as tmp_dir:
        base_path = Path(tmp_dir)
        monitored_path = base_path / "monitored"
        config_dir = base_path / "config"
        monitored_path.mkdir()
        config_dir.mkdir()
        (monitored_path / "example.txt").write_text("content")

        for level, expected in scenarios:
            notifications = _run_worker_once(WorkerConfigManager(monitored_path, config_dir, level))
            summary_present = any(note.get('category') == 'summary' for note in notifications)
            assert summary_present == expected


def _run_worker_with_missing_folder(level: str):
    log_queue = queue.Queue()
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_path = Path(tmp_dir)
        config_dir = base_path / "config"
        config_dir.mkdir()
        missing_path = base_path / "missing"
        config_manager = WorkerConfigManager(missing_path, config_dir, level)
        worker = MonitoringWorker(config_manager, log_queue)
        worker._stop_event = SingleCycleStopEvent()
        worker.run()

    notifications = []
    while True:
        try:
            item = log_queue.get_nowait()
        except queue.Empty:
            break
        else:
            if isinstance(item, dict) and item.get('type') == 'SHOW_NOTIFICATION':
                notifications.append(item)
    return notifications


def test_worker_error_notifications_respect_level():
    scenarios = [
        (NOTIFICATION_LEVEL_NONE, False),
        (NOTIFICATION_LEVEL_ERROR, True),
        (NOTIFICATION_LEVEL_SUMMARY, True),
        (NOTIFICATION_LEVEL_ALL, True),
    ]

    for level, expected in scenarios:
        notifications = _run_worker_with_missing_folder(level)
        error_present = any(note.get('category') == 'error' for note in notifications)
        assert error_present == expected

