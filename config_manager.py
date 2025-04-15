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
        self.default_config = {'folders': [], 'settings': {'start_on_login': False}}
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
                if isinstance(config_data, dict) and 'folders' in config_data and 'settings' in config_data:
                    # Ensure default settings exist if missing
                    if 'start_on_login' not in config_data['settings']:
                        config_data['settings']['start_on_login'] = self.default_config['settings']['start_on_login']
                    return config_data
                # Handle migration from old list format
                elif isinstance(config_data, list):
                     print(f"Warning: Migrating old config format in {self.config_file}.", file=sys.stderr)
                     new_config = self.default_config.copy()
                     # Validate folder items (optional but good)
                     valid_folders = []
                     for item in config_data:
                         if isinstance(item, dict) and 'path' in item and 'age_days' in item and 'pattern' in item:
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
            folders.append({'path': path, 'age_days': age_days, 'pattern': pattern})
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

    def update_folder_rule(self, path: str, age_days: int, pattern: str) -> bool:
        """Updates the rules for a specific folder path."""
        folders = self.config.setdefault('folders', [])
        for item in folders:
            if item['path'] == path:
                item['age_days'] = age_days
                item['pattern'] = pattern
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
