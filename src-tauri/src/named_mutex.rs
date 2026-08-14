//! Cross-process coordination for the Explorer context-menu verbs.
//!
//! An `--add-folder` click has to answer two separate questions before it knows
//! how much of the application to build, and they need two separate kernel
//! objects. Collapsing them into one does not work: the first is answered by a
//! name merely *existing*, the second by a name being *owned*, and a single
//! mutex cannot mean both without a CLI probe either claiming to be the GUI or
//! blocking behind it.
//!
//! 1. **Is a GUI instance running?** — [`GUI_INSTANCE`]. The GUI creates it in
//!    `setup()` and keeps the handle open for the rest of its life; the object
//!    exists exactly as long as that process does. A CLI invocation only ever
//!    probes it with [`is_held`] and must never create it — a CLI process that
//!    created the name would, for the moment it lived, convince a concurrent
//!    click that there was a GUI to forward to.
//!
//! 2. **May I rewrite `config.json` right now?** — [`CONFIG_WRITE`], taken for
//!    the duration of a read-modify-write. `ConfigStore::save` is atomic (a
//!    finished temp file renamed over the target) but load-mutate-save is not:
//!    two clicks arriving together would both read the old file and the second
//!    would write the first's folder straight back out of existence.
//!
//! Both names are session-local — no `Global\` prefix. AutoTidy is a per-user
//! app, the global namespace needs `SeCreateGlobalPrivilege`, and two users on
//! one machine should not be able to block each other's config writes.
//!
//! On non-Windows targets every operation is a no-op and [`is_held`] is always
//! false, so a `--add-folder` there always takes the fast path. That is the
//! correct outcome rather than a compromise: the context menu is registered
//! through the Windows registry and does not exist elsewhere, and the running
//! app keeps no cached copy of the config to be clobbered.

use std::marker::PhantomData;
use std::time::Duration;

/// Existence marker for a live GUI session. Never waited on — the fact that the
/// name resolves is the entire signal.
pub const GUI_INSTANCE: &str = "AutoTidy-GuiInstance";

/// Serialises `config.json` read-modify-write cycles across processes.
pub const CONFIG_WRITE: &str = "AutoTidy-ConfigWrite";

/// How long to wait for [`CONFIG_WRITE`].
///
/// The critical section is a few milliseconds of I/O, so reaching this timeout
/// means the holder is wedged rather than busy. The caller proceeds anyway:
/// silently discarding the folder the user just right-clicked is worse than an
/// unserialised write, and the write itself is still atomic.
pub const CONFIG_WRITE_TIMEOUT: Duration = Duration::from_secs(5);

/// True when some process in this session holds `name` open.
pub fn is_held(name: &str) -> bool {
    imp::is_held(name)
}

/// True when a GUI instance of AutoTidy is running in this session.
///
/// False here is what lets a context-menu invocation skip the Tauri runtime
/// entirely; true sends it down the normal path so `single-instance` can hand
/// its argv to the running app.
pub fn gui_instance_running() -> bool {
    is_held(GUI_INSTANCE)
}

/// Keeps a name in existence for as long as the value is alive.
///
/// Held, not owned: the marker never waits on the mutex, so nothing can ever
/// block on it and there is no thread that has to be the one to release it.
pub struct InstanceMarker {
    handle: imp::Handle,
}

impl InstanceMarker {
    /// Publish `name`, so that [`is_held`] reports true until this value drops.
    ///
    /// Returns `None` if the handle could not be created; the caller degrades to
    /// the pre-existing behaviour rather than failing to start.
    pub fn hold(name: &str) -> Option<Self> {
        imp::create(name).map(|handle| Self { handle })
    }
}

impl Drop for InstanceMarker {
    fn drop(&mut self) {
        imp::close(self.handle);
    }
}

// SAFETY: the handle is only ever closed, never waited on or released, and
// `CloseHandle` is thread-safe. The per-thread ownership rule that applies to
// `ReleaseMutex` therefore does not apply here, which is what lets the marker
// live in Tauri's state and be dropped by whichever thread tears the app down.
unsafe impl Send for InstanceMarker {}
// SAFETY: as above — the value exposes no operations at all through `&self`.
unsafe impl Sync for InstanceMarker {}

/// An owned cross-process lock, released when the value drops.
///
/// Dropping is the only way to release it, so a `?`, an early `return`, or an
/// unwind cannot leave the lock held. A hard abort (this crate builds with
/// `panic = "abort"`) skips `Drop`, but the kernel releases the mutex when the
/// process dies and the next waiter is told so — see the `WAIT_ABANDONED` arm.
pub struct NamedLock {
    handle: imp::Handle,
    /// Windows mutex ownership is per-thread: `ReleaseMutex` must run on the
    /// thread that waited, or it fails with `ERROR_NOT_OWNER` and the lock stays
    /// held forever. Keeping the guard `!Send` makes that a compile error rather
    /// than a deadlock nobody can reproduce.
    _not_send: PhantomData<*const ()>,
}

impl NamedLock {
    /// Wait up to `timeout` for `name`, returning `None` if it could not be
    /// taken. Callers treat `None` as "proceed unserialised", not as failure.
    pub fn acquire(name: &str, timeout: Duration) -> Option<Self> {
        imp::lock(name, timeout).map(|handle| Self {
            handle,
            _not_send: PhantomData,
        })
    }
}

impl Drop for NamedLock {
    fn drop(&mut self) {
        imp::release(self.handle);
    }
}

// ---------------------------------------------------------------------------
// Windows
// ---------------------------------------------------------------------------

#[cfg(windows)]
mod imp {
    use std::ptr;
    use std::time::Duration;
    use windows_sys::Win32::Foundation::{
        CloseHandle, GetLastError, HANDLE, WAIT_ABANDONED, WAIT_OBJECT_0,
    };
    use windows_sys::Win32::System::Threading::{
        CreateMutexW, OpenMutexW, ReleaseMutex, WaitForSingleObject,
    };

    pub(super) type Handle = HANDLE;

    /// `SYNCHRONIZE`. `windows-sys` files this constant under
    /// `Win32_Storage_FileSystem`, which is a large module to compile in for one
    /// integer that the SDK header has fixed forever.
    const SYNCHRONIZE: u32 = 0x0010_0000;

    fn wide(name: &str) -> Vec<u16> {
        name.encode_utf16().chain(std::iter::once(0)).collect()
    }

    /// Open a handle to `name`, creating the object if it does not exist yet,
    /// **without** taking ownership. A named object lives as long as any handle
    /// to it is open, which is all the marker needs.
    pub(super) fn create(name: &str) -> Option<Handle> {
        let name_w = wide(name);
        // SAFETY: `name_w` is a NUL-terminated UTF-16 buffer that outlives the
        // call. A null `SECURITY_ATTRIBUTES` asks for the default descriptor,
        // and `FALSE` for `bInitialOwner` means we get a handle without
        // acquiring the mutex.
        let handle = unsafe { CreateMutexW(ptr::null(), 0, name_w.as_ptr()) };
        if handle.is_null() {
            // SAFETY: reads this thread's last-error slot, set by the call above.
            let error = unsafe { GetLastError() };
            tracing::warn!(name, error, "could not create the named mutex");
            return None;
        }
        Some(handle)
    }

    /// Acquire `name`, waiting at most `timeout`.
    pub(super) fn lock(name: &str, timeout: Duration) -> Option<Handle> {
        let handle = create(name)?;
        let millis = u32::try_from(timeout.as_millis()).unwrap_or(u32::MAX);

        // SAFETY: `handle` is a live mutex handle from `CreateMutexW` above.
        match unsafe { WaitForSingleObject(handle, millis) } {
            WAIT_OBJECT_0 => Some(handle),
            // The previous holder died without releasing — a crash, or the
            // `panic = "abort"` profile skipping `Drop`. The lock is ours. The
            // data it guards is intact regardless, because the write it guards
            // lands as a rename or not at all.
            WAIT_ABANDONED => {
                tracing::warn!(
                    name,
                    "took an abandoned lock; its last holder exited while holding it"
                );
                Some(handle)
            }
            result => {
                tracing::warn!(name, result, "timed out waiting for the named mutex");
                close(handle);
                None
            }
        }
    }

    pub(super) fn is_held(name: &str) -> bool {
        let name_w = wide(name);
        // SAFETY: `name_w` is a NUL-terminated UTF-16 buffer that outlives the
        // call. `OpenMutexW` only reads the name; it never creates the object,
        // so probing cannot make the answer true.
        let handle = unsafe { OpenMutexW(SYNCHRONIZE, 0, name_w.as_ptr()) };
        if handle.is_null() {
            return false;
        }
        close(handle);
        true
    }

    /// Release ownership, then drop our handle.
    pub(super) fn release(handle: Handle) {
        // SAFETY: `handle` was acquired by `lock` on this thread, and `NamedLock`
        // is `!Send`, so this is the thread that owns the mutex.
        if unsafe { ReleaseMutex(handle) } == 0 {
            // SAFETY: reads this thread's last-error slot.
            let error = unsafe { GetLastError() };
            tracing::warn!(error, "could not release a named mutex");
        }
        close(handle);
    }

    pub(super) fn close(handle: Handle) {
        // SAFETY: `handle` is a live kernel handle this module owns and never
        // uses again.
        unsafe { CloseHandle(handle) };
    }
}

// ---------------------------------------------------------------------------
// Everywhere else
// ---------------------------------------------------------------------------

#[cfg(not(windows))]
mod imp {
    use std::time::Duration;

    pub(super) type Handle = ();

    pub(super) fn create(_name: &str) -> Option<Handle> {
        Some(())
    }

    pub(super) fn lock(_name: &str, _timeout: Duration) -> Option<Handle> {
        Some(())
    }

    /// Always false: with no named-object namespace to consult, the honest
    /// answer is "no GUI found", which routes a context-menu action down the
    /// direct-write path.
    pub(super) fn is_held(_name: &str) -> bool {
        false
    }

    pub(super) fn release(_handle: Handle) {}

    pub(super) fn close(_handle: Handle) {}
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    /// Tests share one session namespace with each other and with any AutoTidy
    /// the developer happens to be running, so every name has to be unique.
    fn scratch_name(tag: &str) -> String {
        use std::sync::atomic::{AtomicU32, Ordering};
        static COUNTER: AtomicU32 = AtomicU32::new(0);
        format!(
            "AutoTidyTest-{tag}-{}-{}",
            std::process::id(),
            COUNTER.fetch_add(1, Ordering::Relaxed)
        )
    }

    #[test]
    fn a_probe_is_false_when_nothing_holds_the_name() {
        assert!(!is_held(&scratch_name("unheld")));
    }

    #[test]
    fn the_real_names_are_session_local_and_distinct() {
        // A `Global\` prefix would need a privilege the app does not have, and
        // one name doing both jobs is the design error this module exists to
        // avoid.
        assert!(!GUI_INSTANCE.starts_with(r"Global\"));
        assert!(!CONFIG_WRITE.starts_with(r"Global\"));
        assert_ne!(GUI_INSTANCE, CONFIG_WRITE);
    }

    #[cfg(windows)]
    #[test]
    fn a_marker_makes_the_probe_true_until_it_is_dropped() {
        let name = scratch_name("marker");
        assert!(!is_held(&name));

        let marker = InstanceMarker::hold(&name).expect("hold");
        assert!(is_held(&name), "a held name must resolve");

        drop(marker);
        assert!(!is_held(&name), "dropping the marker must retire the name");
    }

    #[cfg(windows)]
    #[test]
    fn probing_does_not_create_the_name() {
        // The whole scheme breaks if a CLI probe can make itself look like a GUI.
        let name = scratch_name("probe-only");
        assert!(!is_held(&name));
        assert!(!is_held(&name));
    }

    #[cfg(windows)]
    #[test]
    fn a_lock_is_released_on_drop_and_can_be_taken_again() {
        let name = scratch_name("cycle");
        for _ in 0..3 {
            let lock = NamedLock::acquire(&name, Duration::from_secs(1))
                .expect("an unheld lock is available");
            drop(lock);
        }
        // Still takeable after the loop: no handle or ownership leaked.
        assert!(NamedLock::acquire(&name, Duration::from_secs(1)).is_some());
    }

    #[cfg(windows)]
    #[test]
    fn a_held_lock_blocks_another_thread() {
        use std::sync::mpsc;

        let name = scratch_name("exclusive");
        let held = NamedLock::acquire(&name, Duration::from_secs(1)).expect("acquire");

        // Another thread stands in for another process: Windows mutex ownership
        // is per-thread, so a second attempt on *this* thread would recurse and
        // succeed, proving nothing.
        let (tx, rx) = mpsc::channel();
        let probe = name.clone();
        let worker = std::thread::spawn(move || {
            tx.send(NamedLock::acquire(&probe, Duration::from_millis(50)).is_some())
                .ok();
        });
        assert!(
            !rx.recv().unwrap(),
            "a lock held elsewhere must not be handed out"
        );
        worker.join().unwrap();

        drop(held);

        let probe = name.clone();
        let after = std::thread::spawn(move || {
            NamedLock::acquire(&probe, Duration::from_secs(1)).is_some()
        });
        assert!(
            after.join().unwrap(),
            "releasing must let another thread through"
        );
    }

    #[cfg(windows)]
    #[test]
    fn the_two_names_do_not_interfere() {
        // The GUI marker must not make the config lock look taken, or a cold
        // click would wait five seconds for a lock nobody holds.
        let instance = scratch_name("two-a");
        let config = scratch_name("two-b");

        let _marker = InstanceMarker::hold(&instance).expect("hold");
        assert!(NamedLock::acquire(&config, Duration::from_millis(50)).is_some());
    }

    #[cfg(not(windows))]
    #[test]
    fn the_fallback_reports_no_gui_and_never_blocks() {
        assert!(!gui_instance_running());
        assert!(InstanceMarker::hold("anything").is_some());
        assert!(NamedLock::acquire("anything", Duration::from_millis(1)).is_some());
    }
}
