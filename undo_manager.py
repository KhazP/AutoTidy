import json
import os
import shutil
from pathlib import Path
from datetime import datetime

class UndoManager:
    def __init__(self, config_manager):
        self.config_manager = config_manager
        # Assuming config_manager has a method like get_config_dir_path()
        self.history_file_path = self.config_manager.get_config_dir_path() / "autotidy_history.jsonl"

    def get_history_runs(self):
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
                            action_timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                        except ValueError:
                            # Skip if timestamp is not in a recognized ISO format
                            continue


                        if run_id not in runs:
                            runs[run_id] = {
                                "run_id": run_id,
                                "start_time": action_timestamp,
                                "action_count": 0,
                                "actions": [] # Temp store actions to sort later for start_time
                            }

                        runs[run_id]["actions"].append(action_timestamp)
                        runs[run_id]["action_count"] += 1
                    except json.JSONDecodeError:
                        # Log or handle corrupted lines if necessary
                        print(f"Warning: Skipping corrupted JSON line in history: {line.strip()}")
                        continue

            # Determine the earliest timestamp for each run and format it
            processed_runs = []
            for run_id, data in runs.items():
                if data["actions"]:
                    data["start_time"] = min(data["actions"]).isoformat()
                else: # Should not happen if actions is populated correctly
                    data["start_time"] = None
                del data["actions"] # Remove temporary list of actions
                processed_runs.append(data)

            # Sort runs by start_time, most recent first
            processed_runs.sort(key=lambda r: datetime.fromisoformat(r['start_time']), reverse=True)
            return processed_runs

        except IOError as e:
            print(f"Error reading history file {self.history_file_path}: {e}")
            return []
        except Exception as e:
            print(f"An unexpected error occurred while processing history runs: {e}")
            return []


    def get_run_actions(self, run_id_to_find: str):
        if not self.history_file_path.exists():
            return []

        actions_for_run = []
        try:
            with open(self.history_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        action = json.loads(line)
                        if action.get("run_id") == run_id_to_find:
                            # Add timestamp object for sorting, convert back to string later if needed
                            try:
                                action['timestamp_obj'] = datetime.fromisoformat(action.get("timestamp").replace("Z", "+00:00"))
                                actions_for_run.append(action)
                            except (ValueError, AttributeError):
                                print(f"Warning: Skipping action with invalid or missing timestamp: {action.get('original_path', 'N/A')}")
                                continue
                    except json.JSONDecodeError:
                        print(f"Warning: Skipping corrupted JSON line in history: {line.strip()}")
                        continue

            # Sort actions by their actual timestamp
            actions_for_run.sort(key=lambda x: x['timestamp_obj'])

            # Remove the temporary timestamp object if not needed downstream
            for action in actions_for_run:
                del action['timestamp_obj']

            return actions_for_run
        except IOError as e:
            print(f"Error reading history file {self.history_file_path}: {e}")
            return []
        except Exception as e:
            print(f"An unexpected error occurred while fetching run actions: {e}")
            return []

    def undo_action(self, action_data: dict):
        action_taken = action_data.get("action_taken")
        original_path_str = action_data.get("original_path") # Keep for logging, might be None
        destination_path_str = action_data.get("destination_path") # Keep for logging, might be None

        if not action_taken:
            return False, "Error: Missing 'action_taken' in action data."

        # Handle simulated actions first
        if action_taken.startswith("SIMULATED_"):
            return True, f"Action '{action_taken}' was simulated, no undo operation needed for original: '{original_path_str}', destination: '{destination_path_str}'."

        if action_taken == "MOVED":
            # original_path_str and destination_path_str already fetched
            destination_path_str = action_data.get("destination_path")

            if not original_path_str or not destination_path_str:
                return False, "Error: Missing original or destination path in action data."

            original_path = Path(original_path_str)
            destination_path = Path(destination_path_str)

            try:
                if destination_path.exists():
                    # Check if original_path is a directory; if so, the file can be moved into it.
                    # If original_path itself exists as a file, it's a conflict.
                    final_original_path = original_path
                    if original_path.is_dir():
                        final_original_path = original_path / destination_path.name

                    if final_original_path.exists() and final_original_path.is_file():
                         return False, f"Error: Original path target {final_original_path} already exists as a file. Cannot move {destination_path} back without overwriting."

                    # Ensure parent directory of final_original_path exists for the move back
                    final_original_path.parent.mkdir(parents=True, exist_ok=True)

                    shutil.move(str(destination_path), str(final_original_path))
                    return True, f"Successfully moved {destination_path} back to {final_original_path}"
                else:
                    return False, f"Error: Source file {destination_path} (from previous destination) does not exist. Cannot undo move."

            except FileNotFoundError: # Should be caught by destination_path.exists() but as safeguard
                return False, f"Error: File not found during undo. Source: {destination_path} or Target Parent: {original_path.parent}"
            except PermissionError:
                return False, f"Error: Permission denied during undo operation on '{destination_path}' or '{original_path}'."
            except OSError as e:
                return False, f"OS error during undo ({action_taken}) on '{destination_path}' or '{original_path}': {e}"

        elif action_taken == "COPIED":
            # destination_path_str already fetched
            if not destination_path_str:
                return False, "Error: Missing destination path for COPIED action. Cannot undo."

            destination_path = Path(destination_path_str)
            try:
                if destination_path.is_file():
                    os.remove(destination_path)
                    return True, f"Successfully deleted copied file: {destination_path}"
                elif not destination_path.exists():
                    return False, f"Error: Copied file {destination_path} does not exist (already deleted or moved). Cannot undo copy."
                else: # It's a directory or other type
                    return False, f"Error: Destination {destination_path} is not a file. Cannot undo copy with os.remove."
            except FileNotFoundError: # Should be caught by exists() check, but for safety
                return False, f"Error: Copied file '{destination_path}' not found during deletion (should have been caught by exists check)."
            except PermissionError:
                return False, f"Error: Permission denied trying to delete copied file '{destination_path}'."
            except OSError as e: # Catch other OS-level errors like disk issues
                return False, f"OS error deleting copied file '{destination_path}': {e}"

        elif action_taken == "DELETED_TO_TRASH":
            # For now, this is a placeholder. Restoring from trash is OS-dependent.
            message = (f"Undo for '{action_taken}' on file '{original_path_str}' is not automatically implemented. "
                       "Please check your system's Recycle Bin or Trash for the file.")
            # Log this as a warning or info if a logging mechanism is available here.
            # For now, returning it in the message is sufficient for the UI.
            return False, message # False because the action wasn't automatically undone

        elif action_taken == "DELETED_PERMANENTLY":
            return False, f"Action '{action_taken}' on file '{original_path_str}' cannot be undone as it was a permanent deletion."

        else:
            return False, f"Undo not supported or action type unknown for: '{action_taken}' on file '{original_path_str}'."

    def undo_batch(self, run_id: str):
        actions_to_undo = self.get_run_actions(run_id)
        if not actions_to_undo:
            return {'success_count': 0, 'failure_count': 0, 'messages': [f"No actions found for run_id: {run_id}"]}

        success_count = 0
        failure_count = 0
        messages = []

        # Iterate in reverse order of when they were performed
        for action_data in reversed(actions_to_undo):
            original_path_display = action_data.get('original_path', 'N/A')
            action_display = action_data.get('action_taken', 'N/A')
            dest_path_display = action_data.get('destination_path', 'N/A')

            timestamp_display = action_data.get('timestamp', 'N/A')
            message_prefix = f"Action (Timestamp: {timestamp_display}, Orig: {original_path_display}, Dest: {dest_path_display}, Type: {action_display}): "

            success, message = self.undo_action(action_data)
            messages.append(message_prefix + message)
            if success:
                success_count += 1
            else:
                failure_count += 1

        summary_message = f"Undo batch for run_id '{run_id}' complete. Successes: {success_count}, Failures: {failure_count}."
        print(summary_message) # Also print to console for immediate feedback

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
