import json
import shutil
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QPushButton,
    QAbstractItemView, QHBoxLayout, QHeaderView, QMessageBox, QFileDialog,
    QLabel, QLineEdit, QComboBox, QDateEdit, QGridLayout, QGroupBox,
    QToolButton, QWidget
)
from PyQt6.QtGui import QKeySequence
from PyQt6.QtCore import Qt, QDateTime, QTimer
from datetime import datetime # Added to resolve datetime undefined error
import constants
import csv # For CSV export

# ConfigManager is not directly imported if only its path method is used via a passed instance.

class HistoryViewerDialog(QDialog):
    """Dialog to view action history from the JSONL file."""

    def __init__(self, config_manager, history_manager, parent=None): # config_manager and history_manager instances
        super().__init__(parent)
        self.config_manager = config_manager
        self.history_manager = history_manager
        self.all_history_data = [] # Store all loaded history data

        self.setWindowTitle("AutoTidy Action History")
        self.setMinimumSize(900, 500) # Adjusted size for new elements

        main_layout = QVBoxLayout(self)

        # Filter Layout
        self._default_start_date = QDateTime.currentDateTime().addDays(-7)
        self.filters_group = QGroupBox("Filters")
        filters_group_layout = QVBoxLayout()
        filters_group_layout.setContentsMargins(10, 8, 10, 10)
        filters_group_layout.setSpacing(6)
        self.filters_group.setLayout(filters_group_layout)

        # Basic Filters (Date & Folder)
        basic_filters_container = QWidget()
        basic_filters_layout = QGridLayout()
        basic_filters_layout.setContentsMargins(0, 0, 0, 0)
        basic_filters_layout.setHorizontalSpacing(8)
        basic_filters_layout.setVerticalSpacing(4)
        basic_filters_container.setLayout(basic_filters_layout)

        # Date Filter
        basic_filters_layout.addWidget(QLabel("Filter by Date:"), 0, 0)
        self.dateFilter = QDateEdit()
        self.dateFilter.setCalendarPopup(True)
        self.dateFilter.setDateTime(self._default_start_date) # Default to last 7 days
        self.dateFilter.setDisplayFormat("yyyy-MM-dd")
        self.dateFilter.setToolTip("Show logs from this date onwards.")
        basic_filters_layout.addWidget(self.dateFilter, 0, 1)
        self.dateFilter.dateChanged.connect(self.apply_filters)


        # Folder Filter
        basic_filters_layout.addWidget(QLabel("Filter by Folder:"), 0, 2)
        self.folderFilter = QLineEdit()
        self.folderFilter.setPlaceholderText("Enter monitored folder path (partial match)")
        self.folderFilter.setToolTip("Filter by monitored folder containing this text.")
        basic_filters_layout.addWidget(self.folderFilter, 0, 3)
        self.folderFilter.textChanged.connect(self.apply_filters)

        # Keyword Filter
        basic_filters_layout.addWidget(QLabel("Filter by Keyword:"), 1, 0)
        self.keywordFilter = QLineEdit()
        self.keywordFilter.setPlaceholderText("Search details, paths, or actions")
        self.keywordFilter.setToolTip("Filter by keyword within action, details, or file paths.")
        basic_filters_layout.addWidget(self.keywordFilter, 1, 1, 1, 3)
        self.keywordFilter.textChanged.connect(self.apply_filters)

        filters_group_layout.addWidget(basic_filters_container)

        # Advanced Toggle
        advanced_toggle_layout = QHBoxLayout()
        advanced_toggle_layout.setContentsMargins(0, 0, 0, 0)
        advanced_toggle_layout.addStretch()
        self.toggleAdvancedButton = QToolButton()
        self.toggleAdvancedButton.setCheckable(True)
        self.toggleAdvancedButton.setChecked(True)
        self.toggleAdvancedButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        advanced_toggle_layout.addWidget(self.toggleAdvancedButton)
        filters_group_layout.addLayout(advanced_toggle_layout)

        # Advanced Filters (Action & Severity)
        self.advanced_container = QWidget()
        advanced_filters_layout = QGridLayout()
        advanced_filters_layout.setContentsMargins(0, 0, 0, 0)
        advanced_filters_layout.setHorizontalSpacing(8)
        advanced_filters_layout.setVerticalSpacing(4)
        self.advanced_container.setLayout(advanced_filters_layout)

        # Action Type Filter
        advanced_filters_layout.addWidget(QLabel("Filter by Action:"), 0, 0)
        self.actionFilter = QComboBox()
        self.actionFilter.addItem("All Actions", "")
        # Populate with known actions from constants.py
        self.actionFilter.addItems([
            constants.ACTION_MOVED,
            constants.ACTION_COPIED,
            constants.ACTION_DELETED_TO_TRASH,
            constants.ACTION_PERMANENTLY_DELETED,
            constants.ACTION_SIMULATED_MOVE,
            constants.ACTION_SIMULATED_COPY,
            constants.ACTION_SIMULATED_DELETE_TO_TRASH,
            constants.ACTION_SIMULATED_PERMANENT_DELETE,
            constants.ACTION_ERROR,
            constants.ACTION_UNDO_MOVE,
            constants.ACTION_SKIPPED
        ])
        self.actionFilter.setToolTip("Filter by the type of action performed.")
        advanced_filters_layout.addWidget(self.actionFilter, 0, 1)
        self.actionFilter.currentIndexChanged.connect(self.apply_filters)

        # Severity Filter
        advanced_filters_layout.addWidget(QLabel("Filter by Severity:"), 0, 2)
        self.severityFilter = QComboBox()
        self.severityFilter.addItem("All Severities", "")
        self.severityFilter.addItem("INFO", "INFO")
        self.severityFilter.addItem("WARNING", "WARNING") # Assuming you might add WARNING status/severity
        self.severityFilter.addItem("ERROR", "ERROR") # Corresponds to STATUS_FAILURE
        self.severityFilter.setToolTip("Filter by log severity (INFO, WARNING, ERROR).")
        advanced_filters_layout.addWidget(self.severityFilter, 0, 3)
        self.severityFilter.currentIndexChanged.connect(self.apply_filters)

        filters_group_layout.addWidget(self.advanced_container)

        # Apply Filters Button (Manual refresh of filters)
        self.applyFilterButton = QPushButton("Apply Filters")
        self.applyFilterButton.setToolTip("Manually apply all active filters.")
        self.applyFilterButton.clicked.connect(self.apply_filters)
        self.resetFilterButton = QPushButton("Reset filters")
        self.resetFilterButton.setToolTip("Clear all filter fields and restore defaults.")
        self.resetFilterButton.clicked.connect(self.reset_filters)

        filter_buttons_layout = QHBoxLayout()
        filter_buttons_layout.setContentsMargins(0, 0, 0, 0)
        filter_buttons_layout.addStretch()
        filter_buttons_layout.addWidget(self.applyFilterButton)
        filter_buttons_layout.addWidget(self.resetFilterButton)
        filters_group_layout.addLayout(filter_buttons_layout)

        self.toggleAdvancedButton.toggled.connect(self.toggle_advanced_filters)
        self.toggle_advanced_filters(True)

        main_layout.addWidget(self.filters_group)

        # Table Widget
        self.historyTable = QTableWidget()
        self.column_headers = [
            "Timestamp", "Action Taken", "Severity", "Original Path", "Destination Path",
            "Status", "Details", "Monitored Folder", "Rule Pattern",
            "Rule Age", "Rule Regex"
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
                if i != self.column_headers.index("Details"): # Ensure "Details" is still stretched
                    header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                if self.column_headers[i] == "Timestamp": # Give timestamp a bit more space
                     header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)


        main_layout.addWidget(self.historyTable)

        # Buttons Layout
        buttons_layout = QHBoxLayout()

        self.undoButton = QPushButton("&Undo Selected Action")
        self.undoButton.setToolTip("Undo the selected file operation (Ctrl+Z if focus is on table/button)")
        self.undoButton.clicked.connect(self.handle_undo_action)
        buttons_layout.addWidget(self.undoButton)
        
        self.exportButton = QPushButton("E&xport Logs")
        self.exportButton.setToolTip("Export the currently visible logs to a CSV file.")
        self.exportButton.clicked.connect(self.export_logs)
        buttons_layout.addWidget(self.exportButton)

        buttons_layout.addStretch(1)

        self.refreshButton = QPushButton("&Refresh All")
        self.refreshButton.setToolTip("Reload all action history, clearing filters (F5).")
        self.refreshButton.clicked.connect(self.load_history_data)
        buttons_layout.addWidget(self.refreshButton)

        buttons_layout.addStretch(1)

        self.closeButton = QPushButton("&Close")
        self.closeButton.setToolTip("Close this window (Esc)")
        self.closeButton.clicked.connect(self.accept)
        buttons_layout.addWidget(self.closeButton)

        main_layout.addLayout(buttons_layout)

        self.historyTable.itemSelectionChanged.connect(self.update_undo_button_state)

        self.load_history_data() # Load all data first
        self.apply_filters() # Then apply default filters
        self.update_undo_button_state() # Initial state
        self._setup_shortcuts() # Call new method
        QTimer.singleShot(0, self.historyTable.setFocus) # Ensure the table gains focus after layout setup

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

    def toggle_advanced_filters(self, checked: bool):
        """Show or hide advanced filter controls."""
        self.advanced_container.setVisible(checked)
        self.toggleAdvancedButton.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        )
        self.toggleAdvancedButton.setText(
            "Hide advanced filters" if checked else "Show advanced filters"
        )
        # Update layout geometry so the table can reclaim space when collapsed
        self.filters_group.updateGeometry()
        self.historyTable.updateGeometry()

    def reset_filters(self):
        """Reset all filter widgets to their default state and reapply filters."""
        widgets = [self.dateFilter, self.folderFilter, self.keywordFilter, self.actionFilter, self.severityFilter]
        for widget in widgets:
            widget.blockSignals(True)

        try:
            self.dateFilter.setDateTime(self._default_start_date)
            self.folderFilter.clear()
            self.keywordFilter.clear()
            self.actionFilter.setCurrentIndex(0)
            self.severityFilter.setCurrentIndex(0)
        finally:
            for widget in widgets:
                widget.blockSignals(False)

        self.apply_filters()

    def keyPressEvent(self, event):
        """Handle key presses for actions like Escape."""
        if event.key() == Qt.Key.Key_Escape:
            self.accept() # Close on Escape
        elif event.key() == Qt.Key.Key_F5:
            self.load_history_data() # Reload all data
            self.apply_filters() # Reapply filters
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
                self.load_history_data() # Refresh history, as the file's status might have changed
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

                self.load_history_data() # Refresh history to show the UNDO_MOVE entry

            except (IOError, OSError) as e:
                QMessageBox.critical(self, "Move Error", f"Error moving file: {e}")
                # Log this failure as well
                self.history_manager.log_action({
                    "action_taken": "UNDO_ERROR", 
                    "original_path": str(destination_file) if 'destination_file' in locals() else "N/A",
                    "destination_path": str(original_path_target) if 'original_path_target' in locals() else "N/A",
                    "status": constants.STATUS_FAILURE,
                    "severity": "ERROR", # Add severity
                    "details": f"Failed to undo action. Error: {e}"
                })
                self.load_history_data()
                self.apply_filters()
            except Exception as e:
                QMessageBox.critical(self, "Unexpected Error", f"An unexpected error occurred: {e}")
                self.history_manager.log_action({
                    "action_taken": "UNDO_ERROR",
                    "original_path": "N/A",
                    "destination_path": "N/A",
                    "status": constants.STATUS_FAILURE,
                    "severity": "ERROR", # Add severity
                    "details": f"Unexpected error during undo: {e}"
                })
                self.load_history_data()
                self.apply_filters()

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

        # Ensure this logic correctly reflects if an item is undoable based on its "Action Taken"
        # For example, "UNDO_MOVE" or "ERROR" actions should not be undoable.
        if not selected_items or len(selection_model.selectedRows()) != 1:
            self.undoButton.setEnabled(False)
            return

        selected_row = selection_model.selectedRows()[0].row()
        action_item = self.historyTable.item(selected_row, self.column_headers.index("Action Taken"))
        status_item = self.historyTable.item(selected_row, self.column_headers.index("Status"))

        if action_item and status_item:
            action_text = action_item.text()
            status_text = status_item.text()
            # Only enable undo for successful "MOVED" or "COPIED" actions (adjust as needed)
            is_undoable_action = action_text in [constants.ACTION_MOVED, constants.ACTION_COPIED] # Example
            is_successful = status_text == constants.STATUS_SUCCESS
            self.undoButton.setEnabled(is_undoable_action and is_successful)
        else:
            self.undoButton.setEnabled(False)


    def load_history_data(self):
        """Loads all history data from the file and stores it."""
        self.all_history_data = []
        history_file = self.history_manager.history_file_path # Use the path from history_manager
        if not history_file.exists():
            # QMessageBox.information(self, "History", "No history data found.")
            # No need for a message if the file simply doesn't exist yet.
            self.apply_filters() # Apply to an empty list to clear table
            return

        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        log_entry = json.loads(line.strip())
                        # Ensure severity is present, default if not
                        if "severity" not in log_entry:
                            status = log_entry.get("status")
                            if status == constants.STATUS_FAILURE:
                                log_entry["severity"] = "ERROR"
                            elif status == constants.STATUS_SUCCESS:
                                log_entry["severity"] = "INFO"
                            elif status:
                                log_entry["severity"] = "WARNING"
                            else:
                                log_entry["severity"] = "INFO"
                        self.all_history_data.append(log_entry)
                    except json.JSONDecodeError:
                        print(f"Skipping malformed line in history: {line.strip()}") # Log to console
            self.all_history_data.sort(key=lambda x: x.get("timestamp", ""), reverse=True) # Sort by timestamp descending
        except IOError as e:
            QMessageBox.critical(self, "Error Loading History", f"Could not read history file: {e}")
            self.all_history_data = [] # Clear data on error
        
        # After loading all data, apply current filters
        self.apply_filters()


    def apply_filters(self):
        """Filters the loaded history data and updates the table display."""
        self.historyTable.setRowCount(0) # Clear existing rows
        self.historyTable.setSortingEnabled(False) # Disable sorting during population

        # Get filter values
        selected_date_str = self.dateFilter.date().toString("yyyy-MM-dd")
        folder_query = self.folderFilter.text().lower()
        keyword_query = self.keywordFilter.text().lower()
        action_query = self.actionFilter.currentData() if self.actionFilter.currentIndex() > 0 else self.actionFilter.currentText()
        if action_query == "All Actions": action_query = "" # Treat "All Actions" as no filter

        severity_query = self.severityFilter.currentData() if self.severityFilter.currentIndex() > 0 else ""
        if severity_query == "All Severities": severity_query = ""


        filtered_data = []
        for entry in self.all_history_data:
            # Date filter: entry timestamp should be on or after selected_date_str
            timestamp_str = entry.get("timestamp", "")
            try:
                entry_date_str = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00")).strftime("%Y-%m-%d")
                if entry_date_str < selected_date_str:
                    continue
            except ValueError:
                # If timestamp is malformed, skip or include based on preference. Here, we skip.
                continue

            # Folder filter
            monitored_folder = entry.get("monitored_folder", "").lower()
            if folder_query and folder_query not in monitored_folder:
                continue

            # Action Type filter
            action_taken = entry.get("action_taken", "")
            if action_query and action_query != action_taken:
                continue
            
            # Severity filter
            severity = entry.get("severity", "INFO").upper() # Default to INFO if not present
            if severity_query and severity_query != severity:
                continue

            if keyword_query:
                action_text = entry.get("action_taken", "").lower()
                details_text = entry.get("details", "").lower()
                original_path_text = entry.get("original_path", "").lower()
                destination_path_text = entry.get("destination_path", "").lower()

                if not any(
                    keyword_query in field
                    for field in (
                        action_text,
                        details_text,
                        original_path_text,
                        destination_path_text,
                    )
                ):
                    continue

            filtered_data.append(entry)

        self.historyTable.setRowCount(len(filtered_data))
        for row, log_entry in enumerate(filtered_data):
            self.historyTable.setItem(row, self.column_headers.index("Timestamp"), QTableWidgetItem(log_entry.get("timestamp", "")))
            self.historyTable.setItem(row, self.column_headers.index("Action Taken"), QTableWidgetItem(log_entry.get("action_taken", "")))
            self.historyTable.setItem(row, self.column_headers.index("Severity"), QTableWidgetItem(log_entry.get("severity", "INFO")))
            self.historyTable.setItem(row, self.column_headers.index("Original Path"), QTableWidgetItem(log_entry.get("original_path", "")))
            self.historyTable.setItem(row, self.column_headers.index("Destination Path"), QTableWidgetItem(log_entry.get("destination_path", "")))
            self.historyTable.setItem(row, self.column_headers.index("Status"), QTableWidgetItem(log_entry.get("status", "")))
            self.historyTable.setItem(row, self.column_headers.index("Details"), QTableWidgetItem(log_entry.get("details", "")))
            self.historyTable.setItem(row, self.column_headers.index("Monitored Folder"), QTableWidgetItem(log_entry.get("monitored_folder", "")))
            self.historyTable.setItem(row, self.column_headers.index("Rule Pattern"), QTableWidgetItem(log_entry.get("rule_pattern", "")))
            self.historyTable.setItem(row, self.column_headers.index("Rule Age"), QTableWidgetItem(str(log_entry.get("rule_age_days", ""))))
            self.historyTable.setItem(row, self.column_headers.index("Rule Regex"), QTableWidgetItem(str(log_entry.get("rule_use_regex", ""))))

        self.historyTable.setSortingEnabled(True)
        self.historyTable.resizeColumnsToContents()
        # Re-apply stretch to "Details" if necessary, and specific width for Timestamp
        header = self.historyTable.horizontalHeader()
        if header:
            header.setSectionResizeMode(self.column_headers.index("Details"), QHeaderView.ResizeMode.Stretch)
            # Timestamp might need a minimum width or resize to contents again
            ts_col_index = self.column_headers.index("Timestamp")
            header.setSectionResizeMode(ts_col_index, QHeaderView.ResizeMode.ResizeToContents)
            # Ensure other columns are interactive
            for i in range(len(self.column_headers)):
                if i not in [self.column_headers.index("Details"), ts_col_index]:
                    header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        self.update_undo_button_state()


    def export_logs(self):
        """Exports the currently displayed (filtered) logs to a CSV file."""
        if self.historyTable.rowCount() == 0:
            QMessageBox.information(self, "Export Logs", "There are no logs to export.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Logs", "", "CSV Files (*.csv);;Text Files (*.txt)"
        )

        if not file_path:
            return

        try:
            with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                # Write headers
                writer.writerow(self.column_headers)
                # Write data rows
                for row in range(self.historyTable.rowCount()):
                    row_data = []
                    for column in range(self.historyTable.columnCount()):
                        item = self.historyTable.item(row, column)
                        row_data.append(item.text() if item else "")
                    writer.writerow(row_data)
            QMessageBox.information(self, "Export Successful", f"Logs successfully exported to {file_path}")
        except IOError as e:
            QMessageBox.critical(self, "Export Error", f"Could not write to file: {e}")

    # Remove the old load_history method as its functionality is now in load_history_data and apply_filters
    # def load_history(self):
    # ... (old implementation)


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
