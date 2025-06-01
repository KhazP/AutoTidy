
import os
import shutil
import fnmatch
import sys
import re # Import re module
import send2trash # Import send2trash
from datetime import datetime, timedelta
from pathlib import Path

# Placeholder for the parameters that were removed from check_file signature
# These are now passed via worker.py as illustrative placeholders based on the new call structure
# This check_file function is now the one from the plan.
def check_file(
    file_path: Path,
    conditions: list,
    condition_logic: str,
    mime_type: str | None,
    tags: list[str] | None,
    # The following are placeholders for the old signature, to be removed from worker.py call
    age_days_placeholder: int = 0,
    pattern_placeholder: str = "",
    use_regex_placeholder: bool = False
    ) -> bool:
    """
    Checks if a file meets a set of conditions based on the provided logic.

    Args:
        file_path: Path object of the file to check.
        conditions: A list of condition dictionaries.
        condition_logic: 'AND' or 'OR'.
        mime_type: The file's MIME type.
        tags: A list of tags associated with the file.
        age_days_placeholder, pattern_placeholder, use_regex_placeholder: Ignored. Present for call compatibility during refactor.


    Returns:
        True if the file matches the conditions based on the logic, False otherwise.
    """
    if not conditions: # No conditions, no match (or True if you prefer, but False seems safer)
        return False

    condition_results = []

    try:
        # Calculate file age once if needed by any condition
        file_age_days = -1 # Default if not calculated
        needs_age_calc = any(cond.get('field') == 'age_days' for cond in conditions)
        if needs_age_calc:
            mod_time = file_path.stat().st_mtime
            file_age_days = (datetime.now() - datetime.fromtimestamp(mod_time)).days
            # print(f"Debug: Calculated file age for {file_path.name}: {file_age_days} days")


        for cond in conditions:
            field = cond.get('field')
            operator = cond.get('operator')
            value = cond.get('value')
            current_condition_met = False

            # print(f"Debug: Evaluating condition: {cond} for file {file_path.name}")

            if field == 'age_days':
                if not isinstance(value, int):
                    print(f"Warning: Invalid value type for age_days condition: {value}. Skipping.", file=sys.stderr)
                    condition_results.append(False) # Treat malformed condition as non-match
                    continue
                if operator == 'greater_than':
                    current_condition_met = file_age_days > value
                elif operator == 'less_than':
                    current_condition_met = file_age_days < value
                elif operator == 'equals': # Though 'equals' for age might be rare
                    current_condition_met = file_age_days == value
                else:
                    print(f"Warning: Unknown operator '{operator}' for age_days. Skipping.", file=sys.stderr)

            elif field == 'filename_pattern':
                if not isinstance(value, str):
                    print(f"Warning: Invalid value type for filename_pattern: {value}. Skipping.", file=sys.stderr)
                    condition_results.append(False)
                    continue
                # Assuming 'operator' for filename_pattern could be 'matches_pattern' or 'not_matches_pattern'
                # And 'use_regex' could be an implicit part of the pattern string or a separate flag in condition
                # For now, let's assume 'matches_pattern' uses fnmatch and a new 'matches_regex' uses regex
                is_regex = cond.get('use_regex', False) # Allow condition to specify regex usage

                match_result = False
                if is_regex:
                    try:
                        if re.fullmatch(value, file_path.name):
                            match_result = True
                    except re.error as e:
                        print(f"Error: Invalid regex '{value}' in condition for {file_path.name}: {e}", file=sys.stderr)
                else: # fnmatch
                    if fnmatch.fnmatch(file_path.name, value):
                        match_result = True

                if operator == 'matches_pattern': # Generic for both regex/fnmatch
                    current_condition_met = match_result
                elif operator == 'not_matches_pattern':
                    current_condition_met = not match_result
                else:
                    print(f"Warning: Unknown operator '{operator}' for filename_pattern. Skipping.", file=sys.stderr)

            elif field == 'mime_type':
                if not isinstance(value, str):
                    print(f"Warning: Invalid value type for mime_type: {value}. Skipping.", file=sys.stderr)
                    condition_results.append(False)
                    continue
                # Ensure mime_type (from file) is not None for comparison
                file_actual_mime = mime_type if mime_type else ""
                if operator == 'equals':
                    current_condition_met = file_actual_mime == value
                elif operator == 'not_equals':
                    current_condition_met = file_actual_mime != value
                elif operator == 'starts_with':
                    current_condition_met = file_actual_mime.startswith(value)
                elif operator == 'ends_with':
                    current_condition_met = file_actual_mime.endswith(value)
                elif operator == 'contains':
                    current_condition_met = value in file_actual_mime
                else:
                    print(f"Warning: Unknown operator '{operator}' for mime_type. Skipping.", file=sys.stderr)

            elif field == 'tag':
                if not isinstance(value, str):
                    print(f"Warning: Invalid value type for tag condition: {value}. Skipping.", file=sys.stderr)
                    condition_results.append(False)
                    continue
                file_tags = tags if tags else []
                if operator == 'contains':
                    current_condition_met = value in file_tags
                elif operator == 'not_contains':
                    current_condition_met = value not in file_tags
                else:
                    print(f"Warning: Unknown operator '{operator}' for tag. Skipping.", file=sys.stderr)

            else:
                print(f"Warning: Unknown condition field '{field}'. Skipping condition.", file=sys.stderr)
                # For AND logic, an unknown field means the condition set might not fully evaluate
                # For OR logic, it just means this specific condition won't contribute
                # We'll add False, which is safer.
                current_condition_met = False

            condition_results.append(current_condition_met)
            # print(f"Debug: Condition {cond} result: {current_condition_met}")

        # Combine results based on logic
        if not condition_results: # Should have been caught by initial check, but as a safeguard
            return False

        if condition_logic.upper() == 'AND':
            # print(f"Debug: AND logic, all results: {condition_results}, final: {all(condition_results)}")
            return all(condition_results)
        elif condition_logic.upper() == 'OR':
            # print(f"Debug: OR logic,  all results: {condition_results}, final: {any(condition_results)}")
            return any(condition_results)
        else:
            print(f"Warning: Unknown condition_logic '{condition_logic}'. Defaulting to AND.", file=sys.stderr)
            return all(condition_results)

    except FileNotFoundError:
        print(f"Warning: File not found during check_file: {file_path}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error in check_file for {file_path.name}: {e}", file=sys.stderr)
        return False

def process_file_action(
    file_path: Path,
    monitored_folder_path: Path,
    archive_path_template: str,
    action: str, # This is the action determined by the matched rule
    dry_run: bool,
    rule_matched: dict, # Contains details of the rule that matched
    history_logger_callable,
    run_id: str,
    tags: list[str] | None # New parameter for {TAGS} placeholder
) -> tuple[bool, str]:
    """
    Processes a file by moving, copying, or deleting it based on the provided template and action,
    supporting dry run and logging the action to history. Can use {TAGS} in archive_path_template.

    Args:
        file_path: Path object of the file to process.
        monitored_folder_path: Path object of the folder being monitored (used for move/copy).
        archive_path_template: String template for the archive path (used for move/copy).
        action: The action to perform ("move", "copy", "delete_to_trash", "delete_permanently") from the rule.
        dry_run: If True, simulate actions instead of performing them.
        rule_matched: Dictionary of the rule that was matched. Used for logging.
        history_logger_callable: Callable (e.g., HistoryManager.log_action) to log the action.
        run_id: Identifier for the current processing batch.
        tags: Optional list of tags for the file, used for {TAGS} placeholder.

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

            current_template = archive_path_template

            # Handle {TAGS} placeholder
            if "{TAGS}" in current_template:
                if tags and len(tags) > 0:
                    # Sanitize tags: join with underscore, keep alphanumeric and underscore/hyphen
                    # Remove individual tag prefixes like "text_", "mime_" for cleanliness in path
                    cleaned_tags = [tag.split('_', 1)[-1] if '_' in tag else tag for tag in tags]
                    tag_string = "_".join(sorted(list(set(cleaned_tags)))) # Sort for consistent ordering
                    # Further sanitize the combined string for filesystem safety
                    # Replace non-alphanumeric (excluding underscore/hyphen) with underscore
                    safe_tag_string = re.sub(r'[^\w\-]', '_', tag_string)
                    current_template = current_template.replace("{TAGS}", safe_tag_string)
                else:
                    current_template = current_template.replace("{TAGS}", "untagged") # Default if no tags

            resolved_template = current_template.replace("{YYYY}", year)
            resolved_template = resolved_template.replace("{MM}", month)
            resolved_template = resolved_template.replace("{DD}", day)
            resolved_template = resolved_template.replace("{FILENAME}", filename_stem)
            resolved_template = resolved_template.replace("{EXT}", file_ext)
            resolved_template = resolved_template.replace("{ORIGINAL_FOLDER_NAME}", original_folder_name)

            # Ensure resolved_template does not inadvertently create paths outside monitored_folder_path if it's absolute
            # For now, we assume it's a relative path structure from monitored_folder_path
            target_base_dir = monitored_folder_path / resolved_template.lstrip('/') # lstrip to handle if template starts with /
            target_file_path = target_base_dir / filename_full # Initial proposed path

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
                            "rule_matched_name": rule_matched.get('name', 'Unnamed Rule'),
                            "rule_action_config": action, "status": "FAILURE", "details": message, "run_id": run_id
                        }
                        history_logger_callable(log_data_collision)
                        return False, message
                target_file_path = temp_target_file_path # Update target_file_path with non-colliding name for actual ops
            elif dry_run and target_file_path.exists(): # For dry run, if initial path exists, simulate one step of collision avoidance
                target_file_path = target_base_dir / f"{filename_stem}_1{file_ext}"


            relative_target_path = target_base_dir.relative_to(monitored_folder_path) / target_file_path.name

            if dry_run:
                action_taken_str = ("SIMULATED_" + action).upper()
                log_action_verb_msg = "Would copy" if action == "copy" else "Would move"
                message = f"[DRY RUN] {log_action_verb_msg}: '{filename_full}' to '{relative_target_path}' based on rule '{rule_matched.get('name', 'Unnamed Rule')}'"
                log_data = {
                    "original_path": str(file_path), "action_taken": action_taken_str,
                    "destination_path": str(target_file_path), "monitored_folder": str(monitored_folder_path),
                    "rule_matched_name": rule_matched.get('name', 'Unnamed Rule'),
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

            message = f"{actual_log_action_verb_str.capitalize()}: {filename_full} -> {relative_target_path} based on rule '{rule_matched.get('name', 'Unnamed Rule')}'"
            log_data = {
                "original_path": str(file_path), "action_taken": actual_log_action_verb_str,
                "destination_path": str(target_file_path), "monitored_folder": str(monitored_folder_path),
                "rule_matched_name": rule_matched.get('name', 'Unnamed Rule'),
                "rule_action_config": action, "status": "SUCCESS", "details": message, "run_id": run_id
            }
            history_logger_callable(log_data)
            return True, message

        elif action == "delete_to_trash":
            action_taken_str = "SIMULATED_DELETE_TO_TRASH" if dry_run else "DELETED_TO_TRASH"
            details_message = f"[DRY RUN] Would send to trash: '{filename_full}' based on rule '{rule_matched.get('name', 'Unnamed Rule')}'" if dry_run else f"Success: Sent to trash: '{filename_full}' based on rule '{rule_matched.get('name', 'Unnamed Rule')}'"

            if not dry_run:
                send2trash.send2trash(str(file_path))

            log_data = {"original_path": str(file_path), "action_taken": action_taken_str, "destination_path": None,
                        "monitored_folder": str(monitored_folder_path),
                        "rule_matched_name": rule_matched.get('name', 'Unnamed Rule'),
                        "rule_action_config": action, "status": "SUCCESS", "details": details_message, "run_id": run_id}
            history_logger_callable(log_data)
            return True, details_message

        elif action == "delete_permanently":
            action_taken_str = "SIMULATED_DELETE_PERMANENTLY" if dry_run else "DELETED_PERMANENTLY"
            details_message = f"[DRY RUN] Would permanently delete: '{filename_full}' (irreversible) based on rule '{rule_matched.get('name', 'Unnamed Rule')}'" if dry_run else f"Success: Permanently deleted: '{filename_full}' (irreversible) based on rule '{rule_matched.get('name', 'Unnamed Rule')}'"

            if not dry_run:
                os.remove(str(file_path))

            log_data = {"original_path": str(file_path), "action_taken": action_taken_str, "destination_path": None,
                        "monitored_folder": str(monitored_folder_path),
                        "rule_matched_name": rule_matched.get('name', 'Unnamed Rule'),
                        "rule_action_config": action, "status": "SUCCESS", "details": details_message, "run_id": run_id}
            history_logger_callable(log_data)
            return True, details_message

        else: # Unknown action
            message = f"Error: Unknown action '{action}' for file '{filename_full}' from rule '{rule_matched.get('name', 'Unnamed Rule')}'"
            log_data = {"original_path": str(file_path), "action_taken": "UNKNOWN_ACTION", "destination_path": None,
                        "monitored_folder": str(monitored_folder_path),
                        "rule_matched_name": rule_matched.get('name', 'Unnamed Rule'),
                        "rule_action_config": action, "status": "FAILURE", "details": message, "run_id": run_id}
            history_logger_callable(log_data)
            return False, message

    except FileNotFoundError:
        message = f"Error: Source file not found for {action}: '{file_path.name}' (Rule: '{rule_matched.get('name', 'Unnamed Rule')}')"
        action_taken_log = (("SIMULATED_" if dry_run else "") + action + "_ERROR_NOT_FOUND").upper()
        log_data = {"original_path": str(file_path), "action_taken": action_taken_log, "destination_path": None,
                    "monitored_folder": str(monitored_folder_path),
                    "rule_matched_name": rule_matched.get('name', 'Unnamed Rule'),
                    "rule_action_config": action, "status": "FAILURE", "details": message, "run_id": run_id}
        history_logger_callable(log_data)
        return False, message
    except PermissionError:
        message = f"Error: Permission denied for {action} on file '{file_path.name}' (Rule: '{rule_matched.get('name', 'Unnamed Rule')}')"
        action_taken_log = (("SIMULATED_" if dry_run else "") + action + "_ERROR_PERMISSION").upper()
        log_data = {"original_path": str(file_path), "action_taken": action_taken_log, "destination_path": None,
                    "monitored_folder": str(monitored_folder_path),
                    "rule_matched_name": rule_matched.get('name', 'Unnamed Rule'),
                    "rule_action_config": action, "status": "FAILURE", "details": message, "run_id": run_id}
        history_logger_callable(log_data)
        return False, message
    except Exception as e:
        message = f"Error performing {action} on '{file_path.name}' (Rule: '{rule_matched.get('name', 'Unnamed Rule')}'): {e}"
        action_taken_log = (("SIMULATED_" if dry_run else "") + action + "_ERROR_GENERAL").upper()
        log_data = {"original_path": str(file_path), "action_taken": action_taken_log, "destination_path": None,
                    "monitored_folder": str(monitored_folder_path),
                    "rule_matched_name": rule_matched.get('name', 'Unnamed Rule'),
                    "rule_action_config": action, "status": "FAILURE", "details": message, "run_id": run_id}
        history_logger_callable(log_data)
        return False, message
