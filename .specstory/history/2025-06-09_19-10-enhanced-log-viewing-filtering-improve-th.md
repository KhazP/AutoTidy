<!-- Generated by SpecStory -->

# *   **Enhanced Log Viewing/Filtering:** Improve th (2025-06-09 22:10:58)

_**User**_

*   **Enhanced Log Viewing/Filtering:** Improve the log viewer with options to filter by date, folder, action type, or severity (info, warning, error). Allow exporting logs.

---

_**Assistant**_

Okay, I will enhance the log viewer in `ui_history_viewer_dialog.py` by adding filtering options and an export functionality.

Here's the plan:
1.  **Modify `HistoryViewerDialog` in `ui_history_viewer_dialog.py`**:
    *   Add UI elements for filtering (QComboBox for action type, severity; QLineEdit for folder; QDateEdit for date).
    *   Add an "Export Logs" button.
    *   Implement filtering logic in `load_history` or a new dedicated filtering method.
    *   Implement the `export_logs` method to save the (filtered) table content to a CSV or TXT file.
2.  **Update `HistoryManager` in `history_manager.py`**:
    *   Ensure `log_action` includes a "severity" field (e.g., "INFO", "WARNING", "ERROR") based on the "status" or a new parameter. For now, I'll map "SUCCESS" to "INFO", "FAILURE" to "ERROR", and potentially add "WARNING" for other cases if applicable.

Let's start by modifying 

---

