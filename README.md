![AutoTidy Icon](autotidyicon.png)

# AutoTidy

AutoTidy is a desktop utility designed to automatically organize cluttered folders like Downloads, Screenshots or Desktop based on user-defined rules.

## Core Purpose

It solves the problem of folders accumulating temporary or old files by automating the cleanup process.

## How it Works

1.  **Configure:** Use the configuration window (accessible via the system tray icon) to add folders you want AutoTidy to monitor.
2.  **Set Rules:** For each folder, define rules based on:
    *   **File Age:** Minimum number of days old a file must be.
    *   **Filename Pattern:** A pattern (like `*.tmp` or `screenshot*.png`) to match filenames.
3.  **Monitor:** Start the monitoring service via the configuration window or tray menu.
4.  **Organize:** AutoTidy runs in the background. When it finds files in a monitored folder that match *either* the age OR pattern rule, it automatically moves them into a dated subfolder named `_Cleanup/YYYY-MM-DD` within that monitored folder.

## Getting Started

1.  Ensure you have Python 3.8+ and PyQt6 installed (`pip install PyQt6`).
2.  Run the application: `python main.py`
3.  The AutoTidy icon will appear in your system tray.
    *   Left-click the icon to show/hide the configuration window.
    *   Right-click the icon for options like Start/Stop Monitoring and Quit.
4.  Use the configuration window to add folders and set rules.

## License

This software is proprietary. Please see the `LICENSE` file for details. All rights are reserved. Unauthorized copying, modification, or distribution is strictly prohibited.
