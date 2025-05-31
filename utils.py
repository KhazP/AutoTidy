
import os
import shutil
import fnmatch
import sys
import re # Import re module
import send2trash # Import send2trash
from datetime import datetime, timedelta
from pathlib import Path

def check_file(file_path: Path, age_days: int, pattern: str, use_regex: bool) -> bool:
    """
    Checks if a file meets the criteria (age OR pattern).

    Args:
        file_path: Path object of the file to check.
        age_days: Minimum age in days for the file to match.
        pattern: Filename pattern (fnmatch style or regex) to match.
        use_regex: Boolean indicating whether the pattern is a regular expression.

    Returns:
        True if the file matches either condition, False otherwise.
    """
    try:
        # 1. Check Age
        if age_days > 0:
            mod_time = file_path.stat().st_mtime
            age_threshold = datetime.now() - timedelta(days=age_days)
            if datetime.fromtimestamp(mod_time) < age_threshold:
                return True # Matches age criteria

        # 2. Check Pattern
        if pattern:
            if use_regex:
                try:
                    if re.fullmatch(pattern, file_path.name):
                        return True # Matches regex pattern criteria
                except re.error as e:
                    print(f"Error: Invalid regex pattern '{pattern}' for file {file_path.name}: {e}", file=sys.stderr)
                    # Treat as non-match if regex is invalid
            else:
                if fnmatch.fnmatch(file_path.name, pattern):
                    return True # Matches fnmatch pattern criteria

    except FileNotFoundError:
        # File might have been deleted between listing and checking
        print(f"Warning: File not found during check: {file_path}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error checking file {file_path}: {e}", file=sys.stderr)
        return False

    return False # Does not match any criteria

def process_file_action(file_path: Path, monitored_folder_path: Path, archive_path_template: str, action: str, dry_run: bool) -> tuple[bool, str]:
    """
    Processes a file by moving, copying, or deleting it based on the provided template and action, supporting dry run.

    Args:
        file_path: Path object of the file to process.
        monitored_folder_path: Path object of the folder being monitored (used for move/copy).
        archive_path_template: String template for the archive path (used for move/copy).
        action: The action to perform ("move", "copy", "delete_to_trash", "delete_permanently").
        dry_run: If True, simulate actions instead of performing them.

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

            resolved_template = archive_path_template.replace("{YYYY}", year)
            resolved_template = resolved_template.replace("{MM}", month)
            resolved_template = resolved_template.replace("{DD}", day)
            resolved_template = resolved_template.replace("{FILENAME}", filename_stem)
            resolved_template = resolved_template.replace("{EXT}", file_ext)
            resolved_template = resolved_template.replace("{ORIGINAL_FOLDER_NAME}", original_folder_name)

            target_base_dir = monitored_folder_path / resolved_template
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
                        return False, f"Error: Too many filename collisions for {filename_full} in {target_base_dir}"
                target_file_path = temp_target_file_path # Update target_file_path with non-colliding name for actual ops
            elif dry_run and target_file_path.exists(): # For dry run, if initial path exists, simulate one step of collision avoidance
                target_file_path = target_base_dir / f"{filename_stem}_1{file_ext}"


            relative_target_path = target_base_dir.relative_to(monitored_folder_path) / target_file_path.name

            if dry_run:
                log_action_verb = "Would copy" if action == "copy" else "Would move"
                # For dry run, mkdir is not called.
                return True, f"[DRY RUN] {log_action_verb}: '{filename_full}' to '{relative_target_path}'"

            # Actual operations (not a dry run)
            target_base_dir.mkdir(parents=True, exist_ok=True)

            # Re-evaluate target_file_path for actual operation to ensure it's the final one after collision check
            # The collision check before dry_run check should have set target_file_path correctly.
            # No, the collision check for non-dry run must be after mkdir potentially.
            # Let's ensure target_file_path is determined correctly *before* the operation.
            # The previous collision logic was fine, it determines the target_file_path before the shutil call.
            # The key is that `target_base_dir.mkdir` only happens if not dry_run.

            # The `target_file_path` determined by the loop (if not dry_run) or simulated (if dry_run and initial exists) is correct.

            log_action_verb = ""
            if action == "copy":
                shutil.copy2(str(file_path), str(target_file_path))
                log_action_verb = "Copied"
            else: # move
                shutil.move(str(file_path), str(target_file_path))
                log_action_verb = "Moved"

            return True, f"{log_action_verb}: {filename_full} -> {relative_target_path}"

        elif action == "delete_to_trash":
            if dry_run:
                return True, f"[DRY RUN] Would send to trash: '{filename_full}'"
            send2trash.send2trash(str(file_path))
            return True, f"Success: Sent to trash: '{filename_full}'"

        elif action == "delete_permanently":
            if dry_run:
                return True, f"[DRY RUN] Would permanently delete: '{filename_full}' (irreversible)"
            os.remove(str(file_path))
            # Optional: Consider a more permanent log for this action if needed for auditing
            # print(f"AUDIT: Permanently deleted '{file_path}' as per rule.", file=sys.stderr)
            return True, f"Success: Permanently deleted: '{filename_full}' (irreversible)"

        else:
            return False, f"Error: Unknown action '{action}' for file '{filename_full}'"

    except FileNotFoundError:
        # This specific exception might be less relevant for send2trash if it fails before finding the file,
        # but good to keep for os.remove and general shutil operations.
        return False, f"Error: Source file not found for {action}: '{file_path.name}'"
    except PermissionError:
        # Catches permission errors for all operations including os.remove and send2trash (if applicable)
        return False, f"Error: Permission denied for {action} on file '{file_path.name}'"
    except Exception as e:
        # General catch-all for other errors, including potential send2trash specific ones like send2trash.TrashPermissionError
        return False, f"Error performing {action} on '{file_path.name}': {e}"
