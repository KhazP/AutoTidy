from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QCheckBox, QPushButton, QDialogButtonBox,
    QWidget, QMessageBox, QLabel, QSpinBox, QLineEdit, QComboBox # Added QComboBox
)
from PyQt6.QtCore import pyqtSlot

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
        self.initial_schedule_config = self.config_manager.get_schedule_config()
        self.initial_dry_run_mode = self.config_manager.get_dry_run_mode()

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
        interval_minutes_layout.addWidget(self.intervalMinutesLabel)
        interval_minutes_layout.addWidget(self.intervalMinutesSpinBox)
        layout.addLayout(interval_minutes_layout)
        # --- End New Scheduling Section ---

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
        new_schedule_type = "interval" # Hardcoded for now
        new_interval_minutes = self.intervalMinutesSpinBox.value()

        # Dry Run Mode
        new_dry_run_mode = self.dryRunModeCheckbox.isChecked()

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
        if (new_schedule_type != self.initial_schedule_config.get('type') or
                new_interval_minutes != self.initial_schedule_config.get('interval_minutes')):
            self.config_manager.set_schedule_config(new_schedule_type, new_interval_minutes)
            self.initial_schedule_config = {'type': new_schedule_type, 'interval_minutes': new_interval_minutes}
            settings_changed = True

        # Check if dry_run_mode changed
        if new_dry_run_mode != self.initial_dry_run_mode:
            self.config_manager.set_dry_run_mode(new_dry_run_mode)
            self.initial_dry_run_mode = new_dry_run_mode
            settings_changed = True

        # Save config if any setting changed
        if settings_changed:
            self.config_manager.save_config()

        super().accept() # Close the dialog with QDialog.Accepted status

    # reject() is handled automatically by QDialogButtonBox connection
