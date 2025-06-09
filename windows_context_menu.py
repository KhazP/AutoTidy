import sys
import winreg
import os

APP_NAME_ADD = "AutoTidyAddTo"
APP_NAME_EXCLUDE = "AutoTidyExcludeFrom"
APP_DESCRIPTION_ADD = "Add to AutoTidy"
APP_DESCRIPTION_EXCLUDE = "Exclude from AutoTidy"

# Path to the main.py script.
# IMPORTANT: This should be the absolute path to main.py or the installed executable.
# For development, we use the path to main.py with the current Python interpreter.
SCRIPT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "main.py"))
PYTHON_EXE = sys.executable

def create_registry_key(key_path, command_name, command_description, command_action_arg):
    """
    Creates a registry key for the context menu item.
    """
    try:
        # Create the main key for the application context menu
        key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, f"Directory\\shell\\{command_name}")
        winreg.SetValue(key, "", winreg.REG_SZ, command_description) # Fix: Use "" for default value
        winreg.CloseKey(key)

        # Create the command key
        command_key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, f"Directory\\shell\\{command_name}\\command")
        # Set the command to execute. %V is replaced by the selected folder path.
        # Using %V as it's generally more robust for paths than %1, especially with spaces.
        command_to_run = f'''"{PYTHON_EXE}" "{SCRIPT_PATH}" {command_action_arg} "%V"'''
        winreg.SetValue(command_key, "", winreg.REG_SZ, command_to_run) # Fix: Use "" for default value
        winreg.CloseKey(command_key)
        print(f"Successfully created context menu item: {command_description}")
    except Exception as e:
        print(f"Error creating registry key {command_name}: {e}")
        print("Please ensure you are running this script as an administrator.")

def delete_registry_key(command_name):
    """
    Deletes a registry key for the context menu item.
    """
    try:
        winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, f"Directory\\shell\\{command_name}\\command")
        winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, f"Directory\\shell\\{command_name}")
        print(f"Successfully removed context menu item: {command_name}")
    except FileNotFoundError:
        print(f"Context menu item {command_name} not found (already removed or never installed).")
    except Exception as e:
        print(f"Error deleting registry key {command_name}: {e}")
        print("Please ensure you are running this script as an administrator.")

def register_context_menu():
    """Registers the context menu items."""
    print("Registering context menu items...")
    create_registry_key(f"Directory\\shell\\{APP_NAME_ADD}", APP_NAME_ADD, APP_DESCRIPTION_ADD, "--add-folder")
    create_registry_key(f"Directory\\shell\\{APP_NAME_EXCLUDE}", APP_NAME_EXCLUDE, APP_DESCRIPTION_EXCLUDE, "--exclude-folder")
    print("Context menu registration process finished.")
    print("You might need to restart Explorer or log out/in for changes to take effect.")

def unregister_context_menu():
    """Unregisters the context menu items."""
    print("Unregistering context menu items...")
    delete_registry_key(APP_NAME_ADD)
    delete_registry_key(APP_NAME_EXCLUDE)
    print("Context menu unregistration process finished.")
    print("You might need to restart Explorer or log out/in for changes to take effect.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        action = sys.argv[1].lower()
        if action == "register":
            register_context_menu()
        elif action == "unregister":
            unregister_context_menu()
        else:
            print(f"Unknown action: {sys.argv[1]}")
            print("Usage: python windows_context_menu.py [register|unregister]")
    else:
        print("Usage: python windows_context_menu.py [register|unregister]")
        print("Example: python windows_context_menu.py register")

