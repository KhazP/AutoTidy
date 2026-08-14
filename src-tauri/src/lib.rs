//! AutoTidy desktop shell.
//!
//! Owns the tray, the window, the platform integrations, and the bridge that
//! forwards engine events to the webview. All actual file-organising logic
//! lives in `autotidy-core`, which knows nothing about Tauri.

pub mod commands;
pub mod named_mutex;
pub mod platform;
pub mod state;
pub mod tray;

use autotidy_core::config::ConfigStore;
use autotidy_core::engine::{EngineEvent, EventSink, LogLevel};
use autotidy_core::history::{HistoryLog, DEFAULT_MAX_AGE_DAYS};
use std::path::{Path, PathBuf};
use std::time::Duration;
use tauri::{Emitter, Manager};

use state::AppState;

pub const APP_NAME: &str = autotidy_core::config::APP_NAME;
pub const MAIN_WINDOW: &str = "main";
pub const TRAY_ID: &str = "main";

/// The channel `src/lib/types.ts` listens on. Must match `ENGINE_EVENT` there.
pub const ENGINE_EVENT: &str = "autotidy://engine";
/// Tray-driven navigation requests (currently only `"history"`).
pub const NAVIGATE_EVENT: &str = "autotidy://navigate";

/// How long an explicit Stop waits before reporting that the engine is still
/// finishing. Shorter than the quit budget: the user is still sitting in front
/// of the app and a frozen window is worse than a "still stopping" message.
pub const SHUTDOWN_GRACE: Duration = Duration::from_secs(5);

/// The file the log rotates through, mirroring 1.5.0's
/// `RotatingFileHandler(maxBytes=5 MB, backupCount=3)`.
const MAX_LOG_BYTES: u64 = 5 * 1024 * 1024;
const LOG_BACKUPS: u32 = 3;

/// Boot the application.
///
/// Startup order matters:
/// 1. The context-menu fast path first, so an `--add-folder` with nothing to
///    forward to never builds a runtime it is about to throw away.
/// 2. `single-instance`, so a second launch (typically the Explorer context
///    menu passing `--add-folder` while the app *is* running) forwards its argv
///    to the running instance instead of racing it for `config.json`.
/// 3. Logging, so everything after it is captured.
/// 4. Config, tray, then the window — which starts hidden.
pub fn run() {
    let store = match ConfigStore::default_location() {
        Ok(store) => store,
        Err(err) => {
            eprintln!("AutoTidy: {err}");
            std::process::exit(1);
        }
    };

    // The Explorer verbs spawn a whole process to add one path to a JSON file.
    // Building the Tauri runtime first — WebView2 environment, plugins, event
    // loop — costs ~330 ms for a window that is never shown, and is why v2 was
    // slower here than 1.5.0: `main.py` handled the flag and called
    // `sys.exit(0)` before it ever constructed a `QApplication`. Same
    // short-circuit, with the running-instance check made explicit.
    let argv: Vec<String> = std::env::args().collect();
    let actions = parse_cli_args(&argv);
    if is_context_menu_only(&actions, named_mutex::gui_instance_running()) {
        run_context_menu_only(&store, &actions);
        return;
    }

    // Read the level straight off disk: the subscriber has to exist before the
    // app does, and a failed load here still leaves a usable default. Under the
    // config-write lock because a fast-path invocation may be part-way through
    // a read-modify-write of this exact file — this process publishes its
    // GUI-instance marker only once `setup()` runs, so until then a click can
    // still legitimately decide to write the config itself.
    let log_level = {
        let _lock = config_write_lock();
        store
            .load()
            .map(|config| config.settings.log_level)
            .unwrap_or_else(|_| "INFO".to_string())
    };
    init_logging(&store, &log_level);
    tracing::info!(version = env!("CARGO_PKG_VERSION"), "AutoTidy starting up");

    prune_history(&store);

    let result = tauri::Builder::default()
        // First, so a second instance hands over its argv and exits before it
        // can read — let alone write — config.json. This is the 1.5.0 race:
        // `--add-folder` spawned a second process that wrote the file while the
        // running app held a stale copy and clobbered it on quit.
        .plugin(tauri_plugin_single_instance::init(|app, argv, cwd| {
            tracing::info!(?argv, cwd, "second instance forwarded its arguments");
            if !handle_cli_args(app, &argv) {
                // A plain double-launch: the user wants the window, not a
                // silent no-op.
                tray::show_window(app);
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(
            tauri_plugin_autostart::Builder::new()
                // The same registry value name `startup_manager.set_autostart`
                // wrote, so upgrading from 1.5.0 replaces the entry instead of
                // leaving two copies behind.
                .app_name(APP_NAME)
                .build(),
        )
        .manage(AppState::new(store))
        .invoke_handler(tauri::generate_handler![
            commands::get_config,
            commands::save_config,
            commands::add_rule,
            commands::update_rule,
            commands::remove_rule,
            commands::add_excluded_folder,
            commands::remove_excluded_folder,
            commands::rule_templates,
            commands::engine_status,
            commands::start_monitoring,
            commands::stop_monitoring,
            commands::scan_now,
            commands::preview_rule,
            commands::history_page,
            commands::list_runs,
            commands::run_actions,
            commands::undo_run,
            commands::undo_one,
            commands::app_info,
            commands::set_autostart,
            commands::set_context_menu,
            commands::stale_context_menu,
            commands::remove_stale_context_menu,
            commands::reveal_in_explorer,
            commands::import_config,
            commands::export_config,
            commands::vocabulary,
        ])
        .setup(|app| {
            let handle = app.handle().clone();

            // This process's own argv. The single-instance plugin has already
            // run, so reaching here means we *are* the first instance.
            let argv: Vec<String> = std::env::args().collect();
            if handle_cli_args(&handle, &argv) {
                // Invoked purely to add or exclude a folder: do the work and
                // go, without ever showing a window. `main.py` called
                // `sys.exit(0)` at the same point. Reaching this with arguments
                // means the fast path declined — a GUI was running when we
                // looked and had exited by the time single-instance checked —
                // so it is a rare fallback rather than the usual route.
                tracing::info!("started for a context-menu action only; exiting");
                handle.cleanup_before_exit();
                std::process::exit(0);
            }

            // Past the short-circuit, so this process really is a GUI session.
            // Publish the marker before anything slow, because until it exists
            // a context-menu click will write `config.json` itself instead of
            // forwarding here. The marker lives in state so it is closed when
            // the app tears down, and the kernel closes it if we abort.
            match named_mutex::InstanceMarker::hold(named_mutex::GUI_INSTANCE) {
                Some(marker) => {
                    app.manage(marker);
                }
                None => tracing::warn!(
                    "could not publish the GUI-instance marker; \
                     context-menu clicks will write the config directly"
                ),
            }

            warn_about_stale_v1_context_menu();

            tray::setup(&handle)?;
            hide_on_close(&handle);
            Ok(())
        })
        .build(tauri::generate_context!());

    match result {
        Ok(app) => app.run(|_app, event| {
            // Closing the window hides it, so this fires only when the last
            // window really goes away. Without it the app would die with its
            // window and leave the tray icon behind — 1.5.0 set
            // `setQuitOnLastWindowClosed(False)` for the same reason. An
            // explicit `app.exit(code)` carries a code and is let through.
            if let tauri::RunEvent::ExitRequested { api, code, .. } = event {
                if code.is_none() {
                    api.prevent_exit();
                }
            }
        }),
        Err(err) => {
            tracing::error!(%err, "failed to start");
            eprintln!("AutoTidy failed to start: {err}");
            std::process::exit(1);
        }
    }
}

/// Note, in the log only, that AutoTidy 1.x's Explorer entries are still
/// registered machine-wide.
///
/// Deliberately not a prompt and deliberately not a fix. Those keys are the
/// user's registry, written by software they installed; deleting them behind
/// their back is not ours to do, and a modal on every launch — for two menu
/// items that are inert rather than dangerous — would be hostile. Settings
/// carries the offer, where someone wondering why the right-click menu is
/// wrong will go looking. This line is for the support case where they send
/// the log instead.
fn warn_about_stale_v1_context_menu() {
    let stale = platform::stale_v1_context_menu();
    if stale.is_empty() {
        return;
    }
    for entry in &stale {
        tracing::warn!(
            key = %entry.key,
            command = entry.command.as_deref().unwrap_or("(none registered)"),
            "an Explorer folder-menu entry from AutoTidy 1.x is still registered"
        );
    }
    tracing::warn!(
        count = stale.len(),
        elevated = platform::is_elevated(),
        "these entries run the 1.x Python launcher and are out of reach of the 2.0 \
         uninstaller; Settings offers to remove them"
    );
}

/// Hide the window on close instead of destroying it.
///
/// 1.5.0 called `setQuitOnLastWindowClosed(False)`: the X button puts AutoTidy
/// back in the tray, and only the tray's Quit ends the process.
fn hide_on_close(app: &tauri::AppHandle) {
    let Some(window) = app.get_webview_window(MAIN_WINDOW) else {
        tracing::warn!(label = MAIN_WINDOW, "no main window to guard");
        return;
    };
    let hidden = window.clone();
    window.on_window_event(move |event| {
        if let tauri::WindowEvent::CloseRequested { api, .. } = event {
            api.prevent_close();
            let _ = hidden.hide();
        }
    });
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

/// A folder operation requested on the command line by the Explorer verbs.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CliAction {
    AddFolder(String),
    ExcludeFolder(String),
}

/// Whether this invocation can be served without building a Tauri runtime.
///
/// Both halves matter. No actions means a plain launch, which wants a window.
/// A running GUI means the click has somewhere better to go: the normal path
/// lets `single-instance` forward argv to it, so the live app is the one that
/// writes the config and raises the notification.
fn is_context_menu_only(actions: &[CliAction], gui_running: bool) -> bool {
    !actions.is_empty() && !gui_running
}

/// Apply context-menu actions and exit, without building a Tauri runtime.
///
/// Only reached when no GUI instance is running, so there is no tray to raise a
/// notification from and no webview to refresh — exactly the situation 1.5.0's
/// `handle_context_menu_action` was in, which also wrote the config and said
/// nothing. The log is the record.
fn run_context_menu_only(store: &ConfigStore, actions: &[CliAction]) {
    // Unlocked: a read cannot corrupt anything, and this one only picks a log
    // level. The write below takes the lock.
    let log_level = store
        .load()
        .map(|config| config.settings.log_level)
        .unwrap_or_else(|_| "INFO".to_string());
    init_logging(store, &log_level);
    tracing::info!(
        version = env!("CARGO_PKG_VERSION"),
        actions = actions.len(),
        "handling a context-menu action without starting the UI"
    );

    // Deliberately no `prune_history`: that is housekeeping for a session which
    // is not about to happen, and rewriting a long history file to add one
    // folder is exactly the kind of work this path exists to skip.
    for outcome in apply_cli_actions(store, actions) {
        match outcome {
            Ok(Some(message)) => tracing::info!(message),
            Ok(None) => {}
            Err(message) => tracing::error!(message, "context-menu action failed"),
        }
    }
}

/// Take the cross-process config lock, logging if it could not be had.
///
/// A `None` guard still lets the caller proceed: the write is atomic either
/// way, and losing the folder the user just right-clicked would be a worse
/// outcome than an unserialised read-modify-write.
fn config_write_lock() -> Option<named_mutex::NamedLock> {
    let lock = named_mutex::NamedLock::acquire(
        named_mutex::CONFIG_WRITE,
        named_mutex::CONFIG_WRITE_TIMEOUT,
    );
    if lock.is_none() {
        tracing::warn!("proceeding without the config-write lock");
    }
    lock
}

/// Apply a batch of actions under one config-write lock.
///
/// The lock spans the whole batch, and each action inside it is a complete
/// load-mutate-save. `ConfigStore::save` is atomic on its own, but two
/// processes interleaving load-mutate-save would still lose an update: both
/// read the old file, and the second write erases the first's folder.
fn apply_cli_actions(
    store: &ConfigStore,
    actions: &[CliAction],
) -> Vec<Result<Option<String>, String>> {
    let _lock = config_write_lock();
    actions
        .iter()
        .map(|action| apply_cli_action(store, action))
        .collect()
}

/// Parse `--add-folder <PATH>` / `--exclude-folder <PATH>`.
///
/// Both the separated (`--add-folder C:\x`) and joined (`--add-folder=C:\x`)
/// spellings are accepted, because `argparse` accepted both and the registry
/// command could be edited by hand. `argv[0]` is the executable and is skipped.
pub fn parse_cli_args(argv: &[String]) -> Vec<CliAction> {
    const ADD: &str = platform::FLAG_ADD;
    const EXCLUDE: &str = platform::FLAG_EXCLUDE;

    let mut actions = Vec::new();
    let mut args = argv.iter().skip(1);

    while let Some(arg) = args.next() {
        let (flag, inline) = match arg.split_once('=') {
            Some((flag, value)) => (flag, Some(value.to_string())),
            None => (arg.as_str(), None),
        };
        if flag != ADD && flag != EXCLUDE {
            continue;
        }
        // A trailing `--add-folder` with nothing after it is a malformed
        // invocation, not a request to add the empty path.
        let Some(path) = inline.or_else(|| args.next().cloned()) else {
            tracing::warn!(flag, "flag given without a path; ignoring");
            continue;
        };
        if path.trim().is_empty() {
            tracing::warn!(flag, "flag given an empty path; ignoring");
            continue;
        }
        actions.push(match flag {
            ADD => CliAction::AddFolder(path),
            _ => CliAction::ExcludeFolder(path),
        });
    }
    actions
}

/// Handle `--add-folder` / `--exclude-folder`, whether they arrive on this
/// process's own argv or are forwarded from a second instance.
///
/// Returns true when an argument was consumed, so a cold start invoked purely
/// to add a folder can exit without ever showing a window — matching 1.5.0,
/// which called `sys.exit(0)` after handling the argument.
pub fn handle_cli_args(app: &tauri::AppHandle, argv: &[String]) -> bool {
    let actions = parse_cli_args(argv);
    if actions.is_empty() {
        return false;
    }

    let state = app.state::<AppState>();
    for outcome in apply_cli_actions(&state.store, &actions) {
        match outcome {
            Ok(Some(message)) => notify(app, message),
            // Already present: 1.5.0 logged and said nothing to the user, which
            // is right — the folder is in the state the user asked for.
            Ok(None) => {}
            Err(message) => {
                tracing::error!(message, "context-menu action failed");
                notify(app, message);
            }
        }
    }
    true
}

/// Apply one action to the on-disk config.
///
/// Returns the message to surface, or `None` when nothing changed. The config
/// is loaded and saved around each action rather than held in memory, so the
/// window in which a stale copy could be written back is as short as possible.
/// Callers reach this through [`apply_cli_actions`], which holds the
/// cross-process write lock for the duration.
fn apply_cli_action(store: &ConfigStore, action: &CliAction) -> Result<Option<String>, String> {
    let path = match action {
        CliAction::AddFolder(path) | CliAction::ExcludeFolder(path) => path,
    };
    // `main.py` refused anything that was not a directory. A file dropped on
    // the verb would otherwise be monitored as if it were a folder.
    if !Path::new(path).is_dir() {
        return Err(format!("Not a folder: {path}"));
    }

    let mut config = store
        .load()
        .map_err(|e| format!("Could not read the configuration: {e}"))?;

    let (changed, message) = match action {
        CliAction::AddFolder(path) => (
            config.add_folder(Path::new(path)),
            format!("Now monitoring {path}"),
        ),
        CliAction::ExcludeFolder(path) => (
            config.add_excluded_folder(Path::new(path)),
            format!("Excluded {path}"),
        ),
    };
    if !changed {
        tracing::info!(%path, "already configured; nothing to do");
        return Ok(None);
    }

    store
        .save(&config)
        .map_err(|e| format!("Could not save the configuration: {e}"))?;
    tracing::info!(%path, ?action, "configuration updated from the context menu");
    Ok(Some(message))
}

fn notify(app: &tauri::AppHandle, body: String) {
    use tauri_plugin_notification::NotificationExt;

    if let Err(err) = app
        .notification()
        .builder()
        .title(APP_NAME)
        .body(body)
        .show()
    {
        tracing::warn!(%err, "could not show a notification");
    }
}

// ---------------------------------------------------------------------------
// Engine bridge
// ---------------------------------------------------------------------------

/// Forwards engine events to the webview, the OS, and the tray.
///
/// 1.5.0 pushed strings onto a `queue.Queue` that a `QTimer` polled; the UI
/// therefore lagged the work by up to a tick and had to re-parse `"STATUS: …"`
/// sentinels out of the log stream. Here the engine pushes typed events and
/// this fans them out.
pub struct EngineBridge {
    app: tauri::AppHandle,
}

impl EngineBridge {
    pub fn new(app: tauri::AppHandle) -> Self {
        Self { app }
    }
}

impl EventSink for EngineBridge {
    fn emit(&self, event: EngineEvent) {
        match &event {
            EngineEvent::Log { level, message } => match level {
                LogLevel::Info => tracing::info!(target: "autotidy_core::engine", "{message}"),
                LogLevel::Warning => tracing::warn!(target: "autotidy_core::engine", "{message}"),
                LogLevel::Error => tracing::error!(target: "autotidy_core::engine", "{message}"),
            },
            EngineEvent::StatusChanged { status } => tray::sync_status(&self.app, *status),
            EngineEvent::Notify { title, message, .. } => {
                // Already filtered against `notification_level` by the engine,
                // so anything reaching here is meant to be shown.
                notify_titled(&self.app, title, message);
            }
            _ => {}
        }

        // The webview gets every event, including the ones handled above: the
        // log pane and the status pill are rendered from this stream.
        if let Err(err) = self.app.emit(ENGINE_EVENT, &event) {
            tracing::warn!(%err, "could not forward an engine event to the webview");
        }
    }
}

fn notify_titled(app: &tauri::AppHandle, title: &str, body: &str) {
    use tauri_plugin_notification::NotificationExt;

    if let Err(err) = app.notification().builder().title(title).body(body).show() {
        tracing::warn!(%err, "could not show a notification");
    }
}

// ---------------------------------------------------------------------------
// Logging
// ---------------------------------------------------------------------------

/// Install the file logger, replacing `main.py`'s `setup_logging`.
fn init_logging(store: &ConfigStore, level: &str) {
    use tracing_subscriber::EnvFilter;

    let dir = store.dir().to_path_buf();
    if let Err(err) = std::fs::create_dir_all(&dir) {
        eprintln!("AutoTidy: could not create {}: {err}", dir.display());
        return;
    }

    let log_path = store.log_path();
    if let Err(err) = rotate_log(&log_path) {
        eprintln!("AutoTidy: could not rotate {}: {err}", log_path.display());
    }

    let file_name = log_path
        .file_name()
        .map(|n| n.to_os_string())
        .unwrap_or_else(|| "autotidy.log".into());
    let appender = tracing_appender::rolling::never(&dir, file_name);

    // `RUST_LOG` wins when set, so a support request can ask for one run at
    // debug without editing the user's config.
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new(filter_directive(level)));

    let result = tracing_subscriber::fmt()
        .with_writer(appender)
        // The log is a file, not a terminal; escape codes would be noise.
        .with_ansi(false)
        .with_target(true)
        .with_env_filter(filter)
        .try_init();
    if let Err(err) = result {
        eprintln!("AutoTidy: could not install the logger: {err}");
    }
}

/// Translate a Python logging level into a `tracing` filter directive.
///
/// Dependencies stay at `warn`: 1.5.0's root logger was effectively ours alone,
/// while here `INFO` across every crate in the tree would drown the file in
/// windowing and webview chatter.
fn filter_directive(level: &str) -> String {
    let level = match level.trim().to_ascii_uppercase().as_str() {
        "DEBUG" => "debug",
        "WARNING" | "WARN" => "warn",
        // Python's CRITICAL has no `tracing` equivalent; ERROR is the nearest
        // level that still shows the things CRITICAL was used for.
        "ERROR" | "CRITICAL" | "FATAL" => "error",
        "TRACE" => "trace",
        _ => "info",
    };
    format!("warn,autotidy_core={level},autotidy_app_lib={level},AutoTidy={level}")
}

/// Size-based rotation, run once at startup.
///
/// `tracing-appender` only rotates on a time boundary, and the file the app
/// reports as its log path has to stay at that exact path for "Open log file"
/// to work. Checking the size on the way in keeps 1.5.0's 5 MB × 3 policy
/// without the filename moving underneath the user.
fn rotate_log(path: &Path) -> std::io::Result<()> {
    match std::fs::metadata(path) {
        Ok(meta) if meta.len() < MAX_LOG_BYTES => return Ok(()),
        Ok(_) => {}
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(err) => return Err(err),
    }

    for index in (1..=LOG_BACKUPS).rev() {
        let newer = if index == 1 {
            path.to_path_buf()
        } else {
            backup_path(path, index - 1)
        };
        let older = backup_path(path, index);
        if older.exists() {
            std::fs::remove_file(&older)?;
        }
        if newer.exists() {
            std::fs::rename(&newer, &older)?;
        }
    }
    Ok(())
}

/// `autotidy.log.2`, matching the `f"{path}.{i}"` suffixing used for history
/// backups and by Python's `RotatingFileHandler`.
fn backup_path(path: &Path, index: u32) -> PathBuf {
    let mut name = path.to_path_buf().into_os_string();
    name.push(format!(".{index}"));
    PathBuf::from(name)
}

/// Drop history older than 90 days, as `main.py` did on every launch.
fn prune_history(store: &ConfigStore) {
    let log = HistoryLog::new(store.history_path());
    if let Err(err) = log.prune(DEFAULT_MAX_AGE_DAYS) {
        tracing::warn!(%err, "history pruning failed");
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn argv(args: &[&str]) -> Vec<String> {
        std::iter::once("AutoTidy.exe")
            .chain(args.iter().copied())
            .map(String::from)
            .collect()
    }

    // --- CLI parsing ------------------------------------------------------

    #[test]
    fn no_flags_is_a_plain_launch() {
        assert!(parse_cli_args(&argv(&[])).is_empty());
        assert!(parse_cli_args(&argv(&["--something-else", "x"])).is_empty());
        // An empty argv (no argv[0] at all) must not panic.
        assert!(parse_cli_args(&[]).is_empty());
    }

    #[test]
    fn add_folder_is_parsed_in_both_spellings() {
        assert_eq!(
            parse_cli_args(&argv(&["--add-folder", r"C:\Downloads"])),
            vec![CliAction::AddFolder(r"C:\Downloads".into())]
        );
        assert_eq!(
            parse_cli_args(&argv(&[r"--add-folder=C:\Downloads"])),
            vec![CliAction::AddFolder(r"C:\Downloads".into())]
        );
    }

    #[test]
    fn exclude_folder_is_parsed_too() {
        assert_eq!(
            parse_cli_args(&argv(&["--exclude-folder", r"D:\Games"])),
            vec![CliAction::ExcludeFolder(r"D:\Games".into())]
        );
    }

    #[test]
    fn a_path_with_spaces_survives_as_one_argument() {
        // Explorer expands `%V` into a single argv entry, quotes and all.
        assert_eq!(
            parse_cli_args(&argv(&["--add-folder", r"C:\My Documents\Big Folder"])),
            vec![CliAction::AddFolder(r"C:\My Documents\Big Folder".into())]
        );
    }

    #[test]
    fn a_flag_without_a_path_is_ignored_rather_than_adding_nothing() {
        assert!(parse_cli_args(&argv(&["--add-folder"])).is_empty());
        assert!(parse_cli_args(&argv(&["--add-folder="])).is_empty());
        assert!(parse_cli_args(&argv(&["--add-folder", "   "])).is_empty());
    }

    #[test]
    fn argv_zero_is_never_read_as_a_flag() {
        // A dev build whose exe path somehow contains the flag text must not
        // be mistaken for an invocation of it.
        let argv = vec!["--add-folder".to_string(), r"C:\x".to_string()];
        assert_eq!(
            parse_cli_args(&argv),
            vec![],
            "argv[0] is the program, not an argument"
        );
    }

    #[test]
    fn several_flags_are_all_applied() {
        // 1.5.0's `elif` silently dropped the second. Explorer only ever sends
        // one, but honouring both is the behaviour a hand-written command line
        // would expect.
        assert_eq!(
            parse_cli_args(&argv(&[
                "--add-folder",
                r"C:\a",
                "--exclude-folder",
                r"C:\b"
            ])),
            vec![
                CliAction::AddFolder(r"C:\a".into()),
                CliAction::ExcludeFolder(r"C:\b".into()),
            ]
        );
    }

    // --- fast-path decision -----------------------------------------------

    #[test]
    fn a_context_menu_click_with_no_gui_running_skips_the_runtime() {
        let actions = parse_cli_args(&argv(&["--add-folder", r"C:\Downloads"]));
        assert!(is_context_menu_only(&actions, false));
    }

    #[test]
    fn a_context_menu_click_falls_through_while_a_gui_is_running() {
        // The runtime must still be built so `single-instance` can hand argv to
        // the live app: it is the one that writes the config and notifies.
        let actions = parse_cli_args(&argv(&["--add-folder", r"C:\Downloads"]));
        assert!(!is_context_menu_only(&actions, true));
    }

    #[test]
    fn a_plain_launch_never_takes_the_fast_path() {
        // Nothing to do but show a window, which the fast path cannot do.
        assert!(!is_context_menu_only(&[], false));
        assert!(!is_context_menu_only(&[], true));
        assert!(!is_context_menu_only(
            &parse_cli_args(&argv(&["--add-folder"])),
            false
        ));
    }

    #[test]
    fn the_fast_path_is_only_reachable_via_the_gui_instance_marker() {
        // The probe must never be satisfied by the config lock, or a cold click
        // that happens to overlap another one would forward into nothing.
        assert_ne!(named_mutex::GUI_INSTANCE, named_mutex::CONFIG_WRITE);
    }

    // --- CLI application --------------------------------------------------

    #[test]
    fn a_batch_of_actions_all_land_in_one_config() {
        // The `--add-folder` then `--exclude-folder` pair, applied through the
        // same locked batch the fast path uses.
        let dir = tempfile::tempdir().unwrap();
        let watched = dir.path().join("Downloads");
        let skipped = dir.path().join("Games");
        std::fs::create_dir_all(&watched).unwrap();
        std::fs::create_dir_all(&skipped).unwrap();
        let store = ConfigStore::new(dir.path().join("cfg"));

        let outcomes = apply_cli_actions(
            &store,
            &[
                CliAction::AddFolder(watched.to_string_lossy().into_owned()),
                CliAction::ExcludeFolder(skipped.to_string_lossy().into_owned()),
            ],
        );
        assert_eq!(outcomes.len(), 2);
        assert!(outcomes.iter().all(|o| matches!(o, Ok(Some(_)))));

        let config = store.load().unwrap();
        assert_eq!(config.folders.len(), 1);
        assert_eq!(config.excluded_folders.len(), 1);
    }

    #[test]
    fn a_failing_action_does_not_abandon_the_rest_of_the_batch() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("a-file.txt");
        let watched = dir.path().join("Downloads");
        std::fs::write(&file, b"x").unwrap();
        std::fs::create_dir_all(&watched).unwrap();
        let store = ConfigStore::new(dir.path().join("cfg"));

        let outcomes = apply_cli_actions(
            &store,
            &[
                CliAction::AddFolder(file.to_string_lossy().into_owned()),
                CliAction::AddFolder(watched.to_string_lossy().into_owned()),
            ],
        );
        assert!(outcomes[0].is_err(), "a file is not a folder");
        assert!(outcomes[1].is_ok());
        assert_eq!(store.load().unwrap().folders.len(), 1);
    }

    #[test]
    fn adding_a_folder_writes_it_to_the_config() {
        let dir = tempfile::tempdir().unwrap();
        let watched = dir.path().join("Downloads");
        std::fs::create_dir_all(&watched).unwrap();
        let store = ConfigStore::new(dir.path().join("cfg"));

        let action = CliAction::AddFolder(watched.to_string_lossy().into_owned());
        assert!(apply_cli_action(&store, &action).unwrap().is_some());

        let config = store.load().unwrap();
        assert_eq!(config.folders.len(), 1);

        // Idempotent: the second click reports no change instead of a duplicate.
        assert!(apply_cli_action(&store, &action).unwrap().is_none());
        assert_eq!(store.load().unwrap().folders.len(), 1);
    }

    #[test]
    fn excluding_a_folder_writes_it_to_the_config() {
        let dir = tempfile::tempdir().unwrap();
        let skipped = dir.path().join("Games");
        std::fs::create_dir_all(&skipped).unwrap();
        let store = ConfigStore::new(dir.path().join("cfg"));

        let action = CliAction::ExcludeFolder(skipped.to_string_lossy().into_owned());
        assert!(apply_cli_action(&store, &action).unwrap().is_some());
        assert_eq!(store.load().unwrap().excluded_folders.len(), 1);
    }

    #[test]
    fn a_non_directory_is_refused_without_touching_the_config() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("a-file.txt");
        std::fs::write(&file, b"x").unwrap();
        let store = ConfigStore::new(dir.path().join("cfg"));

        let action = CliAction::AddFolder(file.to_string_lossy().into_owned());
        assert!(apply_cli_action(&store, &action).is_err());
        assert!(store.load().unwrap().folders.is_empty());
    }

    #[test]
    fn a_context_menu_add_preserves_the_rest_of_the_config() {
        // The 1.5.0 race destroyed unrelated keys. Even with the race closed,
        // the write path itself must not drop anything.
        let dir = tempfile::tempdir().unwrap();
        let store = ConfigStore::new(dir.path().join("cfg"));
        std::fs::create_dir_all(store.dir()).unwrap();
        std::fs::write(
            store.config_path(),
            r#"{"folders":[],"settings":{"interval_minutes":15,"theme":"dark"},
                "security":{"safe_mode_enabled":true}}"#,
        )
        .unwrap();

        let watched = dir.path().join("Downloads");
        std::fs::create_dir_all(&watched).unwrap();
        apply_cli_action(
            &store,
            &CliAction::AddFolder(watched.to_string_lossy().into_owned()),
        )
        .unwrap();

        let config = store.load().unwrap();
        assert_eq!(config.folders.len(), 1);
        assert_eq!(config.settings.interval_minutes, 15);
        assert!(config.settings.extra.contains_key("theme"));
        assert!(config.extra.contains_key("security"));
    }

    // --- logging ----------------------------------------------------------

    #[test]
    fn python_log_levels_map_onto_tracing_levels() {
        assert!(filter_directive("DEBUG").contains("autotidy_core=debug"));
        assert!(filter_directive("info").contains("autotidy_core=info"));
        assert!(filter_directive("WARNING").contains("autotidy_core=warn"));
        assert!(filter_directive("ERROR").contains("autotidy_core=error"));
        // Python's CRITICAL has no tracing equivalent.
        assert!(filter_directive("CRITICAL").contains("autotidy_core=error"));
        // Anything unrecognised falls back to INFO rather than silencing logs.
        assert!(filter_directive("banana").contains("autotidy_core=info"));
        assert!(filter_directive("").contains("autotidy_core=info"));
    }

    #[test]
    fn dependencies_are_kept_at_warn_even_at_debug() {
        assert!(filter_directive("DEBUG").starts_with("warn,"));
    }

    #[test]
    fn a_small_log_is_left_alone() {
        let dir = tempfile::tempdir().unwrap();
        let log = dir.path().join("autotidy.log");
        std::fs::write(&log, b"a line\n").unwrap();

        rotate_log(&log).unwrap();
        assert_eq!(std::fs::read(&log).unwrap(), b"a line\n");
        assert!(!backup_path(&log, 1).exists());
    }

    #[test]
    fn a_missing_log_is_not_an_error() {
        let dir = tempfile::tempdir().unwrap();
        rotate_log(&dir.path().join("autotidy.log")).unwrap();
    }

    #[test]
    fn an_oversized_log_rotates_and_keeps_three_backups() {
        let dir = tempfile::tempdir().unwrap();
        let log = dir.path().join("autotidy.log");

        // Four rotations: the fourth must push the oldest backup off the end.
        for generation in 0..4u8 {
            std::fs::write(&log, vec![b'a' + generation; MAX_LOG_BYTES as usize + 1]).unwrap();
            rotate_log(&log).unwrap();
            assert!(!log.exists(), "the live log is moved aside, not copied");
        }

        // Newest backup first: .1 holds the most recent generation.
        for (index, generation) in (1..=LOG_BACKUPS).zip([b'd', b'c', b'b']) {
            let backup = backup_path(&log, index);
            assert!(backup.exists(), "{} should exist", backup.display());
            assert_eq!(std::fs::read(&backup).unwrap()[0], generation);
        }
        assert!(
            !backup_path(&log, LOG_BACKUPS + 1).exists(),
            "only three backups are kept"
        );
    }

    #[test]
    fn backup_paths_suffix_the_whole_name() {
        let path = Path::new(r"C:\AutoTidy\autotidy.log");
        assert_eq!(
            backup_path(path, 2),
            PathBuf::from(r"C:\AutoTidy\autotidy.log.2")
        );
    }

    // --- contract ---------------------------------------------------------

    #[test]
    fn the_engine_channel_matches_the_frontends_constant() {
        // `src/lib/types.ts` hardcodes this; a rename here would silently stop
        // every event reaching the UI.
        assert_eq!(ENGINE_EVENT, "autotidy://engine");
    }
}
