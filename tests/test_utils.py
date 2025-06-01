import unittest
from unittest.mock import patch, MagicMock, mock_open, call
from pathlib import Path
from datetime import datetime, timedelta
import sys
import re

from utils import check_file, process_file_action

class TestCheckFile(unittest.TestCase):
    def setUp(self):
        self.mock_file_path = MagicMock(spec=Path)
        self.mock_file_path.name = "test_file.txt" # Default name for some tests
        # Configure the stat mock directly on the instance for tests that use it.
        # Each test method that relies on stat() will set up its specific return value or side_effect.
        self.mock_stat_result = MagicMock()
        self.mock_file_path.stat.return_value = self.mock_stat_result

    # No global patch for Path.stat needed here anymore if we configure self.mock_file_path.stat in each test
    def test_age_days_greater_than_match(self):
        self.mock_stat_result.st_mtime = (datetime.now() - timedelta(days=20)).timestamp()
        conditions = [{'field': 'age_days', 'operator': 'greater_than', 'value': 10}]
        self.assertTrue(check_file(self.mock_file_path, conditions, 'AND', None, None))

    def test_age_days_less_than_no_match(self):
        self.mock_stat_result.st_mtime = (datetime.now() - timedelta(days=5)).timestamp()
        conditions = [{'field': 'age_days', 'operator': 'greater_than', 'value': 10}]
        self.assertFalse(check_file(self.mock_file_path, conditions, 'AND', None, None))

    def test_filename_pattern_fnmatch_match(self):
        self.mock_file_path.name = "report_final.pdf"
        conditions = [{'field': 'filename_pattern', 'operator': 'matches_pattern', 'value': "*.pdf", 'use_regex': False}]
        self.assertTrue(check_file(self.mock_file_path, conditions, 'AND', None, None))

    @patch('utils.re.fullmatch')
    def test_filename_pattern_regex_match(self, mock_re_fullmatch):
        self.mock_file_path.name = "Invoice_12345.docx"
        mock_re_fullmatch.return_value = MagicMock()
        conditions = [{'field': 'filename_pattern', 'operator': 'matches_pattern', 'value': r"Invoice_\d+\.docx", 'use_regex': True}]
        self.assertTrue(check_file(self.mock_file_path, conditions, 'AND', None, None))
        mock_re_fullmatch.assert_called_with(r"Invoice_\d+\.docx", "Invoice_12345.docx")

    @patch('utils.re.fullmatch')
    def test_filename_pattern_regex_no_match(self, mock_re_fullmatch):
        self.mock_file_path.name = "Summary_Report.xlsx"
        mock_re_fullmatch.return_value = None
        conditions = [{'field': 'filename_pattern', 'operator': 'matches_pattern', 'value': r"Invoice_\d+\.docx", 'use_regex': True}]
        self.assertFalse(check_file(self.mock_file_path, conditions, 'AND', None, None))

    def test_mime_type_equals_match(self):
        conditions = [{'field': 'mime_type', 'operator': 'equals', 'value': 'application/pdf'}]
        self.assertTrue(check_file(self.mock_file_path, conditions, 'AND', 'application/pdf', None))

    def test_mime_type_starts_with_match(self):
        conditions = [{'field': 'mime_type', 'operator': 'starts_with', 'value': 'image/'}]
        self.assertTrue(check_file(self.mock_file_path, conditions, 'AND', 'image/jpeg', None))

    def test_mime_type_no_match_if_file_mime_is_none(self):
        conditions = [{'field': 'mime_type', 'operator': 'equals', 'value': 'application/pdf'}]
        self.assertFalse(check_file(self.mock_file_path, conditions, 'AND', None, None))

    def test_tag_contains_match(self):
        conditions = [{'field': 'tag', 'operator': 'contains', 'value': 'important'}]
        self.assertTrue(check_file(self.mock_file_path, conditions, 'AND', None, ['invoice', 'important', 'finance']))

    def test_tag_not_contains_is_true_when_tag_absent(self):
        conditions = [{'field': 'tag', 'operator': 'not_contains', 'value': 'draft'}]
        self.assertTrue(check_file(self.mock_file_path, conditions, 'AND', None, ['invoice', 'final']))

    def test_tag_no_match_if_file_tags_is_none(self):
        conditions = [{'field': 'tag', 'operator': 'contains', 'value': 'important'}]
        self.assertFalse(check_file(self.mock_file_path, conditions, 'AND', None, None))

    def test_and_logic_all_match(self):
        self.mock_stat_result.st_mtime = (datetime.now() - timedelta(days=15)).timestamp()
        self.mock_file_path.name = "project_alpha.doc"
        conditions = [
            {'field': 'age_days', 'operator': 'greater_than', 'value': 10},
            {'field': 'filename_pattern', 'operator': 'matches_pattern', 'value': "project_*.doc"},
            {'field': 'tag', 'operator': 'contains', 'value': 'alpha'}
        ]
        self.assertTrue(check_file(self.mock_file_path, conditions, 'AND', "application/msword", ['alpha', 'confidential']))

    def test_and_logic_one_no_match(self):
        self.mock_stat_result.st_mtime = (datetime.now() - timedelta(days=5)).timestamp()
        self.mock_file_path.name = "project_alpha.doc" # This part matches for the 2nd condition
        conditions = [
            {'field': 'age_days', 'operator': 'greater_than', 'value': 10}, # 5 > 10 is False
            {'field': 'filename_pattern', 'operator': 'matches_pattern', 'value': "project_*.doc"}, # True
        ]
        # Expected: age_days -> False. filename_pattern -> True. AND logic -> False.
        self.assertFalse(check_file(self.mock_file_path, conditions, 'AND', None, None))

    def test_or_logic_one_match(self):
        self.mock_stat_result.st_mtime = (datetime.now() - timedelta(days=5)).timestamp()
        self.mock_file_path.name = "archive_old.zip"
        conditions = [
            {'field': 'age_days', 'operator': 'greater_than', 'value': 10}, # 5 > 10 is False
            {'field': 'filename_pattern', 'operator': 'matches_pattern', 'value': "*.zip"}, # True
            {'field': 'tag', 'operator': 'contains', 'value': 'backup'} # False (tags=None)
        ]
        self.assertTrue(check_file(self.mock_file_path, conditions, 'OR', "application/zip", None))

    def test_or_logic_all_no_match(self):
        self.mock_stat_result.st_mtime = (datetime.now() - timedelta(days=2)).timestamp()
        self.mock_file_path.name = "image.png"
        conditions = [
            {'field': 'age_days', 'operator': 'greater_than', 'value': 5}, # 2 > 5 is False
            {'field': 'filename_pattern', 'operator': 'matches_pattern', 'value': "*.txt"} # False
        ]
        self.assertFalse(check_file(self.mock_file_path, conditions, 'OR', "image/png", ["photo"]))

    def test_no_conditions(self):
        self.assertFalse(check_file(self.mock_file_path, [], 'AND', None, None))

    def test_file_not_found_exception(self):
        # Configure the mock_file_path's stat method to raise FileNotFoundError for this test
        self.mock_file_path.stat.side_effect = FileNotFoundError
        conditions = [{'field': 'age_days', 'operator': 'greater_than', 'value': 10}]
        self.assertFalse(check_file(self.mock_file_path, conditions, 'AND', None, None))


class TestProcessFileAction(unittest.TestCase):
    def setUp(self):
        self.mock_file_path = MagicMock(spec=Path)
        self.mock_file_path.name = "test_doc.pdf"
        self.mock_file_path.stem = "test_doc"
        self.mock_file_path.suffix = ".pdf"
        self.mock_file_path.__str__ = MagicMock(return_value="MonitoredFolder/test_doc.pdf")

        self.mock_monitored_folder_path = MagicMock(spec=Path)
        self.mock_monitored_folder_path.name = "MonitoredFolder"
        self.mock_monitored_folder_path.__str__ = MagicMock(return_value="MonitoredFolder")
        self.mock_monitored_folder_path.__truediv__ = lambda s, other: Path(f"{str(s)}/{str(other)}")


        self.mock_history_logger = MagicMock()
        self.run_id = "test_run_123"
        self.archive_template_with_tags = "_Archive/{TAGS}/{YYYY}/{FILENAME}"
        self.archive_template_basic = "_Archive/{YYYY}-{MM}-{DD}"


    @patch('utils.shutil.move')
    @patch('utils.Path.mkdir')
    @patch('utils.Path.exists', return_value=False)
    def test_action_move_no_collision_with_tags(self, mock_path_exists, mock_mkdir, mock_shutil_move):
        rule = {'name': 'Move PDFs with Tags', 'action': 'move'}
        tags = ["invoice", "urgent"]

        success, msg = process_file_action(
            self.mock_file_path, self.mock_monitored_folder_path,
            self.archive_template_with_tags, "move", False, rule,
            self.mock_history_logger, self.run_id, tags
        )
        self.assertTrue(success)
        self.assertIn("Moved", msg)
        self.assertIn("invoice_urgent", msg)
        mock_shutil_move.assert_called_once()
        args, _ = mock_shutil_move.call_args
        self.assertIn("invoice_urgent", str(args[1]))
        self.mock_history_logger.assert_called_once()

    @patch('utils.shutil.copy2')
    @patch('utils.Path.mkdir')
    @patch('utils.Path.exists', return_value=False)
    def test_action_copy_dry_run_no_tags_in_template(self, mock_path_exists, mock_mkdir, mock_shutil_copy):
        rule = {'name': 'Copy Docs - Basic Template'}
        tags = ["report", "final"]

        success, msg = process_file_action(
            self.mock_file_path, self.mock_monitored_folder_path,
            self.archive_template_basic, "copy", True, rule,
            self.mock_history_logger, self.run_id, tags
        )
        self.assertTrue(success)
        self.assertIn("[DRY RUN] Would copy", msg)
        self.assertNotIn("report_final", msg)
        self.assertNotIn("untagged", msg)
        mock_shutil_copy.assert_not_called()
        self.mock_history_logger.assert_called_once()


    @patch('utils.send2trash.send2trash')
    def test_action_delete_to_trash(self, mock_send2trash):
        rule = {'name': 'Trash old files'}
        success, msg = process_file_action(
            self.mock_file_path, self.mock_monitored_folder_path,
            "", "delete_to_trash", False, rule,
            self.mock_history_logger, self.run_id, None
        )
        self.assertTrue(success)
        self.assertIn("Sent to trash", msg)
        mock_send2trash.assert_called_once_with(str(self.mock_file_path))
        self.mock_history_logger.assert_called_once()

    @patch('utils.os.remove')
    def test_action_delete_permanently_dry_run(self, mock_os_remove):
        rule = {'name': 'Delete temp files'}
        success, msg = process_file_action(
            self.mock_file_path, self.mock_monitored_folder_path,
            "", "delete_permanently", True, rule,
            self.mock_history_logger, self.run_id, None
        )
        self.assertTrue(success)
        self.assertIn("[DRY RUN] Would permanently delete", msg)
        mock_os_remove.assert_not_called()
        self.mock_history_logger.assert_called_once()

    @patch('utils.Path.mkdir')
    @patch('utils.Path.exists')
    @patch('utils.shutil.move')
    def test_action_move_with_collision(self, mock_shutil_move, mock_path_exists, mock_mkdir):
        mock_path_exists.side_effect = [True, False]

        rule = {'name': 'Move with collision test'}
        tags = ["archive"]

        current_mock_file = MagicMock(spec=Path)
        current_mock_file.name = "file_to_move.txt"
        current_mock_file.stem = "file_to_move"
        current_mock_file.suffix = ".txt"
        current_mock_file.__str__ = MagicMock(return_value="MonitoredFolder/file_to_move.txt")

        archive_template_simple = "_Archive/{TAGS}"

        success, msg = process_file_action(
            current_mock_file, self.mock_monitored_folder_path,
            archive_template_simple, "move", False, rule,
            self.mock_history_logger, self.run_id, tags
        )
        self.assertTrue(success)
        self.assertIn("_1.txt", msg)
        mock_shutil_move.assert_called_once()
        args, _ = mock_shutil_move.call_args
        self.assertTrue(str(args[1]).endswith("file_to_move_1.txt"))

    def test_tags_in_path_sanitization_and_untagged(self):
        rule = {'name': 'Tag Path Test'}

        tags_special = ["text_Report Q1!", "mime_application/pdf", "image_dim_100x100"]

        with patch('utils.shutil.copy2'), patch('utils.Path.mkdir'), \
             patch('utils.Path.exists', return_value=False):

            success_special, msg_special = process_file_action(
                self.mock_file_path, self.mock_monitored_folder_path,
                "_Archive/{TAGS}/{FILENAME}", "copy", True, rule,
                self.mock_history_logger, self.run_id, tags_special
            )
            self.assertTrue(success_special)
            self.assertIn("Report_Q1__application_pdf_dim_100x100", msg_special)
            self.assertNotIn("!", msg_special)

            self.mock_history_logger.reset_mock()

            tags_none = []
            success_none, msg_none = process_file_action(
                self.mock_file_path, self.mock_monitored_folder_path,
                "_Archive/{TAGS}/{FILENAME}", "copy", True, rule,
                self.mock_history_logger, self.run_id, tags_none
            )
            self.assertTrue(success_none)
            self.assertIn("/untagged/", msg_none)

            self.mock_history_logger.reset_mock()

            success_really_none, msg_really_none = process_file_action(
                self.mock_file_path, self.mock_monitored_folder_path,
                "_Archive/{TAGS}/{FILENAME}", "copy", True, rule,
                self.mock_history_logger, self.run_id, None
            )
            self.assertTrue(success_really_none)
            self.assertIn("/untagged/", msg_really_none)

if __name__ == '__main__':
    unittest.main()
