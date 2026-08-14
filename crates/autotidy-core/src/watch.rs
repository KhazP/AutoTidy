//! Real-time filesystem watching.
//!
//! No 1.5.0 counterpart — the old engine only ever slept on a timer. This is
//! one of the two capabilities the rewrite exists to enable.
//!
//! Debouncing is mandatory, not a nicety: a single file copy emits a burst of
//! create/modify/close events, and an application saving a document often
//! writes to a temp file and renames over the target. Reacting per-event would
//! scan several times per change and, worse, could act on a file that is still
//! being written.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::sync::mpsc;
use std::time::Duration;

use notify::RecursiveMode;
use notify_debouncer_full::{new_debouncer, DebounceEventResult};

/// How long the filesystem must be quiet before a batch is delivered.
pub const DEFAULT_DEBOUNCE: Duration = Duration::from_secs(2);

/// Floor on the debounce window.
///
/// `notify-debouncer-full` derives its poll tick as `timeout / 4`; a zero (or
/// near-zero) timeout would turn that background thread into a spin loop, so a
/// nonsensical value is clamped rather than honoured.
const MIN_DEBOUNCE: Duration = Duration::from_millis(20);

#[derive(Debug, thiserror::Error)]
pub enum WatchError {
    #[error("could not watch {path}: {source}")]
    Watch {
        path: PathBuf,
        #[source]
        source: Box<notify::Error>,
    },
    #[error("watcher backend failed: {0}")]
    Backend(Box<notify::Error>),
}

/// A batch of paths that changed, already debounced and de-duplicated.
#[derive(Debug, Clone)]
pub struct ChangeBatch {
    pub paths: Vec<PathBuf>,
}

/// Owns the watcher; dropping it stops delivery.
pub struct WatchHandle {
    // The concrete debouncer type is an implementation detail and must not leak
    // into the public API — it changes shape between notify releases.
    pub(crate) _inner: Box<dyn std::any::Any + Send>,
}

/// Watch `paths`, delivering debounced batches to `on_change`.
///
/// `recursive` mirrors the rule's own depth setting: a rule that only scans its
/// top level should not be woken by a change buried ten directories down.
///
/// Paths that cannot be watched (deleted, permission denied) are reported as an
/// error rather than skipped silently — a watch that quietly covers only half
/// the requested folders looks identical to "nothing changed".
pub fn watch<F>(
    paths: &[PathBuf],
    recursive: bool,
    debounce: Duration,
    mut on_change: F,
) -> Result<WatchHandle, WatchError>
where
    F: FnMut(ChangeBatch) + Send + 'static,
{
    let debounce = debounce.max(MIN_DEBOUNCE);

    // The debouncer's own worker thread owns the sending half, so when the
    // `Debouncer` inside `WatchHandle` is dropped that thread exits, the sender
    // goes with it, and the drain loop below ends on its own. No separate stop
    // flag is needed to tear the pair down.
    let (tx, rx) = mpsc::channel::<DebounceEventResult>();
    let mut debouncer = new_debouncer(debounce, None, tx)
        .map_err(|source| WatchError::Backend(Box::new(source)))?;

    let mode = if recursive {
        RecursiveMode::Recursive
    } else {
        RecursiveMode::NonRecursive
    };

    for path in paths {
        debouncer
            .watch(path, mode)
            .map_err(|source| WatchError::Watch {
                path: path.clone(),
                source: Box::new(source),
            })?;
    }

    std::thread::spawn(move || {
        for result in rx {
            match result {
                Ok(events) => {
                    // A batch routinely names the same file several times (a
                    // copy is create + modify + close), and callers treat the
                    // batch as a set of "look at these again" hints. A BTreeSet
                    // both de-duplicates and gives a stable order, which keeps
                    // logs and tests reproducible.
                    let mut paths = BTreeSet::new();
                    let mut needs_rescan = false;
                    for event in events {
                        needs_rescan |= event.event.need_rescan();
                        paths.extend(event.event.paths.iter().cloned());
                    }

                    if needs_rescan {
                        // The backend dropped events and cannot say which; it
                        // carries no paths, so there is nothing to hand the
                        // caller beyond a warning.
                        tracing::warn!("filesystem watcher requested a rescan; events were lost");
                    }
                    if paths.is_empty() {
                        continue;
                    }
                    on_change(ChangeBatch {
                        paths: paths.into_iter().collect(),
                    });
                }
                Err(errors) => {
                    for error in errors {
                        tracing::warn!(%error, "filesystem watcher error");
                    }
                }
            }
        }
    });

    Ok(WatchHandle {
        _inner: Box::new(debouncer),
    })
}

/// True when a changed path is one the engine should react to.
///
/// Filters the feedback loop: the engine's own writes into the archive folder
/// generate events, and reacting to them would re-trigger a scan on every move,
/// forever. Mirrors the pruning `scan::guard_paths` does for the walk.
pub fn is_relevant(path: &Path, guards: &[PathBuf]) -> bool {
    let normalized = crate::config::normalize(path);
    !guards
        .iter()
        .any(|g| normalized == *g || normalized.starts_with(g))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::normalize;
    use std::fs;
    use std::sync::mpsc;

    /// Short enough to keep the suite quick, long enough that a burst of writes
    /// lands inside one window on a loaded CI box.
    const TEST_DEBOUNCE: Duration = Duration::from_millis(150);
    /// Generous ceiling for "an event should arrive"; never actually waited out
    /// on a passing run.
    const ARRIVAL: Duration = Duration::from_secs(5);
    /// How long "nothing should arrive" is given to be wrong.
    const QUIET: Duration = Duration::from_millis(700);

    fn channel_watch(
        paths: &[PathBuf],
        recursive: bool,
    ) -> (WatchHandle, mpsc::Receiver<ChangeBatch>) {
        channel_watch_with(paths, recursive, TEST_DEBOUNCE)
    }

    fn channel_watch_with(
        paths: &[PathBuf],
        recursive: bool,
        debounce: Duration,
    ) -> (WatchHandle, mpsc::Receiver<ChangeBatch>) {
        let (tx, rx) = mpsc::channel();
        let handle = watch(paths, recursive, debounce, move |batch| {
            let _ = tx.send(batch);
        })
        .expect("watch should start");
        (handle, rx)
    }

    fn names(batch: &ChangeBatch) -> Vec<String> {
        batch
            .paths
            .iter()
            .filter_map(|p| p.file_name())
            .map(|n| n.to_string_lossy().into_owned())
            .collect()
    }

    #[test]
    fn a_created_file_is_delivered_as_a_batch() {
        let dir = tempfile::tempdir().unwrap();
        let (_handle, rx) = channel_watch(&[dir.path().to_path_buf()], false);

        fs::write(dir.path().join("arrived.txt"), b"x").unwrap();

        let batch = rx.recv_timeout(ARRIVAL).expect("a batch should arrive");
        assert!(
            names(&batch).iter().any(|n| n == "arrived.txt"),
            "got {:?}",
            batch.paths
        );
    }

    #[test]
    fn rapid_writes_collapse_instead_of_firing_once_per_event() {
        // Longer than the other tests on purpose: the debouncer polls every
        // `debounce / 4`, and the wider that tick, the less the result depends
        // on exactly where the burst falls within it.
        const BURST_DEBOUNCE: Duration = Duration::from_millis(300);
        const BURST: usize = 5;

        let dir = tempfile::tempdir().unwrap();
        let (_handle, rx) = channel_watch_with(&[dir.path().to_path_buf()], false, BURST_DEBOUNCE);

        // Five files written back to back — measured at well under 2ms for the
        // whole loop. Undebounced this is at least five callbacks, and in
        // practice more, since each write is a create plus a modify.
        for index in 0..BURST {
            fs::write(dir.path().join(format!("burst-{index}.txt")), b"x").unwrap();
        }

        // Collect until the whole burst has been accounted for.
        let mut batches: Vec<Vec<String>> = Vec::new();
        let mut seen: BTreeSet<String> = BTreeSet::new();
        while seen.len() < BURST {
            let batch = rx
                .recv_timeout(ARRIVAL)
                .unwrap_or_else(|_| panic!("only saw {seen:?} of the burst"));

            // Each path appears once per batch, however many raw events named it.
            let mut unique = batch.paths.clone();
            unique.sort();
            unique.dedup();
            assert_eq!(
                unique.len(),
                batch.paths.len(),
                "paths must be deduplicated"
            );

            let observed = names(&batch);
            seen.extend(observed.iter().cloned());
            batches.push(observed);
        }

        // The burst spans about a millisecond against a 75ms tick, so it can
        // straddle at most one tick boundary. Two is the honest upper bound;
        // five — one callback per file — is the failure this test exists to
        // catch.
        assert!(
            batches.len() <= 2,
            "expected the burst to coalesce, got {} batches: {batches:?}",
            batches.len()
        );
        assert!(
            batches.iter().any(|batch| batch.len() > 1),
            "no batch carried more than one file, so nothing was actually debounced: {batches:?}"
        );
    }

    #[test]
    fn a_path_under_a_guard_is_not_relevant() {
        let monitored = normalize(Path::new("C:/monitored"));
        let guards = vec![normalize(&monitored.join("_Cleanup"))];

        // The engine's own writes into the archive: ignored.
        assert!(!is_relevant(
            &monitored.join("_Cleanup").join("2026-08-14").join("a.txt"),
            &guards
        ));
        assert!(!is_relevant(&monitored.join("_Cleanup"), &guards));
        // A real change in the monitored folder: acted on.
        assert!(is_relevant(&monitored.join("a.txt"), &guards));
        // A sibling that merely shares a name prefix is not inside the guard.
        assert!(is_relevant(&monitored.join("_CleanupNotes.txt"), &guards));
        // No guards at all means nothing is filtered.
        assert!(is_relevant(&monitored.join("_Cleanup").join("a.txt"), &[]));
    }

    #[test]
    fn watching_a_missing_path_is_an_error_not_a_silent_skip() {
        let dir = tempfile::tempdir().unwrap();
        let missing = dir.path().join("does-not-exist");

        match watch(std::slice::from_ref(&missing), false, TEST_DEBOUNCE, |_| {}) {
            Err(WatchError::Watch { path, .. }) => assert_eq!(path, missing),
            Err(other) => panic!("expected a per-path error, got {other:?}"),
            Ok(_) => panic!("a path that cannot be watched must surface as an error"),
        }
    }

    #[test]
    fn a_good_path_alongside_a_bad_one_still_fails_the_whole_call() {
        // Half a watch looks exactly like "nothing changed", so partial success
        // is not an option.
        let dir = tempfile::tempdir().unwrap();
        let paths = vec![dir.path().to_path_buf(), dir.path().join("missing")];
        assert!(matches!(
            watch(&paths, false, TEST_DEBOUNCE, |_| {}),
            Err(WatchError::Watch { .. })
        ));
    }

    #[test]
    fn dropping_the_handle_stops_delivery() {
        let dir = tempfile::tempdir().unwrap();
        let (handle, rx) = channel_watch(&[dir.path().to_path_buf()], false);
        drop(handle);

        fs::write(dir.path().join("after-drop.txt"), b"x").unwrap();

        assert!(
            rx.recv_timeout(QUIET).is_err(),
            "a dropped WatchHandle must stop delivering"
        );
    }
}
