import sys
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon # QSystemTrayIcon might only be for type hint if passed
from PyQt6.QtGui import QIcon # QIcon might not be needed here directly, but good for context

# Enum for message icons could be defined here if desired,
# but QSystemTrayIcon.MessageIcon is already an enum.

class NotificationManager:
    """Handles desktop notifications via a QSystemTrayIcon."""

    def __init__(self, app_name: str, tray_icon: QSystemTrayIcon):
        """
        Initializes the NotificationManager.

        Args:
            app_name: The name of the application.
            tray_icon: The QSystemTrayIcon instance to use for showing messages.
                       This is expected to be managed (created, shown) by the main application.
        """
        self.app_name = app_name
        self.tray_icon = tray_icon

    def show_notification(
        self,
        title: str,
        message: str,
        icon_type: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information,
        duration_ms: int = 3000  # Default duration 3 seconds
    ):
        """
        Displays a desktop notification using the application's system tray icon.

        Args:
            title: The title of the notification.
            message: The main message content of the notification.
            icon_type: The icon to display (Information, Warning, Critical).
            duration_ms: How long the notification should be displayed (in milliseconds).
        """
        if self.tray_icon and self.tray_icon.isVisible():
            # Prepend app_name to title for clarity, if not already there
            full_title = f"{self.app_name} - {title}" if not title.startswith(self.app_name) else title
            self.tray_icon.showMessage(full_title, message, icon_type, duration_ms)
        else:
            # Fallback if tray icon isn't available or visible
            # This could log to a file or console. For now, print to stderr.
            print(f"NotificationManager: Tray icon not available or not visible. Cannot show notification: '{title}' - '{message}'", file=sys.stderr)

    def info(self, title: str, message: str, duration_ms: int = 3000):
        """Helper to show an informational notification."""
        self.show_notification(title, message, QSystemTrayIcon.MessageIcon.Information, duration_ms)

    def warning(self, title: str, message: str, duration_ms: int = 4000): # Slightly longer for warnings
        """Helper to show a warning notification."""
        self.show_notification(title, message, QSystemTrayIcon.MessageIcon.Warning, duration_ms)

    def error(self, title: str, message: str, duration_ms: int = 5000): # Longer for errors
        """Helper to show an error/critical notification."""
        self.show_notification(title, message, QSystemTrayIcon.MessageIcon.Critical, duration_ms)

if __name__ == '__main__':
    # Example Usage (requires a running QApplication and a visible QSystemTrayIcon)
    # This is a simplified example and might not work standalone without proper app setup.
    app = QApplication(sys.argv)

    # Check if system tray is available
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("NotificationManager Example: System tray not available. Cannot run example.", file=sys.stderr)
        sys.exit(1)

    # Create a dummy tray icon for the example
    # In a real app, this icon would be managed elsewhere (e.g., main.py)
    try:
        # Attempt to load an icon, provide a path to a real .ico or .png file
        # For testing, we might need a fallback if no icon file is handy.
        # Let's assume a placeholder icon or skip if not found for this basic test.
        icon_path = "icon.png" # Replace with a valid path to an icon if available
        if not os.path.exists(icon_path):
             print(f"NotificationManager Example: Icon file '{icon_path}' not found. Tray icon may not be visible.", file=sys.stderr)
             # Create a default icon if possible, though QIcon() without args is often not enough.
             # For this example, we'll proceed, but the tray might not show.
             app_icon = QIcon() # Placeholder
        else:
            app_icon = QIcon(icon_path)

        tray = QSystemTrayIcon(app_icon)
        tray.setToolTip("Notification Manager Test")
        tray.show() # Important: Tray icon must be visible to show messages

        # If tray is still not visible (e.g. on systems that hide icons aggressively)
        # this test might still fail to show notifications.
        if not tray.isVisible():
            print("NotificationManager Example: Tray icon was shown but is not visible. Notifications might not appear.", file=sys.stderr)
            # Attempting to show a message might still work on some systems or queue it.

    except Exception as e:
        print(f"NotificationManager Example: Error setting up dummy tray icon: {e}", file=sys.stderr)
        # Depending on the error, tray might be None or unusable.
        # For this example, we'll create a dummy tray object to allow NotificationManager instantiation,
        # though notifications won't show.
        class DummyTray:
            isVisible = lambda: False # Mock isVisible
            showMessage = lambda *args: print("DummyTray: showMessage called", args) # Mock showMessage
        tray = DummyTray()


    notifier = NotificationManager(app_name="TestApp", tray_icon=tray)

    print("NotificationManager Example: Attempting to show notifications...")
    notifier.info("Test Info", "This is an informational message.")
    notifier.warning("Test Warning", "This is a warning message.")
    notifier.error("Test Error", "This is an error message.")

    # Keep the app running for a bit to see notifications if they work
    # In a real app, QApplication.exec() would be called.
    # For this script, a simple timer or input can pause execution.
    print("NotificationManager Example: Check your system tray for notifications.")
    print("NotificationManager Example: If tray icon isn't fully set up or visible, messages go to stderr via fallback.")

    # A minimal event loop to allow tray icon messages to process (optional for script test)
    # try:
    #     app.exec() # This would block until quit, not ideal for a simple script test.
    # except KeyboardInterrupt:
    #     print("Exiting example.")
    # finally:
    #     if hasattr(tray, 'hide'): # Clean up by hiding the tray icon
    #         tray.hide()

    # For non-blocking test, just indicate completion.
    print("NotificationManager Example: Test complete. If no GUI was visible, this is normal for a script test.")
    # Note: Showing QSystemTrayIcon messages without a persistent QApplication event loop
    # can be unreliable. This example is primarily for class structure testing.

```
