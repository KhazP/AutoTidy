# constants.py

APP_NAME = "AutoTidy"
APP_VERSION = "1.0.1"

# Action types recorded in history
ACTION_MOVED = "MOVED"
ACTION_COPIED = "COPIED"
ACTION_DELETED_TO_TRASH = "DELETED_TO_TRASH"
ACTION_PERMANENTLY_DELETED = "PERMANENTLY_DELETED"
ACTION_SIMULATED_MOVE = "SIMULATED_MOVE"
ACTION_SIMULATED_COPY = "SIMULATED_COPY"
ACTION_SIMULATED_DELETE_TO_TRASH = "SIMULATED_DELETE_TO_TRASH"
ACTION_SIMULATED_PERMANENT_DELETE = "SIMULATED_PERMANENT_DELETE"
ACTION_ERROR = "ERROR"
ACTION_UNDO_MOVE = "UNDO_MOVE"

# Status types recorded in history
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILURE = "FAILURE"
STATUS_SKIPPED = "SKIPPED" # For actions that were intentionally skipped by logic

# Default configuration values
DEFAULT_CONFIG = {
    "rules": [],
    "settings": {
        "run_on_startup": False,
        "show_notifications": True,
        "log_level": "INFO"
    }
}

# Rule Templates
RULE_TEMPLATES = [
    {
        "name": "Clean up Downloads",
        "description": "Deletes files older than 90 days from your Downloads folder.",
        "rules": [
            {
                "folder_to_watch": "%UserProfile%/Downloads",
                "file_pattern": "*.*",
                "action": "delete",
                "destination_folder": "", # Not needed for delete
                "days_older_than": 90,
                "enabled": True,
                "use_regex": False
            }
        ]
    },
    {
        "name": "Organize Screenshots",
        "description": "Moves screenshots named like \'Screenshot YYYY-MM-DD HHMMSS.png\' from your Pictures\\\\Screenshots folder to \'Pictures\\\\Organized Screenshots\'.",
        "rules": [
            {
                "folder_to_watch": "%UserProfile%/Pictures/Screenshots",
                "file_pattern": "Screenshot ????-??-?? ??????.png", # Glob pattern for "Screenshot YYYY-MM-DD HHMMSS.png"
                "action": "move",
                "destination_folder": "%UserProfile%/Pictures/Organized Screenshots",
                "days_older_than": 0,
                "enabled": True,
                "use_regex": False
            }
        ]
    },
    {
        "name": "Organize Video Captures",
        "description": "Moves video captures (MP4, AVI, MKV) older than 30 days from Videos\\\\Captures to \'Videos\\\\Archived Captures\'.",
        "rules": [
            {
                "folder_to_watch": "%UserProfile%/Videos/Captures",
                "file_pattern": "*.mp4",
                "action": "move",
                "destination_folder": "%UserProfile%/Videos/Archived Captures",
                "days_older_than": 30,
                "enabled": True,
                "use_regex": False
            },
            {
                "folder_to_watch": "%UserProfile%/Videos/Captures",
                "file_pattern": "*.avi",
                "action": "move",
                "destination_folder": "%UserProfile%/Videos/Archived Captures",
                "days_older_than": 30,
                "enabled": True,
                "use_regex": False
            },
            {
                "folder_to_watch": "%UserProfile%/Videos/Captures",
                "file_pattern": "*.mkv",
                "action": "move",
                "destination_folder": "%UserProfile%/Videos/Archived Captures",
                "days_older_than": 30,
                "enabled": True,
                "use_regex": False
            }
        ]
    },
    {
        "name": "Clean Temporary Files",
        "description": "Deletes all files from system temporary folders (C:\\\\Windows\\\\Temp and %LocalAppData%\\\\Temp). Use with caution.",
        "rules": [
            {
                "folder_to_watch": "C:/Windows/Temp", # Forward slashes are generally safer for paths in code
                "file_pattern": "*.*",
                "action": "delete",
                "destination_folder": "",
                "days_older_than": 0, # Delete immediately
                "enabled": True,
                "use_regex": False
            },
            {
                "folder_to_watch": "%LocalAppData%/Temp",
                "file_pattern": "*.*",
                "action": "delete",
                "destination_folder": "",
                "days_older_than": 0, # Delete immediately
                "enabled": True,
                "use_regex": False
            }
        ]
    },
    {
        "name": "Organize Game Captures (Example)",
        "description": "Example: Moves MP4 game captures from a specific game\'s capture folder to an \'Organized\' subfolder. Customize the path for your game.",
        "rules": [
            {
                "folder_to_watch": "%UserProfile%/Videos/[Your Game Name]/Captures", # Placeholder
                "file_pattern": "*.mp4",
                "action": "move",
                "destination_folder": "%UserProfile%/Videos/[Your Game Name]/Captures/Organized", # Placeholder
                "days_older_than": 0,
                "enabled": True,
                "use_regex": False
            }
        ]
    }
]

# Logging related constants

# Notification Levels
NOTIFICATION_LEVEL_NONE = "none"
NOTIFICATION_LEVEL_ERROR = "error"
NOTIFICATION_LEVEL_SUMMARY = "summary"
NOTIFICATION_LEVEL_ALL = "all"

DEFAULT_NOTIFICATION_LEVEL = NOTIFICATION_LEVEL_ALL
