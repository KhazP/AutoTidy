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
            "Rule Age", "Rule Regex", "Batch ID" # Added Batch ID
            # Consider adding "Rule Action Config" if useful
        ]
        # Ensure column count matches new headers length
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

        self.undoButton = QPushButton("Undo Selected Action")
        self.undoButton.clicked.connect(self.handle_undo_action)
        buttons_layout.addWidget(self.undoButton)

        self.undoBatchButton = QPushButton("Undo Entire Batch")
        self.undoBatchButton.clicked.connect(self.handle_batch_undo_action) # Connect later
        self.undoBatchButton.setEnabled(False) # Initially disabled
        buttons_layout.addWidget(self.undoBatchButton)

        buttons_layout.addStretch(1) # Add stretch to push buttons to the left

        self.refreshButton = QPushButton("Refresh")
        self.refreshButton.clicked.connect(self.load_history)
        buttons_layout.addWidget(self.refreshButton)

        buttons_layout.addStretch(1) # Add stretch between refresh and close

        self.closeButton = QPushButton("Close")
        self.closeButton.clicked.connect(self.accept)
        buttons_layout.addWidget(self.closeButton)

        layout.addLayout(buttons_layout)

        self.historyTable.itemSelectionChanged.connect(self.update_undo_button_state)
        self.historyTable.itemSelectionChanged.connect(self.update_undo_batch_button_state) # Connect new handler

        self.load_history()
        self.update_undo_button_state() # Initial state for single undo
        self.update_undo_batch_button_state() # Initial state for batch undo

    def handle_batch_undo_action(self):
        selected_rows = self.historyTable.selectionModel().selectedRows()
        if not selected_rows or len(selected_rows) != 1:
            QMessageBox.warning(self, "Batch Undo", "Please select a single row to identify the batch.")
            return

        selected_row_idx = selected_rows[0].row()

        try:
            batch_id_col = self.column_headers.index("Batch ID")
            action_col = self.column_headers.index("Action Taken")
            status_col = self.column_headers.index("Status")
            orig_path_col = self.column_headers.index("Original Path")
            dest_path_col = self.column_headers.index("Destination Path")
        except ValueError:
            QMessageBox.critical(self, "Error", "One or more required columns are missing in the table setup.")
            return

        selected_batch_id_item = self.historyTable.item(selected_row_idx, batch_id_col)
        if not selected_batch_id_item or not selected_batch_id_item.text():
            QMessageBox.warning(self, "Batch Undo", "The selected action does not have a Batch ID.")
            return

        target_batch_id = selected_batch_id_item.text()

        actions_to_undo = []
        all_history_entries = [] # To check for existing UNDO_MOVE

        for row_num in range(self.historyTable.rowCount()):
            entry_action = self.historyTable.item(row_num, action_col).text()
            entry_orig_path = self.historyTable.item(row_num, orig_path_col).text()
            entry_dest_path = self.historyTable.item(row_num, dest_path_col).text()
            all_history_entries.append({
                "action_taken": entry_action,
                "original_path": entry_orig_path,
                "destination_path": entry_dest_path
            })

            current_row_batch_id_item = self.historyTable.item(row_num, batch_id_col)
            if current_row_batch_id_item and current_row_batch_id_item.text() == target_batch_id:
                status_item = self.historyTable.item(row_num, status_col)

                if (entry_action == constants.ACTION_MOVED and
                    status_item and status_item.text() == constants.STATUS_SUCCESS):

                    # Check if this MOVED action has already been undone
                    already_undone = False
                    for hist_entry in all_history_entries:
                        if (hist_entry["action_taken"] == constants.ACTION_UNDO_MOVE and
                            hist_entry["original_path"] == entry_dest_path and  # UNDO's original is MOVED's destination
                            hist_entry["destination_path"] == entry_orig_path): # UNDO's destination is MOVED's original
                            already_undone = True
                            break

                    if not already_undone:
                        actions_to_undo.append({
                            "original_path_target_str": entry_orig_path, # Where it was originally, and will be moved back to
                            "destination_file_str": entry_dest_path,   # Where it is now, and will be moved from
                            "row": row_num # For reference, not strictly used in move logic
                        })

        if not actions_to_undo:
            QMessageBox.information(self, "Batch Undo", f"No eligible 'MOVED' actions found to undo for Batch ID: {target_batch_id}.")
            return

        success_count = 0
        error_list = []

        for action_detail in actions_to_undo:
            original_path_target = Path(action_detail["original_path_target_str"])
            destination_file = Path(action_detail["destination_file_str"])

            if not destination_file.exists():
                error_list.append(f"File to undo does not exist: {destination_file}")
                continue

            if original_path_target.exists():
                # Skip if original path is occupied by a file or directory (Option A)
                error_list.append(f"Original path '{original_path_target}' is occupied. Skipped.")
                continue

            try:
                original_path_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destination_file), str(original_path_target))
                success_count += 1

                log_data = {
                    "action_taken": constants.ACTION_UNDO_MOVE,
                    "original_path": str(destination_file), # Path before this undo
                    "destination_path": str(original_path_target), # Path after this undo
                    "status": constants.STATUS_SUCCESS,
                    "details": f"Part of batch undo for Batch ID: {target_batch_id}. Original move of '{destination_file.name}'.",
                    # "batch_id": target_batch_id # Optional: associate undo with the batch
                }
                self.history_manager.log_action(log_data) # Not passing batch_id to the UNDO_MOVE itself

            except (IOError, OSError) as e:
                error_list.append(f"Error moving {destination_file.name}: {e}")
            except Exception as e:
                error_list.append(f"Unexpected error for {destination_file.name}: {e}")

        summary_message = f"Batch Undo Complete for Batch ID: {target_batch_id}\n\n"
        summary_message += f"Successfully undid {success_count} file(s).\n"
        if error_list:
            summary_message += f"\nEncountered {len(error_list)} error(s):\n"
            summary_message += "\n".join([f" - {err}" for err in error_list[:10]]) # Show up to 10 errors
            if len(error_list) > 10:
                summary_message += f"\n - ...and {len(error_list) - 10} more."

        QMessageBox.information(self, "Batch Undo Summary", summary_message)

        self.load_history()
        # update_undo_button_state and update_undo_batch_button_state are called in finally in load_history
        # but load_history calls them before this method returns.
        # Explicitly call them here if load_history doesn't or if state needs refresh before dialog closes.
        # However, since load_history already calls them, this might be redundant, but safe.

        # The `finally` block for these updates will be outside this try-except-finally structure.
        # The main structure of this method should ensure they are called.
        # For now, relying on load_history to trigger them. If issues, add explicit calls.

    def handle_undo_action(self):
        selected_rows = self.historyTable.selectionModel().selectedRows()
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
            # Batch button state might also need update if an undo changes eligibility of batch
            self.update_undo_batch_button_state()


    def update_undo_button_state(self):
        selected_items = self.historyTable.selectedItems()
        if not selected_items or len(self.historyTable.selectionModel().selectedRows()) != 1:
            self.undoButton.setEnabled(False)
            return

        selected_row = self.historyTable.currentRow()
        if selected_row < 0: # Should not happen if selected_items is not empty and 1 row selected
            self.undoButton.setEnabled(False)
            return

        try:
            action_idx = self.column_headers.index("Action Taken")
            status_idx = self.column_headers.index("Status")

            action_item = self.historyTable.item(selected_row, action_idx)
            status_item = self.historyTable.item(selected_row, status_idx)

            if action_item and status_item:
                action_text = action_item.text()
                status_text = status_item.text()

                if action_text == constants.ACTION_MOVED and status_text == constants.STATUS_SUCCESS:
                    self.undoButton.setEnabled(True)
                else:
                    self.undoButton.setEnabled(False)
            else:
                self.undoButton.setEnabled(False)
        except ValueError: # If "Action Taken" or "Status" not in column_headers
            print("Error: 'Action Taken' or 'Status' column not found.")
            self.undoButton.setEnabled(False)
        except Exception as e:
            print(f"Error updating undo button state: {e}")
            self.undoButton.setEnabled(False)

    def update_undo_batch_button_state(self):
        selected_items = self.historyTable.selectedItems()
        if not selected_items or len(self.historyTable.selectionModel().selectedRows()) != 1:
            self.undoBatchButton.setEnabled(False)
            return

        selected_row_idx = self.historyTable.currentRow()
        if selected_row_idx < 0:
            self.undoBatchButton.setEnabled(False)
            return

        try:
            batch_id_col_idx = self.column_headers.index("Batch ID")
            action_col_idx = self.column_headers.index("Action Taken")
            status_col_idx = self.column_headers.index("Status")
        except ValueError:
            print("Error: Required columns ('Batch ID', 'Action Taken', 'Status') not found for batch undo logic.")
            self.undoBatchButton.setEnabled(False)
            return

        selected_batch_id_item = self.historyTable.item(selected_row_idx, batch_id_col_idx)
        if not selected_batch_id_item or not selected_batch_id_item.text():
            self.undoBatchButton.setEnabled(False)
            return

        target_batch_id = selected_batch_id_item.text()

        eligible_action_in_batch_exists = False
        for row_num in range(self.historyTable.rowCount()):
            batch_id_item = self.historyTable.item(row_num, batch_id_col_idx)
            if batch_id_item and batch_id_item.text() == target_batch_id:
                action_item = self.historyTable.item(row_num, action_col_idx)
                status_item = self.historyTable.item(row_num, status_col_idx)
                if (action_item and action_item.text() == constants.ACTION_MOVED and
                    status_item and status_item.text() == constants.STATUS_SUCCESS):
                    # Basic check: found at least one MOVED + SUCCESS action in this batch.
                    # More complex logic (e.g., checking if already undone) would go here or in handler.
                    eligible_action_in_batch_exists = True
                    break

        if eligible_action_in_batch_exists:
            self.undoBatchButton.setEnabled(True)
        else:
            self.undoBatchButton.setEnabled(False)


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
                                "Rule Regex": "rule_use_regex", # dict key is rule_use_regex
                                "Batch ID": "batch_id" # Added Batch ID mapping
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
        try:
            timestamp_col_index = self.column_headers.index("Timestamp")
            self.historyTable.sortByColumn(timestamp_col_index, Qt.SortOrder.DescendingOrder)
        except ValueError:
            print("Warning: Timestamp column not found for default sorting.")

        self.update_undo_button_state() # Update button state after loading history
        self.update_undo_batch_button_state() # Update batch button state after loading history


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
