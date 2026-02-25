import queue
import tempfile
import uuid
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from constants import NOTIFICATION_LEVEL_ALL
from worker import MonitoringWorker


class ControlledStopEvent:
    """A controllable event to stop the worker after a fixed number of cycles."""

    def __init__(self, cycles):
        self._remaining_cycles = cycles

    def is_set(self):
        return self._remaining_cycles <= 0

    def wait(self, timeout):
        # Simulate waiting for the next interval by decrementing the cycle counter.
        self._remaining_cycles -= 1
        return self.is_set()

    def set(self):
        self._remaining_cycles = 0


class MockConfigManager:
    def __init__(self, monitored_path: Path, config_dir: Path):
        self._monitored_path = monitored_path
        self._config_dir = config_dir

    def get_monitored_folders(self):
        return [{
            'path': str(self._monitored_path),
            'age_days': 0,
            'pattern': '*.txt',
            'use_regex': False,
            'action': 'move'
        }]

    def get_dry_run_mode(self):
        return True

    def get_archive_path_template(self):
        return "{YYYY}/{MM}/{DD}"

    def get_excluded_folders(self):
        return []

    def get_schedule_config(self):
        return {'interval_minutes': 0}

    def get_config_dir_path(self):
        return self._config_dir

    def get_notification_level(self):
        return NOTIFICATION_LEVEL_ALL


class TestMonitoringWorkerRunIds(TestCase):

    def test_consecutive_scans_generate_distinct_run_ids(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_path = Path(tmp_dir)
            monitored_path = base_path / "monitored"
            config_dir = base_path / "config"

            monitored_path.mkdir()
            config_dir.mkdir()

            target_file = monitored_path / "example.txt"
            target_file.write_text("sample")

            config_manager = MockConfigManager(monitored_path, config_dir)
            log_queue = queue.Queue()
            worker = MonitoringWorker(config_manager, log_queue)

            # Replace the stop event so we can deterministically end after two cycles.
            worker._stop_event = ControlledStopEvent(cycles=2)

            # Spy on history logging to capture run IDs used for each cycle.
            history_log_mock = MagicMock()
            worker.history_manager.log_action = history_log_mock

            generated_run_ids = [
                uuid.UUID("11111111-1111-1111-1111-111111111111"),
                uuid.UUID("22222222-2222-2222-2222-222222222222")
            ]

            with patch('worker.uuid.uuid4', side_effect=generated_run_ids):
                worker.run()

            # Each scan should log at least one action containing the run ID for that cycle.
            self.assertEqual(history_log_mock.call_count, 2)

            logged_run_ids = [call.args[0]['run_id'] for call in history_log_mock.call_args_list]
            expected_run_ids = [str(value) for value in generated_run_ids]

            self.assertEqual(logged_run_ids, expected_run_ids)
            self.assertNotEqual(logged_run_ids[0], logged_run_ids[1])


if __name__ == '__main__':
    import unittest
    unittest.main()
