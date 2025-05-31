import unittest
from unittest.mock import patch, mock_open, MagicMock
import json
import os
import sys
from pathlib import Path

# Add the parent directory to sys.path to allow imports from the main project
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config_manager import ConfigManager

class TestConfigManager(unittest.TestCase):

    def setUp(self):
        self.app_name = "TestApp"
        # Mock Path methods for consistent testing environment
        self.mock_home_dir = Path("/fake/home")
        self.mock_appdata_dir = Path("/fake/appdata")

        # Patch 'Path.home' and 'os.getenv' to control config directory resolution
        self.patch_path_home = patch('pathlib.Path.home', return_value=self.mock_home_dir)
        self.patch_os_getenv = patch('os.getenv')

        self.mock_path_home = self.patch_path_home.start()
        self.mock_os_getenv = self.patch_os_getenv.start()

        # Default to Linux-like environment for Path.home()
        self.mock_os_getenv.return_value = None # APPDATA not set

        # Ensure Path.mkdir is also patched if it's called within __init__ indirectly
        self.patch_path_mkdir = patch('pathlib.Path.mkdir', return_value=None)
        self.mock_path_mkdir = self.patch_path_mkdir.start()

    def tearDown(self):
        self.patch_path_home.stop()
        self.patch_os_getenv.stop()
        self.patch_path_mkdir.stop()

    def _get_expected_config_path(self, app_name, is_windows=False):
        if is_windows:
            return self.mock_appdata_dir / app_name / "config.json"
        else:
            return self.mock_home_dir / ".config" / app_name / "config.json"

    def test_config_dir_linux(self):
        # Simulate Linux environment (APPDATA is None)
        self.mock_os_getenv.return_value = None
        cm = ConfigManager(self.app_name)
        expected_dir = self.mock_home_dir / ".config" / self.app_name
        self.assertEqual(cm.config_dir, expected_dir)

    def test_config_dir_windows(self):
        # Simulate Windows environment
        with patch('sys.platform', 'win32'):
            self.mock_os_getenv.return_value = str(self.mock_appdata_dir)
            cm = ConfigManager(self.app_name)
            expected_dir = self.mock_appdata_dir / self.app_name
            self.assertEqual(cm.config_dir, expected_dir)
            self.mock_os_getenv.assert_called_with('APPDATA')


    @patch("builtins.open", new_callable=mock_open)
    @patch("json.load")
    def test_load_config_file_not_found(self, mock_json_load, mock_file_open):
        mock_file_open.side_effect = FileNotFoundError
        cm = ConfigManager(self.app_name)
        self.assertEqual(cm.config, cm.default_config)

    @patch("builtins.open", new_callable=mock_open, read_data='{"folders": [{"path": "/test/path", "age_days": 7, "pattern": "*.*", "rule_logic": "AND"}], "settings": {"check_interval_seconds": 1800}}')
    @patch("json.load")
    def test_load_config_valid_json(self, mock_json_load, mock_file_open):
        # json.load will be called with the file object from mock_open
        # We need it to return the actual parsed data
        valid_data = {"folders": [{"path": "/test/path", "age_days": 7, "pattern": "*.*", "rule_logic": "AND"}], "settings": {"check_interval_seconds": 1800, "start_on_login": False}} # Ensure all defaults are covered
        mock_json_load.return_value = valid_data

        cm = ConfigManager(self.app_name)

        # Check that open was called with the correct path
        expected_path = self._get_expected_config_path(self.app_name)
        mock_file_open.assert_called_once_with(expected_path, 'r')
        self.assertEqual(cm.config, valid_data)

    @patch("builtins.open", new_callable=mock_open, read_data='invalid json')
    @patch("json.load", side_effect=json.JSONDecodeError("Error", "doc", 0))
    def test_load_config_invalid_json(self, mock_json_load, mock_file_open):
        cm = ConfigManager(self.app_name)
        self.assertEqual(cm.config, cm.default_config)

    @patch("builtins.open", new_callable=mock_open)
    @patch("json.dump")
    def test_save_config(self, mock_json_dump, mock_file_open):
        cm = ConfigManager(self.app_name)
        cm.config = {"folders": [{"path": "/save/path", "age_days": 3, "pattern": "a.txt", "rule_logic": "OR"}], "settings": {"start_on_login": True, "check_interval_seconds": 300}}
        cm.save_config()

        expected_path = self._get_expected_config_path(self.app_name)
        mock_file_open.assert_called_once_with(expected_path, 'w')
        mock_json_dump.assert_called_once_with(cm.config, mock_file_open.return_value, indent=4)

    def test_add_folder(self):
        with patch.object(ConfigManager, 'save_config') as mock_save:
            cm = ConfigManager(self.app_name)
            cm.config = {'folders': [], 'settings': {}} # Start fresh
            self.assertTrue(cm.add_folder("/new/path", 10, "*.dat"))
            self.assertEqual(len(cm.config['folders']), 1)
            self.assertEqual(cm.config['folders'][0]['path'], "/new/path")
            self.assertEqual(cm.config['folders'][0]['rule_logic'], "OR") # Default logic
            mock_save.assert_called_once()

            # Try adding the same path again
            self.assertFalse(cm.add_folder("/new/path", 5, "*.*"))
            self.assertEqual(len(cm.config['folders']), 1) # Should not add

    def test_remove_folder(self):
        with patch.object(ConfigManager, 'save_config') as mock_save:
            cm = ConfigManager(self.app_name)
            cm.config = {'folders': [{'path': '/to/remove', 'age_days': 1, 'pattern': 'r.r', 'rule_logic': 'OR'}], 'settings': {}}
            self.assertTrue(cm.remove_folder("/to/remove"))
            self.assertEqual(len(cm.config['folders']), 0)
            mock_save.assert_called_once()

            # Try removing non-existent
            self.assertFalse(cm.remove_folder("/not/found"))

    def test_update_folder_rule(self):
        with patch.object(ConfigManager, 'save_config') as mock_save:
            cm = ConfigManager(self.app_name)
            cm.config = {'folders': [{'path': '/update/path', 'age_days': 1, 'pattern': 'old.pat', 'rule_logic': 'OR'}], 'settings': {}}
            self.assertTrue(cm.update_folder_rule("/update/path", 5, "new.pat", "AND"))
            self.assertEqual(cm.config['folders'][0]['age_days'], 5)
            self.assertEqual(cm.config['folders'][0]['pattern'], "new.pat")
            self.assertEqual(cm.config['folders'][0]['rule_logic'], "AND")
            mock_save.assert_called_once()

            # Try updating non-existent
            self.assertFalse(cm.update_folder_rule("/not/found", 1, "a.b", "OR"))

    def test_get_folder_rule(self):
        cm = ConfigManager(self.app_name)
        rule_data = {'path': '/get/rule', 'age_days': 2, 'pattern': 'g.r', 'rule_logic': 'AND'}
        cm.config = {'folders': [rule_data], 'settings': {}}
        self.assertEqual(cm.get_folder_rule('/get/rule'), rule_data)
        self.assertIsNone(cm.get_folder_rule('/not/found'))

    def test_get_setting(self):
        cm = ConfigManager(self.app_name)
        cm.config = {'settings': {'my_key': 'my_value', 'check_interval_seconds': 7200, 'start_on_login': False}, 'folders': []}
        self.assertEqual(cm.get_setting('my_key'), 'my_value')
        self.assertEqual(cm.get_setting('check_interval_seconds'), 7200)
        self.assertIsNone(cm.get_setting('non_existent_key'))
        self.assertEqual(cm.get_setting('non_existent_key', 'default_val'), 'default_val')

    def test_set_setting(self):
        # No save_config mock here as set_setting explicitly does not save by itself
        cm = ConfigManager(self.app_name)
        cm.config = {'settings': {'check_interval_seconds': 3600, 'start_on_login': False}, 'folders': []}
        cm.set_setting('new_setting', True)
        self.assertTrue(cm.config['settings']['new_setting'])
        cm.set_setting('check_interval_seconds', 1800)
        self.assertEqual(cm.config['settings']['check_interval_seconds'], 1800)

    @patch("builtins.open", new_callable=mock_open, read_data='[{"path": "/old/format", "age_days": 1, "pattern": "*.*"}]')
    @patch("json.load")
    @patch.object(ConfigManager, 'save_config') # Mock save_config for migration test
    def test_load_config_migration_from_list(self, mock_save_config, mock_json_load, mock_file_open):
        old_list_data = [{"path": "/old/format", "age_days": 1, "pattern": "*.*"}]
        mock_json_load.return_value = old_list_data

        cm = ConfigManager(self.app_name)

        expected_folders = [{"path": "/old/format", "age_days": 1, "pattern": "*.*", "rule_logic": "OR"}] # rule_logic default added
        self.assertEqual(cm.config['folders'], expected_folders)
        self.assertEqual(cm.config['settings'], cm.default_config['settings']) # Default settings should be there
        mock_save_config.assert_called_once() # Migration should trigger a save

    @patch("builtins.open", new_callable=mock_open, read_data='{"folders": [{"path": "/no/logic", "age_days": 1, "pattern": "*.*"}], "settings": {"check_interval_seconds": 900}}')
    @patch("json.load")
    def test_load_config_ensures_rule_logic_default(self, mock_json_load, mock_file_open):
        loaded_data = {"folders": [{"path": "/no/logic", "age_days": 1, "pattern": "*.*"}], "settings": {"check_interval_seconds": 900}}
        mock_json_load.return_value = loaded_data

        cm = ConfigManager(self.app_name)

        self.assertEqual(cm.config['folders'][0]['rule_logic'], 'OR')
        self.assertEqual(cm.config['settings']['check_interval_seconds'], 900)
        # Check if default start_on_login was added
        self.assertIn('start_on_login', cm.config['settings'])
        self.assertEqual(cm.config['settings']['start_on_login'], False)


if __name__ == '__main__':
    unittest.main()
