from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QCheckBox, QPushButton, QDialogButtonBox,
    QWidget, QMessageBox, QLabel, QSpinBox, QLineEdit, QComboBox # Added QComboBox
)
from PyQt6.QtGui import QKeySequence # Added for shortcuts
from PyQt6.QtCore import pyqtSlot, Qt # Added Qt

from config_manager import ConfigManager
from startup_manager import set_autostart
from constants import (
    APP_NAME, APP_VERSION,
    NOTIFICATION_LEVEL_NONE,
    NOTIFICATION_LEVEL_ERROR,
    NOTIFICATION_LEVEL_SUMMARY,
    NOTIFICATION_LEVEL_ALL,
    DEFAULT_NOTIFICATION_LEVEL
)

class SettingsDialog(QDialog):
    """Dialog window for application settings."""

    def __init__(self, config_manager: ConfigManager, parent: QWidget | None = None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.initial_start_on_login = self.config_manager.get_setting("start_on_login", False)
        # self.initial_check_interval = self.config_manager.get_setting("check_interval_seconds", 3600) # Old setting
        self.initial_archive_template = self.config_manager.get_archive_path_template()
        self.initial_schedule_config = self.config_manager.get_schedule_config()
        self.initial_dry_run_mode = self.config_manager.get_dry_run_mode()
        # self.initial_show_notifications = self.config_manager.get_setting("show_notifications", True) # Old setting
        self.initial_notification_level = self.config_manager.get_notification_level() # New setting

        self.setWindowTitle("AutoTidy Settings")
        self.setModal(True) # Block interaction with the main window

        self._init_ui()
        self._setup_shortcuts() # Call new method

    def _init_ui(self):
        """Initialize UI elements and layout."""
        layout = QVBoxLayout(self)

        # --- Autostart Checkbox ---
        self.autostart_checkbox = QCheckBox("Start AutoTidy automatically on system &login") # Added &
        self.autostart_checkbox.setChecked(self.initial_start_on_login)
        self.autostart_checkbox.setToolTip("If checked, AutoTidy will start when you log into your computer.")
        layout.addWidget(self.autostart_checkbox)

        # --- Dry Run Mode Checkbox ---
        self.dryRunModeCheckbox = QCheckBox("Enable &Dry Run Mode (Simulate actions, no files will be changed)") # Added &
        self.dryRunModeCheckbox.setChecked(self.initial_dry_run_mode)
        self.dryRunModeCheckbox.setToolTip("If checked, AutoTidy will log actions it would take but won't actually move/copy/delete files.")
        layout.addWidget(self.dryRunModeCheckbox)

        # --- Show Notifications Checkbox --- (This will be replaced by the ComboBox)
        # self.showNotificationsCheckbox = QCheckBox("Show desktop &notifications for completed scans")
        # self.showNotificationsCheckbox.setChecked(self.initial_show_notifications)
        # self.showNotificationsCheckbox.setToolTip("If checked, a desktop notification will be shown when a scan cycle completes and files are processed.")
        # layout.addWidget(self.showNotificationsCheckbox)

        # --- Notification Level ComboBox ---
        notification_layout = QHBoxLayout()
        notification_label = QLabel("Notification &Level:")
        self.notificationLevelComboBox = QComboBox()
        self.notificationLevelComboBox.addItem("None (No notifications or logs)", NOTIFICATION_LEVEL_NONE)
        self.notificationLevelComboBox.addItem("Errors Only (Notify on errors)", NOTIFICATION_LEVEL_ERROR)
        self.notificationLevelComboBox.addItem("Summary (Notify after scan, show errors)", NOTIFICATION_LEVEL_SUMMARY)
        self.notificationLevelComboBox.addItem("All (Detailed logs and all notifications)", NOTIFICATION_LEVEL_ALL)
        self.notificationLevelComboBox.setToolTip("Control how much information AutoTidy provides through logs and desktop notifications.")
        # Set initial value
        current_level_index = self.notificationLevelComboBox.findData(self.initial_notification_level)
        if current_level_index != -1:
            self.notificationLevelComboBox.setCurrentIndex(current_level_index)
        else: # Fallback if current value is somehow not in the list (e.g. old config)
            default_level_index = self.notificationLevelComboBox.findData(DEFAULT_NOTIFICATION_LEVEL)
            if default_level_index != -1:
                self.notificationLevelComboBox.setCurrentIndex(default_level_index)

        notification_layout.addWidget(notification_label)
        notification_layout.addWidget(self.notificationLevelComboBox)
        layout.addLayout(notification_layout)
        # -----------------------------------

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
        self.scheduleTypeComboBox = QComboBox()
        self.scheduleTypeComboBox.addItems(["Run at interval"])
        self.scheduleTypeComboBox.setEnabled(False) # Only one type for now
        # scheduleTypeLayout.addWidget(QLabel("Type:")) # Optional label for type
        schedule_type_layout.addWidget(self.scheduleTypeComboBox)
        layout.addLayout(schedule_type_layout)

        interval_minutes_layout = QHBoxLayout()
        self.intervalMinutesLabel = QLabel("Interval (minutes):")
        self.intervalMinutesSpinBox = QSpinBox()
        self.intervalMinutesSpinBox.setRange(1, 10080) # 1 min to 1 week (7 * 24 * 60)
        self.intervalMinutesSpinBox.setSuffix(" minutes")
        self.intervalMinutesSpinBox.setValue(self.initial_schedule_config.get('interval_minutes', 60))
        self.intervalMinutesSpinBox.setToolTip("How often AutoTidy should check folders for files to organize.")
        interval_minutes_layout.addWidget(self.intervalMinutesLabel)
        interval_minutes_layout.addWidget(self.intervalMinutesSpinBox)
        layout.addLayout(interval_minutes_layout)
        # --- End New Scheduling Section ---

        # --- Archive Path Template ---
        archive_template_label = QLabel("Archive path template:")
        layout.addWidget(archive_template_label)
        self.archivePathTemplateInput = QLineEdit()
        self.archivePathTemplateInput.setText(self.initial_archive_template)
        self.archivePathTemplateInput.setToolTip("Define the subfolder structure for archived files. Use placeholders like {YYYY}-{MM}-{DD}.")
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
        # Add tooltips to OK and Cancel buttons
        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button:
            ok_button.setText("&OK") # Added &
            ok_button.setToolTip("Save settings and close (Enter)")

        cancel_button = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button:
            cancel_button.setText("&Cancel") # Added &
            cancel_button.setToolTip("Discard changes and close (Esc)")

        button_box.accepted.connect(self.accept) # Connect OK to accept()
        button_box.rejected.connect(self.reject) # Connect Cancel to reject()
        layout.addWidget(button_box)

        self.autostart_checkbox.setFocus() # Set initial focus

    def _setup_shortcuts(self):
        """Setup keyboard shortcuts for common actions."""
        # OK and Cancel are often handled by QDialogButtonBox defaults (Enter/Esc)
        # but we can add explicit shortcuts if needed or for clarity.
        # self.addAction(self.create_action("Accept Settings", self.accept, QKeySequence(Qt.Key.Key_Return)))
        # self.addAction(self.create_action("Reject Settings", self.reject, QKeySequence(Qt.Key.Key_Escape)))
        # QDialog typically handles Enter for default button and Esc for reject.
        pass # Relying on QDialogButtonBox and QDialog default handling for Enter/Esc

    # def create_action(self, text, slot, shortcut=None): # Helper for explicit actions if needed
    #     from PyQt6.QtGui import QAction
    #     action = QAction(text, self)
    #     action.triggered.connect(slot)
    #     if shortcut:
    #         action.setShortcut(shortcut)
    #         action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
    #     return action

    @pyqtSlot()
    def accept(self):
        """Handle OK button click: save settings and apply autostart."""
        settings_changed = False
        new_start_on_login = self.autostart_checkbox.isChecked()
        # new_check_interval = self.interval_spinbox.value() # Old setting
        new_archive_template = self.archivePathTemplateInput.text().strip()

        # New schedule settings
        new_schedule_type = "interval" # Hardcoded for now
        new_interval_minutes = self.intervalMinutesSpinBox.value()

        # Dry Run Mode
        new_dry_run_mode = self.dryRunModeCheckbox.isChecked()

        # Show Notifications (Old - replaced by notification_level)
        # new_show_notifications = self.showNotificationsCheckbox.isChecked()

        # Notification Level
        new_notification_level = self.notificationLevelComboBox.currentData() # Get data (value) not text

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
            self.config_manager.set_setting("archive_path_template", new_archive_template)
            self.initial_archive_template = new_archive_template # Update initial state
            settings_changed = True

        # Check if schedule config changed
        current_schedule_config = self.config_manager.get_schedule_config()
        if new_schedule_type != current_schedule_config.get('schedule_type') or \
           new_interval_minutes != current_schedule_config.get('interval_minutes'):
            self.config_manager.set_schedule_config(new_schedule_type, new_interval_minutes)
            self.initial_schedule_config = {'schedule_type': new_schedule_type, 'interval_minutes': new_interval_minutes} # Update initial
            settings_changed = True

        # Check if dry_run_mode changed
        if new_dry_run_mode != self.initial_dry_run_mode:
            self.config_manager.set_dry_run_mode(new_dry_run_mode)
            self.initial_dry_run_mode = new_dry_run_mode # Update initial state
            settings_changed = True

        # Check if show_notifications changed (Old - replaced by notification_level)
        # if new_show_notifications != self.initial_show_notifications:
        #     self.config_manager.set_setting("show_notifications", new_show_notifications)
        #     self.initial_show_notifications = new_show_notifications # Update initial state
        #     settings_changed = True

        # Check if notification_level changed
        if new_notification_level != self.initial_notification_level:
            self.config_manager.set_notification_level(new_notification_level)
            self.initial_notification_level = new_notification_level # Update initial state
            settings_changed = True

        if settings_changed:
            self.config_manager.save_config()

        super().accept() # Close the dialog with QDialog.Accepted status

    # reject() is handled automatically by QDialogButtonBox connection
