<img src="autotidyicon.ico" alt="AutoTidy Icon" width="96"/>

# 🚀 AutoTidy - Automated File Organizer 🚀

[![Version](https://img.shields.io/badge/version-1.0.1-blue.svg?style=for-the-badge)](constants.py)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg?style=for-the-badge)](LICENSE)
[![Contributions Welcome](https://img.shields.io/badge/contributions-welcome-orange.svg?style=for-the-badge)](#-contributing)

> **Automatically tidy up your cluttered folders!**
> AutoTidy monitors specified directories and organizes files based on your custom rules, moving them into dated subfolders.

---

## 📖 Table of Contents

* [Overview](#overview)
* [✨ Core Functionality](#-core-functionality)
* [⚙️ How It Works](#️-how-it-works)
* [🚀 Getting Started](#-getting-started)
* [🛠️ Usage](#️-usage)
* [🔧 Configuration](#-configuration)
* [💻 Tech Stack Highlights](#-tech-stack-highlights)
* [📁 Key Files Overview](#-key-files-overview)
* [⚠️ Known Issues & Limitations](#️-known-issues--limitations)
* [🔮 Future Enhancements (Potential)](#-future-enhancements-potential)
* [🤝 Contributing](#-contributing)
* [📜 Disclaimer](#-disclaimer)
* [📄 License](#-license)

---
## Overview

**AutoTidy** is a desktop utility designed for Windows and Linux users who want to automate the organization of frequently cluttered folders such as Downloads, Screenshots, or the Desktop. It helps maintain a clean digital workspace by systematically moving files based on user-defined rules.

This tool tackles the inefficiency of manual sorting and periodic cleanups, allowing users to set their organization preferences once and let AutoTidy handle the rest in the background.

---
## ✨ Core Functionality

*   **Folder Monitoring**: Users can select one or more local folders for AutoTidy to watch.
*   **Rule-Based Organization**: Define rules for each folder based on:
    *   **File Age**: Specify a minimum age (in days) for a file to be considered.
    *   **Filename Pattern**: Utilize **Enhanced Pattern Matching** with support for both wildcard (`fnmatch`) and Regular Expression (Regex) to identify files.
*   **Versatile File Actions**: Configure rules to automatically Move, Copy, Delete to Trash, or Permanently Delete files. Files matching *either* the age or pattern rule are processed.
*   **Flexible Archiving**: Moved or copied files are organized into a user-configurable archive path using templates (e.g., `{YYYY}`, `{MM}`, `{DD}`, `{FILENAME}`, `{EXT}`, `{ORIGINAL_FOLDER_NAME}`). The default structure remains `_Cleanup/YYYY-MM-DD` within the monitored folder.
*   **Safe Operations with Dry Run**: A "Dry Run" mode allows users to preview the actions AutoTidy would take based on current rules, without actually modifying any files.
*   **Background Operation**: Runs quietly in the system tray, performing checks at a **Configurable Scan Interval**.
*   **User Control**: Start and stop the monitoring service via the UI or tray menu.
*   **Status & Logging**: View the current status (running/stopped) and a log of recent activities and errors in the configuration window.
*   **Action History & Undo**: Keeps a history of file operations, enabling users to undo recent Move or Copy actions.
*   **Autostart Option**: Configure AutoTidy to start automatically on system login.

---
## ⚙️ How It Works

1.  **Configure**: Launch AutoTidy. The application icon appears in the system tray.
    * Left-click the tray icon to open the **Configuration Window**.
    * Use the "Add Folder" button to select directories you want AutoTidy to monitor.
2.  **Set Rules**: For each added folder:
    * Specify the **minimum file age** (in days). Files older than this will be targeted.
    * Define a **filename pattern** using wildcards (e.g., `*.jpg`, `temp_*.*`) or switch to Regular Expressions for more complex matching.
    * Select the **Action** to be performed (Move, Copy, Delete to Trash, or Permanent Delete).
    * *Note: A file will be processed if it meets the age OR the pattern criteria, according to the selected action.*
3.  **Monitor**: Click "Start Monitoring" in the Configuration Window or via the tray menu.
    * AutoTidy's worker process begins running in the background.
    * It periodically scans the configured folders based on the user-defined **Scan Interval**.
4.  **Organize**: When the worker scans a monitored folder:
    * It checks each file against the rules defined for that folder.
    * If a file matches (is older than the set age OR its name matches the pattern), AutoTidy performs the configured **Action** (Move, Copy, or Delete).
    * For Move or Copy actions, the file is placed into an archive structure. The default is a subfolder named `_Cleanup` within the monitored folder, further organized by date (e.g., `_Cleanup/YYYY-MM-DD/filename.ext`). This structure can be customized using the **Archive Path Template**.
    * If the necessary archive subdirectories don't exist, AutoTidy creates them.
5.  **Feedback**:
    * The Configuration Window displays logs of actions (files processed, errors).
    * The status (Running/Stopped) is also visible.
    * Critical errors may be shown as message boxes.

---
## 🚀 Getting Started

Prerequisites:
* Python (3.8+ recommended)
* PyQt6 (`pip install PyQt6`)

To run the application:
1.  Clone or download the repository.
2.  Navigate to the AutoTidy directory in your terminal.
3.  Run the application:
    ```bash
    python main.py
    ```
4.  The AutoTidy icon will appear in your system tray.

---
## 🛠️ Usage

1.  **Launch AutoTidy**: Execute `main.py`.
2.  **Access Configuration**:
    * **Left-click** the AutoTidy tray icon to show/hide the Configuration Window.
    * **Right-click** the tray icon for a context menu with options:
        * Show/Hide Config
        * Start Monitoring
        * Stop Monitoring
        * Quit
3.  **Add Folders**:
    * In the Configuration Window, click "Add Folder".
    * Select a directory you wish to monitor using the dialog.
4.  **Define Rules**:
    * Select a folder from the "Monitored Folders" list.
    * Set the "Min Age (days)" (e.g., 7 for files older than a week).
    * Enter a "Filename Pattern" (e.g., `*.log`, `image-?.png`).
    * Changes to rules are saved automatically when you edit them.
5.  **Start/Stop Monitoring**:
    * Use the "Start Monitoring" / "Stop Monitoring" buttons in the Configuration Window or the tray menu.
6.  **View Logs**:
    * The "Logs" section in the Configuration Window shows recent actions and errors.
7.  **Settings**:
    * Click the "Settings" button in the Configuration Window.
    * Here you can toggle "Start AutoTidy automatically on system login".

---
## 🔧 Configuration

Settings are managed via two main interfaces:

**1. Main Configuration Window (for folders and rules):**
* **Monitored Folders List**: Displays all folders being watched. Select a folder here to edit its rules.
* **Add Folder Button**: Opens a dialog to choose a new folder to monitor.
* **Remove Selected Button**: Removes the currently selected folder from the monitoring list.
* **Min Age (days)**: Numeric input for the age rule.
* **Filename Pattern**: Text input for the pattern rule. Supports standard wildcards (e.g., `*.log`, `image-?.png`) and can be switched to use Regular Expressions for advanced users (e.g., via a toggle/checkbox).
* **Action**: Dropdown or selection control to choose the action for files matching the rule: Move, Copy, Delete to Trash, or Delete Permanently.
* Configuration for folders and rules is saved automatically to a `config.json` file in your user's application data directory (e.g., `%APPDATA%/AutoTidy` on Windows, `~/.config/AutoTidy` on Linux).

**2. Settings Dialog (for application-wide settings):**
* Accessed via the "Settings" button in the Main Configuration Window.
* **Start AutoTidy automatically on system login**: Checkbox to enable/disable autostart.
* **Archive Path Template**: Text input allowing users to define the folder structure for Moved or Copied files using placeholders (e.g., `_Archive/{YYYY}-{MM}/{ORIGINAL_FOLDER_NAME}`). Defaults to `_Cleanup/{YYYY}-{MM}-{DD}`.
* **Scan Interval (minutes)**: Numeric input to set how frequently AutoTidy checks monitored folders.
* **Dry Run Mode**: Checkbox to enable/disable "Dry Run" mode, which simulates actions without making changes.
    * On Windows, this modifies the Registry.
    * On Linux, this creates/removes a `.desktop` file in `~/.config/autostart/`.
* Displays the application **Version**.
* Settings are saved to the same `config.json` file.

---
## 💻 Tech Stack Highlights

* **Platform**: Cross-Platform Desktop (Windows, Linux)
* **Core Language**: Python (3.8+)
* **GUI**: PyQt6
* **Key Python Modules**:
    * `os`, `sys`, `pathlib`: For file system interaction and path manipulation.
    * `shutil`: For moving files.
    * `datetime`, `time`: For handling file age and scheduling.
    * `json`: For storing configuration.
    * `threading`, `queue`: For background processing and UI communication.
    * `fnmatch`: For filename pattern matching.
    * `winreg` (Windows-specific): For managing autostart registry entries.
* **Background Processing**: A separate thread (`MonitoringWorker`) handles folder scanning and file operations to keep the UI responsive.
* **Configuration Storage**: Local JSON file (`config.json`).

---
## 📁 Key Files Overview

<details>
<summary>Click to expand key files list</summary>

* `main.py`: Main application entry point, sets up `QApplication`, tray icon, and initial window.
* `ui_config_window.py`: Defines the main configuration window's UI and logic.
* `ui_settings_dialog.py`: Defines the settings dialog UI and logic.
* `worker.py`: Contains the `MonitoringWorker` class for background file processing.
* `config_manager.py`: Manages loading and saving of application configuration (folders, rules, settings) to `config.json`.
* `startup_manager.py`: Handles enabling/disabling autostart for Windows (registry) and Linux (.desktop files).
* `utils.py`: Contains utility functions for file checking (`check_file`) and moving (`move_file`).
* `constants.py`: Stores application-wide constants like `APP_NAME` and `APP_VERSION`.
* `autotidyicon.ico`: Application icon.
* `README.md`: This file.
</details>

---
## ⚠️ Known Issues & Limitations

* **Error Handling**: While basic error handling is in place (e.g., for permission errors, file not found, invalid Regex patterns), more granular error reporting and recovery mechanisms could be added.
* **Performance on Very Large Folders**: Scanning extremely large directories with many files might take noticeable time, though it runs in a background thread.
* **Pattern Matching**: Supports `fnmatch` (wildcards) and Regular Expressions. Users should ensure Regex patterns are syntactically correct to avoid rule processing errors.
* **Resource Usage**: Background polling consumes system resources. While the scan interval is configurable, very frequent checks on numerous or large folders can increase system load.
* **Archive Naming Collision**: If many files with the same name are processed by a Move or Copy action on the same day (or into the same target path based on template), they are renamed with an incrementing counter (e.g., `file_1.txt`, `file_2.txt`). This is basic and could be improved.
* **Symlinks/Shortcuts**: Behavior with symbolic links or shortcuts as monitored items or files within monitored folders might not be explicitly defined or tested. For MVP, it primarily targets regular files.
* **External Drive Disconnection**: If a monitored folder is on an external drive that gets disconnected, the application will log errors but might not handle reconnection gracefully without a restart of the monitoring service.

---
## 🔮 Future Enhancements (Potential)

* Advanced cron-like scheduling for specific times, days, or intervals.
* UI for viewing/managing files within the `_Cleanup` folders.
* System notifications for completed actions or critical errors.
* More robust handling of filename collisions.
* Internationalization/Localization for the UI.

---
## 🤝 Contributing

Contributions are welcome! If you have ideas for improvements or want to fix a bug:

1.  **Fork** the repository.
2.  Create a **feature branch** (`git checkout -b feature/your-amazing-idea`).
3.  **Develop** and **test** your changes thoroughly.
4.  **Commit** your work (`git commit -m "feat: Add some amazing feature"`). Use clear and descriptive commit messages.
5.  **Push** to your branch (`git push origin feature/your-amazing-idea`).
6.  Open a **Pull Request** against the `main` branch of this repository.

Please ensure your code adheres to general Python best practices and maintains the existing architectural style.

---
## 📜 Disclaimer

> This tool modifies your filesystem by moving files. While developed with care, the author(s) are not responsible for any accidental data loss or unintended consequences of using AutoTidy. **It is strongly recommended to test the configuration on non-critical folders first.** Use at your own risk.

---
## 📄 License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

