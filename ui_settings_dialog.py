from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QCheckBox, QPushButton, QDialogButtonBox,
    QWidget, QMessageBox, QLabel, QSpinBox, QHBoxLayout # Added QSpinBox, QHBoxLayout
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
        self.initial_archive_format = self.config_manager.get_setting("archive_structure_format", "%Y-%m-%d")

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

        # --- Check Interval SpinBox ---
        interval_layout = QHBoxLayout()
        interval_label = QLabel("Folder check interval:")
        self.interval_spinbox = QSpinBox()
        self.interval_spinbox.setRange(60, 86400)  # 1 minute to 24 hours
        self.interval_spinbox.setSuffix(" seconds")
        self.interval_spinbox.setValue(self.initial_check_interval)
        interval_layout.addWidget(interval_label)
        interval_layout.addWidget(self.interval_spinbox)
        layout.addLayout(interval_layout)

        # --- Archive Subfolder Format ---
        archive_format_layout = QHBoxLayout()
        archive_format_label = QLabel("Archive subfolder format:")
        self.archive_format_lineedit = QLineEdit()
        self.archive_format_lineedit.setText(self.initial_archive_format)
        self.archive_format_lineedit.setToolTip(
            "Uses strftime format codes (e.g., %Y-%m-%d for 'YYYY-MM-DD', %Y/%m for 'YYYY/MM').\n"
            "Common codes: %Y (year), %m (month), %d (day), %b (month abbr), %B (month name)."
        )
        archive_format_layout.addWidget(archive_format_label)
        archive_format_layout.addWidget(self.archive_format_lineedit)
        layout.addLayout(archive_format_layout)

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
        new_check_interval = self.interval_spinbox.value()
        new_archive_format = self.archive_format_lineedit.text()

        # Check if start_on_login changed
        if new_start_on_login != self.initial_start_on_login:
            self.config_manager.set_setting("start_on_login", new_start_on_login)
            settings_changed = True
            # Apply autostart setting - this part has side effects beyond just config saving
            try:
                # It's good practice to wrap operations that can fail, like OS interactions
                set_autostart(new_start_on_login, APP_NAME)
                self.initial_start_on_login = new_start_on_login # Update initial state only on success
            except Exception as e: # Catch potential errors from set_autostart
                 QMessageBox.warning(
                    self,
                    "Autostart Error",
                    f"Failed to {'enable' if new_start_on_login else 'disable'} autostart: {e}. "
                    f"Please check application logs or permissions."
                )
                 # Optionally revert checkbox if applying failed, or just log and inform user
                 self.autostart_checkbox.setChecked(self.initial_start_on_login)


        # Check if check_interval_seconds changed
        if new_check_interval != self.initial_check_interval:
            self.config_manager.set_setting("check_interval_seconds", new_check_interval)
            self.initial_check_interval = new_check_interval # Update initial state
            settings_changed = True

        # Check if archive_structure_format changed
        if new_archive_format != self.initial_archive_format:
            # Basic validation: ensure it's not empty, though strftime might have its own errors for invalid formats
            if not new_archive_format.strip():
                QMessageBox.warning(self, "Invalid Format", "Archive subfolder format cannot be empty. Using previous value.")
                self.archive_format_lineedit.setText(self.initial_archive_format) # Revert
            else:
                self.config_manager.set_setting("archive_structure_format", new_archive_format)
                self.initial_archive_format = new_archive_format # Update initial state
                settings_changed = True

        # Save config if any setting changed
        if settings_changed:
            self.config_manager.save_config()

        super().accept() # Close the dialog with QDialog.Accepted status

    # reject() is handled automatically by QDialogButtonBox connection
