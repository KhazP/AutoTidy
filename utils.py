import os
import shutil
import fnmatch
import sys
from datetime import datetime, timedelta
from pathlib import Path

def check_file(file_path: Path, age_days: int, pattern: str, rule_logic: str) -> bool:
    """
    Checks if a file meets the age and/or pattern criteria based on rule_logic.

    Args:
        file_path: Path object of the file to check.
        age_days: Minimum age in days for the file to match.
        pattern: Filename pattern (fnmatch style) to match.
        rule_logic: "AND" or "OR", determining how criteria are combined.

    Returns:
        True if the file matches the combined criteria, False otherwise.
    """
    try:
        file_is_old_enough = False
        if age_days > 0:
            mod_time = file_path.stat().st_mtime
            age_threshold = datetime.now() - timedelta(days=age_days)
            if datetime.fromtimestamp(mod_time) < age_threshold:
                file_is_old_enough = True

        filename_matches_pattern = False
        # Only evaluate pattern if it's not an empty string
        if pattern: # Check if pattern string is not empty
            if fnmatch.fnmatch(file_path.name, pattern):
                filename_matches_pattern = True

        age_criterion_active = age_days > 0
        pattern_criterion_active = bool(pattern) # True if pattern string is not empty

        if rule_logic.upper() == "AND":
            if not age_criterion_active and not pattern_criterion_active:
                return False # No criteria to satisfy for AND.

            # For AND, an inactive criterion is "passed" by default.
            eval_age = file_is_old_enough if age_criterion_active else True
            eval_pattern = filename_matches_pattern if pattern_criterion_active else True
            return eval_age and eval_pattern

        else: # OR logic (or any other string defaults to OR)
            if not age_criterion_active and not pattern_criterion_active:
                return False # No criteria to satisfy for OR.

            # For OR, an inactive criterion is "not passed" by default.
            eval_age = file_is_old_enough if age_criterion_active else False
            eval_pattern = filename_matches_pattern if pattern_criterion_active else False
            return eval_age or eval_pattern

    except FileNotFoundError:
        print(f"Warning: File not found during check: {file_path}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error checking file {file_path}: {e}", file=sys.stderr)
        return False
    # Fallback, though ideally unreachable if logic above is exhaustive for all rule_logic cases
    return False

def move_file(file_path: Path, monitored_folder_path: Path) -> tuple[bool, str]:
    """
    Moves a file to the dated archive subdirectory.

    Args:
        file_path: Path object of the file to move.
        monitored_folder_path: Path object of the folder being monitored.

    Returns:
        A tuple (success: bool, message: str).
    """
    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        target_dir_name = "_Cleanup"
        target_subdir = monitored_folder_path / target_dir_name / today_str
        target_subdir.mkdir(parents=True, exist_ok=True)

        target_file_path = target_subdir / file_path.name

        # Handle potential filename collisions (simple incrementing)
        counter = 1
        original_stem = target_file_path.stem
        original_suffix = target_file_path.suffix
        while target_file_path.exists():
            target_file_path = target_subdir / f"{original_stem}_{counter}{original_suffix}"
            counter += 1
            if counter > 100: # Safety break
                 return False, f"Error: Too many filename collisions for {file_path.name} in {target_subdir}"


        shutil.move(str(file_path), str(target_file_path))
        return True, f"Moved: {file_path.name} -> {target_dir_name}/{today_str}/"

    except FileNotFoundError:
        return False, f"Error: Source file not found for move: {file_path}"
    except PermissionError:
        return False, f"Error: Permission denied moving {file_path} or creating {target_subdir}"
    except Exception as e:
        return False, f"Error moving file {file_path}: {e}"
