<!-- Generated by SpecStory -->

# *   **Rule Templates:** Offer predefined rule temp (2025-06-09 22:15:20)

_**User**_

*   **Rule Templates:** Offer predefined rule templates for common scenarios (e.g., "Organize Screenshots," "Clean up old Downloads") that users can quickly apply and customize.

---

_**Assistant**_

Okay, I will add the predefined rule templates to your `constants.py` file.

This will involve:
1.  Defining a new constant `RULE_TEMPLATES` in `constants.py` with a list of template dictionaries. Each dictionary will contain a `name` for the template and a list of `rules`.

 
````

````

````

````

````

````
I've added the `RULE_TEMPLATES` to `constants.py` and updated `ui_config_window.py` to include an "Apply Template" button. This button opens a menu allowing users to select a predefined template. When a template is selected, the rules defined in it are applied. This may involve adding new folders to be monitored or updating the rules for existing ones. I also updated `config_manager.py` to support these changes.

There were some linting errors in `ui_config_window.py` after the initial modification. I will attempt to fix them. 
````

````
I've added the rule templates to `constants.py` and updated `ui_config_window.py` to allow users to apply these templates. I also modified `config_manager.py` to correctly handle the new rule fields and integrate with the template functionality.

There are a few remaining linting errors in `ui_config_window.py`. I'll address the type hint issue for `update_rule_inputs` and ensure the list widget access is safe.

 
````

````
I've added the rule templates to `constants.py` and updated the UI in `ui_config_window.py` to allow users to apply these templates. This includes a new "Apply Template" button, a menu to display available templates, and the logic to add or update folder configurations based on the selected template. I've also updated `config_manager.py` to support these changes.

---

_**User**_

where are these templated selected from?

---

_**Assistant**_

The rule templates are selected from a menu that appears when you click the "Apply Template" button in the AutoTidy Configuration window. This button is located in the top controls section, next to the "Add Folder" button.

When you click "Apply Template", a dropdown menu will show the names of the predefined templates (e.g., "Organize Screenshots," "Clean up old Downloads"). You can then click on one of these template names to apply its rules.

---

_**User**_

Lets redo templates with these folders, se

%UserProfile%\Downloads

%UserProfile%\Pictures\Screenshots

%UserProfile%\Videos\Captures

C:\Windows\Temp and %LocalAppData%\Temp


%UserProfile%\Videos$$Game Name]




---

_**Assistant**_

Okay, I will redefine the `RULE_TEMPLATES` in `constants.py` based on the folders you've provided.

Here's how the new templates will be structured:

1.  **Clean up Downloads:** Deletes files older than 90 days from `%UserProfile%\Downloads`.
2.  **Organize Screenshots:** Moves PNG and JPG files from `%UserProfile%\Pictures\Screenshots` to an "Organized Screenshots" subfolder.
3.  **Organize Video Captures:** Moves MP4, AVI, and MKV files older than 30 days from `%UserProfile%\Videos\Captures` to an "Archived Captures" subfolder.
4.  **Clean Temporary Files:** Deletes all files from `` and `%LocalAppData%\Temp`.
5.  **Organize Game Captures (Example):** Moves MP4 files from a game-specific video folder (e.g., `%UserProfile%\Videos\[Your Game Name]\Captures`) to an "Organized" subfolder. You'll need to customize the path for the specific game.

I will now update `constants.py`.

---

_**User**_

lets edit 2 like this: the screenshots are formatted like this "Screenshot 2023-03-13 223350.png" so lets only move those.

---

_**Assistant**_



---

