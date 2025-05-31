import threading
import time
import queue
import os
import sys
from pathlib import Path

from config_manager import ConfigManager
from utils import check_file, move_file

DEFAULT_CHECK_INTERVAL_SECONDS = 3600 # 1 hour

class MonitoringWorker(threading.Thread):
    """Worker thread for monitoring folders and organizing files."""

    def __init__(self, config_manager: ConfigManager, log_queue: queue.Queue, check_interval: int = DEFAULT_CHECK_INTERVAL_SECONDS):
        super().__init__(daemon=True) # Daemon threads exit when main thread exits
        self.config_manager = config_manager
        self.log_queue = log_queue
        self.check_interval = check_interval
        self._stop_event = threading.Event()
        self.running = False # Track running state

    def run(self):
        """Main loop for the worker thread."""
        self.running = True
        self.log_queue.put("INFO: Monitoring worker started.")
        self.log_queue.put("STATUS: Running")

        while not self._stop_event.is_set():
            folders_to_monitor = self.config_manager.get_monitored_folders()
            # Fetch archive format string once per scan cycle, as it's a global setting
            archive_format = self.config_manager.get_setting("archive_structure_format", "%Y-%m-%d")

            if not folders_to_monitor:
                self.log_queue.put("INFO: No folders configured for monitoring.")
            else:
                self.log_queue.put(f"INFO: Starting scan of {len(folders_to_monitor)} configured folder(s)...")
                for folder_config in folders_to_monitor:
                    if self._stop_event.is_set():
                        break # Exit loop if stopped during scan

                    path_str = folder_config.get('path')
                    age_days = folder_config.get('age_days', 0)
                    pattern = folder_config.get('pattern', '*.*')
                    rule_logic = folder_config.get('rule_logic', 'OR')
                    pattern_type = folder_config.get('pattern_type', 'glob') # Fetch pattern_type, default to glob

                    if not path_str:
                        self.log_queue.put("WARNING: Skipping entry with missing path.")
                        continue

                    monitored_path = Path(path_str)
                    if not monitored_path.is_dir():
                        self.log_queue.put(f"ERROR: Monitored path is not a directory or does not exist: {path_str}")
                        continue

                    self.log_queue.put(f"INFO: Scanning {monitored_path} (Age > {age_days} days {rule_logic.upper()} Pattern ({pattern_type}): '{pattern}')")
                    files_moved_count = 0
                    try:
                        # Iterate through items in the directory (non-recursive for MVP)
                        for item in monitored_path.iterdir():
                             if self._stop_event.is_set():
                                break # Exit inner loop if stopped

                             if item.is_file():
                                if check_file(item, age_days, pattern, rule_logic, pattern_type):
                                    success, message = move_file(item, monitored_path, archive_format) # Pass archive_format
                                    self.log_queue.put(f"{'INFO' if success else 'ERROR'}: {message}")
                                    if success:
                                        files_moved_count += 1

                    except PermissionError:
                         self.log_queue.put(f"ERROR: Permission denied accessing folder: {monitored_path}")
                    except Exception as e:
                         self.log_queue.put(f"ERROR: Unexpected error scanning {monitored_path}: {e}")

                    if files_moved_count > 0:
                         self.log_queue.put(f"INFO: Finished scan for {monitored_path}, moved {files_moved_count} file(s).")


                self.log_queue.put("INFO: Scan cycle complete.")

            # Wait for the next interval or until stop event is set
            self.log_queue.put(f"INFO: Waiting for {self.check_interval} seconds...")
            self._stop_event.wait(self.check_interval)

        self.running = False
        self.log_queue.put("INFO: Monitoring worker stopped.")
        self.log_queue.put("STATUS: Stopped")


    def stop(self):
        """Signals the worker thread to stop."""
        self._stop_event.set()
