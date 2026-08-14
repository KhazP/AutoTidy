# Changelog

All notable changes to AutoTidy are documented here.
This project follows [Semantic Versioning](https://semver.org/).

---

## [2.0.0] — 2026-08-14

### AutoTidy is now a Rust application

Versions up to 1.5.0 were Python + PyQt6. 2.0.0 is a complete rewrite in
**Rust + Tauri**, keeping the same features and the same config file.

**Upgrading:** nothing to migrate. Your rules, settings and history are read in
place from `%APPDATA%\AutoTidy`. The installer detects AutoTidy 1.x and offers
to remove it first — **take the offer.** The two versions were built with
different installers, so Windows will not replace the old one automatically, and
running both means two copies organising the same folders simultaneously.

---

### Added

- **Recursive scanning.** Rules can descend into subfolders to a configurable
  depth. Defaults to `0` (the monitored folder only), which is exactly what
  1.5.0 did — existing setups behave identically until you change it.
- **Watch mode.** Instead of waking on a timer, AutoTidy can react to files as
  they appear. Debounced, so a file still being copied is left alone.
- **Scan now.** 1.5.0 had no way to trigger a scan; the only option was to stop
  and restart monitoring.
- **Dark mode**, following the Windows theme.
- **Global excluded folders now have a UI.** The setting existed in
  `config.json` in 1.5.0 but there was no way to edit it from the app.
- **Log level and scan depth** are editable in Settings; previously
  config-file-only.
- **Row actions in History** — reveal a file in Explorer or copy its path.
- **A danger zone in Settings**, with a per-field diff showing exactly what
  "Restore defaults" will change before you confirm.

### Changed

- **The engine is separate from the UI.** `autotidy-core` has no GUI
  dependencies, so the same code runs the app, a headless CLI, and the test
  harness.
- **The UI is event-driven.** 1.5.0 polled a queue on a timer; the engine now
  pushes updates, so the log and status reflect work as it happens.
- **History is virtualised** rather than paged at a fixed 500 rows with a
  "Load All" button.
- **Undo tells you the blast radius up front** — how many actions will be
  reversed, how many cannot be, and what happens if one fails partway.
- **Explorer context menu moved to the per-user registry hive.** See Fixed.
- The Windows installer is now NSIS (per-user) rather than Inno Setup
  (machine-wide).

### Fixed

Every one of these existed in 1.5.0 and was found by differentially testing the
new engine against the old one:

- **The Explorer context menu required administrator rights.** 1.5.0 wrote to
  `HKEY_CLASSES_ROOT` and exited with an error when run unelevated, which made
  the feature effectively unavailable. It now uses `HKEY_CURRENT_USER`.
- **`--add-folder` could silently discard unrelated changes.** Adding a folder
  from Explorer spawned a second process that wrote `config.json` while the
  running app held a stale copy in memory and overwrote it on quit.
- **Renaming destination templates lost the rename.** A destination of
  `{FILENAME}_backup{EXT}` correctly computed the new name and then discarded
  it, filing the file under its original name. Only reachable on a real run, so
  a dry run never revealed it.
- **Undoing a whole run left no trace in history.** Only single-item undos were
  logged; batch undos vanished.
- **Config writes were not atomic.** An interrupted save could corrupt
  `config.json` — which is why 1.5.0 carried a `.corrupt.bak` recovery path.
  Writes now go through a temp file and an atomic rename.
- **`--add-folder` and `--exclude-folder` together silently dropped one of
  them** because of an `elif`.
- **An `interval_minutes` of `0`** — reachable by hand-editing the config —
  spun the scan loop with no sleep. It is now clamped.
- **Undo asked you to confirm actions it could not perform**, then reported
  failure afterwards. Non-reversible actions now say so before you commit.

### Performance

Measured on the same machine, same workloads. Reproduce with:

```bash
python tools/bench/benchmark.py --markdown
```

<!-- BENCHMARK TABLE -->

**Read that table honestly.** The workload where AutoTidy is 12× faster is one
where every file matches — a first-run cleanup of a badly overgrown folder.
The routine case is a Downloads folder with a few dozen files scanned once an
hour, and there the old engine already finished in about 13 milliseconds. You
will not perceive the difference.

The changes you *will* notice are the install size, the launch behaviour
(1.5.0's packaging unpacked 33.5 MB into `%TEMP%` on every single launch), and
the two scanning modes that did not exist before.

### Verification

Rewriting a program that moves and deletes files is not something to do on
confidence alone, so the 1.5.0 engine is retained in [`legacy/`](legacy/) as an
executable specification and both engines are run over a purpose-built corpus:

| | What it compares | Coverage |
|---|---|---|
| `tools/parity/run_parity.py` | the decisions each engine makes | 12 rule variants |
| `tools/parity/wet_parity.py` | the files each engine actually produces | 11 rule variants |

Two harnesses because one is not enough: 1.5.0's collision handling lives inside
`if not dry_run:`, so a dry run can never reach it. The second harness runs both
engines for real over disposable copies and diffs the resulting trees.

Plus 246 Rust tests and the legacy engine's own 76.

### Known limitations

- **Windows only.** The engine is cross-platform and its tests run on Linux in
  CI, but the tray, autostart and context-menu integration are Windows-specific.
- **Permanent deletion cannot be undone**, and Recycle Bin deletions are
  reversible only through Windows itself.
- Filename collisions get a counter (`_1`, `_2`), falling back to a timestamp
  after 100 attempts.

### Note for anyone upgrading from 1.x

1.5.0's Explorer menu entries live in a machine-wide registry location that
2.0's per-user uninstaller cannot reach. If you registered them, AutoTidy
detects the leftovers and offers to remove them — they otherwise remain as menu
items pointing at a `python.exe` that may no longer exist.

---

## [1.5.0] and earlier

See [previous releases](https://github.com/KhazP/AutoTidy/releases). The Python
implementation is preserved in [`legacy/`](legacy/) and tagged `v1.5.0`.

[2.0.0]: https://github.com/KhazP/AutoTidy/releases/tag/v2.0.0
[1.5.0]: https://github.com/KhazP/AutoTidy/releases/tag/v1.5.0
