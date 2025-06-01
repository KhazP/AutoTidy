import json
import os
import sys
from pathlib import Path

CONFIG_VERSION = "2.0.0" # New config version

# DEFAULT_CONFIG = {'folders': [], 'settings': {'start_on_login': False}} # Default structure - Moved default to __init__

class ConfigManager:
    """Manages loading and saving application configuration (folders, rules, settings)."""

    def __init__(self, app_name: str):
        """Initializes the ConfigManager.

        Args:
            app_name: The name of the application, used for the config directory.
        """
        self.app_name = app_name
        self.config_dir = self._get_config_dir()
        self.config_file = self.config_dir / "config.json"
        self.default_config = {
            'config_version': CONFIG_VERSION,
            'folders': [
                # Example of new folder structure with a sample rule
                # {
                #     'path': '/path/to/example_monitored_folder',
                #     'rules': [
                #         {
                #             'name': 'Old PNG files',
                #             'conditions': [
                #                 {'field': 'mime_type', 'operator': 'equals', 'value': 'image/png'},
                #                 {'field': 'age_days', 'operator': 'greater_than', 'value': 30}
                #             ],
                #             'condition_logic': 'AND',
                #             'action': 'move'
                #         }
                #     ]
                # }
            ],
            'settings': {
                'start_on_login': False,
                # 'check_interval_seconds': 3600, # Retained for now, but schedule_type/interval_minutes is primary
                'archive_path_template': '_Cleanup/{YYYY}-{MM}-{DD}',
                'schedule_type': 'interval',
                'interval_minutes': 60,
                'dry_run_mode': False
            }
        }
        self.config = self._load_config()

    def get_config_dir_path(self) -> Path: # Method used by HistoryManager
        """Returns the application's configuration directory path."""
        return self.config_dir

    def _get_config_dir(self) -> Path:
        """Determines the appropriate configuration directory based on OS."""
        if sys.platform == "win32":
            # Use %APPDATA% on Windows
            appdata = os.getenv('APPDATA')
            if appdata:
                return Path(appdata) / self.app_name
            else:
                # Fallback if APPDATA is not set (unlikely)
                return Path.home() / ".config" / self.app_name
        else:
            # Use ~/.config/ on Linux/macOS
            return Path.home() / ".config" / self.app_name

    def _load_config(self) -> dict:
        """Loads configuration from the JSON file."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True) # Ensure dir exists
            if not self.config_file.exists():
                print(f"Info: Config file {self.config_file} not found. Creating with default.", file=sys.stderr)
                # self.config = self.default_config.copy() # Set self.config before saving
                # self.save_config() # Save immediately
                return self.default_config.copy()

            with open(self.config_file, 'r') as f:
                config_data = json.load(f)

            # Version check and migration (simplified: discard old)
            if config_data.get('config_version') != CONFIG_VERSION:
                print(f"Warning: Config file version mismatch or missing. Expected {CONFIG_VERSION}, found {config_data.get('config_version')}. Reverting to default.", file=sys.stderr)
                # self.config = self.default_config.copy()
                # self.save_config() # Save new default immediately
                return self.default_config.copy()

            # Basic validation for new structure
            if not isinstance(config_data, dict) or 'folders' not in config_data or 'settings' not in config_data:
                print(f"Warning: Config file {self.config_file} has invalid format. Using default.", file=sys.stderr)
                return self.default_config.copy()

            # Ensure default settings are present if any are missing
            loaded_settings = config_data.setdefault('settings', {})
            default_settings = self.default_config['settings']
            for key, default_value in default_settings.items():
                loaded_settings.setdefault(key, default_value)

            # Ensure folders are lists and rules within them are lists
            loaded_folders = config_data.get('folders', [])
            for folder_item in loaded_folders:
                if not isinstance(folder_item, dict) or 'path' not in folder_item:
                    # Invalid folder item, could remove or log
                    continue # simple skip for now
                folder_item.setdefault('rules', []) # Ensure 'rules' list exists
                for rule in folder_item['rules']: # Further validation for individual rules
                    if not isinstance(rule, dict): continue # skip malformed rule
                    rule.setdefault('conditions', [])
                    rule.setdefault('condition_logic', 'AND') # Default logic
                    rule.setdefault('action', 'move') # Default action
                    # Could add more validation for condition structure here

            return config_data

        except json.JSONDecodeError:
            print(f"Error: Could not decode JSON from {self.config_file}. Using default.", file=sys.stderr)
            return self.default_config.copy()
        except Exception as e:
            print(f"Error loading config: {e}", file=sys.stderr)
            return self.default_config.copy()

    def save_config(self):
        """Saves the current configuration to the JSON file."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True) # Ensure dir exists
            self.config['config_version'] = CONFIG_VERSION # Ensure version is current
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}", file=sys.stderr)

    def get_config(self) -> dict:
        """Returns the current configuration dictionary."""
        return self.config

    def get_monitored_folders(self) -> list:
        """Returns just the list of monitored folder configurations."""
        return self.config.get('folders', [])

    def add_monitored_folder_basic(self, path: str) -> bool:
        """Adds a new folder configuration with a default basic rule or empty rule list."""
        folders = self.config.setdefault('folders', [])
        if not any(folder_item['path'] == path for folder_item in folders):
            folders.append({
                'path': path,
                'rules': [ # Example default rule, can be empty: []
                    {
                        'name': 'Default Rule (Move old files)',
                        'conditions': [
                            {'field': 'age_days', 'operator': 'greater_than', 'value': 30}
                        ],
                        'condition_logic': 'AND',
                        'action': 'move'
                    }
                ]
            })
            self.save_config()
            return True
        return False # Path already exists

    def remove_folder(self, path_str: str) -> bool:
        """Removes a folder configuration by path string."""
        folders = self.config.setdefault('folders', [])
        initial_len = len(folders)
        # Corrected: self.config['folders'] should be updated
        self.config['folders'] = [folder_item for folder_item in folders if folder_item['path'] != path_str]
        if len(self.config['folders']) < initial_len:
            self.save_config()
            return True
        return False # Path not found

    def get_rules_for_folder(self, folder_path_str: str) -> list | None:
        """Gets the list of rules for a specific folder path string."""
        folders = self.config.get('folders', [])
        for folder_item in folders:
            if folder_item['path'] == folder_path_str:
                return folder_item.get('rules', []) # Return empty list if 'rules' key is missing
        return None

    # Rule management for a specific folder (add, remove, update individual rules)
    # These would be new methods. For this subtask, we assume they are not fully implemented yet
    # or will be handled by direct manipulation of the list returned by get_rules_for_folder
    # followed by save_config(). Example stubs:

    def add_rule_to_folder(self, folder_path_str: str, rule_dict: dict) -> bool:
        """Adds a new rule to a folder. Assumes rule_dict is validated."""
        rules = self.get_rules_for_folder(folder_path_str)
        if rules is not None: # Folder exists
            rules.append(rule_dict)
            self.save_config()
            return True
        return False # Folder not found

    def update_rule_in_folder(self, folder_path_str: str, rule_name_to_update: str, new_rule_dict: dict) -> bool:
        """Updates an existing rule in a folder by rule name."""
        rules = self.get_rules_for_folder(folder_path_str)
        if rules is not None:
            for i, rule in enumerate(rules):
                if rule.get('name') == rule_name_to_update:
                    rules[i] = new_rule_dict
                    self.save_config()
                    return True
        return False # Folder or rule not found

    def remove_rule_from_folder(self, folder_path_str: str, rule_name_to_remove: str) -> bool:
        """Removes a rule from a folder by rule name."""
        rules = self.get_rules_for_folder(folder_path_str)
        if rules is not None:
            initial_len = len(rules)
            # Rebuild rules list excluding the one to remove
            new_rules = [rule for rule in rules if rule.get('name') != rule_name_to_remove]
            if len(new_rules) < initial_len:
                 # Find the folder and update its rules
                for folder_item in self.config.get('folders', []):
                    if folder_item['path'] == folder_path_str:
                        folder_item['rules'] = new_rules
                        self.save_config()
                        return True
        return False # Folder or rule not found

    # --- Settings Management --- (largely unchanged, ensure defaults are consistent)

    def get_setting(self, key: str, default=None):
        """Gets a specific setting value."""
        return self.config.setdefault('settings', {}).get(key, default)

    def set_setting(self, key: str, value):
        """Sets a specific setting value."""
        settings = self.config.setdefault('settings', {})
        settings[key] = value
        # Note: save_config() is not called here automatically.
        # Call save_config() explicitly after setting changes.

    def get_archive_path_template(self) -> str:
        """Returns the archive path template string."""
        # Ensure settings dictionary and the specific key exist, falling back to default.
        default_template = self.default_config.get('settings', {}).get('archive_path_template', '_Cleanup/{YYYY}-{MM}-{DD}')
        return self.config.setdefault('settings', {}).get('archive_path_template', default_template)

    def set_archive_path_template(self, template_string: str):
        """Sets the archive path template string."""
        if not template_string: # Basic validation
            # Fallback to default if empty string is provided, or handle error
            template_string = self.default_config.get('settings', {}).get('archive_path_template', '_Cleanup/{YYYY}-{MM}-{DD}')
        self.set_setting('archive_path_template', template_string)

    def get_schedule_config(self) -> dict:
        """Returns the schedule configuration."""
        settings = self.config.setdefault('settings', {})
        default_settings = self.default_config.get('settings', {})
        return {
            'type': settings.get('schedule_type', default_settings.get('schedule_type', 'interval')),
            'interval_minutes': settings.get('interval_minutes', default_settings.get('interval_minutes', 60))
        }

    def set_schedule_config(self, schedule_type: str, interval_minutes: int):
        """Sets the schedule configuration."""
        # Basic validation for interval_minutes
        if not isinstance(interval_minutes, int) or interval_minutes < 1:
            interval_minutes = self.default_config.get('settings', {}).get('interval_minutes', 60)

        self.set_setting('schedule_type', schedule_type) # For now, always 'interval'
        self.set_setting('interval_minutes', interval_minutes)

    def get_dry_run_mode(self) -> bool:
        """Returns the current state of dry run mode."""
        settings = self.config.setdefault('settings', {})
        default_settings = self.default_config.get('settings', {})
        return settings.get('dry_run_mode', default_settings.get('dry_run_mode', False))

    def set_dry_run_mode(self, enabled: bool):
        """Sets the state of dry run mode."""
        if not isinstance(enabled, bool): # Basic type validation
            enabled = False # Default to False if invalid type
        self.set_setting('dry_run_mode', enabled)
