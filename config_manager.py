
import json
import os
import platform
import sys
from pathlib import Path

DEFAULT_CONFIG = [] # List of {'path': str, 'age_days': int, 'pattern': str}

def get_config_dir() -> Path:
    """Gets the platform-specific configuration directory."""
    if platform.system() == "Windows":
        app_data = os.getenv("APPDATA")
        if app_data:
            return Path(app_data) / "AutoTidy"
    else: # Linux/macOS
        xdg_config_home = os.getenv("XDG_CONFIG_HOME")
        if xdg_config_home:
            return Path(xdg_config_home) / "AutoTidy"
        else:
            return Path.home() / ".config" / "AutoTidy"
    # Fallback if APPDATA is not set on Windows (unlikely)
    return Path.home() / ".autotidy"


class ConfigManager:
    """Handles loading and saving application configuration."""

    def __init__(self, config_file_name: str = "config.json"):
        self.config_dir = get_config_dir()
        self.config_file = self.config_dir / config_file_name
        self.config = self._load_config()

    def _load_config(self) -> list:
        """Loads configuration from the JSON file."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True) # Ensure dir exists
            with open(self.config_file, 'r') as f:
                config_data = json.load(f)
                # Basic validation (check if it's a list)
                if isinstance(config_data, list):
                    # Further validation could be added here (e.g., check dict keys)
                    return config_data
                else:
                    print(f"Warning: Config file {self.config_file} has invalid format. Using default.", file=sys.stderr)
                    return DEFAULT_CONFIG[:] # Return a copy
        except FileNotFoundError:
            print(f"Info: Config file {self.config_file} not found. Using default.", file=sys.stderr)
            return DEFAULT_CONFIG[:] # Return a copy
        except json.JSONDecodeError:
            print(f"Error: Could not decode JSON from {self.config_file}. Using default.", file=sys.stderr)
            return DEFAULT_CONFIG[:] # Return a copy
        except Exception as e:
            print(f"Error loading config: {e}", file=sys.stderr)
            return DEFAULT_CONFIG[:] # Return a copy

    def save_config(self):
        """Saves the current configuration to the JSON file."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True) # Ensure dir exists
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}", file=sys.stderr)

    def get_config(self) -> list:
        """Returns the current configuration."""
        return self.config

    def add_folder(self, path: str, age_days: int = 7, pattern: str = "*.*") -> bool:
        """Adds a new folder configuration."""
        if not any(item['path'] == path for item in self.config):
            self.config.append({'path': path, 'age_days': age_days, 'pattern': pattern})
            self.save_config()
            return True
        return False # Path already exists

    def remove_folder(self, path: str) -> bool:
        """Removes a folder configuration by path."""
        initial_len = len(self.config)
        self.config = [item for item in self.config if item['path'] != path]
        if len(self.config) < initial_len:
            self.save_config()
            return True
        return False # Path not found

    def update_folder_rule(self, path: str, age_days: int, pattern: str) -> bool:
        """Updates the rules for a specific folder path."""
        for item in self.config:
            if item['path'] == path:
                item['age_days'] = age_days
                item['pattern'] = pattern
                self.save_config()
                return True
        return False # Path not found

    def get_folder_rule(self, path: str) -> dict | None:
        """Gets the rules for a specific folder path."""
        for item in self.config:
            if item['path'] == path:
                return item
        return None
