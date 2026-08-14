//! AutoTidy engine.
//!
//! Deliberately free of GUI dependencies: this crate is driven by the headless
//! CLI (for differential testing against the Python 1.5.0 engine) and by the
//! Tauri shell alike. Nothing here may depend on `tauri`.

pub mod action;
pub mod config;
pub mod engine;
pub mod history;
pub mod rule;
pub mod scan;
pub mod template;
pub mod undo;
pub mod watch;

pub use config::{
    Action, Config, ConfigError, ConfigStore, NotificationCategory, NotificationLevel, Rule,
    RuleLogic, Settings, APP_NAME, DEFAULT_ARCHIVE_TEMPLATE,
};
pub use engine::{EngineEvent, EngineHandle, EngineStatus, EventSink, LogLevel, ScheduleMode};
pub use history::{HistoryLog, HistoryRecord, Status};
pub use scan::{scan_all, ScanOptions, ScanReport};
