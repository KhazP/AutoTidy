"""Tests for notification level validation in ConfigManager."""
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
    cm.config = {
        'folders': [],
        'excluded_folders': [],
        'settings': dict(cm.default_config['settings']),
    }
    return cm


def test_valid_levels_accepted(tmp_path):
    """All valid notification levels are accepted without modification."""
    cm = _make_cm(tmp_path)
    for level in ("none", "error", "summary", "all"):
        cm.set_notification_level(level)
        assert cm.config['settings']['notification_level'] == level


def test_invalid_level_falls_back_to_default(tmp_path):
    """Invalid notification level falls back to DEFAULT_NOTIFICATION_LEVEL."""
    from constants import DEFAULT_NOTIFICATION_LEVEL
    cm = _make_cm(tmp_path)
    cm.set_notification_level("bogus_level")
    assert cm.config['settings']['notification_level'] == DEFAULT_NOTIFICATION_LEVEL


def test_empty_string_level_falls_back(tmp_path):
    """Empty string notification level falls back to default."""
    from constants import DEFAULT_NOTIFICATION_LEVEL
    cm = _make_cm(tmp_path)
    cm.set_notification_level("")
    assert cm.config['settings']['notification_level'] == DEFAULT_NOTIFICATION_LEVEL


def test_invalid_level_on_load_normalized(tmp_path):
    """Invalid level stored in config file is normalized to default on load."""
    from config_manager import ConfigManager
    from constants import DEFAULT_NOTIFICATION_LEVEL

    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config_file = config_dir / "config.json"

    bad_config = {
        "folders": [],
        "excluded_folders": [],
        "settings": {"notification_level": "definitely_invalid"}
    }
    config_file.write_text(json.dumps(bad_config), encoding="utf-8")

    cm = ConfigManager.__new__(ConfigManager)
    cm.app_name = "TestApp"
    cm.config_dir = config_dir
    cm.config_file = config_file
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
    cm.config = cm._load_config()
    level = cm.config['settings']['notification_level']
    assert level == DEFAULT_NOTIFICATION_LEVEL


def test_valid_level_on_load_preserved(tmp_path):
    """Valid level stored in config file is preserved on load."""
    from config_manager import ConfigManager

    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config_file = config_dir / "config.json"

    good_config = {
        "folders": [],
        "excluded_folders": [],
        "settings": {"notification_level": "error"}
    }
    config_file.write_text(json.dumps(good_config), encoding="utf-8")

    cm = ConfigManager.__new__(ConfigManager)
    cm.app_name = "TestApp"
    cm.config_dir = config_dir
    cm.config_file = config_file
    cm.default_config = {
        'folders': [], 'excluded_folders': [],
        'settings': {'start_on_login': False, 'archive_path_template': '',
                     'schedule_type': 'interval', 'interval_minutes': 60,
                     'dry_run_mode': False, 'notification_level': 'all',
                     'hide_instructions': False, 'log_level': 'INFO'}
    }
    cm.config = cm._load_config()
    assert cm.config['settings']['notification_level'] == "error"
