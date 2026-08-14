//! The IPC surface. This is the contract between the Rust shell and the React
//! frontend; `src/lib/api.ts` mirrors it one-for-one.
//!
//! Every command returns `Result<T, String>` because Tauri surfaces `Err` as a
//! rejected promise, and a stringly error is what the UI can actually display.
//! Engine-internal detail is logged via `tracing` instead of being marshalled.

use autotidy_core::config::{Config, ConfigStore, Rule};
use autotidy_core::engine::{EngineHandle, EngineStatus};
use autotidy_core::history::{HistoryLog, HistoryRecord, Status};
use autotidy_core::rule::CompiledRule;
use autotidy_core::scan::guard_paths;
use autotidy_core::template::{self, Placeholders};
use autotidy_core::undo::{self, BatchResult, RunSummary};
use serde::Serialize;
use serde_json::json;
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

use crate::platform::StaleVerb;
use crate::state::AppState;

/// One page of history, plus the total so the UI can size its scrollbar without
/// loading the whole file. 1.5.0 paged at a fixed 500 with a "Load All" button;
/// the frontend virtualises instead, but the engine still pages so a 10 MB
/// history never crosses the IPC boundary in one message.
///
/// **Ordering is newest-first, and that is part of the contract.** The table
/// sorts and filters only the rows it has loaded, so it can only be correct if
/// offset 0 is the most recent record. Reverting to `read_all`'s natural
/// oldest-first order would silently show the oldest page labelled as the
/// newest — see `history_page`.
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HistoryPage {
    pub records: Vec<HistoryRecord>,
    pub total: usize,
    pub offset: usize,
}

/// A rule preview: which files would match right now, without acting.
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RulePreview {
    /// Full paths of matching files, capped at `limit`.
    pub matches: Vec<String>,
    /// Total matches found, which may exceed `matches.len()`.
    pub total: usize,
    /// Where those files would land, for the first match.
    pub example_destination: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AppInfo {
    pub version: String,
    pub config_path: String,
    pub history_path: String,
    pub log_path: String,
    pub autostart_enabled: bool,
    pub context_menu_registered: bool,
}

/// Turn any error with a `Display` into the string the UI shows, logging the
/// full value on the way out so the log keeps the detail the toast drops.
fn fail(context: &'static str, err: impl std::fmt::Display) -> String {
    tracing::error!(context, %err);
    format!("{context}: {err}")
}

fn history_log(state: &AppState) -> HistoryLog {
    HistoryLog::new(state.store.history_path())
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

/// Load, mutate, save.
///
/// Every rule-level command goes through here rather than caching a `Config` in
/// `AppState`. Holding a copy in memory is exactly what let 1.5.0 clobber
/// `config.json` on quit, and the engine re-reads the file each cycle anyway,
/// so a cached copy would buy nothing.
fn mutate<T>(
    state: &AppState,
    context: &'static str,
    f: impl FnOnce(&mut Config) -> T,
) -> Result<T, String> {
    let mut config = state.store.load().map_err(|e| fail(context, e))?;
    let outcome = f(&mut config);
    state.store.save(&config).map_err(|e| fail(context, e))?;
    Ok(outcome)
}

#[tauri::command]
pub fn get_config(state: tauri::State<'_, AppState>) -> Result<Config, String> {
    state.store.load().map_err(|e| fail("load config", e))
}

/// Persist a whole config. Used by the settings view, which edits many fields
/// at once. Rule-level edits go through the narrower commands below so two
/// windows can't clobber each other's unrelated changes.
#[tauri::command]
pub fn save_config(state: tauri::State<'_, AppState>, config: Config) -> Result<(), String> {
    state
        .store
        .save(&config)
        .map_err(|e| fail("save config", e))
}

#[tauri::command]
pub fn add_rule(state: tauri::State<'_, AppState>, path: String) -> Result<bool, String> {
    mutate(&state, "add folder", |config| {
        config.add_folder(Path::new(&path))
    })
}

#[tauri::command]
pub fn update_rule(state: tauri::State<'_, AppState>, rule: Rule) -> Result<bool, String> {
    mutate(&state, "update rule", |config| {
        match config.find_rule_mut(&rule.path) {
            Some(existing) => {
                *existing = rule;
                true
            }
            None => false,
        }
    })
}

#[tauri::command]
pub fn remove_rule(state: tauri::State<'_, AppState>, path: String) -> Result<bool, String> {
    mutate(&state, "remove rule", |config| config.remove_folder(&path))
}

#[tauri::command]
pub fn add_excluded_folder(
    state: tauri::State<'_, AppState>,
    path: String,
) -> Result<bool, String> {
    mutate(&state, "add excluded folder", |config| {
        config.add_excluded_folder(Path::new(&path))
    })
}

#[tauri::command]
pub fn remove_excluded_folder(
    state: tauri::State<'_, AppState>,
    path: String,
) -> Result<bool, String> {
    mutate(&state, "remove excluded folder", |config| {
        let before = config.excluded_folders.len();
        config.excluded_folders.retain(|e| !same_path(e, &path));
        config.excluded_folders.len() != before
    })
}

/// Compare two configured paths.
///
/// `Config::add_excluded_folder` stores the *normalised* path, so the string the
/// UI holds may differ from what the user originally picked. Comparing
/// normalised forms means a remove always matches the entry it was rendered
/// from, and on Windows it is case-insensitive because the filesystem is.
fn same_path(left: &str, right: &str) -> bool {
    if left == right {
        return true;
    }
    let left = autotidy_core::config::normalize(Path::new(left));
    let right = autotidy_core::config::normalize(Path::new(right));
    if cfg!(windows) {
        left.as_os_str()
            .to_string_lossy()
            .eq_ignore_ascii_case(&right.as_os_str().to_string_lossy())
    } else {
        left == right
    }
}

/// The rule templates 1.5.0 shipped in `constants.RULE_TEMPLATES`, with paths
/// resolved against the current user's home directory.
#[tauri::command]
pub fn rule_templates() -> Result<serde_json::Value, String> {
    Ok(build_rule_templates(&home_dir(), &temp_dir()))
}

/// Same lookup order the rest of the codebase uses, so a template path and a
/// config path never disagree about where "home" is.
fn home_dir() -> PathBuf {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .filter(|h| !h.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

/// `constants._TEMP`: `%LocalAppData%\Temp` on Windows, the system temp dir
/// elsewhere.
fn temp_dir() -> PathBuf {
    #[cfg(windows)]
    {
        if let Some(local) = std::env::var_os("LOCALAPPDATA").filter(|v| !v.is_empty()) {
            return PathBuf::from(local).join("Temp");
        }
    }
    std::env::temp_dir()
}

/// Windows' machine-wide temp folder. On other platforms `constants.py` falls
/// back to the same `_TEMP`, which is reproduced here.
fn windows_temp_dir(temp: &Path) -> PathBuf {
    if cfg!(windows) {
        PathBuf::from("C:/Windows/Temp")
    } else {
        temp.to_path_buf()
    }
}

/// Built as a pure function of the two directories so the port can be tested
/// without depending on the machine's real home.
fn build_rule_templates(home: &Path, temp: &Path) -> serde_json::Value {
    let text = |p: PathBuf| p.to_string_lossy().into_owned();
    let rule = |folder: String, pattern: &str, action: &str, destination: String, days: i64| {
        json!({
            "folder_to_watch": folder,
            "file_pattern": pattern,
            "action": action,
            "destination_folder": destination,
            "days_older_than": days,
            "enabled": true,
            "use_regex": false,
        })
    };

    let screenshots = text(home.join("Pictures").join("Organized Screenshots"));
    let captures = text(home.join("Videos").join("Captures"));
    let archived_captures = text(home.join("Videos").join("Archived Captures"));
    let game_captures = home
        .join("Videos")
        .join("[Your Game Name]")
        .join("Captures");

    json!([
        {
            "name": "Clean up Downloads",
            "description": "Deletes files older than 90 days from your Downloads folder.",
            "rules": [rule(
                text(home.join("Downloads")),
                "*.*",
                "delete_to_trash",
                String::new(),
                90,
            )],
        },
        {
            "name": "Organize Screenshots",
            "description": "Moves screenshots named like 'Screenshot YYYY-MM-DD HHMMSS.png' from your Pictures/Screenshots folder to 'Pictures/Organized Screenshots'.",
            "rules": [rule(
                text(home.join("Pictures").join("Screenshots")),
                "Screenshot ????-??-?? ??????.png",
                "move",
                screenshots,
                0,
            )],
        },
        {
            "name": "Organize Video Captures",
            "description": "Moves video captures (MP4, AVI, MKV) older than 30 days from Videos/Captures to 'Videos/Archived Captures'.",
            "rules": [
                rule(captures.clone(), "*.mp4", "move", archived_captures.clone(), 30),
                rule(captures.clone(), "*.avi", "move", archived_captures.clone(), 30),
                rule(captures, "*.mkv", "move", archived_captures, 30),
            ],
        },
        {
            "name": "Clean Temporary Files",
            "description": "Deletes all files from system temporary folders. Use with caution.",
            "rules": [
                rule(text(windows_temp_dir(temp)), "*.*", "delete_permanently", String::new(), 0),
                rule(text(temp.to_path_buf()), "*.*", "delete_permanently", String::new(), 0),
            ],
        },
        {
            "name": "Organize Game Captures (Example)",
            "description": "Example: Moves MP4 game captures from a specific game's capture folder to an 'Organized' subfolder. Customize the path for your game.",
            "rules": [rule(
                text(game_captures.clone()),
                "*.mp4",
                "move",
                text(game_captures.join("Organized")),
                0,
            )],
        },
    ])
}

// ---------------------------------------------------------------------------
// Engine
// ---------------------------------------------------------------------------

#[tauri::command]
pub fn engine_status(state: tauri::State<'_, AppState>) -> Result<EngineStatus, String> {
    Ok(current_status(&state))
}

pub fn current_status(state: &AppState) -> EngineStatus {
    match state.engine.lock() {
        Ok(guard) => guard
            .as_ref()
            .map(|engine| engine.status())
            .unwrap_or(EngineStatus::Stopped),
        Err(poisoned) => poisoned
            .into_inner()
            .as_ref()
            .map(|engine| engine.status())
            .unwrap_or(EngineStatus::Stopped),
    }
}

#[tauri::command]
pub fn start_monitoring(
    app: tauri::AppHandle,
    state: tauri::State<'_, AppState>,
) -> Result<(), String> {
    start_engine(&app, &state)
}

/// Shared by the command and the tray's "Start Monitoring" item.
pub fn start_engine(app: &tauri::AppHandle, state: &AppState) -> Result<(), String> {
    let mut guard = state
        .engine
        .lock()
        .map_err(|_| "engine state is poisoned".to_string())?;

    if guard
        .as_ref()
        .is_some_and(|engine| engine.status() != EngineStatus::Stopped)
    {
        return Ok(());
    }

    let sink = std::sync::Arc::new(crate::EngineBridge::new(app.clone()));
    *guard = Some(EngineHandle::start(state.store.clone(), sink));
    tracing::info!("monitoring started");
    Ok(())
}

#[tauri::command]
pub fn stop_monitoring(state: tauri::State<'_, AppState>) -> Result<(), String> {
    stop_engine(&state, crate::SHUTDOWN_GRACE)
}

/// Stop and join, giving in-flight work `timeout` to finish.
pub fn stop_engine(state: &AppState, timeout: std::time::Duration) -> Result<(), String> {
    let mut guard = state
        .engine
        .lock()
        .map_err(|_| "engine state is poisoned".to_string())?;

    let Some(engine) = guard.as_mut() else {
        return Ok(());
    };
    if !engine.stop(timeout) {
        // The thread is still finishing a file. Leave the handle in place so a
        // later stop (the staged shutdown in `tray::quit`) can wait on the same
        // thread rather than orphaning it and starting a second engine.
        return Err("monitoring is still shutting down".to_string());
    }
    *guard = None;
    tracing::info!("monitoring stopped");
    Ok(())
}

/// Run a scan immediately, without waiting for the interval.
#[tauri::command]
pub fn scan_now(state: tauri::State<'_, AppState>) -> Result<(), String> {
    let guard = state
        .engine
        .lock()
        .map_err(|_| "engine state is poisoned".to_string())?;
    match guard.as_ref() {
        Some(engine) => {
            engine.scan_now();
            Ok(())
        }
        None => Err("Monitoring is not running. Start it first.".to_string()),
    }
}

/// Dry-evaluate a rule the user is editing — 1.5.0's "Preview Matches" button.
/// Must never touch the filesystem.
#[tauri::command]
pub fn preview_rule(
    state: tauri::State<'_, AppState>,
    rule: Rule,
    limit: usize,
) -> Result<RulePreview, String> {
    let config = state.store.load().map_err(|e| fail("load config", e))?;
    preview(&rule, &config, limit)
}

/// The body of `preview_rule`, free of Tauri so it can be tested directly.
///
/// Reads directory entries and file metadata; creates, moves and deletes
/// nothing. The destination is *computed*, never created.
fn preview(rule: &Rule, config: &Config, limit: usize) -> Result<RulePreview, String> {
    let folder = PathBuf::from(&rule.path);
    if !folder.is_dir() {
        return Err(format!(
            "Not a directory or does not exist: {}",
            folder.display()
        ));
    }

    let compiled = CompiledRule::compile(rule).map_err(|e| format!("Invalid pattern: {e}"))?;
    let template = rule.effective_template(&config.settings.archive_path_template);
    let guards = guard_paths(rule, template, &folder);
    let now = std::time::SystemTime::now();

    let mut candidates = Vec::new();
    collect_files(
        &folder,
        descend_levels(config.settings.max_directory_depth),
        &guards,
        &mut candidates,
    );
    // Sorted for the same reason `scan::discover` sorts: a preview that
    // reordered itself between runs would look like the rule had changed.
    candidates.sort();

    let mut matches = Vec::new();
    let mut total = 0usize;
    let mut example_destination = None;

    for file in candidates {
        let Some(name) = file.file_name().and_then(|n| n.to_str()) else {
            continue;
        };
        if compiled.is_excluded(name) {
            continue;
        }
        let Ok(modified) = std::fs::symlink_metadata(&file).and_then(|m| m.modified()) else {
            continue;
        };
        if !compiled.matches(name, modified, now) {
            continue;
        }

        total += 1;
        if matches.len() < limit {
            if example_destination.is_none() {
                example_destination = destination_for(&file, &folder, template, rule);
            }
            matches.push(file.to_string_lossy().into_owned());
        }
    }

    Ok(RulePreview {
        matches,
        total,
        example_destination,
    })
}

/// Where `file` would land, without creating anything.
fn destination_for(file: &Path, folder: &Path, template: &str, rule: &Rule) -> Option<String> {
    if !rule.action.needs_destination() {
        return None;
    }
    template::validate(template).ok()?;

    let values = Placeholders::for_file(file, folder, chrono::Local::now());
    let resolved = template::resolve(template, folder, &values);
    // `{FILENAME}`/`{EXT}` mean the template named the file itself; otherwise
    // it named a directory and the original file name is appended. Same branch
    // `action::relocate` takes.
    let target = if template::has_filename_tokens(template) {
        resolved
    } else {
        match file.file_name() {
            Some(name) => resolved.join(name),
            None => resolved,
        }
    };
    Some(target.to_string_lossy().into_owned())
}

/// How many directory levels below the monitored folder to descend.
///
/// `scan.rs` treats `max_directory_depth` 0 as a flat `read_dir`, and hands
/// anything else to a walker whose depth 1 also means "direct children only".
/// Both therefore descend `max_depth - 1` levels, and a preview that used the
/// raw number would show matches a real scan would never reach.
fn descend_levels(max_directory_depth: u32) -> u32 {
    max_directory_depth.saturating_sub(1)
}

/// Depth-limited walk that prunes the rule's own archive destination, the same
/// guard `scan::discover` applies so a preview never lists files the scanner
/// would refuse to re-process.
fn collect_files(dir: &Path, depth_left: u32, guards: &BTreeSet<PathBuf>, out: &mut Vec<PathBuf>) {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        // `DirEntry::metadata` does not follow symlinks, matching the
        // `follow_symlinks=False` stat the scanner uses.
        let Ok(meta) = entry.metadata() else {
            continue;
        };
        let file_type = meta.file_type();
        if file_type.is_symlink() {
            continue;
        }
        let path = entry.path();
        if file_type.is_file() {
            out.push(path);
        } else if file_type.is_dir() && depth_left > 0 && !is_guarded(&path, guards) {
            collect_files(&path, depth_left - 1, guards, out);
        }
    }
}

fn is_guarded(path: &Path, guards: &BTreeSet<PathBuf>) -> bool {
    if guards.is_empty() {
        return false;
    }
    let normalized = autotidy_core::config::normalize(path);
    guards
        .iter()
        .any(|guard| normalized == *guard || normalized.starts_with(guard))
}

// ---------------------------------------------------------------------------
// History & undo
// ---------------------------------------------------------------------------

#[tauri::command]
pub fn history_page(
    state: tauri::State<'_, AppState>,
    offset: usize,
    limit: usize,
) -> Result<HistoryPage, String> {
    let mut records = history_log(&state)
        .read_all()
        .map_err(|e| fail("read history", e))?;
    // Newest first, matching the `reverse=True` sort the 1.5.0 history viewer
    // applied before rendering.
    records.reverse();

    let total = records.len();
    let page = records.into_iter().skip(offset).take(limit).collect();
    Ok(HistoryPage {
        records: page,
        total,
        offset,
    })
}

#[tauri::command]
pub fn list_runs(state: tauri::State<'_, AppState>) -> Result<Vec<RunSummary>, String> {
    undo::list_runs(&history_log(&state)).map_err(|e| fail("list runs", e))
}

#[tauri::command]
pub fn run_actions(
    state: tauri::State<'_, AppState>,
    run_id: String,
) -> Result<Vec<HistoryRecord>, String> {
    undo::run_actions(&history_log(&state), &run_id).map_err(|e| fail("read run", e))
}

/// Undo a whole run.
///
/// **Must append `UNDO_MOVE` records to history afterwards.** `undo_batch` in
/// the core is read-only, exactly as `UndoManager` was — in 1.5.0 it was the UI
/// layer that wrote those lines, which is why some history entries carry a
/// reduced field set. Dropping this here would silently stop recording undos.
///
/// The per-record loop is deliberate rather than a call to `undo_batch`: the
/// batch reports only counts and messages, and there is no way to tell from it
/// *which* records succeeded, which is exactly what the history lines need.
#[tauri::command]
pub fn undo_run(state: tauri::State<'_, AppState>, run_id: String) -> Result<BatchResult, String> {
    let log = history_log(&state);
    let actions = undo::run_actions(&log, &run_id).map_err(|e| fail("read run", e))?;

    let mut result = BatchResult {
        run_id: run_id.clone(),
        ..BatchResult::default()
    };
    if actions.is_empty() {
        result
            .messages
            .push(format!("No actions found for run_id: {run_id}"));
        return Ok(result);
    }

    // Reverse chronological, so later actions are unwound before the earlier
    // ones they may depend on — the ordering `undo::undo_batch` uses.
    for record in actions.iter().rev() {
        let prefix = format!(
            "Action (Timestamp: {}, Orig: {}, Dest: {}, Type: {}): ",
            or_na(&record.timestamp),
            or_na(&record.original_path),
            record
                .destination_path
                .as_deref()
                .filter(|path| !path.is_empty())
                .unwrap_or("N/A"),
            or_na(&record.action_taken),
        );
        match undo::undo_action(record) {
            Ok(message) => {
                result.success_count += 1;
                log_undo(&log, record, &message);
                result.messages.push(format!("{prefix}{message}"));
            }
            Err(err) => {
                result.failure_count += 1;
                result.messages.push(format!("{prefix}Error: {err}"));
            }
        }
    }

    tracing::info!(
        run_id = %run_id,
        successes = result.success_count,
        failures = result.failure_count,
        "undo batch complete"
    );
    Ok(result)
}

/// Undo one action. Same history-logging obligation as `undo_run`.
#[tauri::command]
pub fn undo_one(
    state: tauri::State<'_, AppState>,
    record: HistoryRecord,
) -> Result<String, String> {
    let message = undo::undo_action(&record).map_err(|e| fail("undo action", e))?;
    log_undo(&history_log(&state), &record, &message);
    Ok(message)
}

fn or_na(value: &str) -> &str {
    if value.is_empty() {
        "N/A"
    } else {
        value
    }
}

/// The `action_taken` written for the reversal of `action`.
///
/// 1.5.0 only ever undid moves and wrote `UNDO_MOVE`. A reversed copy is a
/// deletion, and labelling that "UNDO_MOVE" would put a line in the user's
/// history that describes an operation which never happened, so copies get
/// their own verb. Neither value is in `undo_action`'s reversible set, so an
/// undo record can never itself be undone.
fn undo_verb(action_taken: &str) -> &'static str {
    match action_taken {
        "COPIED" => "UNDO_COPY",
        _ => "UNDO_MOVE",
    }
}

/// Append the history line for a successful undo.
///
/// A failure to write is logged, not returned: the file has already been moved
/// back, and reporting the undo as failed would invite the user to try again on
/// a file that is no longer where the record says it is.
fn log_undo(log: &HistoryLog, source: &HistoryRecord, message: &str) {
    if let Err(err) = log.append(&undo_record(source, message)) {
        tracing::error!(%err, "undo succeeded but could not be recorded in history");
    }
}

/// Build the history line for a reversed action.
///
/// The paths are the *reversal's* paths, matching what 1.5.0's viewer wrote:
/// `original_path` is where the file was before the undo (the archive), and
/// `destination_path` is where it ended up. A reversed copy has no destination
/// — the copy was deleted, and the original never moved.
fn undo_record(source: &HistoryRecord, message: &str) -> HistoryRecord {
    let archived = source.destination_path.clone().unwrap_or_default();
    let restored = if source.action_taken == "COPIED" {
        None
    } else {
        Some(source.original_path.clone())
    };

    HistoryRecord {
        original_path: archived,
        action_taken: undo_verb(&source.action_taken).to_string(),
        destination_path: restored,
        // Carried over so the undo line filters alongside the action it
        // reverses; 1.5.0 left these blank, which is why two lines in a real
        // history are missing fields the rest of the file has.
        monitored_folder: source.monitored_folder.clone(),
        rule_pattern: source.rule_pattern.clone(),
        rule_age_days: source.rule_age_days,
        rule_use_regex: source.rule_use_regex,
        rule_action_config: source.rule_action_config.clone(),
        status: Status::Success,
        details: message.to_string(),
        // Deliberately not the source run's id: an undo line inside the run
        // would be returned by `run_actions`, and a second undo of that run
        // would then try — and fail — to reverse the undo itself.
        run_id: String::new(),
        severity: String::new(),
        timestamp: String::new(),
        copy_size: None,
        copy_mtime: None,
        extra: Default::default(),
    }
    .finalize()
}

// ---------------------------------------------------------------------------
// Platform
// ---------------------------------------------------------------------------

#[tauri::command]
pub fn app_info(
    app: tauri::AppHandle,
    state: tauri::State<'_, AppState>,
) -> Result<AppInfo, String> {
    let store: &ConfigStore = &state.store;
    Ok(AppInfo {
        version: env!("CARGO_PKG_VERSION").to_string(),
        config_path: store.config_path().to_string_lossy().into_owned(),
        history_path: store.history_path().to_string_lossy().into_owned(),
        log_path: store.log_path().to_string_lossy().into_owned(),
        autostart_enabled: crate::platform::autostart_enabled(&app),
        context_menu_registered: crate::platform::context_menu_registered(),
    })
}

#[tauri::command]
pub fn set_autostart(app: tauri::AppHandle, enabled: bool) -> Result<(), String> {
    crate::platform::set_autostart(&app, enabled).map_err(|e| fail("set autostart", e))
}

/// Register/unregister the Explorer "Add to AutoTidy" / "Exclude from AutoTidy"
/// context-menu entries. Replaces `windows_context_menu.py`.
///
/// 1.5.0 wrote to `HKEY_CLASSES_ROOT`, which needs administrator rights and is
/// why that script exits with an error when run unelevated. The equivalent keys
/// under `HKEY_CURRENT_USER\Software\Classes` are per-user and need no
/// elevation, so this should write there instead.
#[tauri::command]
pub fn set_context_menu(enabled: bool) -> Result<(), String> {
    crate::platform::set_context_menu(enabled).map_err(|e| fail("set context menu", e))
}

/// What AutoTidy 1.5.0 left in the machine-wide registry, and whether this
/// process could remove it.
///
/// Both halves are needed together: the UI shows the leftovers *and* has to
/// decide, before drawing a button, whether pressing it could do anything.
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StaleContextMenu {
    /// Empty on a machine that never ran 1.5.0's context-menu registration —
    /// which is the overwhelmingly common case.
    pub verbs: Vec<StaleVerb>,
    /// Whether AutoTidy is running elevated. Removal writes to the machine
    /// half of `HKEY_CLASSES_ROOT`, so unelevated it can only fail.
    pub elevated: bool,
}

/// Detect Explorer menu entries left behind by AutoTidy 1.x.
///
/// 1.5.0 registered its two verbs under `HKEY_CLASSES_ROOT`, which needed
/// administrator rights; 2.0 registers per-user instead and its uninstaller
/// cannot reach the old ones. So an upgraded machine keeps two menu items that
/// invoke a `python.exe` and a `main.py` this install replaced. Purely a read —
/// nothing is changed until the user asks.
#[tauri::command]
pub fn stale_context_menu() -> Result<StaleContextMenu, String> {
    Ok(StaleContextMenu {
        verbs: crate::platform::stale_v1_context_menu(),
        elevated: crate::platform::is_elevated(),
    })
}

/// Remove the entries [`stale_context_menu`] reported.
///
/// Only ever called from an explicit click. `PlatformError::NeedsElevation`
/// arrives as its own sentence — "administrator rights are required" — rather
/// than as a raw access-denied code, because that is the one failure the user
/// can actually do something about.
#[tauri::command]
pub fn remove_stale_context_menu() -> Result<(), String> {
    crate::platform::remove_stale_v1_context_menu()
        .map_err(|e| fail("remove the AutoTidy 1.x Explorer entries", e))
}

/// Show a path in Explorer.
#[tauri::command]
pub fn reveal_in_explorer(app: tauri::AppHandle, path: String) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;

    app.opener()
        .reveal_item_in_dir(&path)
        .map_err(|e| fail("reveal in explorer", e))
}

/// Import a config from a file the user picks. Returns the loaded config
/// without saving, so the UI can confirm before overwriting.
#[tauri::command]
pub fn import_config(path: String) -> Result<Config, String> {
    let raw = std::fs::read_to_string(&path).map_err(|e| fail("read config file", e))?;
    parse_imported_config(&raw)
}

/// Accepts both shapes `ConfigStore::load` accepts: the modern object and the
/// pre-1.0 bare array of rules, so a backup taken from an old install imports
/// rather than erroring out.
fn parse_imported_config(raw: &str) -> Result<Config, String> {
    let value: serde_json::Value =
        serde_json::from_str(raw).map_err(|e| fail("parse config file", e))?;
    match value {
        serde_json::Value::Array(items) => {
            let folders = items
                .into_iter()
                .filter_map(|item| serde_json::from_value::<Rule>(item).ok())
                .collect();
            Ok(Config {
                folders,
                ..Default::default()
            })
        }
        other => serde_json::from_value(other).map_err(|e| fail("parse config file", e)),
    }
}

#[tauri::command]
pub fn export_config(state: tauri::State<'_, AppState>, path: String) -> Result<(), String> {
    let config = state.store.load().map_err(|e| fail("load config", e))?;
    let mut serialized =
        serde_json::to_string_pretty(&config).map_err(|e| fail("serialise config", e))?;
    serialized.push('\n');
    std::fs::write(&path, serialized).map_err(|e| fail("write config file", e))
}

/// Everything the frontend needs to render a rule editor without hardcoding
/// engine vocabulary: valid actions, notification levels, template placeholders.
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Vocabulary {
    pub actions: Vec<&'static str>,
    pub notification_levels: Vec<&'static str>,
    pub placeholders: Vec<&'static str>,
}

#[tauri::command]
pub fn vocabulary() -> Vocabulary {
    Vocabulary {
        actions: vec!["move", "copy", "delete_to_trash", "delete_permanently"],
        notification_levels: vec!["none", "error", "summary", "all"],
        placeholders: autotidy_core::template::ALLOWED_PLACEHOLDERS.to_vec(),
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use autotidy_core::config::{Action, RuleLogic};

    fn rule_at(dir: &Path) -> Rule {
        let mut rule = Rule::new(dir.to_string_lossy().into_owned());
        rule.age_days = 0;
        rule.rule_logic = RuleLogic::And;
        rule
    }

    fn seed(dir: &Path, relative: &str) -> PathBuf {
        let path = dir.join(relative);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, b"x").unwrap();
        path
    }

    // --- depth ------------------------------------------------------------

    #[test]
    fn depth_zero_and_one_both_mean_this_folder_only() {
        // scan.rs: max_depth 0 takes the flat path, and the walker's depth 1 is
        // also just the direct children. Both must preview identically.
        assert_eq!(descend_levels(0), 0);
        assert_eq!(descend_levels(1), 0);
        assert_eq!(descend_levels(2), 1);
        assert_eq!(descend_levels(5), 4);
    }

    #[test]
    fn preview_honours_max_directory_depth() {
        let dir = tempfile::tempdir().unwrap();
        seed(dir.path(), "top.txt");
        seed(dir.path(), "nested/inner.txt");
        seed(dir.path(), "nested/deeper/deepest.txt");

        let rule = rule_at(dir.path());
        let mut config = Config::default();

        config.settings.max_directory_depth = 0;
        assert_eq!(preview(&rule, &config, 50).unwrap().total, 1);

        config.settings.max_directory_depth = 2;
        assert_eq!(preview(&rule, &config, 50).unwrap().total, 2);

        config.settings.max_directory_depth = 3;
        assert_eq!(preview(&rule, &config, 50).unwrap().total, 3);
    }

    // --- preview ----------------------------------------------------------

    #[test]
    fn preview_caps_matches_but_reports_the_full_total() {
        let dir = tempfile::tempdir().unwrap();
        for i in 0..10 {
            seed(dir.path(), &format!("file{i}.txt"));
        }

        let preview = preview(&rule_at(dir.path()), &Config::default(), 3).unwrap();
        assert_eq!(preview.matches.len(), 3);
        assert_eq!(preview.total, 10);
    }

    #[test]
    fn preview_does_not_create_the_destination() {
        let dir = tempfile::tempdir().unwrap();
        seed(dir.path(), "report.txt");

        let preview = preview(&rule_at(dir.path()), &Config::default(), 10).unwrap();
        let destination = preview.example_destination.expect("a move has a target");

        assert!(destination.ends_with("report.txt"));
        assert!(
            !Path::new(&destination).exists(),
            "a preview must not have created {destination}"
        );
        assert!(
            !dir.path().join("_Cleanup").exists(),
            "a preview must not have created the archive folder"
        );
    }

    #[test]
    fn preview_respects_exclusions_and_the_pattern() {
        let dir = tempfile::tempdir().unwrap();
        seed(dir.path(), "keep.log");
        seed(dir.path(), "take.txt");
        seed(dir.path(), "skip.txt");

        let mut rule = rule_at(dir.path());
        rule.pattern = "*.txt".into();
        rule.exclusions = vec!["skip.*".into()];

        let preview = preview(&rule, &Config::default(), 10).unwrap();
        assert_eq!(preview.total, 1);
        assert!(preview.matches[0].ends_with("take.txt"));
    }

    #[test]
    fn preview_prunes_the_rules_own_archive_folder() {
        let dir = tempfile::tempdir().unwrap();
        seed(dir.path(), "fresh.txt");
        // A file the scanner already archived. A recursive preview that walked
        // into `_Cleanup` would offer to archive it a second time.
        seed(dir.path(), "_Cleanup/2026-02-09/already.txt");

        let mut config = Config::default();
        config.settings.max_directory_depth = 4;

        let preview = preview(&rule_at(dir.path()), &config, 10).unwrap();
        assert_eq!(preview.total, 1);
        assert!(preview.matches[0].ends_with("fresh.txt"));
    }

    #[test]
    fn preview_has_no_destination_for_a_delete_rule() {
        let dir = tempfile::tempdir().unwrap();
        seed(dir.path(), "junk.tmp");

        let mut rule = rule_at(dir.path());
        rule.action = Action::DeleteToTrash;

        let preview = preview(&rule, &Config::default(), 10).unwrap();
        assert_eq!(preview.total, 1);
        assert!(preview.example_destination.is_none());
    }

    #[test]
    fn preview_reports_a_missing_folder_rather_than_returning_nothing() {
        let dir = tempfile::tempdir().unwrap();
        let rule = Rule::new(dir.path().join("gone").to_string_lossy().into_owned());
        assert!(preview(&rule, &Config::default(), 10).is_err());
    }

    #[test]
    fn preview_surfaces_an_invalid_regex_instead_of_silently_matching_nothing() {
        let dir = tempfile::tempdir().unwrap();
        let mut rule = rule_at(dir.path());
        rule.use_regex = true;
        rule.pattern = "[unclosed".into();

        let err = preview(&rule, &Config::default(), 10).unwrap_err();
        assert!(err.contains("Invalid pattern"), "unexpected error: {err}");
    }

    // --- undo records -----------------------------------------------------

    fn moved_record() -> HistoryRecord {
        HistoryRecord {
            original_path: r"C:\Downloads\pack.zip".into(),
            action_taken: "MOVED".into(),
            destination_path: Some(r"C:\Downloads\_Cleanup\2026-02-09\pack.zip".into()),
            monitored_folder: r"C:\Downloads".into(),
            rule_pattern: "*.*".into(),
            rule_age_days: 7,
            rule_use_regex: false,
            rule_action_config: "move".into(),
            status: Status::Success,
            details: "Moved".into(),
            run_id: "run-1".into(),
            severity: "INFO".into(),
            timestamp: "2026-02-09T10:00:00+00:00".into(),
            copy_size: None,
            copy_mtime: None,
            extra: Default::default(),
        }
    }

    #[test]
    fn undo_record_reverses_the_paths() {
        let source = moved_record();
        let undone = undo_record(&source, "Successfully moved it back");

        assert_eq!(undone.action_taken, "UNDO_MOVE");
        assert_eq!(
            undone.original_path,
            source.destination_path.clone().unwrap()
        );
        assert_eq!(undone.destination_path, Some(source.original_path.clone()));
        assert_eq!(undone.status, Status::Success);
        assert_eq!(undone.details, "Successfully moved it back");
    }

    #[test]
    fn undo_record_is_stamped_and_kept_out_of_the_original_run() {
        let undone = undo_record(&moved_record(), "done");
        assert!(!undone.timestamp.is_empty(), "finalize must stamp the time");
        assert_eq!(undone.severity, "INFO");
        assert!(
            undone.run_id.is_empty(),
            "an undo line inside the run would make the run un-re-undoable"
        );
        assert_eq!(undone.monitored_folder, r"C:\Downloads");
    }

    #[test]
    fn undo_record_for_a_copy_has_no_destination() {
        let mut source = moved_record();
        source.action_taken = "COPIED".into();

        let undone = undo_record(&source, "Successfully deleted copied file");
        assert_eq!(undone.action_taken, "UNDO_COPY");
        assert_eq!(undone.destination_path, None);
        assert_eq!(undone.original_path, source.destination_path.unwrap());
    }

    #[test]
    fn an_undo_record_is_not_itself_undoable() {
        for verb in ["UNDO_MOVE", "UNDO_COPY"] {
            let mut record = moved_record();
            record.action_taken = verb.into();
            assert!(
                undo::undo_action(&record).is_err(),
                "{verb} must not be reversible"
            );
        }
    }

    #[test]
    fn undo_verb_defaults_to_move_for_unknown_actions() {
        assert_eq!(undo_verb("MOVED"), "UNDO_MOVE");
        assert_eq!(undo_verb("COPIED"), "UNDO_COPY");
        assert_eq!(undo_verb("SOMETHING_ELSE"), "UNDO_MOVE");
    }

    #[test]
    fn undo_records_survive_a_round_trip_through_the_history_file() {
        let dir = tempfile::tempdir().unwrap();
        let log = HistoryLog::new(dir.path().join("autotidy_history.jsonl"));

        log_undo(&log, &moved_record(), "Successfully moved it back");

        let records = log.read_all().unwrap();
        assert_eq!(records.len(), 1);
        assert_eq!(records[0].action_taken, "UNDO_MOVE");
    }

    // --- path comparison --------------------------------------------------

    #[test]
    fn exclusion_removal_matches_the_normalised_stored_form() {
        assert!(same_path(r"C:\Temp\skip", r"C:\Temp\skip"));
        assert!(same_path(r"C:\Temp\..\Temp\skip", r"C:\Temp\skip"));
        assert!(!same_path(r"C:\Temp\skip", r"C:\Temp\other"));
    }

    #[cfg(windows)]
    #[test]
    fn exclusion_removal_is_case_insensitive_on_windows() {
        assert!(same_path(r"C:\Temp\Skip", r"c:\temp\skip"));
    }

    // --- config import ----------------------------------------------------

    #[test]
    fn import_accepts_the_modern_object_shape() {
        let config = parse_imported_config(
            r#"{"folders":[{"path":"C:/x","age_days":3}],"settings":{"interval_minutes":15}}"#,
        )
        .unwrap();
        assert_eq!(config.folders.len(), 1);
        assert_eq!(config.folders[0].age_days, 3);
        assert_eq!(config.settings.interval_minutes, 15);
    }

    #[test]
    fn import_migrates_the_pre_1_0_bare_array() {
        let config =
            parse_imported_config(r#"[{"path": "C:/old", "age_days": 3, "pattern": "*.log"}]"#)
                .unwrap();
        assert_eq!(config.folders.len(), 1);
        assert_eq!(config.folders[0].pattern, "*.log");
    }

    #[test]
    fn import_rejects_a_file_that_is_not_json() {
        assert!(parse_imported_config("{not json").is_err());
    }

    #[test]
    fn import_preserves_unknown_blocks_for_the_round_trip() {
        let config =
            parse_imported_config(r#"{"folders":[],"security":{"safe_mode_enabled":true}}"#)
                .unwrap();
        assert!(config.extra.contains_key("security"));
    }

    // --- rule templates ---------------------------------------------------

    #[test]
    fn rule_templates_match_the_1_5_0_set() {
        let home = Path::new("/home/tester");
        let templates = build_rule_templates(home, Path::new("/tmp"));
        let items = templates.as_array().expect("an array of templates");

        let names: Vec<&str> = items.iter().map(|t| t["name"].as_str().unwrap()).collect();
        assert_eq!(
            names,
            vec![
                "Clean up Downloads",
                "Organize Screenshots",
                "Organize Video Captures",
                "Clean Temporary Files",
                "Organize Game Captures (Example)",
            ]
        );

        // Video captures shipped three rules, one per extension.
        assert_eq!(items[2]["rules"].as_array().unwrap().len(), 3);
        assert_eq!(items[0]["rules"][0]["days_older_than"], 90);
        assert_eq!(items[0]["rules"][0]["action"], "delete_to_trash");
    }

    #[test]
    fn rule_templates_resolve_home_at_runtime() {
        let templates = build_rule_templates(Path::new("/home/tester"), Path::new("/tmp"));
        let downloads = templates[0]["rules"][0]["folder_to_watch"]
            .as_str()
            .unwrap()
            .replace('\\', "/");

        assert_eq!(downloads, "/home/tester/Downloads");
        // Never the literal Python expression that produced it.
        assert!(!downloads.contains("Path.home"));
        assert!(!downloads.contains("%UserProfile%"));
    }

    #[test]
    fn every_template_rule_carries_the_full_field_set() {
        let templates = build_rule_templates(Path::new("/home/tester"), Path::new("/tmp"));
        for template in templates.as_array().unwrap() {
            for rule in template["rules"].as_array().unwrap() {
                for key in [
                    "folder_to_watch",
                    "file_pattern",
                    "action",
                    "destination_folder",
                    "days_older_than",
                    "enabled",
                    "use_regex",
                ] {
                    assert!(rule.get(key).is_some(), "{key} missing from {rule}");
                }
            }
        }
    }
}
