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
    def __init__(self, monitored_path: Path, config_dir: Path, use_regex: bool, exclusions: list[str]):
        self._monitored_path = monitored_path
        self._config_dir = config_dir
        self._use_regex = use_regex
        self._exclusions = exclusions

    def get_monitored_folders(self):
        return [{
            'path': str(self._monitored_path),
            'age_days': 0,
            'pattern': '*.txt' if not self._use_regex else r".*\\.log",
            'use_regex': self._use_regex,
            'rule_logic': 'OR',
            'action': 'move',
            'destination_folder': '',
            'exclusions': self._exclusions,
        }]

    def get_dry_run_mode(self):
        return True

    def get_archive_path_template(self):
        return "{YYYY}/{MM}/{DD}"

    def get_schedule_config(self):
        return {'interval_minutes': 0}

    def get_config_dir_path(self):
        return self._config_dir


class TestMonitoringWorkerExclusions(TestCase):

    def _run_worker_once(self, config_manager):
        log_queue = queue.Queue()
        worker = MonitoringWorker(config_manager, log_queue)
        worker._stop_event = SingleCycleStopEvent()
        with patch('worker.check_file', return_value=True), patch('worker.process_file_action') as process_mock:
            worker.run()
        return process_mock

    def test_glob_exclusion_prevents_processing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_path = Path(tmp_dir)
            monitored_path = base_path / "monitored"
            config_dir = base_path / "config"
            monitored_path.mkdir()
            config_dir.mkdir()

            (monitored_path / "skip_me.txt").write_text("data")

            config_manager = MockConfigManager(
                monitored_path=monitored_path,
                config_dir=config_dir,
                use_regex=False,
                exclusions=['skip_*.txt']
            )

            process_mock = self._run_worker_once(config_manager)
            self.assertEqual(process_mock.call_count, 0, "Excluded files should not trigger processing")

    def test_regex_exclusion_prevents_processing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_path = Path(tmp_dir)
            monitored_path = base_path / "monitored"
            config_dir = base_path / "config"
            monitored_path.mkdir()
            config_dir.mkdir()

            (monitored_path / "skipme.log").write_text("data")

            config_manager = MockConfigManager(
                monitored_path=monitored_path,
                config_dir=config_dir,
                use_regex=True,
                exclusions=[r"skipme\.log"]
            )

            process_mock = self._run_worker_once(config_manager)
            self.assertEqual(process_mock.call_count, 0, "Excluded files should not trigger processing")


if __name__ == '__main__':
    import unittest
    unittest.main()
