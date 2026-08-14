//! The long-running supervisor: owns the background thread, the schedule, and
//! the event stream the UI subscribes to.
//!
//! Replaces `MonitoringWorker` from `worker.py`, with three changes:
//!
//! * **Push, not poll.** 1.5.0 pushed strings onto a `queue.Queue` that a
//!   `QTimer` polled every so often. Here the engine emits typed
//!   [`EngineEvent`]s through a sink the shell forwards straight to the UI.
//! * **Typed events.** The old queue mixed log lines, `"STATUS: Running"`
//!   sentinels, and notification dicts in one channel of `Any`.
//! * **Watch mode.** The loop can wake on filesystem events instead of only on
//!   an interval timer.
//!
//! Shutdown is cooperative and bounded: [`EngineHandle::stop`] signals, and the
//! scan loop checks between files so an in-flight file operation is never torn
//! in half.

use crate::config::{Config, ConfigStore, NotificationCategory, Rule};
use crate::history::HistoryLog;
use crate::scan::{guard_paths, scan_rule, ScanOptions, ScanReport};
use crate::watch::{is_relevant, WatchHandle, DEFAULT_DEBOUNCE};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::time::Duration;

/// How long a watch-mode wait blocks before re-reading the config.
///
/// Watch mode has no interval to expire, so without a ceiling a change to the
/// rules (or to `schedule_type` itself) would not be noticed until the next
/// filesystem event. A timeout here re-evaluates the config; it does **not**
/// trigger a scan.
const WATCH_POLL: Duration = Duration::from_millis(500);

/// What the engine is doing right now.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum EngineStatus {
    Stopped,
    /// Started, waiting for the next interval or a filesystem event.
    Idle,
    Scanning,
    /// Stop requested; finishing the current file before exiting.
    Stopping,
}

/// How the engine decides when to scan.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ScheduleMode {
    /// Scan every `interval_minutes`, as 1.5.0 did.
    Interval,
    /// Scan when the filesystem reports a change, debounced.
    Watch,
}

/// Everything the shell needs to render. Serialised straight to the frontend.
#[derive(Debug, Clone, serde::Serialize)]
#[serde(tag = "kind", rename_all = "camelCase")]
pub enum EngineEvent {
    #[serde(rename_all = "camelCase")]
    Log { level: LogLevel, message: String },
    #[serde(rename_all = "camelCase")]
    StatusChanged { status: EngineStatus },
    #[serde(rename_all = "camelCase")]
    ScanStarted { run_id: String, folders: usize },
    #[serde(rename_all = "camelCase")]
    ScanFinished {
        run_id: String,
        processed: usize,
        skipped: usize,
        failed: usize,
        dry_run: bool,
    },
    /// A tray notification the shell should surface, already filtered against
    /// the user's `notification_level`.
    #[serde(rename_all = "camelCase")]
    Notify {
        category: &'static str,
        title: String,
        message: String,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum LogLevel {
    Info,
    Warning,
    Error,
}

/// Where engine events go. The Tauri shell implements this by emitting to the
/// webview; the CLI implements it by printing.
pub trait EventSink: Send + Sync + 'static {
    fn emit(&self, event: EngineEvent);
}

/// An `EventSink` that drops everything, for tests and headless runs.
pub struct NullSink;
impl EventSink for NullSink {
    fn emit(&self, _: EngineEvent) {}
}

/// An `EventSink` that collects into a channel, for tests.
pub struct ChannelSink(pub mpsc::Sender<EngineEvent>);
impl EventSink for ChannelSink {
    fn emit(&self, event: EngineEvent) {
        let _ = self.0.send(event);
    }
}

/// Shared state between the handle and its background thread.
pub(crate) struct Shared {
    pub(crate) store: ConfigStore,
    pub(crate) sink: Arc<dyn EventSink>,
    pub(crate) status: Mutex<EngineStatus>,
    pub(crate) stop: Arc<AtomicBool>,
    /// Set by `scan_now` to break the interval wait early. In watch mode the
    /// filesystem watcher pushes through the same channel, so one blocking
    /// `recv_timeout` covers "scan now", "something changed", and "stop".
    pub(crate) wake: Mutex<Option<mpsc::Sender<()>>>,
    /// Signalled by the background thread immediately before it returns.
    ///
    /// `JoinHandle::join` has no timeout, so [`EngineHandle::stop`] waits on
    /// this instead and only calls `join` once the thread has said it is done.
    /// That keeps shutdown bounded even if a scan wedges on a network drive.
    pub(crate) done: Mutex<Option<mpsc::Receiver<()>>>,
}

impl Shared {
    pub(crate) fn set_status(&self, status: EngineStatus) {
        *self.status.lock().unwrap() = status;
        self.sink.emit(EngineEvent::StatusChanged { status });
    }

    pub(crate) fn log(&self, level: LogLevel, message: impl Into<String>) {
        self.sink.emit(EngineEvent::Log {
            level,
            message: message.into(),
        });
    }

    /// Emit a notification only if the configured level permits the category —
    /// the gate `MonitoringWorker._should_send_notification` applied.
    pub(crate) fn notify(
        &self,
        config: &Config,
        category: NotificationCategory,
        title: impl Into<String>,
        message: impl Into<String>,
    ) {
        if !config.settings.notification_level.permits(category) {
            return;
        }
        self.sink.emit(EngineEvent::Notify {
            category: match category {
                NotificationCategory::Error => "error",
                NotificationCategory::Summary => "summary",
                NotificationCategory::Info => "info",
            },
            title: title.into(),
            message: message.into(),
        });
    }

    pub(crate) fn should_stop(&self) -> bool {
        self.stop.load(Ordering::Relaxed)
    }

    /// Break the background thread out of its wait.
    pub(crate) fn wake(&self) {
        if let Some(tx) = self.wake.lock().unwrap().as_ref() {
            let _ = tx.send(());
        }
    }

    /// A sender the filesystem watcher can keep, so a debounced batch lands in
    /// the same queue `scan_now` and `stop` use.
    pub(crate) fn waker(&self) -> Option<mpsc::Sender<()>> {
        self.wake.lock().unwrap().clone()
    }
}

/// Handle to a running engine. Dropping it does **not** stop the thread; call
/// [`stop`](Self::stop) so an in-flight file operation can finish cleanly.
pub struct EngineHandle {
    pub(crate) shared: Arc<Shared>,
    pub(crate) thread: Option<std::thread::JoinHandle<()>>,
}

impl EngineHandle {
    /// Spawn the supervisor. It begins in [`EngineStatus::Idle`] and performs
    /// an immediate first scan, matching 1.5.0's start behaviour.
    pub fn start(store: ConfigStore, sink: Arc<dyn EventSink>) -> Self {
        let (wake_tx, wake_rx) = mpsc::channel();
        let (done_tx, done_rx) = mpsc::channel();

        let shared = Arc::new(Shared {
            store,
            sink,
            status: Mutex::new(EngineStatus::Stopped),
            stop: Arc::new(AtomicBool::new(false)),
            wake: Mutex::new(Some(wake_tx)),
            done: Mutex::new(Some(done_rx)),
        });

        // Announced before the thread exists so the UI never sees a scan begin
        // from a status it was never told about.
        shared.set_status(EngineStatus::Idle);

        let worker = Arc::clone(&shared);
        let thread = std::thread::Builder::new()
            .name("autotidy-engine".to_string())
            .spawn(move || supervise(worker, wake_rx, done_tx))
            .expect("could not spawn the AutoTidy engine thread");

        Self {
            shared,
            thread: Some(thread),
        }
    }

    pub fn status(&self) -> EngineStatus {
        *self.shared.status.lock().unwrap()
    }

    /// Interrupt the interval wait and scan immediately.
    ///
    /// The signal is queued, not coalesced with an in-flight scan: asking for a
    /// scan while one is running schedules another, because the file the user
    /// just dropped in may have arrived after the walk passed that folder.
    pub fn scan_now(&self) {
        self.shared.wake();
    }

    /// Signal shutdown and wait up to `timeout` for the thread to finish.
    ///
    /// Returns `false` on timeout. 1.5.0 gave the worker 2s, then showed a tray
    /// notification and waited 8s more; the shell reproduces that by calling
    /// this twice.
    pub fn stop(&mut self, timeout: Duration) -> bool {
        // Already reaped by an earlier call: nothing left to wait for.
        let Some(thread) = self.thread.take() else {
            return true;
        };

        // Flag first, then announce: the reverse order lets the worker slip in
        // a `StatusChanged { Idle }` after the UI has been told we're stopping.
        self.shared.stop.store(true, Ordering::Relaxed);
        self.shared.set_status(EngineStatus::Stopping);
        self.shared.wake();

        let finished = {
            let done = self.shared.done.lock().unwrap();
            match done.as_ref() {
                Some(rx) => match rx.recv_timeout(timeout) {
                    Ok(()) => true,
                    // The sender died with the thread — it is gone either way,
                    // so `join` will not block.
                    Err(mpsc::RecvTimeoutError::Disconnected) => true,
                    Err(mpsc::RecvTimeoutError::Timeout) => false,
                },
                None => true,
            }
        };

        if !finished {
            // Hand the join handle back so a second, longer `stop` can still
            // reap the thread — this is exactly how the shell reproduces
            // 1.5.0's 2s-then-notify-then-8s shutdown.
            self.thread = Some(thread);
            return false;
        }

        let _ = thread.join();
        self.shared.set_status(EngineStatus::Stopped);
        true
    }
}

// ---------------------------------------------------------------------------
// The supervisor thread
// ---------------------------------------------------------------------------

/// A live filesystem watch plus the inputs it was built from, so the loop can
/// tell whether a config reload actually changed anything.
struct ActiveWatch {
    _handle: WatchHandle,
    roots: Vec<PathBuf>,
    recursive: bool,
    debounce: Duration,
}

fn supervise(shared: Arc<Shared>, wake_rx: mpsc::Receiver<()>, done: mpsc::Sender<()>) {
    // 1.5.0 scanned at the top of its loop, before its first `wait`. Starting
    // the app therefore tidies immediately rather than an hour later — unless
    // shutdown beat us to the thread being scheduled at all.
    if !shared.should_stop() {
        run_cycle(&shared, None);
    }

    let mut watch_slot: Option<ActiveWatch> = None;

    while !shared.should_stop() {
        // Re-read per iteration for the schedule the same way `run_cycle`
        // re-reads for the rules: 1.5.0 called `get_schedule_config()` at the
        // bottom of every pass, which is why changing the interval in the UI
        // takes effect without a restart.
        let config = match shared.store.load() {
            Ok(config) => config,
            Err(err) => {
                shared.log(
                    LogLevel::Warning,
                    format!("Could not read the schedule from configuration: {err}"),
                );
                Config::default()
            }
        };

        let triggered = match schedule_mode(&config) {
            ScheduleMode::Interval => {
                // Release any watcher left over from watch mode.
                watch_slot = None;
                match wake_rx.recv_timeout(config.settings.interval()) {
                    // Woken early by `scan_now` or by `stop`.
                    Ok(()) => true,
                    // The interval elapsed: the ordinary case.
                    Err(mpsc::RecvTimeoutError::Timeout) => true,
                    Err(mpsc::RecvTimeoutError::Disconnected) => break,
                }
            }
            ScheduleMode::Watch => {
                ensure_watch(&shared, &config, &mut watch_slot);
                match wake_rx.recv_timeout(WATCH_POLL) {
                    Ok(()) => true,
                    // Nothing happened; loop round and re-read the config.
                    Err(mpsc::RecvTimeoutError::Timeout) => false,
                    Err(mpsc::RecvTimeoutError::Disconnected) => break,
                }
            }
        };

        // Collapse a pile-up (a debounced batch plus a manual `scan_now`) into
        // the single scan about to run. Anything signalled *during* that scan
        // arrives after this drain and correctly earns another pass.
        while wake_rx.try_recv().is_ok() {}

        if shared.should_stop() {
            break;
        }
        if triggered {
            run_cycle(&shared, None);
        }
    }

    // Drop the watcher before signalling, so the handle is gone by the time
    // `stop` returns and the caller is free to tear the process down.
    drop(watch_slot);
    shared.log(LogLevel::Info, "Monitoring worker stopped.");
    let _ = done.send(());
}

fn schedule_mode(config: &Config) -> ScheduleMode {
    // "interval" (and anything unrecognised) keeps 1.5.0's timer behaviour, so
    // an existing config is never silently switched to watch mode.
    if config
        .settings
        .schedule_type
        .trim()
        .eq_ignore_ascii_case("watch")
    {
        ScheduleMode::Watch
    } else {
        ScheduleMode::Interval
    }
}

/// Watch-mode debounce, overridable through the settings block.
///
/// Carried in `settings.extra` rather than a typed field: it is a tuning knob
/// with a good default, and `extra` already round-trips unknown keys, so
/// nothing needs to change in the config schema to expose it.
fn watch_debounce(config: &Config) -> Duration {
    config
        .settings
        .extra
        .get("watch_debounce_ms")
        .and_then(serde_json::Value::as_u64)
        .map(Duration::from_millis)
        .unwrap_or(DEFAULT_DEBOUNCE)
}

/// The folders watch mode should subscribe to, and the destinations whose
/// events must be ignored.
///
/// The guards are the whole reason this is not just "watch every rule's path":
/// moving a file into `_Cleanup` is itself a filesystem event, and reacting to
/// it would schedule a scan that moves more files that fire more events. The
/// same prefixes `scan::guard_paths` prunes from the walk are dropped here.
fn watch_targets(config: &Config) -> (Vec<PathBuf>, Vec<PathBuf>) {
    let mut roots: Vec<PathBuf> = Vec::new();
    let mut guards: Vec<PathBuf> = Vec::new();

    for rule in config.active_rules() {
        let folder = PathBuf::from(&rule.path);
        if !folder.is_dir() || config.is_globally_excluded(&folder) {
            continue;
        }
        let template = rule.effective_template(&config.settings.archive_path_template);
        guards.extend(guard_paths(rule, template, &folder));
        roots.push(folder);
    }

    roots.sort();
    roots.dedup();
    guards.sort();
    guards.dedup();
    (roots, guards)
}

/// Bring the live watch in line with `config`, rebuilding only when the set of
/// folders, the recursion flag, or the debounce actually changed.
fn ensure_watch(shared: &Shared, config: &Config, slot: &mut Option<ActiveWatch>) {
    let (roots, guards) = watch_targets(config);
    // A rule that only scans its top level must not be woken by a change ten
    // directories down, so the watch tracks the same depth setting the walk does.
    let recursive = config.settings.max_directory_depth > 0;
    let debounce = watch_debounce(config);

    if let Some(active) = slot.as_ref() {
        if active.roots == roots && active.recursive == recursive && active.debounce == debounce {
            return;
        }
    }
    // Drop the old watcher before building its replacement so the two never
    // hold overlapping subscriptions.
    *slot = None;

    if roots.is_empty() {
        return;
    }

    let Some(waker) = shared.waker() else {
        return;
    };

    match crate::watch::watch(&roots, recursive, debounce, move |batch| {
        if batch.paths.iter().any(|path| is_relevant(path, &guards)) {
            let _ = waker.send(());
        }
    }) {
        Ok(handle) => {
            shared.log(
                LogLevel::Info,
                format!("Watching {} folder(s) for changes.", roots.len()),
            );
            *slot = Some(ActiveWatch {
                _handle: handle,
                roots,
                recursive,
                debounce,
            });
        }
        Err(err) => {
            // Leave the slot empty: the next `WATCH_POLL` retries, so a folder
            // that reappears is picked up without a restart.
            let message = format!("Could not watch the configured folders: {err}");
            shared.log(LogLevel::Error, message.clone());
            shared.notify(
                config,
                NotificationCategory::Error,
                "AutoTidy Error",
                message,
            );
        }
    }
}

/// One scan cycle over the current on-disk config.
///
/// Reloading per cycle is deliberate: it is how a rule edited in the UI takes
/// effect without restarting the engine, and it matches 1.5.0, which called
/// `get_monitored_folders()` at the top of every loop iteration.
// `Shared` is crate-private, which makes this effectively crate-private too —
// the shell drives the engine through `EngineHandle`, never through here. The
// signature is fixed by the API contract, so the lint is silenced rather than
// resolved by widening `Shared`'s visibility.
#[allow(private_interfaces)]
pub fn run_cycle(shared: &Shared, opts_override: Option<ScanOptions>) -> Option<ScanReport> {
    let config = match shared.store.load() {
        Ok(config) => config,
        Err(err) => {
            // Deliberately log-only. Gating a notification needs a
            // `notification_level`, and the file that carries it is the one we
            // just failed to read; guessing "all" would talk over a user who
            // asked for silence.
            shared.log(
                LogLevel::Error,
                format!("Could not read configuration: {err}"),
            );
            return None;
        }
    };

    let rules: Vec<&Rule> = config.active_rules().collect();
    if rules.is_empty() {
        shared.log(LogLevel::Info, "No folders configured for monitoring.");
        return None;
    }

    let opts = opts_override.unwrap_or(ScanOptions {
        dry_run: config.settings.dry_run_mode,
        max_depth: config.settings.max_directory_depth,
        threads: 0,
        // Hand the scanner the same stop flag the supervisor watches, so a
        // shutdown aborts between files rather than only between rules. Without
        // this, stopping during a scan of one large folder has to wait for that
        // whole folder — worse than worker.py, which checked per file.
        cancel: Some(Arc::clone(&shared.stop)),
    });

    let run_id = uuid::Uuid::new_v4().to_string();
    let prefix = if opts.dry_run { "[DRY RUN] " } else { "" };

    shared.set_status(EngineStatus::Scanning);
    shared.sink.emit(EngineEvent::ScanStarted {
        run_id: run_id.clone(),
        folders: rules.len(),
    });
    shared.log(
        LogLevel::Info,
        format!(
            "{prefix}Starting scan of {} configured folder(s)...",
            rules.len()
        ),
    );

    let report = scan_interruptibly(shared, &config, &rules, &run_id, &opts);

    // History is written before `ScanFinished` is announced, so a UI that
    // refreshes the log on that event never reads a half-written cycle.
    let history = HistoryLog::new(shared.store.history_path());
    for record in &report.records {
        if let Err(err) = history.append(record) {
            shared.log(
                LogLevel::Warning,
                format!("Could not write a history entry: {err}"),
            );
        }
    }

    // `_log_error` in worker.py did both: a log line and an error notification.
    for error in &report.errors {
        shared.log(LogLevel::Error, error.clone());
        shared.notify(
            &config,
            NotificationCategory::Error,
            "AutoTidy Error",
            error.clone(),
        );
    }

    shared.sink.emit(EngineEvent::ScanFinished {
        run_id,
        processed: report.processed,
        skipped: report.skipped,
        failed: report.failed,
        dry_run: opts.dry_run,
    });

    if report.processed > 0 {
        shared.notify(
            &config,
            NotificationCategory::Summary,
            "AutoTidy Scan Complete",
            format!("{} file(s) processed successfully.", report.processed),
        );
    }
    shared.log(LogLevel::Info, "Scan cycle complete.");

    // A shutdown mid-cycle owns the status from here on; overwriting it with
    // `Idle` would flash the UI back to "running" as the app closes.
    if !shared.should_stop() {
        shared.set_status(EngineStatus::Idle);
    }

    Some(report)
}

/// `scan::scan_all`, re-driven rule by rule so shutdown is not stuck behind a
/// whole cycle.
///
/// Two things force this rather than a plain `scan_all` call:
///
/// * **Interruption.** `scan_all` runs to completion; here the stop flag is
///   checked before each rule, which bounds shutdown at one folder rather than
///   one full sweep. It cannot be finer than that without changing `scan.rs`:
///   the per-file loop lives in `scan_rule` and has no cancellation hook, so a
///   single very large folder still has to finish. In practice the file
///   operations themselves are atomic, so stopping between rules never leaves a
///   half-moved file.
/// * **The run id.** `scan_all` mints its own id internally, so `ScanStarted`
///   could only be emitted *after* the scan it announces had already finished.
///
/// The two pre-checks below are `scan_all`'s, verbatim, and a test pins the two
/// paths to the same output.
fn scan_interruptibly(
    shared: &Shared,
    config: &Config,
    rules: &[&Rule],
    run_id: &str,
    opts: &ScanOptions,
) -> ScanReport {
    let mut report = ScanReport {
        run_id: run_id.to_string(),
        ..Default::default()
    };

    for rule in rules {
        if shared.should_stop() {
            shared.log(
                LogLevel::Info,
                "Stop requested; ending this scan after the current folder.",
            );
            break;
        }

        let folder = PathBuf::from(&rule.path);
        if !folder.is_dir() {
            report.errors.push(format!(
                "Monitored path is not a directory or does not exist: {}",
                rule.path
            ));
            continue;
        }
        if config.is_globally_excluded(&folder) {
            shared.log(
                LogLevel::Info,
                format!("Skipping globally excluded folder: {}", rule.path),
            );
            continue;
        }

        scan_rule(rule, config, run_id, opts, &mut report);
    }

    report
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{normalize, NotificationLevel};
    use crate::history::Status;
    use std::fs;
    use std::time::Instant;
    use tempfile::TempDir;

    /// Ceiling on "this event should turn up". Never waited out on a passing
    /// run — the tests block on channels, not on sleeps — so a generous value
    /// costs nothing and keeps a loaded machine from failing the suite.
    const ARRIVAL: Duration = Duration::from_secs(10);

    struct Fixture {
        tmp: TempDir,
        store: ConfigStore,
        watched: PathBuf,
        events: mpsc::Receiver<EngineEvent>,
        sink: Arc<dyn EventSink>,
    }

    fn fixture() -> Fixture {
        let tmp = tempfile::tempdir().unwrap();
        let config_dir = tmp.path().join("config");
        let watched = tmp.path().join("watched");
        fs::create_dir_all(&config_dir).unwrap();
        fs::create_dir_all(&watched).unwrap();

        let (tx, events) = mpsc::channel();
        let sink: Arc<dyn EventSink> = Arc::new(ChannelSink(tx));

        Fixture {
            store: ConfigStore::new(config_dir),
            watched,
            events,
            sink,
            tmp,
        }
    }

    impl Fixture {
        /// One enabled rule over the watched folder that matches every file
        /// (`age_days = 0` satisfies the age half, `*.*` the pattern half).
        fn config(&self) -> Config {
            let mut config = Config::default();
            let mut rule = Rule::new(self.watched.to_string_lossy().into_owned());
            rule.age_days = 0;
            config.folders.push(rule);
            config
        }

        fn save(&self, config: &Config) {
            self.store.save(config).unwrap();
        }

        fn start(&self) -> EngineHandle {
            EngineHandle::start(self.store.clone(), Arc::clone(&self.sink))
        }

        fn write(&self, name: &str) {
            fs::write(self.watched.join(name), b"contents").unwrap();
        }
    }

    /// Collect events until one satisfies `pred`, returning the run including
    /// that event. Blocks on the channel rather than sleeping.
    fn collect_through<F>(
        rx: &mpsc::Receiver<EngineEvent>,
        what: &str,
        mut pred: F,
    ) -> Vec<EngineEvent>
    where
        F: FnMut(&EngineEvent) -> bool,
    {
        let deadline = Instant::now() + ARRIVAL;
        let mut seen = Vec::new();
        loop {
            let left = deadline.saturating_duration_since(Instant::now());
            if left.is_zero() {
                panic!("timed out waiting for {what}; saw {seen:#?}");
            }
            match rx.recv_timeout(left) {
                Ok(event) => {
                    let matched = pred(&event);
                    seen.push(event);
                    if matched {
                        return seen;
                    }
                }
                Err(_) => panic!("timed out waiting for {what}; saw {seen:#?}"),
            }
        }
    }

    fn wait_for<F>(rx: &mpsc::Receiver<EngineEvent>, what: &str, pred: F) -> EngineEvent
    where
        F: FnMut(&EngineEvent) -> bool,
    {
        collect_through(rx, what, pred).pop().expect("one event")
    }

    /// Assert that nothing matching `pred` shows up inside `window`.
    fn assert_quiet<F>(rx: &mpsc::Receiver<EngineEvent>, window: Duration, what: &str, mut pred: F)
    where
        F: FnMut(&EngineEvent) -> bool,
    {
        let deadline = Instant::now() + window;
        loop {
            let left = deadline.saturating_duration_since(Instant::now());
            if left.is_zero() {
                return;
            }
            match rx.recv_timeout(left) {
                Ok(event) if pred(&event) => panic!("unexpected {what}: {event:?}"),
                Ok(_) => {}
                Err(_) => return,
            }
        }
    }

    fn drain(rx: &mpsc::Receiver<EngineEvent>) -> Vec<EngineEvent> {
        let mut out = Vec::new();
        while let Ok(event) = rx.try_recv() {
            out.push(event);
        }
        out
    }

    /// The lifecycle events only, so ordering can be asserted without pinning
    /// every log line.
    fn shape(events: &[EngineEvent]) -> Vec<String> {
        events
            .iter()
            .filter_map(|event| match event {
                EngineEvent::StatusChanged { status } => Some(format!("{status:?}")),
                EngineEvent::ScanStarted { .. } => Some("ScanStarted".to_string()),
                EngineEvent::ScanFinished { .. } => Some("ScanFinished".to_string()),
                _ => None,
            })
            .collect()
    }

    fn is_finished(event: &EngineEvent) -> bool {
        matches!(event, EngineEvent::ScanFinished { .. })
    }

    fn finished_with(count: usize) -> impl FnMut(&EngineEvent) -> bool {
        move |event| matches!(event, EngineEvent::ScanFinished { processed, .. } if *processed == count)
    }

    // -----------------------------------------------------------------------
    // Lifecycle
    // -----------------------------------------------------------------------

    #[test]
    fn start_scans_immediately_and_emits_events_in_order() {
        let fixture = fixture();
        fixture.write("stale.txt");
        fixture.save(&fixture.config());

        let mut engine = fixture.start();
        let seen = collect_through(&fixture.events, "the first ScanFinished", is_finished);

        // 1.5.0 scanned at the top of its loop, so a fresh start tidies at once
        // rather than an interval later.
        assert_eq!(
            shape(&seen),
            vec!["Idle", "Scanning", "ScanStarted", "ScanFinished"],
            "full run was {seen:#?}"
        );
        match seen.last().unwrap() {
            EngineEvent::ScanFinished {
                processed,
                failed,
                dry_run,
                ..
            } => {
                assert_eq!(*processed, 1);
                assert_eq!(*failed, 0);
                assert!(!dry_run);
            }
            other => panic!("expected ScanFinished, got {other:?}"),
        }
        assert!(
            !fixture.watched.join("stale.txt").exists(),
            "the file should have been archived"
        );

        assert!(engine.stop(Duration::from_secs(5)));
    }

    #[test]
    fn a_run_with_no_active_rules_scans_nothing() {
        let fixture = fixture();
        fixture.save(&Config::default());

        let mut engine = fixture.start();
        let seen = collect_through(
            &fixture.events,
            "the no-folders log",
            |event| matches!(event, EngineEvent::Log { message, .. } if message.contains("No folders configured")),
        );
        assert!(
            !seen
                .iter()
                .any(|e| matches!(e, EngineEvent::ScanStarted { .. })),
            "an empty config must not announce a scan: {seen:#?}"
        );

        assert!(engine.stop(Duration::from_secs(5)));
    }

    #[test]
    fn scan_now_triggers_an_extra_cycle() {
        let fixture = fixture();
        fixture.save(&fixture.config());

        let mut engine = fixture.start();
        // The interval is 60 minutes, so nothing but scan_now can cause a
        // second cycle inside this test.
        wait_for(&fixture.events, "the first ScanFinished", is_finished);

        fixture.write("arrived-later.txt");
        engine.scan_now();

        wait_for(
            &fixture.events,
            "a second ScanFinished that processed the new file",
            finished_with(1),
        );
        assert!(!fixture.watched.join("arrived-later.txt").exists());

        assert!(engine.stop(Duration::from_secs(5)));
    }

    #[test]
    fn stop_reports_success_and_leaves_the_engine_stopped() {
        let fixture = fixture();
        fixture.save(&fixture.config());

        let mut engine = fixture.start();
        wait_for(&fixture.events, "the first ScanFinished", is_finished);

        assert!(
            engine.stop(Duration::from_secs(5)),
            "stop should not time out"
        );
        assert_eq!(engine.status(), EngineStatus::Stopped);

        let tail = shape(&drain(&fixture.events));
        let stopping = tail.iter().position(|s| s == "Stopping");
        let stopped = tail.iter().position(|s| s == "Stopped");
        assert!(
            stopping.is_some() && stopped.is_some() && stopping < stopped,
            "expected Stopping then Stopped, got {tail:?}"
        );

        // The thread is already reaped; a repeat call must not block or lie.
        assert!(engine.stop(Duration::from_millis(1)));
    }

    #[test]
    fn a_stop_that_times_out_can_still_be_reaped_by_a_second_call() {
        let fixture = fixture();
        fixture.save(&fixture.config());

        let mut engine = fixture.start();
        wait_for(&fixture.events, "the first ScanFinished", is_finished);

        // Zero budget: this may or may not win the race, which is the point —
        // either way it must return promptly rather than block on `join`.
        let _first = engine.stop(Duration::ZERO);
        assert!(
            engine.stop(Duration::from_secs(5)),
            "the follow-up stop must reap the thread"
        );
        assert_eq!(engine.status(), EngineStatus::Stopped);
    }

    // -----------------------------------------------------------------------
    // Config reload, history, notifications
    // -----------------------------------------------------------------------

    #[test]
    fn a_config_edited_between_cycles_takes_effect_on_the_next_one() {
        let fixture = fixture();
        fixture.write("waiting.txt");

        let mut disabled = fixture.config();
        disabled.folders[0].enabled = false;
        fixture.save(&disabled);

        let mut engine = fixture.start();
        wait_for(
            &fixture.events,
            "the no-folders log",
            |event| matches!(event, EngineEvent::Log { message, .. } if message.contains("No folders configured")),
        );
        assert!(fixture.watched.join("waiting.txt").exists());

        // The UI would write this; the engine must pick it up without a restart.
        fixture.save(&fixture.config());
        engine.scan_now();

        wait_for(
            &fixture.events,
            "a ScanFinished from the re-enabled rule",
            finished_with(1),
        );
        assert!(!fixture.watched.join("waiting.txt").exists());

        assert!(engine.stop(Duration::from_secs(5)));
    }

    #[test]
    fn every_scan_record_reaches_the_history_file() {
        let fixture = fixture();
        fixture.write("logged.txt");
        fixture.save(&fixture.config());

        let mut engine = fixture.start();
        let finished = wait_for(&fixture.events, "the first ScanFinished", finished_with(1));
        let run_id = match &finished {
            EngineEvent::ScanFinished { run_id, .. } => run_id.clone(),
            other => panic!("expected ScanFinished, got {other:?}"),
        };

        let records = HistoryLog::new(fixture.store.history_path())
            .read_all()
            .unwrap();
        assert_eq!(records.len(), 1, "got {records:#?}");
        assert_eq!(records[0].action_taken, "MOVED");
        assert_eq!(records[0].status, Status::Success);
        // The id on the wire and the id on disk have to be the same run.
        assert_eq!(records[0].run_id, run_id);

        assert!(engine.stop(Duration::from_secs(5)));
    }

    #[test]
    fn a_summary_notification_follows_a_productive_cycle() {
        let fixture = fixture();
        fixture.write("noticed.txt");
        let mut config = fixture.config();
        config.settings.notification_level = NotificationLevel::All;
        fixture.save(&config);

        let mut engine = fixture.start();
        let notify = wait_for(
            &fixture.events,
            "a summary notification",
            |event| matches!(event, EngineEvent::Notify { category, .. } if *category == "summary"),
        );
        match notify {
            EngineEvent::Notify { message, title, .. } => {
                assert_eq!(title, "AutoTidy Scan Complete");
                // Wording preserved from worker.py so the tray text is unchanged.
                assert_eq!(message, "1 file(s) processed successfully.");
            }
            other => panic!("expected Notify, got {other:?}"),
        }

        assert!(engine.stop(Duration::from_secs(5)));
    }

    #[test]
    fn notification_level_none_suppresses_every_notification() {
        let fixture = fixture();
        fixture.write("silent.txt");
        let mut config = fixture.config();
        config.settings.notification_level = NotificationLevel::None;
        fixture.save(&config);

        let mut engine = fixture.start();
        // The trailing `Idle` is emitted after the summary would have been, so
        // reaching it proves the notification was never sent rather than late.
        let seen = collect_through(&fixture.events, "the post-scan Idle", |event| {
            matches!(event, EngineEvent::ScanFinished { .. })
        });
        let tail = collect_through(&fixture.events, "the post-scan Idle", |event| {
            matches!(
                event,
                EngineEvent::StatusChanged {
                    status: EngineStatus::Idle
                }
            )
        });

        for event in seen.iter().chain(tail.iter()) {
            assert!(
                !matches!(event, EngineEvent::Notify { .. }),
                "level=none must emit no notifications, got {event:?}"
            );
        }
        // ...while the work itself still happened.
        assert!(!fixture.watched.join("silent.txt").exists());

        assert!(engine.stop(Duration::from_secs(5)));
    }

    #[test]
    fn a_folder_level_error_is_both_logged_and_notified() {
        let fixture = fixture();
        let mut config = fixture.config();
        config.folders[0].path = fixture
            .tmp
            .path()
            .join("never-existed")
            .to_string_lossy()
            .into_owned();
        fixture.save(&config);

        let mut engine = fixture.start();
        wait_for(&fixture.events, "an error log", |event| {
            matches!(event, EngineEvent::Log { level: LogLevel::Error, message }
                if message.contains("is not a directory or does not exist"))
        });
        wait_for(
            &fixture.events,
            "an error notification",
            |event| matches!(event, EngineEvent::Notify { category, .. } if *category == "error"),
        );

        assert!(engine.stop(Duration::from_secs(5)));
    }

    #[test]
    fn dry_run_is_reported_and_changes_nothing_on_disk() {
        let fixture = fixture();
        fixture.write("rehearsal.txt");
        let mut config = fixture.config();
        config.settings.dry_run_mode = true;
        fixture.save(&config);

        let mut engine = fixture.start();
        let finished = wait_for(&fixture.events, "the first ScanFinished", is_finished);
        match finished {
            EngineEvent::ScanFinished { dry_run, .. } => assert!(dry_run),
            other => panic!("expected ScanFinished, got {other:?}"),
        }
        assert!(fixture.watched.join("rehearsal.txt").exists());

        assert!(engine.stop(Duration::from_secs(5)));
    }

    // -----------------------------------------------------------------------
    // The interruptible scan
    // -----------------------------------------------------------------------

    /// A `Shared` with no thread behind it, for driving `run_cycle` and
    /// `scan_interruptibly` directly.
    fn detached(store: ConfigStore) -> Shared {
        Shared {
            store,
            sink: Arc::new(NullSink),
            status: Mutex::new(EngineStatus::Idle),
            stop: Arc::new(AtomicBool::new(false)),
            wake: Mutex::new(None),
            done: Mutex::new(None),
        }
    }

    #[test]
    fn the_interruptible_scan_agrees_with_scan_all() {
        let fixture = fixture();
        fixture.write("a.txt");
        fixture.write("b.txt");

        let excluded = fixture.tmp.path().join("excluded");
        fs::create_dir_all(&excluded).unwrap();
        fs::write(excluded.join("c.txt"), b"x").unwrap();

        let mut config = fixture.config();
        // A globally excluded rule and a rule whose folder is gone, so both of
        // the pre-checks copied out of `scan_all` are exercised.
        let mut excluded_rule = Rule::new(excluded.to_string_lossy().into_owned());
        excluded_rule.age_days = 0;
        config.folders.push(excluded_rule);
        config
            .excluded_folders
            .push(normalize(&excluded).to_string_lossy().into_owned());
        let mut missing = Rule::new(
            fixture
                .tmp
                .path()
                .join("gone")
                .to_string_lossy()
                .into_owned(),
        );
        missing.age_days = 0;
        config.folders.push(missing);

        // Dry run so both passes see an identical tree.
        let opts = ScanOptions {
            dry_run: true,
            ..Default::default()
        };
        let expected = crate::scan::scan_all(&config, &opts);

        let shared = detached(fixture.store.clone());
        let rules: Vec<&Rule> = config.active_rules().collect();
        let actual = scan_interruptibly(&shared, &config, &rules, "run-1", &opts);

        assert_eq!(actual.processed, expected.processed);
        assert_eq!(actual.skipped, expected.skipped);
        assert_eq!(actual.failed, expected.failed);
        assert_eq!(actual.errors, expected.errors);
        assert_eq!(actual.records.len(), expected.records.len());
        assert_eq!(
            actual.errors.len(),
            1,
            "the missing folder must be reported"
        );
    }

    #[test]
    fn a_pending_stop_ends_the_scan_before_the_first_rule() {
        let fixture = fixture();
        fixture.write("untouched.txt");
        let config = fixture.config();

        let shared = detached(fixture.store.clone());
        shared.stop.store(true, Ordering::Relaxed);

        let rules: Vec<&Rule> = config.active_rules().collect();
        let report = scan_interruptibly(&shared, &config, &rules, "run-1", &ScanOptions::default());

        assert_eq!(report.processed, 0);
        assert!(report.records.is_empty());
        assert!(fixture.watched.join("untouched.txt").exists());
    }

    #[test]
    fn run_cycle_returns_none_when_there_is_nothing_to_do() {
        let fixture = fixture();
        fixture.save(&Config::default());
        let shared = detached(fixture.store.clone());
        assert!(run_cycle(&shared, None).is_none());
    }

    // -----------------------------------------------------------------------
    // Watch mode
    // -----------------------------------------------------------------------

    #[test]
    fn schedule_type_selects_the_mode_and_defaults_to_interval() {
        let mut config = Config::default();
        assert_eq!(schedule_mode(&config), ScheduleMode::Interval);
        config.settings.schedule_type = "watch".into();
        assert_eq!(schedule_mode(&config), ScheduleMode::Watch);
        config.settings.schedule_type = " WATCH ".into();
        assert_eq!(schedule_mode(&config), ScheduleMode::Watch);
        // Anything unrecognised keeps 1.5.0's timer behaviour.
        config.settings.schedule_type = "cron".into();
        assert_eq!(schedule_mode(&config), ScheduleMode::Interval);
    }

    #[test]
    fn watch_targets_exclude_the_archive_each_rule_writes_into() {
        let fixture = fixture();
        let config = fixture.config();
        let (roots, guards) = watch_targets(&config);

        assert_eq!(roots, vec![fixture.watched.clone()]);
        assert_eq!(
            guards,
            vec![normalize(&fixture.watched.join("_Cleanup"))],
            "the destination prefix must be filtered out of the watch"
        );
    }

    #[test]
    fn watch_mode_reacts_to_real_changes_but_not_to_its_own_archive_writes() {
        let fixture = fixture();
        let archive = fixture.watched.join("_Cleanup").join("2020-01-01");
        // Pre-created so the recursive watch covers it from the start.
        fs::create_dir_all(&archive).unwrap();

        let mut config = fixture.config();
        config.settings.schedule_type = "watch".into();
        // A recursive watch is the only way archive events reach us at all —
        // with a flat watch there would be nothing for the guard to filter.
        config.settings.max_directory_depth = 3;
        config
            .settings
            .extra
            .insert("watch_debounce_ms".into(), 120.into());
        fixture.save(&config);

        let mut engine = fixture.start();
        wait_for(&fixture.events, "the initial ScanFinished", is_finished);
        wait_for(
            &fixture.events,
            "the watch to be established",
            |event| matches!(event, EngineEvent::Log { message, .. } if message.starts_with("Watching ")),
        );

        // The feedback loop this guard exists to break: a write inside the
        // destination must not schedule a scan that writes more files.
        fs::write(archive.join("already-archived.txt"), b"x").unwrap();
        assert_quiet(
            &fixture.events,
            Duration::from_millis(800),
            "scan triggered by an archive write",
            is_finished,
        );

        // A genuine change still wakes it.
        fixture.write("dropped-in.txt");
        wait_for(
            &fixture.events,
            "a ScanFinished for the new file",
            finished_with(1),
        );
        assert!(!fixture.watched.join("dropped-in.txt").exists());
        assert!(
            archive.join("already-archived.txt").exists(),
            "files already in the archive must be left alone"
        );

        assert!(engine.stop(Duration::from_secs(5)));
    }
}
