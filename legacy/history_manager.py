import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import constants

logger = logging.getLogger(__name__)

MAX_HISTORY_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_HISTORY_BACKUPS = 3
DEFAULT_MAX_AGE_DAYS = 90


class HistoryManager:
    """Manages logging of file actions to a history file."""

    def __init__(self, config_manager):
        self.history_file_path = config_manager.get_config_dir_path() / "autotidy_history.jsonl"
        self._ensure_history_dir_exists()

    def _ensure_history_dir_exists(self):
        try:
            self.history_file_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error("Could not create history log directory %s: %s", self.history_file_path.parent, e)

    def _rotate_if_needed(self):
        """Rotate the history file if it exceeds MAX_HISTORY_SIZE_BYTES."""
        try:
            if not self.history_file_path.exists():
                return
            if self.history_file_path.stat().st_size < MAX_HISTORY_SIZE_BYTES:
                return

            # Rotate backups: .3 is deleted, .2 → .3, .1 → .2, current → .1
            for i in range(MAX_HISTORY_BACKUPS, 0, -1):
                backup = Path(f"{self.history_file_path}.{i}")
                older = Path(f"{self.history_file_path}.{i - 1}") if i > 1 else self.history_file_path
                if backup.exists():
                    if i == MAX_HISTORY_BACKUPS:
                        backup.unlink()
                    else:
                        backup.unlink()
                if older.exists():
                    older.rename(backup)
        except Exception as e:
            logger.warning("Could not rotate history log: %s", e)

    def prune_old_entries(self, max_age_days: int = DEFAULT_MAX_AGE_DAYS):
        """Remove history entries older than max_age_days from the current log file."""
        if not self.history_file_path.exists():
            return

        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        kept = []
        try:
            with open(self.history_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        ts_str = entry.get("timestamp", "")
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if ts >= cutoff:
                            kept.append(line)
                    except (json.JSONDecodeError, ValueError):
                        kept.append(line)  # Keep unparseable lines

            with open(self.history_file_path, 'w', encoding='utf-8') as f:
                for line in kept:
                    f.write(line + '\n')
        except IOError as e:
            logger.error("Error pruning history log: %s", e)

    def log_action(self, data: dict):
        """Logs an action to the history file, rotating if necessary."""
        if not self.history_file_path.parent.exists():
            logger.error("History log directory does not exist. Cannot log action: %s", data.get('original_path', 'N/A'))
            return

        data["timestamp"] = datetime.now(timezone.utc).isoformat()

        if "severity" not in data:
            status = data.get("status")
            if status == constants.STATUS_FAILURE:
                data["severity"] = "ERROR"
            elif status == constants.STATUS_SUCCESS:
                data["severity"] = "INFO"
            elif status:
                data["severity"] = "WARNING"
            else:
                data["severity"] = "INFO"

        self._rotate_if_needed()

        try:
            with open(self.history_file_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(data) + '\n')
        except IOError as e:
            logger.error("Error writing to history log file %s: %s", self.history_file_path, e)
        except Exception as e:
            logger.error("Unexpected error during history logging: %s", e)
