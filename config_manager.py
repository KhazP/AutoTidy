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
                # 'check_interval_seconds': 3600, # Removed, superseded by new schedule settings
                'archive_path_template': '_Cleanup/{YYYY}-{MM}-{DD}',
                'schedule_type': 'interval',      # 'interval', 'daily', 'weekly'
                'interval_minutes': 60,         # For 'interval' type
                'specific_time': '10:00',       # For 'daily' or 'weekly' type (HH:MM format)
                'days_of_week': [],             # For 'weekly' type (e.g., ["monday", "friday"])
                'dry_run_mode': False,
                'notify_on_scan_completion': False, # New notification setting
                'notify_on_errors': True,           # New notification setting
                'notify_on_actions_summary': True   # New notification setting
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
        # Ensure all schedule-related keys are fetched, using defaults if necessary
        schedule_config = {
            'type': settings.get('schedule_type', default_settings.get('schedule_type')),
            'interval_minutes': settings.get('interval_minutes', default_settings.get('interval_minutes')),
            'specific_time': settings.get('specific_time', default_settings.get('specific_time')),
            'days_of_week': settings.get('days_of_week', default_settings.get('days_of_week', [])),
        }
        return schedule_config

    def set_schedule_config(self, schedule_config: dict):
        """
        Sets the schedule configuration.
        Args:
            schedule_config: A dictionary with keys 'type', 'interval_minutes',
                             'specific_time', 'days_of_week'.
        """
        default_settings = self.default_config.get('settings', {})

        # Validate and set schedule_type
        schedule_type = schedule_config.get('type', default_settings.get('schedule_type'))
        if schedule_type not in ['interval', 'daily', 'weekly']:
            print(f"Warning: Invalid schedule type '{schedule_type}'. Defaulting to '{default_settings.get('schedule_type')}'.", file=sys.stderr)
            schedule_type = default_settings.get('schedule_type')
        self.set_setting('schedule_type', schedule_type)

        # Validate and set interval_minutes (only relevant if type is 'interval')
        if schedule_type == 'interval':
            interval_minutes = schedule_config.get('interval_minutes', default_settings.get('interval_minutes'))
            if not isinstance(interval_minutes, int) or interval_minutes < 1:
                print(f"Warning: Invalid interval_minutes '{interval_minutes}'. Defaulting to '{default_settings.get('interval_minutes')}'.", file=sys.stderr)
                interval_minutes = default_settings.get('interval_minutes')
            self.set_setting('interval_minutes', interval_minutes)
        else:
            # Store a default or None if not interval type, to avoid carrying over old values if type changes
            self.set_setting('interval_minutes', default_settings.get('interval_minutes'))


        # Validate and set specific_time (relevant if type is 'daily' or 'weekly')
        if schedule_type in ['daily', 'weekly']:
            specific_time = schedule_config.get('specific_time', default_settings.get('specific_time'))
            # Basic time format validation (HH:MM)
            import re # Import re locally for this validation
            if not isinstance(specific_time, str) or not re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", specific_time):
                print(f"Warning: Invalid specific_time format '{specific_time}'. Defaulting to '{default_settings.get('specific_time')}'.", file=sys.stderr)
                specific_time = default_settings.get('specific_time')
            self.set_setting('specific_time', specific_time)
        else:
            self.set_setting('specific_time', default_settings.get('specific_time'))


        # Validate and set days_of_week (only relevant if type is 'weekly')
        if schedule_type == 'weekly':
            days_of_week = schedule_config.get('days_of_week', default_settings.get('days_of_week'))
            valid_days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
            if not isinstance(days_of_week, list) or not all(day.lower() in valid_days for day in days_of_week):
                print(f"Warning: Invalid days_of_week value '{days_of_week}'. Defaulting to empty list.", file=sys.stderr)
                days_of_week = [] # Default to empty list if validation fails for weekly
            # Ensure days are stored in lowercase for consistency, though SettingsDialog seems to use lowercase already
            self.set_setting('days_of_week', [day.lower() for day in days_of_week])
        else:
             self.set_setting('days_of_week', default_settings.get('days_of_week', []))


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

    # --- Notification Settings Getters ---
    def get_notify_on_scan_completion(self) -> bool:
        """Returns whether to notify when a scan cycle completes."""
        settings = self.config.setdefault('settings', {})
        default_settings = self.default_config.get('settings', {})
        return settings.get('notify_on_scan_completion', default_settings.get('notify_on_scan_completion', False))

    def get_notify_on_errors(self) -> bool:
        """Returns whether to notify on significant errors."""
        settings = self.config.setdefault('settings', {})
        default_settings = self.default_config.get('settings', {})
        return settings.get('notify_on_errors', default_settings.get('notify_on_errors', True))

    def get_notify_on_actions_summary(self) -> bool:
        """Returns whether to notify with a summary of actions after a scan."""
        settings = self.config.setdefault('settings', {})
        default_settings = self.default_config.get('settings', {})
        return settings.get('notify_on_actions_summary', default_settings.get('notify_on_actions_summary', True))
