"""Tests for path validation: symlink skipping and boundary enforcement."""
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock


def test_symlink_skipped_in_get_preview_matches(tmp_path):
    """Symlinks should be skipped in get_preview_matches."""
    from utils import get_preview_matches

    real_file = tmp_path / "real.txt"
    real_file.write_text("content")

    link = tmp_path / "link.txt"
    try:
        link.symlink_to(real_file)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this system")

    matches = get_preview_matches(tmp_path, 0, "*", False)
    match_names = {p.name for p in matches}
    assert "real.txt" in match_names
    assert "link.txt" not in match_names


def test_boundary_check_rejects_traversal(tmp_path):
    """process_file_action should reject templates containing '..' traversal."""
    from utils import process_file_action

    src_dir = tmp_path / "source"
    src_dir.mkdir()
    src_file = src_dir / "test.txt"
    src_file.write_text("hello")

    history_calls = []

    success, msg = process_file_action(
        file_path=src_file,
        monitored_folder_path=src_dir,
        archive_path_template="../../evil",
        action="move",
        dry_run=False,
        rule_pattern="*",
        rule_age_days=0,
        rule_use_regex=False,
        history_logger_callable=lambda d: history_calls.append(d),
        run_id="test-run",
        destination_folder=None,
    )
    assert not success
    assert any(kw in msg.lower() for kw in ("traversal", "template", "boundary", "invalid"))


def test_path_normalization_in_add_folder(tmp_path):
    """add_folder should store the resolved (normalized) path."""
    from config_manager import ConfigManager

    config_dir = tmp_path / "config"
    config_dir.mkdir()

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
    cm.config = {'folders': [], 'excluded_folders': [], 'settings': {}}

    monitor_dir = tmp_path / "monitored"
    monitor_dir.mkdir()

    raw_path = str(monitor_dir) + os.sep
    cm.add_folder(raw_path)

    stored = cm.config['folders'][0]['path']
    assert not stored.endswith(os.sep)
    assert stored == str(monitor_dir.resolve())


def test_path_normalization_in_add_excluded_folder(tmp_path):
    """add_excluded_folder should store the resolved path."""
    from config_manager import ConfigManager

    config_dir = tmp_path / "config"
    config_dir.mkdir()

    cm = ConfigManager.__new__(ConfigManager)
    cm.app_name = "TestApp"
    cm.config_dir = config_dir
    cm.config_file = config_dir / "config.json"
    cm.default_config = {
        'folders': [], 'excluded_folders': [],
        'settings': {'notification_level': 'all', 'log_level': 'INFO',
                     'start_on_login': False, 'archive_path_template': '',
                     'schedule_type': 'interval', 'interval_minutes': 60,
                     'dry_run_mode': False, 'hide_instructions': False}
    }
    cm.config = {'folders': [], 'excluded_folders': [], 'settings': {}}

    excl_dir = tmp_path / "excluded"
    excl_dir.mkdir()

    cm.add_excluded_folder(str(excl_dir) + os.sep)
    stored = cm.config['excluded_folders'][0]
    assert stored == str(excl_dir.resolve())
