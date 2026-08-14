//! The scan loop: walk monitored folders, decide, act.
//!
//! Ported from `MonitoringWorker.run` in `worker.py`, with two changes that are
//! the point of the rewrite:
//!
//! * **Recursion.** 1.5.0 did a single flat `os.scandir`. Here the walk honours
//!   `max_directory_depth` (`0` keeps the old flat behaviour, so existing
//!   configs upgrade unchanged).
//! * **Parallel discovery.** Directory traversal is the syscall-heavy half and
//!   runs across threads; the *actions* then run sequentially over a sorted
//!   list. Moving files in parallel would buy little on one disk and would make
//!   collision suffixing non-deterministic, which in turn would make the
//!   differential test against the Python engine unreproducible.
//!
//! ## The archive-loop guard
//!
//! Recursion introduces a failure mode flat scanning could not have. The
//! default template `_Cleanup/{YYYY}-{MM}-{DD}` resolves *inside* the monitored
//! folder — real user history confirms this is the common setup — so a
//! recursive walk would descend into the archive it just wrote and re-process
//! those files forever. Every rule's destination is therefore pruned from its
//! own walk before descent.

use crate::action::{self, ActionContext};
use crate::config::{normalize, Config, Rule};
use crate::history::{HistoryRecord, Status};
use crate::rule::CompiledRule;
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

/// Every field's default is its type's default — `dry_run: false` (act for
/// real), `max_depth: 0` (flat, as 1.5.0 scanned), `threads: 0` (let the walker
/// choose), `cancel: None` (uninterruptible).
#[derive(Debug, Clone, Default)]
pub struct ScanOptions {
    pub dry_run: bool,
    /// `0` = the monitored folder only, matching 1.5.0's flat scan.
    pub max_depth: u32,
    /// Discovery threads. `0` lets the walker choose.
    pub threads: usize,
    /// Cooperative cancellation, checked **between files**.
    ///
    /// `worker.py` tested `_stop_event` inside its per-file loop, so 1.5.0
    /// could abandon a scan partway through a folder. Without this the engine's
    /// finest granularity is one whole rule, which on a large folder means
    /// shutdown appears to hang — a regression against the app being replaced.
    pub cancel: Option<std::sync::Arc<std::sync::atomic::AtomicBool>>,
}

impl ScanOptions {
    fn cancelled(&self) -> bool {
        self.cancel
            .as_ref()
            .is_some_and(|c| c.load(std::sync::atomic::Ordering::Relaxed))
    }
}

#[derive(Debug, Default)]
pub struct ScanReport {
    pub run_id: String,
    pub records: Vec<HistoryRecord>,
    pub processed: usize,
    pub failed: usize,
    pub skipped: usize,
    /// Folder-level problems (missing directory, permission denied, an
    /// uncompilable pattern) that aren't attributable to any single file.
    pub errors: Vec<String>,
}

/// Run one full cycle over every active rule.
pub fn scan_all(config: &Config, opts: &ScanOptions) -> ScanReport {
    let run_id = uuid::Uuid::new_v4().to_string();
    let mut report = ScanReport {
        run_id: run_id.clone(),
        ..Default::default()
    };

    for rule in config.active_rules() {
        let folder = PathBuf::from(&rule.path);

        if !folder.is_dir() {
            report.errors.push(format!(
                "Monitored path is not a directory or does not exist: {}",
                rule.path
            ));
            continue;
        }
        // Global exclusions are checked before scanning, matching worker.py.
        if config.is_globally_excluded(&folder) {
            tracing::info!(path = %rule.path, "skipping globally excluded folder");
            continue;
        }

        scan_rule(rule, config, &run_id, opts, &mut report);
    }

    report
}

/// Run one rule over its folder, appending to `report`.
pub fn scan_rule(
    rule: &Rule,
    config: &Config,
    run_id: &str,
    opts: &ScanOptions,
    report: &mut ScanReport,
) {
    let folder = PathBuf::from(&rule.path);

    let compiled = match CompiledRule::compile(rule) {
        Ok(c) => c,
        Err(e) => {
            // 1.5.0 logged this and treated the file as non-matching, silently
            // disabling a rule the user believes is running. Surfaced instead.
            report.errors.push(format!(
                "Rule for {} has an invalid pattern: {e}",
                rule.path
            ));
            return;
        }
    };

    let template = rule.effective_template(&config.settings.archive_path_template);
    let guards = guard_paths(rule, template, &folder);
    let now = SystemTime::now();

    let files = match discover(&folder, opts, &guards) {
        Ok(files) => files,
        Err(e) => {
            report
                .errors
                .push(format!("Error scanning {}: {e}", folder.display()));
            return;
        }
    };

    for file in files {
        // Per-file cancellation, matching worker.py's `_stop_event` check
        // inside its own file loop. Checked before acting, never mid-operation:
        // a move already underway must be allowed to finish or it could leave a
        // file half-relocated.
        if opts.cancelled() {
            tracing::info!(folder = %folder.display(), "scan cancelled");
            return;
        }

        let name = match file.file_name().and_then(|n| n.to_str()) {
            Some(n) => n.to_string(),
            None => continue,
        };

        if compiled.is_excluded(&name) {
            report.skipped += 1;
            report.records.push(
                HistoryRecord {
                    original_path: file.to_string_lossy().into_owned(),
                    action_taken: "SKIPPED".to_string(),
                    destination_path: None,
                    monitored_folder: folder.to_string_lossy().into_owned(),
                    rule_pattern: rule.pattern.clone(),
                    rule_age_days: rule.age_days,
                    rule_use_regex: rule.use_regex,
                    rule_action_config: rule.action.as_str().to_string(),
                    status: Status::Skipped,
                    details: format!("Skipped excluded file: {name}"),
                    run_id: run_id.to_string(),
                    severity: String::new(),
                    timestamp: String::new(),
                    copy_size: None,
                    copy_mtime: None,
                    extra: Default::default(),
                }
                .finalize(),
            );
            continue;
        }

        let modified = match std::fs::symlink_metadata(&file).and_then(|m| m.modified()) {
            Ok(m) => m,
            Err(e) => {
                tracing::warn!(path = %file.display(), %e, "could not stat; skipping");
                continue;
            }
        };

        if !compiled.matches(&name, modified, now) {
            continue;
        }

        let ctx = ActionContext {
            monitored_folder: &folder,
            template,
            action: rule.action,
            dry_run: opts.dry_run,
            run_id,
            rule_pattern: &rule.pattern,
            rule_age_days: rule.age_days,
            rule_use_regex: rule.use_regex,
        };

        match action::process_file(&file, &ctx) {
            Ok(outcome) => {
                if outcome.success {
                    report.processed += 1;
                } else {
                    report.failed += 1;
                }
                report.records.push(outcome.record);
            }
            Err(e) => {
                report.failed += 1;
                report.errors.push(format!("{}: {e}", file.display()));
            }
        }
    }
}

/// Collect candidate files, deepest-first order made deterministic by sorting.
///
/// Sorting is not cosmetic: collision suffixing (`name_1.txt`, `name_2.txt`)
/// depends on the order files are processed, so an unsorted walk would produce
/// different — though equally valid — output on each run and make differential
/// testing impossible.
fn discover(
    folder: &Path,
    opts: &ScanOptions,
    guards: &BTreeSet<PathBuf>,
) -> std::io::Result<Vec<PathBuf>> {
    let mut files = if opts.max_depth == 0 {
        flat_scan(folder)?
    } else {
        recursive_scan(folder, opts, guards)
    };
    files.sort();
    Ok(files)
}

/// `max_depth == 0`: exactly what 1.5.0 did, one `read_dir`, no descent.
fn flat_scan(folder: &Path) -> std::io::Result<Vec<PathBuf>> {
    let mut files = Vec::new();
    for entry in std::fs::read_dir(folder)? {
        let entry = entry?;
        // symlink_metadata so a symlink is never followed — matching
        // `entry.is_symlink()` / `is_file(follow_symlinks=False)`.
        let meta = match entry.metadata() {
            Ok(m) => m,
            Err(_) => continue,
        };
        if meta.file_type().is_symlink() || !meta.is_file() {
            continue;
        }
        files.push(entry.path());
    }
    Ok(files)
}

fn recursive_scan(folder: &Path, opts: &ScanOptions, guards: &BTreeSet<PathBuf>) -> Vec<PathBuf> {
    use ignore::WalkBuilder;

    let mut builder = WalkBuilder::new(folder);
    builder
        .max_depth(Some(opts.max_depth as usize))
        // This is a file organiser, not a code tool: a .gitignore in the user's
        // Downloads folder must not silently exempt files from their rules.
        .git_ignore(false)
        .git_global(false)
        .git_exclude(false)
        .ignore(false)
        .parents(false)
        // `ignore` skips dotfiles by default. 1.5.0 processed them, and real
        // corpora contain them, so hidden files stay in scope.
        .hidden(false)
        .follow_links(false);

    if opts.threads > 0 {
        builder.threads(opts.threads);
    }

    let guards = guards.clone();
    builder.filter_entry(move |entry| {
        // Prune the archive destination before descending into it.
        let path = normalize(entry.path());
        !guards.iter().any(|g| path == *g || path.starts_with(g))
    });

    let mut files = Vec::new();
    for result in builder.build() {
        let entry = match result {
            Ok(e) => e,
            Err(e) => {
                tracing::warn!(%e, "walk error");
                continue;
            }
        };
        match entry.file_type() {
            Some(ft) if ft.is_file() && !ft.is_symlink() => files.push(entry.into_path()),
            _ => {}
        }
    }
    files
}

/// Directories that must never be walked for this rule: its own destination.
///
/// A template is only partly static — `_Cleanup/{YYYY}-{MM}-{DD}` varies daily —
/// so the guard is the deepest **placeholder-free prefix**, here `_Cleanup`.
/// Pruning the prefix covers today's archive and every previous day's, which is
/// what stops re-processing after the date rolls over.
pub fn guard_paths(rule: &Rule, template: &str, monitored: &Path) -> BTreeSet<PathBuf> {
    let mut guards = BTreeSet::new();
    if !rule.action.needs_destination() {
        return guards;
    }

    let stem: String = match template.find('{') {
        Some(idx) => template[..idx].to_string(),
        None => template.to_string(),
    };
    // Trim back to a whole path component: `_Cleanup/2026-` would be a partial
    // segment, and pruning on it would miss the real directory.
    let stem = stem.replace('\\', "/");
    let stem = match stem.rfind('/') {
        Some(idx) => &stem[..idx],
        None => stem.as_str(),
    };
    if stem.is_empty() {
        return guards;
    }

    let candidate = Path::new(stem);
    let resolved = if candidate.is_absolute() {
        normalize(candidate)
    } else {
        normalize(&monitored.join(candidate))
    };

    // Only a destination inside the monitored tree can cause a loop; an archive
    // elsewhere on disk is never walked in the first place.
    if resolved.starts_with(normalize(monitored)) {
        guards.insert(resolved);
    }
    guards
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::Action;

    fn rule_with(template_action: Action) -> Rule {
        let mut r = Rule::new("C:/monitored");
        r.action = template_action;
        r
    }

    #[test]
    fn guard_prunes_the_static_prefix_of_a_dated_template() {
        let rule = rule_with(Action::Move);
        let monitored = Path::new("C:/monitored");
        let guards = guard_paths(&rule, "_Cleanup/{YYYY}-{MM}-{DD}", monitored);
        assert!(
            guards.contains(&normalize(Path::new("C:/monitored/_Cleanup"))),
            "expected the _Cleanup prefix to be pruned, got {guards:?}"
        );
    }

    #[test]
    fn guard_covers_a_fully_static_template() {
        let rule = rule_with(Action::Move);
        let guards = guard_paths(&rule, "Archive/Old", Path::new("C:/monitored"));
        assert!(guards.contains(&normalize(Path::new("C:/monitored/Archive"))));
    }

    #[test]
    fn destination_outside_the_tree_needs_no_guard() {
        let rule = rule_with(Action::Move);
        let guards = guard_paths(&rule, "D:/elsewhere/{YYYY}", Path::new("C:/monitored"));
        assert!(guards.is_empty(), "got {guards:?}");
    }

    #[test]
    fn delete_actions_have_no_destination_to_guard() {
        let rule = rule_with(Action::DeleteToTrash);
        let guards = guard_paths(&rule, "_Cleanup/{YYYY}", Path::new("C:/monitored"));
        assert!(guards.is_empty());
    }

    #[test]
    fn a_template_that_is_only_a_placeholder_yields_no_partial_guard() {
        // "{YYYY}" has no static prefix at all — pruning "" would prune the
        // whole tree, so it must yield nothing.
        let rule = rule_with(Action::Move);
        let guards = guard_paths(&rule, "{YYYY}/{MM}", Path::new("C:/monitored"));
        assert!(guards.is_empty(), "got {guards:?}");
    }

    #[test]
    fn flat_scan_ignores_subdirectories() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("top.txt"), b"x").unwrap();
        std::fs::create_dir_all(dir.path().join("sub")).unwrap();
        std::fs::write(dir.path().join("sub/nested.txt"), b"x").unwrap();

        let found = flat_scan(dir.path()).unwrap();
        assert_eq!(found.len(), 1);
        assert!(found[0].ends_with("top.txt"));
    }

    #[test]
    fn recursive_scan_descends_and_respects_depth() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::create_dir_all(dir.path().join("a/b")).unwrap();
        std::fs::write(dir.path().join("top.txt"), b"x").unwrap();
        std::fs::write(dir.path().join("a/one.txt"), b"x").unwrap();
        std::fs::write(dir.path().join("a/b/two.txt"), b"x").unwrap();

        let opts = ScanOptions {
            max_depth: 1,
            ..Default::default()
        };
        let found = recursive_scan(dir.path(), &opts, &BTreeSet::new());
        assert_eq!(found.len(), 1, "depth 1 sees only the top level: {found:?}");

        let opts = ScanOptions {
            max_depth: 9,
            ..Default::default()
        };
        let found = recursive_scan(dir.path(), &opts, &BTreeSet::new());
        assert_eq!(found.len(), 3, "got {found:?}");
    }

    #[test]
    fn recursive_scan_does_not_descend_into_a_guarded_destination() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::create_dir_all(dir.path().join("_Cleanup/2020-01-01")).unwrap();
        std::fs::write(dir.path().join("live.txt"), b"x").unwrap();
        std::fs::write(dir.path().join("_Cleanup/2020-01-01/archived.txt"), b"x").unwrap();

        let mut guards = BTreeSet::new();
        guards.insert(normalize(&dir.path().join("_Cleanup")));

        let opts = ScanOptions {
            max_depth: 9,
            ..Default::default()
        };
        let found = recursive_scan(dir.path(), &opts, &guards);

        assert_eq!(found.len(), 1, "archive must be pruned, got {found:?}");
        assert!(found[0].ends_with("live.txt"));
    }

    #[test]
    fn hidden_files_are_in_scope() {
        // `ignore` skips dotfiles by default; 1.5.0 did not, and the parity
        // corpus contains a .hiddenfile that the Python engine moves.
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join(".hiddenfile"), b"x").unwrap();

        let opts = ScanOptions {
            max_depth: 5,
            ..Default::default()
        };
        let found = recursive_scan(dir.path(), &opts, &BTreeSet::new());
        assert_eq!(
            found.len(),
            1,
            "hidden files must not be skipped: {found:?}"
        );
    }

    #[test]
    fn discovery_is_sorted_so_collision_suffixes_are_reproducible() {
        let dir = tempfile::tempdir().unwrap();
        for name in ["c.txt", "a.txt", "b.txt"] {
            std::fs::write(dir.path().join(name), b"x").unwrap();
        }
        let found = discover(dir.path(), &ScanOptions::default(), &BTreeSet::new()).unwrap();
        let names: Vec<_> = found
            .iter()
            .map(|p| p.file_name().unwrap().to_string_lossy().into_owned())
            .collect();
        assert_eq!(names, vec!["a.txt", "b.txt", "c.txt"]);
    }

    // -----------------------------------------------------------------------
    // Cancellation
    //
    // worker.py checked `_stop_event` inside its per-file loop, so 1.5.0 could
    // abandon a scan partway through a folder. Without an equivalent here, the
    // engine's finest shutdown granularity would be one whole rule — on a large
    // folder that reads to the user as a hang on quit.
    // -----------------------------------------------------------------------

    fn scan_fixture() -> (tempfile::TempDir, Config, Rule) {
        let dir = tempfile::tempdir().unwrap();
        for name in ["a.txt", "b.txt", "c.txt", "d.txt"] {
            std::fs::write(dir.path().join(name), b"payload").unwrap();
        }
        let mut rule = Rule::new(dir.path().to_string_lossy().into_owned());
        rule.age_days = 0;
        rule.pattern = "*.txt".into();
        rule.rule_logic = crate::config::RuleLogic::And;

        let mut config = Config::default();
        config.folders.push(rule.clone());
        (dir, config, rule)
    }

    #[test]
    fn an_already_cancelled_scan_touches_nothing() {
        let (dir, config, rule) = scan_fixture();
        let flag = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(true));
        let opts = ScanOptions {
            cancel: Some(flag),
            ..Default::default()
        };

        let mut report = ScanReport::default();
        scan_rule(&rule, &config, "run-cancel", &opts, &mut report);

        assert_eq!(report.processed, 0, "cancelled scan must process nothing");
        assert!(report.records.is_empty());
        // And the files are all still where they started.
        for name in ["a.txt", "b.txt", "c.txt", "d.txt"] {
            assert!(
                dir.path().join(name).is_file(),
                "{name} should be untouched"
            );
        }
    }

    #[test]
    fn an_uncancelled_scan_processes_every_file() {
        // The control for the test above: without the flag the same fixture
        // must do the work, so a passing cancellation test can't be vacuous.
        let (_dir, config, rule) = scan_fixture();
        let opts = ScanOptions {
            dry_run: true,
            ..Default::default()
        };

        let mut report = ScanReport::default();
        scan_rule(&rule, &config, "run-live", &opts, &mut report);

        assert_eq!(report.processed, 4, "got {:?}", report.records.len());
    }

    #[test]
    fn cancellation_defaults_to_off() {
        assert!(!ScanOptions::default().cancelled());
    }
}
