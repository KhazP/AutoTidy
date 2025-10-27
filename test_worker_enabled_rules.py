import queue
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from worker import MonitoringWorker


class SingleCycleStopEvent:
    """Stop event replacement that allows a single monitoring cycle."""

    def __init__(self):
        self._is_set = False

    def is_set(self):
        return self._is_set

    def wait(self, timeout):
        self._is_set = True
        return True

    def set(self):
        self._is_set = True


class MockConfigManager:
    def __init__(self, monitored_path: Path, config_dir: Path, enabled: bool):
        self._monitored_path = monitored_path
        self._config_dir = config_dir
        self._enabled = enabled

    def get_monitored_folders(self):
        return [{
            'path': str(self._monitored_path),
            'age_days': 0,
            'pattern': '*.*',
            'use_regex': False,
            'rule_logic': 'OR',
            'action': 'move',
            'destination_folder': '',
            'exclusions': [],
            'enabled': self._enabled,
        }]

    def get_dry_run_mode(self):
        return True

    def get_archive_path_template(self):
        return "{YYYY}/{MM}/{DD}"

    def get_schedule_config(self):
        return {'interval_minutes': 0}

    def get_config_dir_path(self):
        return self._config_dir


class TestMonitoringWorkerEnabledRules(TestCase):

    def _run_worker_once(self, config_manager):
        log_queue = queue.Queue()
        worker = MonitoringWorker(config_manager, log_queue)
        worker._stop_event = SingleCycleStopEvent()
        with patch('worker.check_file', return_value=True), patch('worker.process_file_action') as process_mock:
            process_mock.return_value = (True, 'processed')
            worker.run()
        return process_mock

    def test_enabled_rule_processes_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_path = Path(tmp_dir)
            monitored_path = base_path / "monitored"
            config_dir = base_path / "config"
            monitored_path.mkdir()
            config_dir.mkdir()

            (monitored_path / "example.txt").write_text("content")

            config_manager = MockConfigManager(monitored_path, config_dir, enabled=True)

            process_mock = self._run_worker_once(config_manager)
            self.assertGreater(process_mock.call_count, 0, "Enabled rules should process matching files")

    def test_disabled_rule_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_path = Path(tmp_dir)
            monitored_path = base_path / "monitored"
            config_dir = base_path / "config"
            monitored_path.mkdir()
            config_dir.mkdir()

            (monitored_path / "example.txt").write_text("content")

            config_manager = MockConfigManager(monitored_path, config_dir, enabled=False)

            process_mock = self._run_worker_once(config_manager)
            self.assertEqual(process_mock.call_count, 0, "Disabled rules should be skipped entirely")


if __name__ == '__main__':
    import unittest
    unittest.main()
