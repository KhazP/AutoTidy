
import os
import shutil
import fnmatch
import sys
from datetime import datetime, timedelta
from pathlib import Path

def check_file(file_path: Path, age_days: int, pattern: str) -> bool:
    """
    Checks if a file meets the criteria (age OR pattern).

    Args:
        file_path: Path object of the file to check.
        age_days: Minimum age in days for the file to match.
        pattern: Filename pattern (fnmatch style) to match.

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
        if pattern and fnmatch.fnmatch(file_path.name, pattern):
            return True # Matches pattern criteria

    except FileNotFoundError:
        # File might have been deleted between listing and checking
        print(f"Warning: File not found during check: {file_path}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error checking file {file_path}: {e}", file=sys.stderr)
        return False

    return False # Does not match any criteria

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
