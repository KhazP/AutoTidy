import json
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from unittest import TestCase
from unittest.mock import patch


def _install_pyqt6_stubs():
    if 'PyQt6' in sys.modules:
        return

    qt_module = ModuleType('PyQt6')
    sys.modules['PyQt6'] = qt_module

    qtwidgets = ModuleType('PyQt6.QtWidgets')

    class QApplication:
        def __init__(self, *args, **kwargs):
            pass

        def setQuitOnLastWindowClosed(self, *args, **kwargs):
            pass

        def style(self):
            return QStyle()

    class QMessageBox:
        @staticmethod
        def critical(*args, **kwargs):
            pass

    class QSystemTrayIcon:
        class ActivationReason:
            Trigger = object()

        class MessageIcon:
            Information = object()

        def __init__(self, *args, **kwargs):
            pass

        @staticmethod
        def isSystemTrayAvailable():
            return True

        def setIcon(self, *args, **kwargs):
            pass

        def setToolTip(self, *args, **kwargs):
            pass

        def show(self):
            pass

        def setContextMenu(self, *args, **kwargs):
            pass

        def showMessage(self, *args, **kwargs):
            pass

        def isVisible(self):
            return True

        def hide(self):
            pass

        class _Signal:
            def connect(self, *args, **kwargs):
                pass

        activated = _Signal()

    class QMenu:
        def __init__(self, *args, **kwargs):
            pass

        def addAction(self, *args, **kwargs):
            return QAction()

        def addSeparator(self):
            pass

    class QAction:
        def __init__(self, *args, **kwargs):
            self.triggered = QSystemTrayIcon._Signal()

    class QStyle:
        class StandardPixmap:
            SP_ComputerIcon = object()

        def standardIcon(self, *args, **kwargs):
            return QIcon()

    qtwidgets.QApplication = QApplication
    qtwidgets.QSystemTrayIcon = QSystemTrayIcon
    qtwidgets.QMenu = QMenu
    qtwidgets.QMessageBox = QMessageBox
    qtwidgets.QStyle = QStyle

    sys.modules['PyQt6.QtWidgets'] = qtwidgets

    qtgui = ModuleType('PyQt6.QtGui')

    class QIcon:
        def __init__(self, *args, **kwargs):
            pass

    class QAction(QAction):
        pass

    qtgui.QIcon = QIcon
    qtgui.QAction = QAction
    sys.modules['PyQt6.QtGui'] = qtgui

    qtcore = ModuleType('PyQt6.QtCore')

    def pyqtSlot(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    qtcore.pyqtSlot = pyqtSlot
    sys.modules['PyQt6.QtCore'] = qtcore

    if 'ui_config_window' not in sys.modules:
        ui_config_window = ModuleType('ui_config_window')

        class ConfigWindow:
            def __init__(self, *args, **kwargs):
                self.monitoring_worker = None

            def start_monitoring(self, *args, **kwargs):
                pass

            def stop_monitoring(self, *args, **kwargs):
                pass

            def open_undo_dialog(self, *args, **kwargs):
                pass

            def show(self):
                pass

            def hide(self):
                pass

            def isVisible(self):
                return False

            def raise_(self):
                pass

            def activateWindow(self):
                pass

        ui_config_window.ConfigWindow = ConfigWindow
        sys.modules['ui_config_window'] = ui_config_window


_install_pyqt6_stubs()

from config_manager import ConfigManager
from main import handle_context_menu_action


class HandleContextMenuActionTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.home_path = Path(self.temp_dir.name)
        home_patcher = patch('pathlib.Path.home', return_value=self.home_path)
        self.addCleanup(home_patcher.stop)
        home_patcher.start()

        self.config_manager = ConfigManager('AutoTidyTest')

        self.monitor_folder = self.home_path / 'monitor_me'
        self.monitor_folder.mkdir(parents=True, exist_ok=True)

        self.exclude_folder = self.home_path / 'exclude_me'
        self.exclude_folder.mkdir(parents=True, exist_ok=True)

    def _load_config_file(self):
        with open(self.config_manager.config_file, 'r', encoding='utf-8') as handle:
            return json.load(handle)

    def test_add_folder_updates_config_file(self):
        handle_context_menu_action('add_folder', str(self.monitor_folder), self.config_manager)

        config_contents = self._load_config_file()
        paths = [folder['path'] for folder in config_contents.get('folders', [])]
        self.assertIn(str(self.monitor_folder), paths)

    def test_exclude_folder_updates_config_file(self):
        handle_context_menu_action('exclude_folder', str(self.exclude_folder), self.config_manager)

        config_contents = self._load_config_file()
        excluded = config_contents.get('excluded_folders', [])
        self.assertIn(str(self.exclude_folder), excluded)

