import threading
import time
import queue
import os
import sys
import logging
from pathlib import Path
import uuid
import fnmatch
import re

from config_manager import ConfigManager
from constants import (
    NOTIFICATION_LEVEL_NONE,
    NOTIFICATION_LEVEL_ERROR,
    NOTIFICATION_LEVEL_SUMMARY,
)
import constants
from utils import check_file, process_file_action, safe_regex_match, _compile_pattern
from history_manager import HistoryManager

logger = logging.getLogger(__name__)

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

    def _should_send_notification(self, category: str) -> bool:
        """Return True when the current level allows the notification category."""
        level = self.config_manager.get_notification_level()
        if level == NOTIFICATION_LEVEL_NONE:
            return False
        if level == NOTIFICATION_LEVEL_ERROR:
            return category == "error"
        if level == NOTIFICATION_LEVEL_SUMMARY:
            return category in {"summary", "error"}
        # Level == ALL (or any unrecognized value) defaults to permitting notifications.
        return True

    def _queue_notification(self, category: str, title: str, message: str):
        if self._should_send_notification(category):
            self.log_queue.put({
                "type": "SHOW_NOTIFICATION",
                "title": title,
                "message": message,
                "category": category,
            })

    def _log_error(self, message: str):
        formatted = f"ERROR: {message}"
        self.log_queue.put(formatted)
        self._queue_notification("error", "AutoTidy Error", message)

    def run(self):
        """Main loop for the worker thread."""
        self.running = True
        self.log_queue.put("INFO: Monitoring worker started.")
        self.log_queue.put("STATUS: Running")

        while not self._stop_event.is_set():
            current_run_id = str(uuid.uuid4()) # Generate run_id for this cycle
            # Get the list of folders specifically
            folders_to_monitor = self.config_manager.get_monitored_folders()
            total_files_processed_in_cycle = 0 # Initialize for the cycle

            if not folders_to_monitor:
                self.log_queue.put("INFO: No folders configured for monitoring.")
            else:
                is_dry_run = self.config_manager.get_dry_run_mode() # Get dry run mode
                scan_log_prefix = "[DRY RUN] " if is_dry_run else ""
                self.log_queue.put(f"INFO: {scan_log_prefix}Starting scan of {len(folders_to_monitor)} configured folder(s)...")

                archive_template = self.config_manager.get_archive_path_template()
                excluded_folders = self.config_manager.get_excluded_folders()
                for folder_config in folders_to_monitor:
                    if self._stop_event.is_set():
                        break

                    path_str = folder_config.get('path')
                    if not folder_config.get('enabled', True):
                        display_path = path_str or "<unknown path>"
                        self.log_queue.put(f"INFO: Skipping disabled rule for {display_path}.")
                        continue
                    age_days = folder_config.get('age_days', 0)
                    pattern = folder_config.get('pattern', '*.*')
                    use_regex = folder_config.get('use_regex', False)
                    exclusions = folder_config.get('exclusions', [])
                    rule_logic = folder_config.get('rule_logic', 'OR')
                    action_to_perform = folder_config.get('action', 'move') # Get action
                    destination_folder = folder_config.get('destination_folder', '')

                    if not path_str:
                        self.log_queue.put("WARNING: Skipping entry with missing path.")
                        continue

                    monitored_path = Path(path_str)
                    if not monitored_path.is_dir():
                        self._log_error(f"Monitored path is not a directory or does not exist: {path_str}")
                        continue

                    # Check against global excluded folders before scanning
                    normalized_path = str(monitored_path.resolve())
                    if any(normalized_path == str(Path(ef).resolve()) for ef in excluded_folders if ef):
                        self.log_queue.put(f"INFO: Skipping globally excluded folder: {path_str}")
                        continue

                    scan_mode = "Regex" if use_regex else "Pattern"
                    action_desc_map = {
                        "move": "Moving",
                        "copy": "Copying",
                        "delete_to_trash": "Deleting to Trash",
                        "delete_permanently": "Deleting Permanently"
                    }
                    action_desc = action_desc_map.get(action_to_perform, f"Unknown Action ({action_to_perform})")
                    self.log_queue.put(f"INFO: {scan_log_prefix}Scanning {monitored_path} (Age > {age_days} days, {scan_mode}: '{pattern}', Action: {action_desc})")
                    files_processed_this_folder = 0 # Initialize for this folder

                    # Pre-compile patterns once per rule (not per file) for performance
                    if use_regex and pattern:
                        _compile_pattern(pattern)  # warm the cache; matching uses compiled form
                    compiled_exclusions = []
                    for excl in exclusions:
                        if not excl:
                            continue
                        if use_regex:
                            compiled_exclusions.append(('regex', excl))
                            _compile_pattern(excl)  # warm cache for this exclusion too
                        else:
                            compiled_exclusions.append(('glob', excl))

                    try:
                        with os.scandir(str(monitored_path)) as scanner:
                            dir_entries = list(scanner)

                        for entry in dir_entries:
                            if self._stop_event.is_set():
                                break

                            if entry.is_symlink():
                                logger.debug("Skipping symlink: %s", entry.path)
                                continue

                            if not entry.is_file(follow_symlinks=False):
                                continue

                            item_name = entry.name
                            item_path = Path(entry.path)

                            # Check exclusions first (cheaper, matches documented behavior)
                            is_excluded = False
                            for excl_type, excl_val in compiled_exclusions:
                                if excl_type == 'regex':
                                    result = safe_regex_match(excl_val, item_name)
                                    if result is not None and result:
                                        is_excluded = True
                                        break
                                    elif result is None:
                                        self._log_error(
                                            f"Invalid or timed-out exclusion pattern '{excl_val}' for {monitored_path}"
                                        )
                                else:
                                    if fnmatch.fnmatch(item_name, excl_val):
                                        is_excluded = True
                                        break

                            if is_excluded:
                                details_message = f"Skipped excluded file: {item_name}"
                                self.log_queue.put(f"INFO: {details_message}")
                                self.history_manager.log_action({
                                    "original_path": str(item_path),
                                    "action_taken": constants.ACTION_SKIPPED,
                                    "destination_path": None,
                                    "monitored_folder": str(monitored_path),
                                    "rule_pattern": pattern,
                                    "rule_age_days": age_days,
                                    "rule_use_regex": use_regex,
                                    "rule_action_config": action_to_perform,
                                    "status": constants.STATUS_SKIPPED,
                                    "details": details_message,
                                    "run_id": current_run_id,
                                })
                                continue

                            # Pass cached stat to check_file to avoid a second syscall
                            entry_stat = entry.stat(follow_symlinks=False)
                            if check_file(item_path, age_days, pattern, use_regex, rule_logic,
                                          precomputed_stat=entry_stat):
                                success, message = process_file_action(
                                    item_path,
                                    monitored_path,
                                    archive_template,
                                    action_to_perform,
                                    is_dry_run,
                                    pattern, # rule_pattern
                                    age_days, # rule_age_days
                                    use_regex, # rule_use_regex
                                    self.history_manager.log_action, # history_logger_callable
                                    current_run_id, # run_id
                                    destination_folder
                                )
                                self.log_queue.put(f"{'INFO' if success else 'ERROR'}: {message}")
                                if success:
                                    files_processed_this_folder += 1

                    except PermissionError:
                         self._log_error(f"Permission denied accessing folder: {monitored_path}")
                    except Exception as e:
                         self._log_error(f"Unexpected error scanning {monitored_path}: {e}")

                    if files_processed_this_folder > 0:
                         self.log_queue.put(f"INFO: Finished scan for {monitored_path}, processed {files_processed_this_folder} file(s).")
                    total_files_processed_in_cycle += files_processed_this_folder # Accumulate for the cycle

                if total_files_processed_in_cycle > 0:
                    self._queue_notification(
                        "summary",
                        "AutoTidy Scan Complete",
                        f"{total_files_processed_in_cycle} file(s) processed successfully."
                    )
                
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
        """Signals the worker thread to stop."""
        self._stop_event.set()
