import sys
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton, QLabel, QTextEdit,
    QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView, QApplication
)
from PyQt6.QtCore import Qt, pyqtSlot, QVariant # QVariant might be needed for custom data
from datetime import datetime

# Forward declaration for type hinting if UndoManager is in a separate file
# from undo_manager import UndoManager
# from config_manager import ConfigManager

class UndoDialog(QDialog):
    # Define a custom role for storing full action data or run_id
    RunIdRole = Qt.ItemDataRole.UserRole + 1
    ActionDataRole = Qt.ItemDataRole.UserRole + 2

    def __init__(self, undo_manager, config_manager, parent=None):
        super().__init__(parent)
        self.undo_manager = undo_manager
        self.config_manager = config_manager # Though not directly used in this snippet yet

        self.setWindowTitle("Undo File Operations")
        self.setMinimumSize(800, 600)

        # --- Layout ---
        main_layout = QVBoxLayout(self)

        top_layout = QHBoxLayout()
        left_panel_layout = QVBoxLayout() # For runs list and refresh
        right_panel_layout = QVBoxLayout() # For actions list

        # --- UI Elements ---
        self.refresh_button = QPushButton("Refresh Run List")

        # Runs Table
        self.runs_table = QTableWidget()
        self.runs_table.setColumnCount(3) # Run Start Time, Action Count, Run ID (Hidden)
        self.runs_table.setHorizontalHeaderLabels(["Run Start Time", "Action Count", "Run ID"])
        self.runs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.runs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.runs_table.setColumnHidden(2, True) # Hide Run ID column
        self.runs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.runs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers) # Read-only
        self.runs_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)


        left_panel_layout.addWidget(QLabel("Available Batches/Runs:"))
        left_panel_layout.addWidget(self.refresh_button)
        left_panel_layout.addWidget(self.runs_table)

        # Actions Table
        self.actions_table = QTableWidget()
        self.actions_table.setColumnCount(4) # Original Path, Action, New Path, Timestamp
        self.actions_table.setHorizontalHeaderLabels(["Original Path", "Action", "New Path/Details", "Timestamp"])
        for i in range(4):
            self.actions_table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch if i < 2 else QHeaderView.ResizeMode.Interactive)
        self.actions_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.actions_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers) # Read-only
        self.actions_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        right_panel_layout.addWidget(QLabel("Actions in Selected Batch:"))
        right_panel_layout.addWidget(self.actions_table)

        top_layout.addLayout(left_panel_layout, 1) # Assign stretch factor
        top_layout.addLayout(right_panel_layout, 2) # Assign stretch factor
        main_layout.addLayout(top_layout)        # Buttons
        buttons_layout = QHBoxLayout()
        self.undo_batch_button = QPushButton("Undo Whole Batch")
        self.undo_selected_action_button = QPushButton("Undo Single File")
        buttons_layout.addWidget(self.undo_batch_button)
        buttons_layout.addWidget(self.undo_selected_action_button)
        main_layout.addLayout(buttons_layout)

        # Status Log
        self.status_log = QTextEdit()
        self.status_log.setReadOnly(True)
        main_layout.addWidget(QLabel("Log:"))
        main_layout.addWidget(self.status_log)

        # --- Connect signals ---
        self.refresh_button.clicked.connect(self.populate_runs_list)
        self.runs_table.itemSelectionChanged.connect(self.on_run_selected)
        self.actions_table.itemSelectionChanged.connect(self.on_action_selected)
        self.undo_batch_button.clicked.connect(self.handle_undo_batch)
        self.undo_selected_action_button.clicked.connect(self.handle_undo_selected_action)

        # --- Initial state ---
        self.populate_runs_list() # Load data

    def _log_message(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.status_log.append(f"[{timestamp}] {message}")

    @pyqtSlot()
    def populate_runs_list(self):
        self._log_message("Refreshing runs list...")
        self.runs_table.setRowCount(0) # Clear table
        self.actions_table.setRowCount(0) # Clear actions table
        self.undo_batch_button.setEnabled(False)
        self.undo_selected_action_button.setEnabled(False)

        try:
            runs = self.undo_manager.get_history_runs()
            if not runs:
                self._log_message("No history runs found.")
                return

            self.runs_table.setRowCount(len(runs))
            for row_idx, run_data in enumerate(runs):
                run_id = run_data.get("run_id")
                start_time_str = run_data.get("start_time", "N/A")
                action_count = run_data.get("action_count", 0)

                # Format timestamp nicely
                try:
                    dt_obj = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
                    formatted_time = dt_obj.strftime("%Y-%m-%d %H:%M:%S %Z")
                except (ValueError, TypeError):
                    formatted_time = start_time_str # Fallback

                item_time = QTableWidgetItem(formatted_time)
                item_count = QTableWidgetItem(str(action_count))
                item_run_id = QTableWidgetItem(run_id) # For the hidden column

                # Store run_id directly in the first item for easy retrieval
                item_time.setData(self.RunIdRole, run_id)

                self.runs_table.setItem(row_idx, 0, item_time)
                self.runs_table.setItem(row_idx, 1, item_count)
                self.runs_table.setItem(row_idx, 2, item_run_id) # Hidden

            self._log_message(f"Found {len(runs)} runs.")
        except Exception as e:
            self._log_message(f"Error populating runs list: {e}")
            QMessageBox.critical(self, "Error", f"Could not load history runs: {e}")

    @pyqtSlot()
    def on_run_selected(self):
        self.actions_table.setRowCount(0) # Clear previous actions
        self.undo_selected_action_button.setEnabled(False)

        selected_items = self.runs_table.selectedItems()
        if not selected_items:
            self.undo_batch_button.setEnabled(False)
            return

        self.undo_batch_button.setEnabled(True)
        # Retrieve run_id from the data stored in the first item of the selected row
        selected_run_id_item = self.runs_table.item(self.runs_table.currentRow(), 0)
        run_id = selected_run_id_item.data(self.RunIdRole)

        if not run_id:
            self._log_message("Could not determine Run ID for selected row.")
            return

        self._log_message(f"Run selected: {run_id}. Fetching actions...")
        try:
            actions = self.undo_manager.get_run_actions(run_id)
            if not actions:
                self._log_message(f"No actions found for run_id: {run_id}")
                return

            self.actions_table.setRowCount(len(actions))
            for row_idx, action_data in enumerate(actions):
                original_path = action_data.get("original_path", "N/A")
                action_taken = action_data.get("action_taken", "N/A")
                destination_path = action_data.get("destination_path", action_data.get("details", "N/A")) # Details for delete
                timestamp_str = action_data.get("timestamp", "N/A")

                try:
                    dt_obj = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                    formatted_time = dt_obj.strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    formatted_time = timestamp_str

                item_orig = QTableWidgetItem(original_path)
                # Store the full action data in the first item of the row for easy retrieval
                item_orig.setData(self.ActionDataRole, action_data)

                self.actions_table.setItem(row_idx, 0, item_orig)
                self.actions_table.setItem(row_idx, 1, QTableWidgetItem(action_taken))
                self.actions_table.setItem(row_idx, 2, QTableWidgetItem(str(destination_path))) # Ensure it's a string
                self.actions_table.setItem(row_idx, 3, QTableWidgetItem(formatted_time))

            self._log_message(f"Displayed {len(actions)} actions for run {run_id}.")
        except Exception as e:
            self._log_message(f"Error fetching or displaying actions for run {run_id}: {e}")
            QMessageBox.critical(self, "Error", f"Could not load actions for run {run_id}: {e}")


    @pyqtSlot()
    def on_action_selected(self):
        if self.actions_table.selectedItems():
            self.undo_selected_action_button.setEnabled(True)
        else:
            self.undo_selected_action_button.setEnabled(False)

    @pyqtSlot()
    def handle_undo_batch(self):
        selected_items = self.runs_table.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select a batch (run) to undo.")
            return

        selected_run_id_item = self.runs_table.item(self.runs_table.currentRow(), 0)
        run_id = selected_run_id_item.data(self.RunIdRole)

        if not run_id:
            self._log_message("Error: Could not retrieve Run ID for batch undo.")
            QMessageBox.critical(self, "Error", "Could not retrieve Run ID for the selected batch.")
            return

        reply = QMessageBox.question(self, "Confirm Undo Batch",
                                     f"Are you sure you want to undo all actions in batch '{run_id}'?\n"
                                     "This will attempt to reverse each operation in the batch.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._log_message(f"Attempting to undo batch {run_id}...")
            try:
                results = self.undo_manager.undo_batch(run_id)
                summary = results.get('summary', 'No summary available.')
                self._log_message(f"Batch undo for {run_id} completed. {summary}")
                QMessageBox.information(self, "Batch Undo Result", summary)
                for msg in results.get('messages', []):
                    self._log_message(f"  - {msg}")
            except Exception as e:
                self._log_message(f"Critical error during batch undo for {run_id}: {e}")
                QMessageBox.critical(self, "Undo Error", f"An error occurred during batch undo: {e}")
            finally:
                self.populate_runs_list() # Refresh the view

    @pyqtSlot()
    def handle_undo_selected_action(self):
        selected_items = self.actions_table.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select an action to undo.")
            return

        # Retrieve the full action data stored in the first item of the selected row
        action_data_item = self.actions_table.item(self.actions_table.currentRow(), 0)
        action_data = action_data_item.data(self.ActionDataRole)

        if not action_data:
            self._log_message("Error: Could not retrieve data for the selected action.")
            QMessageBox.critical(self, "Error", "Could not retrieve data for the selected action.")
            return

        original_path = action_data.get("original_path", "N/A")
        action_taken = action_data.get("action_taken", "N/A")

        reply = QMessageBox.question(self, "Confirm Undo Action",
                                     f"Are you sure you want to undo the action:\n"
                                     f"Type: {action_taken}\nOriginal: {original_path}\n"
                                     f"Destination: {action_data.get('destination_path', 'N/A')}",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._log_message(f"Attempting to undo action: {action_taken} on {original_path}...")
            try:
                success, message = self.undo_manager.undo_action(action_data)
                self._log_message(f"Undo action result: {message}")
                if success:
                    QMessageBox.information(self, "Undo Action Result", message)
                else:
                    QMessageBox.warning(self, "Undo Action Result", message)
            except Exception as e:
                self._log_message(f"Critical error during single action undo: {e}")
                QMessageBox.critical(self, "Undo Error", f"An error occurred during action undo: {e}")
            finally:
                self.populate_runs_list() # Refresh the view

# Example usage (requires UndoManager and a mock ConfigManager)
if __name__ == '__main__':
    # Mocks for running standalone
    class MockUndoManager:
        def get_history_runs(self):
            # Simulate some run data
            return [
                {"run_id": "run1_abc", "start_time": "2023-03-15T10:00:00Z", "action_count": 5},
                {"run_id": "run2_def", "start_time": "2023-03-14T14:30:00Z", "action_count": 2},
            ]

        def get_run_actions(self, run_id):
            if run_id == "run1_abc":
                return [
                    {"original_path": "/tmp/fileA.txt", "action_taken": "MOVED", "destination_path": "/archive/fileA.txt", "timestamp": "2023-03-15T10:00:00Z", "run_id": "run1_abc"},
                    {"original_path": "/tmp/fileB.txt", "action_taken": "COPIED", "destination_path": "/archive/fileB_copy.txt", "timestamp": "2023-03-15T10:00:05Z", "run_id": "run1_abc"},
                ]
            elif run_id == "run2_def":
                 return [
                    {"original_path": "/tmp/fileC.log", "action_taken": "DELETED_TO_TRASH", "details": "Sent to trash", "timestamp": "2023-03-14T14:30:00Z", "run_id": "run2_def"},
                 ]
            return []

        def undo_batch(self, run_id):
            return {"run_id": run_id, "success_count": 1, "failure_count": 0, "messages": [f"Mock: Undid one action in batch {run_id}"], "summary": f"Mock summary for {run_id}"}

        def undo_action(self, action_data):
            return True, f"Mock: Successfully undid action {action_data.get('original_path')}"

    class MockConfigManager:
        def get_some_path(self): # Example method
            return "."

    app = QApplication(sys.argv)

    # Assuming UndoManager is functional and can be instantiated
    # from undo_manager import UndoManager # If you have it
    # from config_manager import ConfigManager # If you have it
    # mock_config_manager = ConfigManager() # Or your actual one

    mock_undo_mgr = MockUndoManager()
    mock_cfg_mgr = MockConfigManager()

    dialog = UndoDialog(undo_manager=mock_undo_mgr, config_manager=mock_cfg_mgr)
    dialog.show()
    sys.exit(app.exec())
