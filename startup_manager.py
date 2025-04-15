\
import sys
import os
import platform
import winreg # Only available on Windows

APP_REGISTRY_PATH = r"Software\\Microsoft\\Windows\\CurrentVersion\\Run"

def _get_executable_path() -> str:
    """Gets the path to the executable or the main script."""
    if getattr(sys, 'frozen', False):
        # Running as a bundled executable (PyInstaller)
        return os.path.abspath(sys.executable)
    else:
        # Running as a script - return path to script
        # The registry value will need to include the python interpreter
        return os.path.abspath(sys.argv[0])

def _get_windows_run_command(app_path: str) -> str:
    """Constructs the command to be stored in the Windows registry."""
    if getattr(sys, 'frozen', False):
        # Path to the executable
        return f'"{app_path}"'
    else:
        # Path to the script, needs python interpreter
        python_executable = sys.executable
        # Use pythonw.exe to avoid console window
        if python_executable.lower().endswith("python.exe"):
            python_executable = python_executable[:-10] + "pythonw.exe"
        return f'"{python_executable}" "{app_path}"'


def set_autostart(enable: bool, app_name: str):
    """
    Configures the application to start automatically on system login.

    Args:
        enable: True to enable autostart, False to disable.
        app_name: The name for the registry key (should be unique).

    Returns:
        True if the operation was successful, False otherwise.
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
