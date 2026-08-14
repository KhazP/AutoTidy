//! Reversing logged actions.
//!
//! Ported from `undo_manager.py`. Only `MOVED` and `COPIED` are reversible;
//! trashing and permanent deletion are not, and must report that plainly
//! rather than pretending to succeed.

use crate::history::{parse_timestamp, HistoryLog, HistoryRecord};
use chrono::{DateTime, Utc};
use std::collections::hash_map::Entry;
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::time::UNIX_EPOCH;

/// How far the copy's mtime may have drifted before we refuse to delete it.
/// 1.5.0 used `abs(stat.st_mtime - stored_mtime) > 2.0`; the slack absorbs
/// filesystems that round mtimes (FAT stores 2-second granularity).
const MTIME_TOLERANCE_SECS: f64 = 2.0;

#[derive(Debug, thiserror::Error)]
pub enum UndoError {
    #[error("missing original or destination path in the history record")]
    MissingPaths,
    #[error("original path {0} already exists; refusing to overwrite")]
    OriginalExists(String),
    #[error("{0} no longer exists; nothing to undo")]
    DestinationMissing(String),
    #[error(
        "'{name}' has changed since it was copied ({detail}); undo aborted to prevent data loss"
    )]
    IdentityMismatch { name: String, detail: String },
    #[error("undo is not supported for action: {0}")]
    Unsupported(String),
    #[error("i/o error: {0}")]
    Io(#[from] std::io::Error),
    #[error("history error: {0}")]
    History(#[from] crate::history::HistoryError),
}

/// One batch of actions sharing a `run_id`.
#[derive(Debug, Clone, serde::Serialize)]
pub struct RunSummary {
    pub run_id: String,
    /// Earliest timestamp in the run, RFC3339.
    pub start_time: String,
    pub action_count: usize,
}

#[derive(Debug, Default, serde::Serialize)]
pub struct BatchResult {
    pub run_id: String,
    pub success_count: usize,
    pub failure_count: usize,
    pub messages: Vec<String>,
}

/// All runs, most recent first.
pub fn list_runs(log: &HistoryLog) -> Result<Vec<RunSummary>, UndoError> {
    // Records with no `run_id` predate run tracking (77 of the 776 lines in a
    // real 1.5.0 file), and one with an unreadable timestamp can't be placed in
    // the ordering. Both are skipped, as `get_history_runs` did.
    let mut index: HashMap<String, usize> = HashMap::new();
    let mut runs: Vec<(DateTime<Utc>, String, usize)> = Vec::new();

    for record in log.read_all()? {
        if record.run_id.is_empty() {
            continue;
        }
        let Some(timestamp) = parse_timestamp(&record.timestamp) else {
            tracing::warn!(
                run_id = %record.run_id,
                timestamp = %record.timestamp,
                "skipping history record with an unreadable timestamp"
            );
            continue;
        };
        match index.entry(record.run_id.clone()) {
            Entry::Occupied(slot) => {
                let run = &mut runs[*slot.get()];
                if timestamp < run.0 {
                    run.0 = timestamp;
                }
                run.2 += 1;
            }
            Entry::Vacant(slot) => {
                slot.insert(runs.len());
                runs.push((timestamp, record.run_id.clone(), 1));
            }
        }
    }

    // Stable, so runs that somehow share a start time keep first-seen order.
    runs.sort_by(|left, right| right.0.cmp(&left.0));
    Ok(runs
        .into_iter()
        .map(|(start, run_id, action_count)| RunSummary {
            run_id,
            start_time: start.to_rfc3339(),
            action_count,
        })
        .collect())
}

/// Every record belonging to `run_id`, oldest first.
pub fn run_actions(log: &HistoryLog, run_id: &str) -> Result<Vec<HistoryRecord>, UndoError> {
    // Legacy records deserialise to an empty `run_id`; an empty query must not
    // sweep all of them into one undoable "run".
    if run_id.is_empty() {
        return Ok(Vec::new());
    }

    let mut matched: Vec<(DateTime<Utc>, HistoryRecord)> = log
        .read_all()?
        .into_iter()
        .filter(|record| record.run_id == run_id)
        .filter_map(|record| match parse_timestamp(&record.timestamp) {
            Some(timestamp) => Some((timestamp, record)),
            None => {
                tracing::warn!(
                    original_path = %record.original_path,
                    "skipping action with an invalid or missing timestamp"
                );
                None
            }
        })
        .collect();

    matched.sort_by(|left, right| left.0.cmp(&right.0));
    Ok(matched.into_iter().map(|(_, record)| record).collect())
}

/// Reverse a single action.
///
/// For `COPIED`, the copy's recorded `copy_size`/`copy_mtime` are verified
/// before deletion — if the user edited the copy, deleting it would destroy
/// work, so a mismatch aborts. Records predating that metadata carry neither
/// field and are deleted without the check, as 1.5.0 did.
pub fn undo_action(record: &HistoryRecord) -> Result<String, UndoError> {
    match record.action_taken.as_str() {
        "MOVED" => undo_move(record),
        "COPIED" => undo_copy(record),
        // Trashing is platform-specific to reverse and permanent deletion is
        // gone for good; say so rather than reporting a hollow success.
        other => Err(UndoError::Unsupported(other.to_string())),
    }
}

/// Put a moved file back where it came from.
fn undo_move(record: &HistoryRecord) -> Result<String, UndoError> {
    let original = non_empty(Some(record.original_path.as_str())).ok_or(UndoError::MissingPaths)?;
    let destination =
        non_empty(record.destination_path.as_deref()).ok_or(UndoError::MissingPaths)?;
    let original = Path::new(original);
    let destination = Path::new(destination);

    if !destination.exists() {
        return Err(UndoError::DestinationMissing(
            destination.display().to_string(),
        ));
    }
    // Something already lives at the original path. It may be an unrelated file
    // the user created since, so moving on top of it would destroy data we were
    // never asked to touch.
    if original.exists() {
        return Err(UndoError::OriginalExists(original.display().to_string()));
    }

    if let Some(parent) = original.parent() {
        if !parent.as_os_str().is_empty() && !parent.exists() {
            fs::create_dir_all(parent)?;
        }
    }

    rename_or_copy(destination, original)?;
    Ok(format!(
        "Successfully moved {} back to {}",
        destination.display(),
        original.display()
    ))
}

/// Delete a copy — but only once we're sure it is still the copy we made.
fn undo_copy(record: &HistoryRecord) -> Result<String, UndoError> {
    let destination =
        non_empty(record.destination_path.as_deref()).ok_or(UndoError::MissingPaths)?;
    let destination = Path::new(destination);

    let meta = match fs::metadata(destination) {
        Ok(meta) => meta,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => {
            return Err(UndoError::DestinationMissing(
                destination.display().to_string(),
            ))
        }
        Err(err) => return Err(err.into()),
    };

    let name = file_label(destination);
    if !meta.is_file() {
        return Err(UndoError::IdentityMismatch {
            name,
            detail: "it is no longer a regular file".to_string(),
        });
    }

    // Records written before copy verification existed carry neither field and
    // are deleted unverified, as 1.5.0 did.
    if record.copy_size.is_some() || record.copy_mtime.is_some() {
        if let Some(expected) = record.copy_size {
            if meta.len() != expected {
                return Err(UndoError::IdentityMismatch {
                    name,
                    detail: format!("expected {expected} bytes, found {}", meta.len()),
                });
            }
        }
        if let Some(expected) = record.copy_mtime {
            let Some(actual) = mtime_secs(&meta) else {
                return Err(UndoError::IdentityMismatch {
                    name,
                    detail: "its modification time could not be read".to_string(),
                });
            };
            if (actual - expected).abs() > MTIME_TOLERANCE_SECS {
                return Err(UndoError::IdentityMismatch {
                    name,
                    detail: "its modification time has changed".to_string(),
                });
            }
        }
    }

    fs::remove_file(destination)?;
    Ok(format!(
        "Successfully deleted copied file: {}",
        destination.display()
    ))
}

/// Undo a whole run in reverse chronological order, so later actions are
/// unwound before the earlier ones they may depend on.
pub fn undo_batch(log: &HistoryLog, run_id: &str) -> Result<BatchResult, UndoError> {
    let actions = run_actions(log, run_id)?;
    let mut result = BatchResult {
        run_id: run_id.to_string(),
        ..BatchResult::default()
    };

    if actions.is_empty() {
        result
            .messages
            .push(format!("No actions found for run_id: {run_id}"));
        return Ok(result);
    }

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
        // One failure must not strand the rest of the run half-undone.
        match undo_action(record) {
            Ok(message) => {
                result.success_count += 1;
                result.messages.push(format!("{prefix}{message}"));
            }
            Err(err) => {
                result.failure_count += 1;
                result.messages.push(format!("{prefix}Error: {err}"));
            }
        }
    }

    tracing::info!(
        run_id,
        successes = result.success_count,
        failures = result.failure_count,
        "undo batch complete"
    );
    Ok(result)
}

fn non_empty(value: Option<&str>) -> Option<&str> {
    value.filter(|text| !text.is_empty())
}

fn or_na(value: &str) -> &str {
    if value.is_empty() {
        "N/A"
    } else {
        value
    }
}

fn file_label(path: &Path) -> String {
    path.file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_else(|| path.display().to_string())
}

/// Python's `st_mtime`: seconds since the epoch, fractional, signed.
fn mtime_secs(meta: &fs::Metadata) -> Option<f64> {
    let modified = meta.modified().ok()?;
    Some(match modified.duration_since(UNIX_EPOCH) {
        Ok(since) => since.as_secs_f64(),
        Err(before) => -before.duration().as_secs_f64(),
    })
}

/// `shutil.move` semantics: rename when it can, copy-and-delete when the two
/// paths sit on different volumes (an archive folder on D: undone back to C:).
fn rename_or_copy(from: &Path, to: &Path) -> Result<(), UndoError> {
    match fs::rename(from, to) {
        Ok(()) => Ok(()),
        Err(err) if is_cross_device(&err) && from.is_file() => {
            fs::copy(from, to)?;
            if let Err(err) = fs::remove_file(from) {
                // The file is back where the user wants it; a leftover copy is
                // worth a warning, not a reported failure.
                tracing::warn!(
                    path = %from.display(),
                    %err,
                    "restored the file but could not remove the archived copy"
                );
            }
            Ok(())
        }
        Err(err) => Err(err.into()),
    }
}

fn is_cross_device(err: &std::io::Error) -> bool {
    // ErrorKind::CrossesDevices is newer than this crate's MSRV.
    match err.raw_os_error() {
        #[cfg(windows)]
        Some(17) => true, // ERROR_NOT_SAME_DEVICE
        #[cfg(unix)]
        Some(18) => true, // EXDEV
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::history::Status;
    use std::path::PathBuf;
    use tempfile::TempDir;

    fn record(
        action: &str,
        original: &Path,
        destination: Option<&Path>,
        run_id: &str,
        timestamp: &str,
    ) -> HistoryRecord {
        HistoryRecord {
            original_path: original.to_string_lossy().into_owned(),
            action_taken: action.into(),
            destination_path: destination.map(|p| p.to_string_lossy().into_owned()),
            monitored_folder: original
                .parent()
                .map(|p| p.to_string_lossy().into_owned())
                .unwrap_or_default(),
            rule_pattern: "*.*".into(),
            rule_age_days: 7,
            rule_use_regex: false,
            rule_action_config: "move".into(),
            status: Status::Success,
            details: String::new(),
            run_id: run_id.into(),
            severity: "INFO".into(),
            timestamp: timestamp.into(),
            copy_size: None,
            copy_mtime: None,
            extra: serde_json::Map::new(),
        }
    }

    fn write_log(dir: &TempDir, records: &[HistoryRecord]) -> HistoryLog {
        let log = HistoryLog::new(dir.path().join("autotidy_history.jsonl"));
        for record in records {
            log.append(record).unwrap();
        }
        log
    }

    /// Create `relative` (parents included) holding `contents`.
    fn seed(dir: &TempDir, relative: &str, contents: &str) -> PathBuf {
        let path = dir.path().join(relative);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, contents).unwrap();
        path
    }

    fn actual_mtime(path: &Path) -> f64 {
        mtime_secs(&fs::metadata(path).unwrap()).unwrap()
    }

    // ---- MOVED -----------------------------------------------------------

    #[test]
    fn moved_round_trips_the_file_back() {
        let dir = tempfile::tempdir().unwrap();
        let original = dir.path().join("src").join("report.txt");
        let destination = seed(&dir, "archive/2025-01-01/report.txt", "payload");
        fs::create_dir_all(original.parent().unwrap()).unwrap();

        let message = undo_action(&record(
            "MOVED",
            &original,
            Some(&destination),
            "run-1",
            "2025-01-01T00:00:00+00:00",
        ))
        .unwrap();

        assert!(message.contains("report.txt"));
        assert_eq!(fs::read_to_string(&original).unwrap(), "payload");
        assert!(!destination.exists());
    }

    #[test]
    fn moved_recreates_a_missing_original_parent() {
        let dir = tempfile::tempdir().unwrap();
        // The original folder is gone entirely — the user deleted it since.
        let original = dir.path().join("gone").join("deeper").join("report.txt");
        let destination = seed(&dir, "archive/report.txt", "payload");

        undo_action(&record(
            "MOVED",
            &original,
            Some(&destination),
            "run-1",
            "2025-01-01T00:00:00+00:00",
        ))
        .unwrap();

        assert_eq!(fs::read_to_string(&original).unwrap(), "payload");
    }

    #[test]
    fn moved_refuses_when_the_original_already_exists() {
        let dir = tempfile::tempdir().unwrap();
        let original = seed(&dir, "src/report.txt", "the newer file");
        let destination = seed(&dir, "archive/report.txt", "the archived file");

        let err = undo_action(&record(
            "MOVED",
            &original,
            Some(&destination),
            "run-1",
            "2025-01-01T00:00:00+00:00",
        ))
        .unwrap_err();

        assert!(matches!(err, UndoError::OriginalExists(_)), "{err:?}");
        // Neither file may be touched: refusing is the whole point.
        assert_eq!(fs::read_to_string(&original).unwrap(), "the newer file");
        assert_eq!(
            fs::read_to_string(&destination).unwrap(),
            "the archived file"
        );
    }

    #[test]
    fn moved_fails_when_the_destination_is_gone() {
        let dir = tempfile::tempdir().unwrap();
        let original = dir.path().join("src").join("report.txt");
        let destination = dir.path().join("archive").join("report.txt");

        let err = undo_action(&record(
            "MOVED",
            &original,
            Some(&destination),
            "run-1",
            "2025-01-01T00:00:00+00:00",
        ))
        .unwrap_err();

        assert!(matches!(err, UndoError::DestinationMissing(_)), "{err:?}");
        assert!(
            !original.exists(),
            "nothing may be conjured at the original"
        );
    }

    #[test]
    fn moved_without_usable_paths_errors() {
        let dir = tempfile::tempdir().unwrap();
        let original = dir.path().join("src").join("report.txt");

        let missing_dest = record("MOVED", &original, None, "run-1", "2025-01-01T00:00:00Z");
        assert!(matches!(
            undo_action(&missing_dest).unwrap_err(),
            UndoError::MissingPaths
        ));

        let mut blank_dest = missing_dest.clone();
        blank_dest.destination_path = Some(String::new());
        assert!(matches!(
            undo_action(&blank_dest).unwrap_err(),
            UndoError::MissingPaths
        ));

        let mut blank_original = blank_dest.clone();
        blank_original.original_path = String::new();
        blank_original.destination_path = Some("C:\\archive\\report.txt".into());
        assert!(matches!(
            undo_action(&blank_original).unwrap_err(),
            UndoError::MissingPaths
        ));
    }

    // ---- COPIED ----------------------------------------------------------

    #[test]
    fn copied_without_identity_metadata_deletes() {
        let dir = tempfile::tempdir().unwrap();
        let original = seed(&dir, "src/report.txt", "payload");
        let destination = seed(&dir, "archive/report.txt", "payload");

        undo_action(&record(
            "COPIED",
            &original,
            Some(&destination),
            "run-1",
            "2025-01-01T00:00:00+00:00",
        ))
        .unwrap();

        assert!(!destination.exists());
        assert!(original.exists(), "the source of the copy must survive");
    }

    #[test]
    fn copied_with_matching_identity_deletes() {
        let dir = tempfile::tempdir().unwrap();
        let original = seed(&dir, "src/report.txt", "payload");
        let destination = seed(&dir, "archive/report.txt", "payload");

        let mut rec = record(
            "COPIED",
            &original,
            Some(&destination),
            "run-1",
            "2025-01-01T00:00:00+00:00",
        );
        rec.copy_size = Some(fs::metadata(&destination).unwrap().len());
        rec.copy_mtime = Some(actual_mtime(&destination));

        undo_action(&rec).unwrap();
        assert!(!destination.exists());
    }

    #[test]
    fn copied_with_a_changed_size_refuses_and_leaves_the_file() {
        let dir = tempfile::tempdir().unwrap();
        let original = seed(&dir, "src/report.txt", "payload");
        // The user has since edited the copy — it is now longer than we logged.
        let destination = seed(&dir, "archive/report.txt", "payload plus real work");

        let mut rec = record(
            "COPIED",
            &original,
            Some(&destination),
            "run-1",
            "2025-01-01T00:00:00+00:00",
        );
        rec.copy_size = Some("payload".len() as u64);

        let err = undo_action(&rec).unwrap_err();
        assert!(matches!(err, UndoError::IdentityMismatch { .. }), "{err:?}");
        assert_eq!(
            fs::read_to_string(&destination).unwrap(),
            "payload plus real work",
            "the user's edited copy must survive a refused undo"
        );
    }

    #[test]
    fn copied_with_a_drifted_mtime_refuses_and_leaves_the_file() {
        let dir = tempfile::tempdir().unwrap();
        let original = seed(&dir, "src/report.txt", "payload");
        let destination = seed(&dir, "archive/report.txt", "payload");

        let mut rec = record(
            "COPIED",
            &original,
            Some(&destination),
            "run-1",
            "2025-01-01T00:00:00+00:00",
        );
        // Same size, but the file was touched ten seconds after we copied it.
        rec.copy_size = Some(fs::metadata(&destination).unwrap().len());
        rec.copy_mtime = Some(actual_mtime(&destination) - 10.0);

        let err = undo_action(&rec).unwrap_err();
        assert!(matches!(err, UndoError::IdentityMismatch { .. }), "{err:?}");
        assert!(destination.exists(), "a refused undo must not delete");
        assert_eq!(fs::read_to_string(&destination).unwrap(), "payload");
    }

    #[test]
    fn copied_within_the_mtime_tolerance_still_deletes() {
        let dir = tempfile::tempdir().unwrap();
        let original = seed(&dir, "src/report.txt", "payload");
        let destination = seed(&dir, "archive/report.txt", "payload");

        let mut rec = record(
            "COPIED",
            &original,
            Some(&destination),
            "run-1",
            "2025-01-01T00:00:00+00:00",
        );
        // Coarse-granularity filesystems round mtimes; 1.5 s must not block undo.
        rec.copy_mtime = Some(actual_mtime(&destination) - 1.5);

        undo_action(&rec).unwrap();
        assert!(!destination.exists());
    }

    #[test]
    fn copied_missing_destination_errors() {
        let dir = tempfile::tempdir().unwrap();
        let original = seed(&dir, "src/report.txt", "payload");
        let destination = dir.path().join("archive").join("report.txt");

        let err = undo_action(&record(
            "COPIED",
            &original,
            Some(&destination),
            "run-1",
            "2025-01-01T00:00:00+00:00",
        ))
        .unwrap_err();
        assert!(matches!(err, UndoError::DestinationMissing(_)), "{err:?}");
    }

    #[test]
    fn copied_refuses_when_the_destination_is_a_directory() {
        let dir = tempfile::tempdir().unwrap();
        let original = seed(&dir, "src/report.txt", "payload");
        let destination = dir.path().join("archive");
        fs::create_dir_all(destination.join("keep-me")).unwrap();

        let err = undo_action(&record(
            "COPIED",
            &original,
            Some(&destination),
            "run-1",
            "2025-01-01T00:00:00+00:00",
        ))
        .unwrap_err();

        assert!(matches!(err, UndoError::IdentityMismatch { .. }), "{err:?}");
        assert!(destination.join("keep-me").exists());
    }

    // ---- unsupported -----------------------------------------------------

    #[test]
    fn unsupported_actions_error() {
        let dir = tempfile::tempdir().unwrap();
        let original = seed(&dir, "src/report.txt", "payload");
        for action in [
            "DELETED_PERMANENTLY",
            "TRASHED",
            "SIMULATED_MOVE",
            "UNDO_MOVE",
            "MOVE_ERROR_BOUNDARY",
        ] {
            let err = undo_action(&record(
                action,
                &original,
                Some(&original),
                "run-1",
                "2025-01-01T00:00:00+00:00",
            ))
            .unwrap_err();
            assert!(
                matches!(&err, UndoError::Unsupported(name) if name == action),
                "{action}: {err:?}"
            );
        }
        assert!(original.exists(), "an unsupported undo must touch nothing");
    }

    // ---- run listing -----------------------------------------------------

    #[test]
    fn list_runs_groups_counts_and_sorts_newest_first() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("f.txt");
        let log = write_log(
            &dir,
            &[
                // Deliberately interleaved and out of order on disk.
                record(
                    "MOVED",
                    &file,
                    Some(&file),
                    "old",
                    "2025-01-01T10:00:00+00:00",
                ),
                record(
                    "MOVED",
                    &file,
                    Some(&file),
                    "new",
                    "2025-03-01T09:00:00+00:00",
                ),
                record(
                    "MOVED",
                    &file,
                    Some(&file),
                    "old",
                    "2025-01-01T09:00:00+00:00",
                ),
                record(
                    "MOVED",
                    &file,
                    Some(&file),
                    "mid",
                    "2025-02-01T12:00:00+00:00",
                ),
                record(
                    "MOVED",
                    &file,
                    Some(&file),
                    "old",
                    "2025-01-01T11:00:00+00:00",
                ),
            ],
        );

        let runs = list_runs(&log).unwrap();
        let ids: Vec<&str> = runs.iter().map(|r| r.run_id.as_str()).collect();
        assert_eq!(ids, vec!["new", "mid", "old"]);
        assert_eq!(runs[2].action_count, 3);
        assert_eq!(runs[0].action_count, 1);
        // start_time is the earliest stamp in the run, not the first one seen.
        assert_eq!(
            parse_timestamp(&runs[2].start_time).unwrap(),
            parse_timestamp("2025-01-01T09:00:00+00:00").unwrap()
        );
    }

    #[test]
    fn list_runs_skips_records_without_a_run_id_or_timestamp() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("f.txt");
        let log = write_log(
            &dir,
            &[
                // Legacy 1.5.0 line: no run_id at all.
                record("MOVED", &file, Some(&file), "", "2025-01-01T10:00:00+00:00"),
                record("MOVED", &file, Some(&file), "broken", "not a timestamp"),
                record("MOVED", &file, Some(&file), "broken", ""),
                record(
                    "MOVED",
                    &file,
                    Some(&file),
                    "good",
                    "2025-01-02T10:00:00+00:00",
                ),
            ],
        );

        let runs = list_runs(&log).unwrap();
        assert_eq!(runs.len(), 1);
        assert_eq!(runs[0].run_id, "good");
        assert_eq!(runs[0].action_count, 1);
    }

    #[test]
    fn list_runs_on_an_absent_history_is_empty() {
        let dir = tempfile::tempdir().unwrap();
        let log = HistoryLog::new(dir.path().join("nope.jsonl"));
        assert!(list_runs(&log).unwrap().is_empty());
    }

    #[test]
    fn run_actions_are_oldest_first_and_scoped_to_the_run() {
        let dir = tempfile::tempdir().unwrap();
        let late = dir.path().join("late.txt");
        let early = dir.path().join("early.txt");
        let other = dir.path().join("other.txt");
        let log = write_log(
            &dir,
            &[
                record(
                    "MOVED",
                    &late,
                    Some(&late),
                    "run-1",
                    "2025-01-01T12:00:00+00:00",
                ),
                record(
                    "MOVED",
                    &other,
                    Some(&other),
                    "run-2",
                    "2025-01-01T11:00:00+00:00",
                ),
                record(
                    "MOVED",
                    &early,
                    Some(&early),
                    "run-1",
                    "2025-01-01T10:00:00+00:00",
                ),
            ],
        );

        let actions = run_actions(&log, "run-1").unwrap();
        assert_eq!(actions.len(), 2);
        assert!(actions[0].original_path.ends_with("early.txt"));
        assert!(actions[1].original_path.ends_with("late.txt"));
    }

    #[test]
    fn run_actions_with_an_empty_run_id_matches_nothing() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("f.txt");
        let log = write_log(
            &dir,
            &[
                // Legacy records deserialise with run_id == "".
                record("MOVED", &file, Some(&file), "", "2025-01-01T10:00:00+00:00"),
                record("MOVED", &file, Some(&file), "", "2025-01-01T11:00:00+00:00"),
            ],
        );
        assert!(run_actions(&log, "").unwrap().is_empty());
    }

    // ---- batches ---------------------------------------------------------

    #[test]
    fn undo_batch_unwinds_in_reverse_chronological_order() {
        let dir = tempfile::tempdir().unwrap();
        // A file moved twice in one run: home -> stage -> final. Only the
        // reverse order can restore it; forward order strands it at stage.
        let home = dir.path().join("home").join("f.txt");
        let stage = dir.path().join("stage").join("f.txt");
        let last = seed(&dir, "final/f.txt", "payload");

        let log = write_log(
            &dir,
            &[
                record(
                    "MOVED",
                    &home,
                    Some(&stage),
                    "run-1",
                    "2025-01-01T10:00:00+00:00",
                ),
                record(
                    "MOVED",
                    &stage,
                    Some(&last),
                    "run-1",
                    "2025-01-01T10:00:05+00:00",
                ),
            ],
        );

        let result = undo_batch(&log, "run-1").unwrap();

        assert_eq!(result.run_id, "run-1");
        assert_eq!(result.success_count, 2, "{:#?}", result.messages);
        assert_eq!(result.failure_count, 0);
        assert_eq!(fs::read_to_string(&home).unwrap(), "payload");
        assert!(!stage.exists());
        assert!(!last.exists());
        // The later action is reported first.
        assert!(
            result.messages[0].contains("10:00:05"),
            "{:#?}",
            result.messages
        );
        assert!(result.messages[1].contains("10:00:00"));
    }

    #[test]
    fn undo_batch_keeps_going_after_a_failure() {
        let dir = tempfile::tempdir().unwrap();
        let good_original = dir.path().join("src").join("good.txt");
        let good_destination = seed(&dir, "archive/good.txt", "good payload");
        // This one cannot be undone: its destination is long gone.
        let lost_original = dir.path().join("src").join("lost.txt");
        let lost_destination = dir.path().join("archive").join("lost.txt");

        let log = write_log(
            &dir,
            &[
                record(
                    "MOVED",
                    &good_original,
                    Some(&good_destination),
                    "run-1",
                    "2025-01-01T10:00:00+00:00",
                ),
                record(
                    "MOVED",
                    &lost_original,
                    Some(&lost_destination),
                    "run-1",
                    "2025-01-01T10:00:05+00:00",
                ),
            ],
        );

        let result = undo_batch(&log, "run-1").unwrap();

        assert_eq!(result.failure_count, 1);
        assert_eq!(
            result.success_count, 1,
            "a failure must not abort the batch: {:#?}",
            result.messages
        );
        assert_eq!(result.messages.len(), 2);
        // Failure first (it is the later action), then the recovered one.
        assert!(
            result.messages[0].contains("Error:"),
            "{:#?}",
            result.messages
        );
        assert!(result.messages[1].contains("Successfully moved"));
        assert_eq!(fs::read_to_string(&good_original).unwrap(), "good payload");
    }

    #[test]
    fn undo_batch_for_an_unknown_run_reports_no_actions() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("f.txt");
        let log = write_log(
            &dir,
            &[record(
                "MOVED",
                &file,
                Some(&file),
                "run-1",
                "2025-01-01T10:00:00+00:00",
            )],
        );

        let result = undo_batch(&log, "run-404").unwrap();
        assert_eq!(result.run_id, "run-404");
        assert_eq!(result.success_count, 0);
        assert_eq!(result.failure_count, 0);
        assert_eq!(
            result.messages,
            vec!["No actions found for run_id: run-404"]
        );
    }

    #[test]
    fn batch_messages_carry_the_paths_and_action_type() {
        let dir = tempfile::tempdir().unwrap();
        let original = dir.path().join("src").join("report.txt");
        let destination = seed(&dir, "archive/report.txt", "payload");
        let log = write_log(
            &dir,
            &[record(
                "MOVED",
                &original,
                Some(&destination),
                "run-1",
                "2025-01-01T10:00:00+00:00",
            )],
        );

        let result = undo_batch(&log, "run-1").unwrap();
        let message = &result.messages[0];
        assert!(message.contains("2025-01-01T10:00:00+00:00"), "{message}");
        assert!(message.contains("report.txt"), "{message}");
        assert!(message.contains("Type: MOVED"), "{message}");
    }
}
