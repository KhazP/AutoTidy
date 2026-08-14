
import os
import shutil
import fnmatch
import sys
import logging
import re
import functools
import send2trash
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

_regex_executor = ThreadPoolExecutor(max_workers=1)


@functools.lru_cache(maxsize=256)
def _compile_pattern(pattern: str) -> "re.Pattern | None":
    """Compile a regex pattern once, with timeout protection on first call.

    Result is cached for the lifetime of the process, so per-file matching
    incurs no thread overhead after the first compilation.
    """
    try:
        future = _regex_executor.submit(re.compile, pattern)
        return future.result(timeout=2.0)
    except FuturesTimeout:
        logger.warning("Regex pattern '%s' timed out during compilation", pattern)
        return None
    except re.error:
        return None


def safe_regex_match(pattern: str, string: str, timeout: float = 2.0) -> "re.Match | None":
    """Match *string* against *pattern* safely.

    Compilation is timeout-protected and cached; per-file matching runs the
    compiled pattern directly, eliminating thread-submission overhead.
    """
    compiled = _compile_pattern(pattern)
    if compiled is None:
        return None
    try:
        return compiled.fullmatch(string)
    except re.error:
        return None


def validate_archive_template(template: str) -> tuple[bool, str]:
    """Validate an archive path template for safety.

    Returns (True, "") on success, or (False, reason) on failure.
    """
    if not template:
        return True, ""

    # No path traversal
    parts = Path(template.replace("\\", "/")).parts
    if ".." in parts:
        return False, "Template must not contain '..' path traversal components"

    # Only allowed placeholders
    import re as _re
    placeholders = _re.findall(r'\{([^}]+)\}', template)
    allowed = {"YYYY", "MM", "DD", "FILENAME", "EXT", "ORIGINAL_FOLDER_NAME"}
    for ph in placeholders:
        if ph not in allowed:
            return False, f"Unknown placeholder {{{ph}}}. Allowed: {', '.join(sorted(allowed))}"

    # No dangerous characters
    dangerous = set(';|&`')
    for ch in dangerous:
        if ch in template:
            return False, f"Template contains dangerous character: '{ch}'"

    return True, ""


def _atomic_claim_path(base_dir: Path, stem: str, ext: str, max_attempts: int = 100) -> Path:
    """Atomically claim a unique file path using O_CREAT|O_EXCL.

    Creates a placeholder file to reserve the name, returns the path.
    Caller is responsible for replacing the placeholder with real content.
    """
    candidate = base_dir / f"{stem}{ext}"
    for i in range(max_attempts + 1):
        try:
            fd = os.open(str(candidate), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return candidate
        except FileExistsError:
            if i < max_attempts:
                candidate = base_dir / f"{stem}_{i + 1}{ext}"
    # Final timestamp fallback
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    candidate = base_dir / f"{stem}_{ts}{ext}"
    fd = os.open(str(candidate), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    return candidate


def check_file(
    file_path: Path,
    age_days: int,
    pattern: str,
    use_regex: bool,
    rule_logic: str = "OR",
    precomputed_stat: "os.stat_result | None" = None,
) -> bool:
    """
    Checks if a file meets the criteria using the configured logic.

    Args:
        file_path: Path object of the file to check.
        age_days: Minimum age in days for the file to match.
        pattern: Filename pattern (fnmatch style or regex) to match.
        use_regex: Boolean indicating whether the pattern is a regular expression.
        precomputed_stat: Optional cached stat result to avoid a redundant syscall.

    Returns:
        True if the file matches the configured logic, False otherwise.
    """
    try:
        # 1. Check Age
        age_match = age_days <= 0
        if age_days > 0:
            stat_result = precomputed_stat if precomputed_stat is not None else file_path.stat()
            mod_time = stat_result.st_mtime
            age_threshold = datetime.now() - timedelta(days=age_days)
            if datetime.fromtimestamp(mod_time) < age_threshold:
                age_match = True # Matches age criteria

        # 2. Check Pattern
        pattern_match = False
        if pattern:
            if use_regex:
                try:
                    if safe_regex_match(pattern, file_path.name):
                        pattern_match = True # Matches regex pattern criteria
                except re.error as e:
                    logger.error("Invalid regex pattern '%s' for file %s: %s", pattern, file_path.name, e)
                    # Treat as non-match if regex is invalid
            else:
                if fnmatch.fnmatch(file_path.name, pattern):
                    pattern_match = True # Matches fnmatch pattern criteria

        logic = (rule_logic or "OR").upper()
        if logic == "AND":
            return age_match and pattern_match
        return age_match or pattern_match

    except FileNotFoundError:
        logger.warning("File not found during check: %s", file_path)
        return False
    except Exception as e:
        logger.error("Error checking file %s: %s", file_path, e)
        return False


def get_preview_matches(
    monitored_folder: Path,
    age_days: int,
    pattern: str,
    use_regex: bool,
    rule_logic: str = "OR",
    max_results: int = 10,
) -> List[Path]:
    """Return up to ``max_results`` files that match the provided rule parameters.

    Args:
        monitored_folder: Folder containing files to evaluate.
        age_days: Minimum age in days for files to match.
        pattern: Pattern or regular expression to evaluate against filenames.
        use_regex: Whether ``pattern`` should be treated as a regular expression.
        rule_logic: Combination logic for age and pattern rules (``"AND"`` or ``"OR"``).
        max_results: Maximum number of matching files to return.

    Raises:
        NotADirectoryError: If ``monitored_folder`` is not a valid directory.

    Returns:
        A list of Path objects representing matching files.
    """

    if not monitored_folder.is_dir():
        raise NotADirectoryError(f"{monitored_folder} is not a directory")

    matches: List[Path] = []
    try:
        with os.scandir(str(monitored_folder)) as scanner:
            entries = sorted(scanner, key=lambda e: e.name.lower())
        for entry in entries:
            if entry.is_symlink():
                logger.debug("Skipping symlink in preview: %s", entry.path)
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            entry_stat = entry.stat(follow_symlinks=False)
            if check_file(Path(entry.path), age_days, pattern, use_regex, rule_logic,
                          precomputed_stat=entry_stat):
                matches.append(Path(entry.path))
                if len(matches) >= max_results:
                    break
    except PermissionError as exc:
        raise PermissionError(f"Permission denied accessing {monitored_folder}") from exc

    return matches


def resolve_destination_for_preview(
    monitored_folder: Path,
    destination_template: str,
) -> Path:
    """Resolve a destination template to the base directory used for preview checks.

    Args:
        monitored_folder: The folder being monitored.
        destination_template: Destination string provided by the user.

    Returns:
        Path to the directory that should exist prior to performing the move/copy.

    Raises:
        NotADirectoryError: If ``monitored_folder`` is not a directory.
        ValueError: If ``destination_template`` is empty.
    """

    if not destination_template:
        raise ValueError("Destination template must not be empty.")

    if not monitored_folder.is_dir():
        raise NotADirectoryError(f"{monitored_folder} is not a directory")

    now = datetime.now()
    original_template = destination_template
    resolved_template = destination_template

    replacements = {
        "{YYYY}": now.strftime("%Y"),
        "{MM}": now.strftime("%m"),
        "{DD}": now.strftime("%d"),
        "{ORIGINAL_FOLDER_NAME}": monitored_folder.name,
    }

    includes_filename_tokens = any(
        token in resolved_template for token in ("{FILENAME}", "{EXT}")
    )

    if includes_filename_tokens:
        replacements.setdefault("{FILENAME}", "sample")
        replacements.setdefault("{EXT}", ".txt")

    for placeholder, value in replacements.items():
        resolved_template = resolved_template.replace(placeholder, value)

    resolved_template = os.path.expandvars(resolved_template)
    resolved_template = os.path.expanduser(resolved_template)

    path_candidate = Path(resolved_template)
    if not path_candidate.is_absolute():
        path_candidate = (monitored_folder / path_candidate).resolve()
    else:
        path_candidate = path_candidate.resolve()

    if includes_filename_tokens or any(
        token in original_template for token in ("{FILENAME}", "{EXT}")
    ):
        return path_candidate.parent

    return path_candidate

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
            _tmpl_ok, _tmpl_err = validate_archive_template(template_in_use)
            if not _tmpl_ok:
                message = f"Error: Invalid archive template: {_tmpl_err}"
                log_data = {
                    "original_path": str(file_path), "action_taken": action.upper() + "_ERROR_TEMPLATE",
                    "destination_path": None, "monitored_folder": str(monitored_folder_path),
                    "rule_pattern": rule_pattern, "rule_age_days": rule_age_days, "rule_use_regex": rule_use_regex,
                    "rule_action_config": action, "status": "FAILURE", "details": message, "run_id": run_id
                }
                history_logger_callable(log_data)
                return False, message
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

            # Boundary check: ensure resolved target stays within target_base_dir
            try:
                resolved_target = target_file_path.resolve()
                resolved_base = target_base_dir.resolve()
                if not (str(resolved_target).startswith(str(resolved_base) + os.sep) or resolved_target == resolved_base):
                    message = f"Error: Target path escapes destination boundary for '{filename_full}'"
                    log_data = {
                        "original_path": str(file_path), "action_taken": action.upper() + "_ERROR_BOUNDARY",
                        "destination_path": None, "monitored_folder": str(monitored_folder_path),
                        "rule_pattern": rule_pattern, "rule_age_days": rule_age_days, "rule_use_regex": rule_use_regex,
                        "rule_action_config": action, "status": "FAILURE", "details": message, "run_id": run_id
                    }
                    history_logger_callable(log_data)
                    return False, message
            except OSError:
                pass  # resolve() can fail for non-existent paths; allow operation to proceed

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

            if not dry_run:
                # Atomically claim a unique path to avoid TOCTOU race
                try:
                    target_base_dir.mkdir(parents=True, exist_ok=True)
                    target_file_path = _atomic_claim_path(target_base_dir, filename_stem, file_ext)
                except OSError as _claim_err:
                    message = f"Error: Could not claim unique path for '{filename_full}': {_claim_err}"
                    log_data_collision = {
                        "original_path": str(file_path), "action_taken": action.upper() + "_ERROR_COLLISION",
                        "destination_path": str(target_base_dir / filename_full), "monitored_folder": str(monitored_folder_path),
                        "rule_pattern": rule_pattern, "rule_age_days": rule_age_days, "rule_use_regex": rule_use_regex,
                        "rule_action_config": action, "status": "FAILURE", "details": message, "run_id": run_id
                    }
                    history_logger_callable(log_data_collision)
                    return False, message
            elif dry_run and target_file_path.exists():
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
            # target_base_dir.mkdir already called inside the atomic claim block above

            actual_log_action_verb_str = ""
            if action == "copy":
                shutil.copy2(str(file_path), str(target_file_path))
                actual_log_action_verb_str = "COPIED"
            else:  # move — two-phase: rename (same-FS fast path) or copy+verify+unlink
                src = Path(file_path)
                dst = Path(target_file_path)
                try:
                    # Remove the empty placeholder created by _atomic_claim_path before renaming
                    if dst.exists() and dst.stat().st_size == 0:
                        dst.unlink()
                    src.rename(dst)
                except OSError:
                    # Cross-filesystem fallback: copy2 → verify size → unlink source
                    shutil.copy2(str(src), str(dst))
                    if dst.stat().st_size != src.stat().st_size:
                        dst.unlink()
                        raise OSError("Copy verification failed: size mismatch")
                    src.unlink()
                actual_log_action_verb_str = "MOVED"

            message = f"{actual_log_action_verb_str.capitalize()}: {filename_full} -> {relative_target_path}"
            log_data = {
                "original_path": str(file_path), "action_taken": actual_log_action_verb_str,
                "destination_path": str(target_file_path), "monitored_folder": str(monitored_folder_path),
                "rule_pattern": rule_pattern, "rule_age_days": rule_age_days, "rule_use_regex": rule_use_regex,
                "rule_action_config": action, "status": "SUCCESS", "details": message, "run_id": run_id
            }
            # Record identity metadata for copy so undo can verify the file hasn't changed
            if action == "copy":
                try:
                    stat = target_file_path.stat()
                    log_data["copy_size"] = stat.st_size
                    log_data["copy_mtime"] = stat.st_mtime
                except OSError:
                    pass
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
