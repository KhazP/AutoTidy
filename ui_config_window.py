import sys
import queue
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QLineEdit,
    QSpinBox, QLabel, QTextEdit, QFileDialog, QMessageBox, QListWidgetItem, QComboBox
)
from PyQt6.QtCore import QTimer, Qt, pyqtSlot

from config_manager import ConfigManager
from worker import MonitoringWorker
from ui_settings_dialog import SettingsDialog # Import the new dialog

LOG_QUEUE_CHECK_INTERVAL_MS = 250

class ConfigWindow(QWidget):
    """Main configuration window for AutoTidy."""

    def __init__(self, config_manager: ConfigManager, log_queue: queue.Queue):
        super().__init__()
        self.config_manager = config_manager
        self.log_queue = log_queue
        self.monitoring_worker: MonitoringWorker | None = None
        self.worker_status = "Stopped" # Track worker status

        self.setWindowTitle("AutoTidy Configuration")
        self.setGeometry(200, 200, 600, 450) # x, y, width, height

        self._init_ui()
        self._load_initial_config()
        self._setup_log_timer()

    def _init_ui(self):
        """Initialize UI elements and layout."""
        main_layout = QVBoxLayout(self)

        # --- Top Controls ---
        top_controls_layout = QHBoxLayout()
        self.add_folder_button = QPushButton("Add Folder")
        self.remove_folder_button = QPushButton("Remove Selected")
        top_controls_layout.addWidget(self.add_folder_button)
        top_controls_layout.addWidget(self.remove_folder_button)
        top_controls_layout.addStretch()
        # --- Add Settings Button ---
        self.settings_button = QPushButton("Settings")
        # Optionally add an icon: self.settings_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        top_controls_layout.addWidget(self.settings_button)
        # -------------------------
        main_layout.addLayout(top_controls_layout)

        # --- Folder List ---
        main_layout.addWidget(QLabel("Monitored Folders:"))
        self.folder_list_widget = QListWidget()
        main_layout.addWidget(self.folder_list_widget)

        # --- Rule Editor ---
        rule_layout = QHBoxLayout()
        rule_layout.addWidget(QLabel("Rules for selected folder:"))
        rule_layout.addWidget(QLabel("Min Age (days):"))
        self.age_spinbox = QSpinBox()
        self.age_spinbox.setRange(0, 3650) # 0 to 10 years
        self.age_spinbox.setEnabled(False)
        rule_layout.addWidget(self.age_spinbox)

        rule_layout.addWidget(QLabel("Filename Pattern:"))
        self.pattern_lineedit = QLineEdit()
        self.pattern_lineedit.setPlaceholderText("*.*")
        self.pattern_lineedit.setEnabled(False)
        rule_layout.addWidget(self.pattern_lineedit)

        rule_layout.addWidget(QLabel("Logic:"))
        self.rule_logic_combo = QComboBox()
        self.rule_logic_combo.addItems(["OR", "AND"])
        self.rule_logic_combo.setEnabled(False)
        rule_layout.addWidget(self.rule_logic_combo)

        main_layout.addLayout(rule_layout)

        # --- Status and Logs ---
        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel("Status:"))
        self.status_label = QLabel("Stopped")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        self.start_button = QPushButton("Start Monitoring")
        self.stop_button = QPushButton("Stop Monitoring")
        self.stop_button.setEnabled(False)
        status_layout.addWidget(self.start_button)
        status_layout.addWidget(self.stop_button)
        main_layout.addLayout(status_layout)

        main_layout.addWidget(QLabel("Logs:"))
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        main_layout.addWidget(self.log_view)

        # --- Connect Signals ---
        self.add_folder_button.clicked.connect(self.add_folder)
        self.remove_folder_button.clicked.connect(self.remove_folder)
        self.folder_list_widget.currentItemChanged.connect(self.update_rule_inputs)
        self.age_spinbox.valueChanged.connect(self.save_rule_changes)
        self.pattern_lineedit.editingFinished.connect(self.save_rule_changes) # Save when focus lost or Enter pressed
        self.rule_logic_combo.currentIndexChanged.connect(self.save_rule_changes) # Connect new combo box
        self.start_button.clicked.connect(self.start_monitoring)
        self.stop_button.clicked.connect(self.stop_monitoring)
        self.settings_button.clicked.connect(self.open_settings_dialog) # Connect settings button

    def _load_initial_config(self):
        """Load existing configuration into the UI."""
        # Config is now a dict, get folders list
        folders = self.config_manager.get_monitored_folders()
        self.folder_list_widget.clear()
        for item in folders:
            path = item.get('path')
            if path:
                list_item = QListWidgetItem(path)
                self.folder_list_widget.addItem(list_item)

    def _setup_log_timer(self):
        """Set up the QTimer to check the log queue."""
        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self.check_log_queue)
        self.log_timer.start(LOG_QUEUE_CHECK_INTERVAL_MS)

    @pyqtSlot()
    def add_folder(self):
        """Open dialog to add a folder to monitor."""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Folder to Monitor")
        if dir_path:
            # Use default rules initially
            if self.config_manager.add_folder(dir_path):
                list_item = QListWidgetItem(dir_path)
                self.folder_list_widget.addItem(list_item)
                self.folder_list_widget.setCurrentItem(list_item) # Select the new item
                self.log_queue.put(f"INFO: Added folder: {dir_path}")
            else:
                 QMessageBox.warning(self, "Folder Exists", f"The folder '{dir_path}' is already being monitored.")


    @pyqtSlot()
    def remove_folder(self):
        """Remove the selected folder from monitoring."""
        current_item = self.folder_list_widget.currentItem()
        if current_item:
            path = current_item.text()
            reply = QMessageBox.question(self, "Confirm Removal",
                                         f"Are you sure you want to stop monitoring '{path}'?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                if self.config_manager.remove_folder(path):
                    row = self.folder_list_widget.row(current_item)
                    self.folder_list_widget.takeItem(row)
                    self.log_queue.put(f"INFO: Removed folder: {path}")
                    # Clear/disable inputs if no item is selected
                    if self.folder_list_widget.count() == 0:
                         self.age_spinbox.setEnabled(False)
                         self.pattern_lineedit.setEnabled(False)
                         self.rule_logic_combo.setEnabled(False) # Disable logic combo
                         self.age_spinbox.setValue(0)
                         self.pattern_lineedit.clear()
                         self.rule_logic_combo.setCurrentIndex(0) # Reset logic combo

                else:
                     QMessageBox.warning(self, "Error", f"Could not remove folder '{path}' from configuration.")
        else:
            QMessageBox.information(self, "No Selection", "Please select a folder to remove.")

    @pyqtSlot(QListWidgetItem, QListWidgetItem)
    def update_rule_inputs(self, current: QListWidgetItem, previous: QListWidgetItem):
        """Update rule input fields when folder selection changes."""
        if current:
            path = current.text()
            rule = self.config_manager.get_folder_rule(path)
            if rule:
                # Block signals temporarily to prevent save_rule_changes from firing
                self.age_spinbox.blockSignals(True)
                self.pattern_lineedit.blockSignals(True)
                self.rule_logic_combo.blockSignals(True)

                self.age_spinbox.setValue(rule.get('age_days', 0))
                self.pattern_lineedit.setText(rule.get('pattern', '*.*'))
                self.rule_logic_combo.setCurrentText(rule.get('rule_logic', 'OR'))
                self.age_spinbox.setEnabled(True)
                self.pattern_lineedit.setEnabled(True)
                self.rule_logic_combo.setEnabled(True)

                self.age_spinbox.blockSignals(False)
                self.pattern_lineedit.blockSignals(False)
                self.rule_logic_combo.blockSignals(False)
            else:
                # Should not happen if list is synced with config, but handle defensively
                self.age_spinbox.setEnabled(False)
                self.pattern_lineedit.setEnabled(False)
                self.rule_logic_combo.setEnabled(False)
                self.age_spinbox.setValue(0)
                self.pattern_lineedit.clear()
                self.rule_logic_combo.setCurrentIndex(0)
        else:
            # No item selected
            self.age_spinbox.setEnabled(False)
            self.pattern_lineedit.setEnabled(False)
            self.rule_logic_combo.setEnabled(False)
            self.age_spinbox.setValue(0)
            self.pattern_lineedit.clear()
            self.rule_logic_combo.setCurrentIndex(0)

    @pyqtSlot()
    def save_rule_changes(self):
        """Save the current rule input values for the selected folder."""
        current_item = self.folder_list_widget.currentItem()
        if current_item:
            path = current_item.text()
            age = self.age_spinbox.value()
            pattern = self.pattern_lineedit.text()
            rule_logic = self.rule_logic_combo.currentText() # Get logic from combo box
            if self.config_manager.update_folder_rule(path, age, pattern, rule_logic):
                 self.log_queue.put(f"INFO: Updated rules for {path} (Logic: {rule_logic})")
            else:
                 # Should not happen if item exists
                 self.log_queue.put(f"ERROR: Failed to update rules for {path} (not found in config?)")

    @pyqtSlot()
    def open_settings_dialog(self):
        """Open the settings dialog window."""
        dialog = SettingsDialog(self.config_manager, self) # Pass config manager and parent
        dialog.exec() # Show the dialog modally

    @pyqtSlot()
    def start_monitoring(self):
        """Start the background monitoring worker thread."""
        if self.monitoring_worker and self.monitoring_worker.is_alive():
            self.log_queue.put("INFO: Monitoring is already running.")
            return

        self.log_queue.put("INFO: Starting monitoring...")
        # Fetch the check interval from settings
        check_interval_s = self.config_manager.get_setting("check_interval_seconds", 3600) # Default 1hr
        # Pass the current config manager, queue, and check interval
        self.monitoring_worker = MonitoringWorker(
            self.config_manager,
            self.log_queue,
            check_interval=check_interval_s
        )
        self.monitoring_worker.start()

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        # Status label will be updated via queue message from worker

    @pyqtSlot()
    def stop_monitoring(self):
        """Stop the background monitoring worker thread."""
        if self.monitoring_worker and self.monitoring_worker.is_alive():
            self.log_queue.put("INFO: Stopping monitoring...")
            self.monitoring_worker.stop()
            # Wait briefly for the thread to potentially finish its current cycle and log stop message
            # A more robust solution might involve joining with a timeout or signals
            # self.monitoring_worker.join(timeout=1.0)
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            # Status label will be updated via queue message from worker
        else:
            self.log_queue.put("INFO: Monitoring is not currently running.")
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.status_label.setText("Stopped") # Ensure UI consistency


    @pyqtSlot()
    def check_log_queue(self):
        """Check the queue for messages from the worker thread and update UI."""
        try:
            while True: # Process all messages currently in queue
                message = self.log_queue.get_nowait()
                if message.startswith("STATUS:"):
                    self.worker_status = message.split(":", 1)[1].strip()
                    self.status_label.setText(self.worker_status)
                    # Update button states based on reported status
                    if self.worker_status == "Running":
                        self.start_button.setEnabled(False)
                        self.stop_button.setEnabled(True)
                    else: # Stopped or Error
                        self.start_button.setEnabled(True)
                        self.stop_button.setEnabled(False)
                        # If worker stopped unexpectedly, reflect this
                        if self.monitoring_worker and not self.monitoring_worker.is_alive() and self.worker_status != "Stopped":
                             self.status_label.setText("Stopped (Unexpectedly)")


                elif message.startswith("ERROR:"):
                    self.log_view.append(f'<font color="red">{message}</font>')
                elif message.startswith("WARNING:"):
                     self.log_view.append(f'<font color="orange">{message}</font>')
                else: # INFO or other
                    self.log_view.append(message)

                # Auto-scroll to bottom
                scroll_bar = self.log_view.verticalScrollBar()
                if scroll_bar: # Add check to satisfy type checker and for safety
                    scroll_bar.setValue(scroll_bar.maximum())

        except queue.Empty:
            # No messages left in the queue
            pass
        except Exception as e:
             # Avoid crashing the UI thread if there's an issue processing logs
             print(f"Error processing log queue: {e}", file=sys.stderr)
             self.log_view.append(f'<font color="red">ERROR: UI failed to process log message: {e}</font>')

        # Also check if thread died unexpectedly without sending STATUS: Stopped
        if self.monitoring_worker and not self.monitoring_worker.is_alive() and self.worker_status == "Running":
             self.log_queue.put("STATUS: Stopped (Unexpectedly)")


    def closeEvent(self, event):
        """Handle the window close event (hide instead of quit)."""
        event.ignore()
        self.hide()
        # Optionally show a tray message
        # if self.parent(): # Check if called from main app context with tray
        #     self.parent().tray_icon.showMessage(
        #         "AutoTidy",
        #         "Application is still running in the system tray.",
        #         QSystemTrayIcon.Information,
        #         2000
        #     )

    def force_show(self):
        """Ensure the window is visible and brought to the front."""
        self.show()
        self.activateWindow()
        self.raise_()
