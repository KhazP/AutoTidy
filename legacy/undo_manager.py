import json
import logging
import os
import shutil
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

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
                        logger.warning("Skipping corrupted JSON line in history: %s", line.strip())
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
            logger.error("Error reading history file %s: %s", self.history_file_path, e)
            return []
        except Exception as e:
            logger.error("Unexpected error processing history runs: %s", e)
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
                                logger.warning("Skipping action with invalid or missing timestamp: %s", action.get('original_path', 'N/A'))
                                continue
                    except json.JSONDecodeError:
                        logger.warning("Skipping corrupted JSON line in history: %s", line.strip())
                        continue

            # Sort actions by their actual timestamp
            actions_for_run.sort(key=lambda x: x['timestamp_obj'])

            # Remove the temporary timestamp object if not needed downstream
            for action in actions_for_run:
                del action['timestamp_obj']

            return actions_for_run
        except IOError as e:
            logger.error("Error reading history file %s: %s", self.history_file_path, e)
            return []
        except Exception as e:
            logger.error("Unexpected error fetching run actions: %s", e)
            return []

    def undo_action(self, action_data: dict):
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
                    if original_path.exists():
                        # This case needs careful handling.
                        # If original_path is a directory, we might be able to move into it.
                        # If original_path is a file, it's a conflict.
                        # For now, let's be conservative and not overwrite.
                        return False, f"Error: Original path {original_path} already exists. Cannot move {destination_path} back without overwriting."

                    # Ensure parent directory of original_path exists for the move back
                    original_path.parent.mkdir(parents=True, exist_ok=True)

                    shutil.move(str(destination_path), str(original_path))
                    return True, f"Successfully moved {destination_path} back to {original_path}"
                else:
                    return False, f"Error: Destination path {destination_path} does not exist. Cannot undo move."

            except FileNotFoundError:
                # This message is already specific and good.
                return False, f"Error: File not found during undo. Source: {destination_path} or Target Parent: {original_path.parent}"
            except PermissionError:
                return False, f"Error: Permission denied during undo operation on '{destination_path}' or '{original_path}'."
            except OSError as e:
                return False, f"OS error during undo ({action_taken}) on '{destination_path}' or '{original_path}': {e}"

        elif action_taken == "COPIED":
            # Undoing a copy means deleting the copied file (destination_path)
            destination_path_str = action_data.get("destination_path")
            if not destination_path_str:
                return False, "Error: Missing destination path for COPIED action."

            destination_path = Path(destination_path_str)
            try:
                if not destination_path.exists():
                    return False, f"Error: Copied file {destination_path} does not exist. Cannot undo copy."
                if not destination_path.is_file():
                    return False, f"Error: Destination {destination_path} is not a file. Cannot undo copy."

                # Verify file identity using stored size and mtime before deleting
                stored_size = action_data.get("copy_size")
                stored_mtime = action_data.get("copy_mtime")
                if stored_size is not None or stored_mtime is not None:
                    try:
                        stat = destination_path.stat()
                        if stored_size is not None and stat.st_size != stored_size:
                            return False, (
                                f"Error: File '{destination_path.name}' size has changed since copy "
                                f"(expected {stored_size} bytes, found {stat.st_size}). "
                                "Undo aborted to prevent data loss."
                            )
                        if stored_mtime is not None and abs(stat.st_mtime - stored_mtime) > 2.0:
                            return False, (
                                f"Error: File '{destination_path.name}' modification time has changed since copy. "
                                "Undo aborted to prevent data loss."
                            )
                    except OSError as e:
                        return False, f"Error: Could not verify file identity for '{destination_path}': {e}"

                os.remove(destination_path)
                return True, f"Successfully deleted copied file: {destination_path}"
            except FileNotFoundError:
                return False, f"Error: Copied file '{destination_path}' not found during deletion."
            except PermissionError:
                return False, f"Error: Permission denied trying to delete '{destination_path}'."
            except OSError as e:
                return False, f"OS error deleting copied file '{destination_path}': {e}"

        # Placeholder for other actions like DELETED_TO_TRASH or DELETED_PERMANENTLY
        # Undoing DELETED_PERMANENTLY is not possible.
        # Undoing DELETED_TO_TRASH would require interacting with the trash, which is platform-specific.
        else:
            return False, f"Undo not supported for action: {action_taken}"

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
        logger.info(summary_message)

        return {
            'run_id': run_id,
            'success_count': success_count,
            'failure_count': failure_count,
            'messages': messages,
            'summary': summary_message
        }

