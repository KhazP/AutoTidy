"""Tests for config corruption recovery."""
import json
import pytest
from pathlib import Path


def _make_cm(tmp_path):
    from config_manager import ConfigManager

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    cm = ConfigManager.__new__(ConfigManager)
    cm.app_name = "TestApp"
    cm.config_dir = config_dir
    cm.config_file = config_dir / "config.json"
    cm.default_config = {
        'folders': [],
        'excluded_folders': [],
        'settings': {
            'start_on_login': False,
            'archive_path_template': '_Cleanup/{YYYY}-{MM}-{DD}',
            'schedule_type': 'interval',
            'interval_minutes': 60,
            'dry_run_mode': False,
            'notification_level': 'all',
            'hide_instructions': False,
            'log_level': 'INFO',
        }
    }
    return cm


def test_corrupted_json_creates_backup(tmp_path):
    """Corrupted JSON config creates a .corrupt.bak backup file."""
    cm = _make_cm(tmp_path)
    cm.config_file.write_text("{invalid json: [}", encoding="utf-8")

    cm.config = cm._load_config()

    backup = Path(str(cm.config_file) + ".corrupt.bak")
    assert backup.exists(), "Backup file should have been created for corrupted config"


def test_corrupted_json_returns_defaults(tmp_path):
    """Corrupted JSON config returns defaults."""
    cm = _make_cm(tmp_path)
    cm.config_file.write_text("this is not json!!!", encoding="utf-8")

    config = cm._load_config()

    assert isinstance(config, dict)
    assert config.get('folders') == []


def test_valid_config_no_backup_created(tmp_path):
    """Valid config does not create a .corrupt.bak file."""
    cm = _make_cm(tmp_path)
    valid = {"folders": [], "excluded_folders": [], "settings": {}}
    cm.config_file.write_text(json.dumps(valid), encoding="utf-8")

    cm.config = cm._load_config()

    backup = Path(str(cm.config_file) + ".corrupt.bak")
    assert not backup.exists(), "No backup should be created for valid config"


def test_missing_config_returns_defaults(tmp_path):
    """Missing config file returns defaults without error."""
    cm = _make_cm(tmp_path)
    # Don't create the config file
    config = cm._load_config()

    assert isinstance(config, dict)
    assert 'folders' in config


def test_backup_contains_original_corrupt_data(tmp_path):
    """Backup file contains the original corrupt data."""
    cm = _make_cm(tmp_path)
    corrupt_content = "not valid {json at all"
    cm.config_file.write_text(corrupt_content, encoding="utf-8")

    cm.config = cm._load_config()

    backup = Path(str(cm.config_file) + ".corrupt.bak")
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == corrupt_content
