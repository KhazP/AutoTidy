import sys
import queue
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QLineEdit,
    QSpinBox, QLabel, QTextEdit, QFileDialog, QMessageBox, QListWidgetItem, QComboBox, QCheckBox,
    QSystemTrayIcon # Added for type hinting
)
from PyQt6.QtCore import QTimer, Qt, pyqtSlot, QCoreApplication

from config_manager import ConfigManager
from ui_rule_editor_dialog import RuleEditorDialog # Import the new RuleEditorDialog
from worker import MonitoringWorker
from ui_settings_dialog import SettingsDialog
from ui_history_viewer_dialog import HistoryViewerDialog # Import History Viewer
from history_manager import HistoryManager # Import HistoryManager
from undo_manager import UndoManager # Added for Undo functionality
from ui_undo_dialog import UndoDialog # Added for Undo functionality

LOG_QUEUE_CHECK_INTERVAL_MS = 250

class ConfigWindow(QWidget):
    """Main configuration window for AutoTidy."""

    def __init__(self, config_manager: ConfigManager, log_queue: queue.Queue, tray_icon: QSystemTrayIcon): # Added tray_icon
        super().__init__()
        self.config_manager = config_manager
        self.log_queue = log_queue
        self.tray_icon = tray_icon # Store tray_icon
        self.history_manager = HistoryManager(self.config_manager) # Instantiate HistoryManager
        self.undo_manager = UndoManager(self.config_manager) # Instantiate UndoManager
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

        self.view_history_button = QPushButton("View Action History / Undo") # New Undo button
        top_controls_layout.addWidget(self.view_history_button) # Add new button to layout

        self.settings_button = QPushButton("Settings")
        top_controls_layout.addWidget(self.settings_button)
        main_layout.addLayout(top_controls_layout)

        # --- Folder List ---
        main_layout.addWidget(QLabel("Monitored Folders:"))
        self.folder_list_widget = QListWidget()
        main_layout.addWidget(self.folder_list_widget)

        # --- Rule Editor ---
        # This entire section including the QHBoxLayout "rule_layout" and its widgets
        # (age_spinbox, pattern_lineedit, useRegexCheckbox, rule_logic_combo, actionComboBox)
        # is being removed and replaced by the RuleEditorDialog.
        # The self.edit_rule_button is now added below the folder list.

        # --- Edit Rule Button ---
        self.edit_rule_button = QPushButton("Edit Rule for Selected Folder")
        self.edit_rule_button.setEnabled(False) # Disabled until a folder is selected
        main_layout.addWidget(self.edit_rule_button)

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
        self.edit_rule_button.clicked.connect(self.open_rule_editor_dialog) # Activated this connection
        # Connections for old inline rule editor are removed:
        # self.age_spinbox.valueChanged.connect(self.save_rule_changes)
        # self.pattern_lineedit.editingFinished.connect(self.save_rule_changes)
        # self.useRegexCheckbox.stateChanged.connect(self.save_rule_changes)
        # self.rule_logic_combo.currentIndexChanged.connect(self.save_rule_changes)
        # self.actionComboBox.currentIndexChanged.connect(self.save_rule_changes)
        self.start_button.clicked.connect(self.start_monitoring)
        self.stop_button.clicked.connect(self.stop_monitoring)
        self.settings_button.clicked.connect(self.open_settings_dialog)
        self.viewHistoryButton.clicked.connect(self.open_history_viewer) # Connect View History button
        self.view_history_button.clicked.connect(self.open_undo_dialog) # Connect new Undo button

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
                    # Disable "Edit Rule" button if no folder is selected (and no other item is auto-selected)
                    if self.folder_list_widget.currentItem() is None: # More robust check
                        self.edit_rule_button.setEnabled(False)
                else:
                     QMessageBox.warning(self, "Error", f"Could not remove folder '{path}' from configuration.")
        else:
            QMessageBox.information(self, "No Selection", "Please select a folder to remove.")

    @pyqtSlot(QListWidgetItem, QListWidgetItem)
    def update_rule_inputs(self, current: QListWidgetItem, previous: QListWidgetItem):
        """Enable/disable the 'Edit Rule' button based on folder selection."""
        if current:
            self.edit_rule_button.setEnabled(True)
        else:
            self.edit_rule_button.setEnabled(False)

    # save_rule_changes method is entirely removed. Rule saving is now handled by RuleEditorDialog.

    @pyqtSlot()
    def open_rule_editor_dialog(self):
        """Open the Rule Editor dialog for the selected folder."""
        current_item = self.folder_list_widget.currentItem()
        if not current_item:
            QMessageBox.information(self, "No Selection", "Please select a folder to edit its rule.")
            return

        path = current_item.text()
        # Get the rule. It's possible get_folder_rule returns just the rule part,
        # ensure 'path' is part of the dict for the dialog.
        rule_data = self.config_manager.get_folder_rule(path)

        if rule_data is None: # Should ideally not happen if folder exists
            self.log_queue.put(f"WARNING: No rule found for {path} when opening editor. Creating default for editor.")
            # This is a new folder or inconsistent state, provide a default rule structure
            # The RuleEditorDialog expects 'path' in current_rule_data
            rule_data = {'path': path, 'age_days': 0, 'pattern': '*.*', 'rule_logic': 'OR', 'use_regex': False, 'action': 'move'}
        elif 'path' not in rule_data:
            rule_data['path'] = path # Ensure path is included

        dialog = RuleEditorDialog(current_rule_data=rule_data, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_rule_data = dialog.get_rule_data()
            # new_rule_data contains 'path' which is the key for update_folder_rule
            if self.config_manager.update_folder_rule(
                path=new_rule_data['path'], # Use path from new_rule_data as it's the key
                age_days=new_rule_data['age_days'],
                pattern=new_rule_data['pattern'],
                rule_logic=new_rule_data['rule_logic'],
                use_regex=new_rule_data['use_regex'],
                action=new_rule_data['action']
            ):
                self.log_queue.put(f"INFO: Updated rules for {new_rule_data['path']} "
                                   f"(Action: {new_rule_data['action']}, Logic: {new_rule_data['rule_logic']}, "
                                   f"Pattern: '{new_rule_data['pattern']}', Regex: {new_rule_data['use_regex']}, "
                                   f"Age: {new_rule_data['age_days']})")
            else:
                # This usually means the path wasn't found in the config, which is unlikely if we just got it.
                self.log_queue.put(f"ERROR: Failed to update rules for {new_rule_data['path']} via RuleEditorDialog.")
                QMessageBox.critical(self, "Error", f"Failed to update rule for {new_rule_data['path']}.")

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

    @pyqtSlot()
    def open_undo_dialog(self):
        """Open the undo/history dialog window."""
        dialog = UndoDialog(self.undo_manager, self.config_manager, self)
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
            self.log_queue,
            self.tray_icon # Pass tray_icon to worker
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
