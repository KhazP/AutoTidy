import json
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QPushButton,
    QAbstractItemView, QHBoxLayout, QHeaderView
)
from PyQt6.QtCore import Qt
# ConfigManager is not directly imported if only its path method is used via a passed instance.

class HistoryViewerDialog(QDialog):
    """Dialog to view action history from the JSONL file."""

    def __init__(self, config_manager, parent=None): # config_manager is an instance of ConfigManager
        super().__init__(parent)
        self.config_manager = config_manager

        self.setWindowTitle("AutoTidy Action History")
        self.setMinimumSize(800, 400) # Set a reasonable minimum size

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
        self.refreshButton = QPushButton("Refresh")
        self.refreshButton.clicked.connect(self.load_history)
        buttons_layout.addWidget(self.refreshButton)
        buttons_layout.addStretch()
        self.closeButton = QPushButton("Close")
        self.closeButton.clicked.connect(self.accept)
        buttons_layout.addWidget(self.closeButton)

        layout.addLayout(buttons_layout)

        self.load_history()

    def load_history(self):
        """Loads history from the JSONL file into the table."""
        self.historyTable.setSortingEnabled(False) # Disable sorting during load for performance
        self.historyTable.setRowCount(0) # Clear table

        history_file_path = self.config_manager.get_config_dir_path() / "autotidy_history.jsonl"

        if not history_file_path.exists():
            # Optionally show a message in the table or a status bar
            # For now, just means an empty table, which is fine.
            print(f"History file not found: {history_file_path}")
            self.historyTable.setSortingEnabled(True)
            return

        try:
            with open(history_file_path, 'r', encoding='utf-8') as f:
                for line_number, line in enumerate(f):
                    try:
                        log_entry = json.loads(line.strip())
                        if not isinstance(log_entry, dict):
                            print(f"Warning: Skipping non-dict entry in history file at line {line_number + 1}")
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
                        print(f"Warning: Skipping malformed JSON line in history file at line {line_number + 1}: {line.strip()}")
                    except Exception as e_inner:
                        print(f"Error processing history entry at line {line_number + 1}: {e_inner}")


        except IOError as e:
            print(f"Error reading history file {history_file_path}: {e}")
            # Show error to user? For now, console.
        except Exception as e_outer:
            print(f"Unexpected error loading history: {e_outer}")

        self.historyTable.resizeColumnsToContents()
        # Re-enable sorting after data is loaded
        self.historyTable.setSortingEnabled(True)
        # Default sort by timestamp, descending
        timestamp_col_index = self.column_headers.index("Timestamp")
        if timestamp_col_index != -1:
            self.historyTable.sortByColumn(timestamp_col_index, Qt.SortOrder.DescendingOrder)


if __name__ == '__main__':
    # This is for direct testing of the dialog
    from PyQt6.QtWidgets import QApplication
    import sys

    # Mock ConfigManager for testing HistoryViewerDialog standalone
    class MockConfigManager:
        def get_config_dir_path(self):
            test_dir = Path(".") # Current directory for test
            # Create a dummy history file for testing
            dummy_history_file = test_dir / "autotidy_history.jsonl"
            with open(dummy_history_file, 'w', encoding='utf-8') as f:
                # Sample log entries
                log1 = {"timestamp": "2023-01-01T10:00:00Z", "action_taken": "MOVED", "original_path": "/test/file1.txt", "status": "SUCCESS", "details": "Moved to /archive/file1.txt"}
                log2 = {"timestamp": "2023-01-01T10:05:00Z", "action_taken": "DELETED_TO_TRASH", "original_path": "/test/file2.txt", "status": "SUCCESS", "details": "Sent to trash"}
                log3 = {"timestamp": "2023-01-01T10:02:00Z", "action_taken": "SIMULATED_COPY", "original_path": "/test/file3.dat", "status": "SUCCESS", "details": "[DRY RUN] Would copy to /archive/file3.dat", "rule_age_days": 5, "rule_pattern": "*.dat"}

                f.write(json.dumps(log1) + '\n')
                f.write(json.dumps(log2) + '\n')
                f.write(json.dumps(log3) + '\n')
            return test_dir

    app = QApplication(sys.argv)
    # Ensure you have a ConfigManager instance or a mock
    mock_cm = MockConfigManager()
    dialog = HistoryViewerDialog(mock_cm)
    dialog.show()
    exit_code = app.exec()
    # Clean up dummy file
    (mock_cm.get_config_dir_path() / "autotidy_history.jsonl").unlink(missing_ok=True)
    sys.exit(exit_code)
