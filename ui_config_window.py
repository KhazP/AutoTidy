import sys
import queue
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QLineEdit,
    QSpinBox, QLabel, QTextEdit, QFileDialog, QMessageBox, QListWidgetItem, QComboBox, QCheckBox
)
from PyQt6.QtCore import QTimer, Qt, pyqtSlot

from config_manager import ConfigManager
from worker import MonitoringWorker
from ui_settings_dialog import SettingsDialog
from ui_history_viewer_dialog import HistoryViewerDialog # Import History Viewer
from history_manager import HistoryManager # Import HistoryManager

LOG_QUEUE_CHECK_INTERVAL_MS = 250

class ConfigWindow(QWidget):
    """Main configuration window for AutoTidy."""

    def __init__(self, config_manager: ConfigManager, log_queue: queue.Queue):
        super().__init__()
        self.config_manager = config_manager
        self.log_queue = log_queue
        self.history_manager = HistoryManager(self.config_manager) # Instantiate HistoryManager
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

        self.viewHistoryButton = QPushButton("View History") # Add View History button
        top_controls_layout.addWidget(self.viewHistoryButton)

        self.settings_button = QPushButton("Settings")
        top_controls_layout.addWidget(self.settings_button)
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

        # Add Use Regex Checkbox
        self.useRegexCheckbox = QCheckBox("Use Regular Expression")
        self.useRegexCheckbox.setEnabled(False)
        rule_layout.addWidget(self.useRegexCheckbox)

        rule_layout.addWidget(QLabel("Logic:"))
        self.rule_logic_combo = QComboBox()
        self.rule_logic_combo.addItems(["OR", "AND"])
        self.rule_logic_combo.setEnabled(False)
        rule_layout.addWidget(self.rule_logic_combo)

        # Action ComboBox (Move/Copy/Delete)
        rule_layout.addWidget(QLabel("Action:"))
        self.actionComboBox = QComboBox()
        self.actionComboBox.addItems(["Move", "Copy", "Delete to Trash", "Delete Permanently"])
        self.actionComboBox.setEnabled(False)
        rule_layout.addWidget(self.actionComboBox)

        main_layout.addLayout(rule_layout)

        # --- Status and Logs ---
        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel("Status:"))
        self.status_label = QLabel("Stopped")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        self.start_button = QPushButton("Start Monitoring") # Text will be updated by _update_ui_for_status_and_mode
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
        self.useRegexCheckbox.stateChanged.connect(self.save_rule_changes) # Connect checkbox
        self.rule_logic_combo.currentIndexChanged.connect(self.save_rule_changes) # Connect new combo box
        self.actionComboBox.currentIndexChanged.connect(self.save_rule_changes) # Connect action combo box
        self.start_button.clicked.connect(self.start_monitoring)
        self.stop_button.clicked.connect(self.stop_monitoring)
        self.settings_button.clicked.connect(self.open_settings_dialog)
        self.viewHistoryButton.clicked.connect(self.open_history_viewer) # Connect View History button

        self._update_ui_for_status_and_mode() # Initial UI update

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
                         self.useRegexCheckbox.setEnabled(False) # Disable regex checkbox
                         self.actionComboBox.setEnabled(False) # Disable action combo box
                         self.age_spinbox.setValue(0)
                         self.pattern_lineedit.clear()
                         self.useRegexCheckbox.setChecked(False) # Uncheck regex checkbox
                         self.rule_logic_combo.setCurrentIndex(0) # Reset logic combo
                         self.actionComboBox.setCurrentIndex(0) # Reset action combo box

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
                self.useRegexCheckbox.blockSignals(True)
                self.actionComboBox.blockSignals(True) # Block actionComboBox signals

                self.age_spinbox.setValue(rule.get('age_days', 0))
                self.pattern_lineedit.setText(rule.get('pattern', '*.*'))
                self.rule_logic_combo.setCurrentText(rule.get('rule_logic', 'OR'))
                self.useRegexCheckbox.setChecked(rule.get('use_regex', False)) # Load use_regex

                action_value = rule.get('action', 'move')
                action_display_map = {
                    "move": "Move",
                    "copy": "Copy",
                    "delete_to_trash": "Delete to Trash",
                    "delete_permanently": "Delete Permanently"
                }
                self.actionComboBox.setCurrentText(action_display_map.get(action_value, "Move"))

                self.age_spinbox.setEnabled(True)
                self.pattern_lineedit.setEnabled(True)
                self.rule_logic_combo.setEnabled(True)
                self.useRegexCheckbox.setEnabled(True) # Enable checkbox
                self.actionComboBox.setEnabled(True) # Enable actionComboBox

                self.age_spinbox.blockSignals(False)
                self.pattern_lineedit.blockSignals(False)
                self.rule_logic_combo.blockSignals(False)
                self.useRegexCheckbox.blockSignals(False)
                self.actionComboBox.blockSignals(False) # Unblock actionComboBox signals
            else:
                # Should not happen if list is synced with config, but handle defensively
                self.age_spinbox.setEnabled(False)
                self.pattern_lineedit.setEnabled(False)
                self.rule_logic_combo.setEnabled(False)
                self.useRegexCheckbox.setEnabled(False) # Disable checkbox
                self.actionComboBox.setEnabled(False) # Disable actionComboBox
                self.age_spinbox.setValue(0)
                self.pattern_lineedit.clear()
                self.rule_logic_combo.setCurrentIndex(0)
                self.useRegexCheckbox.setChecked(False) # Uncheck checkbox
                self.actionComboBox.setCurrentIndex(0) # Reset actionComboBox
        else:
            # No item selected
            self.age_spinbox.setEnabled(False)
            self.pattern_lineedit.setEnabled(False)
            self.rule_logic_combo.setEnabled(False)
            self.useRegexCheckbox.setEnabled(False) # Disable checkbox
            self.actionComboBox.setEnabled(False) # Disable actionComboBox
            self.age_spinbox.setValue(0)
            self.pattern_lineedit.clear()
            self.rule_logic_combo.setCurrentIndex(0)
            self.useRegexCheckbox.setChecked(False) # Uncheck checkbox
            self.actionComboBox.setCurrentIndex(0) # Reset actionComboBox

    @pyqtSlot()
    def save_rule_changes(self):
        """Save the current rule input values for the selected folder."""
        current_item = self.folder_list_widget.currentItem()
        if current_item:
            path = current_item.text()
            age = self.age_spinbox.value()
            pattern = self.pattern_lineedit.text()
            rule_logic = self.rule_logic_combo.currentText()
            use_regex = self.useRegexCheckbox.isChecked()

            action_text = self.actionComboBox.currentText()
            action_map = {
                "Move": "move",
                "Copy": "copy",
                "Delete to Trash": "delete_to_trash",
                "Delete Permanently": "delete_permanently"
            }
            action_value = action_map.get(action_text, "move")

            # Show warning for permanent delete
            if action_value == "delete_permanently":
                # Check if this is a new selection or already saved.
                # This check prevents the warning from showing every time save_rule_changes is called
                # if the user has already confirmed it (e.g. by changing another field).
                # A more robust way would be to only show this if currentText() just changed to "Delete Permanently".
                # For now, we check against the config to see if it was already "delete_permanently".
                # This means the warning appears when user selects it, and if they then change another rule aspect
                # while "Delete Permanently" is still selected, it might show again.
                # A better UX would be to connect this warning to the currentIndexChanged signal specifically for this option.
                # However, sticking to the prompt's placement in save_rule_changes:
                current_rule = self.config_manager.get_folder_rule(path)
                if not current_rule or current_rule.get('action') != "delete_permanently":
                    QMessageBox.warning(self, "Permanent Delete Warning",
                                        "Warning: 'Delete Permanently' will erase files irreversibly. "
                                        "These files cannot be recovered from the Recycle Bin. "
                                        "Ensure this rule is configured carefully.",
                                        QMessageBox.StandardButton.Ok)

            if self.config_manager.update_folder_rule(path, age, pattern, rule_logic, use_regex, action_value): # Pass action_value
                 self.log_queue.put(f"INFO: Updated rules for {path} (Logic: {rule_logic}, Regex: {use_regex}, Action: {action_value})")
            else:
                 # Should not happen if item exists
                 self.log_queue.put(f"ERROR: Failed to update rules for {path} (not found in config?)")

    @pyqtSlot()
    def open_settings_dialog(self):
        """Open the settings dialog window."""
        dialog = SettingsDialog(self.config_manager, self) # Pass config manager and parent
        dialog.exec() # Show the dialog modally
        self._update_ui_for_status_and_mode() # Refresh UI after settings change

    @pyqtSlot()
    def open_history_viewer(self):
        """Opens the history viewer dialog."""
        # Pass config_manager and history_manager
        dialog = HistoryViewerDialog(self.config_manager, self.history_manager, self)
        dialog.exec()

    def _update_ui_for_status_and_mode(self):
        """Updates button texts and status label based on worker status and dry run mode."""
        dry_run_active = self.config_manager.get_dry_run_mode()
        is_running = self.worker_status == "Running"

        if dry_run_active:
            self.start_button.setText("Start Dry Run")
            if is_running:
                self.status_label.setText("Dry Run Active")
                self.start_button.setEnabled(False)
                self.stop_button.setEnabled(True)
            else: # Stopped or Error
                # Preserve error message if worker_status indicates an error
                self.status_label.setText(self.worker_status if "Error" in self.worker_status else "Idle (Dry Run Mode)")
                self.start_button.setEnabled(True)
                self.stop_button.setEnabled(False)
        else:
            self.start_button.setText("Start Monitoring")
            if is_running:
                self.status_label.setText("Running") # Or self.worker_status if it can be "Running (Dry Run)"
                self.start_button.setEnabled(False)
                self.stop_button.setEnabled(True)
            else: # Stopped or Error
                self.status_label.setText(self.worker_status)
                self.start_button.setEnabled(True)
                self.stop_button.setEnabled(False)


    @pyqtSlot()
    def start_monitoring(self):
        """Start the background monitoring worker thread."""
        if self.monitoring_worker and self.monitoring_worker.is_alive():
            dry_run_active = self.config_manager.get_dry_run_mode()
            self.log_queue.put(f"INFO: {'Dry run' if dry_run_active else 'Monitoring'} is already running.")
            return

        dry_run_active = self.config_manager.get_dry_run_mode()
        self.log_queue.put(f"INFO: Starting {'dry run' if dry_run_active else 'monitoring'}...")

        self.monitoring_worker = MonitoringWorker(
            self.config_manager,
            self.log_queue
        )
        self.monitoring_worker.start()
        # self.worker_status will be updated by message from worker, then _update_ui_for_status_and_mode
        # For immediate feedback, we can anticipate:
        # self.worker_status = "Running" # Anticipate
        # self._update_ui_for_status_and_mode()
        # However, it's better to let the worker signal its actual start.

    @pyqtSlot()
    def stop_monitoring(self):
        """Stop the background monitoring worker thread."""
        if self.monitoring_worker and self.monitoring_worker.is_alive():
            self.log_queue.put("INFO: Stopping monitoring...")
            self.monitoring_worker.stop()
            # self.monitoring_worker.join(timeout=1.0) # Avoid long UI block
            # self.worker_status = "Stopped" # Anticipate
            # self._update_ui_for_status_and_mode()
            # Worker will send "STATUS: Stopped"
        else:
            self.log_queue.put("INFO: Monitoring is not currently running.")
            # self.worker_status = "Stopped" # Ensure consistency
            # self._update_ui_for_status_and_mode()


    @pyqtSlot()
    def check_log_queue(self):
        """Check the queue for messages from the worker thread and update UI."""
        try:
            while True: # Process all messages currently in queue
                message = self.log_queue.get_nowait()
                if message.startswith("STATUS:"):
                    self.worker_status = message.split(":", 1)[1].strip()
                    # self.status_label.setText(self.worker_status) # Delegated
                    self._update_ui_for_status_and_mode() # Update all UI based on new status
                    # # Update button states based on reported status # Delegated
                    # if self.worker_status == "Running":
                    #     self.start_button.setEnabled(False)
                    #     self.stop_button.setEnabled(True)
                    # else: # Stopped or Error
                    #     self.start_button.setEnabled(True)
                    #     self.stop_button.setEnabled(False)
                    #     # If worker stopped unexpectedly, reflect this
                    #     if self.monitoring_worker and not self.monitoring_worker.is_alive() and self.worker_status != "Stopped":
                    #          self.status_label.setText("Stopped (Unexpectedly)") # This part can be refined in _update_ui


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
