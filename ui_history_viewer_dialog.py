import json
import shutil
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QPushButton,
    QAbstractItemView, QHBoxLayout, QHeaderView, QMessageBox
)
from PyQt6.QtCore import Qt
import constants # Assuming constants.py contains ACTION_MOVED and STATUS_SUCCESS

# ConfigManager is not directly imported if only its path method is used via a passed instance.

class HistoryViewerDialog(QDialog):
    """
    A dialog for viewing the action history of the AutoTidy application.
    It displays logged actions from a JSONL file in a sortable table.
    This dialog is intended as a read-only viewer. For undo functionality,
    the UndoDialog should be used.
    """

    def __init__(self, config_manager, history_manager, parent=None):
        """
        Initializes the HistoryViewerDialog.

        Args:
            config_manager: An instance of ConfigManager, used to locate the history file.
            history_manager: An instance of HistoryManager (though not directly used in this
                             version, it's kept for potential future enhancements like filtering).
            parent: The parent widget, if any.
        """
        super().__init__(parent)
        self.config_manager = config_manager
        self.history_manager = history_manager # Kept for consistency, though not directly used

        self.setWindowTitle("AutoTidy Action History (Read-Only)")
        self.setMinimumSize(800, 400)

        layout = QVBoxLayout(self)

        # Table Widget
        self.historyTable = QTableWidget()
        self.column_headers = [
            "Timestamp", "Action Taken", "Original Path", "Destination Path",
            "Status", "Details", "Monitored Folder", "Rule Pattern",
            "Rule Age", "Rule Regex"
            # Consider adding "Rule Action Config" if useful
        ]
        self.historyTable.setColumnCount(len(self.column_headers))
        self.historyTable.setHorizontalHeaderLabels(self.column_headers)
        self.historyTable.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers) # Read-only
        self.historyTable.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.historyTable.setSortingEnabled(True)
        # Stretch last column (Details)
        self.historyTable.horizontalHeader().setSectionResizeMode(self.column_headers.index("Details"), QHeaderView.ResizeMode.Stretch)
        # Allow manual resize for other columns initially, then resize to contents
        for i in range(len(self.column_headers)):
            if i != self.column_headers.index("Details"):
                 self.historyTable.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)


        layout.addWidget(self.historyTable)

        # Buttons Layout
        buttons_layout = QHBoxLayout()
        # self.undoButton = QPushButton("Undo Selected Action") # Removed
        # self.undoButton.clicked.connect(self.handle_undo_action) # Removed
        # buttons_layout.addWidget(self.undoButton) # Removed

        buttons_layout.addStretch(1) # Add stretch to push remaining buttons to right

        self.refreshButton = QPushButton("Refresh")
        self.refreshButton.clicked.connect(self.load_history)
        buttons_layout.addWidget(self.refreshButton)

        # buttons_layout.addStretch(1) # Stretch between refresh and close, or remove if only two buttons
        self.closeButton = QPushButton("Close")
        self.closeButton.clicked.connect(self.accept)
        buttons_layout.addWidget(self.closeButton)

        layout.addLayout(buttons_layout)

        # self.historyTable.itemSelectionChanged.connect(self.update_undo_button_state) # Removed

        self.load_history()
        # self.update_undo_button_state() # Removed: No undo button state to update

    # def handle_undo_action(self): # Removed
        # ... (entire method removed) ...

    # def update_undo_button_state(self): # Removed
        # ... (entire method removed) ...

    def load_history(self):
        """
        Loads action history data from the `autotidy_history.jsonl` file,
        populates the table with this data, and applies default sorting.
        User is notified via QMessageBox if the history file is not found,
        cannot be read, or contains malformed entries.
        """
        self.historyTable.setSortingEnabled(False) # Disable sorting during load for performance
        self.historyTable.setRowCount(0) # Clear table

        history_file_path = self.config_manager.get_config_dir_path() / "autotidy_history.jsonl"

        if not history_file_path.exists():
            QMessageBox.information(self, "History Information", f"History file not found: {history_file_path}\nNo actions logged yet or file has been moved/deleted.")
            self.historyTable.setSortingEnabled(True)
            return

        try:
            with open(history_file_path, 'r', encoding='utf-8') as f:
                for line_number, line in enumerate(f):
                    try:
                        log_entry = json.loads(line.strip())
                        if not isinstance(log_entry, dict):
                            QMessageBox.warning(self, "History Load Warning",
                                                f"Skipping non-dictionary entry in history file at line {line_number + 1}.")
                            continue

                        row_position = self.historyTable.rowCount()
                        self.historyTable.insertRow(row_position)

                        # Populate cells based on headers - this ensures order and handles missing keys
                        for col_idx, header_key_original in enumerate(self.column_headers):
                            # Convert header to snake_case for dictionary lookup if necessary,
                            # or ensure log_entry keys match headers directly (preferable)
                            # Current log_entry keys are already snake_case and match these well if we map.
                            key_map = {
                                "Timestamp": "timestamp",
                                "Action Taken": "action_taken",
                                "Original Path": "original_path",
                                "Destination Path": "destination_path",
                                "Status": "status",
                                "Details": "details",
                                "Monitored Folder": "monitored_folder",
                                "Rule Pattern": "rule_pattern",
                                "Rule Age": "rule_age_days", # dict key is rule_age_days
                                "Rule Regex": "rule_use_regex" # dict key is rule_use_regex
                            }
                            dict_key = key_map.get(header_key_original, header_key_original.lower().replace(" ", "_"))
                            cell_value = str(log_entry.get(dict_key, '')) # Default to empty string if key missing

                            item = QTableWidgetItem(cell_value)
                            # Timestamps can be long, consider special handling if needed
                            self.historyTable.setItem(row_position, col_idx, item)

                    except json.JSONDecodeError:
                        QMessageBox.warning(self, "History Load Warning",
                                            f"Skipping malformed JSON line in history file at line {line_number + 1}: {line.strip()}")
                    except Exception as e_inner:
                        QMessageBox.warning(self, "History Load Error",
                                            f"Error processing history entry at line {line_number + 1}: {e_inner}")

        except IOError as e:
            QMessageBox.critical(self, "History File Error", f"Error reading history file {history_file_path}: {e}")
        except Exception as e_outer:
            QMessageBox.critical(self, "History Load Error", f"Unexpected error loading history: {e_outer}")

        self.historyTable.resizeColumnsToContents()
        # Re-enable sorting after data is loaded
        self.historyTable.setSortingEnabled(True)
        # Default sort by timestamp, descending
        timestamp_col_index = self.column_headers.index("Timestamp")
        if timestamp_col_index != -1:
            self.historyTable.sortByColumn(timestamp_col_index, Qt.SortOrder.DescendingOrder)
        # self.update_undo_button_state() # Removed: No undo button state to update


if __name__ == '__main__':
    # This is for direct testing of the dialog
    from PyQt6.QtWidgets import QApplication
    import sys
    from history_manager import HistoryManager # Required for mock testing

    # Mock ConfigManager and HistoryManager for testing HistoryViewerDialog standalone
    class MockConfigManager:
        def get_config_dir_path(self):
            test_dir = Path(".") # Current directory for test
            # Create a dummy history file for testing if it doesn't exist
            dummy_history_file = test_dir / "autotidy_history.jsonl"
            if not dummy_history_file.exists():
                 with open(dummy_history_file, 'w', encoding='utf-8') as f:
                    log1 = {"timestamp": "2023-01-01T10:00:00Z", "action_taken": "MOVED", "original_path": str(test_dir / "file1_original.txt"), "destination_path": str(test_dir / "file1_moved.txt"), "status": "SUCCESS", "details": "Moved to archive"}
                    f.write(json.dumps(log1) + '\n')
            # Create dummy files for undo testing
            (test_dir / "file1_moved.txt").touch(exist_ok=True)

            return test_dir

    app = QApplication(sys.argv)
    mock_cm = MockConfigManager()
    # HistoryManager needs a config_manager instance
    mock_hm = HistoryManager(mock_cm)

    dialog = HistoryViewerDialog(mock_cm, mock_hm) # Pass both mocks
    dialog.show()
    exit_code = app.exec()

    # Clean up dummy files
    config_dir = mock_cm.get_config_dir_path()
    (config_dir / "autotidy_history.jsonl").unlink(missing_ok=True)
    (config_dir / "file1_moved.txt").unlink(missing_ok=True)
    (config_dir / "file1_original.txt").unlink(missing_ok=True) # If undo was tested

    sys.exit(exit_code)
