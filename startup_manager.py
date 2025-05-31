"""
Manages application autostart behavior across different operating systems.

This module provides functionality to enable or disable the application
from starting automatically when the user logs in. It currently supports
Windows (via registry manipulation) and Linux (via .desktop files in
~/.config/autostart/).
"""
import sys
import os
import platform
import winreg # Only available on Windows

APP_REGISTRY_PATH = r"Software\\Microsoft\\Windows\\CurrentVersion\\Run"

def _get_executable_path() -> str:
    """
    Determines the absolute path to the currently running executable or the main script.

    If the application is running as a bundled executable (e.g., via PyInstaller),
    `sys.executable` is used. Otherwise (running as a script), `sys.argv[0]`
    (the path to the script) is used.

    Returns:
        The absolute path to the executable or main script file.
    """
    if getattr(sys, 'frozen', False):
        # Running as a bundled executable (PyInstaller)
        return os.path.abspath(sys.executable)
    else:
        # Running as a script - return path to script
        # The registry value will need to include the python interpreter
        return os.path.abspath(sys.argv[0])

def _get_windows_run_command(app_path: str) -> str:
    """
    Constructs the command string to be stored in the Windows registry for autostart.

    If running as a bundled executable, the command is simply the quoted path
    to the executable. If running as a script, it constructs a command that
    invokes `pythonw.exe` (to avoid a console window) with the script path.

    Args:
        app_path: The absolute path to the executable or main script.

    Returns:
        The formatted command string suitable for the Windows registry.
    """
    if getattr(sys, 'frozen', False):
        # Path to the executable
        return f'"{app_path}"'
    else:
        # Path to the script, needs python interpreter
        python_executable = sys.executable
        # Use pythonw.exe to avoid console window if the original is python.exe
        if python_executable.lower().endswith("python.exe"):
            python_executable = python_executable[:-10] + "pythonw.exe"
        return f'"{python_executable}" "{app_path}"'


def set_autostart(enable: bool, app_name: str) -> bool:
    """
    Configures the application to start automatically on system login.

    This function handles platform-specific mechanisms:
    - Windows: Modifies the `HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run`
               registry key.
    - Linux: Creates or removes a .desktop file in `~/.config/autostart/`.
    - Other OS: Prints a warning and returns False, as autostart is not implemented.

    Args:
        enable: If True, enables autostart. If False, disables autostart.
        app_name: The name of the application, used for the registry key on Windows
                  or the .desktop filename on Linux. This should be unique to
                  avoid conflicts.

    Returns:
        True if the autostart setting was successfully applied (or if the desired
        state was already set, e.g., disabling an already non-existent entry).
        False if an error occurred or if autostart is not supported on the
        current platform.
    """
    app_path = _get_executable_path()
    system = platform.system()

    if system == "Windows":
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, APP_REGISTRY_PATH, 0, winreg.KEY_WRITE)
            if enable:
                command = _get_windows_run_command(app_path)
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, command)
                print(f"INFO: Enabled autostart for {app_name} with command: {command}")
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                    print(f"INFO: Disabled autostart for {app_name}")
                except FileNotFoundError:
                    print(f"INFO: Autostart entry for {app_name} not found, nothing to disable.") # Not an error
            winreg.CloseKey(key)
            return True
        except OSError as e:
            print(f"ERROR: Failed to access registry for autostart setting: {e}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"ERROR: Unexpected error setting autostart: {e}", file=sys.stderr)
            return False

    elif system == "Linux":
        # Placeholder for Linux .desktop file creation/deletion
        autostart_dir = os.path.expanduser("~/.config/autostart")
        desktop_file_path = os.path.join(autostart_dir, f"{app_name.lower()}.desktop")

        if enable:
            # Ensure the autostart directory exists
            os.makedirs(autostart_dir, exist_ok=True)

            # Determine the command to run
            if getattr(sys, 'frozen', False):
                exec_command = f'"{app_path}"' # Path to executable
            else:
                exec_command = f'"{sys.executable}" "{app_path}"' # python /path/to/main.py

            desktop_content = f"""\
[Desktop Entry]
Type=Application
Name={app_name}
Exec={exec_command}
Comment=Starts {app_name} application
Terminal=false
"""
            try:
                with open(desktop_file_path, "w") as f:
                    f.write(desktop_content)
                os.chmod(desktop_file_path, 0o755) # Make executable if needed? Usually not for .desktop
                print(f"INFO: Enabled autostart for {app_name} via {desktop_file_path}")
                return True
            except Exception as e:
                print(f"ERROR: Failed to create .desktop file {desktop_file_path}: {e}", file=sys.stderr)
                return False
        else:
            if os.path.exists(desktop_file_path):
                try:
                    os.remove(desktop_file_path)
                    print(f"INFO: Disabled autostart for {app_name} by removing {desktop_file_path}")
                    return True
                except Exception as e:
                    print(f"ERROR: Failed to remove .desktop file {desktop_file_path}: {e}", file=sys.stderr)
                    return False
            else:
                print(f"INFO: Autostart .desktop file for {app_name} not found, nothing to disable.")
                return True # Not an error if already disabled

    else:
        print(f"WARNING: Autostart not implemented for operating system: {system}", file=sys.stderr)
        return False # Indicate not supported/implemented

# Example usage (for testing):
# if __name__ == "__main__":
#     APP_NAME_TEST = "AutoTidyTest"
#     print("Attempting to enable autostart...")
#     if set_autostart(True, APP_NAME_TEST):
#         print("Enable successful (check registry/autostart dir)")
#     else:
#         print("Enable failed.")

#     input("Press Enter to disable autostart...")

#     print("Attempting to disable autostart...")
#     if set_autostart(False, APP_NAME_TEST):
#         print("Disable successful (check registry/autostart dir)")
#     else:
#         print("Disable failed.")
