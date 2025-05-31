import json
import os
import sys
from pathlib import Path

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
            'folders': [],
            'settings': {
                'start_on_login': False,
                'check_interval_seconds': 3600, # Old setting, might be replaced by new schedule settings
                'archive_path_template': '_Cleanup/{YYYY}-{MM}-{DD}',
                'schedule_type': 'interval',  # Default schedule type
                'interval_minutes': 60,  # Default interval in minutes
                'dry_run_mode': False  # Default dry run mode
            }
        }
        self.config = self._load_config()

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
            with open(self.config_file, 'r') as f:
                config_data = json.load(f)
                # Basic validation (check if it's a dict with expected keys)
                if isinstance(config_data, dict) and 'folders' in config_data: # 'settings' check removed as setdefault will handle it
                    # Ensure default settings exist if missing
                    # Ensure 'settings' key itself exists in config_data first
                    loaded_settings = config_data.setdefault('settings', {})
                    default_settings = self.default_config['settings']
                    for key, default_value in default_settings.items():
                        if key not in loaded_settings: # Check against loaded_settings
                            loaded_settings[key] = default_value
                    # No need to re-assign config_data['settings'] if using setdefault and modifying loaded_settings in place

                    # Ensure rule_logic exists for all loaded folders
                    loaded_folders = config_data.get('folders', [])
                    for folder_item in loaded_folders:
                        if 'rule_logic' not in folder_item:
                            folder_item['rule_logic'] = 'OR'
                        if 'use_regex' not in folder_item:  # Add default for use_regex
                            folder_item['use_regex'] = False
                        folder_item.setdefault('action', 'move') # Add default for action

                    return config_data
                # Handle migration from old list format
                elif isinstance(config_data, list):
                     print(f"Warning: Migrating old config format in {self.config_file}.", file=sys.stderr)
                     new_config = self.default_config.copy()
                     # Validate folder items (optional but good)
                     valid_folders = []
                     for item in config_data:
                         if isinstance(item, dict) and 'path' in item and 'age_days' in item and 'pattern' in item:
                             item.setdefault('rule_logic', 'OR') # Ensure rule_logic default during migration
                             item.setdefault('use_regex', False) # Ensure use_regex default during migration
                             item.setdefault('action', 'move')   # Ensure action default during migration
                             valid_folders.append(item)
                         else:
                             print(f"Warning: Skipping invalid folder item during migration: {item}", file=sys.stderr)
                     new_config['folders'] = valid_folders
                     # Save the migrated config immediately
                     self.config = new_config # Temporarily set self.config for save
                     self.save_config()
                     return new_config
                else:
                    print(f"Warning: Config file {self.config_file} has invalid format. Using default.", file=sys.stderr)
                    return self.default_config.copy() # Return a copy
        except FileNotFoundError:
            print(f"Info: Config file {self.config_file} not found. Using default.", file=sys.stderr)
            return self.default_config.copy() # Return a copy
        except json.JSONDecodeError:
            print(f"Error: Could not decode JSON from {self.config_file}. Using default.", file=sys.stderr)
            return self.default_config.copy() # Return a copy
        except Exception as e:
            print(f"Error loading config: {e}", file=sys.stderr)
            return self.default_config.copy() # Return a copy

    def save_config(self):
        """Saves the current configuration to the JSON file."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True) # Ensure dir exists
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}", file=sys.stderr)

    def get_config(self) -> dict: # Changed return type
        """Returns the current configuration dictionary."""
        return self.config

    def get_monitored_folders(self) -> list:
        """Returns just the list of monitored folder configurations."""
        return self.config.get('folders', [])

    def add_folder(self, path: str, age_days: int = 7, pattern: str = "*.*") -> bool:
        """Adds a new folder configuration."""
        folders = self.config.setdefault('folders', []) # Ensure 'folders' key exists
        if not any(item['path'] == path for item in folders):
            folders.append({
                'path': path,
                'age_days': age_days,
                'pattern': pattern,
                'rule_logic': 'OR',
                'use_regex': False, # Add default use_regex field
                'action': 'move'   # Add default action field
            })
            self.save_config()
            return True
        return False # Path already exists

    def remove_folder(self, path: str) -> bool:
        """Removes a folder configuration by path."""
        folders = self.config.setdefault('folders', [])
        initial_len = len(folders)
        self.config['folders'] = [item for item in folders if item['path'] != path]
        if len(self.config['folders']) < initial_len:
            self.save_config()
            return True
        return False # Path not found

    def update_folder_rule(self, path: str, age_days: int, pattern: str, rule_logic: str, use_regex: bool, action: str) -> bool:
        """Updates the rules for a specific folder path."""
        folders = self.config.setdefault('folders', [])
        for item in folders:
            if item['path'] == path:
                item['age_days'] = age_days
                item['pattern'] = pattern
                item['rule_logic'] = rule_logic
                item['use_regex'] = use_regex
                item['action'] = action # Save the new action field
                self.save_config()
                return True
        return False # Path not found

    def get_folder_rule(self, path: str) -> dict | None:
        """Gets the rules for a specific folder path."""
        folders = self.config.setdefault('folders', [])
        for item in folders:
            if item['path'] == path:
                return item
        return None

    # --- Settings Management ---

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
