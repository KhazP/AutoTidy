import os
import shutil
import fnmatch
import sys
import re
import send2trash
from datetime import datetime, timedelta
from pathlib import Path

def check_file(
    file_path: Path,
    conditions: list,
    condition_logic: str,
    mime_type: str | None,
    tags: list[str] | None
) -> bool:
    """
    Checks if a file meets a set of conditions based on the provided logic.
    """
    # print(f"\n--- DBG_CHECK_FILE --- Path: {file_path.name}, Logic: {condition_logic}, Conditions: {conditions}, Mime: {mime_type}, Tags: {tags}") # DEBUG

    if not conditions:
        # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, No conditions, returning False") # DEBUG
        return False

    condition_results = []

    try:
        file_age_days = -1
        needs_age_calc = any(cond.get('field') == 'age_days' for cond in conditions)
        if needs_age_calc:
            mod_time = file_path.stat().st_mtime
            file_age_days = (datetime.now() - datetime.fromtimestamp(mod_time)).days
            # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, Calculated file_age_days: {file_age_days}") # DEBUG

        for i, cond in enumerate(conditions):
            field = cond.get('field')
            operator = cond.get('operator')
            value = cond.get('value')
            # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, Evaluating Cond[{i}]: Fld='{field}', Op='{operator}', Val='{value}'") # DEBUG

            current_condition_eval_success = False
            current_condition_met = False

            if field == 'age_days':
                if not isinstance(value, (int, float)):
                    # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, Cond[{i}]: Invalid value type for age_days. Skipping.", file=sys.stderr) # DEBUG
                    continue
                if file_age_days == -1 and needs_age_calc :
                     # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, Cond[{i}]: File age not calculated. Skipping age condition.", file=sys.stderr) # DEBUG
                     continue
                current_condition_eval_success = True
                if operator == 'greater_than': current_condition_met = file_age_days > value
                elif operator == 'less_than': current_condition_met = file_age_days < value
                elif operator == 'equals': current_condition_met = file_age_days == value
                else:
                    # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, Cond[{i}]: Unknown operator for age_days. Skipping.", file=sys.stderr) # DEBUG
                    current_condition_eval_success = False

            elif field == 'filename_pattern':
                if not isinstance(value, str):
                    # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, Cond[{i}]: Invalid value for filename_pattern. Skipping.", file=sys.stderr) # DEBUG
                    continue
                is_regex = cond.get('use_regex', False)
                current_condition_eval_success = True
                match_result = False
                if is_regex:
                    try:
                        if re.fullmatch(value, file_path.name): match_result = True
                    except re.error as e:
                        # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, Cond[{i}]: Invalid regex '{value}': {e}. Skipping.", file=sys.stderr) # DEBUG
                        current_condition_eval_success = False
                else:
                    if fnmatch.fnmatch(file_path.name, value): match_result = True

                if current_condition_eval_success:
                    if operator == 'matches_pattern': current_condition_met = match_result
                    elif operator == 'not_matches_pattern': current_condition_met = not match_result
                    else:
                        # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, Cond[{i}]: Unknown operator for filename_pattern. Skipping.", file=sys.stderr) # DEBUG
                        current_condition_eval_success = False

            elif field == 'mime_type':
                if not isinstance(value, str):
                    # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, Cond[{i}]: Invalid value for mime_type. Skipping.", file=sys.stderr) # DEBUG
                    continue
                file_actual_mime = mime_type if mime_type and not mime_type.startswith("Error:") else ""
                # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, Cond[{i}]: Comparing file_actual_mime='{file_actual_mime}' with value='{value}'") # DEBUG
                current_condition_eval_success = True
                if operator == 'equals': current_condition_met = file_actual_mime == value
                elif operator == 'not_equals': current_condition_met = file_actual_mime != value
                elif operator == 'starts_with': current_condition_met = file_actual_mime.startswith(value)
                elif operator == 'ends_with': current_condition_met = file_actual_mime.endswith(value)
                elif operator == 'contains': current_condition_met = value in file_actual_mime
                else:
                    # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, Cond[{i}]: Unknown operator for mime_type. Skipping.", file=sys.stderr) # DEBUG
                    current_condition_eval_success = False

            elif field == 'tag':
                if not isinstance(value, str):
                    # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, Cond[{i}]: Invalid value for tag. Skipping.", file=sys.stderr) # DEBUG
                    continue
                file_tags = tags if tags else []
                # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, Cond[{i}]: Comparing file_tags='{file_tags}' with value='{value}'") # DEBUG
                current_condition_eval_success = True
                if operator == 'contains': current_condition_met = value in file_tags
                elif operator == 'not_contains': current_condition_met = value not in file_tags
                else:
                    # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, Cond[{i}]: Unknown operator for tag. Skipping.", file=sys.stderr) # DEBUG
                    current_condition_eval_success = False

            else:
                # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, Cond[{i}]: Unknown condition field '{field}'. Skipping.", file=sys.stderr) # DEBUG
                pass

            if current_condition_eval_success:
                condition_results.append(current_condition_met)
            # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, Cond[{i}] EvalSuccess={current_condition_eval_success}, Met={current_condition_met}") # DEBUG

        if not condition_results:
            # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, No valid conditions processed, returning False. Results: {condition_results}") # DEBUG
            return False

        final_result = False
        if condition_logic.upper() == 'AND':
            final_result = all(condition_results)
        elif condition_logic.upper() == 'OR':
            final_result = any(condition_results)
        else:
            # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, Unknown condition_logic '{condition_logic}'. Defaulting to AND.", file=sys.stderr) # DEBUG
            final_result = all(condition_results)

        # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, ConditionResults: {condition_results}, FinalResult: {final_result}") # DEBUG
        return final_result

    except FileNotFoundError:
        # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, FileNotFoundError during stat, returning False", file=sys.stderr) # DEBUG
        return False
    except Exception as e:
        # print(f"--- DBG_CHECK_FILE --- Path: {file_path.name}, Exception: {e}, returning False", file=sys.stderr) # DEBUG
        return False

def process_file_action(
    file_path: Path,
    monitored_folder_path: Path,
    archive_path_template: str,
    action: str,
    dry_run: bool,
    rule_matched: dict,
    history_logger_callable,
    run_id: str,
    tags: list[str] | None
) -> tuple[bool, str]:
    """
    Processes a file by moving, copying, or deleting it based on the provided template and action,
    supporting dry run and logging the action to history. Can use {TAGS} in archive_path_template.
    """
    try:
        filename_full = file_path.name

        if action == "copy" or action == "move":
            now = datetime.now()
            year = now.strftime("%Y")
            month = now.strftime("%m")
            day = now.strftime("%d")

            filename_stem = file_path.stem
            file_ext = file_path.suffix
            original_folder_name = monitored_folder_path.name

            current_template = archive_path_template

            if "{TAGS}" in current_template:
                if tags and len(tags) > 0:
                    cleaned_tags = [tag.split('_', 1)[-1] if '_' in tag else tag for tag in tags]
                    tag_string = "_".join(sorted(list(set(cleaned_tags))))
                    safe_tag_string = re.sub(r'[^\w\-]', '_', tag_string)
                    current_template = current_template.replace("{TAGS}", safe_tag_string)
                else:
                    current_template = current_template.replace("{TAGS}", "untagged")

            resolved_template = current_template.replace("{YYYY}", year)
            resolved_template = resolved_template.replace("{MM}", month)
            resolved_template = resolved_template.replace("{DD}", day)
            resolved_template = resolved_template.replace("{FILENAME}", filename_stem)
            resolved_template = resolved_template.replace("{EXT}", file_ext)
            resolved_template = resolved_template.replace("{ORIGINAL_FOLDER_NAME}", original_folder_name)

            target_base_dir = monitored_folder_path / resolved_template.lstrip('/')
            target_file_path = target_base_dir / filename_full

            counter = 1
            temp_target_file_path = target_file_path
            if not dry_run:
                while temp_target_file_path.exists():
                    temp_target_file_path = target_base_dir / f"{filename_stem}_{counter}{file_ext}"
                    counter += 1
                    if counter > 100:
                        message = f"Error: Too many filename collisions for {filename_full} in {target_base_dir}"
                        log_data_collision = {
                            "original_path": str(file_path), "action_taken": action.upper() + "_ERROR_COLLISION",
                            "destination_path": str(target_base_dir / filename_full), "monitored_folder": str(monitored_folder_path),
                            "rule_matched_name": rule_matched.get('name', 'Unnamed Rule'),
                            "rule_action_config": action, "status": "FAILURE", "details": message, "run_id": run_id
                        }
                        history_logger_callable(log_data_collision)
                        return False, message
                target_file_path = temp_target_file_path
            elif dry_run and target_file_path.exists():
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

            target_base_dir.mkdir(parents=True, exist_ok=True)

            actual_log_action_verb_str = ""
            if action == "copy":
                shutil.copy2(str(file_path), str(target_file_path))
                actual_log_action_verb_str = "COPIED"
            else:
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

        else:
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
