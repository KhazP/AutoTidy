//! Performing a rule's action on one file: move, copy, trash, delete.
//!
//! Ported from `process_file_action` in `utils.py`. This is the module where a
//! bug costs the user their files, so it stays explicit rather than clever.

use crate::config::Action;
use crate::history::{HistoryRecord, Status};
use crate::template::{self, Placeholders};
use std::path::{Path, PathBuf};

/// Suffix attempts before `claim_unique_path` gives up and timestamps.
/// Matches `_atomic_claim_path`'s `max_attempts=100` default.
const MAX_CLAIM_ATTEMPTS: u32 = 100;

#[derive(Debug, thiserror::Error)]
pub enum ActionError {
    #[error("invalid archive template: {0}")]
    Template(#[from] crate::template::TemplateError),
    #[error("target path escapes destination boundary for '{0}'")]
    BoundaryEscape(String),
    #[error("could not claim a unique path for '{name}': {source}")]
    Claim {
        name: String,
        #[source]
        source: std::io::Error,
    },
    #[error("copy verification failed for '{0}': size mismatch")]
    VerificationFailed(String),
    #[error("i/o error on {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("could not send '{path}' to the recycle bin: {message}")]
    Trash { path: PathBuf, message: String },
}

/// Everything an action needs that isn't the file itself.
#[derive(Debug, Clone)]
pub struct ActionContext<'a> {
    pub monitored_folder: &'a Path,
    /// Already resolved by `Rule::effective_template`.
    pub template: &'a str,
    pub action: Action,
    pub dry_run: bool,
    pub run_id: &'a str,
    // Echoed into the history record so the log records which rule fired.
    pub rule_pattern: &'a str,
    pub rule_age_days: i64,
    pub rule_use_regex: bool,
}

/// What happened, and the line to write to history.
#[derive(Debug)]
pub struct Outcome {
    pub success: bool,
    /// Human-readable, shown in the live log pane.
    pub message: String,
    pub record: HistoryRecord,
}

/// Apply `ctx.action` to `file`.
///
/// Never returns `Err` for an expected failure: a permission error, a missing
/// source, or a bad template all produce an `Outcome` with `success: false` and
/// a `FAILURE` history record, because every attempt must be logged. `Err` is
/// reserved for failures that prevent even recording the attempt.
pub fn process_file(file: &Path, ctx: &ActionContext<'_>) -> Result<Outcome, ActionError> {
    // Every message quotes the source file name, exactly as 1.5.0 did.
    let filename = match file.file_name() {
        Some(name) => name.to_string_lossy().into_owned(),
        None => {
            // A bare root or a path ending in `..`: there is no file here to
            // act on, and guessing would mean acting on a directory.
            let err = general_io(
                file,
                "path has no file name component; refusing to act on it",
            );
            let out = io_failure(file, &file.display().to_string(), ctx, &err, None);
            return Ok(out);
        }
    };

    // Confirm the source is a plain file before anything is created, claimed or
    // deleted. 1.5.0 discovered a missing source only by letting `shutil` throw,
    // which for a move meant a zero-byte placeholder had already been left in
    // the archive folder. Checking first keeps failures side-effect free.
    //
    // `symlink_metadata` does not follow links, so a dangling symlink reports
    // as present rather than as a missing file, and is handled by the operation
    // itself rather than being silently reclassified.
    match std::fs::symlink_metadata(file) {
        Ok(meta) if meta.is_dir() => {
            let err = general_io(file, "path is a directory, not a file");
            return Ok(io_failure(file, &filename, ctx, &err, None));
        }
        Ok(_) => {}
        Err(source) => {
            // Note a deliberate divergence from 1.5.0: this check also runs for
            // a dry run, so a simulated action over a vanished file reports
            // `SIMULATED_*_ERROR_NOT_FOUND` instead of claiming it "would move"
            // a file that is not there.
            let err = ActionError::Io {
                path: file.to_path_buf(),
                source,
            };
            return Ok(io_failure(file, &filename, ctx, &err, None));
        }
    }

    Ok(match ctx.action {
        Action::Move | Action::Copy => relocate(file, &filename, ctx),
        Action::DeleteToTrash | Action::DeletePermanently => discard(file, &filename, ctx),
    })
}

// ---------------------------------------------------------------------------
// Move / copy
// ---------------------------------------------------------------------------

fn relocate(file: &Path, filename: &str, ctx: &ActionContext<'_>) -> Outcome {
    // "MOVE" / "COPY" — the prefix every error `action_taken` is built from.
    let verb = ctx.action.as_str().to_ascii_uppercase();

    // 1. A template is validated before it is allowed anywhere near a path.
    if let Err(e) = template::validate(ctx.template) {
        let message = format!("Error: Invalid archive template: {e}");
        return failure(file, ctx, format!("{verb}_ERROR_TEMPLATE"), None, message);
    }

    // 2. Expand the template for this specific file.
    let values = Placeholders::for_file(file, ctx.monitored_folder, chrono::Local::now());
    let resolved = template::resolve(ctx.template, ctx.monitored_folder, &values);

    // 3. `{FILENAME}`/`{EXT}` mean the template named the file itself, so the
    //    resolved path is the target and its parent is the directory to create.
    //    Otherwise the resolved path is the directory and the original file name
    //    is appended.
    let (base_dir, target_file) = if template::has_filename_tokens(ctx.template) {
        let parent = resolved
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or_else(|| resolved.clone());
        (parent, resolved)
    } else {
        let target = resolved.join(filename);
        (resolved, target)
    };

    // 4. Defence in depth. Both branches above build the target from its own
    //    base, so this should be unreachable; it stays because the cost of
    //    being wrong is writing outside the folder the user chose.
    if !within_boundary(&target_file, &base_dir) {
        let message = format!("Error: Target path escapes destination boundary for '{filename}'");
        return failure(file, ctx, format!("{verb}_ERROR_BOUNDARY"), None, message);
    }

    // The name to reserve comes from the *target*, not the source. 1.5.0 passed
    // the source stem/extension to `_atomic_claim_path`, which silently threw
    // away any renaming a `{FILENAME}`-style template had just performed.
    let (stem, ext) = split_stem_ext(&target_file);

    // 5. A dry run must not create a single directory or file.
    if ctx.dry_run {
        // Read-only peek so the preview shows the `_1` the real run would pick.
        let preview = if target_file.exists() {
            base_dir.join(format!("{stem}_1{ext}"))
        } else {
            target_file
        };
        let shown = relative_display(&preview, ctx.monitored_folder);
        let would = if ctx.action == Action::Copy {
            "Would copy"
        } else {
            "Would move"
        };
        let message = format!("[DRY RUN] {would}: '{filename}' to '{shown}'");
        let record = build_record(
            file,
            ctx,
            format!("SIMULATED_{verb}"),
            Some(&preview),
            Status::Success,
            &message,
        )
        .finalize();
        return Outcome {
            success: true,
            message,
            record,
        };
    }

    // 6. Create the destination, then reserve a name inside it.
    if let Err(source) = std::fs::create_dir_all(&base_dir) {
        let message = format!("Error: Could not claim unique path for '{filename}': {source}");
        return failure(
            file,
            ctx,
            format!("{verb}_ERROR_COLLISION"),
            Some(&target_file),
            message,
        );
    }
    let claimed = match claim_unique_path(&base_dir, &stem, &ext, MAX_CLAIM_ATTEMPTS) {
        Ok(path) => path,
        Err(e) => {
            let message = format!("Error: Could not claim unique path for '{filename}': {e}");
            return failure(
                file,
                ctx,
                format!("{verb}_ERROR_COLLISION"),
                Some(&target_file),
                message,
            );
        }
    };

    // 7. Commit.
    let performed = match ctx.action {
        Action::Copy => copy_onto_reservation(file, &claimed),
        _ => move_onto_reservation(file, &claimed),
    };
    if let Err(e) = performed {
        tracing::error!(
            source_path = %file.display(),
            destination = %claimed.display(),
            error = %e,
            "action failed"
        );
        return io_failure(file, filename, ctx, &e, Some(&claimed));
    }

    // 8. `MOVED` / `COPIED` are matched as literals by `undo.rs`.
    let taken = if ctx.action == Action::Copy {
        "COPIED"
    } else {
        "MOVED"
    };
    let shown = relative_display(&claimed, ctx.monitored_folder);
    let message = format!("{}: {filename} -> {shown}", capitalize(taken));
    let mut record = build_record(
        file,
        ctx,
        taken.to_string(),
        Some(&claimed),
        Status::Success,
        &message,
    );

    // A copy leaves a second, independent file behind. Record its identity so
    // `undo.rs` can refuse to delete it if the user has since edited it.
    if ctx.action == Action::Copy {
        match std::fs::metadata(&claimed) {
            Ok(meta) => {
                record.copy_size = Some(meta.len());
                record.copy_mtime = meta.modified().ok().map(unix_seconds);
            }
            Err(e) => {
                // Not fatal: the copy succeeded. Undo simply falls back to the
                // unverified path it uses for pre-1.5.0 history.
                tracing::warn!(
                    destination = %claimed.display(),
                    error = %e,
                    "could not stat the copy; undo verification metadata omitted"
                );
            }
        }
    }

    Outcome {
        success: true,
        message,
        record: record.finalize(),
    }
}

/// Fill the reservation with the source's bytes.
///
/// No gap at all here: `claim_unique_path` left a zero-byte file holding the
/// name and `fs::copy` truncates and rewrites it in place, so the name is never
/// unowned between reserving and committing.
///
/// Unlike Python's `shutil.copy2`, `fs::copy` does not carry the source mtime
/// over. That is fine because `copy_mtime` is read back off the destination
/// after the fact, so the value recorded always describes the file undo will
/// later inspect.
fn copy_onto_reservation(src: &Path, dst: &Path) -> Result<(), ActionError> {
    match std::fs::copy(src, dst) {
        Ok(_) => Ok(()),
        Err(source) => {
            // Never leave a zero-byte or half-written file in the user's
            // archive; everything at `dst` right now is ours.
            if let Err(e) = std::fs::remove_file(dst) {
                tracing::warn!(path = %dst.display(), error = %e, "could not clean up a failed copy");
            }
            Err(ActionError::Io {
                path: src.to_path_buf(),
                source,
            })
        }
    }
}

/// Replace the reservation with the source file itself.
///
/// The deliberate trade-off, and the reason this is not `std::fs::rename`:
///
/// A rename cannot land on a name that is currently occupied by our own
/// reservation, so the reservation has to be released first — which reopens a
/// window. 1.5.0 did exactly that (`dst.unlink(); src.rename(dst)`) and
/// `rename` *replaces* an existing destination on both Windows and POSIX, so
/// anything that raced into the freed name was silently destroyed.
///
/// The window cannot be closed without a rename primitive that accepts an
/// existing handle, but its consequence can be changed. `rename_no_clobber`
/// uses `MoveFileExW` **without** `MOVEFILE_REPLACE_EXISTING` (and `link(2)` on
/// unix), so a destination that reappeared in the window makes the move fail
/// loudly and the source stay put. We can lose the move; we cannot lose a file.
fn move_onto_reservation(src: &Path, dst: &Path) -> Result<(), ActionError> {
    std::fs::remove_file(dst).map_err(|source| ActionError::Io {
        path: dst.to_path_buf(),
        source,
    })?;

    match rename_no_clobber(src, dst) {
        Ok(()) => Ok(()),
        // Something claimed the name in the window above. Refuse to overwrite
        // it; the source is untouched and the failure is logged.
        Err(source) if is_already_exists(&source) => {
            tracing::error!(
                destination = %dst.display(),
                "destination was taken between reserving and moving; refusing to overwrite"
            );
            Err(ActionError::Io {
                path: dst.to_path_buf(),
                source,
            })
        }
        // Cross-filesystem moves (EXDEV / ERROR_NOT_SAME_DEVICE) and anything
        // else a rename cannot do: 1.5.0's `except OSError` branch.
        Err(source) => {
            tracing::debug!(
                error = %source,
                "rename unavailable; falling back to verified copy + unlink"
            );
            copy_verify_unlink(src, dst)
        }
    }
}

/// Cross-filesystem move: copy, verify the destination really is the same size
/// as the source, then unlink the source.
///
/// The size check is the only thing standing between a truncated copy and a
/// deleted original, so a mismatch removes the partial destination and fails.
fn copy_verify_unlink(src: &Path, dst: &Path) -> Result<(), ActionError> {
    // The reservation has already been released, and `fs::copy` truncates
    // whatever it finds, so re-check that the name is still free.
    if dst.exists() {
        return Err(ActionError::Io {
            path: dst.to_path_buf(),
            source: std::io::Error::new(
                std::io::ErrorKind::AlreadyExists,
                "destination appeared before the fallback copy",
            ),
        });
    }

    std::fs::copy(src, dst).map_err(|source| ActionError::Io {
        path: dst.to_path_buf(),
        source,
    })?;

    let name = || {
        src.file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_else(|| src.display().to_string())
    };

    // Both sizes are read after the copy, matching 1.5.0: a source that changed
    // mid-copy is also a mismatch, and refusing the move is the safe answer.
    let src_len = match std::fs::metadata(src) {
        Ok(meta) => meta.len(),
        Err(source) => {
            let _ = std::fs::remove_file(dst);
            return Err(ActionError::Io {
                path: src.to_path_buf(),
                source,
            });
        }
    };
    let dst_len = match std::fs::metadata(dst) {
        Ok(meta) => meta.len(),
        Err(source) => {
            let _ = std::fs::remove_file(dst);
            return Err(ActionError::Io {
                path: dst.to_path_buf(),
                source,
            });
        }
    };
    if src_len != dst_len {
        let _ = std::fs::remove_file(dst);
        return Err(ActionError::VerificationFailed(name()));
    }

    std::fs::remove_file(src).map_err(|source| ActionError::Io {
        path: src.to_path_buf(),
        source,
    })
}

/// Rename that fails rather than overwriting.
///
/// `std::fs::rename` is unusable here: on Windows it passes
/// `MOVEFILE_REPLACE_EXISTING`, and on unix `rename(2)` replaces silently.
/// Either would destroy a file sitting at `dst`.
#[cfg(windows)]
fn rename_no_clobber(src: &Path, dst: &Path) -> std::io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::{MoveFileExW, MOVEFILE_COPY_ALLOWED};

    fn wide(path: &Path) -> std::io::Result<Vec<u16>> {
        let mut buf: Vec<u16> = path.as_os_str().encode_wide().collect();
        if buf.contains(&0) {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "path contains an interior NUL",
            ));
        }
        buf.push(0);
        Ok(buf)
    }

    let src_w = wide(src)?;
    let dst_w = wide(dst)?;

    // MOVEFILE_COPY_ALLOWED lets the move span volumes. MOVEFILE_REPLACE_EXISTING
    // is deliberately absent, which is the whole point of this function: an
    // occupied destination returns ERROR_ALREADY_EXISTS instead of being
    // silently clobbered.
    //
    // SAFETY: both buffers are NUL-terminated, outlive the call, and are only
    // read by the callee.
    let ok = unsafe { MoveFileExW(src_w.as_ptr(), dst_w.as_ptr(), MOVEFILE_COPY_ALLOWED) };
    if ok == 0 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}

/// See the Windows implementation. `link(2)` fails with `EEXIST` rather than
/// replacing, which is the no-clobber guarantee `rename(2)` cannot give;
/// cross-device errors are handled by the caller's `copy_verify_unlink`.
#[cfg(not(windows))]
fn rename_no_clobber(src: &Path, dst: &Path) -> std::io::Result<()> {
    std::fs::hard_link(src, dst)?;
    match std::fs::remove_file(src) {
        Ok(()) => Ok(()),
        Err(e) => {
            // The link and the source name the same inode, so dropping the link
            // we just made loses nothing and avoids leaving a duplicate behind.
            let _ = std::fs::remove_file(dst);
            Err(e)
        }
    }
}

// ---------------------------------------------------------------------------
// Trash / permanent delete
// ---------------------------------------------------------------------------

fn discard(file: &Path, filename: &str, ctx: &ActionContext<'_>) -> Outcome {
    let to_trash = ctx.action == Action::DeleteToTrash;

    if ctx.dry_run {
        let (taken, message) = if to_trash {
            (
                "SIMULATED_DELETE_TO_TRASH",
                format!("[DRY RUN] Would send to trash: '{filename}'"),
            )
        } else {
            (
                "SIMULATED_DELETE_PERMANENTLY",
                format!("[DRY RUN] Would permanently delete: '{filename}' (irreversible)"),
            )
        };
        let record = build_record(
            file,
            ctx,
            taken.to_string(),
            None,
            Status::Success,
            &message,
        )
        .finalize();
        return Outcome {
            success: true,
            message,
            record,
        };
    }

    let performed = if to_trash {
        trash::delete(file).map_err(|e| ActionError::Trash {
            path: file.to_path_buf(),
            message: e.to_string(),
        })
    } else {
        std::fs::remove_file(file).map_err(|source| ActionError::Io {
            path: file.to_path_buf(),
            source,
        })
    };
    if let Err(e) = performed {
        tracing::error!(source_path = %file.display(), error = %e, "delete failed");
        return io_failure(file, filename, ctx, &e, None);
    }

    let (taken, message) = if to_trash {
        (
            "DELETED_TO_TRASH",
            format!("Success: Sent to trash: '{filename}'"),
        )
    } else {
        (
            "DELETED_PERMANENTLY",
            format!("Success: Permanently deleted: '{filename}' (irreversible)"),
        )
    };
    let record = build_record(
        file,
        ctx,
        taken.to_string(),
        None,
        Status::Success,
        &message,
    )
    .finalize();
    Outcome {
        success: true,
        message,
        record,
    }
}

// ---------------------------------------------------------------------------
// Path claiming
// ---------------------------------------------------------------------------

/// Reserve an unused path in `dir` for `stem`+`ext`, returning the claimed path.
///
/// 1.5.0 created an `O_CREAT|O_EXCL` placeholder to reserve the name, then
/// deleted it and renamed into the gap — reopening the very race the exclusive
/// create was meant to close. This must claim and commit without a window:
/// create exclusively and keep the handle/reservation until the content lands.
///
/// After `max_attempts` collisions, falls back to a timestamped name rather
/// than failing, matching 1.5.0's final fallback.
pub fn claim_unique_path(
    dir: &Path,
    stem: &str,
    ext: &str,
    max_attempts: u32,
) -> Result<PathBuf, ActionError> {
    // `base`, then `stem_1.ext` … `stem_<max_attempts>.ext`, exactly the
    // sequence `_atomic_claim_path` walked.
    for attempt in 0..=max_attempts {
        let name = if attempt == 0 {
            format!("{stem}{ext}")
        } else {
            format!("{stem}_{attempt}{ext}")
        };
        let candidate = dir.join(&name);
        match reserve(&candidate) {
            Ok(()) => return Ok(candidate),
            // Taken. A directory sitting on the name reports as an access
            // failure rather than EEXIST on Windows, hence the second check.
            Err(e) if is_already_exists(&e) || candidate.exists() => continue,
            Err(source) => return Err(ActionError::Claim { name, source }),
        }
    }

    // Every suffix was occupied. Timestamp instead of failing, so a
    // pathological directory still gets its file — 1.5.0's last resort.
    // `%6f` is microseconds, matching Python's `%f`.
    let name = format!(
        "{stem}_{}{ext}",
        chrono::Local::now().format("%Y%m%d_%H%M%S_%6f")
    );
    let candidate = dir.join(&name);
    reserve(&candidate).map_err(|source| ActionError::Claim { name, source })?;
    Ok(candidate)
}

/// Take exclusive ownership of `path` by creating it and nothing else.
///
/// `create_new` is `O_CREAT|O_EXCL` on unix and `CREATE_NEW` on Windows: the
/// test-and-create is one operation, so two racing scans cannot both believe
/// they own the name. The handle is dropped immediately; the zero-byte file
/// left behind *is* the reservation, and the caller replaces it with content.
fn reserve(path: &Path) -> std::io::Result<()> {
    std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map(|_handle| ())
}

// ---------------------------------------------------------------------------
// Boundary
// ---------------------------------------------------------------------------

/// Reject a resolved target that escapes its own destination directory —
/// the `resolved_target.startswith(resolved_base)` check in `process_file_action`.
pub fn within_boundary(target: &Path, base: &Path) -> bool {
    // `config::normalize` resolves `..`/`.` lexically without touching the
    // filesystem. `canonicalize` would be wrong twice over: it fails outright on
    // a destination that does not exist yet, and on Windows it returns
    // `\\?\`-prefixed paths that no longer compare equal to their inputs.
    let target = crate::config::normalize(target);
    let base = crate::config::normalize(base);

    // Component-wise, so a sibling named `archive-old` is not accepted as being
    // inside `archive` the way a raw string prefix test would.
    target == base || target.starts_with(&base)
}

// ---------------------------------------------------------------------------
// Record helpers
// ---------------------------------------------------------------------------

/// Which of 1.5.0's three `except` arms an error corresponds to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Failure {
    NotFound,
    Permission,
    General,
}

impl Failure {
    fn suffix(self) -> &'static str {
        match self {
            Failure::NotFound => "_ERROR_NOT_FOUND",
            Failure::Permission => "_ERROR_PERMISSION",
            Failure::General => "_ERROR_GENERAL",
        }
    }

    fn classify(err: &ActionError) -> Self {
        let io = match err {
            ActionError::Io { source, .. } | ActionError::Claim { source, .. } => source,
            _ => return Failure::General,
        };
        match io.kind() {
            std::io::ErrorKind::NotFound => Failure::NotFound,
            std::io::ErrorKind::PermissionDenied => Failure::Permission,
            _ => Failure::General,
        }
    }
}

/// Turn an error into the FAILURE outcome 1.5.0 would have logged, including
/// its `action_taken` spelling: `(("SIMULATED_" if dry_run else "") + action +
/// suffix).upper()`.
fn io_failure(
    file: &Path,
    filename: &str,
    ctx: &ActionContext<'_>,
    err: &ActionError,
    destination: Option<&Path>,
) -> Outcome {
    let kind = Failure::classify(err);
    let action = ctx.action.as_str();
    let action_taken = format!(
        "{}{}{}",
        if ctx.dry_run { "SIMULATED_" } else { "" },
        action.to_ascii_uppercase(),
        kind.suffix()
    );
    let message = match kind {
        Failure::NotFound => format!("Error: Source file not found for {action}: '{filename}'"),
        Failure::Permission => {
            format!("Error: Permission denied for {action} on file '{filename}'")
        }
        Failure::General => format!("Error performing {action} on '{filename}': {err}"),
    };
    failure(file, ctx, action_taken, destination, message)
}

fn failure(
    file: &Path,
    ctx: &ActionContext<'_>,
    action_taken: String,
    destination: Option<&Path>,
    message: String,
) -> Outcome {
    tracing::warn!(
        source_path = %file.display(),
        action_taken = %action_taken,
        detail = %message,
        "action failed"
    );
    let record = build_record(
        file,
        ctx,
        action_taken,
        destination,
        Status::Failure,
        &message,
    )
    .finalize();
    Outcome {
        success: false,
        message,
        record,
    }
}

fn build_record(
    file: &Path,
    ctx: &ActionContext<'_>,
    action_taken: String,
    destination: Option<&Path>,
    status: Status,
    details: &str,
) -> HistoryRecord {
    HistoryRecord {
        original_path: file.display().to_string(),
        action_taken,
        destination_path: destination.map(|p| p.display().to_string()),
        monitored_folder: ctx.monitored_folder.display().to_string(),
        rule_pattern: ctx.rule_pattern.to_string(),
        rule_age_days: ctx.rule_age_days,
        rule_use_regex: ctx.rule_use_regex,
        rule_action_config: ctx.action.as_str().to_string(),
        status,
        details: details.to_string(),
        run_id: ctx.run_id.to_string(),
        // Both stamped by `HistoryRecord::finalize`.
        severity: String::new(),
        timestamp: String::new(),
        copy_size: None,
        copy_mtime: None,
        extra: serde_json::Map::new(),
    }
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

/// `Path::stem` / `Path::suffix` semantics: `archive.tar.gz` splits into
/// `archive.tar` + `.gz`, and `.bashrc` into `.bashrc` + `""`.
fn split_stem_ext(path: &Path) -> (String, String) {
    let stem = path
        .file_stem()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_default();
    let ext = path
        .extension()
        .map(|e| format!(".{}", e.to_string_lossy()))
        .unwrap_or_default();
    (stem, ext)
}

/// The `target.relative_to(monitored)` display, falling back to the absolute
/// path when the destination lives outside the monitored folder.
fn relative_display(target: &Path, monitored: &Path) -> String {
    let base = crate::config::normalize(monitored);
    match crate::config::normalize(target).strip_prefix(&base) {
        Ok(rel) if !rel.as_os_str().is_empty() => rel.display().to_string(),
        _ => target.display().to_string(),
    }
}

/// `"MOVED"` -> `"Moved"`, matching Python's `str.capitalize()`.
fn capitalize(s: &str) -> String {
    let mut chars = s.chars();
    match chars.next() {
        Some(first) => first.to_uppercase().collect::<String>() + &chars.as_str().to_lowercase(),
        None => String::new(),
    }
}

/// Seconds since the Unix epoch, as `os.stat().st_mtime` reports them.
fn unix_seconds(time: std::time::SystemTime) -> f64 {
    match time.duration_since(std::time::UNIX_EPOCH) {
        Ok(d) => d.as_secs_f64(),
        // Pre-1970 timestamps are nonsense in practice but must not panic.
        Err(e) => -e.duration().as_secs_f64(),
    }
}

fn general_io(path: &Path, message: &str) -> ActionError {
    ActionError::Io {
        path: path.to_path_buf(),
        source: std::io::Error::new(std::io::ErrorKind::InvalidInput, message),
    }
}

/// True when an error means "the destination name is already taken".
fn is_already_exists(e: &std::io::Error) -> bool {
    if e.kind() == std::io::ErrorKind::AlreadyExists {
        return true;
    }
    #[cfg(windows)]
    {
        // ERROR_FILE_EXISTS / ERROR_ALREADY_EXISTS. `std` folds both into
        // `AlreadyExists` today; checked explicitly because misreading a
        // collision as a generic error is what would license an overwrite.
        if matches!(e.raw_os_error(), Some(80) | Some(183)) {
            return true;
        }
    }
    false
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::{tempdir, TempDir};

    const BODY: &str = "the bytes that must survive";

    fn ctx<'a>(
        monitored: &'a Path,
        template: &'a str,
        action: Action,
        dry_run: bool,
    ) -> ActionContext<'a> {
        ActionContext {
            monitored_folder: monitored,
            template,
            action,
            dry_run,
            run_id: "test-run",
            rule_pattern: "*.*",
            rule_age_days: 0,
            rule_use_regex: false,
        }
    }

    fn seed(dir: &Path, name: &str, body: &str) -> PathBuf {
        let path = dir.join(name);
        fs::write(&path, body).unwrap();
        path
    }

    /// The path actually written, taken from the record rather than rebuilt, so
    /// assertions do not depend on how `template::resolve` spells a path.
    fn recorded_destination(out: &Outcome) -> PathBuf {
        PathBuf::from(
            out.record
                .destination_path
                .as_ref()
                .expect("a move/copy must record a destination"),
        )
    }

    fn entry_count(dir: &Path) -> usize {
        fs::read_dir(dir).unwrap().count()
    }

    fn workspace() -> (TempDir, PathBuf) {
        let tmp = tempdir().unwrap();
        let monitored = tmp.path().to_path_buf();
        (tmp, monitored)
    }

    // -- move / copy --------------------------------------------------------

    #[test]
    fn move_relocates_the_file_and_preserves_its_bytes() {
        let (_tmp, monitored) = workspace();
        let src = seed(&monitored, "report.txt", BODY);

        let out = process_file(&src, &ctx(&monitored, "archive", Action::Move, false)).unwrap();

        assert!(out.success, "{}", out.message);
        assert_eq!(out.record.action_taken, "MOVED");
        assert_eq!(out.record.status, Status::Success);
        assert!(!src.exists(), "the source must be gone after a move");

        let dst = recorded_destination(&out);
        assert!(dst.exists(), "the destination must exist");
        assert_eq!(fs::read_to_string(&dst).unwrap(), BODY);
        assert_eq!(dst.file_name().unwrap(), "report.txt");
        assert_eq!(dst.parent().unwrap().file_name().unwrap(), "archive");
        assert_eq!(out.record.rule_action_config, "move");
        assert_eq!(out.record.run_id, "test-run");
        assert!(!out.record.timestamp.is_empty(), "finalize must stamp time");
        assert_eq!(out.record.severity, "INFO");
    }

    #[test]
    fn copy_leaves_the_source_and_records_identity_for_undo() {
        let (_tmp, monitored) = workspace();
        let src = seed(&monitored, "report.txt", BODY);

        let out = process_file(&src, &ctx(&monitored, "archive", Action::Copy, false)).unwrap();

        assert!(out.success, "{}", out.message);
        assert_eq!(out.record.action_taken, "COPIED");
        assert!(src.exists(), "a copy must not remove the source");
        assert_eq!(fs::read_to_string(&src).unwrap(), BODY);

        let dst = recorded_destination(&out);
        assert_eq!(fs::read_to_string(&dst).unwrap(), BODY);

        // undo.rs refuses to delete a copy unless these match the file on disk.
        assert_eq!(out.record.copy_size, Some(BODY.len() as u64));
        let recorded_mtime = out.record.copy_mtime.expect("copy_mtime must be recorded");
        let on_disk = unix_seconds(fs::metadata(&dst).unwrap().modified().unwrap());
        assert!(
            (recorded_mtime - on_disk).abs() < 0.001,
            "copy_mtime {recorded_mtime} should describe the destination ({on_disk})"
        );
    }

    #[test]
    fn a_name_collision_never_overwrites_the_file_already_there() {
        let (_tmp, monitored) = workspace();
        let archive = monitored.join("archive");
        fs::create_dir_all(&archive).unwrap();
        let victim = seed(&archive, "report.txt", "DO NOT TOUCH");
        let src = seed(&monitored, "report.txt", BODY);

        let out = process_file(&src, &ctx(&monitored, "archive", Action::Move, false)).unwrap();

        assert!(out.success, "{}", out.message);
        // The single most important assertion in this file.
        assert_eq!(
            fs::read_to_string(&victim).unwrap(),
            "DO NOT TOUCH",
            "the pre-existing file was clobbered"
        );
        assert_eq!(
            fs::read_to_string(archive.join("report_1.txt")).unwrap(),
            BODY
        );
        assert!(!src.exists());

        let dst = recorded_destination(&out);
        assert_eq!(dst.file_name().unwrap(), "report_1.txt");
    }

    #[test]
    fn repeated_collisions_keep_counting_up_without_losing_anything() {
        let (_tmp, monitored) = workspace();
        let archive = monitored.join("archive");
        fs::create_dir_all(&archive).unwrap();
        fs::write(archive.join("note.txt"), "zero").unwrap();
        fs::write(archive.join("note_1.txt"), "one").unwrap();

        let src = seed(&monitored, "note.txt", "two");
        let out = process_file(&src, &ctx(&monitored, "archive", Action::Move, false)).unwrap();

        assert!(out.success, "{}", out.message);
        assert_eq!(
            fs::read_to_string(archive.join("note.txt")).unwrap(),
            "zero"
        );
        assert_eq!(
            fs::read_to_string(archive.join("note_1.txt")).unwrap(),
            "one"
        );
        assert_eq!(
            fs::read_to_string(archive.join("note_2.txt")).unwrap(),
            "two"
        );
    }

    #[test]
    fn a_filename_token_template_renames_the_file_it_lands_on() {
        let (_tmp, monitored) = workspace();
        let src = seed(&monitored, "report.txt", BODY);

        let out = process_file(
            &src,
            &ctx(
                &monitored,
                "archive/{FILENAME}_backup{EXT}",
                Action::Move,
                false,
            ),
        )
        .unwrap();

        assert!(out.success, "{}", out.message);
        let dst = recorded_destination(&out);
        // 1.5.0 resolved this correctly and then discarded it: `_atomic_claim_path`
        // was handed the *source* stem/extension, so the file landed as
        // `report.txt` and the `_backup` the user asked for vanished.
        assert_eq!(dst.file_name().unwrap(), "report_backup.txt");
        assert_eq!(fs::read_to_string(&dst).unwrap(), BODY);
        assert!(!src.exists());
    }

    #[test]
    fn a_filename_token_collision_suffixes_the_rendered_name() {
        let (_tmp, monitored) = workspace();
        let archive = monitored.join("archive");
        fs::create_dir_all(&archive).unwrap();
        let victim = seed(&archive, "report_backup.txt", "DO NOT TOUCH");
        let src = seed(&monitored, "report.txt", BODY);

        let out = process_file(
            &src,
            &ctx(
                &monitored,
                "archive/{FILENAME}_backup{EXT}",
                Action::Move,
                false,
            ),
        )
        .unwrap();

        assert!(out.success, "{}", out.message);
        assert_eq!(
            recorded_destination(&out).file_name().unwrap(),
            "report_backup_1.txt"
        );
        assert_eq!(fs::read_to_string(&victim).unwrap(), "DO NOT TOUCH");
        assert_eq!(
            fs::read_to_string(archive.join("report_backup_1.txt")).unwrap(),
            BODY
        );
    }

    #[test]
    fn success_action_taken_strings_are_the_literals_undo_matches() {
        let (_tmp, monitored) = workspace();

        let moved = seed(&monitored, "a.txt", BODY);
        let out = process_file(&moved, &ctx(&monitored, "archive", Action::Move, false)).unwrap();
        assert_eq!(out.record.action_taken, "MOVED");

        let copied = seed(&monitored, "b.txt", BODY);
        let out = process_file(&copied, &ctx(&monitored, "archive", Action::Copy, false)).unwrap();
        assert_eq!(out.record.action_taken, "COPIED");

        let trashed = seed(&monitored, "c.txt", BODY);
        let out =
            process_file(&trashed, &ctx(&monitored, "", Action::DeleteToTrash, true)).unwrap();
        assert_eq!(out.record.action_taken, "SIMULATED_DELETE_TO_TRASH");

        let nuked = seed(&monitored, "d.txt", BODY);
        let out = process_file(
            &nuked,
            &ctx(&monitored, "", Action::DeletePermanently, false),
        )
        .unwrap();
        assert_eq!(out.record.action_taken, "DELETED_PERMANENTLY");
    }

    // -- dry run ------------------------------------------------------------

    #[test]
    fn dry_run_creates_no_files_and_no_directories() {
        let (_tmp, monitored) = workspace();
        let src = seed(&monitored, "report.txt", BODY);

        let out = process_file(&src, &ctx(&monitored, "archive", Action::Move, true)).unwrap();

        assert!(out.success, "{}", out.message);
        assert_eq!(out.record.action_taken, "SIMULATED_MOVE");
        assert_eq!(out.record.status, Status::Success);
        assert!(
            out.message.starts_with("[DRY RUN] Would move:"),
            "{}",
            out.message
        );

        assert!(
            !monitored.join("archive").exists(),
            "a dry run must not create the destination directory"
        );
        let dst = recorded_destination(&out);
        assert!(
            !dst.exists(),
            "a dry run must not create the destination file"
        );
        assert!(!dst.parent().unwrap().exists());
        // Nothing at all changed in the monitored folder: just the source.
        assert_eq!(entry_count(&monitored), 1);
        assert_eq!(fs::read_to_string(&src).unwrap(), BODY);
    }

    #[test]
    fn dry_run_copy_says_would_copy_and_touches_nothing() {
        let (_tmp, monitored) = workspace();
        let src = seed(&monitored, "report.txt", BODY);

        let out = process_file(&src, &ctx(&monitored, "archive", Action::Copy, true)).unwrap();

        assert!(out.success);
        assert_eq!(out.record.action_taken, "SIMULATED_COPY");
        assert!(out.message.contains("Would copy"), "{}", out.message);
        assert!(!monitored.join("archive").exists());
        assert_eq!(entry_count(&monitored), 1);
    }

    #[test]
    fn dry_run_delete_to_trash_leaves_the_file_alone() {
        let (_tmp, monitored) = workspace();
        let src = seed(&monitored, "report.txt", BODY);

        let out = process_file(&src, &ctx(&monitored, "", Action::DeleteToTrash, true)).unwrap();

        assert!(out.success);
        assert_eq!(out.record.action_taken, "SIMULATED_DELETE_TO_TRASH");
        assert!(
            out.message.contains("Would send to trash"),
            "{}",
            out.message
        );
        assert!(src.exists(), "a dry run must not trash anything");
        assert_eq!(fs::read_to_string(&src).unwrap(), BODY);
        assert_eq!(entry_count(&monitored), 1);
    }

    #[test]
    fn dry_run_delete_permanently_leaves_the_file_alone() {
        let (_tmp, monitored) = workspace();
        let src = seed(&monitored, "report.txt", BODY);

        let out =
            process_file(&src, &ctx(&monitored, "", Action::DeletePermanently, true)).unwrap();

        assert!(out.success);
        assert_eq!(out.record.action_taken, "SIMULATED_DELETE_PERMANENTLY");
        assert!(out.message.contains("irreversible"), "{}", out.message);
        assert!(src.exists());
        assert_eq!(fs::read_to_string(&src).unwrap(), BODY);
    }

    #[test]
    fn dry_run_preview_shows_the_suffix_a_real_run_would_pick() {
        let (_tmp, monitored) = workspace();
        let archive = monitored.join("archive");
        fs::create_dir_all(&archive).unwrap();
        fs::write(archive.join("report.txt"), "already here").unwrap();
        let src = seed(&monitored, "report.txt", BODY);

        let out = process_file(&src, &ctx(&monitored, "archive", Action::Move, true)).unwrap();

        assert!(out.success);
        assert_eq!(
            recorded_destination(&out).file_name().unwrap(),
            "report_1.txt"
        );
        // …and still wrote nothing.
        assert_eq!(entry_count(&archive), 1);
        assert_eq!(
            fs::read_to_string(archive.join("report.txt")).unwrap(),
            "already here"
        );
    }

    // -- delete -------------------------------------------------------------

    #[test]
    fn delete_permanently_removes_the_file() {
        let (_tmp, monitored) = workspace();
        let src = seed(&monitored, "report.txt", BODY);

        let out =
            process_file(&src, &ctx(&monitored, "", Action::DeletePermanently, false)).unwrap();

        assert!(out.success, "{}", out.message);
        assert_eq!(out.record.action_taken, "DELETED_PERMANENTLY");
        assert!(out.record.destination_path.is_none());
        assert!(!src.exists());
        assert_eq!(entry_count(&monitored), 0);
    }

    // -- failure paths ------------------------------------------------------

    #[test]
    fn an_invalid_template_fails_the_outcome_without_erring_or_panicking() {
        let (_tmp, monitored) = workspace();
        let src = seed(&monitored, "report.txt", BODY);

        for (template, action, expected) in [
            ("../escape/{YYYY}", Action::Move, "MOVE_ERROR_TEMPLATE"),
            ("../escape/{YYYY}", Action::Copy, "COPY_ERROR_TEMPLATE"),
            ("{NOT_A_TOKEN}", Action::Move, "MOVE_ERROR_TEMPLATE"),
            ("archive;rm -rf", Action::Move, "MOVE_ERROR_TEMPLATE"),
        ] {
            let out = process_file(&src, &ctx(&monitored, template, action, false))
                .expect("a bad template is a logged failure, never an Err");
            assert!(
                !out.success,
                "template {template:?} should have been rejected"
            );
            assert_eq!(out.record.action_taken, expected);
            assert_eq!(out.record.status, Status::Failure);
            assert_eq!(out.record.severity, "ERROR");
            assert!(out.record.destination_path.is_none());
        }

        // Nothing was created and the source is untouched.
        assert_eq!(entry_count(&monitored), 1);
        assert_eq!(fs::read_to_string(&src).unwrap(), BODY);
    }

    #[test]
    fn a_missing_source_reports_not_found_and_creates_nothing() {
        let (_tmp, monitored) = workspace();
        let ghost = monitored.join("never-existed.txt");

        let out = process_file(&ghost, &ctx(&monitored, "archive", Action::Move, false)).unwrap();

        assert!(!out.success);
        assert_eq!(out.record.action_taken, "MOVE_ERROR_NOT_FOUND");
        assert_eq!(out.record.status, Status::Failure);
        assert!(out.message.contains("not found"), "{}", out.message);
        assert!(
            !monitored.join("archive").exists(),
            "a failed action must not leave a directory behind"
        );
        assert_eq!(entry_count(&monitored), 0);
    }

    #[test]
    fn a_missing_source_is_reported_for_every_action() {
        let (_tmp, monitored) = workspace();
        let ghost = monitored.join("never-existed.txt");

        for (action, expected) in [
            (Action::Copy, "COPY_ERROR_NOT_FOUND"),
            (Action::DeleteToTrash, "DELETE_TO_TRASH_ERROR_NOT_FOUND"),
            (
                Action::DeletePermanently,
                "DELETE_PERMANENTLY_ERROR_NOT_FOUND",
            ),
        ] {
            let out = process_file(&ghost, &ctx(&monitored, "archive", action, false)).unwrap();
            assert!(!out.success);
            assert_eq!(out.record.action_taken, expected);
        }

        // A dry run over a vanished file carries the SIMULATED_ prefix.
        let out = process_file(&ghost, &ctx(&monitored, "archive", Action::Move, true)).unwrap();
        assert_eq!(out.record.action_taken, "SIMULATED_MOVE_ERROR_NOT_FOUND");
    }

    #[test]
    fn a_directory_is_refused_rather_than_moved() {
        let (_tmp, monitored) = workspace();
        let dir = monitored.join("a-folder");
        fs::create_dir(&dir).unwrap();

        let out = process_file(&dir, &ctx(&monitored, "archive", Action::Move, false)).unwrap();

        assert!(!out.success);
        assert_eq!(out.record.action_taken, "MOVE_ERROR_GENERAL");
        assert!(dir.is_dir(), "the directory must be left alone");
    }

    // -- boundary -----------------------------------------------------------

    #[test]
    fn boundary_accepts_the_base_and_its_descendants() {
        let tmp = tempdir().unwrap();
        let base = tmp.path().join("archive");

        assert!(within_boundary(&base, &base));
        assert!(within_boundary(&base.join("file.txt"), &base));
        assert!(within_boundary(
            &base.join("2026").join("01").join("f.txt"),
            &base
        ));
        assert!(within_boundary(&base.join(".").join("file.txt"), &base));
    }

    #[test]
    fn boundary_rejects_an_escape() {
        let tmp = tempdir().unwrap();
        let base = tmp.path().join("archive");

        // The case the check exists for.
        assert!(!within_boundary(&base.join("..").join("evil.txt"), &base));
        assert!(!within_boundary(&base.join("..").join(".."), &base));
        // A plain sibling.
        assert!(!within_boundary(&tmp.path().join("elsewhere"), &base));
        // The string-prefix trap: `archive-old` is not inside `archive`.
        assert!(!within_boundary(
            &tmp.path().join("archive-old").join("f.txt"),
            &base
        ));
        // The parent is not inside its own child.
        assert!(!within_boundary(tmp.path(), &base));
    }

    // -- claim_unique_path --------------------------------------------------

    #[test]
    fn claim_takes_the_base_name_then_numbered_suffixes() {
        let tmp = tempdir().unwrap();
        let dir = tmp.path();

        let first = claim_unique_path(dir, "note", ".txt", 5).unwrap();
        assert_eq!(first.file_name().unwrap(), "note.txt");
        assert!(first.exists(), "the claim must actually reserve the name");
        assert_eq!(
            fs::metadata(&first).unwrap().len(),
            0,
            "the reservation is an empty placeholder"
        );

        let second = claim_unique_path(dir, "note", ".txt", 5).unwrap();
        assert_eq!(second.file_name().unwrap(), "note_1.txt");
        let third = claim_unique_path(dir, "note", ".txt", 5).unwrap();
        assert_eq!(third.file_name().unwrap(), "note_2.txt");
    }

    #[test]
    fn claim_never_hands_back_a_path_holding_someone_elses_content() {
        let tmp = tempdir().unwrap();
        let dir = tmp.path();
        fs::write(dir.join("note.txt"), "PRECIOUS").unwrap();

        let claimed = claim_unique_path(dir, "note", ".txt", 5).unwrap();

        assert_ne!(claimed, dir.join("note.txt"));
        assert_eq!(
            fs::read_to_string(dir.join("note.txt")).unwrap(),
            "PRECIOUS"
        );
    }

    #[test]
    fn claim_splits_multi_dot_names_the_way_python_does() {
        let tmp = tempdir().unwrap();
        let dir = tmp.path();
        let (stem, ext) = split_stem_ext(Path::new("backup.tar.gz"));
        assert_eq!((stem.as_str(), ext.as_str()), ("backup.tar", ".gz"));

        claim_unique_path(dir, &stem, &ext, 5).unwrap();
        let second = claim_unique_path(dir, &stem, &ext, 5).unwrap();
        assert_eq!(second.file_name().unwrap(), "backup.tar_1.gz");
    }

    #[test]
    fn claim_handles_extensionless_names() {
        let tmp = tempdir().unwrap();
        let dir = tmp.path();
        let (stem, ext) = split_stem_ext(Path::new("Makefile"));
        assert_eq!((stem.as_str(), ext.as_str()), ("Makefile", ""));

        assert_eq!(
            claim_unique_path(dir, &stem, &ext, 3)
                .unwrap()
                .file_name()
                .unwrap(),
            "Makefile"
        );
        assert_eq!(
            claim_unique_path(dir, &stem, &ext, 3)
                .unwrap()
                .file_name()
                .unwrap(),
            "Makefile_1"
        );
    }

    #[test]
    fn claim_falls_back_to_a_timestamp_when_every_suffix_is_taken() {
        let tmp = tempdir().unwrap();
        let dir = tmp.path();
        for name in ["note.txt", "note_1.txt", "note_2.txt"] {
            fs::write(dir.join(name), "taken").unwrap();
        }

        let claimed = claim_unique_path(dir, "note", ".txt", 2).unwrap();

        let name = claimed.file_name().unwrap().to_string_lossy().into_owned();
        assert!(name.starts_with("note_"), "{name}");
        assert!(name.ends_with(".txt"), "{name}");
        // note_YYYYmmdd_HHMMSS_ffffff.txt
        assert_eq!(name.len(), "note_".len() + 22 + ".txt".len(), "{name}");
        assert!(claimed.exists());
        // The occupied names kept their content.
        for existing in ["note.txt", "note_1.txt", "note_2.txt"] {
            assert_eq!(fs::read_to_string(dir.join(existing)).unwrap(), "taken");
        }
    }

    #[test]
    fn claim_reports_an_error_when_the_directory_is_missing() {
        let tmp = tempdir().unwrap();
        let err = claim_unique_path(&tmp.path().join("no-such-dir"), "a", ".txt", 3).unwrap_err();
        assert!(matches!(err, ActionError::Claim { .. }), "{err:?}");
        assert_eq!(Failure::classify(&err), Failure::NotFound);
    }

    // -- primitives ---------------------------------------------------------

    #[test]
    fn rename_no_clobber_refuses_an_occupied_destination() {
        // The regression test for the whole module: std::fs::rename would
        // happily replace `dst` here.
        let tmp = tempdir().unwrap();
        let src = seed(tmp.path(), "src.txt", "SOURCE");
        let dst = seed(tmp.path(), "dst.txt", "VICTIM");

        let err = rename_no_clobber(&src, &dst).expect_err("must not overwrite");

        assert!(is_already_exists(&err), "unexpected error kind: {err:?}");
        assert_eq!(fs::read_to_string(&dst).unwrap(), "VICTIM");
        assert_eq!(fs::read_to_string(&src).unwrap(), "SOURCE");
    }

    #[test]
    fn rename_no_clobber_moves_when_the_destination_is_free() {
        let tmp = tempdir().unwrap();
        let src = seed(tmp.path(), "src.txt", "SOURCE");
        let dst = tmp.path().join("dst.txt");

        rename_no_clobber(&src, &dst).unwrap();

        assert!(!src.exists());
        assert_eq!(fs::read_to_string(&dst).unwrap(), "SOURCE");
    }

    #[test]
    fn the_cross_device_fallback_copies_verifies_and_unlinks() {
        let tmp = tempdir().unwrap();
        let src = seed(tmp.path(), "src.bin", "0123456789");
        let dst = tmp.path().join("moved.bin");

        copy_verify_unlink(&src, &dst).unwrap();

        assert!(!src.exists());
        assert_eq!(fs::read_to_string(&dst).unwrap(), "0123456789");
    }

    #[test]
    fn the_cross_device_fallback_refuses_an_occupied_destination() {
        let tmp = tempdir().unwrap();
        let src = seed(tmp.path(), "src.bin", "SOURCE");
        let dst = seed(tmp.path(), "dst.bin", "VICTIM");

        let err = copy_verify_unlink(&src, &dst).expect_err("must not overwrite");

        assert!(matches!(err, ActionError::Io { .. }), "{err:?}");
        assert_eq!(fs::read_to_string(&dst).unwrap(), "VICTIM");
        assert_eq!(fs::read_to_string(&src).unwrap(), "SOURCE");
    }

    #[test]
    fn capitalize_matches_pythons_str_capitalize() {
        assert_eq!(capitalize("MOVED"), "Moved");
        assert_eq!(capitalize("COPIED"), "Copied");
        assert_eq!(capitalize(""), "");
    }
}
