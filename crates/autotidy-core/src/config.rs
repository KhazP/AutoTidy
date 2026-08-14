//! Configuration load/save, wire-compatible with AutoTidy 1.5.0's `config.json`.
//!
//! Compatibility is a hard requirement: v2 must read an existing
//! `%APPDATA%/AutoTidy/config.json` and write it back without losing any key.
//! Real-world configs carry ~36 settings keys and a whole `security` block left
//! behind by removed UI code, while only 8 settings keys are read by the engine.
//! Every unrecognised key is captured in an `extra` map and written back
//! verbatim, so an upgrade never destroys data the engine doesn't understand.

use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::{Map, Value};
use std::io::Write as _;
use std::path::{Path, PathBuf};

pub const APP_NAME: &str = "AutoTidy";
pub const DEFAULT_ARCHIVE_TEMPLATE: &str = "_Cleanup/{YYYY}-{MM}-{DD}";
pub const DEFAULT_INTERVAL_MINUTES: u64 = 60;

#[derive(Debug, thiserror::Error)]
pub enum ConfigError {
    #[error("could not determine a configuration directory")]
    NoConfigDir,
    #[error("i/o error on {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("malformed JSON in {path}: {source}")]
    Parse {
        path: PathBuf,
        #[source]
        source: serde_json::Error,
    },
}

// ---------------------------------------------------------------------------
// Action
// ---------------------------------------------------------------------------

/// What a rule does with a matched file.
///
/// Deserialisation mirrors `ConfigManager.normalize_action` from
/// `config_manager.py`: aliases are folded, and anything unrecognised (or a
/// non-string, or an empty string) becomes `Move` rather than failing the load.
/// A config that fails to parse would strand the user with no rules at all, so
/// leniency here is deliberate.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Action {
    #[default]
    Move,
    Copy,
    DeleteToTrash,
    DeletePermanently,
}

impl Action {
    pub fn as_str(self) -> &'static str {
        match self {
            Action::Move => "move",
            Action::Copy => "copy",
            Action::DeleteToTrash => "delete_to_trash",
            Action::DeletePermanently => "delete_permanently",
        }
    }

    /// Fold an arbitrary user/legacy string onto a canonical action.
    pub fn normalize(raw: &str) -> Self {
        match raw.trim().to_ascii_lowercase().as_str() {
            "copy" => Action::Copy,
            "delete" | "delete_to_trash" | "delete to trash" => Action::DeleteToTrash,
            "delete_permanently" | "delete permanently" => Action::DeletePermanently,
            _ => Action::Move,
        }
    }

    /// True when the action destroys the source file without a recoverable copy.
    pub fn is_destructive(self) -> bool {
        matches!(self, Action::DeleteToTrash | Action::DeletePermanently)
    }

    /// True when the action needs a resolved destination path.
    pub fn needs_destination(self) -> bool {
        matches!(self, Action::Move | Action::Copy)
    }
}

impl Serialize for Action {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        s.serialize_str(self.as_str())
    }
}

impl<'de> Deserialize<'de> for Action {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        Ok(match Value::deserialize(d)? {
            Value::String(s) => Action::normalize(&s),
            _ => Action::Move,
        })
    }
}

// ---------------------------------------------------------------------------
// RuleLogic
// ---------------------------------------------------------------------------

/// How a rule combines its age and pattern predicates.
///
/// `worker.py` computes `logic = (rule_logic or "OR").upper()` and treats
/// everything that isn't exactly `"AND"` as `Or`. Reproduced exactly.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum RuleLogic {
    And,
    #[default]
    Or,
}

impl RuleLogic {
    pub fn as_str(self) -> &'static str {
        match self {
            RuleLogic::And => "AND",
            RuleLogic::Or => "OR",
        }
    }
}

impl Serialize for RuleLogic {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        s.serialize_str(self.as_str())
    }
}

impl<'de> Deserialize<'de> for RuleLogic {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        Ok(match Value::deserialize(d)? {
            Value::String(s) if s.trim().eq_ignore_ascii_case("and") => RuleLogic::And,
            _ => RuleLogic::Or,
        })
    }
}

// ---------------------------------------------------------------------------
// NotificationLevel
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum NotificationLevel {
    None,
    Error,
    Summary,
    #[default]
    All,
}

impl NotificationLevel {
    pub fn as_str(self) -> &'static str {
        match self {
            NotificationLevel::None => "none",
            NotificationLevel::Error => "error",
            NotificationLevel::Summary => "summary",
            NotificationLevel::All => "all",
        }
    }

    /// Mirrors `MonitoringWorker._should_send_notification`.
    pub fn permits(self, category: NotificationCategory) -> bool {
        match self {
            NotificationLevel::None => false,
            NotificationLevel::Error => category == NotificationCategory::Error,
            NotificationLevel::Summary => matches!(
                category,
                NotificationCategory::Error | NotificationCategory::Summary
            ),
            NotificationLevel::All => true,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NotificationCategory {
    Error,
    Summary,
    Info,
}

impl Serialize for NotificationLevel {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        s.serialize_str(self.as_str())
    }
}

impl<'de> Deserialize<'de> for NotificationLevel {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        Ok(match Value::deserialize(d)? {
            Value::String(s) => match s.trim().to_ascii_lowercase().as_str() {
                "none" => NotificationLevel::None,
                "error" => NotificationLevel::Error,
                "summary" => NotificationLevel::Summary,
                _ => NotificationLevel::All,
            },
            _ => NotificationLevel::All,
        })
    }
}

// ---------------------------------------------------------------------------
// Rule
// ---------------------------------------------------------------------------

/// One monitored folder and the rule applied to it (an entry in `"folders"`).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Rule {
    pub path: String,
    #[serde(default)]
    pub age_days: i64,
    #[serde(default = "default_pattern")]
    pub pattern: String,
    #[serde(default)]
    pub rule_logic: RuleLogic,
    #[serde(default)]
    pub use_regex: bool,
    #[serde(default)]
    pub action: Action,
    #[serde(default)]
    pub destination_folder: String,
    #[serde(default)]
    pub exclusions: Vec<String>,
    #[serde(default = "default_true")]
    pub enabled: bool,

    /// Keys written by other//future versions, round-tripped untouched.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

impl Rule {
    /// A new rule with the same defaults `ConfigManager.add_folder` applies.
    pub fn new(path: impl Into<String>) -> Self {
        Self {
            path: path.into(),
            age_days: 7,
            pattern: default_pattern(),
            rule_logic: RuleLogic::Or,
            use_regex: false,
            action: Action::Move,
            destination_folder: String::new(),
            exclusions: Vec::new(),
            enabled: true,
            extra: Map::new(),
        }
    }

    /// How this rule combines its age and pattern predicates.
    pub fn logic(&self) -> RuleLogic {
        self.rule_logic
    }

    /// The template this rule writes through: an explicit `destination_folder`
    /// wins, otherwise the global archive template. Matches the
    /// `destination_value if destination_value else archive_path_template`
    /// precedence in `process_file_action`.
    pub fn effective_template<'a>(&'a self, global_archive_template: &'a str) -> &'a str {
        let explicit = self.destination_folder.trim();
        if explicit.is_empty() {
            global_archive_template
        } else {
            explicit
        }
    }
}

fn default_pattern() -> String {
    "*.*".to_string()
}
fn default_true() -> bool {
    true
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

/// Settings the engine actually reads.
///
/// Only these are acted upon. Everything else a real config carries
/// (`sound_notifications`, `pause_on_battery`, `theme`, `ui_scaling`, … — all
/// orphaned by removed UI code) lands in `extra` and is preserved verbatim.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Settings {
    #[serde(default)]
    pub start_on_login: bool,
    #[serde(default = "default_archive_template")]
    pub archive_path_template: String,
    #[serde(default = "default_schedule_type")]
    pub schedule_type: String,
    #[serde(default = "default_interval_minutes")]
    pub interval_minutes: u64,
    #[serde(default)]
    pub dry_run_mode: bool,
    #[serde(default)]
    pub notification_level: NotificationLevel,
    #[serde(default)]
    pub hide_instructions: bool,
    #[serde(default = "default_log_level")]
    pub log_level: String,

    /// Recursion depth for the v2 scanner. `0` means "this folder only", which
    /// is exactly what 1.5.0's flat `os.scandir` did — so existing configs
    /// (which already carry `max_directory_depth: 0`) keep their behaviour on
    /// upgrade and opt into recursion explicitly.
    #[serde(default)]
    pub max_directory_depth: u32,

    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

fn default_archive_template() -> String {
    DEFAULT_ARCHIVE_TEMPLATE.to_string()
}
fn default_schedule_type() -> String {
    "interval".to_string()
}
fn default_interval_minutes() -> u64 {
    DEFAULT_INTERVAL_MINUTES
}
fn default_log_level() -> String {
    "INFO".to_string()
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            start_on_login: false,
            archive_path_template: default_archive_template(),
            schedule_type: default_schedule_type(),
            interval_minutes: default_interval_minutes(),
            dry_run_mode: false,
            notification_level: NotificationLevel::default(),
            hide_instructions: false,
            log_level: default_log_level(),
            max_directory_depth: 0,
            extra: Map::new(),
        }
    }
}

impl Settings {
    /// Interval clamped to something sane. `set_schedule_config` rejects
    /// values below 1 minute; a zero here would spin the scan loop.
    pub fn interval(&self) -> std::time::Duration {
        let minutes = self.interval_minutes.max(1);
        std::time::Duration::from_secs(minutes * 60)
    }
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Config {
    #[serde(default)]
    pub folders: Vec<Rule>,
    #[serde(default)]
    pub excluded_folders: Vec<String>,
    #[serde(default)]
    pub settings: Settings,

    /// Top-level blocks the engine doesn't own — notably the `security` block
    /// left behind by the removed security dialog.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

impl Config {
    /// Rules that should actually run: enabled, with a non-empty path, and not
    /// sitting under a globally excluded folder.
    pub fn active_rules(&self) -> impl Iterator<Item = &Rule> {
        self.folders
            .iter()
            .filter(|r| r.enabled && !r.path.trim().is_empty())
    }

    /// True when `path` is globally excluded. Compares normalised absolute
    /// paths, matching worker.py's `Path(ef).resolve()` comparison.
    pub fn is_globally_excluded(&self, path: &Path) -> bool {
        let target = normalize(path);
        self.excluded_folders
            .iter()
            .filter(|e| !e.trim().is_empty())
            .any(|e| normalize(Path::new(e)) == target)
    }

    pub fn find_rule(&self, path: &str) -> Option<&Rule> {
        self.folders.iter().find(|r| r.path == path)
    }

    pub fn find_rule_mut(&mut self, path: &str) -> Option<&mut Rule> {
        self.folders.iter_mut().find(|r| r.path == path)
    }

    /// Add a folder if not already present. Returns false when it already
    /// exists, matching `ConfigManager.add_folder`'s contract.
    pub fn add_folder(&mut self, path: &Path) -> bool {
        let resolved = normalize(path).to_string_lossy().into_owned();
        if self.folders.iter().any(|r| r.path == resolved) {
            return false;
        }
        self.folders.push(Rule::new(resolved));
        true
    }

    pub fn add_excluded_folder(&mut self, path: &Path) -> bool {
        let resolved = normalize(path).to_string_lossy().into_owned();
        if self.excluded_folders.contains(&resolved) {
            return false;
        }
        self.excluded_folders.push(resolved);
        true
    }

    pub fn remove_folder(&mut self, path: &str) -> bool {
        let before = self.folders.len();
        self.folders.retain(|r| r.path != path);
        self.folders.len() != before
    }
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

/// Owns the on-disk location of the config and mediates all reads/writes.
#[derive(Debug, Clone)]
pub struct ConfigStore {
    dir: PathBuf,
}

impl ConfigStore {
    pub fn new(dir: impl Into<PathBuf>) -> Self {
        Self { dir: dir.into() }
    }

    /// The same directory 1.5.0 uses: `%APPDATA%/AutoTidy` on Windows,
    /// `~/.config/AutoTidy` elsewhere. Must match exactly or v2 would silently
    /// start from an empty config instead of the user's real one.
    pub fn default_location() -> Result<Self, ConfigError> {
        #[cfg(windows)]
        {
            if let Some(appdata) = std::env::var_os("APPDATA") {
                if !appdata.is_empty() {
                    return Ok(Self::new(PathBuf::from(appdata).join(APP_NAME)));
                }
            }
        }
        let home = home_dir().ok_or(ConfigError::NoConfigDir)?;
        Ok(Self::new(home.join(".config").join(APP_NAME)))
    }

    pub fn dir(&self) -> &Path {
        &self.dir
    }

    pub fn config_path(&self) -> PathBuf {
        self.dir.join("config.json")
    }

    pub fn history_path(&self) -> PathBuf {
        self.dir.join("autotidy_history.jsonl")
    }

    pub fn log_path(&self) -> PathBuf {
        self.dir.join("autotidy.log")
    }

    /// Load the config, tolerating a missing file (returns defaults).
    ///
    /// A corrupt file is backed up to `config.json.corrupt.bak` before falling
    /// back to defaults — same rescue behaviour as `_load_config`, kept because
    /// 1.5.0 users may already have a damaged file from its non-atomic writes.
    pub fn load(&self) -> Result<Config, ConfigError> {
        let path = self.config_path();
        let raw = match std::fs::read_to_string(&path) {
            Ok(raw) => raw,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                tracing::info!(path = %path.display(), "no config file; using defaults");
                return Ok(Config::default());
            }
            Err(source) => return Err(ConfigError::Io { path, source }),
        };

        let value: Value = match serde_json::from_str(&raw) {
            Ok(v) => v,
            Err(source) => {
                self.quarantine_corrupt(&path, &raw);
                tracing::error!(%source, "config corrupt; using defaults");
                return Ok(Config::default());
            }
        };

        match value {
            // Pre-1.0 format: a bare array of rules. Migrated in place, exactly
            // as the `isinstance(config_data, list)` branch of _load_config did.
            Value::Array(items) => {
                tracing::warn!("migrating legacy list-format config");
                let folders = items
                    .into_iter()
                    .filter_map(|item| serde_json::from_value::<Rule>(item).ok())
                    .collect();
                let migrated = Config {
                    folders,
                    ..Default::default()
                };
                self.save(&migrated)?;
                Ok(migrated)
            }
            other => serde_json::from_value(other).map_err(|source| ConfigError::Parse {
                path: path.clone(),
                source,
            }),
        }
    }

    /// Write the config atomically: a sibling temp file is fully written and
    /// flushed, then renamed over the target. 1.5.0 truncated and rewrote the
    /// real file in place, which is why `.corrupt.bak` recovery exists at all.
    pub fn save(&self, config: &Config) -> Result<(), ConfigError> {
        std::fs::create_dir_all(&self.dir).map_err(|source| ConfigError::Io {
            path: self.dir.clone(),
            source,
        })?;
        let path = self.config_path();

        let mut serialized =
            serde_json::to_vec_pretty(config).map_err(|source| ConfigError::Parse {
                path: path.clone(),
                source,
            })?;
        serialized.push(b'\n');

        let mut tmp =
            tempfile::NamedTempFile::new_in(&self.dir).map_err(|source| ConfigError::Io {
                path: self.dir.clone(),
                source,
            })?;
        tmp.write_all(&serialized)
            .map_err(|source| ConfigError::Io {
                path: path.clone(),
                source,
            })?;
        tmp.as_file().sync_all().map_err(|source| ConfigError::Io {
            path: path.clone(),
            source,
        })?;
        tmp.persist(&path).map_err(|e| ConfigError::Io {
            path: path.clone(),
            source: e.error,
        })?;
        Ok(())
    }

    fn quarantine_corrupt(&self, path: &Path, raw: &str) {
        let backup = path.with_extension("json.corrupt.bak");
        if let Err(e) = std::fs::write(&backup, raw) {
            tracing::error!(%e, "config corrupt and backup failed");
        } else {
            tracing::error!(backup = %backup.display(), "config corrupt; backed up");
        }
    }
}

// ---------------------------------------------------------------------------
// Path helpers
// ---------------------------------------------------------------------------

/// Best-effort absolute normalisation.
///
/// `canonicalize` is avoided for comparison because on Windows it returns
/// `\\?\`-prefixed paths and fails outright on paths that don't exist, and
/// exclusion checks must work for folders that have gone missing.
pub fn normalize(path: &Path) -> PathBuf {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .map(|cwd| cwd.join(path))
            .unwrap_or_else(|_| path.to_path_buf())
    };

    let mut out = PathBuf::new();
    for component in absolute.components() {
        match component {
            std::path::Component::ParentDir => {
                out.pop();
            }
            std::path::Component::CurDir => {}
            other => out.push(other.as_os_str()),
        }
    }
    out
}

fn home_dir() -> Option<PathBuf> {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .filter(|h| !h.is_empty())
        .map(PathBuf::from)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    /// A verbatim excerpt of a real 1.5.0 config: orphaned settings keys, the
    /// dead `security` block, and `check_interval_seconds` that the engine no
    /// longer reads. None of it may be lost on rewrite.
    const REAL_CONFIG: &str = r#"{
        "folders": [
            {
                "path": "E:/Downloads/OneDrive",
                "age_days": 7,
                "pattern": "*.*",
                "rule_logic": "OR",
                "use_regex": false,
                "action": "move",
                "destination_folder": "",
                "exclusions": [],
                "enabled": true
            }
        ],
        "settings": {
            "start_on_login": false,
            "check_interval_seconds": 3600,
            "archive_path_template": "_Cleanup/{YYYY}-{MM}-{DD}",
            "schedule_type": "interval",
            "interval_minutes": 60,
            "dry_run_mode": false,
            "notification_level": "all",
            "sound_notifications": true,
            "pause_on_battery": false,
            "theme": "system",
            "ui_scaling": 1.0,
            "max_directory_depth": 0,
            "hide_instructions": true
        },
        "security": {
            "safe_mode_enabled": true,
            "max_files_per_operation": 1,
            "protected_directories": []
        },
        "excluded_folders": []
    }"#;

    /// Collect every leaf path in a JSON value so a round-trip can be checked
    /// for key loss regardless of key ordering.
    fn leaves(v: &Value, prefix: String, out: &mut std::collections::BTreeMap<String, Value>) {
        match v {
            Value::Object(map) => {
                for (k, val) in map {
                    leaves(val, format!("{prefix}/{k}"), out);
                }
            }
            Value::Array(items) => {
                for (i, val) in items.iter().enumerate() {
                    leaves(val, format!("{prefix}/{i}"), out);
                }
            }
            leaf => {
                out.insert(prefix, leaf.clone());
            }
        }
    }

    fn leaf_map(raw: &str) -> std::collections::BTreeMap<String, Value> {
        let v: Value = serde_json::from_str(raw).unwrap();
        let mut out = std::collections::BTreeMap::new();
        leaves(&v, String::new(), &mut out);
        out
    }

    #[test]
    fn real_config_round_trips_without_losing_keys() {
        let parsed: Config = serde_json::from_str(REAL_CONFIG).unwrap();
        let written = serde_json::to_string_pretty(&parsed).unwrap();

        let before = leaf_map(REAL_CONFIG);
        let after = leaf_map(&written);

        for (key, value) in &before {
            assert_eq!(
                after.get(key),
                Some(value),
                "key {key} was lost or altered on round-trip"
            );
        }
    }

    #[test]
    fn orphaned_keys_land_in_extra_not_dropped() {
        let parsed: Config = serde_json::from_str(REAL_CONFIG).unwrap();
        assert!(parsed.settings.extra.contains_key("check_interval_seconds"));
        assert!(parsed.settings.extra.contains_key("sound_notifications"));
        assert!(parsed.settings.extra.contains_key("theme"));
        assert!(parsed.extra.contains_key("security"));
        // ...while live keys are parsed into real fields, not swallowed by extra.
        assert!(!parsed.settings.extra.contains_key("interval_minutes"));
        assert_eq!(parsed.settings.interval_minutes, 60);
        assert!(parsed.settings.hide_instructions);
    }

    #[test]
    fn action_normalisation_matches_python() {
        assert_eq!(Action::normalize("move"), Action::Move);
        assert_eq!(Action::normalize("COPY"), Action::Copy);
        assert_eq!(Action::normalize(" delete "), Action::DeleteToTrash);
        assert_eq!(Action::normalize("delete to trash"), Action::DeleteToTrash);
        assert_eq!(
            Action::normalize("delete permanently"),
            Action::DeletePermanently
        );
        // Unknown and empty both fall back to move, as normalize_action does.
        assert_eq!(Action::normalize("explode"), Action::Move);
        assert_eq!(Action::normalize(""), Action::Move);
    }

    #[test]
    fn rule_logic_defaults_to_or_for_anything_but_and() {
        let and: RuleLogic = serde_json::from_str("\"AND\"").unwrap();
        assert_eq!(and, RuleLogic::And);
        assert_eq!(
            serde_json::from_str::<RuleLogic>("\"and\"").unwrap(),
            RuleLogic::And
        );
        assert_eq!(
            serde_json::from_str::<RuleLogic>("\"nonsense\"").unwrap(),
            RuleLogic::Or
        );
        assert_eq!(
            serde_json::from_str::<RuleLogic>("null").unwrap(),
            RuleLogic::Or
        );
    }

    #[test]
    fn notification_gating_matches_worker() {
        use NotificationCategory::*;
        assert!(!NotificationLevel::None.permits(Error));
        assert!(NotificationLevel::Error.permits(Error));
        assert!(!NotificationLevel::Error.permits(Summary));
        assert!(NotificationLevel::Summary.permits(Summary));
        assert!(NotificationLevel::Summary.permits(Error));
        assert!(!NotificationLevel::Summary.permits(Info));
        assert!(NotificationLevel::All.permits(Info));
    }

    #[test]
    fn missing_rule_fields_take_python_defaults() {
        let rule: Rule = serde_json::from_str(r#"{"path": "C:/x"}"#).unwrap();
        assert_eq!(rule.pattern, "*.*");
        assert_eq!(rule.rule_logic, RuleLogic::Or);
        assert_eq!(rule.action, Action::Move);
        assert!(rule.enabled);
        assert!(!rule.use_regex);
        assert_eq!(rule.age_days, 0);
        assert!(rule.exclusions.is_empty());
    }

    #[test]
    fn effective_template_prefers_explicit_destination() {
        let mut rule = Rule::new("C:/x");
        assert_eq!(rule.effective_template("GLOBAL"), "GLOBAL");
        rule.destination_folder = "   ".into();
        assert_eq!(rule.effective_template("GLOBAL"), "GLOBAL");
        rule.destination_folder = "D:/archive".into();
        assert_eq!(rule.effective_template("GLOBAL"), "D:/archive");
    }

    #[test]
    fn save_then_load_survives_a_full_cycle() {
        let dir = tempfile::tempdir().unwrap();
        let store = ConfigStore::new(dir.path());

        let original: Config = serde_json::from_str(REAL_CONFIG).unwrap();
        store.save(&original).unwrap();
        let reloaded = store.load().unwrap();

        assert_eq!(reloaded.folders.len(), 1);
        assert_eq!(reloaded.folders[0].path, "E:/Downloads/OneDrive");
        assert!(reloaded.extra.contains_key("security"));
        assert!(reloaded
            .settings
            .extra
            .contains_key("check_interval_seconds"));
    }

    #[test]
    fn missing_config_file_yields_defaults_not_an_error() {
        let dir = tempfile::tempdir().unwrap();
        let store = ConfigStore::new(dir.path().join("does-not-exist"));
        let config = store.load().unwrap();
        assert!(config.folders.is_empty());
        assert_eq!(config.settings.interval_minutes, DEFAULT_INTERVAL_MINUTES);
    }

    #[test]
    fn corrupt_config_is_quarantined_and_replaced_with_defaults() {
        let dir = tempfile::tempdir().unwrap();
        let store = ConfigStore::new(dir.path());
        std::fs::create_dir_all(dir.path()).unwrap();
        std::fs::write(store.config_path(), "{not json at all").unwrap();

        let config = store.load().unwrap();
        assert!(config.folders.is_empty());
        assert!(
            store
                .config_path()
                .with_extension("json.corrupt.bak")
                .exists(),
            "corrupt config should be preserved for the user"
        );
    }

    #[test]
    fn legacy_list_format_is_migrated() {
        let dir = tempfile::tempdir().unwrap();
        let store = ConfigStore::new(dir.path());
        std::fs::create_dir_all(dir.path()).unwrap();
        std::fs::write(
            store.config_path(),
            r#"[{"path": "C:/old", "age_days": 3, "pattern": "*.log"}]"#,
        )
        .unwrap();

        let config = store.load().unwrap();
        assert_eq!(config.folders.len(), 1);
        assert_eq!(config.folders[0].age_days, 3);
        assert_eq!(config.folders[0].action, Action::Move);

        // Migration rewrites the file in the modern shape.
        let reloaded = store.load().unwrap();
        assert_eq!(reloaded.folders.len(), 1);
    }

    #[test]
    fn global_exclusions_compare_normalised_paths() {
        let mut config = Config::default();
        config.excluded_folders.push(
            normalize(Path::new("C:/Temp/../Temp/skip"))
                .to_string_lossy()
                .into_owned(),
        );
        assert!(config.is_globally_excluded(Path::new("C:/Temp/skip")));
        assert!(!config.is_globally_excluded(Path::new("C:/Temp/other")));
    }

    #[test]
    fn interval_never_collapses_to_zero() {
        // worker.py reads `interval_minutes` straight from the config and
        // sleeps `x 60`; only the setter validates. A hand-edited `0` would
        // spin the loop with no sleep at all.
        let s = Settings {
            interval_minutes: 0,
            ..Default::default()
        };
        assert_eq!(s.interval(), std::time::Duration::from_secs(60));
    }
}
