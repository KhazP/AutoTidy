import json
from datetime import datetime, timezone, timedelta # timedelta might not be needed here, but good for datetime context
from pathlib import Path
import sys # For potential error logging to stderr
import constants # Added to resolve constants not defined error

class HistoryManager:
    """Manages logging of file actions to a history file."""

    def __init__(self, config_manager): # config_manager will be an instance of ConfigManager
        """
        Initializes the HistoryManager.

        Args:
            config_manager: The application's ConfigManager instance, used to determine log file path.
        """
        # In ConfigManager, we'll need a method like get_app_data_dir()
        # For now, assuming it's the same as config_dir or a specific method for it.
        # Let's assume config_manager has a method `get_config_dir_path()` that returns the Path object.
        self.history_file_path = config_manager.get_config_dir_path() / "autotidy_history.jsonl"
        self._ensure_history_dir_exists()

    def _ensure_history_dir_exists(self):
        """Ensures the directory for the history log file exists."""
        try:
            self.history_file_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            # This is a critical point; if we can't create the log dir, logging will fail.
            # For now, print to stderr. A more robust app might disable history logging or alert the user.
            print(f"Error: Could not create history log directory {self.history_file_path.parent}: {e}", file=sys.stderr)


    def log_action(self, data: dict):
        """
        Logs an action to the history file.

        Args:
            data: A dictionary containing the action details.
                  The timestamp will be added/overwritten by this method.
                  A "severity" field (e.g., "INFO", "ERROR", "WARNING") will be added if not present,
                  defaulting based on "status".
        """
        if not self.history_file_path.parent.exists():
            # If directory creation failed earlier, don't attempt to log.
            print(f"Error: History log directory does not exist. Cannot log action: {data.get('original_path', 'N/A')}", file=sys.stderr)
            return

        data["timestamp"] = datetime.now(timezone.utc).isoformat()

        # Ensure severity is present
        if "severity" not in data:
            if data.get("status") == constants.STATUS_FAILURE:
                data["severity"] = "ERROR"
            # Add elif for WARNING if a specific status maps to it
            # elif data.get("status") == constants.STATUS_WARNING: # Example
            #     data["severity"] = "WARNING"
            else: # Default for SUCCESS or other statuses
                data["severity"] = "INFO"

        try:
            with open(self.history_file_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(data) + '\n')
        except IOError as e:
            # Handle potential errors during file write (e.g., disk full, permissions)
            print(f"Error writing to history log file {self.history_file_path}: {e}", file=sys.stderr)
        except Exception as e:
            # Catch any other unexpected errors during logging
            print(f"Unexpected error during history logging: {e}", file=sys.stderr)

# Example Usage (for testing or if run directly, though not typical for this class)
if __name__ == '__main__':
    # This part is for example/testing and won't run when imported.
    # Mock ConfigManager for testing HistoryManager standalone
    class MockConfigManager:
        def get_config_dir_path(self):
            # Use a temporary directory for testing
            test_dir = Path("./test_autotidy_config")
            test_dir.mkdir(exist_ok=True)
            return test_dir

    mock_cm = MockConfigManager()
    history_logger = HistoryManager(mock_cm)

    test_log_data_success = {
        "original_path": "/path/to/source/file.txt",
        "action_taken": "MOVED",
        "destination_path": "/path/to/destination/file.txt",
        "monitored_folder": "/path/to/source",
        "rule_pattern": "*.txt",
        "rule_age_days": 7,
        "rule_use_regex": False,
        "rule_action_config": "move",
        "status": "SUCCESS",
        "details": "Moved successfully."
    }
    history_logger.log_action(test_log_data_success)

    test_log_data_failure = {
        "original_path": "/path/to/another/file.log",
        "action_taken": "SIMULATED_DELETE_PERMANENTLY",
        "destination_path": None,
        "monitored_folder": "/path/to/another",
        "rule_pattern": "*.log",
        "rule_age_days": 0,
        "rule_use_regex": True,
        "rule_action_config": "delete_permanently",
        "status": "FAILURE", # Should be SUCCESS if it's just simulation message.
                             # If an error occurs *during* simulation (e.g. bad regex), then FAILURE.
                             # Let's assume this is a failure to log the simulation, or a simulated failure.
        "details": "Dry run: Would permanently delete file.log (irreversible)"
                   # If status is FAILURE, details should be an error message.
                   # Let's adjust this example to be more consistent.
    }
    # Corrected example for a simulated action log
    test_log_data_simulated_success = {
        "original_path": "/path/to/another/file.log",
        "action_taken": "SIMULATED_DELETE_PERMANENTLY", # Action includes SIMULATED_
        "destination_path": None,
        "monitored_folder": "/path/to/another",
        "rule_pattern": "*.log",
        "rule_age_days": 0,
        "rule_use_regex": True,
        "rule_action_config": "delete_permanently", # The rule's configured action
        "status": "SUCCESS", # Because the (simulated) action was logged successfully
        "details": "[DRY RUN] Would permanently delete: 'file.log' (irreversible)" # Dry run message
    }
    history_logger.log_action(test_log_data_simulated_success)

    print(f"Test log entries written to: {history_logger.history_file_path}")
    # Remember to clean up test_autotidy_config directory after testing
    # For actual use, ConfigManager provides the real path.
