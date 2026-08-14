//! Archive-path template validation and expansion.
//!
//! Ported from `validate_archive_template` / the `apply_template` closure in
//! `utils.py`. Public signatures here are a fixed contract — `action.rs`
//! depends on them.

use std::path::{Path, PathBuf};

/// The only placeholders a template may contain.
pub const ALLOWED_PLACEHOLDERS: &[&str] = &[
    "YYYY",
    "MM",
    "DD",
    "FILENAME",
    "EXT",
    "ORIGINAL_FOLDER_NAME",
];

/// Characters rejected outright to keep templates from carrying shell syntax.
pub const DANGEROUS_CHARS: &[char] = &[';', '|', '&', '`'];

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum TemplateError {
    #[error("template must not contain '..' path traversal components")]
    Traversal,
    #[error(
        "unknown placeholder {{{0}}}; allowed: YYYY, MM, DD, FILENAME, EXT, ORIGINAL_FOLDER_NAME"
    )]
    UnknownPlaceholder(String),
    #[error("template contains dangerous character: '{0}'")]
    DangerousChar(char),
}

/// Values substituted into a template for one specific file.
#[derive(Debug, Clone)]
pub struct Placeholders {
    pub year: String,
    pub month: String,
    pub day: String,
    /// File stem — no extension.
    pub filename: String,
    /// Extension including the leading dot, or empty.
    pub ext: String,
    pub original_folder_name: String,
}

impl Placeholders {
    /// Build from a file path plus the folder being monitored, stamping today's
    /// date. Matches how `process_file_action` derives its replacements.
    pub fn for_file(
        file: &Path,
        monitored_folder: &Path,
        now: chrono::DateTime<chrono::Local>,
    ) -> Self {
        let name = file
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_default();
        let (stem, ext) = split_stem_ext(&name);

        Self {
            year: now.format("%Y").to_string(),
            month: now.format("%m").to_string(),
            day: now.format("%d").to_string(),
            filename: stem.to_string(),
            ext: ext.to_string(),
            original_folder_name: monitored_folder
                .file_name()
                .map(|n| n.to_string_lossy().into_owned())
                .unwrap_or_default(),
        }
    }
}

/// Split a bare file name the way `pathlib.Path.stem` / `.suffix` do: at the
/// last dot, but only when that dot is neither the first nor the last
/// character. `.bashrc` is all stem, `archive.tar.gz` splits to
/// (`archive.tar`, `.gz`).
///
/// `Path::file_stem` differs on trailing dots (`foo.` → stem `foo`, extension
/// `Some("")`), so the split is done by hand rather than delegated.
fn split_stem_ext(name: &str) -> (&str, &str) {
    match name.rfind('.') {
        // Python: `0 < i < len(name) - 1`.
        Some(i) if i > 0 && i + 1 < name.len() => (&name[..i], &name[i..]),
        _ => (name, ""),
    }
}

/// Every `{...}` group in the template, matching Python's
/// `re.findall(r'\{([^}]+)\}', template)`.
///
/// The body is greedy and may itself contain `{`, so `{a{b}` yields `a{b`. An
/// empty `{}` is not a placeholder at all (`[^}]+` needs one character), and
/// scanning resumes one character on, exactly as the regex engine would.
fn find_placeholders(template: &str) -> Vec<&str> {
    let mut found = Vec::new();
    let mut rest = template;

    while let Some(open) = rest.find('{') {
        // `{` and `}` are single-byte, so these slices stay on char boundaries.
        let after = &rest[open + 1..];
        match after.find('}') {
            Some(0) => rest = after,
            Some(close) => {
                found.push(&after[..close]);
                rest = &after[close + 1..];
            }
            None => break,
        }
    }
    found
}

/// Reject traversal, unknown placeholders, and shell metacharacters.
/// An empty template is valid (it means "no override").
pub fn validate(template: &str) -> Result<(), TemplateError> {
    if template.is_empty() {
        return Ok(());
    }

    // Backslashes are normalised first so `..\evil` is caught on every platform,
    // mirroring `Path(template.replace("\\", "/")).parts`.
    if template
        .replace('\\', "/")
        .split('/')
        .any(|component| component == "..")
    {
        return Err(TemplateError::Traversal);
    }

    for name in find_placeholders(template) {
        if !ALLOWED_PLACEHOLDERS.contains(&name) {
            return Err(TemplateError::UnknownPlaceholder(name.to_string()));
        }
    }

    for &ch in DANGEROUS_CHARS {
        if template.contains(ch) {
            return Err(TemplateError::DangerousChar(ch));
        }
    }

    Ok(())
}

/// Substitute every placeholder. Unknown placeholders are left intact —
/// `validate` is the gate that rejects them, and expansion must not silently
/// mangle a template that skipped validation.
pub fn expand(template: &str, values: &Placeholders) -> String {
    // Substitution order matches the Python dict's insertion order. It is
    // observable: a value inserted by an earlier token is still scanned by the
    // later ones, so a file literally named `x{EXT}` would have that token
    // replaced. Preserved deliberately rather than "fixed".
    let substitutions: [(&str, &str); 6] = [
        ("{YYYY}", &values.year),
        ("{MM}", &values.month),
        ("{DD}", &values.day),
        ("{FILENAME}", &values.filename),
        ("{EXT}", &values.ext),
        ("{ORIGINAL_FOLDER_NAME}", &values.original_folder_name),
    ];

    let mut out = template.to_string();
    for (token, value) in substitutions {
        if out.contains(token) {
            out = out.replace(token, value);
        }
    }
    out
}

/// True when the template names the file itself, meaning it resolves to a file
/// path rather than a directory. Drives whether the caller appends the original
/// filename to the resolved path.
pub fn has_filename_tokens(template: &str) -> bool {
    template.contains("{FILENAME}") || template.contains("{EXT}")
}

/// Expand environment variables (`%VAR%` on Windows, `$VAR` elsewhere) and a
/// leading `~`, mirroring `os.path.expandvars` + `os.path.expanduser`.
pub fn expand_env(input: &str) -> String {
    let expanded = expand_vars_with(input, cfg!(windows), &|name| std::env::var(name).ok());
    expand_user_with(&expanded, home_dir().as_deref())
}

fn is_var_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '_'
}

/// The variable-substitution half of `expand_env`, with the platform switch and
/// the environment itself injected so both dialects stay testable everywhere.
///
/// Unset variables are left verbatim — `os.path.expandvars` does the same, and
/// silently blanking them would collapse `%NOPE%/archive` to `/archive`, i.e.
/// the drive root.
fn expand_vars_with<F>(input: &str, windows_style: bool, lookup: &F) -> String
where
    F: Fn(&str) -> Option<String>,
{
    let mut out = String::with_capacity(input.len());
    let mut rest = input;

    loop {
        let marker = rest.find(|c| c == '$' || (windows_style && c == '%'));
        let Some(idx) = marker else {
            out.push_str(rest);
            return out;
        };
        out.push_str(&rest[..idx]);

        // `$` and `%` are single-byte, so `idx + 1` is a valid boundary.
        let is_percent = rest.as_bytes()[idx] == b'%';
        let body = &rest[idx + 1..];

        if is_percent {
            // `%%` collapses to one `%`.
            if let Some(tail) = body.strip_prefix('%') {
                out.push('%');
                rest = tail;
                continue;
            }
            match body.find('%') {
                Some(end) => {
                    let name = &body[..end];
                    match lookup(name) {
                        Some(value) => out.push_str(&value),
                        None => {
                            out.push('%');
                            out.push_str(name);
                            out.push('%');
                        }
                    }
                    rest = &body[end + 1..];
                }
                // Unterminated `%foo` is left alone.
                None => {
                    out.push('%');
                    out.push_str(body);
                    return out;
                }
            }
        } else if windows_style && body.starts_with('$') {
            // ntpath collapses `$$`; posixpath leaves it, and falls out of the
            // empty-name branch below.
            out.push('$');
            rest = &body[1..];
        } else if let Some(inner) = body.strip_prefix('{') {
            match inner.find('}') {
                Some(end) => {
                    let name = &inner[..end];
                    match lookup(name) {
                        Some(value) => out.push_str(&value),
                        None => {
                            out.push_str("${");
                            out.push_str(name);
                            out.push('}');
                        }
                    }
                    rest = &inner[end + 1..];
                }
                None => {
                    out.push_str("${");
                    out.push_str(inner);
                    return out;
                }
            }
        } else {
            let end = body.find(|c: char| !is_var_char(c)).unwrap_or(body.len());
            let name = &body[..end];
            if name.is_empty() {
                // A bare `$` (or `$$` on posix): emit it and move on.
                out.push('$');
            } else {
                match lookup(name) {
                    Some(value) => out.push_str(&value),
                    None => {
                        out.push('$');
                        out.push_str(name);
                    }
                }
            }
            rest = &body[end..];
        }
    }
}

/// The `~` half of `expand_env`, with the home directory injected.
///
/// Only a leading `~` that stands alone or is followed by a separator expands —
/// `~other` names a different user's home, which neither platform can resolve
/// reliably, so it is left untouched.
fn expand_user_with(input: &str, home: Option<&str>) -> String {
    let Some(tail) = input.strip_prefix('~') else {
        return input.to_string();
    };
    if !(tail.is_empty() || tail.starts_with('/') || tail.starts_with('\\')) {
        return input.to_string();
    }
    let Some(home) = home else {
        return input.to_string();
    };

    let mut out = home.trim_end_matches(['/', '\\']).to_string();
    out.push_str(tail);
    out
}

/// Same lookup order as `config::ConfigStore` uses for the config directory.
fn home_dir() -> Option<String> {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .filter(|h| !h.is_empty())
        .map(|h| h.to_string_lossy().into_owned())
}

/// Resolve a template to an absolute path. Relative templates resolve against
/// `monitored_folder`, matching `(monitored_folder_path / candidate).resolve()`.
pub fn resolve(template: &str, monitored_folder: &Path, values: &Placeholders) -> PathBuf {
    let expanded = expand_env(&expand(template, values));
    let candidate = Path::new(&expanded);

    // `normalize` absolutises against the cwd and folds `.` / `..` lexically,
    // without touching the filesystem — `resolve()` on a path that does not
    // exist yet has to keep working.
    if candidate.is_absolute() {
        crate::config::normalize(candidate)
    } else {
        crate::config::normalize(&monitored_folder.join(candidate))
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn values() -> Placeholders {
        Placeholders {
            year: "2026".into(),
            month: "02".into(),
            day: "09".into(),
            filename: "report".into(),
            ext: ".txt".into(),
            original_folder_name: "Downloads".into(),
        }
    }

    /// An absolute path that is genuinely absolute on the host platform —
    /// `/x` has a root but no prefix on Windows, so it is *not* absolute there
    /// (same as `PureWindowsPath('/x').is_absolute()`).
    fn abs(tail: &str) -> PathBuf {
        if cfg!(windows) {
            PathBuf::from(format!("C:\\{}", tail.replace('/', "\\")))
        } else {
            PathBuf::from(format!("/{tail}"))
        }
    }

    // -- validate -----------------------------------------------------------

    #[test]
    fn empty_template_is_valid() {
        assert_eq!(validate(""), Ok(()));
    }

    #[test]
    fn default_template_is_valid() {
        assert_eq!(validate(crate::config::DEFAULT_ARCHIVE_TEMPLATE), Ok(()));
    }

    #[test]
    fn parent_dir_components_are_rejected() {
        for template in [
            "../escape",
            "..",
            "_Cleanup/../../etc",
            "a/../b",
            "_Cleanup/{YYYY}/..",
            // Backslashes are normalised first, so Windows separators are caught
            // even when the tests run on a unix host.
            "..\\escape",
            "_Cleanup\\..\\..\\Windows",
        ] {
            assert_eq!(
                validate(template),
                Err(TemplateError::Traversal),
                "{template} should be rejected"
            );
        }
    }

    #[test]
    fn dots_inside_a_name_are_not_traversal() {
        assert_eq!(validate("..hidden"), Ok(()));
        assert_eq!(validate("a..b"), Ok(()));
        assert_eq!(validate("archive.../{YYYY}"), Ok(()));
        assert_eq!(validate("./{YYYY}"), Ok(()));
    }

    #[test]
    fn unknown_placeholder_is_rejected() {
        assert_eq!(
            validate("_Cleanup/{NOPE}"),
            Err(TemplateError::UnknownPlaceholder("NOPE".into()))
        );
        // Case matters — the Python compares against an exact-case set.
        assert_eq!(
            validate("{yyyy}"),
            Err(TemplateError::UnknownPlaceholder("yyyy".into()))
        );
        // The greedy body may swallow an inner brace, as `[^}]+` does.
        assert_eq!(
            validate("{a{b}"),
            Err(TemplateError::UnknownPlaceholder("a{b".into()))
        );
    }

    #[test]
    fn all_allowed_placeholders_validate() {
        for name in ALLOWED_PLACEHOLDERS {
            assert_eq!(validate(&format!("_Cleanup/{{{name}}}")), Ok(()));
        }
        assert_eq!(
            validate("{YYYY}/{MM}/{DD}/{ORIGINAL_FOLDER_NAME}/{FILENAME}{EXT}"),
            Ok(())
        );
    }

    #[test]
    fn empty_braces_and_unterminated_braces_are_not_placeholders() {
        // `[^}]+` requires a body, so `{}` is just text.
        assert_eq!(validate("{}"), Ok(()));
        assert_eq!(validate("{}{YYYY}"), Ok(()));
        assert_eq!(validate("{unterminated"), Ok(()));
    }

    #[test]
    fn each_dangerous_char_is_rejected() {
        for &ch in DANGEROUS_CHARS {
            let template = format!("_Cleanup/a{ch}b");
            assert_eq!(
                validate(&template),
                Err(TemplateError::DangerousChar(ch)),
                "{template} should be rejected"
            );
        }
    }

    #[test]
    fn traversal_outranks_the_other_checks() {
        // Python tests traversal first; a template with both reports traversal.
        assert_eq!(validate("../{NOPE};"), Err(TemplateError::Traversal));
        // ...and an unknown placeholder outranks a dangerous character.
        assert_eq!(
            validate("{NOPE};"),
            Err(TemplateError::UnknownPlaceholder("NOPE".into()))
        );
    }

    // -- expand -------------------------------------------------------------

    #[test]
    fn every_placeholder_expands() {
        let out = expand(
            "{ORIGINAL_FOLDER_NAME}/{YYYY}-{MM}-{DD}/{FILENAME}{EXT}",
            &values(),
        );
        assert_eq!(out, "Downloads/2026-02-09/report.txt");
    }

    #[test]
    fn repeated_placeholders_all_expand() {
        assert_eq!(expand("{YYYY}/{YYYY}", &values()), "2026/2026");
    }

    #[test]
    fn unknown_placeholders_survive_expansion() {
        // `validate` is the gate; `expand` must not mangle what it doesn't know.
        assert_eq!(expand("{NOPE}/{YYYY}", &values()), "{NOPE}/2026");
        assert_eq!(expand("{yyyy}", &values()), "{yyyy}");
    }

    #[test]
    fn expansion_leaves_a_template_without_placeholders_alone() {
        assert_eq!(expand("_Cleanup/plain", &values()), "_Cleanup/plain");
        assert_eq!(expand("", &values()), "");
    }

    #[test]
    fn ext_keeps_its_leading_dot() {
        assert_eq!(expand("archive/{EXT}", &values()), "archive/.txt");
    }

    // -- has_filename_tokens ------------------------------------------------

    #[test]
    fn filename_tokens_are_detected() {
        assert!(has_filename_tokens("{FILENAME}{EXT}"));
        assert!(has_filename_tokens("_Cleanup/{YYYY}/{FILENAME}"));
        assert!(has_filename_tokens("_Cleanup/x{EXT}"));
    }

    #[test]
    fn directory_only_templates_have_no_filename_tokens() {
        assert!(!has_filename_tokens("_Cleanup/{YYYY}-{MM}-{DD}"));
        assert!(!has_filename_tokens(""));
        assert!(!has_filename_tokens("{ORIGINAL_FOLDER_NAME}"));
    }

    // -- Placeholders::for_file ---------------------------------------------

    fn stamped() -> chrono::DateTime<chrono::Local> {
        use chrono::TimeZone;
        chrono::Local
            .with_ymd_and_hms(2026, 2, 9, 13, 45, 0)
            .unwrap()
    }

    #[test]
    fn for_file_zero_pads_the_date_parts() {
        let p = Placeholders::for_file(
            Path::new("C:/Downloads/report.txt"),
            Path::new("C:/Downloads"),
            stamped(),
        );
        assert_eq!(p.year, "2026");
        assert_eq!(p.month, "02");
        assert_eq!(p.day, "09");
    }

    #[test]
    fn for_file_splits_stem_and_extension_like_pathlib() {
        let cases = [
            ("report.txt", "report", ".txt"),
            ("archive.tar.gz", "archive.tar", ".gz"),
            ("no_extension", "no_extension", ""),
            // A leading dot is part of the stem, never an extension.
            (".bashrc", ".bashrc", ""),
            // A trailing dot leaves an empty suffix, so the whole name is stem.
            ("trailing.", "trailing.", ""),
        ];
        for (name, stem, ext) in cases {
            let p = Placeholders::for_file(
                Path::new(&format!("/monitored/{name}")),
                Path::new("/monitored"),
                stamped(),
            );
            assert_eq!(p.filename, stem, "stem of {name}");
            assert_eq!(p.ext, ext, "ext of {name}");
        }
    }

    #[test]
    fn for_file_takes_the_monitored_folders_last_component() {
        let p = Placeholders::for_file(
            Path::new("/home/me/Downloads/report.txt"),
            Path::new("/home/me/Downloads"),
            stamped(),
        );
        assert_eq!(p.original_folder_name, "Downloads");

        // A trailing separator must not blank the name out.
        let p = Placeholders::for_file(
            Path::new("/home/me/Downloads/report.txt"),
            Path::new("/home/me/Downloads/"),
            stamped(),
        );
        assert_eq!(p.original_folder_name, "Downloads");
    }

    // -- expand_env ---------------------------------------------------------

    /// Serialises the two tests that mutate the process environment; the rest
    /// inject their lookup and stay independent.
    static ENV_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

    fn fake_env(name: &str) -> Option<String> {
        match name {
            "AUTOTIDY_HOME" => Some("D:/Archive".to_string()),
            "EMPTYVAR" => Some(String::new()),
            _ => None,
        }
    }

    #[test]
    fn windows_percent_variables_expand() {
        assert_eq!(
            expand_vars_with("%AUTOTIDY_HOME%/{YYYY}", true, &fake_env),
            "D:/Archive/{YYYY}"
        );
        assert_eq!(expand_vars_with("a%EMPTYVAR%b", true, &fake_env), "ab");
        assert_eq!(expand_vars_with("100%% sure", true, &fake_env), "100% sure");
    }

    #[test]
    fn unset_variables_are_left_verbatim() {
        // Blanking these would turn `%NOPE%/archive` into a drive-root write.
        assert_eq!(
            expand_vars_with("%NOPE%/archive", true, &fake_env),
            "%NOPE%/archive"
        );
        assert_eq!(
            expand_vars_with("$NOPE/archive", false, &fake_env),
            "$NOPE/archive"
        );
        assert_eq!(
            expand_vars_with("${NOPE}/archive", false, &fake_env),
            "${NOPE}/archive"
        );
        // An unterminated `%` is not a variable at all.
        assert_eq!(expand_vars_with("50% off", true, &fake_env), "50% off");
    }

    #[test]
    fn posix_dollar_variables_expand() {
        assert_eq!(
            expand_vars_with("$AUTOTIDY_HOME/sub", false, &fake_env),
            "D:/Archive/sub"
        );
        assert_eq!(
            expand_vars_with("${AUTOTIDY_HOME}sub", false, &fake_env),
            "D:/Archivesub"
        );
        assert_eq!(expand_vars_with("${}", false, &fake_env), "${}");
    }

    #[test]
    fn percent_syntax_is_inert_off_windows() {
        assert_eq!(
            expand_vars_with("%AUTOTIDY_HOME%/x", false, &fake_env),
            "%AUTOTIDY_HOME%/x"
        );
    }

    #[test]
    fn a_bare_dollar_is_harmless() {
        assert_eq!(expand_vars_with("a$ b", false, &fake_env), "a$ b");
        assert_eq!(expand_vars_with("$", false, &fake_env), "$");
        // ntpath collapses `$$`, posixpath keeps it.
        assert_eq!(expand_vars_with("$$", true, &fake_env), "$");
        assert_eq!(expand_vars_with("$$", false, &fake_env), "$$");
    }

    #[test]
    fn expand_env_reads_the_real_environment() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        std::env::set_var("AUTOTIDY_TEMPLATE_TEST_VAR", "expanded");
        let marker = if cfg!(windows) {
            "%AUTOTIDY_TEMPLATE_TEST_VAR%"
        } else {
            "$AUTOTIDY_TEMPLATE_TEST_VAR"
        };
        assert_eq!(expand_env(&format!("{marker}/tail")), "expanded/tail");
        std::env::remove_var("AUTOTIDY_TEMPLATE_TEST_VAR");
    }

    #[test]
    fn a_leading_tilde_becomes_the_home_directory() {
        assert_eq!(
            expand_user_with("~/Archive", Some("C:/Users/me")),
            "C:/Users/me/Archive"
        );
        assert_eq!(expand_user_with("~", Some("C:/Users/me")), "C:/Users/me");
        assert_eq!(
            expand_user_with("~\\Archive", Some("C:/Users/me")),
            "C:/Users/me\\Archive"
        );
        // A trailing separator on the home value must not double up.
        assert_eq!(
            expand_user_with("~/Archive", Some("C:/Users/me/")),
            "C:/Users/me/Archive"
        );
    }

    #[test]
    fn a_tilde_elsewhere_or_naming_another_user_is_left_alone() {
        assert_eq!(
            expand_user_with("~other/x", Some("C:/Users/me")),
            "~other/x"
        );
        assert_eq!(
            expand_user_with("archive/~/x", Some("C:/Users/me")),
            "archive/~/x"
        );
        assert_eq!(expand_user_with("~/x", None), "~/x");
    }

    // -- resolve ------------------------------------------------------------

    #[test]
    fn a_relative_template_resolves_against_the_monitored_folder() {
        let monitored = abs("Users/me/Downloads");
        let resolved = resolve("_Cleanup/{YYYY}-{MM}", &monitored, &values());
        assert_eq!(resolved, monitored.join("_Cleanup").join("2026-02"));
    }

    #[test]
    fn an_absolute_template_ignores_the_monitored_folder() {
        let monitored = abs("Users/me/Downloads");
        let template = abs("Archive/{YYYY}");
        let resolved = resolve(&template.to_string_lossy(), &monitored, &values());
        assert_eq!(resolved, abs("Archive/2026"));
        assert!(!resolved.starts_with(&monitored));
    }

    #[test]
    fn resolution_folds_away_dot_and_parent_components() {
        let monitored = abs("Users/me/Downloads");
        // `..` never survives `validate`, but `resolve` is also reachable from
        // callers that skipped it, so the folding must still happen.
        assert_eq!(
            resolve("../Archive", &monitored, &values()),
            abs("Users/me/Archive")
        );
        assert_eq!(
            resolve("./_Cleanup/./{YYYY}", &monitored, &values()),
            monitored.join("_Cleanup").join("2026")
        );
    }

    #[test]
    fn a_filename_template_resolves_to_a_file_path() {
        let monitored = abs("Users/me/Downloads");
        let resolved = resolve("_Cleanup/{FILENAME}{EXT}", &monitored, &values());
        assert_eq!(resolved, monitored.join("_Cleanup").join("report.txt"));
        assert!(has_filename_tokens("_Cleanup/{FILENAME}{EXT}"));
    }

    #[test]
    fn an_empty_template_resolves_to_the_monitored_folder() {
        let monitored = abs("Users/me/Downloads");
        assert_eq!(resolve("", &monitored, &values()), monitored);
    }

    #[test]
    fn resolution_expands_environment_variables_too() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let monitored = abs("Users/me/Downloads");
        let home = abs("Archive");
        std::env::set_var(
            "AUTOTIDY_TEMPLATE_TEST_DEST",
            home.to_string_lossy().as_ref(),
        );
        let marker = if cfg!(windows) {
            "%AUTOTIDY_TEMPLATE_TEST_DEST%"
        } else {
            "$AUTOTIDY_TEMPLATE_TEST_DEST"
        };
        assert_eq!(
            resolve(&format!("{marker}/{{YYYY}}"), &monitored, &values()),
            abs("Archive/2026")
        );
        std::env::remove_var("AUTOTIDY_TEMPLATE_TEST_DEST");
    }
}
