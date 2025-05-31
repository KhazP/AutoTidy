import json
import os
import shutil
from pathlib import Path
from datetime import datetime
import sys # For stderr

class UndoManager:
    """
    Manages the retrieval of historical file operations and provides functionality
    to undo these operations. It reads from the history log file created by
    HistoryManager, groups actions by 'run_id' (batches), and can reverse
    supported actions like 'MOVED' or 'COPIED'.
    """
    def __init__(self, config_manager):
        """
        Initializes the UndoManager.

        Args:
            config_manager: An instance of ConfigManager, used to locate the
                            history log file (`autotidy_history.jsonl`).
        """
        self.config_manager = config_manager
        self.history_file_path = self.config_manager.get_config_dir_path() / "autotidy_history.jsonl"

    def get_history_runs(self):
        """
        Retrieves a summary of all logged operation runs (batches).

        Each run is identified by a `run_id` and includes the start time of
        the earliest action in that run and the total count of actions in that run.
        The runs are sorted by their start time in descending order (most recent first).

        Returns:
            A list of dictionaries, where each dictionary represents a run:
            [
                {
                    "run_id": str,
                    "start_time": str (ISO format),
                    "action_count": int
                },
                ...
            ]
            Returns an empty list if the history file doesn't exist or an error occurs.
        """
        if not self.history_file_path.exists():
            return []

        runs = {}
        try:
            with open(self.history_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        action = json.loads(line)
                        run_id = action.get("run_id")
                        timestamp_str = action.get("timestamp")

                        if not run_id or not timestamp_str:
                            # Skip lines missing essential data
                            continue

                        # Ensure timestamp is valid ISO format for comparison
                        try:
                            # Parse timestamp string to datetime object for comparison and finding min
                            action_timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                        except ValueError:
                            print(f"WARNING: Skipping action with invalid timestamp format: {timestamp_str} in run {run_id}", file=sys.stderr)
                            continue # Skip this action if timestamp is invalid

                        # Initialize run data if this is the first time we see this run_id
                        if run_id not in runs:
                            runs[run_id] = {
                                "run_id": run_id,
                                "min_timestamp_obj": action_timestamp, # Initialize min timestamp
                                "action_count": 0
                            }
                        else:
                            # Update min_timestamp_obj if the current action is earlier
                            if action_timestamp < runs[run_id]["min_timestamp_obj"]:
                                runs[run_id]["min_timestamp_obj"] = action_timestamp

                        runs[run_id]["action_count"] += 1
                    except json.JSONDecodeError:
                        print(f"WARNING: Skipping corrupted JSON line in history: {line.strip()}", file=sys.stderr)
                        continue

            # Convert collected run data into the desired list format
            processed_runs = []
            for run_id, data in runs.items():
                processed_runs.append({
                    "run_id": data["run_id"],
                    "start_time": data["min_timestamp_obj"].isoformat(), # Convert the true minimum timestamp to ISO string
                    "action_count": data["action_count"]
                })

            # Sort runs by their actual start_time (datetime objects for accurate sort), most recent first
            # We need to parse the ISO string back to datetime for sorting if min_timestamp_obj is not kept till here
            # Or, ensure sorting happens before converting min_timestamp_obj to string.
            # The current logic correctly converts to string after all minimums are found.
            processed_runs.sort(key=lambda r: datetime.fromisoformat(r['start_time']), reverse=True)
            return processed_runs

        except IOError as e:
            print(f"ERROR: Error reading history file {self.history_file_path}: {e}", file=sys.stderr)
            return []
        except Exception as e:
            print(f"ERROR: An unexpected error occurred while processing history runs: {e}", file=sys.stderr)
            return []


    def get_run_actions(self, run_id_to_find: str):
        """
        Retrieves all actions associated with a specific `run_id`.

        The actions are read from the history file and filtered by the provided
        `run_id`. They are then sorted by their timestamp in ascending order
        (chronological order of execution).

        Args:
            run_id_to_find: The specific run_id for which to retrieve actions.

        Returns:
            A list of action dictionaries, sorted by timestamp. Each dictionary
            is a raw log entry from the history file. Returns an empty list if
            the history file doesn't exist, the run_id is not found, or an error occurs.
        """
        if not self.history_file_path.exists():
            return []

        actions_for_run = []
        try:
            with open(self.history_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        action = json.loads(line)
                        if action.get("run_id") == run_id_to_find:
                            # Parse timestamp string to datetime object for sorting
                            try:
                                # Store the datetime object directly for sorting
                                action['timestamp_obj'] = datetime.fromisoformat(action.get("timestamp").replace("Z", "+00:00"))
                                actions_for_run.append(action)
                            except (ValueError, AttributeError): # Catch error if timestamp is missing or malformed
                                print(f"WARNING: Skipping action with invalid or missing timestamp for run {run_id_to_find}: {action.get('original_path', 'N/A')}", file=sys.stderr)
                                continue
                    except json.JSONDecodeError:
                        print(f"WARNING: Skipping corrupted JSON line in history: {line.strip()}", file=sys.stderr)
                        continue

            # Sort actions by their actual timestamp (datetime objects ensure correct chronological order)
            actions_for_run.sort(key=lambda x: x['timestamp_obj'])

            # Clean up the temporary 'timestamp_obj' key from each dictionary
            # as it was only needed for sorting.
            for action_entry in actions_for_run:
                 del action_entry['timestamp_obj']

            return actions_for_run
        except IOError as e:
            print(f"ERROR: Error reading history file {self.history_file_path}: {e}", file=sys.stderr)
            return []
        except Exception as e:
            print(f"ERROR: An unexpected error occurred while fetching run actions: {e}", file=sys.stderr)
            return []

    def undo_action(self, action_data: dict) -> tuple[bool, str]:
        """
        Attempts to undo a single logged action.

        The behavior depends on the `action_taken` field in `action_data`:
        - "MOVED": Attempts to move the file from `destination_path` back to `original_path`.
                   Checks for existence of source and potential overwrite of destination.
        - "COPIED": Attempts to delete the file at `destination_path` (the copy).
        - Other actions (e.g., "DELETED_TO_TRASH", "DELETED_PERMANENTLY") are currently not supported for undo.

        Args:
            action_data: A dictionary representing the logged action, typically
                         obtained from `get_run_actions`. Must contain relevant
                         keys like `action_taken`, `original_path`, `destination_path`.

        Returns:
            A tuple (success: bool, message: str).
            `success` is True if the undo operation was performed successfully, False otherwise.
            `message` provides details about the outcome (e.g., success message or error description).
        """
        action_taken = action_data.get("action_taken")

        if action_taken == "MOVED":
            original_path_str = action_data.get("original_path")
            destination_path_str = action_data.get("destination_path")

            if not original_path_str or not destination_path_str:
                return False, "Error: Missing original or destination path in action data."

            original_path = Path(original_path_str)
            destination_path = Path(destination_path_str)

            try:
                if destination_path.exists():
                    # Check for potential overwrite at the original location
                    if original_path.exists():
                        # Simple strategy: don't overwrite if original_path still exists and is a file.
                        # More complex strategies could involve renaming or user prompts (handled by UI).
                        if original_path.is_file():
                            return False, f"Error: Original path '{original_path}' already exists and is a file. Cannot move '{destination_path}' back without data loss."
                        # If original_path is a directory, moving into it might be acceptable,
                        # but for simplicity, let's assume it should be a clear path.
                        # Consider if the filename now matches a directory name.
                        return False, f"Error: Original path '{original_path}' already exists. Cannot safely move '{destination_path}' back."

                    # Ensure parent directory of original_path exists for the move back
                    original_path.parent.mkdir(parents=True, exist_ok=True)

                    shutil.move(str(destination_path), str(original_path))
                    return True, f"Successfully moved '{destination_path.name}' from '{destination_path.parent}' back to '{original_path.parent}'"
                else:
                    return False, f"Error: The 'moved' file at '{destination_path}' does not exist. Cannot undo move."
            except FileNotFoundError: # Should ideally be caught by .exists() but good for robustness
                return False, f"Error: File not found during undo. Source '{destination_path}' or target parent '{original_path.parent}' might be missing."
            except PermissionError:
                return False, f"Error: Permission denied during undo operation on '{destination_path}' or '{original_path}'."
            except OSError as e:
                return False, f"OS error during undo ({action_taken}) on '{destination_path}' or '{original_path}': {e}"

        elif action_taken == "COPIED":
            # Undoing a "COPIED" action means deleting the file that was created at destination_path.
            destination_path_str = action_data.get("destination_path")
            if not destination_path_str:
                return False, "Error: Missing destination path for 'COPIED' action. Cannot determine which file to delete."

            destination_path = Path(destination_path_str)
            try:
                if destination_path.is_file(): # Ensure it's a file
                    os.remove(destination_path)
                    return True, f"Successfully deleted the copied file: '{destination_path}'"
                elif not destination_path.exists():
                     return False, f"Error: The copied file at '{destination_path}' does not exist. Cannot undo copy."
                else: # It's a directory or other, don't attempt to delete with os.remove
                    return False, f"Error: Destination '{destination_path}' is not a file. Cannot undo copy by simple deletion."
            except FileNotFoundError: # Should be caught by .exists(), but included for robustness
                return False, f"Error: Copied file '{destination_path}' not found during deletion attempt."
            except PermissionError:
                return False, f"Error: Permission denied when trying to delete the copied file '{destination_path}'."
            except OSError as e:
                return False, f"OS error when deleting copied file '{destination_path}': {e}"

        # --- Handling for other action types ---
        # DELETED_TO_TRASH: Could be implemented by finding the file in trash and restoring.
        #                   This is highly platform-dependent and complex.
        # DELETED_PERMANENTLY: Cannot be undone.
        elif action_taken == "DELETED_TO_TRASH":
            return False, f"Undo for 'DELETED_TO_TRASH' is not implemented. File was: {action_data.get('original_path')}"
        elif action_taken == "DELETED_PERMANENTLY":
            return False, f"Cannot undo 'DELETED_PERMANENTLY' for file: {action_data.get('original_path')}"
        else:
            # Includes SIMULATED actions, UNDO actions themselves, etc.
            return False, f"Undo is not supported or applicable for action type: '{action_taken}'"

    def undo_batch(self, run_id: str) -> dict:
        """
        Attempts to undo all actions associated with a given `run_id`.

        Actions within the batch are undone in the reverse order of their
        original execution. The outcome of each individual undo attempt is logged.

        Args:
            run_id: The identifier of the batch run to undo.

        Returns:
            A dictionary summarizing the batch undo operation:
            {
                "run_id": str,
                "success_count": int,    // Number of actions successfully undone
                "failure_count": int,    // Number of actions that failed to undo
                "messages": list[str], // Detailed messages for each action attempt
                "summary": str         // A summary message of the overall batch outcome
            }
        """
        actions_to_undo = self.get_run_actions(run_id)
        if not actions_to_undo:
            return {
                'run_id': run_id, 'success_count': 0, 'failure_count': 0,
                'messages': [f"No actions found for run_id: {run_id}"],
                'summary': f"No actions found for run_id: {run_id}"
            }

        success_count = 0
        failure_count = 0
        messages = []

        # Iterate in reverse order of when they were performed for safe undo
        for action_data in reversed(actions_to_undo):
            original_path_display = action_data.get('original_path', 'N/A')
            action_display = action_data.get('action_taken', 'N/A')
            dest_path_display = action_data.get('destination_path', 'N/A')
            timestamp_display = action_data.get('timestamp', 'N/A')

            message_prefix = (f"Attempting to undo: {action_display} on '{original_path_display}' "
                              f"(Dest: '{dest_path_display}', Time: {timestamp_display}): ")

            success, message = self.undo_action(action_data)
            messages.append(message_prefix + message)
            if success:
                success_count += 1
            else:
                failure_count += 1
                # Log failures to stderr for system logs as well
                print(f"ERROR: Failed undo in batch '{run_id}': {message_prefix}{message}", file=sys.stderr)


        summary_message = f"Undo batch for run_id '{run_id}' complete. Successes: {success_count}, Failures: {failure_count}."
        # This print is for console feedback if run directly; UI should use returned messages.
        # It's okay for __main__ but for library use, results should be returned.
        # The current implementation returns the summary, so UI can decide to show it.
        # The print here could be conditional on a verbosity flag or if __name__ == '__main__'.
        # For now, let's keep it as it informs directly if run from console,
        # but ensure errors within the loop also go to stderr.
        print(summary_message, file=sys.stdout if failure_count == 0 else sys.stderr)


        return {
            'run_id': run_id,
            'success_count': success_count,
            'failure_count': failure_count,
            'messages': messages,
            'summary': summary_message
        }

if __name__ == '__main__':
    # This is for basic testing and demonstration if the file is run directly.
    # It requires a mock ConfigManager and a sample autotidy_history.jsonl file.

    class MockConfigManager:
        def get_config_dir_path(self):
            # Point to a directory where a test autotidy_history.jsonl might exist
            # For robust testing, you'd create this file programmatically.
            # Example: current directory for simplicity if you place a test file there.
            return Path(".")

    mock_cm = MockConfigManager()
    undo_mgr = UndoManager(mock_cm)

    # Create a dummy history file for testing
    dummy_history_content = [
        {"run_id": "test_run_1", "timestamp": "2023-01-01T10:00:00Z", "action_taken": "MOVED", "original_path": "dummy_source/fileA.txt", "destination_path": "dummy_archive/fileA.txt", "details": "Moved file"},
        {"run_id": "test_run_1", "timestamp": "2023-01-01T10:00:05Z", "action_taken": "COPIED", "original_path": "dummy_source/fileB.txt", "destination_path": "dummy_archive/fileB_copy.txt", "details": "Copied file"},
        {"run_id": "test_run_2", "timestamp": "2023-01-02T11:00:00Z", "action_taken": "MOVED", "original_path": "dummy_source/fileC.txt", "destination_path": "dummy_archive/fileC.txt", "details": "Moved file"},
        {"run_id": "test_run_1", "timestamp": "2023-01-01T09:59:00Z", "action_taken": "MOVED", "original_path": "dummy_source/file0.txt", "destination_path": "dummy_archive/file0.txt", "details": "Moved file"}, # Earlier action in same run
    ]
    history_file = mock_cm.get_config_dir_path() / "autotidy_history.jsonl"
    with open(history_file, 'w', encoding='utf-8') as f:
        for entry in dummy_history_content:
            f.write(json.dumps(entry) + '\n')

    print("--- Testing get_history_runs() ---")
    runs = undo_mgr.get_history_runs()
    if runs:
        for run in runs:
            print(f"Run ID: {run['run_id']}, Start Time: {run['start_time']}, Actions: {run['action_count']}")
    else:
        print("No history runs found or error reading history.")

    print("\n--- Testing get_run_actions('test_run_1') ---")
    run1_actions = undo_mgr.get_run_actions("test_run_1")
    if run1_actions:
        for action in run1_actions:
            print(f"  Action: {action['action_taken']} from {action['original_path']} to {action['destination_path']} at {action['timestamp']}")
    else:
        print("No actions found for run_id 'test_run_1'.")

    # --- Test undo_batch (simulated - no actual file operations here in __main__) ---
    # To test undo_action and undo_batch properly, you would need to:
    # 1. Create dummy files and directories (e.g., dummy_source/fileA.txt, dummy_archive/)
    # 2. Run undo_batch("test_run_1")
    # 3. Check if files were moved back as expected.
    # This __main__ block is more for checking data parsing and flow.

    print("\n--- Simulating undo_batch('test_run_1') (no file ops in this demo) ---")
    # For a real test, you'd need to set up the file system accordingly.
    # This call will print errors because the dummy files don't exist.

    # Create dummy files for a more realistic test of undo logic for one action
    # (File creation part for a more contained test)
    source_dir = Path("dummy_source_undo_test")
    archive_dir = Path("dummy_archive_undo_test")

    # Clean up before test
    if source_dir.exists(): shutil.rmtree(source_dir)
    if archive_dir.exists(): shutil.rmtree(archive_dir)

    source_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Let's use a specific action from dummy_history_content for a targeted undo test
    # Example: the MOVED action for fileA.txt
    action_to_undo_path_orig = source_dir / "fileA_undo.txt"
    action_to_undo_path_dest = archive_dir / "fileA_undo.txt" # This is where it was "MOVED"

    # Create the "moved" file in the archive
    with open(action_to_undo_path_dest, "w") as f:
        f.write("This file was 'moved'.")

    # Create a specific history entry for this test
    undo_test_run_id = "undo_test_run"
    specific_action_for_undo = {
        "run_id": undo_test_run_id,
        "timestamp": datetime.now().isoformat() + "Z",
        "action_taken": "MOVED",
        "original_path": str(action_to_undo_path_orig),
        "destination_path": str(action_to_undo_path_dest),
        "details": "Test move for undo"
    }
    # Add this to the history file
    with open(history_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(specific_action_for_undo) + '\n')

    print(f"\nAttempting to undo actions for run_id: {undo_test_run_id}")
    print(f"State before undo: {action_to_undo_path_dest} should exist, {action_to_undo_path_orig} should not.")

    undo_results = undo_mgr.undo_batch(undo_test_run_id)
    print("\nUndo Batch Results:")
    print(f"  Summary: {undo_results['summary']}")
    for msg in undo_results['messages']:
        print(f"  - {msg}")

    print(f"\nState after undo: {action_to_undo_path_dest} should NOT exist, {action_to_undo_path_orig} SHOULD exist.")
    print(f"  {action_to_undo_path_dest} exists: {action_to_undo_path_dest.exists()}")
    print(f"  {action_to_undo_path_orig} exists: {action_to_undo_path_orig.exists()}")


    # Cleanup dummy history file and dirs
    # os.remove(history_file) # Comment out if you want to inspect it
    # shutil.rmtree(source_dir)
    # shutil.rmtree(archive_dir)
    print("\n--- End of __main__ tests ---")
    print(f"Note: Review {history_file} and dummy directories for full verification.")
    print("To clean up, delete 'autotidy_history.jsonl', 'dummy_source_undo_test', and 'dummy_archive_undo_test'.")
