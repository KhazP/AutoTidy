from pathlib import Path
import shutil
import os
import datetime # For timestamping the UNDO_MOVE action

from config_manager import ConfigManager
from history_manager import HistoryManager

class UndoManager:
    def __init__(self, config_manager: ConfigManager, history_manager: HistoryManager):
        self.config_manager = config_manager
        self.history_manager = history_manager

    def can_undo(self, history_entry_data: dict) -> bool:
        """
        Checks if a given history entry data suggests an action that can be undone.
        For now, only successful "MOVED" actions are considered undoable.
        """
        if not history_entry_data:
            return False

        action_taken = history_entry_data.get('action_taken')
        status = history_entry_data.get('status')

        if action_taken == "MOVED" and status == "SUCCESS":
            # Basic check: ensure essential paths are present
            if history_entry_data.get('original_path') and history_entry_data.get('destination_path'):
                return True
        return False

    def attempt_undo_action(self, history_entry_data: dict) -> tuple[bool, str]:
        """
        Attempts to undo the action described in the history_entry_data.
        This is a stub implementation for now for MOVED actions.
        """
        if not self.can_undo(history_entry_data):
            return False, "This action is not eligible for undo or undo is not supported for this action type."

        action_type_to_undo = history_entry_data.get('action_taken')
        is_dry_run = self.config_manager.get_dry_run_mode() # Get dry run mode early for logging

        if action_type_to_undo == "MOVED":
            original_action_original_path = Path(history_entry_data.get('original_path'))
            original_action_current_path = Path(history_entry_data.get('destination_path'))

            # Safety Check 1: Source file (in archive) must exist
            if not original_action_current_path.exists() or not original_action_current_path.is_file():
                message = f"Cannot undo: Archived file '{original_action_current_path}' no longer exists or is not a file."
                self._log_undo_attempt(history_entry_data, "FAILURE", message,
                                     original_action_original_path, original_action_current_path, is_dry_run)
                return False, message

            # Safety Check 2: Target path (original location) for conflicts
            if original_action_original_path.exists():
                if original_action_original_path.is_dir():
                    message = f"Cannot undo: Original path '{original_action_original_path}' is now a directory."
                    self._log_undo_attempt(history_entry_data, "FAILURE", message,
                                         original_action_original_path, original_action_current_path, is_dry_run)
                    return False, message
                # For V1, any existing file is a conflict to be safe.
                message = (f"Cannot undo: A file or folder already exists at the original path "
                           f"'{original_action_original_path}'. Please move/remove it manually if you wish to proceed.")
                self._log_undo_attempt(history_entry_data, "FAILURE", message,
                                     original_action_original_path, original_action_current_path, is_dry_run)
                return False, message

            dry_run_prefix = "[DRY RUN] " if is_dry_run else ""
            try:
                if not is_dry_run:
                    original_action_original_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(original_action_current_path), str(original_action_original_path))

                message = (f"{dry_run_prefix}Successfully moved file from '{original_action_current_path}' "
                           f"back to '{original_action_original_path}'.")
                self._log_undo_attempt(history_entry_data, "SUCCESS", message,
                                     original_action_original_path, original_action_current_path, is_dry_run)
                return True, message
            except Exception as e:
                error_message = f"Error during undo 'move' operation: {e}"
                self._log_undo_attempt(history_entry_data, "FAILURE", error_message,
                                     original_action_original_path, original_action_current_path, is_dry_run,
                                     exception_str=str(e))
                return False, error_message

        return False, f"Undo for action type '{action_type_to_undo}' not yet implemented."

    def _log_undo_attempt(self, original_history_entry: dict, undo_status: str, undo_details: str,
                          undo_destination_path: Path, undo_source_path: Path,
                          is_dry_run: bool, exception_str: str = None):
        action_taken_string = "UNDO_MOVE"
        if is_dry_run:
            action_taken_string = "SIMULATED_UNDO_MOVE"

        original_action_timestamp = original_history_entry.get('timestamp', 'N/A')

        log_data = {
            "original_path": str(undo_source_path),
            "action_taken": action_taken_string,
            "destination_path": str(undo_destination_path),
            "monitored_folder": original_history_entry.get('monitored_folder', 'N/A'),
            "rule_pattern": original_history_entry.get('rule_pattern', 'N/A'),
            "rule_age_days": original_history_entry.get('rule_age_days', 'N/A'),
            "rule_use_regex": original_history_entry.get('rule_use_regex', False),
            "rule_action_config": "UNDO_MOVE", # The action *being* performed now
            "status": undo_status,
            "details": f"Undo of original action (timestamp: {original_action_timestamp}). Details: {undo_details}",
            "error_details": exception_str if exception_str else None
        }
        self.history_manager.log_action(log_data)

if __name__ == '__main__':
    # Basic test stub
    class MockConfigManager:
        def get_dry_run_mode(self): return False
        def get_config_dir_path(self): return Path("./mock_config_dir") # For HistoryManager if it writes

    class MockHistoryManager:
        def log_action(self, data):
            print(f"MOCK_HISTORY_LOG: {data.get('action_taken')} - {data.get('original_path')} -> {data.get('destination_path', 'N/A')}, Details: {data.get('details')}")

    print("Testing UndoManager stubs...")
    # Create mock config dir if it doesn't exist for the mock history manager
    mock_config_dir = MockConfigManager().get_config_dir_path()
    mock_config_dir.mkdir(exist_ok=True)

    um = UndoManager(MockConfigManager(), MockHistoryManager())

    test_move_ok = {
        "timestamp": "2023-01-01T12:00:00Z",
        "action_taken": "MOVED", "status": "SUCCESS",
        "original_path": "/orig/file.txt", "destination_path": "/archive/file.txt",
        "monitored_folder": "/orig", "rule_pattern": "*.txt", "rule_age_days": 0,
        "rule_use_regex": False, "rule_action_config": "move",
        "details": "Moved successfully"
    }
    test_move_fail = {
        "action_taken": "MOVED", "status": "FAILURE",
        "original_path": "/orig/file.txt", "destination_path": "/archive/file.txt"
    }
    test_copy = {"action_taken": "COPIED", "status": "SUCCESS"}
    test_no_paths = {"action_taken": "MOVED", "status": "SUCCESS"}


    print(f"Can undo 'test_move_ok'? {um.can_undo(test_move_ok)}")
    status, msg = um.attempt_undo_action(test_move_ok)
    print(f"Attempt 'test_move_ok': Status={status}, Message='{msg}'\n")

    print(f"Can undo 'test_move_fail'? {um.can_undo(test_move_fail)}")
    status, msg = um.attempt_undo_action(test_move_fail)
    print(f"Attempt 'test_move_fail': Status={status}, Message='{msg}'\n")

    print(f"Can undo 'test_copy'? {um.can_undo(test_copy)}")
    status, msg = um.attempt_undo_action(test_copy)
    print(f"Attempt 'test_copy': Status={status}, Message='{msg}'\n")

    print(f"Can undo 'test_no_paths'? {um.can_undo(test_no_paths)}")
    status, msg = um.attempt_undo_action(test_no_paths)
    print(f"Attempt 'test_no_paths': Status={status}, Message='{msg}'\n")

    # Test with dry run mode
    class MockConfigManagerDryRun(MockConfigManager):
        def get_dry_run_mode(self): return True

    um_dry = UndoManager(MockConfigManagerDryRun(), MockHistoryManager())
    print("--- Testing Dry Run Mode ---")
    print(f"Can undo 'test_move_ok' (dry run)? {um_dry.can_undo(test_move_ok)}")
    status_dry, msg_dry = um_dry.attempt_undo_action(test_move_ok)
    print(f"Attempt 'test_move_ok' (dry run): Status={status_dry}, Message='{msg_dry}'\n")

    # Clean up mock config dir
    # shutil.rmtree(mock_config_dir) # Or handle cleanup manually
    print(f"Mock config directory was: {mock_config_dir}")
