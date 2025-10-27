
import os
import shutil
import fnmatch
import sys
import re # Import re module
import send2trash # Import send2trash
from datetime import datetime, timedelta
from pathlib import Path

def check_file(
    file_path: Path,
    age_days: int,
    pattern: str,
    use_regex: bool,
    rule_logic: str = "OR",
) -> bool:
    """
    Checks if a file meets the criteria using the configured logic.

    Args:
        file_path: Path object of the file to check.
        age_days: Minimum age in days for the file to match.
        pattern: Filename pattern (fnmatch style or regex) to match.
        use_regex: Boolean indicating whether the pattern is a regular expression.

    Returns:
        True if the file matches the configured logic, False otherwise.
    """
    try:
        # 1. Check Age
        age_match = False
        if age_days > 0:
            mod_time = file_path.stat().st_mtime
            age_threshold = datetime.now() - timedelta(days=age_days)
            if datetime.fromtimestamp(mod_time) < age_threshold:
                age_match = True # Matches age criteria

        # 2. Check Pattern
        pattern_match = False
        if pattern:
            if use_regex:
                try:
                    if re.fullmatch(pattern, file_path.name):
                        pattern_match = True # Matches regex pattern criteria
                except re.error as e:
                    print(f"Error: Invalid regex pattern '{pattern}' for file {file_path.name}: {e}", file=sys.stderr)
                    # Treat as non-match if regex is invalid
            else:
                if fnmatch.fnmatch(file_path.name, pattern):
                    pattern_match = True # Matches fnmatch pattern criteria

        logic = (rule_logic or "OR").upper()
        if logic == "AND":
            return age_match and pattern_match
        return age_match or pattern_match

    except FileNotFoundError:
        # File might have been deleted between listing and checking
        print(f"Warning: File not found during check: {file_path}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error checking file {file_path}: {e}", file=sys.stderr)
        return False

    return False # Does not match any criteria

def process_file_action(
    file_path: Path,
    monitored_folder_path: Path,
    archive_path_template: str,
    action: str,
    dry_run: bool,
    rule_pattern: str, # New parameter for history logging
    rule_age_days: int,  # New parameter for history logging
    rule_use_regex: bool, # New parameter for history logging
    history_logger_callable, # New parameter for history logging
    run_id: str, # New parameter for batch operation run_id
    destination_folder: str | None = None,
) -> tuple[bool, str]:
    """
    Processes a file by moving, copying, or deleting it based on the provided template and action,
    supporting dry run and logging the action to history.

    Args:
        file_path: Path object of the file to process.
        monitored_folder_path: Path object of the folder being monitored (used for move/copy).
        archive_path_template: String template for the archive path (used for move/copy).
        action: The action to perform ("move", "copy", "delete_to_trash", "delete_permanently").
        dry_run: If True, simulate actions instead of performing them.
        rule_pattern: Pattern from the rule that matched this file.
        rule_age_days: Age from the rule that matched this file.
        rule_use_regex: Boolean, if regex was used for the pattern.
        history_logger_callable: Callable (e.g., HistoryManager.log_action) to log the action.
        destination_folder: Optional destination override for move/copy actions. Supports
            environment variables, user home expansion, and relative paths resolved against
            the monitored folder when not absolute.

    Returns:
        A tuple (success: bool, message: str).
    """
    try:
        filename_full = file_path.name # Used for logging in all cases

        if action == "copy" or action == "move":
            now = datetime.now()
            year = now.strftime("%Y")
            month = now.strftime("%m")
            day = now.strftime("%d")

            filename_stem = file_path.stem
            file_ext = file_path.suffix
            original_folder_name = monitored_folder_path.name

            replacements = {
                "{YYYY}": year,
                "{MM}": month,
                "{DD}": day,
                "{FILENAME}": filename_stem,
                "{EXT}": file_ext,
                "{ORIGINAL_FOLDER_NAME}": original_folder_name,
            }

            def apply_template(template: str) -> str:
                result = template
                for placeholder, value in replacements.items():
                    result = result.replace(placeholder, value)
                return result

            destination_value = (destination_folder or "").strip()
            template_in_use = destination_value if destination_value else archive_path_template
            resolved_template = apply_template(template_in_use)
            expanded_template = os.path.expandvars(resolved_template)
            expanded_template = os.path.expanduser(expanded_template)
            includes_filename_tokens = any(token in template_in_use for token in ("{FILENAME}", "{EXT}"))

            target_path_candidate = Path(expanded_template)
            if not target_path_candidate.is_absolute():
                target_path_candidate = (monitored_folder_path / target_path_candidate).resolve()
            else:
                # Normalize absolute paths as well
                target_path_candidate = target_path_candidate.resolve()

            if includes_filename_tokens:
                target_file_path = target_path_candidate
                target_base_dir = target_file_path.parent
            else:
                target_base_dir = target_path_candidate
                target_file_path = target_base_dir / filename_full

            # Simulate filename collision handling for dry run as well
            counter = 1
            # For dry run, we only check if the initial path would exist if we *were* to create it.
            # A true dry run of collision would require knowing other files that *would* be moved in the same batch.
            # This simplified collision simulation for dry run shows the first available name.
            # For non-dry run, this loop is critical.
            # We need to ensure this loop only queries the filesystem if it's NOT a dry run,
            # or be very careful about its meaning in a dry run.
            # Let's refine: the collision loop should only run (checking `exists()`) if not dry_run.
            # For dry_run, we calculate the initial path and that's what we report.
            # However, to be more informative about what *would* happen, we can keep the collision logic
            # but ensure it doesn't create side effects (like creating the dir to check inside it).

            # Path for logging message (calculated before potential collision adjustments for dry run)
            # If we want to show the collided name in dry run, this needs to be inside the loop or after.
            # Let's calculate the final intended path for both dry and non-dry runs.

            temp_target_file_path = target_file_path
            if not dry_run: # Only check actual existence if not a dry run
                while temp_target_file_path.exists():
                    temp_target_file_path = target_base_dir / f"{filename_stem}_{counter}{file_ext}"
                    counter += 1
                    if counter > 100: # Safety break
                        message = f"Error: Too many filename collisions for {filename_full} in {target_base_dir}"
                        log_data_collision = {
                            "original_path": str(file_path), "action_taken": action.upper() + "_ERROR_COLLISION",
                            "destination_path": str(target_base_dir / filename_full), "monitored_folder": str(monitored_folder_path),
                            "rule_pattern": rule_pattern, "rule_age_days": rule_age_days, "rule_use_regex": rule_use_regex,
                            "rule_action_config": action, "status": "FAILURE", "details": message, "run_id": run_id
                        }
                        history_logger_callable(log_data_collision)
                        return False, message
                target_file_path = temp_target_file_path # Update target_file_path with non-colliding name for actual ops
            elif dry_run and target_file_path.exists(): # For dry run, if initial path exists, simulate one step of collision avoidance
                target_file_path = target_base_dir / f"{filename_stem}_1{file_ext}"

            try:
                relative_target_path = target_file_path.relative_to(monitored_folder_path)
            except ValueError:
                relative_target_path = target_file_path

            if dry_run:
                action_taken_str = ("SIMULATED_" + action).upper()
                log_action_verb_msg = "Would copy" if action == "copy" else "Would move"
                message = f"[DRY RUN] {log_action_verb_msg}: '{filename_full}' to '{relative_target_path}'"
                log_data = {
                    "original_path": str(file_path), "action_taken": action_taken_str,
                    "destination_path": str(target_file_path), "monitored_folder": str(monitored_folder_path),
                    "rule_pattern": rule_pattern, "rule_age_days": rule_age_days, "rule_use_regex": rule_use_regex,
                    "rule_action_config": action, "status": "SUCCESS", "details": message, "run_id": run_id
                }
                history_logger_callable(log_data)
                return True, message

            # Actual operations (not a dry run)
            target_base_dir.mkdir(parents=True, exist_ok=True)

            actual_log_action_verb_str = ""
            if action == "copy":
                shutil.copy2(str(file_path), str(target_file_path))
                actual_log_action_verb_str = "COPIED"
            else: # move
                shutil.move(str(file_path), str(target_file_path))
                actual_log_action_verb_str = "MOVED"

            message = f"{actual_log_action_verb_str.capitalize()}: {filename_full} -> {relative_target_path}"
            log_data = {
                "original_path": str(file_path), "action_taken": actual_log_action_verb_str,
                "destination_path": str(target_file_path), "monitored_folder": str(monitored_folder_path),
                "rule_pattern": rule_pattern, "rule_age_days": rule_age_days, "rule_use_regex": rule_use_regex,
                "rule_action_config": action, "status": "SUCCESS", "details": message, "run_id": run_id
            }
            history_logger_callable(log_data)
            return True, message

        elif action == "delete_to_trash":
            action_taken_str = "SIMULATED_DELETE_TO_TRASH" if dry_run else "DELETED_TO_TRASH"
            details_message = f"[DRY RUN] Would send to trash: '{filename_full}'" if dry_run else f"Success: Sent to trash: '{filename_full}'"

            if not dry_run:
                send2trash.send2trash(str(file_path))

            log_data = {"original_path": str(file_path), "action_taken": action_taken_str, "destination_path": None,
                        "monitored_folder": str(monitored_folder_path), "rule_pattern": rule_pattern,
                        "rule_age_days": rule_age_days, "rule_use_regex": rule_use_regex,
                        "rule_action_config": action, "status": "SUCCESS", "details": details_message, "run_id": run_id}
            history_logger_callable(log_data)
            return True, details_message

        elif action == "delete_permanently":
            action_taken_str = "SIMULATED_DELETE_PERMANENTLY" if dry_run else "DELETED_PERMANENTLY"
            details_message = f"[DRY RUN] Would permanently delete: '{filename_full}' (irreversible)" if dry_run else f"Success: Permanently deleted: '{filename_full}' (irreversible)"

            if not dry_run:
                os.remove(str(file_path))

            log_data = {"original_path": str(file_path), "action_taken": action_taken_str, "destination_path": None,
                        "monitored_folder": str(monitored_folder_path), "rule_pattern": rule_pattern,
                        "rule_age_days": rule_age_days, "rule_use_regex": rule_use_regex,
                        "rule_action_config": action, "status": "SUCCESS", "details": details_message, "run_id": run_id}
            history_logger_callable(log_data)
            return True, details_message

        else: # Unknown action
            message = f"Error: Unknown action '{action}' for file '{filename_full}'"
            log_data = {"original_path": str(file_path), "action_taken": "UNKNOWN_ACTION", "destination_path": None,
                        "monitored_folder": str(monitored_folder_path), "rule_pattern": rule_pattern,
                        "rule_age_days": rule_age_days, "rule_use_regex": rule_use_regex,
                        "rule_action_config": action, "status": "FAILURE", "details": message, "run_id": run_id}
            history_logger_callable(log_data)
            return False, message

    except FileNotFoundError:
        message = f"Error: Source file not found for {action}: '{file_path.name}'"
        action_taken_log = (("SIMULATED_" if dry_run else "") + action + "_ERROR_NOT_FOUND").upper()
        log_data = {"original_path": str(file_path), "action_taken": action_taken_log, "destination_path": None,
                    "monitored_folder": str(monitored_folder_path), "rule_pattern": rule_pattern,
                    "rule_age_days": rule_age_days, "rule_use_regex": rule_use_regex,
                    "rule_action_config": action, "status": "FAILURE", "details": message, "run_id": run_id}
        history_logger_callable(log_data)
        return False, message
    except PermissionError:
        message = f"Error: Permission denied for {action} on file '{file_path.name}'"
        action_taken_log = (("SIMULATED_" if dry_run else "") + action + "_ERROR_PERMISSION").upper()
        log_data = {"original_path": str(file_path), "action_taken": action_taken_log, "destination_path": None,
                    "monitored_folder": str(monitored_folder_path), "rule_pattern": rule_pattern,
                    "rule_age_days": rule_age_days, "rule_use_regex": rule_use_regex,
                    "rule_action_config": action, "status": "FAILURE", "details": message, "run_id": run_id}
        history_logger_callable(log_data)
        return False, message
    except Exception as e:
        message = f"Error performing {action} on '{file_path.name}': {e}"
        action_taken_log = (("SIMULATED_" if dry_run else "") + action + "_ERROR_GENERAL").upper()
        log_data = {"original_path": str(file_path), "action_taken": action_taken_log, "destination_path": None,
                    "monitored_folder": str(monitored_folder_path), "rule_pattern": rule_pattern,
                    "rule_age_days": rule_age_days, "rule_use_regex": rule_use_regex,
                    "rule_action_config": action, "status": "FAILURE", "details": message, "run_id": run_id}
        history_logger_callable(log_data)
        return False, message
