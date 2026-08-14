//! System tray icon and menu.
//!
//! Reproduces the 1.5.0 tray from `main.py`: Show/Hide Config, a separator,
//! Start/Stop Monitoring, View Action History / Undo, a separator, Quit.
//! Left-click toggles the window; right-click opens the menu.

use autotidy_core::EngineStatus;
use std::time::Duration;
use tauri::menu::{Menu, MenuEvent, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, Wry};

use crate::state::AppState;
use crate::{APP_NAME, MAIN_WINDOW, NAVIGATE_EVENT, TRAY_ID};

const ITEM_SHOW: &str = "show";
const ITEM_START: &str = "start";
const ITEM_STOP: &str = "stop";
const ITEM_HISTORY: &str = "history";
const ITEM_QUIT: &str = "quit";

/// 1.5.0's staged shutdown: 2s, then a "please wait" notification, then 8s
/// more. Ten seconds total for an in-flight file operation to land.
const QUIT_FIRST_WAIT: Duration = Duration::from_secs(2);
const QUIT_SECOND_WAIT: Duration = Duration::from_secs(8);

/// The menu, kept so `sync_status` can reach its items later. `TrayIcon` has no
/// menu getter, and re-building the menu on every status change would make the
/// menu flicker shut while the user is reading it.
struct TrayMenu(Menu<Wry>);

/// Build the tray icon and wire its menu.
pub fn setup(app: &AppHandle) -> tauri::Result<()> {
    // Order is 1.5.0's, exactly: show, separator, start, stop, history,
    // separator, quit.
    let show = MenuItem::with_id(app, ITEM_SHOW, "Show/Hide Config", true, None::<&str>)?;
    let start = MenuItem::with_id(app, ITEM_START, "Start Monitoring", true, None::<&str>)?;
    let stop = MenuItem::with_id(app, ITEM_STOP, "Stop Monitoring", false, None::<&str>)?;
    let history = MenuItem::with_id(
        app,
        ITEM_HISTORY,
        "View Action History / Undo",
        true,
        None::<&str>,
    )?;
    let quit = MenuItem::with_id(app, ITEM_QUIT, "Quit", true, None::<&str>)?;

    let menu = Menu::with_items(
        app,
        &[
            &show,
            &PredefinedMenuItem::separator(app)?,
            &start,
            &stop,
            &history,
            &PredefinedMenuItem::separator(app)?,
            &quit,
        ],
    )?;

    // `tauri.conf.json` declares the tray, so Tauri has already created it with
    // the bundled icon. Building one here would leave two icons in the tray.
    let tray = match app.tray_by_id(TRAY_ID) {
        Some(tray) => tray,
        None => {
            let mut builder = TrayIconBuilder::with_id(TRAY_ID);
            if let Some(icon) = app.default_window_icon() {
                builder = builder.icon(icon.clone());
            }
            builder.build(app)?
        }
    };

    tray.set_menu(Some(menu.clone()))?;
    tray.on_menu_event(on_menu_event);
    tray.on_tray_icon_event(|tray, event| {
        // Left click, on release — the equivalent of Qt's
        // `ActivationReason.Trigger`. Right click is the menu, which the tray
        // opens itself.
        if let TrayIconEvent::Click {
            button: MouseButton::Left,
            button_state: MouseButtonState::Up,
            ..
        } = event
        {
            toggle_window(tray.app_handle());
        }
    });

    app.manage(TrayMenu(menu));
    sync_status(
        app,
        crate::commands::current_status(&app.state::<AppState>()),
    );
    Ok(())
}

fn on_menu_event(app: &AppHandle, event: MenuEvent) {
    match event.id().as_ref() {
        ITEM_SHOW => toggle_window(app),
        ITEM_START => {
            let state = app.state::<AppState>();
            if let Err(err) = crate::commands::start_engine(app, &state) {
                tracing::error!(%err, "tray could not start monitoring");
            }
            sync_status(app, crate::commands::current_status(&state));
        }
        ITEM_STOP => {
            let state = app.state::<AppState>();
            if let Err(err) = crate::commands::stop_engine(&state, crate::SHUTDOWN_GRACE) {
                tracing::error!(%err, "tray could not stop monitoring");
            }
            sync_status(app, crate::commands::current_status(&state));
        }
        ITEM_HISTORY => {
            show_window(app);
            // The frontend routes on this; if it is not listening yet the user
            // still gets the window, which is the half that matters.
            let _ = app.emit(NAVIGATE_EVENT, "history");
        }
        ITEM_QUIT => quit(app),
        other => tracing::warn!(id = other, "unhandled tray menu item"),
    }
}

/// Reflect engine state in the tray tooltip and the Start/Stop item's enabled
/// state, so the menu can't offer "Start" while already running.
pub fn sync_status(app: &AppHandle, status: EngineStatus) {
    let handle = app.clone();
    // Menu mutation must happen on the main thread. This is called from the
    // engine's event sink, which is a background thread, and the menu setters
    // would block it until the event loop caught up — including while the main
    // thread is itself blocked in `quit` waiting for that same engine.
    let dispatch = app.run_on_main_thread(move || {
        if let Some(menu) = handle.try_state::<TrayMenu>() {
            set_enabled(&menu.0, ITEM_START, status == EngineStatus::Stopped);
            set_enabled(
                &menu.0,
                ITEM_STOP,
                matches!(status, EngineStatus::Idle | EngineStatus::Scanning),
            );
        }
        if let Some(tray) = handle.tray_by_id(TRAY_ID) {
            let _ = tray.set_tooltip(Some(tooltip(status)));
        }
    });
    if let Err(err) = dispatch {
        tracing::warn!(%err, "could not sync the tray with the engine status");
    }
}

fn set_enabled(menu: &Menu<Wry>, id: &str, enabled: bool) {
    if let Some(item) = menu.get(id).and_then(|kind| kind.as_menuitem().cloned()) {
        let _ = item.set_enabled(enabled);
    }
}

/// 1.5.0's tooltip was a flat "AutoTidy is running", which said nothing once
/// the app was in the tray for a week. The status is the useful part.
fn tooltip(status: EngineStatus) -> String {
    let state = match status {
        EngineStatus::Stopped => "stopped",
        EngineStatus::Idle => "monitoring",
        EngineStatus::Scanning => "scanning",
        EngineStatus::Stopping => "stopping",
    };
    format!("{APP_NAME} — {state}")
}

/// Show or hide the main window.
pub fn toggle_window(app: &AppHandle) {
    let Some(window) = app.get_webview_window(MAIN_WINDOW) else {
        return;
    };
    if window.is_visible().unwrap_or(false) {
        let _ = window.hide();
    } else {
        show_window(app);
    }
}

/// Bring the window up and to the front — the `show` / `raise_` /
/// `activateWindow` trio 1.5.0's `toggle_window` used.
pub fn show_window(app: &AppHandle) {
    let Some(window) = app.get_webview_window(MAIN_WINDOW) else {
        return;
    };
    // A window minimised to the taskbar is "visible" as far as the platform is
    // concerned, so unminimise before showing or the click appears to do
    // nothing.
    let _ = window.unminimize();
    let _ = window.show();
    let _ = window.set_focus();
}

/// Shut down cleanly.
///
/// 1.5.0 gave the worker 2s, then showed a "Shutting down, please wait..."
/// tray notification and waited 8s more, for 10s total. Preserved: an
/// in-flight file move must be allowed to finish rather than be killed.
pub fn quit(app: &AppHandle) {
    tracing::info!("quit requested; shutting down");
    stop_for_quit(app);
    app.exit(0);
}

fn stop_for_quit(app: &AppHandle) {
    use tauri_plugin_notification::NotificationExt;

    let state = app.state::<AppState>();
    let mut guard = match state.engine.lock() {
        Ok(guard) => guard,
        // A panicked engine thread must not stop us from exiting.
        Err(poisoned) => poisoned.into_inner(),
    };
    let Some(engine) = guard.as_mut() else {
        return;
    };

    if engine.stop(QUIT_FIRST_WAIT) {
        *guard = None;
        return;
    }

    let _ = app
        .notification()
        .builder()
        .title(APP_NAME)
        .body("Shutting down, please wait...")
        .show();

    if engine.stop(QUIT_SECOND_WAIT) {
        *guard = None;
    } else {
        tracing::warn!("worker thread did not stop gracefully within 10s");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_staged_shutdown_budget_is_the_1_5_0_ten_seconds() {
        assert_eq!(QUIT_FIRST_WAIT + QUIT_SECOND_WAIT, Duration::from_secs(10));
        assert_eq!(QUIT_FIRST_WAIT, Duration::from_secs(2));
    }

    #[test]
    fn the_tooltip_names_the_engine_state() {
        assert_eq!(tooltip(EngineStatus::Stopped), "AutoTidy — stopped");
        assert_eq!(tooltip(EngineStatus::Idle), "AutoTidy — monitoring");
        assert_eq!(tooltip(EngineStatus::Scanning), "AutoTidy — scanning");
        assert_eq!(tooltip(EngineStatus::Stopping), "AutoTidy — stopping");
    }
}
