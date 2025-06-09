# AutoTidy Dependencies

This document lists the dependencies required for the AutoTidy application.

## Runtime Dependencies

The following packages are required to run AutoTidy:

### PyQt6
- **Purpose**: GUI framework for the desktop application
- **Usage**: Main interface, system tray, dialogs, and all UI components
- **Installation**: `pip install PyQt6`

### send2trash
- **Purpose**: Safe file deletion (moves files to recycle bin instead of permanent deletion)
- **Usage**: Used in `utils.py` for the file deletion functionality
- **Installation**: `pip install send2trash`

## Standard Library Dependencies

The application also uses the following Python standard library modules (no installation required):

- `sys`, `os` - System operations
- `json` - Configuration file handling
- `shutil` - File operations
- `pathlib` - Path handling
- `datetime` - Date and time operations
- `threading`, `queue` - Multi-threading support
- `time` - Time operations
- `uuid` - Unique identifier generation
- `fnmatch` - File pattern matching
- `re` - Regular expressions

## Development Dependencies

For building and packaging:

- `pyinstaller` - For creating executable files
- `inno-setup` - For creating Windows installer (external tool)

## Installation

To install all required dependencies:

```bash
pip install -r requirements.txt
```

## Previous Dependencies (Removed)

The following dependencies were removed as they were not used in the current implementation:

- `ffmpeg-python` - Not used in current file organization features
- `opencv-python` - Not used in current file organization features  
- `python-magic` - Not used in current file organization features
- `reportlab` - Not used in current file organization features
- `spacy` - Not used in current file organization features
- `textract` - Not used in current file organization features (also had installation issues)

## Note

The dependencies have been minimized to only include what is actually used by the application to ensure:
1. Faster installation
2. Smaller package size
3. Fewer potential compatibility issues
4. Easier maintenance
