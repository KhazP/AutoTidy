// Suppress the console window on Windows release builds; the app lives in the
// tray and has no terminal output for a user to read.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    autotidy_app_lib::run()
}
