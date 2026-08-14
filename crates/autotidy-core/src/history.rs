//! Append-only JSONL action history.
//!
//! The on-disk schema is fixed by compatibility: a real 1.5.0 history file
//! (776 entries observed) carries exactly these keys —
//! `original_path`, `action_taken`, `destination_path`, `monitored_folder`,
//! `rule_pattern`, `rule_age_days`, `rule_use_regex`, `rule_action_config`,
//! `status`, `details`, `run_id`, `severity`, `timestamp`.
//! Field names and value spellings must not drift: `undo.rs` reads them back,
//! and users have years of history that has to keep working.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, ErrorKind, Write};
use std::path::{Path, PathBuf};

pub const MAX_HISTORY_SIZE_BYTES: u64 = 10 * 1024 * 1024;
pub const MAX_HISTORY_BACKUPS: u32 = 3;
pub const DEFAULT_MAX_AGE_DAYS: i64 = 90;

#[derive(Debug, thiserror::Error)]
pub enum HistoryError {
    #[error("i/o error on {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("could not serialise history record: {0}")]
    Serialize(#[from] serde_json::Error),
}

/// Outcome of a single logged action. Serialised as the exact uppercase
/// strings 1.5.0 wrote.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Status {
    #[serde(rename = "SUCCESS")]
    Success,
    #[serde(rename = "FAILURE")]
    Failure,
    #[serde(rename = "SKIPPED")]
    Skipped,
}

impl Status {
    /// Mirrors the severity derivation in `HistoryManager.log_action`.
    pub fn severity(self) -> &'static str {
        match self {
            Status::Success => "INFO",
            Status::Failure => "ERROR",
            Status::Skipped => "WARNING",
        }
    }
}

/// One line of the history file.
///
/// `action_taken` is a free-form string rather than an enum on purpose: 1.5.0
/// wrote a long tail of values (`MOVED`, `COPIED`, `SIMULATED_MOVE`,
/// `UNDO_MOVE`, `SKIPPED`, plus error variants like `MOVE_ERROR_BOUNDARY`),
/// and an enum would reject history written by a version we don't know about.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HistoryRecord {
    pub original_path: String,
    pub action_taken: String,
    #[serde(default)]
    pub destination_path: Option<String>,
    /// Defaulted, not required: the `UNDO_MOVE` lines 1.5.0's undo UI wrote
    /// carry only path/status/details/timestamp, and without this two entries
    /// in a real 776-line history fail to parse and vanish from the log view.
    #[serde(default)]
    pub monitored_folder: String,
    #[serde(default)]
    pub rule_pattern: String,
    #[serde(default)]
    pub rule_age_days: i64,
    #[serde(default)]
    pub rule_use_regex: bool,
    #[serde(default)]
    pub rule_action_config: String,
    pub status: Status,
    #[serde(default)]
    pub details: String,
    #[serde(default)]
    pub run_id: String,
    #[serde(default)]
    pub severity: String,
    /// RFC3339 UTC, matching Python's `datetime.now(timezone.utc).isoformat()`.
    #[serde(default)]
    pub timestamp: String,

    /// Identity metadata recorded for `COPIED` so undo can verify the file
    /// hasn't changed before deleting it. Absent in older history.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub copy_size: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub copy_mtime: Option<f64>,

    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

impl HistoryRecord {
    /// Stamp `timestamp` and derive `severity` if unset — the two fields
    /// `log_action` filled in on the way to disk.
    pub fn finalize(mut self) -> Self {
        if self.timestamp.is_empty() {
            self.timestamp = chrono::Utc::now().to_rfc3339();
        }
        if self.severity.is_empty() {
            self.severity = self.status.severity().to_string();
        }
        self
    }
}

/// The history file plus its rotation policy.
#[derive(Debug, Clone)]
pub struct HistoryLog {
    path: PathBuf,
}

impl HistoryLog {
    pub fn new(path: impl Into<PathBuf>) -> Self {
        Self { path: path.into() }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Append one record, rotating first if the file has grown past
    /// `MAX_HISTORY_SIZE_BYTES`.
    pub fn append(&self, record: &HistoryRecord) -> Result<(), HistoryError> {
        // A rotation that fails must not cost us the log line: 1.5.0 warned and
        // carried on appending to the oversized file, and losing the record is
        // strictly worse than an over-long history.
        if let Err(err) = self.rotate_if_needed() {
            tracing::warn!(
                path = %self.path.display(),
                %err,
                "could not rotate history log; appending anyway"
            );
        }

        if let Some(parent) = self.path.parent() {
            if !parent.as_os_str().is_empty() {
                fs::create_dir_all(parent).map_err(|source| HistoryError::Io {
                    path: parent.to_path_buf(),
                    source,
                })?;
            }
        }

        let mut line = serde_json::to_string(record)?;
        line.push('\n');

        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)
            .map_err(|source| self.io_err(source))?;
        file.write_all(line.as_bytes())
            .map_err(|source| self.io_err(source))?;
        Ok(())
    }

    /// Every parseable record, oldest first. Unparseable lines are skipped with
    /// a warning rather than aborting the read — a single corrupt line must not
    /// cost the user their whole history.
    pub fn read_all(&self) -> Result<Vec<HistoryRecord>, HistoryError> {
        let file = match File::open(&self.path) {
            Ok(file) => file,
            Err(source) if source.kind() == ErrorKind::NotFound => return Ok(Vec::new()),
            Err(source) => return Err(self.io_err(source)),
        };

        let mut records = Vec::new();
        for (index, line) in BufReader::new(file).lines().enumerate() {
            let line = match line {
                Ok(line) => line,
                // A line of invalid UTF-8 is corruption, not a read failure:
                // skip it the same way we skip malformed JSON.
                Err(source) if source.kind() == ErrorKind::InvalidData => {
                    tracing::warn!(
                        path = %self.path.display(),
                        line = index + 1,
                        "skipping history line that is not valid UTF-8"
                    );
                    continue;
                }
                Err(source) => return Err(self.io_err(source)),
            };

            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            match serde_json::from_str::<HistoryRecord>(trimmed) {
                Ok(record) => records.push(record),
                Err(err) => tracing::warn!(
                    path = %self.path.display(),
                    line = index + 1,
                    %err,
                    "skipping unparseable history line"
                ),
            }
        }
        Ok(records)
    }

    /// Drop records older than `max_age_days`. Lines that fail to parse are
    /// kept, matching `prune_old_entries`' conservative behaviour.
    ///
    /// The rewrite goes through a sibling temp file and a rename. 1.5.0
    /// truncated the live file and wrote the survivors back into it, so a crash
    /// mid-write left the user with a half-empty history and no way back.
    pub fn prune(&self, max_age_days: i64) -> Result<(), HistoryError> {
        let raw = match fs::read(&self.path) {
            Ok(raw) => raw,
            Err(source) if source.kind() == ErrorKind::NotFound => return Ok(()),
            Err(source) => return Err(self.io_err(source)),
        };

        // An absurd `max_age_days` that can't be expressed as a duration means
        // we have no idea what to drop, so we drop nothing.
        let Some(cutoff) = chrono::TimeDelta::try_days(max_age_days).map(|age| Utc::now() - age)
        else {
            tracing::warn!(
                max_age_days,
                "ignoring out-of-range history retention window"
            );
            return Ok(());
        };

        // Operating on raw bytes keeps lines we can't even decode intact.
        let mut kept: Vec<&[u8]> = Vec::new();
        for line in raw.split(|byte| *byte == b'\n') {
            let line = trim_ascii_whitespace(line);
            if line.is_empty() {
                continue;
            }
            if keep_after_prune(line, cutoff) {
                kept.push(line);
            }
        }

        let dir = match self.path.parent() {
            Some(parent) if !parent.as_os_str().is_empty() => parent,
            _ => Path::new("."),
        };
        let mut tmp = tempfile::NamedTempFile::new_in(dir).map_err(|source| HistoryError::Io {
            path: dir.to_path_buf(),
            source,
        })?;
        // Temp files are created private; the history file may not have been.
        if let Ok(meta) = fs::metadata(&self.path) {
            let _ = tmp.as_file().set_permissions(meta.permissions());
        }
        for line in kept {
            tmp.write_all(line).map_err(|source| self.io_err(source))?;
            tmp.write_all(b"\n").map_err(|source| self.io_err(source))?;
        }
        tmp.as_file()
            .sync_all()
            .map_err(|source| self.io_err(source))?;
        tmp.persist(&self.path)
            .map_err(|err| self.io_err(err.error))?;
        Ok(())
    }

    /// `.3` is discarded, `.2`→`.3`, `.1`→`.2`, current→`.1`.
    pub fn rotate_if_needed(&self) -> Result<(), HistoryError> {
        let meta = match fs::metadata(&self.path) {
            Ok(meta) => meta,
            Err(source) if source.kind() == ErrorKind::NotFound => return Ok(()),
            Err(source) => return Err(self.io_err(source)),
        };
        if meta.len() < MAX_HISTORY_SIZE_BYTES {
            return Ok(());
        }

        for index in (1..=MAX_HISTORY_BACKUPS).rev() {
            let backup = self.backup_path(index);
            let older = if index > 1 {
                self.backup_path(index - 1)
            } else {
                self.path.clone()
            };
            if backup.exists() {
                fs::remove_file(&backup).map_err(|source| HistoryError::Io {
                    path: backup.clone(),
                    source,
                })?;
            }
            if older.exists() {
                fs::rename(&older, &backup).map_err(|source| HistoryError::Io {
                    path: older.clone(),
                    source,
                })?;
            }
        }
        Ok(())
    }

    /// `autotidy_history.jsonl.2` — the suffix goes on the whole name, matching
    /// the `f"{path}.{i}"` the Python rotation used.
    fn backup_path(&self, index: u32) -> PathBuf {
        let mut name = self.path.clone().into_os_string();
        name.push(format!(".{index}"));
        PathBuf::from(name)
    }

    fn io_err(&self, source: std::io::Error) -> HistoryError {
        HistoryError::Io {
            path: self.path.clone(),
            source,
        }
    }
}

/// Python's `datetime.fromisoformat(ts.replace("Z", "+00:00"))`, near enough:
/// RFC3339 covers both the `+00:00` offset `datetime.now(timezone.utc)
/// .isoformat()` writes and the `Z` form other tools produce.
pub(crate) fn parse_timestamp(raw: &str) -> Option<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(raw.trim())
        .ok()
        .map(|ts| ts.with_timezone(&Utc))
}

/// Whether `prune` should keep this line. Anything we can't read is kept: the
/// point of the pass is to shed age, not to silently discard evidence we merely
/// failed to understand.
fn keep_after_prune(line: &[u8], cutoff: DateTime<Utc>) -> bool {
    let Ok(text) = std::str::from_utf8(line) else {
        return true;
    };
    let Ok(value) = serde_json::from_str::<Value>(text) else {
        return true;
    };
    match value
        .get("timestamp")
        .and_then(Value::as_str)
        .and_then(parse_timestamp)
    {
        Some(timestamp) => timestamp >= cutoff,
        None => true,
    }
}

fn trim_ascii_whitespace(mut line: &[u8]) -> &[u8] {
    while let [first, rest @ ..] = line {
        if first.is_ascii_whitespace() {
            line = rest;
        } else {
            break;
        }
    }
    while let [rest @ .., last] = line {
        if last.is_ascii_whitespace() {
            line = rest;
        } else {
            break;
        }
    }
    line
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    /// One line of history as 1.5.0 actually wrote it, down to the six-digit
    /// fractional seconds and the `+00:00` offset.
    const REAL_LINE: &str = r#"{"original_path": "C:\\Users\\x\\Downloads\\Ancestors.jpg", "action_taken": "MOVED", "destination_path": "C:\\Users\\x\\Downloads\\_Cleanup\\2025-05-31\\Ancestors.jpg", "monitored_folder": "C:\\Users\\x\\Downloads", "rule_pattern": "*.*", "rule_age_days": 7, "rule_use_regex": false, "rule_action_config": "move", "status": "SUCCESS", "details": "Moved: Ancestors.jpg -> _Cleanup\\2025-05-31\\Ancestors.jpg", "run_id": "6a132f20-61ab-4d93-9d30-5b8fb6220d43", "timestamp": "2025-05-31T15:52:13.363770+00:00", "severity": "INFO"}"#;

    /// The oldest entries in a real file predate `run_id` and `severity`.
    const LEGACY_LINE: &str = r#"{"original_path": "C:\\a\\b.jpg", "action_taken": "MOVED", "destination_path": "C:\\a\\_Cleanup\\b.jpg", "monitored_folder": "C:\\a", "rule_pattern": "*.*", "rule_age_days": 7, "rule_use_regex": false, "rule_action_config": "move", "status": "SUCCESS", "details": "Moved", "timestamp": "2025-05-31T15:52:13.365271+00:00"}"#;

    /// What 1.5.0's undo UI wrote after reversing a move: no `monitored_folder`
    /// and none of the `rule_*` fields.
    const UNDO_MOVE_LINE: &str = r#"{"action_taken": "UNDO_MOVE", "original_path": "C:\\a\\_Cleanup\\2025-05-31\\pack.zip", "destination_path": "C:\\a\\pack.zip", "status": "SUCCESS", "details": "Successfully undid previous move of 'pack.zip'.", "timestamp": "2025-05-31T16:35:20.106585+00:00"}"#;

    fn log_in(dir: &TempDir) -> HistoryLog {
        HistoryLog::new(dir.path().join("autotidy_history.jsonl"))
    }

    fn record(original: &str, timestamp: &str) -> HistoryRecord {
        HistoryRecord {
            original_path: original.into(),
            action_taken: "MOVED".into(),
            destination_path: Some(format!("{original}.moved")),
            monitored_folder: "C:\\monitored".into(),
            rule_pattern: "*.*".into(),
            rule_age_days: 7,
            rule_use_regex: false,
            rule_action_config: "move".into(),
            status: Status::Success,
            details: "Moved".into(),
            run_id: "run-1".into(),
            severity: "INFO".into(),
            timestamp: timestamp.into(),
            copy_size: None,
            copy_mtime: None,
            extra: Map::new(),
        }
    }

    fn days_ago(days: i64) -> String {
        (Utc::now() - chrono::TimeDelta::try_days(days).unwrap()).to_rfc3339()
    }

    #[test]
    fn append_creates_parent_directory_and_round_trips() {
        let dir = tempfile::tempdir().unwrap();
        // Nested directory that does not exist yet.
        let log = HistoryLog::new(dir.path().join("nested").join("deeper").join("hist.jsonl"));

        log.append(&record("C:\\a.txt", &days_ago(0))).unwrap();
        log.append(&record("C:\\b.txt", &days_ago(0))).unwrap();

        let records = log.read_all().unwrap();
        assert_eq!(records.len(), 2);
        assert_eq!(records[0].original_path, "C:\\a.txt");
        assert_eq!(records[1].original_path, "C:\\b.txt");
        assert_eq!(records[0].action_taken, "MOVED");
        assert_eq!(records[0].status, Status::Success);
        assert_eq!(
            records[0].destination_path.as_deref(),
            Some("C:\\a.txt.moved")
        );
        assert_eq!(records[0].rule_age_days, 7);

        // Exactly one newline-terminated line per record, no stray blanks.
        let raw = fs::read_to_string(log.path()).unwrap();
        assert_eq!(raw.lines().count(), 2);
        assert!(raw.ends_with('\n'));
    }

    #[test]
    fn moved_records_do_not_serialise_copy_metadata() {
        let dir = tempfile::tempdir().unwrap();
        let log = log_in(&dir);
        log.append(&record("C:\\a.txt", &days_ago(0))).unwrap();
        let raw = fs::read_to_string(log.path()).unwrap();
        assert!(!raw.contains("copy_size"), "{raw}");
        assert!(!raw.contains("copy_mtime"), "{raw}");
    }

    #[test]
    fn corrupt_line_is_skipped_and_neighbours_survive() {
        let dir = tempfile::tempdir().unwrap();
        let log = log_in(&dir);
        let good_first = serde_json::to_string(&record("C:\\first.txt", &days_ago(1))).unwrap();
        let good_last = serde_json::to_string(&record("C:\\last.txt", &days_ago(1))).unwrap();
        fs::write(
            log.path(),
            format!("{good_first}\n{{not json at all\n{good_last}\n"),
        )
        .unwrap();

        let records = log.read_all().unwrap();
        assert_eq!(records.len(), 2);
        assert_eq!(records[0].original_path, "C:\\first.txt");
        assert_eq!(records[1].original_path, "C:\\last.txt");
    }

    #[test]
    fn blank_lines_are_skipped() {
        let dir = tempfile::tempdir().unwrap();
        let log = log_in(&dir);
        let good = serde_json::to_string(&record("C:\\only.txt", &days_ago(1))).unwrap();
        fs::write(log.path(), format!("\n\n{good}\n   \n\n")).unwrap();

        let records = log.read_all().unwrap();
        assert_eq!(records.len(), 1);
        assert_eq!(records[0].original_path, "C:\\only.txt");
    }

    #[test]
    fn read_all_on_missing_file_is_empty() {
        let dir = tempfile::tempdir().unwrap();
        assert!(log_in(&dir).read_all().unwrap().is_empty());
    }

    #[test]
    fn real_1_5_0_lines_parse() {
        let dir = tempfile::tempdir().unwrap();
        let log = log_in(&dir);
        fs::write(log.path(), format!("{REAL_LINE}\n{LEGACY_LINE}\n")).unwrap();

        let records = log.read_all().unwrap();
        assert_eq!(records.len(), 2);
        assert_eq!(records[0].run_id, "6a132f20-61ab-4d93-9d30-5b8fb6220d43");
        assert_eq!(records[0].severity, "INFO");
        assert_eq!(records[0].status, Status::Success);
        // Legacy entries carry neither field; they must default, not fail.
        assert_eq!(records[1].run_id, "");
        assert_eq!(records[1].severity, "");
    }

    #[test]
    fn python_isoformat_timestamp_parses() {
        let python = parse_timestamp("2025-05-31T15:52:13.363770+00:00").unwrap();
        let rfc3339_z = parse_timestamp("2025-05-31T15:52:13.363770Z").unwrap();
        assert_eq!(python, rfc3339_z);
        assert_eq!(python.timestamp(), 1_748_706_733);
        assert!(parse_timestamp("").is_none());
        assert!(parse_timestamp("not a timestamp").is_none());
    }

    #[test]
    fn finalize_fills_timestamp_and_severity() {
        let mut raw = record("C:\\a.txt", "");
        raw.severity = String::new();
        raw.status = Status::Failure;
        let finalized = raw.finalize();
        assert_eq!(finalized.severity, "ERROR");
        assert!(parse_timestamp(&finalized.timestamp).is_some());
    }

    #[test]
    fn prune_drops_old_and_keeps_new() {
        let dir = tempfile::tempdir().unwrap();
        let log = log_in(&dir);
        log.append(&record("C:\\ancient.txt", &days_ago(200)))
            .unwrap();
        log.append(&record("C:\\old.txt", &days_ago(91))).unwrap();
        log.append(&record("C:\\fresh.txt", &days_ago(3))).unwrap();
        log.append(&record("C:\\now.txt", &days_ago(0))).unwrap();

        log.prune(DEFAULT_MAX_AGE_DAYS).unwrap();

        let kept: Vec<String> = log
            .read_all()
            .unwrap()
            .into_iter()
            .map(|r| r.original_path)
            .collect();
        assert_eq!(kept, vec!["C:\\fresh.txt", "C:\\now.txt"]);
    }

    #[test]
    fn prune_keeps_unparseable_lines() {
        let dir = tempfile::tempdir().unwrap();
        let log = log_in(&dir);
        let old = serde_json::to_string(&record("C:\\old.txt", &days_ago(200))).unwrap();
        let fresh = serde_json::to_string(&record("C:\\fresh.txt", &days_ago(1))).unwrap();
        fs::write(
            log.path(),
            format!("{old}\n{{ truncated json\nnot json at all\n{fresh}\n"),
        )
        .unwrap();

        log.prune(DEFAULT_MAX_AGE_DAYS).unwrap();

        let raw = fs::read_to_string(log.path()).unwrap();
        let lines: Vec<&str> = raw.lines().collect();
        assert_eq!(lines.len(), 3, "{raw}");
        assert_eq!(lines[0], "{ truncated json");
        assert_eq!(lines[1], "not json at all");
        assert!(lines[2].contains("C:\\\\fresh.txt"));
        assert!(!raw.contains("old.txt"));
    }

    #[test]
    fn prune_keeps_lines_without_a_usable_timestamp() {
        let dir = tempfile::tempdir().unwrap();
        let log = log_in(&dir);
        fs::write(
            log.path(),
            concat!(
                "{\"original_path\": \"no-timestamp\"}\n",
                "{\"original_path\": \"empty-timestamp\", \"timestamp\": \"\"}\n",
                "{\"original_path\": \"naive\", \"timestamp\": \"2020-01-01T00:00:00\"}\n",
                "[\"not even an object\"]\n",
            ),
        )
        .unwrap();

        log.prune(1).unwrap();

        let raw = fs::read_to_string(log.path()).unwrap();
        assert_eq!(raw.lines().count(), 4, "{raw}");
        assert!(raw.contains("no-timestamp"));
        assert!(raw.contains("empty-timestamp"));
        assert!(raw.contains("naive"));
        assert!(raw.contains("not even an object"));
    }

    #[test]
    fn prune_leaves_no_temp_files_behind() {
        let dir = tempfile::tempdir().unwrap();
        let log = log_in(&dir);
        log.append(&record("C:\\fresh.txt", &days_ago(0))).unwrap();
        log.prune(DEFAULT_MAX_AGE_DAYS).unwrap();

        let entries: Vec<PathBuf> = fs::read_dir(dir.path())
            .unwrap()
            .map(|e| e.unwrap().path())
            .collect();
        assert_eq!(entries, vec![log.path().to_path_buf()]);
    }

    #[test]
    fn prune_on_missing_file_is_a_noop() {
        let dir = tempfile::tempdir().unwrap();
        let log = log_in(&dir);
        log.prune(DEFAULT_MAX_AGE_DAYS).unwrap();
        assert!(!log.path().exists());
    }

    #[test]
    fn rotate_is_a_noop_below_the_threshold() {
        let dir = tempfile::tempdir().unwrap();
        let log = log_in(&dir);
        log.append(&record("C:\\a.txt", &days_ago(0))).unwrap();
        let before = fs::read_to_string(log.path()).unwrap();

        log.rotate_if_needed().unwrap();

        assert_eq!(fs::read_to_string(log.path()).unwrap(), before);
        assert!(!log.backup_path(1).exists());
    }

    #[test]
    fn rotate_on_missing_file_is_a_noop() {
        let dir = tempfile::tempdir().unwrap();
        let log = log_in(&dir);
        log.rotate_if_needed().unwrap();
        assert!(!log.path().exists());
        assert!(!log.backup_path(1).exists());
    }

    /// Grow the log past the rotation threshold without writing 10 MB by hand.
    fn oversize(path: &Path, marker: &str) {
        let file = File::create(path).unwrap();
        writeln!(&file, "{marker}").unwrap();
        file.set_len(MAX_HISTORY_SIZE_BYTES + 1).unwrap();
    }

    #[test]
    fn append_rotates_oversized_log_and_starts_a_fresh_one() {
        let dir = tempfile::tempdir().unwrap();
        let log = log_in(&dir);
        oversize(log.path(), "previous generation");

        log.append(&record("C:\\after-rotation.txt", &days_ago(0)))
            .unwrap();

        // The bloated file moved aside intact...
        let rotated = fs::read(log.backup_path(1)).unwrap();
        assert_eq!(rotated.len() as u64, MAX_HISTORY_SIZE_BYTES + 1);
        assert!(rotated.starts_with(b"previous generation"));

        // ...and the live file holds only the new record.
        let records = log.read_all().unwrap();
        assert_eq!(records.len(), 1);
        assert_eq!(records[0].original_path, "C:\\after-rotation.txt");
        assert!(fs::metadata(log.path()).unwrap().len() < MAX_HISTORY_SIZE_BYTES);
    }

    #[test]
    fn rotate_shifts_backups_and_discards_the_oldest() {
        let dir = tempfile::tempdir().unwrap();
        let log = log_in(&dir);
        oversize(log.path(), "current");
        fs::write(log.backup_path(1), "one").unwrap();
        fs::write(log.backup_path(2), "two").unwrap();
        fs::write(log.backup_path(3), "three").unwrap();

        log.rotate_if_needed().unwrap();

        // .3 (the former "three") is gone for good; everything else shifted.
        assert_eq!(fs::read_to_string(log.backup_path(3)).unwrap(), "two");
        assert_eq!(fs::read_to_string(log.backup_path(2)).unwrap(), "one");
        assert!(fs::read(log.backup_path(1))
            .unwrap()
            .starts_with(b"current"));
        assert!(!log.path().exists(), "rotation must free the live path");
        assert!(!log.backup_path(4).exists());
    }

    #[test]
    fn undo_move_lines_without_rule_fields_parse() {
        let dir = tempfile::tempdir().unwrap();
        let log = log_in(&dir);
        fs::write(log.path(), format!("{UNDO_MOVE_LINE}\n")).unwrap();

        let records = log.read_all().unwrap();
        assert_eq!(records.len(), 1, "1.5.0's undo UI wrote this exact shape");
        assert_eq!(records[0].action_taken, "UNDO_MOVE");
        assert_eq!(records[0].monitored_folder, "");
        assert_eq!(records[0].rule_age_days, 0);
    }

    #[test]
    fn backup_paths_suffix_the_whole_filename() {
        let log = HistoryLog::new("C:\\cfg\\autotidy_history.jsonl");
        assert!(log
            .backup_path(2)
            .to_string_lossy()
            .ends_with("autotidy_history.jsonl.2"));
    }
}
