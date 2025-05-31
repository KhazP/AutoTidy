
import os
import shutil
import fnmatch
import sys
import re # Import re module
from datetime import datetime, timedelta
from pathlib import Path

def check_file(file_path: Path, age_days: int, pattern: str, rule_logic: str, pattern_type: str) -> bool:
    """
    Checks if a file meets the criteria based on age, pattern, rule_logic, and pattern_type.

    Args:
        file_path: Path object of the file to check.
        age_days: Minimum age in days for the file to match.
                  If 0, age condition is not considered for a match on its own.
        pattern: Filename pattern (fnmatch or regex) to match.
                 If empty, pattern condition is not considered for a match on its own.
        rule_logic: 'AND' or 'OR'. Determines how age and pattern matches are combined.
        pattern_type: 'glob' or 'regex'. Determines how the pattern is interpreted.

    Returns:
        True if the file matches the combined criteria, False otherwise.
    """
    try:
        age_matches = False
        if age_days > 0:
            mod_time = file_path.stat().st_mtime
            age_threshold = datetime.now() - timedelta(days=age_days)
            if datetime.fromtimestamp(mod_time) < age_threshold:
                age_matches = True

        pattern_matches = False
        if pattern:  # Only attempt to match if pattern is not empty
            if pattern_type.lower() == "regex":
                try:
                    if re.fullmatch(pattern, file_path.name):
                        pattern_matches = True
                except re.error as e:
                    print(f"Error: Invalid regex pattern '{pattern}' for file {file_path.name}: {e}", file=sys.stderr)
                    pattern_matches = False # Treat as no match on regex error
            else:  # Default to glob matching (fnmatch)
                if fnmatch.fnmatch(file_path.name, pattern):
                    pattern_matches = True

        # Handle logic based on rule_logic, age_days, and pattern presence
        if rule_logic.upper() == "AND":
            if age_days == 0 and not pattern: # No criteria to AND
                return False
            elif age_days == 0: # Only pattern matters
                return pattern_matches
            elif not pattern: # Only age matters
                return age_matches
            else: # Both age and pattern criteria are active
                return age_matches and pattern_matches
        elif rule_logic.upper() == "OR":
            if age_days == 0 and not pattern: # No criteria to OR
                return False
            elif age_days == 0: # Only pattern matters for OR if age is 0
                return pattern_matches
            elif not pattern: # Only age matters for OR if pattern is empty
                return age_matches
            else: # Either age or pattern can trigger a match
                return age_matches or pattern_matches
        else:
            # Default or unknown logic, perhaps log a warning or treat as OR
            print(f"Warning: Unknown rule_logic '{rule_logic}'. Defaulting to OR.", file=sys.stderr)
            return age_matches or pattern_matches # Fallback to OR

    except FileNotFoundError:
        print(f"Warning: File not found during check: {file_path}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error checking file {file_path}: {e}", file=sys.stderr)
        return False

def move_file(file_path: Path, monitored_folder_path: Path, archive_format_string: str) -> tuple[bool, str]:
    """
    Moves a file to a subdirectory structured by the archive_format_string.

    Args:
        file_path: Path object of the file to move.
        monitored_folder_path: Path object of the folder being monitored.
        archive_format_string: strftime format string for the target subdirectory.

    Returns:
        A tuple (success: bool, message: str).
    """
    try:
        try:
            target_date_subdir_name = datetime.now().strftime(archive_format_string)
        except ValueError as e:
            print(f"Warning: Invalid archive_format_string '{archive_format_string}': {e}. Falling back to '%Y-%m-%d'.", file=sys.stderr)
            target_date_subdir_name = datetime.now().strftime("%Y-%m-%d")

        target_dir_name = "_Cleanup"
        # Ensure no leading/trailing slashes from format string cause issues with path joining
        target_date_subdir_name = target_date_subdir_name.strip(os.path.sep)
        target_subdir = monitored_folder_path / target_dir_name / target_date_subdir_name
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
        # Use target_date_subdir_name in the log message
        return True, f"Moved: {file_path.name} -> {target_dir_name}/{target_date_subdir_name}/"

    except FileNotFoundError:
        return False, f"Error: Source file not found for move: {file_path}"
    except PermissionError:
        return False, f"Error: Permission denied moving {file_path} or creating {target_subdir}"
    except Exception as e:
        return False, f"Error moving file {file_path}: {e}"
