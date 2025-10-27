import os
import sys
import queue
import re
import html
from datetime import datetime, timedelta

try:
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QLineEdit,
        QSpinBox, QLabel, QTextEdit, QFileDialog, QMessageBox, QListWidgetItem, QComboBox, QCheckBox,
        QApplication, QMenu, QInputDialog, QGroupBox, QFormLayout, QStackedLayout
    )
except ImportError:  # pragma: no cover - fallback for test environments with stubs
    from PyQt6 import QtWidgets as _QtWidgets  # type: ignore

    QWidget = getattr(_QtWidgets, "QWidget", object)
    QVBoxLayout = getattr(_QtWidgets, "QVBoxLayout", object)
    QHBoxLayout = getattr(_QtWidgets, "QHBoxLayout", object)
    QPushButton = getattr(_QtWidgets, "QPushButton", object)
    QListWidget = getattr(_QtWidgets, "QListWidget", object)
    QLineEdit = getattr(_QtWidgets, "QLineEdit", object)
    QSpinBox = getattr(_QtWidgets, "QSpinBox", object)
    QLabel = getattr(_QtWidgets, "QLabel", object)
    QTextEdit = getattr(_QtWidgets, "QTextEdit", object)
    QFileDialog = getattr(_QtWidgets, "QFileDialog", object)
    QMessageBox = getattr(_QtWidgets, "QMessageBox", object)
    QListWidgetItem = getattr(_QtWidgets, "QListWidgetItem", object)
    QComboBox = getattr(_QtWidgets, "QComboBox", object)
    QCheckBox = getattr(_QtWidgets, "QCheckBox", object)
    QApplication = getattr(_QtWidgets, "QApplication", object)
    QMenu = getattr(_QtWidgets, "QMenu", object)
    QInputDialog = getattr(_QtWidgets, "QInputDialog", object)
    QGroupBox = getattr(_QtWidgets, "QGroupBox", type("QGroupBox", (QWidget,), {}))
    QFormLayout = getattr(_QtWidgets, "QFormLayout", object)
    QStackedLayout = getattr(_QtWidgets, "QStackedLayout", object)

try:
    from PyQt6.QtGui import QDesktopServices, QKeySequence, QAction # Import QAction
except ImportError:  # pragma: no cover - fallback for test environments with stubs
    from PyQt6 import QtGui as _QtGui  # type: ignore

    class _DesktopServicesFallback:
        @staticmethod
        def openUrl(*_args, **_kwargs):
            return None

    class _KeySequenceFallback:
        def __init__(self, *_args, **_kwargs):
            pass

    class _ActionFallback:
        def __init__(self, *_args, **_kwargs):
            pass

    QDesktopServices = getattr(_QtGui, "QDesktopServices", _DesktopServicesFallback)
    QKeySequence = getattr(_QtGui, "QKeySequence", _KeySequenceFallback)
    QAction = getattr(_QtGui, "QAction", _ActionFallback)

try:
    from PyQt6.QtCore import QTimer, Qt, QUrl, pyqtSlot
except ImportError:  # pragma: no cover - fallback for test environments with stubs
    from PyQt6 import QtCore as _QtCore  # type: ignore

    class _QtFallback:
        class TextFormat:
            RichText = 0

        class TextInteractionFlag:
            TextBrowserInteraction = 0
            NoTextInteraction = 0

        class AlignmentFlag:
            AlignTop = 0

        class ShortcutContext:
            WindowShortcut = 0

        class Key:
            Key_Delete = 0
            Key_Escape = 0

        class ItemFlag:
            ItemIsEditable = 0

    def _pyqt_slot_fallback(*_args, **_kwargs):
        def decorator(func):
            return func

        return decorator

    class _QUrlFallback:
        @staticmethod
        def fromLocalFile(path):
            return path

    QTimer = getattr(_QtCore, "QTimer", object)
    Qt = getattr(_QtCore, "Qt", _QtFallback)
    QUrl = getattr(_QtCore, "QUrl", _QUrlFallback)
    pyqtSlot = getattr(_QtCore, "pyqtSlot", _pyqt_slot_fallback)
from pathlib import Path

from config_manager import ConfigManager
from worker import MonitoringWorker
from ui_settings_dialog import SettingsDialog
from constants import (
    RULE_TEMPLATES, # Import RULE_TEMPLATES
    NOTIFICATION_LEVEL_NONE,
    NOTIFICATION_LEVEL_ERROR,
    NOTIFICATION_LEVEL_SUMMARY,
    EXCLUSION_HELP_CONTENT,
)


from undo_manager import UndoManager # Added for Undo functionality
from ui_undo_dialog import UndoDialog # Added for Undo functionality
from utils import get_preview_matches, resolve_destination_for_preview

LOG_QUEUE_CHECK_INTERVAL_MS = 250

ACTION_VALUE_TO_TEXT = {
    "move": "Move",
    "copy": "Copy",
    "delete_to_trash": "Delete to Trash",
    "delete_permanently": "Delete Permanently",
}

ACTION_TEXT_TO_VALUE = {v: k for k, v in ACTION_VALUE_TO_TEXT.items()}

class ConfigWindow(QWidget):
    """Main configuration window for AutoTidy."""

    def __init__(self, config_manager: ConfigManager, log_queue: queue.Queue):
        super().__init__()
        self.config_manager = config_manager
        self.log_queue = log_queue
        self.undo_manager = UndoManager(self.config_manager) # Instantiate UndoManager
        self.monitoring_worker: MonitoringWorker | None = None
        self.worker_status = "Stopped" # Track worker status
        self._log_entries: list[tuple[str, str]] = []

        self.setWindowTitle("AutoTidy Configuration")
        self.setGeometry(200, 200, 600, 450) # x, y, width, height

        self._init_ui()
        self._load_initial_config()
        self._setup_log_timer()
        self._setup_shortcuts() # Call new method

    def _init_ui(self):
        """Initialize UI elements and layout."""
        main_layout = QVBoxLayout(self)

        # --- Quick Start Instructions ---
        self.instructions_container = QWidget()
        instructions_layout = QHBoxLayout(self.instructions_container)
        instructions_layout.setContentsMargins(0, 0, 0, 0)
        instructions_layout.setSpacing(12)

        self.instructions_label = QLabel(
            (
                "<b>How to get started:</b><br/>"
                "1. Add a folder you want AutoTidy to watch.<br/>"
                "2. Adjust the folder's cleanup rule to fit your workflow.<br/>"
                "3. Click <em>Start Monitoring</em> when you're ready.<br/>"
                "<a href=\"readme\">Learn more in the README</a>"
            )
        )
        self.instructions_label.setTextFormat(Qt.TextFormat.RichText)
        self.instructions_label.setWordWrap(True)
        self.instructions_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self.instructions_label.linkActivated.connect(self._on_instruction_link_activated)
        instructions_layout.addWidget(self.instructions_label, 1)

        self.dismiss_instructions_button = QPushButton("Hide Instructions")
        self.dismiss_instructions_button.setToolTip("Hide these tips (they won't show again)")
        self.dismiss_instructions_button.clicked.connect(self._hide_instructions_permanently)
        instructions_layout.addWidget(self.dismiss_instructions_button, 0, Qt.AlignmentFlag.AlignTop)

        main_layout.addWidget(self.instructions_container)

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

        # --- Folder and Rule Area ---
        self.rule_area_container = QWidget()
        self.rule_area_layout = QStackedLayout(self.rule_area_container)
        self.rule_area_layout.setContentsMargins(0, 0, 0, 0)
        try:
            self.rule_area_layout.setStackingMode(QStackedLayout.StackingMode.StackAll)
        except AttributeError:
            pass  # Some Qt stubs may not expose stacking mode

        self.rule_controls_widget = QWidget()
        rule_controls_layout = QVBoxLayout(self.rule_controls_widget)
        rule_controls_layout.setContentsMargins(0, 0, 0, 0)
        rule_controls_layout.setSpacing(6)

        rule_controls_layout.addWidget(QLabel("Monitored Folders:"))
        self.folder_list_widget = QListWidget()
        rule_controls_layout.addWidget(self.folder_list_widget)

        rule_controls_layout.addWidget(QLabel("Rules for selected folder:"))

        self.rule_summary_label = QLabel("Select a monitored folder to see its rule.")
        self.rule_summary_label.setStyleSheet("color: #6c757d; font-style: italic;")
        self.rule_summary_label.setWordWrap(True)
        rule_controls_layout.addWidget(self.rule_summary_label)

        rule_groups_layout = QHBoxLayout()

        match_group = QGroupBox("Match criteria")
        match_form = QFormLayout()
        match_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        match_group.setLayout(match_form)

        self.age_spinbox = QSpinBox()
        self.age_spinbox.setRange(0, 3650) # 0 to 10 years
        self.age_spinbox.setEnabled(False)
        self.age_spinbox.setToolTip("Minimum age in days for a file to be considered for action.")
        match_form.addRow("Min Age (days):", self.age_spinbox)

        self.pattern_lineedit = QLineEdit()
        self.pattern_lineedit.setPlaceholderText("*.*")
        self.pattern_lineedit.setEnabled(False)
        self.pattern_lineedit.setToolTip("Filename pattern to match (e.g., *.tmp, document_*.docx). Wildcards supported.")
        match_form.addRow("Filename Pattern:", self.pattern_lineedit)

        # Add Use Regex Checkbox
        self.useRegexCheckbox = QCheckBox("Use Regular E&xpression") # Added &
        self.useRegexCheckbox.setEnabled(False)
        self.useRegexCheckbox.setToolTip("Check to use full regular expressions for pattern matching.")
        match_form.addRow(self.useRegexCheckbox)

        self.rule_logic_combo = QComboBox()
        self.rule_logic_combo.addItems(["OR", "AND"])
        self.rule_logic_combo.setEnabled(False)
        self.rule_logic_combo.setToolTip("Logic to combine age and pattern rules (OR: either matches, AND: both must match).")
        match_form.addRow("Logic:", self.rule_logic_combo)

        action_group = QGroupBox("Action")
        action_form = QFormLayout()
        action_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        action_group.setLayout(action_form)

        self.actionComboBox = QComboBox()
        self.actionComboBox.addItems(["Move", "Copy", "Delete to Trash", "Delete Permanently"])
        self.actionComboBox.setEnabled(False)
        self.actionComboBox.setToolTip("Action to perform on matching files.")
        action_form.addRow("Action:", self.actionComboBox)

        self.destination_lineedit = QLineEdit()
        self.destination_lineedit.setPlaceholderText("Leave blank to use archive template")
        self.destination_lineedit.setEnabled(False)
        self.destination_lineedit.setToolTip(
            "Destination folder or template for move/copy actions. Supports environment variables and placeholders."
        )

        destination_widget = QWidget()
        destination_layout = QHBoxLayout(destination_widget)
        destination_layout.setContentsMargins(0, 0, 0, 0)
        destination_layout.setSpacing(6)
        destination_layout.addWidget(self.destination_lineedit, 1)

        self.destination_browse_button = QPushButton("Browse…")
        self.destination_browse_button.setEnabled(False)
        self.destination_browse_button.setToolTip("Choose a destination folder for move/copy actions.")
        destination_layout.addWidget(self.destination_browse_button)
        action_form.addRow("Destination:", destination_widget)

        preview_button_row = QHBoxLayout()
        preview_button_row.addStretch()
        self.preview_rule_button = QPushButton("Preview matches")
        self.preview_rule_button.setEnabled(False)
        self.preview_rule_button.setToolTip("Show a sample of files matching the current rule settings.")
        preview_button_row.addWidget(self.preview_rule_button)
        action_form.addRow(preview_button_row)

        self.enabledCheckbox = QCheckBox("Rule Enabled")
        self.enabledCheckbox.setEnabled(False)
        self.enabledCheckbox.setToolTip("Temporarily disable this rule without removing it.")
        action_form.addRow(self.enabledCheckbox)

        rule_groups_layout.addWidget(match_group)
        rule_groups_layout.addWidget(action_group)
        rule_controls_layout.addLayout(rule_groups_layout)

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
        rule_controls_layout.addLayout(exclusion_layout)

        self.rule_area_layout.addWidget(self.rule_controls_widget)

        placeholder_wrapper = QWidget()
        try:
            placeholder_wrapper.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        except AttributeError:
            pass
        placeholder_layout = QVBoxLayout(placeholder_wrapper)
        placeholder_layout.setContentsMargins(24, 24, 24, 24)
        placeholder_layout.addStretch()
        self.rule_placeholder_label = QLabel(
            (
                "<b>The rule controls snooze until a folder is selected.</b><br/>"
                "Add a folder with <em>Add Folder</em> above, then pick it to tailor its cleanup rule."
            )
        )
        self.rule_placeholder_label.setWordWrap(True)
        placeholder_alignment = getattr(Qt.AlignmentFlag, "AlignCenter", Qt.AlignmentFlag.AlignTop)
        self.rule_placeholder_label.setAlignment(placeholder_alignment)
        self.rule_placeholder_label.setStyleSheet(
            "color: #495057; background-color: rgba(255, 255, 255, 232); border: 1px dashed #ced4da; "
            "border-radius: 8px; padding: 24px;"
        )
        try:
            self.rule_placeholder_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        except AttributeError:
            pass
        placeholder_layout.addWidget(self.rule_placeholder_label, 0, placeholder_alignment)
        placeholder_layout.addStretch()
        self.rule_area_layout.addWidget(placeholder_wrapper)
        self._placeholder_overlay = placeholder_wrapper
        self._placeholder_overlay.hide()

        main_layout.addWidget(self.rule_area_container)

        # --- Status and Logs ---
        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel("Status:"))

        status_value_container = QWidget()
        status_value_layout = QVBoxLayout(status_value_container)
        status_value_layout.setContentsMargins(0, 0, 0, 0)
        status_value_layout.setSpacing(2)

        status_line_layout = QHBoxLayout()
        status_line_layout.setContentsMargins(0, 0, 0, 0)
        status_line_layout.setSpacing(6)

        self.status_indicator = QLabel()
        self.status_indicator.setFixedSize(12, 12)
        self.status_indicator.setStyleSheet("background-color: #6c757d; border-radius: 6px; border: 1px solid rgba(0, 0, 0, 0.2);")
        status_line_layout.addWidget(self.status_indicator)

        self.status_label = QLabel("Stopped")
        status_line_layout.addWidget(self.status_label)

        status_value_layout.addLayout(status_line_layout)

        self.status_summary_label = QLabel("")
        self.status_summary_label.setStyleSheet("color: #555555; font-size: 9pt;")
        self.status_summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        status_value_layout.addWidget(self.status_summary_label)

        status_layout.addWidget(status_value_container)
        status_layout.addStretch()
        self.start_button = QPushButton("&Start Monitoring") # Text will be updated, added &
        self.start_button.setToolTip("Start the monitoring or dry run process (Ctrl+S)")
        self.stop_button = QPushButton("S&top Monitoring") # Added &
        self.stop_button.setToolTip("Stop the currently running process (Ctrl+T)")
        self.stop_button.setEnabled(False)
        status_layout.addWidget(self.start_button)
        status_layout.addWidget(self.stop_button)
        main_layout.addLayout(status_layout)

        logs_container = QWidget()
        logs_layout = QVBoxLayout(logs_container)
        logs_layout.setContentsMargins(0, 0, 0, 0)
        logs_layout.setSpacing(6)

        log_header_layout = QHBoxLayout()
        log_header_layout.setContentsMargins(0, 0, 0, 0)
        log_header_layout.setSpacing(6)
        log_header_layout.addWidget(QLabel("Logs:"))
        log_header_layout.addStretch()

        self.log_filter_combo = QComboBox()
        self.log_filter_combo.addItems(["All", "Info", "Warning", "Error"])
        self.log_filter_combo.setCurrentText("All")
        self.log_filter_combo.setToolTip("Filter log messages by severity")
        log_header_layout.addWidget(self.log_filter_combo)

        logs_layout.addLayout(log_header_layout)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        logs_layout.addWidget(self.log_view)

        log_actions_layout = QHBoxLayout()
        log_actions_layout.setContentsMargins(0, 0, 0, 0)
        log_actions_layout.setSpacing(6)
        log_actions_layout.addStretch()

        self.clear_logs_button = QPushButton("Clear")
        self.copy_logs_button = QPushButton("Copy")
        self.save_logs_button = QPushButton("Save…")

        log_actions_layout.addWidget(self.clear_logs_button)
        log_actions_layout.addWidget(self.copy_logs_button)
        log_actions_layout.addWidget(self.save_logs_button)

        logs_layout.addLayout(log_actions_layout)

        main_layout.addWidget(logs_container)

        # --- Connect Signals ---
        self.add_folder_button.clicked.connect(self.add_folder)
        self.remove_folder_button.clicked.connect(self.remove_folder)
        self.folder_list_widget.currentItemChanged.connect(self.update_rule_inputs)
        self.age_spinbox.valueChanged.connect(self.save_rule_changes)
        self.pattern_lineedit.editingFinished.connect(self.save_rule_changes) # Save when focus lost or Enter pressed
        self.useRegexCheckbox.stateChanged.connect(self.save_rule_changes) # Connect checkbox
        self.rule_logic_combo.currentIndexChanged.connect(self.save_rule_changes) # Connect new combo box
        self.actionComboBox.currentIndexChanged.connect(self.save_rule_changes) # Connect action combo box
        self.destination_lineedit.editingFinished.connect(self.save_rule_changes)
        self.destination_browse_button.clicked.connect(self.browse_destination_folder)
        self.enabledCheckbox.stateChanged.connect(self.save_rule_changes)
        # self.apply_template_button.clicked.connect(self.apply_template) # Will be handled by QMenu
        self.preview_rule_button.clicked.connect(self.preview_rule)
        self.start_button.clicked.connect(self.start_monitoring)
        self.stop_button.clicked.connect(self.stop_monitoring)
        self.settings_button.clicked.connect(self.open_settings_dialog)
        self.view_history_button.clicked.connect(self.open_undo_dialog) # Connect new Undo button
        self.add_exclusion_button.clicked.connect(self.add_exclusion_pattern) # Renamed for clarity
        self.remove_exclusion_button.clicked.connect(self.remove_selected_exclusion_pattern) # Renamed for clarity
        self.exclusion_help_button.clicked.connect(self.show_exclusion_pattern_help) # Renamed for clarity
        self.exclusion_list_widget.itemChanged.connect(self.save_exclusion_list_changes) # Save when an item is edited

        self.clear_logs_button.clicked.connect(self.clear_logs)
        self.copy_logs_button.clicked.connect(self.copy_logs_to_clipboard)
        self.save_logs_button.clicked.connect(self.export_logs)
        self.log_filter_combo.currentTextChanged.connect(self._on_log_filter_changed)

        self._update_ui_for_status_and_mode() # Initial UI update
        self._set_initial_focus() # Set initial focus
        self._apply_instruction_visibility()
        self._update_placeholder_visibility()

    def _set_initial_focus(self):
        """Sets the initial focus to a sensible widget."""
        self.add_folder_button.setFocus()

    @pyqtSlot()
    def clear_logs(self):
        """Clear the displayed logs and stored entries."""
        self._log_entries.clear()
        self.log_view.clear()

    @pyqtSlot()
    def copy_logs_to_clipboard(self):
        """Copy the current log contents to the clipboard."""
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.log_view.toPlainText())

    @pyqtSlot()
    def export_logs(self):
        """Export all stored logs to a file."""
        default_name = f"autotidy-logs-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Logs",
            default_name,
            "Text Files (*.txt);;All Files (*)",
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as handle:
                for _, message in self._log_entries:
                    handle.write(f"{message}\n")
        except OSError as exc:
            QMessageBox.critical(self, "Save Logs", f"Could not save logs to '{file_path}': {exc}")

    @pyqtSlot(str)
    def _on_log_filter_changed(self, _text: str):
        """Refresh the log view when the filter changes."""
        self._refresh_log_view()

    def _refresh_log_view(self):
        """Rebuild the visible log view based on the current filter."""
        self.log_view.clear()
        for severity, message in self._log_entries:
            if self._log_filter_allows(severity):
                self.log_view.append(self._format_log_message(severity, message))
        self._scroll_log_to_bottom()

    def _append_log_entry(self, severity: str, message: str):
        """Store and append a log entry respecting the active filter."""
        self._log_entries.append((severity, message))
        if self._log_filter_allows(severity):
            self.log_view.append(self._format_log_message(severity, message))
            self._scroll_log_to_bottom()

    def _log_filter_allows(self, severity: str) -> bool:
        selected = (self.log_filter_combo.currentText() or "All").upper()
        return selected == "ALL" or selected == severity.upper()

    def _format_log_message(self, severity: str, message: str) -> str:
        upper_severity = severity.upper()
        if upper_severity == "ERROR":
            return f'<font color="red">{message}</font>'
        if upper_severity == "WARNING":
            return f'<font color="orange">{message}</font>'
        return message

    def _scroll_log_to_bottom(self):
        scroll_bar = getattr(self.log_view, "verticalScrollBar", None)
        if callable(scroll_bar):
            scroll_obj = scroll_bar()
        else:
            scroll_obj = None

        if scroll_obj is not None:
            scroll_obj.setValue(scroll_obj.maximum())

    def _determine_log_severity(self, message: str) -> str:
        normalized = message.strip().upper()
        if normalized.startswith("ERROR:"):
            return "ERROR"
        if normalized.startswith("WARNING:") or normalized.startswith("WARN:"):
            return "WARNING"
        if normalized.startswith("STATUS:"):
            return "INFO"
        return "INFO"

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

    def _apply_instruction_visibility(self):
        """Show or hide the quick start instructions based on saved preference."""
        should_show = not self.config_manager.get_setting("hide_instructions", False)
        self.instructions_container.setVisible(should_show)

    def _update_placeholder_visibility(self):
        """Toggle the placeholder overlay based on folder availability and selection."""
        overlay = getattr(self, "_placeholder_overlay", None)
        if overlay is None:
            return

        has_items = self.folder_list_widget.count() > 0
        has_selection = self.folder_list_widget.currentItem() is not None
        should_show = not has_items or not has_selection
        overlay.setVisible(should_show)

        # Ensure the visible widget is on top so the UI stays contextual.
        # If the placeholder should be visible, raise it above the rule controls.
        # Otherwise, bring the rule controls to the front so the folder list and inputs
        # are fully visible (fixes the case where a semi-opaque overlay was drawn over controls).
        try:
            if should_show:
                overlay.raise_()
            else:
                self.rule_controls_widget.raise_()
        except Exception:
            # Some Qt stubs used in tests may not implement raise_; ignore failures there.
            pass

    def _update_rule_summary(self):
        """Update the textual summary of the currently selected rule."""
        summary_label = getattr(self, "rule_summary_label", None)
        if summary_label is None or not hasattr(summary_label, "setText"):
            return

        current_item = self.folder_list_widget.currentItem()
        if current_item is None:
            summary_label.setText(html.escape("Select a monitored folder to see its rule."))
            return

        path = current_item.text()
        stripped_path = path.rstrip("/\\")
        if stripped_path:
            folder_name_candidate = stripped_path.split("/")[-1]
            if "\\" in folder_name_candidate:
                folder_name_candidate = folder_name_candidate.split("\\")[-1]
            folder_name = folder_name_candidate or stripped_path
        else:
            folder_name = path
        folder_name = folder_name or path

        rule = self.config_manager.get_folder_rule(path) if hasattr(self, "config_manager") else None
        if rule is None:
            message = f"No saved rule found for {folder_name}."
            summary_label.setText(html.escape(message))
            return

        if not self.enabledCheckbox.isChecked():
            message = f"Rule for {folder_name} is disabled; matching files will be left untouched."
            summary_label.setText(html.escape(message))
            return

        age_value = self.age_spinbox.value() if hasattr(self, "age_spinbox") else 0
        pattern_raw = self.pattern_lineedit.text().strip() if hasattr(self, "pattern_lineedit") else ""
        use_regex = self.useRegexCheckbox.isChecked() if hasattr(self, "useRegexCheckbox") else False
        logic_value = (self.rule_logic_combo.currentText() if hasattr(self, "rule_logic_combo") else "OR").upper()
        action_text = self.actionComboBox.currentText() if hasattr(self, "actionComboBox") else "Move"
        action_value = ACTION_TEXT_TO_VALUE.get(action_text, action_text.lower())
        destination_text = self.destination_lineedit.text().strip() if hasattr(self, "destination_lineedit") else ""

        if age_value > 0:
            age_phrase = f"at least {age_value} day{'s' if age_value != 1 else ''} old"
        else:
            age_phrase = ""

        if use_regex:
            if pattern_raw:
                pattern_phrase = f"matching the regular expression “{pattern_raw}”"
            else:
                pattern_phrase = "matching an empty regular expression"
        else:
            pattern_value = pattern_raw or "*.*"
            if pattern_value in {"*", "*.*"}:
                pattern_phrase = ""
            else:
                pattern_phrase = f"matching the pattern “{pattern_value}”"

        if age_phrase and pattern_phrase:
            connector = " and " if logic_value == "AND" else " or "
            condition_sentence = f"Files that are {age_phrase}{connector}{pattern_phrase}"
        elif age_phrase:
            condition_sentence = f"Files that are {age_phrase}"
        elif pattern_phrase:
            condition_sentence = f"Files {pattern_phrase}"
        else:
            condition_sentence = "All files"

        if action_value == "move":
            if destination_text:
                action_sentence = f"will be moved to “{destination_text}”."
            else:
                action_sentence = "will be moved using the default destination."
        elif action_value == "copy":
            if destination_text:
                action_sentence = f"will be copied to “{destination_text}”."
            else:
                action_sentence = "will be copied using the default destination."
        elif action_value == "delete_to_trash":
            action_sentence = "will be sent to the recycle bin."
        elif action_value == "delete_permanently":
            action_sentence = "will be permanently deleted."
        else:
            action_sentence = f"will perform the “{action_text}” action."

        summary = f"{folder_name}: {condition_sentence} {action_sentence}"
        summary_label.setText(html.escape(summary))

    def _hide_instructions_permanently(self):
        """Hide the instructions widget and remember the user's choice."""
        self.config_manager.set_setting("hide_instructions", True)
        self.config_manager.save_config()
        self._apply_instruction_visibility()

    def _on_instruction_link_activated(self, link: str):
        """Handle help link clicks from the instructions area."""
        if link == "readme":
            readme_path = os.path.abspath("README.md")
            QDesktopServices.openUrl(QUrl.fromLocalFile(readme_path))

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

        if self.folder_list_widget.count() > 0:
            self.folder_list_widget.setCurrentRow(0)

        self._update_placeholder_visibility()

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
                self._update_placeholder_visibility()
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
                    if self.folder_list_widget.count() > 0:
                        new_row = min(row, self.folder_list_widget.count() - 1)
                        self.folder_list_widget.setCurrentRow(new_row)
                    # Clear/disable inputs if no item is selected
                    if self.folder_list_widget.count() == 0:
                         self.age_spinbox.setEnabled(False)
                         self.pattern_lineedit.setEnabled(False)
                         self.rule_logic_combo.setEnabled(False) # Disable logic combo
                         self.useRegexCheckbox.setEnabled(False) # Disable regex checkbox
                         self.actionComboBox.setEnabled(False) # Disable action combo box
                         self.enabledCheckbox.setEnabled(False)
                         self.age_spinbox.setValue(0)
                         self.pattern_lineedit.clear()
                         self.useRegexCheckbox.setChecked(False) # Uncheck regex checkbox
                         self.rule_logic_combo.setCurrentIndex(0) # Reset logic combo
                         self.actionComboBox.setCurrentIndex(0) # Reset action combo box
                         self.enabledCheckbox.setChecked(False)
                         self.exclusion_list_widget.clear() # Clear exclusions
                         self.exclusion_list_widget.setEnabled(False)
                         self.add_exclusion_button.setEnabled(False)
                         self.remove_exclusion_button.setEnabled(False)
                         self.exclusion_help_button.setEnabled(False) # Disable help button
                         # Explicitly call update_rule_inputs with None when list is empty
                         self.update_rule_inputs(None, None)
                    self._update_placeholder_visibility()
                else:
                     QMessageBox.warning(self, "Error", f"Could not remove folder '{path}' from configuration.")
        else:
            QMessageBox.information(self, "No Selection", "Please select a folder to remove.")

    @pyqtSlot(QListWidgetItem, QListWidgetItem)
    def update_rule_inputs(self, current: QListWidgetItem | None, previous: QListWidgetItem | None): # Allow None
        """Update rule input fields when folder selection changes."""
        self._update_placeholder_visibility()
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
                self.destination_lineedit.blockSignals(True)
                self.enabledCheckbox.blockSignals(True)
                self.exclusion_list_widget.blockSignals(True) # Block exclusion list signals

                self.age_spinbox.setValue(rule.get('age_days', 0))
                self.pattern_lineedit.setText(rule.get('pattern', '*.*'))
                self.rule_logic_combo.setCurrentText(rule.get('rule_logic', 'OR'))
                self.useRegexCheckbox.setChecked(rule.get('use_regex', False)) # Load use_regex

                action_value = rule.get('action', 'move')
                self.actionComboBox.setCurrentText(ACTION_VALUE_TO_TEXT.get(action_value, "Move"))

                self.destination_lineedit.setText(rule.get('destination_folder', ''))

                self.enabledCheckbox.setChecked(rule.get('enabled', True))

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
                self.destination_lineedit.setEnabled(True)
                self.destination_browse_button.setEnabled(True)
                self.enabledCheckbox.setEnabled(True)
                preview_button = getattr(self, "preview_rule_button", None)
                if preview_button is not None and hasattr(preview_button, "setEnabled"):
                    preview_button.setEnabled(True)
                self.exclusion_list_widget.setEnabled(True)
                self.add_exclusion_button.setEnabled(True)
                self.remove_exclusion_button.setEnabled(True)
                self.exclusion_help_button.setEnabled(True) # Enable help button


                self.age_spinbox.blockSignals(False)
                self.pattern_lineedit.blockSignals(False)
                self.rule_logic_combo.blockSignals(False)
                self.useRegexCheckbox.blockSignals(False)
                self.actionComboBox.blockSignals(False) # Unblock actionComboBox signals
                self.destination_lineedit.blockSignals(False)
                self.enabledCheckbox.blockSignals(False)
                self.exclusion_list_widget.blockSignals(False) # Unblock exclusion list signals
                self._update_destination_enabled_state(base_enabled=True)
            else:
                # Should not happen if list is synced with config, but handle defensively
                self.age_spinbox.setEnabled(False)
                self.pattern_lineedit.setEnabled(False)
                self.rule_logic_combo.setEnabled(False)
                self.useRegexCheckbox.setEnabled(False) # Disable checkbox
                self.actionComboBox.setEnabled(False) # Disable actionComboBox
                self.destination_lineedit.setEnabled(False)
                self.destination_browse_button.setEnabled(False)
                self.enabledCheckbox.setEnabled(False)
                preview_button = getattr(self, "preview_rule_button", None)
                if preview_button is not None and hasattr(preview_button, "setEnabled"):
                    preview_button.setEnabled(False)
                self.age_spinbox.setValue(0)
                self.pattern_lineedit.clear()
                self.rule_logic_combo.setCurrentIndex(0)
                self.useRegexCheckbox.setChecked(False) # Uncheck checkbox
                self.actionComboBox.setCurrentIndex(0) # Reset actionComboBox
                self.destination_lineedit.clear()
                self.enabledCheckbox.setChecked(False)
                self.exclusion_list_widget.clear() # Clear exclusions
                self.exclusion_list_widget.setEnabled(False)
                self.add_exclusion_button.setEnabled(False)
                self.remove_exclusion_button.setEnabled(False)
                self.exclusion_help_button.setEnabled(False) # Disable help button
                self._update_destination_enabled_state(base_enabled=False)
        else:
            # No item selected, disable all rule inputs
            self.age_spinbox.setEnabled(False)
            self.pattern_lineedit.setEnabled(False)
            self.rule_logic_combo.setEnabled(False)
            self.useRegexCheckbox.setEnabled(False) # Disable checkbox
            self.actionComboBox.setEnabled(False) # Disable actionComboBox
            self.destination_lineedit.setEnabled(False)
            self.destination_browse_button.setEnabled(False)
            self.enabledCheckbox.setEnabled(False)
            preview_button = getattr(self, "preview_rule_button", None)
            if preview_button is not None and hasattr(preview_button, "setEnabled"):
                preview_button.setEnabled(False)
            self.age_spinbox.setValue(0)
            self.pattern_lineedit.clear()
            self.rule_logic_combo.setCurrentIndex(0)
            self.useRegexCheckbox.setChecked(False)
            self.actionComboBox.setCurrentIndex(0) # Reset actionComboBox
            self.destination_lineedit.clear()
            self.enabledCheckbox.setChecked(False)
            self.exclusion_list_widget.clear() # Clear exclusions
            self.exclusion_list_widget.setEnabled(False)
            self.add_exclusion_button.setEnabled(False)
            self.remove_exclusion_button.setEnabled(False)
            self.exclusion_help_button.setEnabled(False) # Disable help button
            self._update_destination_enabled_state(base_enabled=False)
        self._update_placeholder_visibility()
        self._update_rule_summary()

    def _update_destination_enabled_state(self, base_enabled: bool | None = None):
        """Enable destination controls when editing is allowed and action supports it."""
        if base_enabled is None:
            base_enabled = self.destination_lineedit.isEnabled()

        current_item = self.folder_list_widget.currentItem()
        is_running = self.worker_status in {"Running", "Dry Run Active"}
        action_text = self.actionComboBox.currentText() if self.actionComboBox else "Move"
        action_value = ACTION_TEXT_TO_VALUE.get(action_text, "move")

        can_edit_rules = base_enabled and current_item is not None and not is_running
        allow_destination = can_edit_rules and action_value in {"move", "copy"}

        self.destination_lineedit.setEnabled(allow_destination)
        self.destination_browse_button.setEnabled(allow_destination)


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
            action_value = ACTION_TEXT_TO_VALUE.get(action_text, "move")

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

            rule_enabled = self.enabledCheckbox.isChecked()
            destination_text = self.destination_lineedit.text().strip()

            can_edit_rules = (
                self.folder_list_widget.currentItem() is not None
                and self.worker_status not in {"Running", "Dry Run Active"}
            )
            self._update_destination_enabled_state(base_enabled=can_edit_rules)

            if self.config_manager.update_folder_rule(
                path,
                age,
                pattern,
                rule_logic,
                use_regex,
                action_value,
                exclusions, # Pass exclusions
                destination_folder=destination_text,
                enabled=rule_enabled
            ):
                self.log_queue.put(f"INFO: Updated rules for {path}")
            else:
                # Should not happen if item exists
                self.log_queue.put(f"ERROR: Failed to update rules for {path} (not found in config?)")

        self._update_rule_summary()

    @pyqtSlot()
    def browse_destination_folder(self):
        """Open a dialog to select a destination folder for move/copy actions."""
        if not self.folder_list_widget.currentItem():
            QMessageBox.information(self, "No Folder Selected", "Select a folder before choosing a destination.")
            return

        existing_value = self.destination_lineedit.text().strip()
        start_dir = existing_value or self.folder_list_widget.currentItem().text()
        directory = QFileDialog.getExistingDirectory(self, "Select Destination Folder", start_dir)
        if directory:
            self.destination_lineedit.setText(directory)
            self.save_rule_changes()

    @pyqtSlot()
    def open_settings_dialog(self):
        """Open the settings dialog window."""
        dialog = SettingsDialog(self.config_manager, self) # Pass config manager and parent
        dialog.exec() # Show the dialog modally
        self._update_ui_for_status_and_mode() # Refresh UI after settings change

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
        self.enabledCheckbox.setEnabled(can_edit_rules)
        self.exclusion_list_widget.setEnabled(can_edit_rules)
        self.add_exclusion_button.setEnabled(can_edit_rules)
        self.remove_exclusion_button.setEnabled(can_edit_rules)
        self.exclusion_help_button.setEnabled(can_edit_rules) # Enable/disable help button
        preview_button = getattr(self, "preview_rule_button", None)
        if preview_button is not None and hasattr(preview_button, "setEnabled"):
            preview_button.setEnabled(can_edit_rules)
        self._update_destination_enabled_state(base_enabled=can_edit_rules)
        self.update_status_summary()

    def update_status_summary(self):
        """Refresh the status indicator and summary text based on current configuration."""
        status_text = self.worker_status or "Stopped"
        normalized_status = status_text.lower()

        if "error" in normalized_status:
            indicator_color = "#dc3545"  # Red for error
        elif "dry run" in normalized_status:
            indicator_color = "#0d6efd"  # Blue for dry run
        elif "running" in normalized_status:
            indicator_color = "#28a745"  # Green for running
        elif "stopped" in normalized_status:
            indicator_color = "#6c757d"  # Grey for stopped
        else:
            indicator_color = "#6c757d"  # Default grey

        status_indicator = getattr(self, "status_indicator", None)
        if status_indicator is not None and hasattr(status_indicator, "setStyleSheet"):
            status_indicator.setStyleSheet(
                f"background-color: {indicator_color}; border-radius: 6px; border: 1px solid rgba(0, 0, 0, 0.2);"
            )
        status_label_widget = getattr(self, "status_label", None)
        if status_label_widget is not None and hasattr(status_label_widget, "setText"):
            status_label_widget.setText(status_text)

        if hasattr(self.config_manager, "get_dry_run_mode"):
            dry_run_active = self.config_manager.get_dry_run_mode()
        elif hasattr(self.config_manager, "get_setting"):
            dry_run_active = bool(self.config_manager.get_setting('dry_run_mode', False))
        else:
            dry_run_active = False

        if hasattr(self.config_manager, "get_schedule_config"):
            schedule_config = self.config_manager.get_schedule_config() or {}
        elif hasattr(self.config_manager, "get_setting"):
            schedule_config = {
                'interval_minutes': self.config_manager.get_setting('interval_minutes', 0) or 0
            }
        else:
            schedule_config = {}
        interval_minutes = schedule_config.get('interval_minutes', 0) or 0

        summary_parts = ["Dry Run: On" if dry_run_active else "Dry Run: Off"]
        if interval_minutes > 0:
            next_run_time = datetime.now() + timedelta(minutes=interval_minutes)
            time_display = next_run_time.strftime("%I:%M %p").lstrip("0")
            summary_parts.append(
                f"Next run: in {interval_minutes} min (~{time_display})"
            )
        else:
            summary_parts.append("Next run: Not scheduled")

        summary_label = getattr(self, "status_summary_label", None)
        if summary_label is not None and hasattr(summary_label, "setText"):
            summary_label.setText(" • ".join(summary_parts))

    def _get_selected_folder_path(self) -> Path | None:
        """Return the Path of the currently selected monitored folder."""
        current_item = self.folder_list_widget.currentItem()
        if not current_item:
            return None

        path = Path(current_item.text())
        return path

    @pyqtSlot()
    def preview_rule(self):
        """Show a dialog with a preview of files matching the current rule configuration."""

        folder_path = self._get_selected_folder_path()
        if folder_path is None:
            QMessageBox.information(self, "No Folder Selected", "Select a folder to preview its rule.")
            return

        if not folder_path.exists() or not folder_path.is_dir():
            QMessageBox.warning(
                self,
                "Folder Unavailable",
                (
                    "The selected folder does not exist or is not accessible.\n"
                    "Please verify the folder path before previewing the rule."
                ),
            )
            return

        age_days = self.age_spinbox.value()
        pattern = self.pattern_lineedit.text().strip() or "*.*"
        use_regex = self.useRegexCheckbox.isChecked()
        rule_logic = self.rule_logic_combo.currentText() or "OR"
        destination_text = self.destination_lineedit.text().strip()
        action_value = ACTION_TEXT_TO_VALUE.get(self.actionComboBox.currentText(), "move")

        if use_regex and pattern:
            try:
                re.compile(pattern)
            except re.error as exc:
                QMessageBox.critical(
                    self,
                    "Invalid Regular Expression",
                    f"The provided pattern is not a valid regular expression:\n{exc}",
                )
                return

        if action_value in {"move", "copy"} and destination_text:
            try:
                base_destination = resolve_destination_for_preview(folder_path, destination_text)
            except (ValueError, NotADirectoryError) as exc:
                QMessageBox.critical(self, "Destination Error", str(exc))
                return
            except Exception as exc:  # Catch unexpected resolution errors
                QMessageBox.critical(
                    self,
                    "Destination Error",
                    f"Unable to resolve the destination folder:\n{exc}",
                )
                return

            if not base_destination.exists():
                QMessageBox.warning(
                    self,
                    "Destination Missing",
                    (
                        "The resolved destination folder does not exist:\n"
                        f"{base_destination}\n"
                        "Please create the folder or adjust the destination template."
                    ),
                )
                return

        try:
            matches = get_preview_matches(
                folder_path,
                age_days,
                pattern,
                use_regex,
                rule_logic,
            )
        except (NotADirectoryError, PermissionError) as exc:
            QMessageBox.critical(self, "Preview Failed", str(exc))
            return
        except Exception as exc:  # Catch-all for unexpected issues
            QMessageBox.critical(
                self,
                "Preview Failed",
                f"An unexpected error occurred while previewing the rule:\n{exc}",
            )
            return

        dialog = QMessageBox(self)
        dialog.setWindowTitle("Rule Preview")
        dialog.setIcon(QMessageBox.Icon.Information)

        if matches:
            relative_paths = []
            for match in matches:
                try:
                    relative_paths.append(str(match.relative_to(folder_path)))
                except ValueError:
                    relative_paths.append(str(match))

            displayed_count = len(relative_paths)
            dialog.setText(
                (
                    f"Found {displayed_count} matching file(s) in {folder_path}.\n"
                    "Showing up to 10 results."
                )
            )
            dialog.setInformativeText("\n".join(relative_paths))
        else:
            dialog.setText("No files currently match the configured rule.")
            dialog.setInformativeText(f"Folder checked: {folder_path}")

        dialog.exec()


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
        self.worker_status = "Dry Run Active" if dry_run_active else "Running"
        self._update_ui_for_status_and_mode()
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
            self.worker_status = "Stopping..."
            self._update_ui_for_status_and_mode()
            # self.monitoring_worker.join(timeout=1.0) # Avoid long UI block
            # self.worker_status = "Stopped" # Anticipate
            # self._update_ui_for_status_and_mode()
            # Worker will send "STATUS: Stopped"
        else:
            self.log_queue.put("INFO: Monitoring is not currently running.")
            # self.worker_status = "Stopped" # Ensure consistency
            # self._update_ui_for_status_and_mode()


    def _should_show_notification(self, category: str) -> bool:
        level = self.config_manager.get_notification_level()
        if level == NOTIFICATION_LEVEL_NONE:
            return False
        if level == NOTIFICATION_LEVEL_ERROR:
            return category == "error"
        if level == NOTIFICATION_LEVEL_SUMMARY:
            return category in {"summary", "error"}
        return True

    @pyqtSlot()
    def check_log_queue(self):
        """Check the queue for messages from the worker thread and update UI."""
        try:
            while True: # Process all messages currently in queue
                message = self.log_queue.get_nowait()
                if isinstance(message, dict) and message.get("type") == "SHOW_NOTIFICATION":
                    category = message.get("category", "info")
                    if self._should_show_notification(category):
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
                        print(f"DEBUG: Notification suppressed by level ({category}): {message.get('title')}", file=sys.stderr)
                elif isinstance(message, str) and message.startswith("STATUS:"):
                    reported_status = message.split(":", 1)[1].strip()
                    if reported_status.lower().startswith("running") and self.config_manager.get_dry_run_mode():
                        self.worker_status = "Dry Run Active"
                    else:
                        self.worker_status = reported_status
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


                elif isinstance(message, str): # Ensure only strings are appended directly
                    severity = self._determine_log_severity(message)
                    # STATUS messages are handled above and should not be double logged
                    if not message.startswith("STATUS:"):
                        self._append_log_entry(severity, message)
                else:
                    # Handle or log unexpected message types if necessary
                    print(f"DEBUG: Received unexpected message type in log queue: {type(message)}", file=sys.stderr)

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
                        expanded_folder_path = os.path.expandvars(folder_path)
                        expanded_dest_folder = os.path.expandvars(rule_def.get('destination_folder', ''))

                        # Check if folder already exists in list, if not, add it
                        existing_items_texts = []
                        for i in range(self.folder_list_widget.count()):
                            item = self.folder_list_widget.item(i)
                            if item: # Ensure item is not None before calling text()
                                existing_items_texts.append(item.text())
                        
                        normalized_action = self.config_manager.normalize_action(rule_def.get('action', 'move'))
                        normalized_rule_def = dict(rule_def)
                        normalized_rule_def['action'] = normalized_action
                        normalized_rule_def['destination_folder'] = expanded_dest_folder

                        if expanded_folder_path not in existing_items_texts:
                            if self.config_manager.add_folder(expanded_folder_path, normalized_rule_def): # Add with template rule
                                list_item = QListWidgetItem(expanded_folder_path)
                                self.folder_list_widget.addItem(list_item)
                                folders_added_or_updated.append(expanded_folder_path)
                                self.log_queue.put(f"INFO: Added folder '{expanded_folder_path}' from template '{template_name}'.")
                            else:
                                self.log_queue.put(f"INFO: Folder '{expanded_folder_path}' (from template) likely already in config, attempting to update rule.")

                        update_success = self.config_manager.update_folder_rule(
                            path=expanded_folder_path,
                            age_days=rule_def.get('days_older_than', 0),
                            pattern=rule_def.get('file_pattern', '*.*'),
                            rule_logic=rule_def.get('rule_logic', 'OR'),
                            use_regex=rule_def.get('use_regex', False),
                            action=normalized_action,
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
        """Prompt the user for a new exclusion pattern and add it to the rule."""
        if not self.folder_list_widget.currentItem():
            QMessageBox.information(self, "No Folder Selected", "Select a folder before adding an exclusion pattern.")
            return

        pattern_text, ok = QInputDialog.getText(
            self,
            "Add Exclusion Pattern",
            "Enter a new exclusion pattern:",
        )

        if not ok:
            return

        pattern = pattern_text.strip()
        if not pattern:
            QMessageBox.warning(self, "Invalid Pattern", "The exclusion pattern cannot be empty.")
            return

        existing_patterns = {
            self.exclusion_list_widget.item(i).text()
            for i in range(self.exclusion_list_widget.count())
        }

        if pattern in existing_patterns:
            QMessageBox.information(self, "Duplicate Pattern", "This exclusion pattern already exists.")
            return

        self.exclusion_list_widget.blockSignals(True)
        item = QListWidgetItem(pattern)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.exclusion_list_widget.addItem(item)
        self.exclusion_list_widget.blockSignals(False)

        self.save_rule_changes()
        self.log_queue.put(f"INFO: Added exclusion pattern '{pattern}' for {self.folder_list_widget.currentItem().text()}.")

    def remove_selected_exclusion_pattern(self):
        """Remove the currently selected exclusion pattern after confirmation."""
        if not self.folder_list_widget.currentItem():
            QMessageBox.information(self, "No Folder Selected", "Select a folder before removing an exclusion pattern.")
            return

        current_item = self.exclusion_list_widget.currentItem()
        if not current_item:
            QMessageBox.information(self, "No Pattern Selected", "Select an exclusion pattern to remove.")
            return

        pattern = current_item.text()
        reply = QMessageBox.question(
            self,
            "Remove Exclusion Pattern",
            f"Remove the exclusion pattern '{pattern}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        row = self.exclusion_list_widget.row(current_item)
        self.exclusion_list_widget.takeItem(row)
        self.save_rule_changes()
        self.log_queue.put(f"INFO: Removed exclusion pattern '{pattern}' for {self.folder_list_widget.currentItem().text()}.")

    def show_exclusion_pattern_help(self):
        self.log_queue.put("INFO: Show exclusion pattern help clicked.")

        glob_list_html = "".join(
            f"<li><code>{html.escape(pattern)}</code> – {html.escape(description)}</li>"
            for pattern, description in EXCLUSION_HELP_CONTENT["glob_examples"]
        )
        regex_list_html = "".join(
            f"<li><code>{html.escape(pattern)}</code> – {html.escape(description)}</li>"
            for pattern, description in EXCLUSION_HELP_CONTENT["regex_examples"]
        )
        logic_list_html = "".join(
            f"<li>{html.escape(note)}</li>"
            for note in EXCLUSION_HELP_CONTENT["logic_notes"]
        )

        message_html = (
            f"<p>{html.escape(EXCLUSION_HELP_CONTENT['intro'])}</p>"
            "<h4>Wildcard (glob) examples</h4>"
            f"<ul>{glob_list_html}</ul>"
            "<h4>Regular expression examples</h4>"
            f"<ul>{regex_list_html}</ul>"
            "<h4>How exclusions interact with rule logic</h4>"
            f"<ul>{logic_list_html}</ul>"
            "<p><a href='learn_more_exclusions'>Learn more in the README</a></p>"
        )

        # QMessageBox does not expose a linkActivated signal. Build a small dialog
        # with a QLabel that supports rich text links and connect that signal.
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QDialogButtonBox

        dialog = QDialog(self)
        dialog.setWindowTitle("Exclusion Pattern Help")
        layout = QVBoxLayout(dialog)

        label = QLabel(message_html)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        label.setWordWrap(True)
        # Connect label link clicks to the helper that opens README anchors
        try:
            label.linkActivated.connect(self._open_exclusion_help_link)
        except Exception:
            # If using stubbed Qt in tests, the QLabel may not have linkActivated
            # In that case, ignore the connection to maintain testability.
            pass

        layout.addWidget(label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)

        dialog.exec()

    def _open_exclusion_help_link(self, link: str):
        if link != "learn_more_exclusions":
            return

        readme_path = Path(__file__).resolve().parent / "README.md"
        anchor = EXCLUSION_HELP_CONTENT.get("readme_anchor", "")
        url = QUrl.fromLocalFile(str(readme_path))
        if anchor:
            url.setFragment(anchor.lstrip("#"))
        QDesktopServices.openUrl(url)

    def save_exclusion_list_changes(self, item: QListWidgetItem):
        if item:
            self.log_queue.put(f"INFO: Updated exclusion pattern to '{item.text()}'.")
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
