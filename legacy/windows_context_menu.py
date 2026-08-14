import sys
import winreg
import os
import logging

APP_NAME_ADD = "AutoTidyAddTo"
APP_NAME_EXCLUDE = "AutoTidyExcludeFrom"
APP_DESCRIPTION_ADD = "Add to AutoTidy"
APP_DESCRIPTION_EXCLUDE = "Exclude from AutoTidy"

# Path to the main.py script.
# IMPORTANT: This should be the absolute path to main.py or the installed executable.
# For development, we use the path to main.py with the current Python interpreter.
SCRIPT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "main.py"))
PYTHON_EXE = sys.executable
logger = logging.getLogger(__name__)


def _configure_cli_logging():
    """Set a predictable log format for command-line usage."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def create_registry_key(key_path, command_name, command_description, command_action_arg):
    """
    Creates a registry key for the context menu item.
    """
    try:
        # Create the main key for the application context menu
        key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_path)
        winreg.SetValue(key, "", winreg.REG_SZ, command_description)
        winreg.CloseKey(key)

        # Create the command key
        command_key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, f"{key_path}\\command")
        # Set the command to execute. %V is replaced by the selected folder path.
        # Using %V as it's generally more robust for paths than %1, especially with spaces.
        command_to_run = f'''"{PYTHON_EXE}" "{SCRIPT_PATH}" {command_action_arg} "%V"'''
        winreg.SetValue(command_key, "", winreg.REG_SZ, command_to_run)
        winreg.CloseKey(command_key)
        logger.info("Successfully created context menu item: %s", command_description)
    except Exception as e:
        logger.error("Error creating registry key %s: %s", command_name, e)
        logger.error("Please ensure you are running this script as an administrator.")

def delete_registry_key(command_name):
    """
    Deletes a registry key for the context menu item.
    """
    try:
        winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, f"Directory\\shell\\{command_name}\\command")
        winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, f"Directory\\shell\\{command_name}")
        logger.info("Successfully removed context menu item: %s", command_name)
    except FileNotFoundError:
        logger.info("Context menu item %s not found (already removed or never installed).", command_name)
    except Exception as e:
        logger.error("Error deleting registry key %s: %s", command_name, e)
        logger.error("Please ensure you are running this script as an administrator.")

def _is_admin() -> bool:
    """Return True if the current process has administrator privileges."""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def register_context_menu():
    """Registers the context menu items."""
    if not _is_admin():
        logger.error("Administrator privileges are required to register context menu items.")
        logger.error("Please run this script as Administrator.")
        sys.exit(1)
    logger.info("Registering context menu items...")
    create_registry_key(f"Directory\\shell\\{APP_NAME_ADD}", APP_NAME_ADD, APP_DESCRIPTION_ADD, "--add-folder")
    create_registry_key(f"Directory\\shell\\{APP_NAME_EXCLUDE}", APP_NAME_EXCLUDE, APP_DESCRIPTION_EXCLUDE, "--exclude-folder")
    logger.info("Context menu registration process finished.")
    logger.info("You might need to restart Explorer or log out/in for changes to take effect.")

def unregister_context_menu():
    """Unregisters the context menu items."""
    if not _is_admin():
        logger.error("Administrator privileges are required to unregister context menu items.")
        logger.error("Please run this script as Administrator.")
        sys.exit(1)
    logger.info("Unregistering context menu items...")
    delete_registry_key(APP_NAME_ADD)
    delete_registry_key(APP_NAME_EXCLUDE)
    logger.info("Context menu unregistration process finished.")
    logger.info("You might need to restart Explorer or log out/in for changes to take effect.")

if __name__ == "__main__":
    _configure_cli_logging()
    if len(sys.argv) > 1:
        action = sys.argv[1].lower()
        if action == "register":
            register_context_menu()
        elif action == "unregister":
            unregister_context_menu()
        else:
            logger.error("Unknown action: %s", sys.argv[1])
            logger.info("Usage: python windows_context_menu.py [register|unregister]")
    else:
        logger.info("Usage: python windows_context_menu.py [register|unregister]")
        logger.info("Example: python windows_context_menu.py register")

