import sys
import queue
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QLineEdit,
    QSpinBox, QLabel, QTextEdit, QFileDialog, QMessageBox, QListWidgetItem, QComboBox, QCheckBox,
    QApplication, QMenu
)
from PyQt6.QtGui import QKeySequence, QAction # Import QAction
from PyQt6.QtCore import QTimer, Qt, pyqtSlot

from config_manager import ConfigManager
from worker import MonitoringWorker
from ui_settings_dialog import SettingsDialog
from constants import RULE_TEMPLATES # Import RULE_TEMPLATES


from undo_manager import UndoManager # Added for Undo functionality
from ui_undo_dialog import UndoDialog # Added for Undo functionality

LOG_QUEUE_CHECK_INTERVAL_MS = 250

class ConfigWindow(QWidget):
    """Main configuration window for AutoTidy."""

    def __init__(self, config_manager: ConfigManager, log_queue: queue.Queue):
        super().__init__()
        self.config_manager = config_manager
        self.log_queue = log_queue
        self.undo_manager = UndoManager(self.config_manager) # Instantiate UndoManager
        self.monitoring_worker: MonitoringWorker | None = None
        self.worker_status = "Stopped" # Track worker status

        self.setWindowTitle("AutoTidy Configuration")
        self.setGeometry(200, 200, 600, 450) # x, y, width, height

        self._init_ui()
        self._load_initial_config()
        self._setup_log_timer()
        self._setup_shortcuts() # Call new method

    def _init_ui(self):
        """Initialize UI elements and layout."""
        main_layout = QVBoxLayout(self)

        # --- Top Controls ---
        top_controls_layout = QHBoxLayout()
        self.add_folder_button = QPushButton("&Add Folder") # Added & for mnemonic
        self.add_folder_button.setToolTip("Add a new folder to monitor (Ctrl+O)")
        
        self.apply_template_button = QPushButton("Apply &Template") # New button
        self.apply_template_button.setToolTip("Apply a predefined rule template")
        self.apply_template_button.clicked.connect(self.show_template_menu) # Connect to show menu

        self.remove_folder_button = QPushButton("&Remove Selected") # Added &
        self.remove_folder_button.setToolTip("Remove the selected folder from monitoring (Del)")
        top_controls_layout.addWidget(self.add_folder_button)
        top_controls_layout.addWidget(self.apply_template_button) # Add new button
        top_controls_layout.addWidget(self.remove_folder_button)
        top_controls_layout.addStretch()

        self.view_history_button = QPushButton("View Action &History / Undo") # Added &
        self.view_history_button.setToolTip("Open the action history and undo window (Ctrl+H)")
        top_controls_layout.addWidget(self.view_history_button) # Add new button to layout

        self.settings_button = QPushButton("&Settings") # Added &
        self.settings_button.setToolTip("Open application settings (Ctrl+,)")
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
        self.age_spinbox.setToolTip("Minimum age in days for a file to be considered for action.")
        rule_layout.addWidget(self.age_spinbox)

        rule_layout.addWidget(QLabel("Filename Pattern:"))
        self.pattern_lineedit = QLineEdit()
        self.pattern_lineedit.setPlaceholderText("*.*")
        self.pattern_lineedit.setEnabled(False)
        self.pattern_lineedit.setToolTip("Filename pattern to match (e.g., *.tmp, document_*.docx). Wildcards supported.")
        rule_layout.addWidget(self.pattern_lineedit)

        # Add Use Regex Checkbox
        self.useRegexCheckbox = QCheckBox("Use Regular E&xpression") # Added &
        self.useRegexCheckbox.setEnabled(False)
        self.useRegexCheckbox.setToolTip("Check to use full regular expressions for pattern matching.")
        rule_layout.addWidget(self.useRegexCheckbox)

        rule_layout.addWidget(QLabel("Logic:"))
        self.rule_logic_combo = QComboBox()
        self.rule_logic_combo.addItems(["OR", "AND"])
        self.rule_logic_combo.setEnabled(False)
        self.rule_logic_combo.setToolTip("Logic to combine age and pattern rules (OR: either matches, AND: both must match).")
        rule_layout.addWidget(self.rule_logic_combo)

        # Action ComboBox (Move/Copy/Delete)
        rule_layout.addWidget(QLabel("Action:"))
        self.actionComboBox = QComboBox()
        self.actionComboBox.addItems(["Move", "Copy", "Delete to Trash", "Delete Permanently"])
        self.actionComboBox.setEnabled(False)
        self.actionComboBox.setToolTip("Action to perform on matching files.")
        rule_layout.addWidget(self.actionComboBox)

        main_layout.addLayout(rule_layout)

        # --- Exclusion Rules Editor ---
        exclusion_layout = QHBoxLayout()
        exclusion_editor_layout = QVBoxLayout()
        exclusion_editor_layout.addWidget(QLabel("Exclusion Patterns for selected folder (one per line):"))
        self.exclusion_list_widget = QListWidget()
        self.exclusion_list_widget.setToolTip("Files/folders matching these patterns will be ignored. Wildcards supported.")
        self.exclusion_list_widget.setEnabled(False)
        exclusion_editor_layout.addWidget(self.exclusion_list_widget)

        exclusion_buttons_layout = QHBoxLayout()
        self.add_exclusion_button = QPushButton("Add E&xclusion")
        self.add_exclusion_button.setToolTip("Add a new exclusion pattern.")
        self.add_exclusion_button.setEnabled(False)
        self.remove_exclusion_button = QPushButton("Remove Selected E&xclusion")
        self.remove_exclusion_button.setToolTip("Remove the selected exclusion pattern.")
        self.remove_exclusion_button.setEnabled(False)
        self.exclusion_help_button = QPushButton("Exclusion &Help") # New Help Button
        self.exclusion_help_button.setToolTip("Show help and examples for exclusion patterns.")
        # self.exclusion_help_button.setEnabled(False) # Enable it when a folder is selected, like other exclusion buttons
        exclusion_buttons_layout.addWidget(self.add_exclusion_button)
        exclusion_buttons_layout.addWidget(self.remove_exclusion_button)
        exclusion_buttons_layout.addWidget(self.exclusion_help_button) # Add to layout
        exclusion_editor_layout.addLayout(exclusion_buttons_layout)

        exclusion_layout.addLayout(exclusion_editor_layout)
        main_layout.addLayout(exclusion_layout)

        # --- Status and Logs ---
        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel("Status:"))
        self.status_label = QLabel("Stopped")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        self.start_button = QPushButton("&Start Monitoring") # Text will be updated, added &
        self.start_button.setToolTip("Start the monitoring or dry run process (Ctrl+S)")
        self.stop_button = QPushButton("S&top Monitoring") # Added &
        self.stop_button.setToolTip("Stop the currently running process (Ctrl+T)")
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
        # self.apply_template_button.clicked.connect(self.apply_template) # Will be handled by QMenu
        self.start_button.clicked.connect(self.start_monitoring)
        self.stop_button.clicked.connect(self.stop_monitoring)
        self.settings_button.clicked.connect(self.open_settings_dialog)
        self.view_history_button.clicked.connect(self.open_undo_dialog) # Connect new Undo button
        self.add_exclusion_button.clicked.connect(self.add_exclusion_pattern) # Renamed for clarity
        self.remove_exclusion_button.clicked.connect(self.remove_selected_exclusion_pattern) # Renamed for clarity
        self.exclusion_help_button.clicked.connect(self.show_exclusion_pattern_help) # Renamed for clarity
        self.exclusion_list_widget.itemChanged.connect(self.save_exclusion_list_changes) # Save when an item is edited

        self._update_ui_for_status_and_mode() # Initial UI update
        self._set_initial_focus() # Set initial focus

    def _set_initial_focus(self):
        """Sets the initial focus to a sensible widget."""
        self.add_folder_button.setFocus()

    def _setup_shortcuts(self):
        """Setup keyboard shortcuts for common actions."""
        self.add_folder_button.setShortcut(QKeySequence("Ctrl+O"))
        # Remove folder shortcut handled by keyPressEvent on list widget
        self.view_history_button.setShortcut(QKeySequence("Ctrl+H"))
        self.settings_button.setShortcut(QKeySequence("Ctrl+,")) # Comma for settings often
        self.start_button.setShortcut(QKeySequence("Ctrl+S"))
        self.stop_button.setShortcut(QKeySequence("Ctrl+T"))

        # Shortcut for closing/hiding the window
        close_shortcut = QKeySequence(Qt.Key.Key_Escape)
        self.addAction(self.create_action("Hide Window", self.close, close_shortcut))

    def create_action(self, text, slot, shortcut=None):
        """Helper to create a QAction for shortcuts not tied to a button."""
        from PyQt6.QtGui import QAction # Local import
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(shortcut)
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut) # Ensure it works window-wide
        return action

    def keyPressEvent(self, event):
        """Handle key presses for actions like deleting from list."""
        if event.key() == Qt.Key.Key_Delete and self.folder_list_widget.hasFocus() and self.folder_list_widget.currentItem():
            self.remove_folder()
        elif event.key() == Qt.Key.Key_Escape:
            self.close() # Hide on Escape
        else:
            super().keyPressEvent(event)
            
    # Ensure the window can be closed by the Escape key even if a child widget has focus
    # This is often handled by QDialogs automatically, but for QWidget, we might need this.
    # The addAction with WindowShortcut context for Escape should generally cover this.

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
                         self.exclusion_list_widget.clear() # Clear exclusions
                         self.exclusion_list_widget.setEnabled(False)
                         self.add_exclusion_button.setEnabled(False)
                         self.remove_exclusion_button.setEnabled(False)
                         self.exclusion_help_button.setEnabled(False) # Disable help button
                         # Explicitly call update_rule_inputs with None when list is empty
                         self.update_rule_inputs(None, None) 
                else:
                     QMessageBox.warning(self, "Error", f"Could not remove folder '{path}' from configuration.")
        else:
            QMessageBox.information(self, "No Selection", "Please select a folder to remove.")

    @pyqtSlot(QListWidgetItem, QListWidgetItem)
    def update_rule_inputs(self, current: QListWidgetItem | None, previous: QListWidgetItem | None): # Allow None
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
                self.exclusion_list_widget.blockSignals(True) # Block exclusion list signals

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

                self.exclusion_list_widget.clear()
                exclusions = rule.get('exclusions', [])
                for exclusion_pattern in exclusions:
                    item = QListWidgetItem(exclusion_pattern)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable) # Make item editable
                    self.exclusion_list_widget.addItem(item)

                self.age_spinbox.setEnabled(True)
                self.pattern_lineedit.setEnabled(True)
                self.rule_logic_combo.setEnabled(True)
                self.useRegexCheckbox.setEnabled(True) # Enable checkbox
                self.actionComboBox.setEnabled(True) # Enable actionComboBox
                self.exclusion_list_widget.setEnabled(True)
                self.add_exclusion_button.setEnabled(True)
                self.remove_exclusion_button.setEnabled(True)
                self.exclusion_help_button.setEnabled(True) # Enable help button


                self.age_spinbox.blockSignals(False)
                self.pattern_lineedit.blockSignals(False)
                self.rule_logic_combo.blockSignals(False)
                self.useRegexCheckbox.blockSignals(False)
                self.actionComboBox.blockSignals(False) # Unblock actionComboBox signals
                self.exclusion_list_widget.blockSignals(False) # Unblock exclusion list signals
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
                self.exclusion_list_widget.clear() # Clear exclusions
                self.exclusion_list_widget.setEnabled(False)
                self.add_exclusion_button.setEnabled(False)
                self.remove_exclusion_button.setEnabled(False)
                self.exclusion_help_button.setEnabled(False) # Disable help button
        else:
            # No item selected, disable all rule inputs
            self.age_spinbox.setEnabled(False)
            self.pattern_lineedit.setEnabled(False)
            self.rule_logic_combo.setEnabled(False)
            self.useRegexCheckbox.setEnabled(False) # Disable checkbox
            self.actionComboBox.setEnabled(False) # Disable actionComboBox
            self.age_spinbox.setValue(0)
            self.pattern_lineedit.clear()
            self.rule_logic_combo.setCurrentIndex(0)
            self.useRegexCheckbox.setChecked(False)
            self.actionComboBox.setCurrentIndex(0) # Reset actionComboBox
            self.exclusion_list_widget.clear() # Clear exclusions
            self.exclusion_list_widget.setEnabled(False)
            self.add_exclusion_button.setEnabled(False)
            self.remove_exclusion_button.setEnabled(False)
            self.exclusion_help_button.setEnabled(False) # Disable help button


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

            exclusions = []
            for i in range(self.exclusion_list_widget.count()):
                item = self.exclusion_list_widget.item(i)
                if item: # Add check for item existence
                    exclusions.append(item.text())

            if self.config_manager.update_folder_rule(
                path,
                age,
                pattern,
                rule_logic,
                use_regex,
                action_value,
                exclusions # Pass exclusions
            ):
                self.log_queue.put(f"INFO: Updated rules for {path}")
            else:
                # Should not happen if item exists
                self.log_queue.put(f"ERROR: Failed to update rules for {path} (not found in config?)")

    @pyqtSlot()
    def open_settings_dialog(self):
        """Open the settings dialog window."""
        dialog = SettingsDialog(self.config_manager, self) # Pass config manager and parent
        dialog.exec() # Show the dialog modally        self._update_ui_for_status_and_mode() # Refresh UI after settings change

    @pyqtSlot()
    def open_undo_dialog(self):
        """Open the undo/history dialog window."""
        dialog = UndoDialog(self.undo_manager, self.config_manager, self)
        dialog.exec()

    def _update_ui_for_status_and_mode(self):
        """Update UI elements based on worker status and dry run mode."""
        is_running = self.worker_status == "Running" or self.worker_status == "Dry Run Active"
        is_dry_run_mode = self.config_manager.get_setting('dry_run_mode', False)

        self.start_button.setText("&Start Dry Run" if is_dry_run_mode and not is_running else "&Start Monitoring")
        self.start_button.setToolTip(
            "Preview actions without making changes (Dry Run)" if is_dry_run_mode and not is_running
            else "Start the monitoring process (Ctrl+S)"
        )
        self.start_button.setEnabled(not is_running)
        self.stop_button.setEnabled(is_running)

        # Disable folder/rule editing when worker is active
        self.add_folder_button.setEnabled(not is_running)
        self.apply_template_button.setEnabled(not is_running) # Enable/disable template button
        self.remove_folder_button.setEnabled(not is_running)
        self.settings_button.setEnabled(not is_running) # Also disable settings when running

        # Enable/disable rule inputs based on selection and running state
        current_item = self.folder_list_widget.currentItem()
        can_edit_rules = current_item is not None and not is_running

        self.age_spinbox.setEnabled(can_edit_rules)
        self.pattern_lineedit.setEnabled(can_edit_rules)
        self.rule_logic_combo.setEnabled(can_edit_rules)
        self.useRegexCheckbox.setEnabled(can_edit_rules)
        self.actionComboBox.setEnabled(can_edit_rules)
        self.exclusion_list_widget.setEnabled(can_edit_rules)
        self.add_exclusion_button.setEnabled(can_edit_rules)
        self.remove_exclusion_button.setEnabled(can_edit_rules)
        self.exclusion_help_button.setEnabled(can_edit_rules) # Enable/disable help button


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
                elif isinstance(message, dict) and message.get("type") == "SHOW_NOTIFICATION":
                    if self.config_manager.get_setting("show_notifications", True):
                        app_instance = QApplication.instance()
                        # Check if it's an instance of our AutoTidyApp (which has the method)
                        if app_instance and hasattr(app_instance, 'show_system_notification') and callable(getattr(app_instance, 'show_system_notification')):
                            title = message.get("title", "AutoTidy")
                            body = message.get("message", "")
                            # Explicitly call, relying on the hasattr check
                            getattr(app_instance, 'show_system_notification')(title, body)
                        else:
                            print(f"DEBUG: AutoTidyApp instance not found or no show_system_notification method for: {message}", file=sys.stderr)
                    else:
                        print(f"DEBUG: Notifications disabled. Suppressed: {message.get('title')}", file=sys.stderr)
                elif isinstance(message, str): # Ensure only strings are appended directly
                    self.log_view.append(message)
                else:
                    # Handle or log unexpected message types if necessary
                    print(f"DEBUG: Received unexpected message type in log queue: {type(message)}", file=sys.stderr)

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
        """Handle the window close event."""
        # Ensure worker is stopped if running
        if self.monitoring_worker and self.monitoring_worker.is_alive():
            self.log_queue.put("INFO: Stopping monitoring due to window close...")
            if hasattr(self.monitoring_worker, 'stop') and callable(self.monitoring_worker.stop):
                self.monitoring_worker.stop()
                self.monitoring_worker.join(timeout=2) # Wait for worker to finish
                if self.monitoring_worker.is_alive():
                    self.log_queue.put("WARNING: Monitoring worker did not terminate before the window closed.")
            else:
                self.log_queue.put("ERROR: MonitoringWorker does not have a stop method.")

        # Save any pending changes (e.g., if user typed in a field and closed)
        # self.save_rule_changes() # This might be redundant if changes are saved on field edit

        self.log_timer.stop() # Stop the log timer
        self.config_manager.save_config() # Ensure config is saved
        self.log_queue.put("INFO: AutoTidy configuration window closed.")
        super().closeEvent(event)

    def show_template_menu(self):
        """Show a context menu with rule templates."""
        template_menu = QMenu(self)
        if not RULE_TEMPLATES:
            no_template_action = QAction("No templates available", self) # Create QAction
            no_template_action.setEnabled(False)
            template_menu.addAction(no_template_action) # Add QAction to menu
        else:
            for i, template_data in enumerate(RULE_TEMPLATES):
                action = QAction(template_data['name'], self) # Create QAction
                action.setToolTip(template_data.get('description', 'No description'))
                action.setData(i) # Store index of the template
                action.triggered.connect(self.apply_selected_template)
                template_menu.addAction(action) # Add QAction to menu
        
        self.apply_template_button.setMenu(template_menu) # Associate menu with button
        # Position menu below the button. Adjust x, y as needed for better positioning.
        menu_pos = self.apply_template_button.mapToGlobal(self.apply_template_button.rect().bottomLeft())
        template_menu.popup(menu_pos)


    def apply_selected_template(self):
        """Apply the rules from the selected template."""
        sender_action = self.sender() # Get the QAction that was triggered
        if isinstance(sender_action, QAction): # Check if sender is QAction
            template_index = sender_action.data()
            if template_index is not None and isinstance(template_index, int) and 0 <= template_index < len(RULE_TEMPLATES):
                template = RULE_TEMPLATES[template_index]
                template_name = template['name']
                template_rules = template.get('rules', [])

                if not template_rules:
                    QMessageBox.information(self, "No Rules in Template", f"The template '{template_name}' has no rules defined.")
                    return

                # Ask for confirmation
                reply = QMessageBox.question(self, "Apply Template",
                                             f"This will add {len(template_rules)} rule(s) from the template '{template_name}'. "
                                             f"Existing rules for these folders (if any) will be overwritten if the paths match. "
                                             f"New folders will be added if they don't exist.\n\n"
                                             f"Description: {template.get('description', 'N/A')}\n\n"
                                             "Do you want to proceed?",
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                             QMessageBox.StandardButton.No)

                if reply == QMessageBox.StandardButton.Yes:
                    folders_added_or_updated = []
                    for rule_def in template_rules:
                        folder_path = rule_def.get('folder_to_watch')
                        if not folder_path:
                            self.log_queue.put(f"WARNING: Template rule in '{template_name}' missing 'folder_to_watch'. Skipping.")
                            continue
                        
                        # Expand environment variables in paths
                        import os
                        expanded_folder_path = os.path.expandvars(folder_path)
                        expanded_dest_folder = os.path.expandvars(rule_def.get('destination_folder', ''))

                        # Check if folder already exists in list, if not, add it
                        existing_items_texts = []
                        for i in range(self.folder_list_widget.count()):
                            item = self.folder_list_widget.item(i)
                            if item: # Ensure item is not None before calling text()
                                existing_items_texts.append(item.text())
                        
                        if expanded_folder_path not in existing_items_texts:
                            if self.config_manager.add_folder(expanded_folder_path, rule_def): # Add with template rule
                                list_item = QListWidgetItem(expanded_folder_path)
                                self.folder_list_widget.addItem(list_item)
                                folders_added_or_updated.append(expanded_folder_path)
                                self.log_queue.put(f"INFO: Added folder '{expanded_folder_path}' from template '{template_name}'.")
                            else:
                                self.log_queue.put(f"INFO: Folder '{expanded_folder_path}' (from template) likely already in config, attempting to update rule.")
                        
                        action_map = {
                            "move": "move",
                            "copy": "copy",
                            "delete": "delete_to_trash", 
                            "delete_permanently": "delete_permanently"
                        }
                        
                        update_success = self.config_manager.update_folder_rule(
                            path=expanded_folder_path,
                            age_days=rule_def.get('days_older_than', 0),
                            pattern=rule_def.get('file_pattern', '*.*'),
                            rule_logic=rule_def.get('rule_logic', 'OR'), 
                            use_regex=rule_def.get('use_regex', False),   
                            action=action_map.get(rule_def.get('action', 'move').lower(), "move"),
                            exclusions=rule_def.get('exclusions', []),  
                            destination_folder=expanded_dest_folder, 
                            enabled=rule_def.get('enabled', True) 
                        )
                        if update_success:
                            if expanded_folder_path not in folders_added_or_updated: 
                                folders_added_or_updated.append(expanded_folder_path)
                            self.log_queue.put(f"INFO: Applied rule from template '{template_name}' to folder '{expanded_folder_path}'.")
                        else:
                            self.log_queue.put(f"ERROR: Failed to apply rule from template '{template_name}' to folder '{expanded_folder_path}'.")

                    if folders_added_or_updated:
                        QMessageBox.information(self, "Template Applied",
                                                f"Template '{template_name}' applied. Rules for the following folders were added/updated:\n" +
                                                "\n".join(folders_added_or_updated) +
                                                "\n\nPlease review the changes.")
                        # Refresh the UI to show the new/updated rules
                        if self.folder_list_widget.count() > 0:
                            # Try to select the last modified/added folder from the template
                            last_affected_folder = folders_added_or_updated[-1]
                            items = self.folder_list_widget.findItems(last_affected_folder, Qt.MatchFlag.MatchExactly)
                            if items:
                                self.folder_list_widget.setCurrentItem(items[0])
                            else: 
                                self.folder_list_widget.setCurrentRow(0)
                        else: 
                            self.update_rule_inputs(None, None) # Pass None as QListWidgetItem

                    else: 
                         QMessageBox.warning(self, "Template Application Issue", f"Could not apply any rules from template '{template_name}'. Check logs for details.")
                else: # User clicked No
                    self.log_queue.put(f"INFO: User cancelled applying template '{template_name}'.")
        else:
            self.log_queue.put("ERROR: apply_selected_template called by a non-QAction sender.")


    # Placeholder methods for exclusion functionality to resolve linting errors
    # These should be implemented or connected to actual logic if it exists elsewhere.
    def add_exclusion_pattern(self):
        self.log_queue.put("INFO: Add exclusion pattern clicked (placeholder).")
        # Example: Open a dialog to get new pattern, then add to list and config

    def remove_selected_exclusion_pattern(self):
        self.log_queue.put("INFO: Remove selected exclusion pattern clicked (placeholder).")
        # Example: Get selected pattern from self.exclusion_list_widget, remove it, update config

    def show_exclusion_pattern_help(self):
        self.log_queue.put("INFO: Show exclusion pattern help clicked (placeholder).")
        QMessageBox.information(self, "Exclusion Help", "Enter patterns (e.g., *.tmp, temp_folder/) to exclude files/folders. One per line.")

    def save_exclusion_list_changes(self, item: QListWidgetItem):
        self.log_queue.put(f"INFO: Exclusion item '{item.text()}' changed (placeholder for saving).")
        # This should trigger saving the entire exclusion list for the current folder rule.
        self.save_rule_changes() # Re-use save_rule_changes to update the whole rule including exclusions


if __name__ == '__main__':
    import sys
    from PyQt6.QtWidgets import QApplication
    from config_manager import ConfigManager
    from worker import MonitoringWorker
    from ui_settings_dialog import SettingsDialog
    from undo_manager import UndoManager
    from ui_undo_dialog import UndoDialog

    app = QApplication(sys.argv)
    # Needs app_name for ConfigManager
    config_manager = ConfigManager("AutoTidyTest") # Provide a name for testing
    log_queue = queue.Queue()
    main_win = ConfigWindow(config_manager, log_queue)
    main_win.show()
    sys.exit(app.exec())
