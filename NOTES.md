# NOTES.md - AutoTidy MVP Development Guide for AI Agent

This document provides a summary and high-level implementation plan for the AutoTidy MVP, based on the project's PRD and Tech Design Doc. It is intended to guide the AI IDE agent during initial code generation.

## Project Overview

* **Product Name**: AutoTidy
* **Core Purpose**: Solves the problem of cluttered user folders (like Desktop, Downloads) by automating the process of organizing files based on user-defined rules.
* **MVP Goal**: Enable users to select folders, define rules (based on file age and filename patterns), and have the application automatically move matching files into a structured, dated subdirectory (`_Cleanup/YYYY-MM-DD`).
* **Target Audience**: Individuals using Windows or Linux desktops who prefer an automated solution for keeping frequently used directories tidy.

## Technical Specifications (from Tech Design Doc)

* **Platform**: Cross-platform Desktop Application (Windows, Linux)
* **Tech Stack (Frontend)**: Python with PyQt (v5/v6) or PySide (v2/v6) for GUI widgets.
* **Tech Stack (Backend/Core)**: Python (3.8+), using standard libraries (`os`, `shutil`, `pathlib`, `datetime`, `threading`, `json`, `fnmatch`, `time`, `queue`).
* **Key Libraries/APIs**:
    * GUI: PyQt/PySide (`QApplication`, `QWidget`, `QSystemTrayIcon`, `QMenu`, `QListWidget`, `QLineEdit`, `QSpinBox`, `QTextEdit`, `QPushButton`, `QFileDialog`, `QMessageBox`, `QTimer`)
    * Threading: `threading.Thread`, `queue.Queue`
    * File System: `os`, `shutil`, `pathlib`, `datetime`
    * Config: `json`
    * Pattern Matching: `fnmatch`
    * Packaging (Post-Dev): PyInstaller
* **Architecture Overview**:
    * Main `QApplication` managing the event loop.
    * `QSystemTrayIcon` for tray presence and context menu.
    * Main configuration window (`QWidget` or `QMainWindow`) with UI elements.
    * Configuration Manager class handling loading/saving settings to JSON.
    * Monitoring Worker class running in a separate `threading.Thread`.
    * Rule Engine logic (functions or class) for checking file conditions.
    * File Action logic (e.g., `process_file_action` function) for handling file relocation (move/copy).
    * Communication between worker thread and main UI thread via `queue.Queue` checked periodically by a `QTimer` in the main thread.
* **Data Handling Notes**:
    * Configuration (monitored folders, rules) stored locally in a JSON file within standard user config directories (`%APPDATA%/AutoTidy` or `~/.config/AutoTidy`).
    * Logs are session-based, displayed in the UI (`QTextEdit`), not persisted to disk by default.
    * Operates entirely locally; no external data transmission.
* **Error Handling Approach**:
    * Use `try...except` blocks for file operations in the worker thread.
    * Send error messages back to the main thread via the communication queue.
    * Display critical errors to the user via `QMessageBox`.
    * Log non-critical errors/warnings to the UI log view.
    * Handle inaccessible folders gracefully (log, skip, potentially update UI status).

## Core MVP Features & Implementation Plan (from PRD & Tech Design Doc)

### Feature: Folder Monitoring Setup
* **Description**: Users can add one or more local folders to be monitored by the application.
* **Key Acceptance Criteria/User Story**: User can click an 'Add Folder' button, select a directory via a native dialog, and see it appear in a list of monitored folders within the app's configuration window. User can also remove folders from the list.
* **Technical Implementation Notes**: Requires a `QPushButton` ('Add Folder'), potentially a `QPushButton` ('Remove Folder'), and a `QListWidget` (or `QTableView`) to display folders. Use `QFileDialog.getExistingDirectory` to select folders. Store the list of folder paths (along with their rules) in the JSON configuration file via the Config Manager class.
* **Agent Implementation Steps (Suggested)**:
    1.  Create the main configuration window class (`ConfigWindow(QWidget)`).
    2.  Add 'Add Folder' and 'Remove Folder' `QPushButton` widgets to `ConfigWindow`.
    3.  Add a `QListWidget` (`monitoredFoldersList`) to display folder paths.
    4.  Implement a slot connected to 'Add Folder' button's `clicked` signal. This slot should:
        * Call `QFileDialog.getExistingDirectory`.
        * If a directory is selected, add the path to the `monitoredFoldersList`.
        * Call the Config Manager to save the updated list (initially with default rules).
    5.  Implement a slot connected to 'Remove Folder' button's `clicked` signal to remove the selected item from `monitoredFoldersList` and update the configuration.
    6.  Implement the `ConfigManager` class with `load_config()` and `save_config()` methods interacting with a JSON file. Structure the JSON to store a list of objects, each containing `path`, `age_days`, `pattern`.
    7.  Ensure `ConfigWindow` loads existing folders into the list on startup.

### Feature: Rule Definition
* **Description**: For each monitored folder, users can configure rules based on File Age Threshold and Filename Pattern Matching.
* **Key Acceptance Criteria/User Story**: When a folder is selected in the list, the user can see and edit input fields for its associated minimum file age (e.g., in days) and a filename pattern (e.g., `*.tmp`). Changes should be saved.
* **Technical Implementation Notes**: Requires input widgets (`QSpinBox` for age, `QLineEdit` for pattern) in the `ConfigWindow`. These should be enabled/populated when a folder is selected in the `QListWidget`. Changes in these inputs should trigger saving the updated rule for the selected folder via the Config Manager. The `currentTextChanged` or `editingFinished` signal for `QLineEdit` and `valueChanged` signal for `QSpinBox` can be used.
* **Agent Implementation Steps (Suggested)**:
    1.  Add `QSpinBox` (`ageThresholdInput`) and `QLineEdit` (`patternInput`) to `ConfigWindow`. Initially, they might be disabled.
    2.  Connect the `currentItemChanged` signal of `monitoredFoldersList` to a slot (`updateRuleInputs`).
    3.  Implement `updateRuleInputs` slot:
        * Get the selected folder path.
        * Load its current rules from the Config Manager.
        * Populate `ageThresholdInput` and `patternInput` with the loaded values.
        * Enable the input widgets.
    4.  Connect the `valueChanged` signal of `ageThresholdInput` and `editingFinished` signal of `patternInput` to a slot (`saveRuleChanges`).
    5.  Implement `saveRuleChanges` slot:
        * Get the currently selected folder path from `monitoredFoldersList`.
        * Get the current values from `ageThresholdInput` and `patternInput`.
        * Call the Config Manager to update and save the rules for that specific folder in the JSON config.

### Feature: Automated File Organization
* **Description**: The application automatically moves files matching the defined rules into a dedicated subdirectory named `_Cleanup/YYYY-MM-DD` (relative to the monitored folder).
* **Key Acceptance Criteria/User Story**: Files in monitored folders older than the specified age OR matching the specified pattern are moved to a subfolder like `_Cleanup/2025-04-15` within that monitored folder.
* **Technical Implementation Notes**: This is the core logic within the `MonitoringWorker` thread. It involves iterating through files in monitored paths (`os.listdir` or `os.scandir`), checking conditions using the Rule Engine logic (`os.path.getmtime`, `datetime`, `fnmatch`), calculating the target path, creating the dated subdirectory (`os.makedirs(exist_ok=True)`), and moving the file (`shutil.move`). Must handle errors gracefully (`try...except`).
* **Agent Implementation Steps (Suggested)**:
    1.  Create the `RuleEngine` logic (e.g., a function `check_file(file_path, age_days, pattern, use_regex)` returning `True` or `False`). It needs to calculate file age from metadata and check against `age_days`, and check filename against `pattern` using `fnmatch` or `re`. Return `True` if *either* condition is met.
    2.  Create the File Action logic (e.g., a function `process_file_action(file_path, monitored_folder_path, archive_path_template, action)`). This function uses the `archive_path_template` to determine the target directory and performs `shutil.move` or `shutil.copy2` based on the `action` string. Include `try...except` for `FileNotFoundError`, `PermissionError`. Return success status/message.
    3.  Implement the main loop inside the `MonitoringWorker` thread's `run()` method.
    4.  The loop should iterate through each configured folder/rule set.
    5.  For each folder, iterate through its files/subdirs (potentially recursively, or just top-level for MVP).
    6.  For each file, call the rule checking logic.
    7.  If a file matches, call `process_file_action` with the appropriate parameters including the action from the rule.
    8.  Send status/error messages back to the main thread via the queue.

### Feature: Background Operation
* **Description**: The application runs in the background, ideally starting on system startup, and periodically checks monitored folders based on their rules.
* **Key Acceptance Criteria/User Story**: The app can run without the main window being visible. It checks folders automatically at regular intervals (e.g., hourly). The user can start/stop the background monitoring process. (Startup on system login is ideal but might be post-MVP).
* **Technical Implementation Notes**: Use `threading.Thread` for the `MonitoringWorker`. Implement a loop within the worker's `run` method containing `time.sleep()` for periodic checks (e.g., `time.sleep(3600)` for hourly). Provide Start/Stop buttons in the UI and context menu that control a flag (e.g., `self.running` or `self.stopped`) used by the worker thread's loop and potentially signal the thread to start/stop cleanly. The main application relies on `QSystemTrayIcon` to stay running when the window is closed.
* **Agent Implementation Steps (Suggested)**:
    1.  Create the `MonitoringWorker` class inheriting from `threading.Thread`.
    2.  Implement its `__init__` method to accept necessary data (e.g., config, communication queue) and initialize a stop flag (`self.stopped = threading.Event()`).
    3.  Implement the `run` method containing the main `while not self.stopped.is_set():` loop.
    4.  Inside the loop, include the folder scanning logic (from Feature 3).
    5.  After scanning all folders, call `self.stopped.wait(3600)` (or use `time.sleep` if the event isn't needed for immediate stop).
    6.  Add Start/Stop `QPushButton` widgets to `ConfigWindow`.
    7.  Implement slots for Start/Stop buttons:
        * Start: Create and start the `MonitoringWorker` thread if not already running. Update UI status.
        * Stop: Set the `self.stopped` event/flag on the worker instance. Update UI status.
    8.  Ensure the main application does not exit when the config window is closed if the tray icon is present (`QApplication.setQuitOnLastWindowClosed(False)`). Add a 'Quit' action to the tray menu to properly stop threads and exit the app.

### Feature: Basic Status & Control
* **Description**: Provide a simple interface to view monitored folders, their configured rules, basic status (running/stopped), and a log of recent activity/errors. Include controls to start/stop the monitoring service.
* **Key Acceptance Criteria/User Story**: User can see which folders are being watched, their rules, whether the monitoring service is active, and a log of recent actions (e.g., "Moved file X", "Error: Permission denied for folder Y"). User can click Start/Stop buttons.
* **Technical Implementation Notes**: Requires a `QTextEdit` (read-only) for logs and potentially a `QLabel` for simple Running/Stopped status in the `ConfigWindow`. The worker thread sends messages (status, errors) via a `queue.Queue`. The main UI thread uses a `QTimer` to periodically check the queue and update the `QTextEdit` and status label accordingly. Start/Stop buttons control the worker thread's execution state.
* **Agent Implementation Steps (Suggested)**:
    1.  Add a `QTextEdit` (`logView`) set to read-only and a `QLabel` (`statusLabel`) to `ConfigWindow`.
    2.  In the main application class or `ConfigWindow`, set up the `queue.Queue` for communication.
    3.  Pass the queue to the `MonitoringWorker` instance upon creation.
    4.  In the `MonitoringWorker`, instead of printing status/errors, put formatted strings onto the queue (`self.queue.put("INFO: Moved file X")`, `self.queue.put("ERROR: Permission denied")`).
    5.  In the main application class or `ConfigWindow`, create a `QTimer` (`self.log_timer = QTimer()`).
    6.  Connect the timer's `timeout` signal to a slot (`check_log_queue`).
    7.  Start the timer (`self.log_timer.start(250)` - check queue every 250ms).
    8.  Implement the `check_log_queue` slot:
        * Use a loop with `self.queue.get_nowait()` inside a `try...except queue.Empty`.
        * For each message retrieved, append it to `logView`.
        * Update `statusLabel` based on worker state (need a way to track this, e.g., via specific queue messages or checking `worker_thread.is_alive()`).
    9.  Implement Start/Stop button logic as described in Feature 4, ensuring they update `statusLabel`.

## UI/UX Concept (from PRD)

* Minimalist application residing primarily in the system tray/menu bar (`QSystemTrayIcon`).
* Clicking tray icon opens a small configuration window (`QWidget`/`QMainWindow`).
* Window contains: 'Add Folder' button, list view (`QListWidget`/`QTableView`) for folders/rules, input fields (`QLineEdit`/`QSpinBox`) for rules, status/log area (`QTextEdit`), Start/Stop buttons (`QPushButton`).
* Right-click tray menu (`QMenu`) provides: Add Folder, Start/Stop App, Quit App actions.
* Clean, simple interface using standard PyQt/PySide widgets. QSS can be used for further styling if needed.

## Out of Scope for MVP (from PRD)

* File previews within the application.
* User configuration of the archive subfolder structure (fixed as `_Cleanup/YYYY-MM-DD`).
* User accounts, settings synchronization, or any cloud features.
* Complex rule combinations (e.g., age AND pattern AND size).
* Moving files to locations outside the monitored folder's hierarchy.
* Advanced scheduling options.
* Undo functionality for moved files.
* Detailed notification system (only critical errors might use pop-ups).

## Key Agent Instructions

* Agent: Please generate the MVP codebase based on the details above.
* Prioritize implementing the features exactly as specified in the 'Core MVP Features & Implementation Plan' section.
* Strictly adhere to the 'Technical Specifications' regarding platform (Windows/Linux), stack (Python, PyQt/PySide), and architecture (threading, queue communication).
* Refer to the full PRD (`autotidy_prd_python_v1.md`) and Tech Design Doc (`autotidy_tdd_python_v1.md`) files in the project root for complete details if needed.
* Create files and directory structures logically (e.g., `main.py`, `ui_config_window.py`, `worker.py`, `config_manager.py`, `utils.py`).
* Add comments to explain complex logic, class responsibilities, and the thread communication mechanism.
* Ensure UI updates happen only in the main thread, using the queue and QTimer mechanism.
* Implement proper application shutdown logic in the 'Quit' action (stop worker thread, save config if needed).