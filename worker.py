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
from semantic_analyzer import (
    get_file_type,
    extract_text_from_document, SUPPORTED_DOCUMENT_MIME_TYPES,
    extract_image_features, SUPPORTED_IMAGE_MIME_TYPES,
    extract_media_metadata, SUPPORTED_MEDIA_MIME_TYPES,
    generate_tags # Import generate_tags
)

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
        """Main loop for the worker thread."""
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
                    if not path_str:
                        self.log_queue.put("WARNING: Skipping folder entry with missing path.")
                        continue

                    monitored_path = Path(path_str)
                    if not monitored_path.is_dir():
                        self.log_queue.put(f"ERROR: Monitored path is not a directory or does not exist: {path_str}")
                        continue

                    rules_for_folder = folder_config.get('rules', [])
                    if not rules_for_folder:
                        self.log_queue.put(f"INFO: No rules defined for folder: {monitored_path}")
                        continue

                    self.log_queue.put(f"INFO: {scan_log_prefix}Scanning {monitored_path} with {len(rules_for_folder)} rule(s)...")
                    files_processed_count_for_folder = 0 # Renamed for clarity per folder

                    try:
                        for item in monitored_path.iterdir():
                            if self._stop_event.is_set():
                                break

                            if not item.is_file():
                                continue

                            # --- Semantic Analysis (done once per file) ---
                            mime_type = get_file_type(str(item))
                            self.log_queue.put(f"DEBUG: File {item.name} MIME type: {mime_type}")

                            extracted_text = None
                            if mime_type and not mime_type.startswith("Error:") and mime_type in SUPPORTED_DOCUMENT_MIME_TYPES:
                                extracted_text = extract_text_from_document(str(item), mime_type)
                                # Logging for extracted_text done in semantic_analyzer or can be added here if needed

                            image_features = None
                            if mime_type and not mime_type.startswith("Error:") and mime_type in SUPPORTED_IMAGE_MIME_TYPES:
                                image_features = extract_image_features(str(item), mime_type)
                                # Logging for image_features

                            media_metadata = None
                            if mime_type and not mime_type.startswith("Error:") and mime_type in SUPPORTED_MEDIA_MIME_TYPES:
                                media_metadata = extract_media_metadata(str(item), mime_type)
                                # Logging for media_metadata

                            tags = generate_tags(mime_type, extracted_text, image_features, media_metadata)
                            self.log_queue.put(f"DEBUG: Generated tags for {item.name}: {tags}")
                            # --- End Semantic Analysis ---

                            # --- Rule Evaluation (iterate through rules for the current file) ---
                            for rule in rules_for_folder:
                                if self._stop_event.is_set():
                                    break

                                rule_name = rule.get('name', 'Unnamed Rule')
                                conditions = rule.get('conditions', [])
                                condition_logic = rule.get('condition_logic', 'AND')
                                action_to_perform = rule.get('action', 'move') # Action from the rule

                                # The actual check_file will be refactored in the next step.
                                # For now, we pass None for age/pattern from the old top-level structure
                                # and pass the new mime_type and tags.
                                # The crucial part is that check_file will need to use `conditions` and `condition_logic`.
                                # This is a placeholder for the upcoming check_file refactor.
                                # We'll assume check_file now takes these directly.

                                # Placeholder: old parameters that check_file will soon ignore or use differently
                                # These will be derived *inside* check_file from the `conditions` list
                                temp_age_days_from_rule = 0
                                temp_pattern_from_rule = ""
                                temp_use_regex_from_rule = False

                                # Extract age/pattern from conditions if present for logging/history (will be better handled by check_file)
                                for cond in conditions:
                                    if cond.get('field') == 'age_days':
                                        temp_age_days_from_rule = cond.get('value', 0)
                                    elif cond.get('field') == 'filename_pattern': # Assuming this is how pattern conditions are stored
                                        temp_pattern_from_rule = cond.get('value', '')
                                        # temp_use_regex_from_rule might be part of this condition or a separate one
                                        # For now, this is a simplification.

                                # TODO: Refactor check_file to accept `conditions` list and `condition_logic`
                                # and perform evaluation internally.
                                # For this subtask, we are just adapting worker.py structure.
                                # The current check_file will not work correctly with this new setup.
                                # This call is illustrative of the intent.
                                if check_file(
                                    file_path=item,
                                    conditions=conditions,
                                    condition_logic=condition_logic,
                                    mime_type=mime_type,
                                    tags=tags
                                ):

                                    self.log_queue.put(f"INFO: File {item.name} matched rule '{rule_name}' in folder {monitored_path}.")
                                    success, message = process_file_action(
                                        file_path=item,
                                        monitored_folder_path=monitored_path,
                                        archive_path_template=archive_template,
                                        action=action_to_perform, # Action from the current rule
                                        dry_run=is_dry_run,
                                        rule_matched=rule, # Pass the whole rule dictionary
                                        history_logger_callable=self.history_manager.log_action,
                                        run_id=current_run_id,
                                        tags=tags # Pass generated tags
                                    )
                                    self.log_queue.put(f"{'INFO' if success else 'ERROR'}: {message}")
                                    if success:
                                        files_processed_count_for_folder += 1
                                        break # File processed by a rule, move to next file
                            # --- End Rule Evaluation ---

                    except PermissionError:
                        self.log_queue.put(f"ERROR: Permission denied accessing folder: {monitored_path}")
                    except Exception as e:
                        self.log_queue.put(f"ERROR: Unexpected error scanning {monitored_path}: {e}")

                    if files_processed_count_for_folder > 0:
                        self.log_queue.put(f"INFO: Finished scan for {monitored_path}, processed {files_processed_count_for_folder} file(s).")

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
