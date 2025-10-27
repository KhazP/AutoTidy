import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from utils import process_file_action


class TestProcessFileActionDestinations(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.monitored_path = Path(self.temp_dir.name)
        self.history_logs = []

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_file(self, name: str, content: str = "data") -> Path:
        file_path = self.monitored_path / name
        file_path.write_text(content, encoding="utf-8")
        return file_path

    def _history_logger(self, entry: dict):
        self.history_logs.append(entry)

    def test_move_uses_default_archive_template_when_destination_empty(self):
        file_path = self._create_file("move_default.txt")
        now = datetime.now()
        year = now.strftime("%Y")
        month = now.strftime("%m")
        day = now.strftime("%d")

        success, message = process_file_action(
            file_path,
            self.monitored_path,
            "_Cleanup/{YYYY}-{MM}-{DD}",
            "move",
            False,
            "*.*",
            0,
            False,
            self._history_logger,
            "run-default-move",
            "",
        )

        expected_dir = self.monitored_path / "_Cleanup" / f"{year}-{month}-{day}"
        expected_file = expected_dir / "move_default.txt"

        self.assertTrue(success, message)
        self.assertFalse(file_path.exists(), "Original file should be moved")
        self.assertTrue(expected_file.exists(), "Moved file should exist in archive template destination")
        expected_relative = expected_file.relative_to(self.monitored_path)
        self.assertIn(str(expected_relative), message)
        self.assertGreater(len(self.history_logs), 0)
        self.assertEqual(str(expected_file), self.history_logs[-1]["destination_path"])

    def test_copy_uses_default_archive_template_when_destination_empty(self):
        file_path = self._create_file("copy_default.txt", content="sample")
        now = datetime.now()
        year = now.strftime("%Y")
        month = now.strftime("%m")
        day = now.strftime("%d")

        success, message = process_file_action(
            file_path,
            self.monitored_path,
            "_Cleanup/{YYYY}-{MM}-{DD}",
            "copy",
            False,
            "*.*",
            0,
            False,
            self._history_logger,
            "run-default-copy",
            None,
        )

        expected_dir = self.monitored_path / "_Cleanup" / f"{year}-{month}-{day}"
        expected_file = expected_dir / "copy_default.txt"

        self.assertTrue(success, message)
        self.assertTrue(file_path.exists(), "Original file should remain after copy")
        self.assertTrue(expected_file.exists(), "Copied file should exist in archive template destination")
        self.assertEqual(file_path.read_text(encoding="utf-8"), expected_file.read_text(encoding="utf-8"))
        expected_relative = expected_file.relative_to(self.monitored_path)
        self.assertIn(str(expected_relative), message)
        self.assertGreater(len(self.history_logs), 0)
        self.assertEqual(str(expected_file), self.history_logs[-1]["destination_path"])

    def test_move_to_custom_destination_relative_path(self):
        file_path = self._create_file("move_custom.txt")
        now = datetime.now()
        year = now.strftime("%Y")

        success, message = process_file_action(
            file_path,
            self.monitored_path,
            "_Cleanup/{YYYY}-{MM}-{DD}",
            "move",
            False,
            "*.*",
            0,
            False,
            self._history_logger,
            "run-custom-move",
            "custom_archive/{YYYY}",
        )

        expected_dir = self.monitored_path / "custom_archive" / year
        expected_file = expected_dir / "move_custom.txt"

        self.assertTrue(success, message)
        self.assertFalse(file_path.exists(), "Original file should be moved to custom destination")
        self.assertTrue(expected_file.exists(), "Moved file should exist in custom destination")
        self.assertTrue(expected_dir.is_dir())
        expected_relative = expected_file.relative_to(self.monitored_path)
        self.assertIn(str(expected_relative), message)
        self.assertGreater(len(self.history_logs), 0)
        self.assertEqual(str(expected_file), self.history_logs[-1]["destination_path"])

    def test_copy_to_custom_destination_with_env_var(self):
        file_path = self._create_file("copy_custom.txt", content="env-data")
        dest_dir_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(dest_dir_ctx.cleanup)
        os.environ["AUTO_TIDY_DEST"] = dest_dir_ctx.name
        self.addCleanup(lambda: os.environ.pop("AUTO_TIDY_DEST", None))
        now = datetime.now()
        month = now.strftime("%m")

        success, message = process_file_action(
            file_path,
            self.monitored_path,
            "_Cleanup/{YYYY}-{MM}-{DD}",
            "copy",
            False,
            "*.*",
            0,
            False,
            self._history_logger,
            "run-custom-copy",
            "$AUTO_TIDY_DEST/custom/{MM}",
        )

        expected_dir = Path(dest_dir_ctx.name) / "custom" / month
        expected_file = expected_dir / "copy_custom.txt"

        self.assertTrue(success, message)
        self.assertTrue(file_path.exists(), "Original file should remain after copy to custom destination")
        self.assertTrue(expected_file.exists(), "Copied file should exist in environment-derived destination")
        self.assertEqual(file_path.read_text(encoding="utf-8"), expected_file.read_text(encoding="utf-8"))
        self.assertTrue(expected_dir.is_dir())
        self.assertIn(str(expected_file), message)
        self.assertGreater(len(self.history_logs), 0)
        self.assertEqual(str(expected_file), self.history_logs[-1]["destination_path"])


if __name__ == "__main__":
    unittest.main()
