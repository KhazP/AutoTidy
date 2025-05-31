import threading
import time
import queue
import os
import sys
from pathlib import Path
import uuid

from config_manager import ConfigManager
from utils import check_file, process_file_action
from history_manager import HistoryManager # Import HistoryManager

# DEFAULT_CHECK_INTERVAL_SECONDS = 3600

class MonitoringWorker(threading.Thread):
    """Worker thread for monitoring folders and organizing files."""

    # Removed check_interval from __init__
    def __init__(self, config_manager: ConfigManager, log_queue: queue.Queue):
        super().__init__(daemon=True)
        self.config_manager = config_manager
        self.log_queue = log_queue
        self._stop_event = threading.Event()
        self.running = False
        self.history_manager = HistoryManager(self.config_manager) # Instantiate HistoryManager

    def run(self):
        """
        Main operational loop of the monitoring worker thread.

        This method continuously scans configured folders based on the schedule
        defined in the application's configuration. For each folder, it iterates
        through files, checking them against specified criteria (age, pattern).
        If a file matches, it performs the configured action (move, copy, delete).

        The loop respects a stop event (`self._stop_event`), allowing for graceful
        termination. If the event is set, the loop will attempt to finish its
        current folder scan and then exit, or it will break during the sleep
        interval. All operations, errors, and status changes are logged via the
        provided `log_queue`.
        """
        self.running = True
        self.log_queue.put("INFO: Monitoring worker started.")
        self.log_queue.put("STATUS: Running")

        current_run_id = str(uuid.uuid4()) # Generate run_id for this cycle

        while not self._stop_event.is_set():
            # Get the list of folders specifically
            folders_to_monitor = self.config_manager.get_monitored_folders()

            if not folders_to_monitor:
                self.log_queue.put("INFO: No folders configured for monitoring.")
            else:
                is_dry_run = self.config_manager.get_dry_run_mode() # Get dry run mode
                scan_log_prefix = "[DRY RUN] " if is_dry_run else ""
                self.log_queue.put(f"INFO: {scan_log_prefix}Starting scan of {len(folders_to_monitor)} configured folder(s)...")

                archive_template = self.config_manager.get_archive_path_template()
                for folder_config in folders_to_monitor:
                    if self._stop_event.is_set():
                        break

                    path_str = folder_config.get('path')
                    age_days = folder_config.get('age_days', 0)
                    pattern = folder_config.get('pattern', '*.*')
                    use_regex = folder_config.get('use_regex', False)
                    action_to_perform = folder_config.get('action', 'move') # Get action

                    if not path_str:
                        self.log_queue.put("WARNING: Skipping entry with missing path.")
                        continue

                    monitored_path = Path(path_str)
                    if not monitored_path.is_dir():
                        self.log_queue.put(f"ERROR: Monitored path is not a directory or does not exist: {path_str}")
                        continue

                    scan_mode = "Regex" if use_regex else "Pattern"
                    action_desc_map = {
                        "move": "Moving",
                        "copy": "Copying",
                        "delete_to_trash": "Deleting to Trash",
                        "delete_permanently": "Deleting Permanently"
                    }
                    action_desc = action_desc_map.get(action_to_perform, f"Unknown Action ({action_to_perform})")
                    # Add scan_log_prefix to individual folder scan message
                    self.log_queue.put(f"INFO: {scan_log_prefix}Scanning {monitored_path} (Age > {age_days} days, {scan_mode}: '{pattern}', Action: {action_desc})")
                    files_processed_count = 0
                    try:
                        for item in monitored_path.iterdir():
                             if self._stop_event.is_set():
                                break

                             if item.is_file():
                                if check_file(item, age_days, pattern, use_regex, self.log_queue): # Pass log_queue
                                    success, message = process_file_action(
                                        item,
                                        monitored_path,
                                        archive_template,
                                        action_to_perform,
                                        is_dry_run,
                                        pattern, # rule_pattern
                                        age_days, # rule_age_days
                                        use_regex, # rule_use_regex
                                        self.history_manager.log_action, # history_logger_callable
                                        current_run_id, # run_id
                                        self.log_queue # Pass log_queue
                                    )
                                    self.log_queue.put(f"{'INFO' if success else 'ERROR'}: {message}")
                                    if success:
                                        files_processed_count += 1

                    except PermissionError:
                         self.log_queue.put(f"ERROR: PermissionError denied accessing folder: {monitored_path}")
                    except Exception as e:
                         self.log_queue.put(f"ERROR: Unexpected {type(e).__name__} while scanning {monitored_path}: {e}")

                    if files_processed_count > 0:
                         self.log_queue.put(f"INFO: Finished scan for {monitored_path}, processed {files_processed_count} file(s).")


                self.log_queue.put("INFO: Scan cycle complete.")

            # Fetch schedule config for the sleep interval
            schedule_config = self.config_manager.get_schedule_config()
            interval_minutes = schedule_config.get('interval_minutes', 60) # Default to 60 if somehow missing
            sleep_duration_seconds = interval_minutes * 60

            # Wait for the next interval or until stop event is set
            self.log_queue.put(f"INFO: Next check in {interval_minutes} minute(s)...")
            self._stop_event.wait(sleep_duration_seconds)

        self.running = False
        self.log_queue.put("INFO: Monitoring worker stopped.")
        self.log_queue.put("STATUS: Stopped")


    def stop(self):
        """
        Signals the worker thread to stop its operations cleanly.

        This method sets an internal threading event (`self._stop_event`).
        The `run` method's main loop checks this event and, if set,
        will break out of its scanning and processing cycle before starting
        a new scan or after its current sleep interval finishes. This allows
        the thread to shut down gracefully.
        """
        self._stop_event.set()
