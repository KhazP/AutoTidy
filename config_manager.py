import json
import os
import sys
from pathlib import Path

# DEFAULT_CONFIG = {'folders': [], 'settings': {'start_on_login': False}} # Default structure - Moved default to __init__

class ConfigManager:
    """
    Manages the application's configuration, including monitored folders,
    their associated rules, and general application settings. It handles
    loading configuration from a JSON file, saving changes, and provides
    methods to access and modify configuration data.
    """

    def __init__(self, app_name: str):
        """
        Initializes the ConfigManager.

        This involves setting up paths for configuration storage based on the
        operating system and loading the existing configuration or creating a
        default one if none exists or if the existing one is corrupted.

        Args:
            app_name: The name of the application, used to determine the
                      configuration directory's name (e.g., ~/.config/app_name).
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

    def get_config_dir_path(self) -> Path:
        """
        Returns the absolute path to the application's configuration directory.
        This path is determined based on the operating system.

        Returns:
            A Path object representing the configuration directory.
        """
        return self.config_dir

    def _get_config_dir(self) -> Path:
        """
        Determines and returns the appropriate application-specific configuration
        directory based on the operating system.

        On Windows, it typically uses `%APPDATA%/app_name`.
        On Linux and macOS, it typically uses `~/.config/app_name`.

        Returns:
            A Path object representing the application's configuration directory.
        """
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
        """
        Loads the configuration from the JSON file (`config.json`) located in
        the application's configuration directory.

        Handles cases where the file doesn't exist (creates default config),
        is malformed (uses default config), or is in an old format (migrates it).
        It also ensures that default values are populated for any missing settings
        or folder rule parameters.

        Returns:
            A dictionary representing the loaded (or default/migrated) configuration.
        """
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True) # Ensure config directory exists
            with open(self.config_file, 'r') as f:
                config_data = json.load(f)

                # --- Modern config format handling (dict with 'folders' and 'settings') ---
                if isinstance(config_data, dict) and 'folders' in config_data:
                    # Ensure 'settings' key and its default values are present
                    loaded_settings = config_data.setdefault('settings', {})
                    default_settings = self.default_config['settings']
                    for key, default_value in default_settings.items():
                        # Populate missing settings with their default values
                        if key not in loaded_settings:
                            loaded_settings[key] = default_value

                    # Ensure all folder items have default rule parameters if missing
                    loaded_folders = config_data.get('folders', [])
                    for folder_item in loaded_folders:
                        folder_item.setdefault('rule_logic', 'OR') # Default rule logic
                        folder_item.setdefault('use_regex', False) # Default for regex usage
                        folder_item.setdefault('action', 'move')   # Default action type
                    return config_data

                # --- Migration from old list-based format ---
                # The old format was just a list of folder rule dictionaries.
                elif isinstance(config_data, list):
                     print(f"Warning: Migrating old config format in {self.config_file}. See documentation if issues arise.", file=sys.stderr)
                     new_config = self.default_config.copy() # Start with default structure
                     valid_folders = []
                     for item in config_data: # Iterate through old folder list
                         if isinstance(item, dict) and 'path' in item and 'age_days' in item and 'pattern' in item:
                             # Add default rule parameters to old folder entries during migration
                             item.setdefault('rule_logic', 'OR')
                             item.setdefault('use_regex', False)
                             item.setdefault('action', 'move')
                             valid_folders.append(item)
                         else:
                             print(f"Warning: Skipping invalid folder item during migration: {item}", file=sys.stderr)
                     new_config['folders'] = valid_folders
                     # Settings will be taken from self.default_config

                     # Save the newly migrated config immediately to prevent re-migration attempts
                     self.config = new_config # Temporarily set self.config to allow save_config to work
                     self.save_config() # Persist the migrated structure
                     print(f"Info: Successfully migrated config to new format: {self.config_file}", file=sys.stdout) # Use stdout for info
                     return new_config # Return the migrated config
                # --- Invalid format ---
                else:
                    print(f"Warning: Config file {self.config_file} has an unrecognized or invalid format. Using default configuration.", file=sys.stderr)
                    return self.default_config.copy()

        except FileNotFoundError:
            # This is a common case for first run or if file was deleted.
            print(f"Info: Config file {self.config_file} not found. Creating with default configuration.", file=sys.stdout) # Use stdout for info
            return self.default_config.copy()
        except json.JSONDecodeError:
            print(f"Error: Could not decode JSON from {self.config_file}. The file might be corrupted. Using default configuration.", file=sys.stderr)
            return self.default_config.copy()
        except Exception as e:
            # Catch other potential errors during loading (e.g., permissions)
            print(f"Error loading configuration from {self.config_file}: {e}. Using default configuration.", file=sys.stderr)
            return self.default_config.copy()

    def save_config(self):
        """
        Saves the current in-memory configuration (self.config) to the
        `config.json` file in a pretty-printed JSON format.
        The configuration directory is created if it doesn't exist.
        """
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True) # Ensure config directory exists
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            # Handle potential errors during save (e.g., permissions, disk full)
            print(f"Error saving configuration to {self.config_file}: {e}", file=sys.stderr)

    def get_config(self) -> dict: # Changed return type
        """Returns the current configuration dictionary."""
        return self.config

    def get_monitored_folders(self) -> list:
        """
        Returns the list of monitored folder configurations.
        Each item in the list is a dictionary defining a folder's path and its rules.

        Returns:
            A list of folder configuration dictionaries. Returns an empty list
            if no folders are configured or if the 'folders' key is missing.
        """
        return self.config.get('folders', [])

    def add_folder(self, path: str, age_days: int = 7, pattern: str = "*.*") -> bool:
        """Adds a new folder configuration."""
        folders = self.config.setdefault('folders', []) # Ensure 'folders' key exists
        if not any(item['path'] == path for item in folders):
            folders.append({
                'path': path,
                'age_days': age_days,
                'pattern': pattern,
                'rule_logic': 'OR',    # Default rule logic
                'use_regex': False,   # Default for regex usage
                'action': 'move'      # Default action type
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
