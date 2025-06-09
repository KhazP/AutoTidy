import json
import shutil
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QPushButton,
    QAbstractItemView, QHBoxLayout, QHeaderView, QMessageBox
)
from PyQt6.QtGui import QKeySequence # Added
from PyQt6.QtCore import Qt
import constants # Assuming constants.py contains ACTION_MOVED and STATUS_SUCCESS

# ConfigManager is not directly imported if only its path method is used via a passed instance.

class HistoryViewerDialog(QDialog):
    """Dialog to view action history from the JSONL file."""

    def __init__(self, config_manager, history_manager, parent=None): # config_manager and history_manager instances
        super().__init__(parent)
        self.config_manager = config_manager
        self.history_manager = history_manager

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
        header = self.historyTable.horizontalHeader()
        if header:
            header.setSectionResizeMode(self.column_headers.index("Details"), QHeaderView.ResizeMode.Stretch)
            # Allow manual resize for other columns initially, then resize to contents
            for i in range(len(self.column_headers)):
                if i != self.column_headers.index("Details"):
                    header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)

        layout.addWidget(self.historyTable)

        # Buttons Layout
        buttons_layout = QHBoxLayout()

        self.undoButton = QPushButton("&Undo Selected Action") # Added &
        self.undoButton.setToolTip("Undo the selected file operation (Ctrl+Z if focus is on table/button)")
        self.undoButton.clicked.connect(self.handle_undo_action)
        buttons_layout.addWidget(self.undoButton)

        buttons_layout.addStretch(1) # Add stretch before refresh to push undo to left

        self.refreshButton = QPushButton("&Refresh") # Added &
        self.refreshButton.setToolTip("Reload the action history (F5)")
        self.refreshButton.clicked.connect(self.load_history)
        buttons_layout.addWidget(self.refreshButton)

        buttons_layout.addStretch(1) # Add stretch between refresh and close

        self.closeButton = QPushButton("&Close") # Added &
        self.closeButton.setToolTip("Close this window (Esc)")
        self.closeButton.clicked.connect(self.accept)
        buttons_layout.addWidget(self.closeButton)

        layout.addLayout(buttons_layout)

        self.historyTable.itemSelectionChanged.connect(self.update_undo_button_state)

        self.load_history()
        self.update_undo_button_state() # Initial state
        self._setup_shortcuts() # Call new method
        self.historyTable.setFocus() # Set initial focus

    def _setup_shortcuts(self):
        """Setup keyboard shortcuts."""
        self.refreshButton.setShortcut(QKeySequence(Qt.Key.Key_F5))
        # Undo shortcut can be tricky if it needs context (which item is selected)
        # A common pattern is Ctrl+Z. We can add it to the button.
        # For it to work globally in the dialog when the table has focus, 
        # we might need to catch it in keyPressEvent of the dialog or table.
        self.undoButton.setShortcut(QKeySequence("Ctrl+Z")) 
        # Close on Escape is usually default for QDialog.accepted/rejected
        # self.closeButton.setShortcut(QKeySequence(Qt.Key.Key_Escape)) # QDialog handles Esc for reject/close

    def keyPressEvent(self, event):
        """Handle key presses for actions like Escape."""
        if event.key() == Qt.Key.Key_Escape:
            self.accept() # Close on Escape
        elif event.key() == Qt.Key.Key_F5:
            self.load_history() # Refresh on F5
        # Ctrl+Z for undo if table has focus and an item is undoable
        elif event.matches(QKeySequence.StandardKey.Undo): # Checks for Ctrl+Z or platform equivalent
            if self.undoButton.isEnabled():
                self.handle_undo_action()
        else:
            super().keyPressEvent(event)

    def handle_undo_action(self):
        selection_model = self.historyTable.selectionModel()
        if not selection_model:
            QMessageBox.warning(self, "Undo Action", "Cannot get selection model.")
            return

        selected_rows = selection_model.selectedRows()
        if not selected_rows or len(selected_rows) != 1:
            # This case should ideally be prevented by the button's enabled state,
            # but as a safeguard:
            QMessageBox.warning(self, "Undo Action", "Please select exactly one action to undo.")
            return

        selected_row_index = selected_rows[0].row()

        try:
            original_path_item = self.historyTable.item(selected_row_index, self.column_headers.index("Original Path"))
            destination_path_item = self.historyTable.item(selected_row_index, self.column_headers.index("Destination Path"))

            if not original_path_item or not destination_path_item:
                QMessageBox.critical(self, "Error", "Could not retrieve path information for the selected action.")
                return

            original_path_str = original_path_item.text()
            destination_path_str = destination_path_item.text()

            if not original_path_str or not destination_path_str:
                QMessageBox.critical(self, "Error", "Path information is missing for the selected action.")
                return

            original_path_target = Path(original_path_str)
            destination_file = Path(destination_path_str)

            # Pre-move checks
            if not destination_file.exists():
                QMessageBox.warning(self, "Undo Failed", f"The file to undo does not exist: {destination_file}")
                self.load_history() # Refresh history, as the file's status might have changed
                return

            if original_path_target.exists():
                if original_path_target.is_file():
                    reply = QMessageBox.question(self, "Confirm Overwrite",
                                                 f"The original file location '{original_path_target}' already exists. Overwrite?",
                                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                                 QMessageBox.StandardButton.No)
                    if reply == QMessageBox.StandardButton.No:
                        return
                elif original_path_target.is_dir():
                    QMessageBox.critical(self, "Undo Failed",
                                         f"Cannot restore file. The original path '{original_path_target}' is now a directory.")
                    return

            # Perform the move
            try:
                # Ensure parent directory of original_path_target exists
                original_path_target.parent.mkdir(parents=True, exist_ok=True)

                shutil.move(str(destination_file), str(original_path_target))

                # Log the undo action
                log_data = {
                    "action_taken": constants.ACTION_UNDO_MOVE,
                    "original_path": str(destination_file), # Path before undo (what was moved)
                    "destination_path": str(original_path_target), # Path after undo (where it went)
                    "status": constants.STATUS_SUCCESS,
                    "details": f"Successfully undid previous move of '{destination_file.name}'. Moved from '{destination_file}' to '{original_path_target}'.",
                }
                self.history_manager.log_action(log_data)

                QMessageBox.information(self, "Success", f"Action undone. File moved from '{destination_file}' back to '{original_path_target}'.")

                self.load_history() # Refresh history to show the UNDO_MOVE entry

            except (IOError, OSError) as e:
                QMessageBox.critical(self, "Move Error", f"Error moving file: {e}")
            except Exception as e:
                QMessageBox.critical(self, "Unexpected Error", f"An unexpected error occurred: {e}")

        except IndexError:
             QMessageBox.critical(self, "Error", "Could not correctly interpret history data for undo.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"An unexpected error occurred during undo preparation: {e}")
        finally:
            self.update_undo_button_state()


    def update_undo_button_state(self):
        selected_items = self.historyTable.selectedItems()
        selection_model = self.historyTable.selectionModel()

        if not selection_model:
            self.undoButton.setEnabled(False)
            return

        if not selected_items or len(selection_model.selectedRows()) != 1:
            self.undoButton.setEnabled(False)
            return

        selected_row = self.historyTable.currentRow()
        if selected_row < 0: # Should not happen if selected_items is not empty and 1 row selected
            self.undoButton.setEnabled(False)
            return

        try:
            action_item = self.historyTable.item(selected_row, self.column_headers.index("Action Taken"))
            status_item = self.historyTable.item(selected_row, self.column_headers.index("Status"))

            if action_item and status_item:
                action_text = action_item.text()
                status_text = status_item.text()

                # Assuming constants.ACTION_MOVED and constants.STATUS_SUCCESS are defined
                # e.g., ACTION_MOVED = "MOVED", STATUS_SUCCESS = "SUCCESS"
                if action_text == constants.ACTION_MOVED and status_text == constants.STATUS_SUCCESS:
                    self.undoButton.setEnabled(True)
                else:
                    self.undoButton.setEnabled(False)
            else:
                self.undoButton.setEnabled(False)
        except IndexError:
            # This might happen if column_headers doesn't contain "Action Taken" or "Status"
            # Or if the row/column index is somehow out of bounds despite checks.
            print("Error: Could not find 'Action Taken' or 'Status' column for undo logic.")
            self.undoButton.setEnabled(False)
        except Exception as e:
            print(f"Error updating undo button state: {e}")
            self.undoButton.setEnabled(False)


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
        self.update_undo_button_state() # Update button state after loading history


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
