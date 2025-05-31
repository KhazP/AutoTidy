import os
import time
import shutil
import fnmatch
import re # For regex matching
from datetime import datetime, timedelta
from pathlib import Path
# Assuming watchdog is used or intended, based on FileSystemEventHandler
# If not, these imports might not be strictly necessary for the current periodic scan model
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Import semantic engine functions
from semantic_engine import (
    get_file_type,
    extract_text_from_file,
    analyze_image,
    get_media_metadata,
    generate_tags_from_text
)
# Assuming utils.py and constants.py are present and define these
# These will cause an error if not found, but the subtask is to modify worker.py
# For the purpose of this subtask, we'll assume they exist and are correct.
try:
    from utils import move_file_with_history, delete_file_with_history_to_trash, delete_file_permanently_with_history
    from constants import VALID_ACTIONS
except ImportError:
    print("WARNING: 'utils' or 'constants' module not found. Worker actions will be limited.")
    # Define fallbacks so the rest of the file can be parsed and the semantic integration tested
    VALID_ACTIONS = ["move", "copy", "delete_to_trash", "delete_permanently"]
    # Dummy functions for actions if utils not found
    def move_file_with_history(entry_path, folder_config, archive_template_str, undo_manager, log_queue, monitored_folder_path):
        log_queue.put(f"DUMMY_ACTION: Would move {entry_path} using template {archive_template_str}")
    def delete_file_with_history_to_trash(entry_path, undo_manager, log_queue):
        log_queue.put(f"DUMMY_ACTION: Would delete to trash {entry_path}")
    def delete_file_permanently_with_history(entry_path, undo_manager, log_queue):
        log_queue.put(f"DUMMY_ACTION: Would delete permanently {entry_path}")


class MonitoringWorker(FileSystemEventHandler): # Base class for watchdog, kept for structure
    def __init__(self, config_manager, log_queue, undo_manager):
        super().__init__()
        self.config_manager = config_manager
        self.log_queue = log_queue
        self.undo_manager = undo_manager
        self.running = False
        self.observer = None # For potential future watchdog use
        self.processed_files_cache = set() # Cache to avoid reprocessing

    def start(self):
        self.running = True
        self.log_queue.put("INFO: Worker thread started.")
        self.log_queue.put("STATUS: Running")

        # Initial scan before starting the loop
        self.scan_all_folders()

        while self.running:
            scan_interval_minutes = 5 # Default
            try:
                # Attempt to get scan_interval from config_manager, with a fallback
                scan_interval_minutes = self.config_manager.get_setting('scan_interval_minutes', 5)
            except Exception as e:
                self.log_queue.put(f"WARNING: Could not retrieve scan_interval_minutes from config. Using default {scan_interval_minutes} min. Error: {e}")

            scan_interval_seconds = scan_interval_minutes * 60

            # Sleep in smaller chunks to respond to stop signal faster
            for _ in range(int(scan_interval_seconds / 5)): # Check every 5 seconds
                if not self.running:
                    break
                time.sleep(5)

            if self.running:
                self.scan_all_folders()

        # Log when the loop has actually exited
        self.log_queue.put("INFO: Worker thread run loop exited.")


    def stop(self):
        self.running = False
        # if self.observer: # If watchdog observer was used
        #     self.observer.stop()
        #     self.observer.join()
        self.log_queue.put("INFO: Worker thread stopping signal received.") # Changed from stopped to stopping
        self.processed_files_cache.clear()
        # Status update to "Stopped" will be done once the run loop actually exits.

    def scan_all_folders(self):
        if not self.running:
            return
        self.log_queue.put("INFO: Starting scheduled scan of monitored folders...")
        config = self.config_manager.get_config()
        is_dry_run = self.config_manager.get_setting('dry_run_mode', False)

        for folder_path_str, folder_config in config.get("folders", {}).items():
            if not self.running:
                break

            folder_path = Path(folder_path_str) # Work with Path objects
            self.log_queue.put(f"INFO: Scanning folder: {folder_path}")
            self.process_folder(folder_path, folder_config, is_dry_run)

        if self.running: # Only log if not stopped during scan
            self.log_queue.put("INFO: Scheduled scan finished.")

    def process_folder(self, folder_path: Path, folder_config: dict, is_dry_run: bool):
        try:
            if not folder_path.exists() or not folder_path.is_dir():
                self.log_queue.put(f"ERROR: Folder not found or is not a directory: {folder_path}")
                return

            archive_folder_name_template = self.config_manager.get_setting("archive_path_template", "_Cleanup/{YYYY}-{MM}-{DD}")
            # Extract the first part of the template as the base archive folder name
            # This assumes the template starts with the archive folder, e.g., "_Cleanup/..."
            archive_folder_name = Path(archive_folder_name_template.split('/')[0].split('\\')[0])


            for entry in os.scandir(folder_path):
                if not self.running:
                    return

                entry_path = Path(entry.path)

                if entry.name == archive_folder_name.name or entry.name.startswith('.') or entry.name == "__pycache__":
                    continue

                if entry.is_file():
                    # Check cache *before* any I/O or intensive processing
                    # Construct a unique identifier for the file including its modification time
                    try:
                        file_id = (entry_path, entry.stat().st_mtime)
                    except FileNotFoundError: # File might have been moved/deleted since scandir
                        self.log_queue.put(f"DEBUG: File {entry_path.name} not found for stat, skipping.")
                        continue

                    if file_id in self.processed_files_cache:
                        # self.log_queue.put(f"DEBUG: Skipping recently processed or unchanged file: {entry_path.name}")
                        continue

                    self.log_queue.put(f"INFO: Analyzing file: {entry_path}")

                    # Semantic Analysis
                    file_type = get_file_type(str(entry_path))
                    self.log_queue.put(f"INFO: [{entry_path.name}] File Type: {file_type}")

                    text_content = None
                    if file_type and (file_type.startswith('text/') or \
                                   any(ft in file_type for ft in ['pdf', 'word', 'opendocument.text', 'epub'])): # Added epub
                        text_content = extract_text_from_file(str(entry_path))
                        if text_content:
                            self.log_queue.put(f"INFO: [{entry_path.name}] Extracted Text (first 100 chars): {text_content[:100].replace(os.linesep, ' ')}...")
                            tags = generate_tags_from_text(text_content)
                            self.log_queue.put(f"INFO: [{entry_path.name}] Generated Tags: {tags}")
                        # else: # Only log if text was extracted (reduces verbosity)
                            # self.log_queue.put(f"INFO: [{entry_path.name}] No text extracted or text is empty.")

                    if file_type and file_type.startswith('image/'):
                        image_features = analyze_image(str(entry_path))
                        if image_features:
                            self.log_queue.put(f"INFO: [{entry_path.name}] Image Features: {image_features}")

                    if file_type and (file_type.startswith('audio/') or file_type.startswith('video/')):
                        media_metadata = get_media_metadata(str(entry_path))
                        if media_metadata:
                            log_media_info = {
                                'format': media_metadata.get('format', {}).get('format_long_name', 'N/A'),
                                'duration': media_metadata.get('format', {}).get('duration', 'N/A'),
                                'streams': len(media_metadata.get('streams', []))
                            }
                            self.log_queue.put(f"INFO: [{entry_path.name}] Media Metadata: {log_media_info}")

                    # --- Existing Rule Processing Logic ---
                    min_age_days = folder_config.get("min_age_days", 0)
                    filename_pattern = folder_config.get("filename_pattern", "*")
                    pattern_type = folder_config.get("pattern_type", "wildcard") # Default to wildcard
                    action = folder_config.get("action", "move") # Default to move

                    if action not in VALID_ACTIONS:
                        self.log_queue.put(f"ERROR: Invalid action '{action}' for {folder_path}. Skipping rule.")
                        continue

                    file_mod_time = datetime.fromtimestamp(entry_path.stat().st_mtime) # Re-stat for current mod time
                    age_matches = (datetime.now() - file_mod_time) > timedelta(days=min_age_days) if min_age_days > 0 else False # Corrected logic for else

                    name_matches = False
                    if filename_pattern and filename_pattern != "*": # Only match if pattern is not "*"
                        if pattern_type == "regex":
                            try:
                                name_matches = bool(re.match(filename_pattern, entry.name))
                            except re.error as e:
                                self.log_queue.put(f"ERROR: Invalid regex pattern '{filename_pattern}' for {folder_path}: {e}")
                                continue
                        else: # Wildcard
                            name_matches = fnmatch.fnmatch(entry.name, filename_pattern)
                    elif filename_pattern == "*": # If pattern is "*", it's a match by name (for any name)
                        name_matches = True


                    # Rule triggers if *either* age or name matches, *unless* both are specified,
                    # in which case *both* must match. This needs clarification or a config option.
                    # Current logic: process if (age_matches OR name_matches)
                    # More typical: process if (age_matches AND name_matches) if both specified,
                    # or if only one is specified, that one.
                    # For now, using simple OR, assuming a file matching *any* criterion of a rule is processed.
                    # A common interpretation: if a rule has age, it must match. If it has pattern, it must match.
                    # If it has both, both must match. If it has neither, it matches all files (dangerous).

                    # Let's refine rule matching:
                    # A file must meet all specified criteria for a rule to apply.
                    # If a criterion is not specified (e.g. min_age_days = 0 or filename_pattern = "*"), it's considered met.

                    rule_applies = True
                    if min_age_days > 0 and not age_matches:
                        rule_applies = False
                    if filename_pattern != "*" and not name_matches: # If a specific pattern is given and it doesn't match
                        rule_applies = False

                    # If min_age_days is 0 AND filename_pattern is "*", the rule applies to all files.
                    # This is usually intended if an action should apply to all files in the folder unconditionally.

                    if rule_applies:
                        self.log_queue.put(f"INFO: File '{entry.name}' in '{folder_path}' matches rule criteria. Action: {action}.")

                        if is_dry_run:
                            self.log_queue.put(f"DRY RUN: Would perform '{action}' on '{entry_path}'")
                        else:
                            try:
                                archive_template_str = self.config_manager.get_setting("archive_path_template", "_Cleanup/{YYYY}-{MM}-{DD}")

                                if action == "move":
                                    move_file_with_history(entry_path, folder_config, archive_template_str, self.undo_manager, self.log_queue, monitored_folder_path=str(folder_path))
                                elif action == "copy":
                                    self.log_queue.put(f"ACTION: Copying {entry_path} (Copy logic with history not fully implemented in this step)")
                                    # Add actual copy logic here if developed: e.g. copy_file_with_history(...)
                                elif action == "delete_to_trash":
                                    delete_file_with_history_to_trash(entry_path, self.undo_manager, self.log_queue)
                                elif action == "delete_permanently":
                                    delete_file_permanently_with_history(entry_path, self.undo_manager, self.log_queue)

                                # Add to cache only after successful action or if no action was needed but file was processed
                                self.processed_files_cache.add(file_id)
                                if len(self.processed_files_cache) > 2000:
                                    # Simple FIFO-like removal for set (pop removes an arbitrary element)
                                    self.processed_files_cache.pop()
                            except Exception as e:
                                self.log_queue.put(f"ERROR: Failed to perform '{action}' on '{entry_path}': {e}")
                    # else: # If rule doesn't apply, still mark as "processed" for this scan cycle to avoid re-analyzing if no action taken
                    #    self.processed_files_cache.add(file_id)
                    #    if len(self.processed_files_cache) > 2000: self.processed_files_cache.pop()
                    # Re-think: only cache if action was taken or if no rule applied. If rule *didn't* apply, it might apply next time (e.g. age)
                    # For now, only caching if action was taken or dry-run indicated it would be.
                    # Semantic analysis itself is light enough that re-doing it if no rule matches is okay.
                    # If a rule *does* match (even dry-run), then we cache.

        except FileNotFoundError:
            self.log_queue.put(f"ERROR: Folder not found during scan: {folder_path}.")
        except PermissionError:
            self.log_queue.put(f"ERROR: Permission denied for folder: {folder_path}.")
        except Exception as e:
            self.log_queue.put(f"ERROR: Unexpected error processing folder {folder_path}: {e}")


if __name__ == '__main__':
    # This block is for illustrative purposes and won't run in the actual application
    # It requires mock objects for ConfigManager, LogQueue, UndoManager
    print("worker.py should not be run directly for testing in this manner.")
    print("Integration testing happens via the main application execution.")
