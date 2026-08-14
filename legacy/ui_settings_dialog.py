import os
from datetime import datetime, timedelta
from pathlib import Path
from string import Formatter

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QCheckBox, QDialogButtonBox,
    QWidget, QMessageBox, QLabel, QSpinBox, QLineEdit, QComboBox, QGroupBox,
    QFormLayout, QPushButton
)
from PyQt6.QtGui import QKeySequence # Added for shortcuts
from PyQt6.QtCore import pyqtSlot, Qt # Added Qt

from config_manager import ConfigManager
from startup_manager import is_autostart_supported, set_autostart
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
        self._archive_template_error: str | None = None

        self.setWindowTitle("AutoTidy Settings")
        self.setModal(True) # Block interaction with the main window

        self._init_ui()
        self._setup_shortcuts() # Call new method

    def _init_ui(self):
        """Initialize UI elements and layout."""
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # --- Startup & Mode Section ---
        startup_group = QGroupBox("Startup && Mode")
        startup_layout = QVBoxLayout()
        startup_layout.setSpacing(6)

        self.autostart_checkbox = QCheckBox("Start AutoTidy at &login")
        self.autostart_checkbox.setChecked(self.initial_start_on_login)
        self.autostart_checkbox.setToolTip("If checked, AutoTidy will start when you log into your computer.")
        startup_layout.addWidget(self.autostart_checkbox)

        autostart_helper = QLabel("Launch AutoTidy automatically whenever you sign into your account.")
        autostart_helper.setWordWrap(True)
        autostart_helper.setStyleSheet("color: grey;")
        autostart_helper.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        startup_layout.addWidget(autostart_helper)

        self._autostart_supported = is_autostart_supported()
        if not self._autostart_supported:
            self.autostart_checkbox.setEnabled(False)
            self.autostart_checkbox.setToolTip(
                "Autostart configuration is not supported on this platform."
            )

        self.dryRunModeCheckbox = QCheckBox("Enable &Dry Run Mode")
        self.dryRunModeCheckbox.setChecked(self.initial_dry_run_mode)
        self.dryRunModeCheckbox.setToolTip(
            "If checked, AutoTidy will log actions it would take but won't actually "
            "move/copy/delete files."
        )
        startup_layout.addWidget(self.dryRunModeCheckbox)

        dry_run_helper = QLabel("Simulate every cleanup and capture details without touching your files.")
        dry_run_helper.setWordWrap(True)
        dry_run_helper.setStyleSheet("color: grey;")
        dry_run_helper.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        startup_layout.addWidget(dry_run_helper)

        startup_group.setLayout(startup_layout)
        layout.addWidget(startup_group)

        # --- Show Notifications Checkbox --- (This will be replaced by the ComboBox)
        # self.showNotificationsCheckbox = QCheckBox("Show desktop &notifications for completed scans")
        # self.showNotificationsCheckbox.setChecked(self.initial_show_notifications)
        # self.showNotificationsCheckbox.setToolTip("If checked, a desktop notification will be shown when a scan cycle completes and files are processed.")
        # layout.addWidget(self.showNotificationsCheckbox)

        # --- Notifications Section ---
        notifications_group = QGroupBox("Notifications")
        notifications_layout = QFormLayout()
        notifications_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        notifications_layout.setVerticalSpacing(6)

        notification_label = QLabel("Notification &level:")
        self.notificationLevelComboBox = QComboBox()
        self.notificationLevelComboBox.addItem("None", NOTIFICATION_LEVEL_NONE)
        self.notificationLevelComboBox.addItem("Errors only", NOTIFICATION_LEVEL_ERROR)
        self.notificationLevelComboBox.addItem("Summary", NOTIFICATION_LEVEL_SUMMARY)
        self.notificationLevelComboBox.addItem("All activity", NOTIFICATION_LEVEL_ALL)
        self.notificationLevelComboBox.setToolTip(
            "Control how much information AutoTidy provides through logs and desktop notifications."
        )
        notification_label.setBuddy(self.notificationLevelComboBox)
        # Set initial value
        current_level_index = self.notificationLevelComboBox.findData(self.initial_notification_level)
        if current_level_index != -1:
            self.notificationLevelComboBox.setCurrentIndex(current_level_index)
        else: # Fallback if current value is somehow not in the list (e.g. old config)
            default_level_index = self.notificationLevelComboBox.findData(DEFAULT_NOTIFICATION_LEVEL)
            if default_level_index != -1:
                self.notificationLevelComboBox.setCurrentIndex(default_level_index)

        notifications_layout.addRow(notification_label, self.notificationLevelComboBox)

        notification_helper = QLabel(
            "Choose when AutoTidy should alert you: never, only on errors, after each scan, or for every step."
        )
        notification_helper.setWordWrap(True)
        notification_helper.setStyleSheet("color: grey;")
        notification_helper.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        notifications_layout.addRow(QLabel(), notification_helper)

        notifications_group.setLayout(notifications_layout)
        layout.addWidget(notifications_group)

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

        # --- Scheduling Section ---
        scheduling_group = QGroupBox("Scheduling")
        scheduling_layout = QVBoxLayout()
        scheduling_layout.setSpacing(6)

        schedule_mode_description = QLabel(
            "Interval scheduling is currently the only available mode."
        )
        schedule_mode_description.setWordWrap(True)
        schedule_mode_description.setStyleSheet("color: grey;")
        schedule_mode_description.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        scheduling_layout.addWidget(schedule_mode_description)

        interval_minutes_layout = QHBoxLayout()
        interval_minutes_layout.setContentsMargins(0, 0, 0, 0)
        interval_minutes_layout.setSpacing(8)
        self.intervalMinutesLabel = QLabel("Interval (minutes):")
        self.intervalMinutesSpinBox = QSpinBox()
        self.intervalMinutesSpinBox.setRange(1, 10080) # 1 min to 1 week (7 * 24 * 60)
        self.intervalMinutesSpinBox.setSuffix(" minutes")
        self.intervalMinutesSpinBox.setValue(self.initial_schedule_config.get('interval_minutes', 60))
        self.intervalMinutesSpinBox.setToolTip("How often AutoTidy should check folders for files to organize.")

        interval_info_label = QLabel("ℹ️")
        interval_info_label.setToolTip(
            "Dry Run Mode still follows the selected interval; AutoTidy logs actions instead of modifying files."
        )
        interval_info_label.setAccessibleName("Interval scheduling info")
        interval_info_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        interval_minutes_layout.addWidget(self.intervalMinutesLabel)
        interval_minutes_layout.addWidget(self.intervalMinutesSpinBox)
        interval_minutes_layout.addWidget(interval_info_label)

        self.nextRunStatusLabel = QLabel()
        self.nextRunStatusLabel.setObjectName("nextRunStatusLabel")
        self.nextRunStatusLabel.setStyleSheet("color: grey;")
        self.nextRunStatusLabel.setWordWrap(True)
        self.nextRunStatusLabel.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        scheduling_layout.addLayout(interval_minutes_layout)
        scheduling_layout.addWidget(self.nextRunStatusLabel)
        scheduling_group.setLayout(scheduling_layout)
        layout.addWidget(scheduling_group)

        # --- Archiving Section ---
        archiving_group = QGroupBox("Archiving")
        archiving_layout = QVBoxLayout()
        archiving_layout.setSpacing(6)

        archive_template_label = QLabel("Archive path template:")
        self.archivePathTemplateInput = QLineEdit()
        self.archivePathTemplateInput.setText(self.initial_archive_template)
        self.archivePathTemplateInput.setToolTip(
            "Define the subfolder structure for archived files. Use placeholders like {YYYY}-{MM}-{DD}."
        )

        archiving_layout.addWidget(archive_template_label)
        archiving_layout.addWidget(self.archivePathTemplateInput)

        self.archiveTemplatePreviewLabel = QLabel()
        self.archiveTemplatePreviewLabel.setObjectName("archiveTemplatePreviewLabel")
        self.archiveTemplatePreviewLabel.setWordWrap(True)
        self.archiveTemplatePreviewLabel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.archiveTemplatePreviewLabel.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        archiving_layout.addWidget(self.archiveTemplatePreviewLabel)

        archive_template_desc_label = QLabel(
            "Placeholders: {YYYY}, {MM}, {DD}, {FILENAME}, {EXT}, {ORIGINAL_FOLDER_NAME}"
        )
        archive_template_desc_label.setStyleSheet("color: grey;")
        archive_template_desc_label.setWordWrap(True)
        archive_template_desc_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        archiving_layout.addWidget(archive_template_desc_label)

        archiving_group.setLayout(archiving_layout)
        layout.addWidget(archiving_group)

        self.archivePathTemplateInput.textChanged.connect(self._on_archive_template_changed)
        self._update_archive_template_preview(self.archivePathTemplateInput.text())

        self.intervalMinutesSpinBox.valueChanged.connect(self._update_next_run_status_label)
        self.dryRunModeCheckbox.stateChanged.connect(self._update_next_run_status_label)
        self._update_next_run_status_label()


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

        restore_defaults_button = QPushButton("Restore Defaults")
        restore_defaults_button.setToolTip("Revert all settings to their default values.")
        restore_defaults_button.setAutoDefault(False)
        button_box.addButton(restore_defaults_button, QDialogButtonBox.ButtonRole.ResetRole)

        button_box.accepted.connect(self.accept) # Connect OK to accept()
        button_box.rejected.connect(self.reject) # Connect Cancel to reject()
        restore_defaults_button.clicked.connect(self._restore_defaults)
        layout.addWidget(button_box)

        # Ensure tab order flows naturally through grouped controls
        self.setTabOrder(self.autostart_checkbox, self.dryRunModeCheckbox)
        self.setTabOrder(self.dryRunModeCheckbox, self.notificationLevelComboBox)
        self.setTabOrder(self.notificationLevelComboBox, self.intervalMinutesSpinBox)
        self.setTabOrder(self.intervalMinutesSpinBox, self.archivePathTemplateInput)

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

    def _on_archive_template_changed(self, text: str):
        """Render a preview when the archive template text changes."""
        self._update_archive_template_preview(text)

    def _update_archive_template_preview(self, template_text: str):
        """Update the inline preview and error state for the archive template."""
        preview_path, error_message, using_default = self._calculate_archive_template_preview(template_text)
        self._archive_template_error = error_message

        if error_message:
            self.archiveTemplatePreviewLabel.setText(f"⚠️ {error_message}")
            self.archiveTemplatePreviewLabel.setStyleSheet("color: #d9534f;")
            self.archivePathTemplateInput.setStyleSheet("border: 1px solid #d9534f;")
        else:
            suffix_note = " (using default template)" if using_default and not template_text.strip() else ""
            self.archiveTemplatePreviewLabel.setText(f"Preview: {preview_path}{suffix_note}")
            self.archiveTemplatePreviewLabel.setStyleSheet("color: grey; font-style: italic;")
            self.archivePathTemplateInput.setStyleSheet("")

    def _calculate_archive_template_preview(self, template_text: str) -> tuple[str | None, str | None, bool]:
        """Return a preview path, validation error, and whether defaults were used."""
        trimmed = template_text.strip()
        using_default_template = False
        default_template = self.config_manager.default_config.get('settings', {}).get(
            'archive_path_template',
            '_Cleanup/{YYYY}-{MM}-{DD}',
        )

        if not trimmed:
            trimmed = default_template
            using_default_template = True

        formatter = Formatter()
        allowed_placeholders = {
            'YYYY',
            'MM',
            'DD',
            'FILENAME',
            'EXT',
            'ORIGINAL_FOLDER_NAME',
        }

        try:
            parsed_segments = list(formatter.parse(trimmed))
        except ValueError as exc:
            return None, f"Invalid template: {exc}", using_default_template

        for _, field_name, format_spec, conversion in parsed_segments:
            if field_name is None:
                continue
            if conversion:
                return None, f"Invalid placeholder {{{field_name}!{conversion}}}.", using_default_template
            if format_spec:
                return None, f"Formatting is not supported for {{{field_name}}}.", using_default_template
            if field_name not in allowed_placeholders:
                return None, f"Unknown placeholder {{{field_name}}}.", using_default_template

        sample_folder = Path.home() / "Downloads"
        sample_filename_stem = "example"
        sample_extension = ".txt"

        now = datetime.now()

        replacements = {
            "{YYYY}": now.strftime("%Y"),
            "{MM}": now.strftime("%m"),
            "{DD}": now.strftime("%d"),
            "{FILENAME}": sample_filename_stem,
            "{EXT}": sample_extension,
            "{ORIGINAL_FOLDER_NAME}": sample_folder.name,
        }

        resolved_template = trimmed
        for placeholder, value in replacements.items():
            resolved_template = resolved_template.replace(placeholder, value)

        resolved_template = os.path.expandvars(resolved_template)
        resolved_template = os.path.expanduser(resolved_template)

        target_path_candidate = Path(resolved_template)
        if not target_path_candidate.is_absolute():
            target_path_candidate = (sample_folder / target_path_candidate).resolve()
        else:
            target_path_candidate = target_path_candidate.resolve()

        includes_filename_tokens = any(token in trimmed for token in ("{FILENAME}", "{EXT}"))

        if includes_filename_tokens:
            preview_path = target_path_candidate
        else:
            preview_path = target_path_candidate / f"{sample_filename_stem}{sample_extension}"

        return os.fspath(preview_path), None, using_default_template

    def _update_next_run_status_label(self, *_):
        """Refresh the projected scheduling status label."""
        interval_minutes = self.intervalMinutesSpinBox.value()
        next_run_time = datetime.now() + timedelta(minutes=interval_minutes)
        interval_phrase = "1 minute" if interval_minutes == 1 else f"{interval_minutes} minutes"
        formatted_time = next_run_time.strftime("%b %d, %Y %I:%M %p")

        if self.dryRunModeCheckbox.isChecked():
            status_text = (
                f"Dry Run Mode active. Next simulated run in {interval_phrase} at {formatted_time}."
            )
        else:
            status_text = f"Next run in {interval_phrase} at {formatted_time}."

        self.nextRunStatusLabel.setText(status_text)

    @pyqtSlot()
    def accept(self):
        """Handle OK button click: save settings and apply autostart."""
        settings_changed = False
        new_start_on_login = self.autostart_checkbox.isChecked()
        # new_check_interval = self.interval_spinbox.value() # Old setting
        new_archive_template = self.archivePathTemplateInput.text().strip()

        self._update_archive_template_preview(self.archivePathTemplateInput.text())
        if self._archive_template_error:
            self.archivePathTemplateInput.setFocus()
            return

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
        autostart_changed = new_start_on_login != self.initial_start_on_login
        if self._autostart_supported and autostart_changed:
            success = set_autostart(new_start_on_login, APP_NAME)
            if success:
                self.config_manager.set_setting("start_on_login", new_start_on_login)
                self.initial_start_on_login = new_start_on_login # Update initial state
                settings_changed = True
            else:
                self.autostart_checkbox.setChecked(self.initial_start_on_login)
                QMessageBox.warning(
                    self,
                    "Autostart Error",
                    f"Failed to {'enable' if new_start_on_login else 'disable'} autostart. "
                    f"Please check application logs or permissions."
                )
        elif autostart_changed:
            self.autostart_checkbox.setChecked(self.initial_start_on_login)
            QMessageBox.information(
                self,
                "Autostart Not Available",
                "Autostart configuration is not supported on this platform."
            )

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

    def _restore_defaults(self):
        """Restore the dialog controls to their baseline default values."""
        default_settings = self.config_manager.default_config.get('settings', {})

        if self._autostart_supported:
            self.autostart_checkbox.setChecked(default_settings.get('start_on_login', False))
        else:
            # Keep disabled autostart checkbox unchecked when unsupported
            self.autostart_checkbox.setChecked(False)

        self.dryRunModeCheckbox.setChecked(default_settings.get('dry_run_mode', False))
        self.intervalMinutesSpinBox.setValue(default_settings.get('interval_minutes', 60))
        self.archivePathTemplateInput.setText(default_settings.get('archive_path_template', ''))

        default_notification_level = default_settings.get('notification_level', DEFAULT_NOTIFICATION_LEVEL)
        level_index = self.notificationLevelComboBox.findData(default_notification_level)
        if level_index != -1:
            self.notificationLevelComboBox.setCurrentIndex(level_index)

        self._update_archive_template_preview(self.archivePathTemplateInput.text())
        self._update_next_run_status_label()
        self.autostart_checkbox.setFocus()
