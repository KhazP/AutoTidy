import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
from datetime import datetime, timedelta
import sys
import os

# Add the parent directory to sys.path to allow imports from the main project
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils import check_file, move_file

class TestUtils(unittest.TestCase):

    def setUp(self):
        # Create a dummy file for testing
        self.test_dir = Path("test_utils_temp_dir")
        self.test_dir.mkdir(exist_ok=True)
        self.test_file = self.test_dir / "test_file.txt"
        with open(self.test_file, "w") as f:
            f.write("test content")

        # Set modification time for age tests (e.g., 10 days ago)
        ten_days_ago_ts = (datetime.now() - timedelta(days=10)).timestamp()
        os.utime(self.test_file, (ten_days_ago_ts, ten_days_ago_ts))

    def tearDown(self):
        # Clean up the dummy file and directory
        if self.test_file.exists():
            self.test_file.unlink()
        if self.test_dir.exists():
            self.test_dir.rmdir()

    # Tests for check_file
    # --- OR Logic Tests (Glob) ---
    def test_check_file_or_logic_age_match_only_glob(self):
        # File is older (age_days=5), pattern doesn't match. OR logic -> True
        self.assertTrue(check_file(self.test_file, age_days=5, pattern="*.log", rule_logic="OR", pattern_type="glob"))

    def test_check_file_or_logic_pattern_match_only_glob(self):
        # File age doesn't match (age_days=20), pattern matches. OR logic -> True
        self.assertTrue(check_file(self.test_file, age_days=20, pattern="test_*.txt", rule_logic="OR", pattern_type="glob"))

    def test_check_file_or_logic_both_match_glob(self):
        # File age matches (age_days=5), pattern matches. OR logic -> True
        self.assertTrue(check_file(self.test_file, age_days=5, pattern="test_*.txt", rule_logic="OR", pattern_type="glob"))

    def test_check_file_or_logic_neither_match_glob(self):
        # File age doesn't match (age_days=20), pattern doesn't match. OR logic -> False
        self.assertFalse(check_file(self.test_file, age_days=20, pattern="*.log", rule_logic="OR", pattern_type="glob"))

    def test_check_file_or_logic_age_zero_pattern_match_glob(self):
        # age_days is 0, pattern matches. OR logic -> True
        self.assertTrue(check_file(self.test_file, age_days=0, pattern="test_*.txt", rule_logic="OR", pattern_type="glob"))

    def test_check_file_or_logic_age_zero_pattern_mismatch_glob(self):
        # age_days is 0, pattern doesn't match. OR logic -> False (effectively only checks pattern)
        self.assertFalse(check_file(self.test_file, age_days=0, pattern="*.log", rule_logic="OR", pattern_type="glob"))

    def test_check_file_or_logic_empty_pattern_age_match_glob(self):
        # pattern is empty, age matches. OR logic -> True
        self.assertTrue(check_file(self.test_file, age_days=5, pattern="", rule_logic="OR", pattern_type="glob"))

    def test_check_file_or_logic_empty_pattern_age_mismatch_glob(self):
        # pattern is empty, age doesn't match. OR logic -> False (effectively only checks age)
        self.assertFalse(check_file(self.test_file, age_days=20, pattern="", rule_logic="OR", pattern_type="glob"))

    # --- AND Logic Tests (Glob) ---
    def test_check_file_and_logic_both_match_glob(self):
        # File age matches (age_days=5), pattern matches. AND logic -> True
        self.assertTrue(check_file(self.test_file, age_days=5, pattern="test_*.txt", rule_logic="AND", pattern_type="glob"))

    def test_check_file_and_logic_age_match_pattern_mismatch_glob(self):
        # File age matches (age_days=5), pattern doesn't match. AND logic -> False
        self.assertFalse(check_file(self.test_file, age_days=5, pattern="*.log", rule_logic="AND", pattern_type="glob"))

    def test_check_file_and_logic_age_mismatch_pattern_match_glob(self):
        # File age doesn't match (age_days=20), pattern matches. AND logic -> False
        self.assertFalse(check_file(self.test_file, age_days=20, pattern="test_*.txt", rule_logic="AND", pattern_type="glob"))

    def test_check_file_and_logic_neither_match_glob(self):
        # File age doesn't match (age_days=20), pattern doesn't match. AND logic -> False
        self.assertFalse(check_file(self.test_file, age_days=20, pattern="*.log", rule_logic="AND", pattern_type="glob"))

    def test_check_file_and_logic_age_zero_pattern_match_glob(self):
        # age_days is 0, pattern matches. AND logic -> True (effectively only checks pattern)
        self.assertTrue(check_file(self.test_file, age_days=0, pattern="test_*.txt", rule_logic="AND", pattern_type="glob"))

    def test_check_file_and_logic_age_zero_pattern_mismatch_glob(self):
        # age_days is 0, pattern doesn't match. AND logic -> False
        self.assertFalse(check_file(self.test_file, age_days=0, pattern="*.log", rule_logic="AND", pattern_type="glob"))

    def test_check_file_and_logic_empty_pattern_age_match_glob(self):
        # pattern is empty, age matches. AND logic -> True (effectively only checks age)
        self.assertTrue(check_file(self.test_file, age_days=5, pattern="", rule_logic="AND", pattern_type="glob"))

    def test_check_file_and_logic_empty_pattern_age_mismatch_glob(self):
        # pattern is empty, age doesn't match. AND logic -> False
        self.assertFalse(check_file(self.test_file, age_days=20, pattern="", rule_logic="AND", pattern_type="glob"))

    # --- OR Logic Tests (Regex) ---
    def test_check_file_or_logic_age_match_only_regex(self):
        self.assertTrue(check_file(self.test_file, age_days=5, pattern=r"non_matching_regex\.log", rule_logic="OR", pattern_type="regex"))

    def test_check_file_or_logic_pattern_match_only_regex(self):
        self.assertTrue(check_file(self.test_file, age_days=20, pattern=r"^test_file\.txt$", rule_logic="OR", pattern_type="regex"))

    def test_check_file_or_logic_both_match_regex(self):
        self.assertTrue(check_file(self.test_file, age_days=5, pattern=r"^test_file\.txt$", rule_logic="OR", pattern_type="regex"))

    def test_check_file_or_logic_neither_match_regex(self):
        self.assertFalse(check_file(self.test_file, age_days=20, pattern=r"non_matching_regex\.log", rule_logic="OR", pattern_type="regex"))

    def test_check_file_or_logic_age_zero_pattern_match_regex(self):
        self.assertTrue(check_file(self.test_file, age_days=0, pattern=r"^test_file\.txt$", rule_logic="OR", pattern_type="regex"))

    def test_check_file_or_logic_age_zero_pattern_mismatch_regex(self):
        self.assertFalse(check_file(self.test_file, age_days=0, pattern=r"non_matching_regex\.log", rule_logic="OR", pattern_type="regex"))

    def test_check_file_or_logic_empty_pattern_age_match_regex(self): # Empty regex is no pattern match
        self.assertTrue(check_file(self.test_file, age_days=5, pattern="", rule_logic="OR", pattern_type="regex"))

    def test_check_file_or_logic_empty_pattern_age_mismatch_regex(self): # Empty regex is no pattern match
        self.assertFalse(check_file(self.test_file, age_days=20, pattern="", rule_logic="OR", pattern_type="regex"))

    # --- AND Logic Tests (Regex) ---
    def test_check_file_and_logic_both_match_regex(self):
        self.assertTrue(check_file(self.test_file, age_days=5, pattern=r"^test_file\.txt$", rule_logic="AND", pattern_type="regex"))

    def test_check_file_and_logic_age_match_pattern_mismatch_regex(self):
        self.assertFalse(check_file(self.test_file, age_days=5, pattern=r"non_matching_regex\.log", rule_logic="AND", pattern_type="regex"))

    def test_check_file_and_logic_age_mismatch_pattern_match_regex(self):
        self.assertFalse(check_file(self.test_file, age_days=20, pattern=r"^test_file\.txt$", rule_logic="AND", pattern_type="regex"))

    def test_check_file_and_logic_neither_match_regex(self):
        self.assertFalse(check_file(self.test_file, age_days=20, pattern=r"non_matching_regex\.log", rule_logic="AND", pattern_type="regex"))

    def test_check_file_and_logic_age_zero_pattern_match_regex(self):
        self.assertTrue(check_file(self.test_file, age_days=0, pattern=r"^test_file\.txt$", rule_logic="AND", pattern_type="regex"))

    def test_check_file_and_logic_age_zero_pattern_mismatch_regex(self):
        self.assertFalse(check_file(self.test_file, age_days=0, pattern=r"non_matching_regex\.log", rule_logic="AND", pattern_type="regex"))

    def test_check_file_and_logic_empty_pattern_age_match_regex(self): # Empty regex is no pattern match
        self.assertTrue(check_file(self.test_file, age_days=5, pattern="", rule_logic="AND", pattern_type="regex"))

    def test_check_file_and_logic_empty_pattern_age_mismatch_regex(self): # Empty regex is no pattern match
        self.assertFalse(check_file(self.test_file, age_days=20, pattern="", rule_logic="AND", pattern_type="regex"))

    # --- Regex Specific Tests ---
    def test_check_file_regex_invalid_pattern(self):
        # Invalid regex should not crash, should log an error (mocked), and result in no match.
        with patch('sys.stderr', new_callable=MagicMock) as mock_stderr:
            # OR logic, age doesn't match, pattern is invalid -> False
            self.assertFalse(check_file(self.test_file, age_days=20, pattern="([", rule_logic="OR", pattern_type="regex"))
            self.assertTrue(any("Error: Invalid regex pattern" in call.args[0] for call in mock_stderr.write.call_args_list))

            # AND logic, age matches, pattern is invalid -> False
            mock_stderr.reset_mock() # Reset mock for the next check
            self.assertFalse(check_file(self.test_file, age_days=5, pattern="([", rule_logic="AND", pattern_type="regex"))
            self.assertTrue(any("Error: Invalid regex pattern" in call.args[0] for call in mock_stderr.write.call_args_list))

    # --- General Tests ---
    def test_check_file_file_not_found(self): # Added pattern_type to existing test
        non_existent_file = Path("non_existent_file.txt")
        with patch('sys.stderr', new_callable=MagicMock) as mock_stderr_or_glob:
            self.assertFalse(check_file(non_existent_file, age_days=1, pattern="*.*", rule_logic="OR", pattern_type="glob"))
            self.assertTrue(any("Warning: File not found during check" in call.args[0] for call in mock_stderr_or_glob.write.call_args_list))

        with patch('sys.stderr', new_callable=MagicMock) as mock_stderr_and_glob:
            self.assertFalse(check_file(non_existent_file, age_days=1, pattern="*.*", rule_logic="AND", pattern_type="glob"))
            self.assertTrue(any("Warning: File not found during check" in call.args[0] for call in mock_stderr_and_glob.write.call_args_list))

        with patch('sys.stderr', new_callable=MagicMock) as mock_stderr_or_regex:
            self.assertFalse(check_file(non_existent_file, age_days=1, pattern=".*", rule_logic="OR", pattern_type="regex")) # Basic regex pattern
            self.assertTrue(any("Warning: File not found during check" in call.args[0] for call in mock_stderr_or_regex.write.call_args_list))

        with patch('sys.stderr', new_callable=MagicMock) as mock_stderr_and_regex:
            self.assertFalse(check_file(non_existent_file, age_days=1, pattern=".*", rule_logic="AND", pattern_type="regex"))
            self.assertTrue(any("Warning: File not found during check" in call.args[0] for call in mock_stderr_and_regex.write.call_args_list))


    # Tests for move_file
    @patch('shutil.move')
    @patch('pathlib.Path.mkdir')
    def test_move_file_success(self, mock_mkdir, mock_shutil_move):
        monitored_folder = self.test_dir
        archive_format = "%Y-%m-%d"
        success, message = move_file(self.test_file, monitored_folder, archive_format)
        self.assertTrue(success)
        expected_date_str = datetime.now().strftime(archive_format)
        self.assertIn(f"Moved: {self.test_file.name} -> _Cleanup/{expected_date_str}/", message)
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_shutil_move.assert_called_once()
        # Check that the target path for shutil.move is correct
        moved_to_path = Path(mock_shutil_move.call_args[0][1])
        self.assertEqual(moved_to_path.parent.name, expected_date_str)
        self.assertEqual(moved_to_path.parent.parent.name, "_Cleanup")

    @patch('shutil.move', side_effect=PermissionError("Test permission error"))
    @patch('pathlib.Path.mkdir')
    def test_move_file_permission_error(self, mock_mkdir, mock_shutil_move):
        monitored_folder = self.test_dir
        success, message = move_file(self.test_file, monitored_folder, "%Y-%m-%d")
        self.assertFalse(success)
        self.assertIn("Error: Permission denied", message)

    @patch('shutil.move')
    @patch('pathlib.Path.mkdir')
    @patch('pathlib.Path.exists', side_effect=[True, True, False]) # Simulate 2 collisions
    def test_move_file_name_collision(self, mock_path_exists, mock_mkdir, mock_shutil_move):
        monitored_folder = self.test_dir
        archive_format = "%Y-%m-%d"
        success, message = move_file(self.test_file, monitored_folder, archive_format)
        self.assertTrue(success)
        expected_date_str = datetime.now().strftime(archive_format)
        self.assertIn(f"Moved: {self.test_file.name} -> _Cleanup/{expected_date_str}/", message)
        # Check that the final path has "_2" in it (original, _1, _2)
        final_target_path = Path(mock_shutil_move.call_args[0][1])
        self.assertTrue("_2" in final_target_path.name)
        self.assertEqual(final_target_path.parent.name, expected_date_str)

    @patch('shutil.move')
    @patch('pathlib.Path.mkdir')
    def test_move_file_custom_archive_format(self, mock_mkdir, mock_shutil_move):
        monitored_folder = self.test_dir
        custom_format = "%Y/custom_%b/%d_test" # e.g., 2023/custom_Oct/15_test
        success, message = move_file(self.test_file, monitored_folder, custom_format)
        self.assertTrue(success)

        expected_subpath = datetime.now().strftime(custom_format)
        self.assertIn(f"Moved: {self.test_file.name} -> _Cleanup/{expected_subpath}/", message)

        # Check that shutil.move was called with a path reflecting this custom structure
        moved_to_path = Path(mock_shutil_move.call_args[0][1])
        # Example: .../_Cleanup/2023/custom_Oct/15_test/test_file.txt
        # moved_to_path.parent.name should be '15_test'
        # moved_to_path.parent.parent.name should be 'custom_Oct'
        # moved_to_path.parent.parent.parent.name should be '2023'
        # moved_to_path.parent.parent.parent.parent.name should be '_Cleanup'

        # We can check parts of the expected path
        path_parts = expected_subpath.split(os.path.sep)
        current_path_segment = moved_to_path.parent
        for part in reversed(path_parts):
            self.assertEqual(current_path_segment.name, part)
            current_path_segment = current_path_segment.parent
        self.assertEqual(current_path_segment.name, "_Cleanup")
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

    @patch('shutil.move')
    @patch('pathlib.Path.mkdir')
    @patch('sys.stderr', new_callable=MagicMock)
    def test_move_file_invalid_archive_format(self, mock_stderr, mock_mkdir, mock_shutil_move):
        monitored_folder = self.test_dir
        invalid_format = "%Y/%invalid/%d"
        success, message = move_file(self.test_file, monitored_folder, invalid_format)

        self.assertTrue(success) # Should still succeed by falling back to default
        self.assertTrue(any("Warning: Invalid archive_format_string" in call.args[0] for call in mock_stderr.write.call_args_list))

        # Check that shutil.move was called with a path reflecting the default format
        default_format_date_str = datetime.now().strftime("%Y-%m-%d")
        self.assertIn(f"Moved: {self.test_file.name} -> _Cleanup/{default_format_date_str}/", message)
        moved_to_path = Path(mock_shutil_move.call_args[0][1])
        self.assertEqual(moved_to_path.parent.name, default_format_date_str)

if __name__ == '__main__':
    unittest.main()
