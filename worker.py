import threading
import time
from datetime import datetime, timedelta, time as dt_time # Added
import queue
import os
import sys
from pathlib import Path
import uuid

from PyQt6.QtWidgets import QSystemTrayIcon # Added for type hinting

from config_manager import ConfigManager
from utils import check_file, process_file_action
from history_manager import HistoryManager
from notification_manager import NotificationManager # Import NotificationManager
from constants import APP_NAME # Import APP_NAME

# DEFAULT_CHECK_INTERVAL_SECONDS = 3600

class MonitoringWorker(threading.Thread):
    """Worker thread for monitoring folders and organizing files."""

    # Removed check_interval from __init__
    def __init__(self, config_manager: ConfigManager, log_queue: queue.Queue, tray_icon: QSystemTrayIcon): # Added tray_icon
        super().__init__(daemon=True)
        self.config_manager = config_manager
        self.log_queue = log_queue
        self.tray_icon = tray_icon # Store tray_icon
        self._stop_event = threading.Event()
        self.running = False
        self.history_manager = HistoryManager(self.config_manager)
        self.notifier = NotificationManager(app_name=APP_NAME, tray_icon=self.tray_icon) # Instantiate NotificationManager

    def run(self):
        """Main loop for the worker thread."""
        self.running = True
        self.log_queue.put("INFO: Monitoring worker started.")
        self.log_queue.put("STATUS: Running")

        current_run_id = str(uuid.uuid4()) # Generate run_id for this cycle

        while not self._stop_event.is_set():
            total_files_processed_in_cycle = 0 # Initialize for notifications
            errors_occurred_in_cycle = False   # Initialize for notifications
            current_run_id = str(uuid.uuid4()) # New run_id for each cycle

            # Get the list of folders specifically
            folders_to_monitor = self.config_manager.get_monitored_folders()

            if not folders_to_monitor:
                self.log_queue.put("INFO: No folders configured for monitoring.")
                # Optionally, notify if scan completion is on, though usually for active scans
                # if self.config_manager.get_notify_on_scan_completion():
                #    self.notifier.info("Scan Skipped", "No folders configured for monitoring.")
            else:
                is_dry_run = self.config_manager.get_dry_run_mode() # Get dry run mode
                scan_log_prefix = "[DRY RUN] " if is_dry_run else ""
                self.log_queue.put(f"INFO: {scan_log_prefix}Starting scan of {len(folders_to_monitor)} configured folder(s)...")

                archive_template = self.config_manager.get_archive_path_template()
                for folder_config in folders_to_monitor:
                    if self._stop_event.is_set(): # Check before processing each folder
                        self.log_queue.put("INFO: Stop event received during folder scan.")
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
                                if check_file(item, age_days, pattern, use_regex):
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
                                        current_run_id # run_id
                                    )
                                    self.log_queue.put(f"{'INFO' if success else 'ERROR'}: {message}")
                                    if success:
                                        files_processed_count += 1
                                    # If process_file_action itself logged an error (returned success=False), mark it
                                    elif not success: # An error occurred for this file action
                                        errors_occurred_in_cycle = True


                    except PermissionError as e:
                         error_msg = f"ERROR: Permission denied accessing folder: {monitored_path}"
                         self.log_queue.put(error_msg)
                         errors_occurred_in_cycle = True
                    except Exception as e:
                         error_msg = f"ERROR: Unexpected error scanning {monitored_path}: {e}"
                         self.log_queue.put(error_msg)
                         errors_occurred_in_cycle = True

                    total_files_processed_in_cycle += files_processed_count
                    if files_processed_count > 0: # Log per-folder summary if any files were processed for it
                         self.log_queue.put(f"INFO: Finished scan for {monitored_path}, processed {files_processed_count} file(s).")

                if self._stop_event.is_set():
                    self.log_queue.put("INFO: Scan cycle interrupted by stop signal.")
                else:
                    self.log_queue.put("INFO: Scan cycle complete.")
                    # --- Notifications for end of cycle ---
                    if self.config_manager.get_notify_on_actions_summary() and total_files_processed_in_cycle > 0:
                        self.notifier.info("Scan Summary", f"Successfully processed {total_files_processed_in_cycle} file(s).")

                    if self.config_manager.get_notify_on_scan_completion() and not (self.config_manager.get_notify_on_actions_summary() and total_files_processed_in_cycle > 0) :
                        # Avoid double notification if summary already shown.
                        # Or, always show "Scan Complete" if desired, even if summary was also shown.
                        # For now, show if summary wasn't shown or if no files were processed.
                        if total_files_processed_in_cycle == 0 :
                             self.notifier.info("Scan Complete", "AutoTidy finished a scan cycle. No files met criteria.")
                        # else: # If summary was on and files were processed, this would be redundant
                             # self.notifier.info("Scan Complete", "AutoTidy has finished a scan cycle.")


                    if self.config_manager.get_notify_on_errors() and errors_occurred_in_cycle:
                        self.notifier.error("Scan Errors", "One or more errors occurred during the last scan. Please check logs.")

            # --- Scheduling Logic ---
            schedule_config = self.config_manager.get_schedule_config()
            sleep_duration_seconds, next_run_info = self._calculate_sleep_duration(schedule_config)

            self.log_queue.put(f"INFO: {next_run_info}")
            self._stop_event.wait(sleep_duration_seconds)

        self.running = False
        self.log_queue.put("INFO: Monitoring worker stopped.")
        self.log_queue.put("STATUS: Stopped")


    def stop(self):
        """Signals the worker thread to stop."""
        self._stop_event.set()

    def _calculate_sleep_duration(self, schedule_config: dict) -> tuple[float, str]:
        """
        Calculates the sleep duration until the next scheduled run.
        Returns a tuple of (sleep_duration_in_seconds, human_readable_next_run_info).
        """
        schedule_type = schedule_config.get('type', 'interval')
        now = datetime.now()
        next_run_datetime = None
        next_run_info = ""

        if schedule_type == 'interval':
            interval_minutes = schedule_config.get('interval_minutes', 60)
            sleep_seconds = interval_minutes * 60
            next_run_datetime = now + timedelta(seconds=sleep_seconds)
            next_run_info = f"Next check in {interval_minutes} minute(s) (Interval)."
            return max(1.0, float(sleep_seconds)), next_run_info

        elif schedule_type == 'daily':
            time_str = schedule_config.get('specific_time', '00:00')
            try:
                run_time_obj = dt_time.fromisoformat(time_str)
            except ValueError:
                self.log_queue.put(f"WARNING: Invalid specific_time format '{time_str}'. Defaulting to 00:00.")
                run_time_obj = dt_time(0, 0)

            next_run_datetime_today = now.replace(hour=run_time_obj.hour, minute=run_time_obj.minute, second=0, microsecond=0)
            if next_run_datetime_today <= now:
                next_run_datetime = next_run_datetime_today + timedelta(days=1)
            else:
                next_run_datetime = next_run_datetime_today
            next_run_info = f"Next check scheduled daily at {next_run_datetime.strftime('%H:%M')} on {next_run_datetime.strftime('%Y-%m-%d')}."

        elif schedule_type == 'weekly':
            time_str = schedule_config.get('specific_time', '00:00')
            days_of_week_config = schedule_config.get('days_of_week', []) # e.g., ["monday", "friday"]

            if not days_of_week_config:
                self.log_queue.put("WARNING: Weekly schedule chosen but no days selected. Defaulting to 1 hour interval.")
                return max(1.0, float(3600)), "Weekly schedule misconfigured (no days), next check in 1 hour."

            try:
                run_time_obj = dt_time.fromisoformat(time_str)
            except ValueError:
                self.log_queue.put(f"WARNING: Invalid specific_time format for weekly schedule '{time_str}'. Defaulting to 00:00.")
                run_time_obj = dt_time(0, 0)

            # Map day names to datetime weekday numbers (0=Monday, 6=Sunday)
            day_map = {
                "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                "friday": 4, "saturday": 5, "sunday": 6
            }
            target_weekdays = {day_map[day.lower()] for day in days_of_week_config if day.lower() in day_map}

            if not target_weekdays:
                self.log_queue.put("WARNING: Weekly schedule days misconfigured. Defaulting to 1 hour interval.")
                return max(1.0, float(3600)), "Weekly schedule days misconfigured, next check in 1 hour."

            # Iterate for up to 7 days to find the next valid run day and time
            for i in range(8): # Check today and next 7 days
                potential_date = (now + timedelta(days=i)).date()
                if potential_date.weekday() in target_weekdays:
                    candidate_datetime = datetime.combine(potential_date, run_time_obj)
                    if candidate_datetime > now:
                        next_run_datetime = candidate_datetime
                        break

            if next_run_datetime:
                next_run_info = f"Next check scheduled weekly on {next_run_datetime.strftime('%A')} at {next_run_datetime.strftime('%H:%M')} ({next_run_datetime.strftime('%Y-%m-%d')})."
            else:
                # Should not happen if target_weekdays is populated and loop is correct
                self.log_queue.put("ERROR: Could not determine next weekly run time. Defaulting to 1 hour interval.")
                return max(1.0, float(3600)), "Error in weekly schedule, next check in 1 hour."

        else: # Unknown schedule type
            self.log_queue.put(f"WARNING: Unknown schedule type '{schedule_type}'. Defaulting to 1 hour interval.")
            return max(1.0, float(3600)), "Unknown schedule type, next check in 1 hour."

        if next_run_datetime:
            sleep_seconds = (next_run_datetime - now).total_seconds()
            return max(1.0, sleep_seconds), next_run_info
        else:
            # Fallback, should ideally be handled by specific type logic
            self.log_queue.put(f"ERROR: Could not determine next run time for schedule type '{schedule_type}'. Defaulting to 1 hour interval.")
            return max(1.0, float(3600)), "Error in schedule calculation, next check in 1 hour."
