from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QCheckBox, QPushButton, QDialogButtonBox,
    QWidget, QMessageBox, QLabel, QSpinBox, QLineEdit, QComboBox, QTimeEdit, QGroupBox
)
from PyQt6.QtCore import pyqtSlot, QTime

from config_manager import ConfigManager
from startup_manager import set_autostart
from constants import APP_NAME, APP_VERSION # Import APP_VERSION

class SettingsDialog(QDialog):
    """Dialog window for application settings."""

    def __init__(self, config_manager: ConfigManager, parent: QWidget | None = None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.initial_start_on_login = self.config_manager.get_setting("start_on_login", False)
        # self.initial_check_interval = self.config_manager.get_setting("check_interval_seconds", 3600) # Old setting
        self.initial_archive_template = self.config_manager.get_archive_path_template()
        self.initial_schedule_config = self.config_manager.get_schedule_config() # This will be a dict
        self.initial_dry_run_mode = self.config_manager.get_dry_run_mode()
        # Load initial notification settings
        self.initial_notify_on_scan_completion = self.config_manager.get_notify_on_scan_completion()
        self.initial_notify_on_errors = self.config_manager.get_notify_on_errors()
        self.initial_notify_on_actions_summary = self.config_manager.get_notify_on_actions_summary()

        self.setWindowTitle("AutoTidy Settings")
        self.setModal(True) # Block interaction with the main window

        self._init_ui()

    def _init_ui(self):
        """Initialize UI elements and layout."""
        layout = QVBoxLayout(self)

        # --- Autostart Checkbox ---
        self.autostart_checkbox = QCheckBox("Start AutoTidy automatically on system login")
        self.autostart_checkbox.setChecked(self.initial_start_on_login)
        layout.addWidget(self.autostart_checkbox)

        # --- Dry Run Mode Checkbox ---
        self.dryRunModeCheckbox = QCheckBox("Enable Dry Run Mode (Simulate actions, no files will be changed)")
        self.dryRunModeCheckbox.setChecked(self.initial_dry_run_mode)
        layout.addWidget(self.dryRunModeCheckbox)

        # --- Desktop Notifications Section ---
        notifications_groupbox = QGroupBox("Desktop Notifications")
        notifications_layout = QVBoxLayout()

        self.notifyScanCompletionCheckbox = QCheckBox("Notify on scan cycle completion")
        self.notifyScanCompletionCheckbox.setChecked(self.initial_notify_on_scan_completion)
        notifications_layout.addWidget(self.notifyScanCompletionCheckbox)

        self.notifyErrorsCheckbox = QCheckBox("Notify on significant errors")
        self.notifyErrorsCheckbox.setChecked(self.initial_notify_on_errors)
        notifications_layout.addWidget(self.notifyErrorsCheckbox)

        self.notifyActionsSummaryCheckbox = QCheckBox("Notify with summary of actions taken after scan")
        self.notifyActionsSummaryCheckbox.setChecked(self.initial_notify_on_actions_summary)
        notifications_layout.addWidget(self.notifyActionsSummaryCheckbox)

        notifications_groupbox.setLayout(notifications_layout)
        layout.addWidget(notifications_groupbox)
        # ----------------------------

        # --- Check Interval SpinBox (Old, to be replaced or removed if schedule_interval_minutes is used) ---
        # For now, let's comment it out to avoid confusion and prepare for using the new setting.
        # If needed, it can be repurposed or removed once worker uses new schedule settings.
        # interval_layout = QHBoxLayout()
        # interval_label = QLabel("Folder check interval:") # This label might be confusing now
        # self.interval_spinbox = QSpinBox()
        # self.interval_spinbox.setRange(60, 86400)  # 1 minute to 24 hours
        # self.interval_spinbox.setSuffix(" seconds")
        # self.interval_spinbox.setValue(self.initial_check_interval) # This uses the old setting
        # interval_layout.addWidget(interval_label)
        # interval_layout.addWidget(self.interval_spinbox)
        # layout.addLayout(interval_layout)

        # --- New Scheduling Section ---
        scheduling_label = QLabel("Scheduling:")
        layout.addWidget(scheduling_label)

        schedule_type_layout = QHBoxLayout()
        schedule_type_layout.addWidget(QLabel("Schedule Type:"))
        self.scheduleTypeComboBox = QComboBox()
        self.scheduleTypeComboBox.addItems(["Interval", "Specific Time of Day", "Specific Days of the Week"])
        schedule_type_layout.addWidget(self.scheduleTypeComboBox)
        layout.addLayout(schedule_type_layout)

        # --- Interval Options ---
        self.interval_options_widget = QWidget()
        interval_options_layout = QHBoxLayout(self.interval_options_widget)
        interval_options_layout.setContentsMargins(0,0,0,0) # Remove padding for seamless integration
        self.intervalMinutesLabel = QLabel("Run every:")
        self.intervalMinutesSpinBox = QSpinBox()
        self.intervalMinutesSpinBox.setRange(1, 10080) # 1 min to 1 week (7 * 24 * 60)
        self.intervalMinutesSpinBox.setSuffix(" minutes")
        interval_options_layout.addWidget(self.intervalMinutesLabel)
        interval_options_layout.addWidget(self.intervalMinutesSpinBox)
        interval_options_layout.addStretch()
        layout.addWidget(self.interval_options_widget)

        # --- Specific Time Options ---
        self.specific_time_options_widget = QWidget()
        specific_time_options_layout = QHBoxLayout(self.specific_time_options_widget)
        specific_time_options_layout.setContentsMargins(0,0,0,0)
        specific_time_options_layout.addWidget(QLabel("Run at time:"))
        self.specific_time_edit = QTimeEdit()
        self.specific_time_edit.setDisplayFormat("HH:mm")
        specific_time_options_layout.addWidget(self.specific_time_edit)
        specific_time_options_layout.addStretch()
        layout.addWidget(self.specific_time_options_widget)

        # --- Days of the Week Options ---
        self.days_of_week_options_widget = QGroupBox("Run on specific days at set time") # Use QGroupBox for title
        self.days_of_week_options_widget.setCheckable(False) # Not a checkable groupbox itself
        days_of_week_layout = QVBoxLayout(self.days_of_week_options_widget) # Main layout for this group is QVBoxLayout

        # Time edit for weekly schedule (can be shared or separate)
        # For now, let's assume "Specific Days of the Week" also uses the self.specific_time_edit
        # If specific_time_edit needs to be part of this group visually, it should be added here
        # or this group shown alongside specific_time_options_widget.
        # For simplicity, we'll make specific_time_options_widget visible for "Specific Days of the Week" too.

        days_checkboxes_layout = QHBoxLayout() # Layout for the checkboxes themselves
        self.day_checkboxes = {}
        for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
            checkbox = QCheckBox(day)
            self.day_checkboxes[day.lower()] = checkbox
            days_checkboxes_layout.addWidget(checkbox)
        days_of_week_layout.addLayout(days_checkboxes_layout)
        layout.addWidget(self.days_of_week_options_widget)

        # --- End New Scheduling Section ---
        self._load_schedule_settings() # Load initial schedule settings
        self.scheduleTypeComboBox.currentIndexChanged.connect(self._update_schedule_options_ui)
        self._update_schedule_options_ui() # Initial UI state

        # --- Archive Path Template ---
        archive_template_label = QLabel("Archive path template:")
        layout.addWidget(archive_template_label)
        self.archivePathTemplateInput = QLineEdit()
        self.archivePathTemplateInput.setText(self.initial_archive_template)
        layout.addWidget(self.archivePathTemplateInput)
        archive_template_desc_label = QLabel(
            "Placeholders: {YYYY}, {MM}, {DD}, {FILENAME}, {EXT}, {ORIGINAL_FOLDER_NAME}"
        )
        archive_template_desc_label.setStyleSheet("font-size: 9pt; color: grey;") # Optional styling
        layout.addWidget(archive_template_desc_label)


        # --- Version Label ---
        version_label = QLabel(f"Version: {APP_VERSION}")
        version_label.setStyleSheet("color: grey;") # Optional: Make it less prominent
        layout.addWidget(version_label)
        # ---------------------

        layout.addStretch() # Add some space before buttons

        # --- Dialog Buttons (OK/Cancel) ---
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept) # Connect OK to accept()
        button_box.rejected.connect(self.reject) # Connect Cancel to reject()
        layout.addWidget(button_box)

    @pyqtSlot()
    def accept(self):
        """Handle OK button click: save settings and apply autostart."""
        settings_changed = False
        new_start_on_login = self.autostart_checkbox.isChecked()
        # new_check_interval = self.interval_spinbox.value() # Old setting
        new_archive_template = self.archivePathTemplateInput.text().strip()

        # New schedule settings
        # New schedule settings
        schedule_config = {'type': '', 'interval_minutes': None, 'specific_time': None, 'days_of_week': []}
        selected_schedule_type_text = self.scheduleTypeComboBox.currentText()

        if selected_schedule_type_text == "Interval":
            schedule_config['type'] = 'interval'
            schedule_config['interval_minutes'] = self.intervalMinutesSpinBox.value()
        elif selected_schedule_type_text == "Specific Time of Day":
            schedule_config['type'] = 'daily' # Assuming "Specific Time of Day" implies daily
            schedule_config['specific_time'] = self.specific_time_edit.time().toString("HH:mm")
        elif selected_schedule_type_text == "Specific Days of the Week":
            schedule_config['type'] = 'weekly'
            schedule_config['specific_time'] = self.specific_time_edit.time().toString("HH:mm")
            selected_days = []
            for day_key, checkbox in self.day_checkboxes.items():
                if checkbox.isChecked():
                    selected_days.append(day_key)
            schedule_config['days_of_week'] = selected_days
            if not selected_days: # Basic validation
                 QMessageBox.warning(self, "Validation Error", "For 'Specific Days of the Week' schedule, please select at least one day.")
                 super().reject() # Keep dialog open or indicate error
                 return


        # Dry Run Mode
        new_dry_run_mode = self.dryRunModeCheckbox.isChecked()

        # Notification Settings
        new_notify_on_scan_completion = self.notifyScanCompletionCheckbox.isChecked()
        new_notify_on_errors = self.notifyErrorsCheckbox.isChecked()
        new_notify_on_actions_summary = self.notifyActionsSummaryCheckbox.isChecked()

        # Basic validation for archive template (ensure not empty, else ConfigManager defaults)
        if not new_archive_template:
            # QMessageBox.warning(self, "Validation Error", "Archive path template cannot be empty.")
            # super().reject() # Or keep the dialog open, or revert to initial/default.
            # For now, we let ConfigManager handle setting a default if it's empty.
            pass


        # Check if start_on_login changed
        if new_start_on_login != self.initial_start_on_login:
            self.config_manager.set_setting("start_on_login", new_start_on_login)
            settings_changed = True
            # Apply autostart setting - this part has side effects beyond just config saving
            success = set_autostart(new_start_on_login, APP_NAME)
            if not success:
                QMessageBox.warning(
                    self,
                    "Autostart Error",
                    f"Failed to {'enable' if new_start_on_login else 'disable'} autostart. "
                    f"Please check application logs or permissions."
                )
            else:
                self.initial_start_on_login = new_start_on_login # Update initial state

        # Check if check_interval_seconds changed (Commented out, using new schedule settings)
        # if new_check_interval != self.initial_check_interval:
        #     self.config_manager.set_setting("check_interval_seconds", new_check_interval)
        #     self.initial_check_interval = new_check_interval # Update initial state
        #     settings_changed = True

        # Check if archive_path_template changed
        if new_archive_template != self.initial_archive_template:
            self.config_manager.set_archive_path_template(new_archive_template)
            self.initial_archive_template = new_archive_template # Update initial state
            settings_changed = True

        # Check if schedule settings changed
        # More robust check: compare entire dictionaries or specific relevant fields
        initial_type = self.initial_schedule_config.get('type', 'interval')
        initial_interval = self.initial_schedule_config.get('interval_minutes', 60)
        initial_time = self.initial_schedule_config.get('specific_time', '00:00')
        initial_days = sorted(self.initial_schedule_config.get('days_of_week', []))

        current_type = schedule_config['type']
        current_interval = schedule_config.get('interval_minutes')
        current_time = schedule_config.get('specific_time')
        current_days = sorted(schedule_config.get('days_of_week', []))

        schedule_values_changed = False
        if current_type != initial_type:
            schedule_values_changed = True
        elif current_type == 'interval' and current_interval != initial_interval:
            schedule_values_changed = True
        elif current_type == 'daily' and current_time != initial_time:
            schedule_values_changed = True
        elif current_type == 'weekly' and (current_time != initial_time or current_days != initial_days):
            schedule_values_changed = True

        if schedule_values_changed:
            self.config_manager.set_schedule_config(schedule_config) # Pass the whole dict
            self.initial_schedule_config = schedule_config # Update initial state
            settings_changed = True

        # Check if dry_run_mode changed
        if new_dry_run_mode != self.initial_dry_run_mode:
            self.config_manager.set_dry_run_mode(new_dry_run_mode)
            self.initial_dry_run_mode = new_dry_run_mode
            settings_changed = True

        # Check if notification settings changed
        if new_notify_on_scan_completion != self.initial_notify_on_scan_completion:
            self.config_manager.set_setting('notify_on_scan_completion', new_notify_on_scan_completion)
            self.initial_notify_on_scan_completion = new_notify_on_scan_completion
            settings_changed = True

        if new_notify_on_errors != self.initial_notify_on_errors:
            self.config_manager.set_setting('notify_on_errors', new_notify_on_errors)
            self.initial_notify_on_errors = new_notify_on_errors
            settings_changed = True

        if new_notify_on_actions_summary != self.initial_notify_on_actions_summary:
            self.config_manager.set_setting('notify_on_actions_summary', new_notify_on_actions_summary)
            self.initial_notify_on_actions_summary = new_notify_on_actions_summary
            settings_changed = True

        # Save config if any setting changed
        if settings_changed:
            self.config_manager.save_config()

        super().accept() # Close the dialog with QDialog.Accepted status

    # reject() is handled automatically by QDialogButtonBox connection

    def _load_schedule_settings(self):
        """Load schedule settings from config_manager into UI elements."""
        config = self.initial_schedule_config # Already fetched in __init__

        schedule_type = config.get('type', 'interval') # Default to interval

        if schedule_type == 'interval':
            self.scheduleTypeComboBox.setCurrentText("Interval")
            self.intervalMinutesSpinBox.setValue(config.get('interval_minutes', 60))
        elif schedule_type == 'daily':
            self.scheduleTypeComboBox.setCurrentText("Specific Time of Day")
            time_str = config.get('specific_time', '00:00')
            self.specific_time_edit.setTime(QTime.fromString(time_str, "HH:mm"))
        elif schedule_type == 'weekly':
            self.scheduleTypeComboBox.setCurrentText("Specific Days of the Week")
            time_str = config.get('specific_time', '00:00') # Weekly also needs a time
            self.specific_time_edit.setTime(QTime.fromString(time_str, "HH:mm"))

            selected_days = config.get('days_of_week', [])
            for day_key, checkbox in self.day_checkboxes.items():
                checkbox.setChecked(day_key in selected_days)
        else: # Default to interval if unknown type
            self.scheduleTypeComboBox.setCurrentText("Interval")
            self.intervalMinutesSpinBox.setValue(config.get('interval_minutes', 60))

        # self._update_schedule_options_ui() # Call this after setting combo box to ensure correct initial UI state

    def _update_schedule_options_ui(self):
        """Show/hide schedule configuration options based on selected type."""
        selected_type = self.scheduleTypeComboBox.currentText()

        if selected_type == "Interval":
            self.interval_options_widget.setVisible(True)
            self.specific_time_options_widget.setVisible(False)
            self.days_of_week_options_widget.setVisible(False)
        elif selected_type == "Specific Time of Day":
            self.interval_options_widget.setVisible(False)
            self.specific_time_options_widget.setVisible(True)
            self.days_of_week_options_widget.setVisible(False)
        elif selected_type == "Specific Days of the Week":
            self.interval_options_widget.setVisible(False)
            self.specific_time_options_widget.setVisible(True) # Show time for weekly schedule as well
            self.days_of_week_options_widget.setVisible(True)
        else: # Default or error case
            self.interval_options_widget.setVisible(True)
            self.specific_time_options_widget.setVisible(False)
            self.days_of_week_options_widget.setVisible(False)
