from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QCheckBox, QPushButton, QDialogButtonBox,
    QWidget, QMessageBox, QLabel, QSpinBox, QComboBox # Added QComboBox
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
        self.initial_check_interval = self.config_manager.get_setting("check_interval_seconds", 3600)

        self.UNITS_SECONDS_MAP = {"Minutes": 60, "Hours": 3600, "Days": 86400}
        self.PREFERRED_DISPLAY_UNITS = ["Days", "Hours", "Minutes"] # Order for attempting to display

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

        # --- Check Interval Controls ---
        interval_layout = QHBoxLayout()
        interval_label = QLabel("Folder check interval:")
        self.interval_value_spinbox = QSpinBox()
        self.interval_value_spinbox.setRange(1, 999) # Value for the selected unit

        self.interval_unit_combo = QComboBox()
        self.interval_unit_combo.addItems(list(self.UNITS_SECONDS_MAP.keys()))

        # Convert initial_check_interval (total seconds) to display value and unit
        display_val = 1
        display_unit_text = "Hours" # Default display unit

        for unit_text_candidate in self.PREFERRED_DISPLAY_UNITS:
            seconds_in_unit = self.UNITS_SECONDS_MAP[unit_text_candidate]
            if self.initial_check_interval >= seconds_in_unit and self.initial_check_interval % seconds_in_unit == 0:
                calculated_val = self.initial_check_interval // seconds_in_unit
                if calculated_val >= 1: # Ensure the value is at least 1 for the chosen unit
                    display_val = calculated_val
                    display_unit_text = unit_text_candidate
                    break # Found the largest suitable unit
        else: # If no preferred unit perfectly divided or resulted in value < 1
            # Fallback to minutes if it's smaller than the smallest preferred unit that didn't work out
            # Or if initial interval is small
            if self.initial_check_interval < self.UNITS_SECONDS_MAP.get(display_unit_text, self.UNITS_SECONDS_MAP["Minutes"]):
                 if self.initial_check_interval >= self.UNITS_SECONDS_MAP["Minutes"]:
                    display_val = self.initial_check_interval // self.UNITS_SECONDS_MAP["Minutes"]
                    display_unit_text = "Minutes"
                 else: # Edge case: less than 1 minute, force to 1 minute
                    display_val = 1
                    display_unit_text = "Minutes"


        self.interval_value_spinbox.setValue(display_val)
        self.interval_unit_combo.setCurrentText(display_unit_text)

        interval_layout.addWidget(interval_label)
        interval_layout.addWidget(self.interval_value_spinbox)
        interval_layout.addWidget(self.interval_unit_combo)
        layout.addLayout(interval_layout)

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

        # Calculate new_check_interval in total seconds from UI components
        value = self.interval_value_spinbox.value()
        unit_text = self.interval_unit_combo.currentText()
        seconds_per_unit = self.UNITS_SECONDS_MAP.get(unit_text, self.UNITS_SECONDS_MAP["Minutes"]) # Default to Minutes' seconds
        new_check_interval_total_seconds = value * seconds_per_unit

        # For comparison and saving, use the total seconds
        new_check_interval = new_check_interval_total_seconds

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

        # Check if check_interval_seconds changed
        if new_check_interval != self.initial_check_interval:
            self.config_manager.set_setting("check_interval_seconds", new_check_interval)
            self.initial_check_interval = new_check_interval # Update initial state
            settings_changed = True

        # Save config if any setting changed
        if settings_changed:
            self.config_manager.save_config()

        super().accept() # Close the dialog with QDialog.Accepted status

    # reject() is handled automatically by QDialogButtonBox connection
