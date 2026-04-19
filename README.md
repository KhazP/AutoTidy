<img src="assets/autotidyicon.ico" alt="AutoTidy Icon" width="96"/>

# 🚀 AutoTidy — Automated File Organizer

[![Version](https://img.shields.io/badge/version-1.5.0-blue.svg?style=for-the-badge)](constants.py)
[![License: MPL-2.0](https://img.shields.io/badge/License-MPL_2.0-blue.svg?style=for-the-badge)](LICENSE)
[![Contributions Welcome](https://img.shields.io/badge/contributions-welcome-orange.svg?style=for-the-badge)](#-contributing)

> **Automatically tidy up cluttered folders.**  
> AutoTidy watches chosen folders and organizes files using simple rules you set. Move, copy, or delete files based on age and/or name patterns.

---

## 📖 Table of Contents

- [Overview](#overview)
- [What’s New in 1.5](#whats-new-in-15)
- [✨ Core Features](#-core-features)
- [⚙️ How It Works](#️-how-it-works)
- [📦 Installation](#-installation)
- [🛠️ Run from Source](#️-run-from-source)
- [🔧 Configuration](#-configuration)
- [🗂️ Logs, History & Undo](#️-logs-history--undo)
- [💻 Tech Stack](#-tech-stack)
- [🔁 Reproducibility & Security](#-reproducibility--security)
- [🙏 Dependencies & Acknowledgments](#-dependencies--acknowledgments)
- [📚 Citation & Checklist Audit](#-citation--checklist-audit)
- [📁 Key Files](#-key-files)
- [⚠️ Known Limitations](#️-known-limitations)
- [🗺️ Roadmap / Future Ideas](#️-roadmap--future-ideas)
- [🤝 Contributing](#-contributing)
- [📜 Disclaimer](#-disclaimer)
- [📄 License](#-license)

---

## Overview

**AutoTidy** helps keep folders like **Downloads**, **Screenshots**, or your **Desktop** clean.  
You choose the folders and set simple rules. AutoTidy does the rest in the background on a schedule you control.

---

## What’s New in 1.5

- **AND / OR rule logic per folder** — match by **all** conditions (AND) or **any** (OR). Setting **age = 0** makes it a name-only rule.
- **Enable/Disable rules** without deleting them.
- **Custom destinations** for move/copy with a **Browse…** button; supports env vars and relative paths.
- **Exclusions everywhere**: per-folder **ignore patterns** (glob or regex) + a **Global Excluded Folders** list.
- **Preview Matches** — see what a rule will catch before you run it.
- **Better logs & history**: timestamps, severity filter, keyword search, export, “Skipped” entries, and **double-click to open paths**.
- **Status at a glance**: colored status dot, Dry-Run indicator, and **Next Run** time.
- **Notification levels respected** end-to-end (None / Errors / Summary / All).
- **Unique scan IDs** so each run is clearly grouped in History.
- **Windows-only startup** toggle; it’s disabled on other platforms.

---

## ✨ Core Features

- **Watch multiple folders**.
- **Rule-based actions**: Move, Copy, Delete to Trash, or Permanently Delete.
- **Flexible matching**:
  - **Age (days)** and/or **Filename pattern** (wildcards or regex).
  - Choose **AND** or **OR** logic per folder.
- **Custom archive routing**:
  - Template-based archive paths (e.g., `_Cleanup/{YYYY}-{MM}-{DD}`).
  - Or send to **your own destination folder**.
- **Exclusions**:
  - **Per-folder** ignore patterns (glob/regex).
  - **Global excluded folders** that apply to all rules.
- **Dry Run mode** to simulate changes safely.
- **Tray app** with configurable **scan interval**.
- **Logs & History** with filters, search, export, and **Undo** for Move/Copy.
- **Desktop notifications** that follow your chosen **notification level**.

---

## ⚙️ How It Works

1. **Add folders** to monitor.
2. **Create a rule** per folder:
   - Set **Age (days)** and a **Filename pattern** (e.g., `*.jpg`, `temp_*` or regex).
   - Pick **AND** (all must match) or **OR** (any can match).
   - Choose the **Action**: Move, Copy, Delete to Trash, or Permanently Delete.
   - (Optional) Set a **custom destination** for Move/Copy with **Browse…**.
   - (Optional) Add **exclusion patterns** to skip files you never want touched.
3. **Preview Matches** (optional) to see sample results.
4. **Start Monitoring**. AutoTidy scans on your schedule and applies the rules.

> **Note on logic:**  
> - **AND** = file must match **age** *and* **name pattern** (unless age is 0).  
> - **OR** = file is processed if it matches **age** *or* **name pattern**.

---

## 📦 Installation

### Windows (recommended)
- Download the **Setup** EXE from Releases (or build it yourself).
- The installer supports **Per-user** (no admin) or **All users** (admin) installation.
- Auto-created Start Menu shortcut; optional Desktop shortcut.

### Linux / macOS
- Run from source (see below) or package with PyInstaller.  
- The **startup on login** toggle is **Windows-only** in v1.5.

---

## 🛠️ Run from Source

**Prereqs**
- Python **3.10+**

**Recommended environment setup**

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
```

**Install deps**

```bash
pip install -r requirements.txt
```

**Run tests**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest
```

**Run**

```bash
python main.py
```

**Build (example)**

```bash
pyinstaller --noconfirm --clean --name AutoTidy --icon assets/autotidyicon.ico --add-data "assets/autotidyicon.ico;assets" main.py
```

(Adjust for your layout; see your `dist/` output. The Windows installer is built with Inno Setup.)

---

## 🔧 Configuration

* Rules and settings are saved to a user config (e.g., `%APPDATA%/AutoTidy/config.json` on Windows, `~/.config/AutoTidy/config.json` on Linux).
* **Notification Level**: None / Errors Only / Summary / All.
* **Scan Interval**: minutes between scans.
* **Archive Template**: `_Cleanup/{YYYY}-{MM}-{DD}` by default; supports `{YYYY}`, `{MM}`, `{DD}`, `{FILENAME}`, `{EXT}`, `{ORIGINAL_FOLDER_NAME}` and more.
* **Global Excluded Folders**: list that always gets ignored.

### Exclusion Patterns (per folder)

* **Glob examples**

  * `*.tmp` — ignore temp files
  * `cache/` — ignore a `cache` directory
  * `~$*.docx` — ignore Office autosave files
* **Regex examples** (when regex is enabled)

  * `^backup_\d{4}` — `backup_2024*` etc.
  * `\.(log|bak)$` — endings like `.log` or `.bak`

> Exclusions are checked first. If a file matches an exclusion, it’s **skipped**, even if it matches your rule.

---

## 🗂️ Logs, History & Undo

* **Logs**: timestamps, severity filter (Info/Warning/Error), keyword search, **Clear/Copy/Save**.
* **History**:

  * Each scan has a **unique ID**.
  * Filter and search; see **Skipped** entries (e.g., due to exclusions).
  * **Double-click** a row to open the file path (or copy it if missing).
  * **Undo** Move/Copy actions from History/Undo dialog.

---

## 💻 Tech Stack

* **Python** (3.10+)
* **PyQt6** for the interface
* **Threaded worker** for background scans
* Uses standard libs: `os`, `pathlib`, `shutil`, `datetime`, `json`, `threading`, `queue`, `fnmatch`, and platform helpers.

---

## 🔁 Reproducibility & Security

* AutoTidy behavior is deterministic for a given config and filesystem state; no stochastic model training/inference is used.
* The project uses version-controlled source and automated tests in `tests/`.
* CI runs pytest with coverage via `.github/workflows/tests.yml`.
* No API keys or credentials are required for core functionality. Do not commit sensitive local paths or private data snapshots.

---

## 🙏 Dependencies & Acknowledgments

* Runtime dependencies are declared in `requirements.txt` and `pyproject.toml`.
* Primary libraries used:

  * `PyQt6` for the desktop UI.
  * `Send2Trash` for safe file deletion to recycle bin/trash.

* Contributor workflow and collaboration details are documented in the Contributing section.

---

## 📚 Citation & Checklist Audit

* Citation metadata is available in `CITATION.cff`.
* Code-checklist audit results are tracked in `docs/CODE_CHECKLIST_AUDIT.md`.
* Data/model checklist items are marked not applicable because AutoTidy is a desktop file-organization utility rather than a model-training repository.

---

## 📁 Key Files

<details>
<summary>Click to expand</summary>

* `main.py` — App entry; sets up tray icon and windows.
* `ui_config_window.py` — Main configuration window and rule editor.
* `ui_settings_dialog.py` — App-wide settings (interval, archive template, notifications, etc.).
* `worker.py` — Background scanner that applies rules and posts results.
* `config_manager.py` — Loads/saves config; templates; global exclusions; action normalization.
* `startup_manager.py` — Windows startup handling; disabled on non-Windows in v1.5.
* `utils.py` — Helpers (file checks, path rendering, previews).
* `constants.py` — App constants and placeholders.
* `tests/` — Automated tests and PyQt stubs.
* `assets/autotidyicon.ico` — App icon.
* `README.md` — This file.

</details>

---

## ⚠️ Known Limitations

* Very large folders can take time to scan (runs in a background thread).
* Regex must be valid; invalid patterns are reported and ignored.
* Frequent scans across many large folders can increase resource use.
* Filename collisions are handled with simple counters (e.g., `_1`, `_2`).

---

## 🗺️ Roadmap / Future Ideas

* Specific-time scheduling options (beyond interval).
* Smarter collision handling / conflict resolution.
* Optional, more detailed per-rule analytics.

---

## 🤝 Contributing

1. **Fork** the repo
2. Create a branch: `git checkout -b feat/my-improvement`
3. **Develop & test** your changes
4. Commit: `git commit -m "feat: my improvement"`
5. Push: `git push origin feat/my-improvement`
6. Open a **Pull Request** to `main`

Please keep changes aligned with the current structure and style.

---

## 📜 Disclaimer

AutoTidy **moves or deletes files** based on your rules. Test with **non-critical folders** first.
Use at your own risk; the authors aren’t liable for data loss.

---

## 📄 License

MPL-2.0 — see [LICENSE](LICENSE).
