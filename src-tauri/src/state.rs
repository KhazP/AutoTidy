//! Shared application state, owned by Tauri and handed to every command.

use autotidy_core::config::ConfigStore;
use autotidy_core::engine::EngineHandle;
use std::sync::Mutex;

pub struct AppState {
    pub store: ConfigStore,
    /// `None` until monitoring is started. 1.5.0 booted into a stopped state
    /// and required an explicit Start, which is preserved: an organiser that
    /// begins moving files the instant it launches is a bad surprise.
    pub engine: Mutex<Option<EngineHandle>>,
}

impl AppState {
    pub fn new(store: ConfigStore) -> Self {
        Self {
            store,
            engine: Mutex::new(None),
        }
    }
}
