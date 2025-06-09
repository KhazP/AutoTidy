import sys
import queue
import threading
import os
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox
from PyQt6.QtGui import QIcon, QAction # Assuming you have an icon file
from PyQt6.QtCore import pyqtSlot

# Import local modules
from config_manager import ConfigManager
from ui_config_window import ConfigWindow
from constants import APP_NAME # Import from constants
# Worker is implicitly used by ConfigWindow's start/stop actions
# No direct need for UndoManager/UndoDialog imports here if ConfigWindow handles it

# Determine the base path (directory of the script)
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

ICON_NAME = "autotidyicon.ico"
ICON_PATH = resource_path(ICON_NAME)  # Use resource_path for PyInstaller compatibility

class AutoTidyApp(QApplication):
    """Main application class managing the system tray icon and windows."""

    def __init__(self, argv):
        super().__init__(argv)
        self.setQuitOnLastWindowClosed(False) # Keep running in tray

        # Check if system tray is available
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("ERROR: System tray is not available on this system!", file=sys.stderr)
            QMessageBox.critical(None, "AutoTidy Error", "System tray is not available on this system!")
            sys.exit(1)

        self.config_manager = ConfigManager(APP_NAME) # Pass APP_NAME here
        self.log_queue = queue.Queue()

        # Create UI (initially hidden)
        self.config_window = ConfigWindow(self.config_manager, self.log_queue)        # Create Tray Icon
        self.tray_icon = QSystemTrayIcon(self)
        
        # Set icon using QIcon(ICON_PATH)
        if os.path.exists(ICON_PATH):
            icon = QIcon(ICON_PATH)
            self.tray_icon.setIcon(icon)
        else:
            # Use a default Qt icon as fallback
            from PyQt6.QtWidgets import QStyle
            style = self.style()
            if style:
                icon = style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
                self.tray_icon.setIcon(icon)
            
        self.tray_icon.setToolTip(f"{APP_NAME} is running")
        self.tray_icon.show()

        # Create Tray Menu
        self.tray_menu = QMenu()
        show_action = QAction("Show/Hide Config", self)
        start_action = QAction("Start Monitoring", self)
        stop_action = QAction("Stop Monitoring", self)
        history_action = QAction("View Action History / Undo", self) # New action
        quit_action = QAction("Quit", self)

        self.tray_menu.addAction(show_action)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(start_action)
        self.tray_menu.addAction(stop_action)
        self.tray_menu.addAction(history_action) # Add to menu
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(self.tray_menu)

        # Connect Signals
        show_action.triggered.connect(self.toggle_window)
        start_action.triggered.connect(self.config_window.start_monitoring) # Delegate to window's slot
        stop_action.triggered.connect(self.config_window.stop_monitoring)   # Delegate to window's slot
        history_action.triggered.connect(self.config_window.open_undo_dialog) # Connect to ConfigWindow's slot
        quit_action.triggered.connect(self.quit_app)
        self.tray_icon.activated.connect(self.on_tray_activated)

        # Show Tray Icon
        self.log_queue.put(f"{APP_NAME} started. Running in system tray.") # Simpler log message
        self.log_queue.put("STATUS: Stopped") # Initial status

        # Timer to check log queue is in ConfigWindow, it will handle notifications via QApplication.instance()
        # No separate timer or direct connection needed here for notifications anymore.

    def show_system_notification(self, title: str, message: str):
        """Displays a system tray notification."""
        if self.tray_icon.isVisible(): # Only show if tray icon is active
            icon_type = QSystemTrayIcon.MessageIcon.Information
            self.tray_icon.showMessage(title, message, icon_type, 5000) # Show for 5 seconds
        else:
            # Fallback if tray icon isn't visible for some reason (should not happen in normal operation)
            print(f"Tray Notification: {title} - {message}", file=sys.stderr)

    @pyqtSlot(QSystemTrayIcon.ActivationReason)
    def on_tray_activated(self, reason):
        """Handle tray icon activation (e.g., click)."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger: # Left click
            self.toggle_window()
        # elif reason == QSystemTrayIcon.ActivationReason.Context: # Right click handled by menu

    @pyqtSlot()
    def toggle_window(self):
        """Show or hide the configuration window."""
        if self.config_window.isVisible():
            self.config_window.hide()
        else:
            self.config_window.show()
            self.config_window.raise_()
            self.config_window.activateWindow()

    @pyqtSlot()
    def quit_app(self):
        """Cleanly stop the worker and quit the application."""
        self.log_queue.put("INFO: Quit action triggered. Shutting down...")

        # Attempt to stop the worker thread gracefully
        if self.config_window.monitoring_worker and self.config_window.monitoring_worker.is_alive():
            self.log_queue.put("INFO: Stopping worker thread...")
            self.config_window.stop_monitoring()
            # Give the worker a moment to stop
            self.config_window.monitoring_worker.join(timeout=2.0)
            if self.config_window.monitoring_worker.is_alive():
                 self.log_queue.put("WARNING: Worker thread did not stop gracefully.")


        # Save config just in case (though it should save on changes)
        self.config_manager.save_config()

        self.tray_icon.hide() # Hide tray icon before quitting
        self.quit()


if __name__ == "__main__":
    # Ensure APP_NAME is used for ConfigManager initialization
    app = AutoTidyApp(sys.argv)
    sys.exit(app.exec())
