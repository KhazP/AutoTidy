from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QLineEdit,
    QCheckBox, QComboBox, QPushButton, QDialogButtonBox, QWidget
)
from PyQt6.QtCore import pyqtSlot

class RuleEditorDialog(QDialog):
    """Dialog for editing a folder's rule."""

    def __init__(self, current_rule_data: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.current_rule_data = current_rule_data
        # current_rule_data should include 'path' to identify the folder
        # and other rule fields like 'age_days', 'pattern', etc.

        folder_path = self.current_rule_data.get('path', 'N/A')
        self.setWindowTitle(f"Edit Rule for: {folder_path}")
        self.setMinimumWidth(450) # Set a reasonable minimum width

        self._init_ui()
        self.load_rule_data()

    def _init_ui(self):
        """Initialize UI elements and layout."""
        main_layout = QVBoxLayout(self)

        # Folder Path Display (Non-Editable)
        # Path is part of current_rule_data and shouldn't be edited here.
        # If needed, it can be displayed as a label.
        if self.current_rule_data and 'path' in self.current_rule_data:
             path_label = QLabel(f"<b>Folder:</b> {self.current_rule_data['path']}")
             main_layout.addWidget(path_label)

        # Min Age
        age_layout = QHBoxLayout()
        age_layout.addWidget(QLabel("Min Age (days):"))
        self.age_spinbox = QSpinBox()
        self.age_spinbox.setRange(0, 3650)  # 0 to 10 years
        age_layout.addWidget(self.age_spinbox)
        main_layout.addLayout(age_layout)

        # Filename Pattern
        pattern_layout = QHBoxLayout()
        pattern_layout.addWidget(QLabel("Filename Pattern:"))
        self.pattern_lineedit = QLineEdit()
        self.pattern_lineedit.setPlaceholderText("*.*")
        pattern_layout.addWidget(self.pattern_lineedit)
        main_layout.addLayout(pattern_layout)

        # Use Regular Expression Checkbox
        self.useRegexCheckbox = QCheckBox("Use Regular Expression")
        main_layout.addWidget(self.useRegexCheckbox)

        # Rule Logic (AND/OR)
        logic_layout = QHBoxLayout()
        logic_layout.addWidget(QLabel("File matches if Age AND/OR Pattern is met:"))
        self.rule_logic_combo = QComboBox()
        self.rule_logic_combo.addItems(["OR", "AND"])
        logic_layout.addWidget(self.rule_logic_combo)
        main_layout.addLayout(logic_layout)

        # Action ComboBox
        action_layout = QHBoxLayout()
        action_layout.addWidget(QLabel("Action:"))
        self.actionComboBox = QComboBox()
        self.actionComboBox.addItems(["Move", "Copy", "Delete to Trash", "Delete Permanently"])
        action_layout.addWidget(self.actionComboBox)
        main_layout.addLayout(action_layout)

        # Dialog Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

    def load_rule_data(self):
        """Populate input fields with current rule data."""
        if not self.current_rule_data:
            # Set defaults if creating a new rule (though this dialog is for editing)
            # This part might be more relevant if the dialog was also for "Add New Rule from scratch"
            self.age_spinbox.setValue(0)
            self.pattern_lineedit.setText("*.*")
            self.useRegexCheckbox.setChecked(False)
            self.rule_logic_combo.setCurrentIndex(0) # OR
            self.actionComboBox.setCurrentIndex(0)   # Move
            return

        self.age_spinbox.setValue(self.current_rule_data.get('age_days', 0))
        self.pattern_lineedit.setText(self.current_rule_data.get('pattern', '*.*'))
        self.useRegexCheckbox.setChecked(self.current_rule_data.get('use_regex', False))
        self.rule_logic_combo.setCurrentText(self.current_rule_data.get('rule_logic', 'OR'))

        action_value = self.current_rule_data.get('action', 'move')
        # Map stored value to display text for QComboBox
        action_display_map = {
            "move": "Move",
            "copy": "Copy",
            "delete_to_trash": "Delete to Trash",
            "delete_permanently": "Delete Permanently"
        }
        self.actionComboBox.setCurrentText(action_display_map.get(action_value, "Move"))

    def get_rule_data(self) -> dict:
        """Collect values from input fields and return as a dictionary."""
        # Map display text from QComboBox back to stored value
        action_text = self.actionComboBox.currentText()
        action_map_to_value = {
            "Move": "move",
            "Copy": "copy",
            "Delete to Trash": "delete_to_trash",
            "Delete Permanently": "delete_permanently"
        }

        return {
            # Path is not edited here, but pass it back so ConfigManager knows which rule to update
            'path': self.current_rule_data.get('path'),
            'age_days': self.age_spinbox.value(),
            'pattern': self.pattern_lineedit.text(),
            'use_regex': self.useRegexCheckbox.isChecked(),
            'rule_logic': self.rule_logic_combo.currentText(),
            'action': action_map_to_value.get(action_text, "move")
        }

    # Optional: Add accept method for validation if needed
    # def accept(self):
    #     # Basic validation example
    #     if not self.pattern_lineedit.text():
    #         QMessageBox.warning(self, "Validation Error", "Pattern cannot be empty.")
    #         return # Keep dialog open
    #     super().accept()

```
