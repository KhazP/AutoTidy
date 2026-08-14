//! Windows platform integration: autostart and the Explorer context menu.
//!
//! Replaces `startup_manager.py` and `windows_context_menu.py`.

use std::path::{Path, PathBuf};

/// The two Explorer verbs 1.5.0 registered.
pub const VERB_ADD: &str = "AutoTidyAddTo";
pub const VERB_EXCLUDE: &str = "AutoTidyExcludeFrom";

/// The text Explorer shows for each verb, unchanged from 1.5.0.
pub const LABEL_ADD: &str = "Add to AutoTidy";
pub const LABEL_EXCLUDE: &str = "Exclude from AutoTidy";

/// The CLI flag each verb passes back to the app.
pub const FLAG_ADD: &str = "--add-folder";
pub const FLAG_EXCLUDE: &str = "--exclude-folder";

/// `Directory\shell`, as spelled inside a `Software\Classes` subtree.
///
/// `HKEY_CLASSES_ROOT` is not a hive. It is a merged view of
/// `HKLM\Software\Classes` (machine-wide) with `HKCU\Software\Classes`
/// (per-user) laid over the top. So this one path serves both:
///
/// * under `CURRENT_USER` it is where 2.0 registers its verbs — per-user, no
///   elevation, and it shadows HKCR for this user exactly as the machine
///   entries did;
/// * under `LOCAL_MACHINE` it is where 1.5.0's landed. A write to a HKCR key
///   that HKCU does not already hold is redirected to the machine half, which
///   is precisely why `windows_context_menu.py` needed administrator rights.
///
/// The hive is therefore the whole difference between "ours" and "1.x's", and
/// the paths are identical *by definition* rather than by coincidence.
const SHELL_ROOT: &str = r"Software\Classes\Directory\shell";

#[derive(Debug, thiserror::Error)]
pub enum PlatformError {
    #[error("registry error: {0}")]
    Registry(String),
    #[error("could not determine the executable path: {0}")]
    ExePath(String),
    /// The operation needs rights the current token does not carry. Kept apart
    /// from [`PlatformError::Registry`] so the UI can say "run as
    /// administrator" instead of showing the user the words "access denied".
    #[error("administrator rights are required")]
    NeedsElevation,
    #[error("not supported on this platform")]
    Unsupported,
}

/// One Explorer verb that AutoTidy 1.5.0 left in the machine-wide registry.
///
/// Carries the registered command line as well as the key path: the whole point
/// of showing this to the user is that they can see it names a `python.exe` and
/// a `main.py` that this install replaced, and decide for themselves.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StaleVerb {
    /// The key name, e.g. `AutoTidyAddTo`.
    pub verb: String,
    /// The full key path, for checking against `regedit`.
    pub key: String,
    /// The caption Explorer draws, when the key still has one.
    pub label: Option<String>,
    /// The command line the entry runs. `None` for a verb whose `command`
    /// subkey is missing or empty — still a menu item, just an inert one.
    pub command: Option<String>,
}

/// What AutoTidy 1.5.0 left behind under `HKEY_CLASSES_ROOT`.
///
/// Empty is the normal answer: it is only non-empty on a machine that once ran
/// 1.5.0 *and* had the context menu registered from an elevated session.
///
/// This is a pure read. It opens keys with `RegOpenKeyEx` and never
/// `RegCreateKeyEx` — note that `windows_registry`'s `Key::create` is the
/// latter, so a probe written with it would report `AutoTidyAddTo` as present
/// on every machine, having just created it.
pub fn stale_v1_context_menu() -> Vec<StaleVerb> {
    #[cfg(windows)]
    {
        use windows_registry::LOCAL_MACHINE;
        // The machine half, deliberately not the merged `CLASSES_ROOT` view:
        // 2.0 registers verbs with these same two names under
        // `HKCU\Software\Classes`, and HKCR shows those through. Probing the
        // merged view would report a false positive for every user who has
        // simply switched 2.0's own context menu on.
        win::stale_verbs_under(LOCAL_MACHINE, "HKEY_LOCAL_MACHINE", SHELL_ROOT)
    }
    #[cfg(not(windows))]
    {
        Vec::new()
    }
}

/// Delete both 1.5.0 verbs, and their `command` subkeys with them.
///
/// Fails with [`PlatformError::NeedsElevation`] when the process cannot write
/// to the machine half of HKCR, which is the usual case: 2.0 installs per-user
/// and unelevated. Verbs that are already gone are not an error — the caller
/// asked for a state, and that state is what we are in.
pub fn remove_stale_v1_context_menu() -> Result<(), PlatformError> {
    #[cfg(windows)]
    {
        use windows_registry::LOCAL_MACHINE;
        win::remove_stale_verbs_under(LOCAL_MACHINE, SHELL_ROOT)
    }
    #[cfg(not(windows))]
    {
        Err(PlatformError::Unsupported)
    }
}

/// Whether this process holds the rights [`remove_stale_v1_context_menu`] needs.
///
/// Measured by asking for the access rather than by asking the token: opening
/// `HKLM\Software\Classes` for write. That key grants write to Administrators
/// and read to everyone else, and UAC hands even a member of Administrators a
/// filtered token until they elevate — so it succeeds exactly when AutoTidy is
/// running elevated. Where it and a token check would disagree (a machine whose
/// ACLs have been changed), this is the answer that matters, because it is the
/// question the UI is really asking: *will the Remove button work?*
///
/// `RegOpenKeyEx`, never `RegCreateKeyEx`. A probe that created the thing it
/// measures would be no probe at all.
pub fn is_elevated() -> bool {
    #[cfg(windows)]
    {
        win::can_write_machine_classes()
    }
    #[cfg(not(windows))]
    {
        false
    }
}

/// Path to the running executable, which is what the registry entries invoke.
pub fn exe_path() -> Result<PathBuf, PlatformError> {
    std::env::current_exe().map_err(|e| PlatformError::ExePath(e.to_string()))
}

/// The registry command value for one verb.
///
/// `%V` rather than `%1`: it is the folder Explorer's *background* context menu
/// was opened in as well as the one that was clicked, and it survives paths
/// with spaces. Same choice `windows_context_menu.py` made.
pub fn command_value(exe: &Path, flag: &str) -> String {
    format!("\"{}\" {} \"%V\"", exe.display(), flag)
}

/// Register or remove the Explorer folder context-menu entries.
///
/// Writes under `HKEY_CURRENT_USER\Software\Classes\Directory\shell`, **not**
/// `HKEY_CLASSES_ROOT`. 1.5.0 used HKCR, which requires elevation and made the
/// feature unusable without running as administrator; the per-user hive needs
/// no elevation and shadows HKCR for the current user anyway.
pub fn set_context_menu(enabled: bool) -> Result<(), PlatformError> {
    #[cfg(windows)]
    {
        win::set_context_menu_under(SHELL_ROOT, enabled)
    }
    #[cfg(not(windows))]
    {
        let _ = enabled;
        Err(PlatformError::Unsupported)
    }
}

pub fn context_menu_registered() -> bool {
    #[cfg(windows)]
    {
        win::context_menu_registered_under(SHELL_ROOT)
    }
    #[cfg(not(windows))]
    {
        false
    }
}

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

#[cfg(windows)]
mod win {
    use super::*;
    use windows_registry::{Key, CURRENT_USER, LOCAL_MACHINE};

    /// `windows_registry::Error` is a re-export of a type the crate does not
    /// name publicly, so it is taken by `Display` rather than by type.
    fn registry_err(err: impl std::fmt::Display) -> PlatformError {
        PlatformError::Registry(err.to_string())
    }

    /// `ERROR_ACCESS_DENIED` (5), as the `HRESULT` the registry crate wraps it
    /// in. This is the one failure the UI has to word differently.
    pub(super) const HRESULT_ACCESS_DENIED: i32 = 0x8007_0005_u32 as i32;

    /// `ERROR_FILE_NOT_FOUND` (2). Present for the tests, which pin down that
    /// a missing key is *not* mistaken for a permission problem.
    #[cfg(test)]
    pub(super) const HRESULT_FILE_NOT_FOUND: i32 = 0x8007_0002_u32 as i32;

    /// Sort a registry failure into "you need to elevate" and everything else.
    ///
    /// Takes the code and the message rather than the error, because the error
    /// type is not nameable outside `windows_registry` — the caller pulls both
    /// off a value whose type is only inferred. Only `ERROR_ACCESS_DENIED`
    /// becomes [`PlatformError::NeedsElevation`]: a corrupt key, a key open in
    /// another process, or a hive that will not load are real failures, and
    /// telling the user to run as administrator would send them off to do
    /// something that cannot help.
    pub(super) fn classify(code: i32, message: String) -> PlatformError {
        if code == HRESULT_ACCESS_DENIED {
            PlatformError::NeedsElevation
        } else {
            PlatformError::Registry(message)
        }
    }

    /// Read whichever of the two verbs exist under `hive`\\`root`.
    ///
    /// `hive` and `hive_label` are parameters so the tests can plant fixtures
    /// under a scratch key of their own instead of touching the real
    /// machine-wide shell entries — which they could not create unelevated
    /// anyway, and must never delete.
    pub(super) fn stale_verbs_under(hive: &Key, hive_label: &str, root: &str) -> Vec<StaleVerb> {
        [VERB_ADD, VERB_EXCLUDE]
            .into_iter()
            .filter_map(|verb| read_verb(hive, hive_label, root, verb))
            .collect()
    }

    /// The key's own presence is the signal, not the command: a verb whose
    /// `command` subkey went missing still draws a menu item, and leaving it
    /// behind is exactly the outcome this feature exists to prevent.
    fn read_verb(hive: &Key, hive_label: &str, root: &str, verb: &str) -> Option<StaleVerb> {
        let verb_path = format!(r"{root}\{verb}");
        let key = hive.open(&verb_path).ok()?;
        let non_empty = |value: String| {
            if value.trim().is_empty() {
                None
            } else {
                Some(value)
            }
        };
        Some(StaleVerb {
            verb: verb.to_string(),
            key: format!(r"{hive_label}\{verb_path}"),
            label: key.get_string("").ok().and_then(non_empty),
            command: hive
                .open(format!(r"{verb_path}\command"))
                .and_then(|command| command.get_string(""))
                .ok()
                .and_then(non_empty),
        })
    }

    /// `RegDeleteTree` takes the `command` subkey down with the verb, so there
    /// is no order to get wrong and no half-removed state to leave behind.
    pub(super) fn remove_stale_verbs_under(hive: &Key, root: &str) -> Result<(), PlatformError> {
        for verb in [VERB_ADD, VERB_EXCLUDE] {
            let verb_path = format!(r"{root}\{verb}");
            if let Err(err) = hive.open(&verb_path) {
                // A read denied by an ACL we would also fail to delete through
                // is reported rather than swallowed as "already clean"; every
                // other read failure means the verb is not there, which is the
                // state the caller asked for.
                if err.code().0 == HRESULT_ACCESS_DENIED {
                    return Err(PlatformError::NeedsElevation);
                }
                continue;
            }
            hive.remove_tree(&verb_path)
                .map_err(|err| classify(err.code().0, err.to_string()))?;
        }
        Ok(())
    }

    /// See [`super::is_elevated`]. `Software\Classes` always exists, so a
    /// failure here is about rights rather than about the key.
    pub(super) fn can_write_machine_classes() -> bool {
        LOCAL_MACHINE
            .options()
            .write()
            .open(r"Software\Classes")
            .is_ok()
    }

    /// Write both verbs under `root`, or remove both.
    ///
    /// `root` is a parameter purely so the tests can exercise the real registry
    /// round-trip under a scratch key instead of the user's live shell entries.
    pub(super) fn set_context_menu_under(root: &str, enabled: bool) -> Result<(), PlatformError> {
        if !enabled {
            remove_verb(root, VERB_ADD)?;
            remove_verb(root, VERB_EXCLUDE)?;
            return Ok(());
        }

        let exe = exe_path()?;
        write_verb(root, VERB_ADD, LABEL_ADD, &command_value(&exe, FLAG_ADD))?;
        write_verb(
            root,
            VERB_EXCLUDE,
            LABEL_EXCLUDE,
            &command_value(&exe, FLAG_EXCLUDE),
        )?;
        Ok(())
    }

    /// A verb is two keys: the verb itself, whose default value is the menu
    /// text, and a `command` subkey whose default value is the command line.
    fn write_verb(root: &str, verb: &str, label: &str, command: &str) -> Result<(), PlatformError> {
        let verb_path = format!(r"{root}\{verb}");
        let key = CURRENT_USER.create(&verb_path).map_err(registry_err)?;
        // The empty name is the key's default value, which is what Explorer
        // reads for the menu caption.
        key.set_string("", label).map_err(registry_err)?;

        let command_key = CURRENT_USER
            .create(format!(r"{verb_path}\command"))
            .map_err(registry_err)?;
        command_key.set_string("", command).map_err(registry_err)?;
        Ok(())
    }

    /// Removing a verb that was never registered is a success, not an error —
    /// the caller asked for "not registered" and that is the state we are in.
    fn remove_verb(root: &str, verb: &str) -> Result<(), PlatformError> {
        let verb_path = format!(r"{root}\{verb}");
        if CURRENT_USER.open(&verb_path).is_err() {
            return Ok(());
        }
        CURRENT_USER.remove_tree(&verb_path).map_err(registry_err)
    }

    /// Probing reads the `command` value rather than merely testing for the
    /// key: an empty shell of a key left behind by a failed write would
    /// otherwise report as registered while doing nothing in Explorer.
    pub(super) fn context_menu_registered_under(root: &str) -> bool {
        CURRENT_USER
            .open(format!(r"{root}\{VERB_ADD}\command"))
            .and_then(|key| key.get_string(""))
            .map(|value| !value.trim().is_empty())
            .unwrap_or(false)
    }
}

// ---------------------------------------------------------------------------
// Autostart
// ---------------------------------------------------------------------------

/// Enable or disable "start on login".
///
/// `tauri-plugin-autostart` writes the same
/// `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` value under the same
/// `AutoTidy` name that `startup_manager.set_autostart` did, so an install
/// upgraded from 1.5.0 keeps a single entry rather than gaining a second one.
#[cfg(desktop)]
pub fn set_autostart(app: &tauri::AppHandle, enabled: bool) -> Result<(), PlatformError> {
    use tauri_plugin_autostart::ManagerExt;

    let manager = app.autolaunch();
    let result = if enabled {
        manager.enable()
    } else {
        manager.disable()
    };
    result.map_err(|e| PlatformError::Registry(e.to_string()))
}

#[cfg(desktop)]
pub fn autostart_enabled(app: &tauri::AppHandle) -> bool {
    use tauri_plugin_autostart::ManagerExt;

    app.autolaunch().is_enabled().unwrap_or(false)
}

#[cfg(not(desktop))]
pub fn set_autostart(_app: &tauri::AppHandle, _enabled: bool) -> Result<(), PlatformError> {
    Err(PlatformError::Unsupported)
}

#[cfg(not(desktop))]
pub fn autostart_enabled(_app: &tauri::AppHandle) -> bool {
    false
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn command_quotes_the_exe_and_passes_the_folder_placeholder() {
        let exe = Path::new(r"C:\Program Files\AutoTidy\AutoTidy.exe");
        assert_eq!(
            command_value(exe, FLAG_ADD),
            r#""C:\Program Files\AutoTidy\AutoTidy.exe" --add-folder "%V""#
        );
        assert_eq!(
            command_value(exe, FLAG_EXCLUDE),
            r#""C:\Program Files\AutoTidy\AutoTidy.exe" --exclude-folder "%V""#
        );
    }

    /// The verbs must never be written under `Directory\shell` outside the real
    /// registration path — a test that got this wrong would edit the user's
    /// live Explorer menu.
    ///
    /// `Software\Classes` is the load-bearing prefix in both directions: it is
    /// what makes the path per-user under `CURRENT_USER`, and what makes the
    /// probe read the machine half of HKCR — rather than the merged view,
    /// which would show 2.0's own verbs back to it — under `LOCAL_MACHINE`.
    #[test]
    fn shell_root_is_the_per_user_hive_not_hkcr() {
        assert_eq!(SHELL_ROOT, r"Software\Classes\Directory\shell");
        assert!(!SHELL_ROOT.starts_with("Directory"));
        assert!(SHELL_ROOT.starts_with(r"Software\Classes\"));
    }

    /// A unique scratch path under `HKCU\Software`, with no shared parent, so
    /// that removing it removes every trace of the test.
    #[cfg(windows)]
    fn scratch_key(name: &str) -> String {
        format!(
            r"Software\AutoTidyTest-{name}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or_default()
        )
    }

    /// Plant what 1.5.0 actually left: a caption on the verb, and a command
    /// line naming a `python.exe` and a `main.py`.
    #[cfg(windows)]
    fn plant_v1_verb(root: &str, verb: &str, label: &str, command: &str) {
        use windows_registry::CURRENT_USER;

        let key = CURRENT_USER.create(format!(r"{root}\{verb}")).unwrap();
        key.set_string("", label).unwrap();
        let command_key = CURRENT_USER
            .create(format!(r"{root}\{verb}\command"))
            .unwrap();
        command_key.set_string("", command).unwrap();
    }

    #[cfg(windows)]
    const V1_ADD_COMMAND: &str =
        r#""C:\Python312\python.exe" "C:\Program Files\AutoTidy\main.py" --add-folder "%V""#;
    #[cfg(windows)]
    const V1_EXCLUDE_COMMAND: &str =
        r#""C:\Python312\python.exe" "C:\Program Files\AutoTidy\main.py" --exclude-folder "%V""#;

    /// Detection has to be a read. `windows_registry::Key::create` is
    /// `RegCreateKeyEx`, so a probe written with it would answer "yes, both
    /// verbs are registered" on a clean machine — having registered them.
    #[cfg(windows)]
    #[test]
    fn probing_creates_nothing() {
        use windows_registry::CURRENT_USER;

        let scratch = scratch_key("probe");
        let root = format!(r"{scratch}\shell");

        assert!(win::stale_verbs_under(CURRENT_USER, "HKEY_CURRENT_USER", &root).is_empty());
        assert!(
            CURRENT_USER.open(&scratch).is_err(),
            "probing must not bring the key it looked for into existence"
        );
    }

    /// Full round-trip under a scratch key: plant 1.5.0's entries, see them
    /// reported with their command lines, remove them, see them gone.
    #[cfg(windows)]
    #[test]
    fn detects_then_removes_the_v1_verbs() {
        use windows_registry::CURRENT_USER;

        let scratch = scratch_key("stale");
        let root = format!(r"{scratch}\shell");
        let probe = || win::stale_verbs_under(CURRENT_USER, "HKEY_CURRENT_USER", &root);

        plant_v1_verb(&root, VERB_ADD, LABEL_ADD, V1_ADD_COMMAND);
        plant_v1_verb(&root, VERB_EXCLUDE, LABEL_EXCLUDE, V1_EXCLUDE_COMMAND);

        let found = probe();
        assert_eq!(found.len(), 2);

        assert_eq!(found[0].verb, VERB_ADD);
        assert_eq!(
            found[0].key,
            format!(r"HKEY_CURRENT_USER\{root}\{VERB_ADD}")
        );
        assert_eq!(found[0].label.as_deref(), Some(LABEL_ADD));
        // The command is the whole reason the UI shows this to the user.
        assert_eq!(found[0].command.as_deref(), Some(V1_ADD_COMMAND));

        assert_eq!(found[1].verb, VERB_EXCLUDE);
        assert_eq!(found[1].label.as_deref(), Some(LABEL_EXCLUDE));
        assert_eq!(found[1].command.as_deref(), Some(V1_EXCLUDE_COMMAND));

        win::remove_stale_verbs_under(CURRENT_USER, &root).expect("remove");
        assert!(probe().is_empty());
        // The `command` subkeys go with their verbs, not after them.
        assert!(CURRENT_USER
            .open(format!(r"{root}\{VERB_ADD}\command"))
            .is_err());
        assert!(CURRENT_USER.open(format!(r"{root}\{VERB_ADD}")).is_err());
        assert!(CURRENT_USER
            .open(format!(r"{root}\{VERB_EXCLUDE}"))
            .is_err());

        // Removing what is already gone succeeds: the caller asked for a state.
        win::remove_stale_verbs_under(CURRENT_USER, &root).expect("idempotent remove");

        CURRENT_USER
            .remove_tree(&scratch)
            .expect("clean up scratch");
    }

    /// One verb, no `command` subkey — still a menu item, still ours to offer
    /// to remove, and reported without a command rather than not reported.
    #[cfg(windows)]
    #[test]
    fn a_verb_without_a_command_is_still_stale() {
        use windows_registry::CURRENT_USER;

        let scratch = scratch_key("nocommand");
        let root = format!(r"{scratch}\shell");
        CURRENT_USER
            .create(format!(r"{root}\{VERB_EXCLUDE}"))
            .unwrap();

        let found = win::stale_verbs_under(CURRENT_USER, "HKEY_CURRENT_USER", &root);
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].verb, VERB_EXCLUDE);
        assert_eq!(found[0].command, None);
        // No caption was ever written, and an empty default value is not one.
        assert_eq!(found[0].label, None);

        win::remove_stale_verbs_under(CURRENT_USER, &root).expect("remove");
        assert!(win::stale_verbs_under(CURRENT_USER, "HKEY_CURRENT_USER", &root).is_empty());

        CURRENT_USER
            .remove_tree(&scratch)
            .expect("clean up scratch");
    }

    /// The point of [`PlatformError::NeedsElevation`]: only a permission
    /// failure earns it. Everything else stays a plain registry error, so the
    /// UI never tells a user to re-launch as administrator over a problem
    /// elevation cannot fix.
    #[cfg(windows)]
    #[test]
    fn only_access_denied_means_elevation() {
        assert!(matches!(
            win::classify(win::HRESULT_ACCESS_DENIED, "denied".into()),
            PlatformError::NeedsElevation
        ));
        assert!(matches!(
            win::classify(win::HRESULT_FILE_NOT_FOUND, "missing".into()),
            PlatformError::Registry(_)
        ));
        // ERROR_INVALID_PARAMETER, standing in for every other Win32 failure.
        assert!(matches!(
            win::classify(0x8007_0057_u32 as i32, "invalid".into()),
            PlatformError::Registry(_)
        ));
    }

    /// The codes above are not guesses: this pulls a real `ERROR_ACCESS_DENIED`
    /// and a real `ERROR_FILE_NOT_FOUND` out of Windows, without writing
    /// anything anywhere.
    #[cfg(windows)]
    #[test]
    fn real_registry_errors_classify_as_expected() {
        use windows_registry::LOCAL_MACHINE;

        let missing = LOCAL_MACHINE
            .open(r"Software\AutoTidyNoSuchKey-classification-probe")
            .expect_err("that key must not exist");
        assert!(matches!(
            win::classify(missing.code().0, missing.to_string()),
            PlatformError::Registry(_)
        ));

        // Opening the machine class root for write is exactly the probe
        // `is_elevated` makes, so the two must agree about this machine.
        let denied = LOCAL_MACHINE.options().write().open(r"Software\Classes");
        assert_eq!(denied.is_ok(), is_elevated());
        if let Err(err) = denied {
            assert!(matches!(
                win::classify(err.code().0, err.to_string()),
                PlatformError::NeedsElevation
            ));
        }
    }

    /// Full round-trip against the real registry, under a scratch key that is
    /// not `Directory\shell` and so is invisible to Explorer.
    #[cfg(windows)]
    #[test]
    fn registry_round_trip_registers_and_unregisters() {
        use windows_registry::CURRENT_USER;

        let unique = format!(
            "{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or_default()
        );
        // No shared parent key, so the cleanup below removes every trace.
        let scratch = format!(r"Software\AutoTidyTest-{unique}");
        let root = format!(r"{scratch}\shell");

        assert!(
            !win::context_menu_registered_under(&root),
            "a fresh scratch key must not look registered"
        );

        win::set_context_menu_under(&root, true).expect("register");
        assert!(win::context_menu_registered_under(&root));

        // Both verbs, and the caption, are really there.
        let exe = exe_path().unwrap();
        for (verb, label, flag) in [
            (VERB_ADD, LABEL_ADD, FLAG_ADD),
            (VERB_EXCLUDE, LABEL_EXCLUDE, FLAG_EXCLUDE),
        ] {
            let key = CURRENT_USER.open(format!(r"{root}\{verb}")).unwrap();
            assert_eq!(key.get_string("").unwrap(), label);
            let command = CURRENT_USER
                .open(format!(r"{root}\{verb}\command"))
                .unwrap();
            assert_eq!(command.get_string("").unwrap(), command_value(&exe, flag));
        }

        // Re-registering over an existing entry must not fail.
        win::set_context_menu_under(&root, true).expect("re-register");

        win::set_context_menu_under(&root, false).expect("unregister");
        assert!(!win::context_menu_registered_under(&root));
        assert!(CURRENT_USER.open(format!(r"{root}\{VERB_ADD}")).is_err());
        assert!(CURRENT_USER
            .open(format!(r"{root}\{VERB_EXCLUDE}"))
            .is_err());

        // Unregistering twice is a no-op, not an error.
        win::set_context_menu_under(&root, false).expect("idempotent unregister");

        CURRENT_USER
            .remove_tree(&scratch)
            .expect("clean up scratch");
    }
}
