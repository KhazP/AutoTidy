<img src="assets/autotidyicon.ico" alt="" width="88" align="left" hspace="12" vspace="4"/>

# AutoTidy

**Automatic file organisation for Windows.** Point it at the folders that get
messy — Downloads, Desktop, Screenshots — describe what should happen to what,
and it keeps them tidy in the background.

<br clear="left"/>

[![Version](https://img.shields.io/badge/version-2.0.0-1f6feb?style=flat-square)](Cargo.toml)
[![Rust](https://img.shields.io/badge/Rust-2021-b7410e?style=flat-square&logo=rust&logoColor=white)](crates/)
[![Tauri](https://img.shields.io/badge/Tauri-2-24c8db?style=flat-square&logo=tauri&logoColor=white)](src-tauri/)
[![License](https://img.shields.io/badge/license-MPL--2.0-blue?style=flat-square)](LICENSE)
[![Installer](https://img.shields.io/badge/installer-1.8%20MB-success?style=flat-square)](#install)

---

> ### 2.0 is a full rewrite in Rust
>
> AutoTidy was a Python + PyQt6 app through 1.5.0. Version 2.0 rebuilds it on
> **Rust and Tauri** — a 1.8 MB installer instead of 73 MB, with recursive
> scanning and real-time folder watching that the old architecture couldn't
> support.
>
> **Upgrading is nothing to do.** Your rules, settings and history are read in
> place from `%APPDATA%\AutoTidy` exactly as they are. The rewrite was verified
> against the old engine file-by-file — see [Verification](#verification).

---

## What it does

You define rules per folder. Each rule matches files by **age**, by **name
pattern**, or both, and then does one thing with them:

| Action | What happens |
|---|---|
| **Move** | Relocated into a dated archive folder, or anywhere you choose |
| **Copy** | Duplicated, original left alone |
| **Delete to Recycle Bin** | Recoverable through Windows |
| **Delete permanently** | Irreversible — the UI makes sure you know |

Everything it does is written to a log you can browse, filter and **undo**.

### Features

- **Age and pattern matching** — combined with AND or OR. Age `0` makes a rule
  name-only.
- **Glob or regex** patterns, with per-rule exclusions and a global
  never-touch-these-folders list.
- **Preview matches** before a rule ever runs.
- **Dry-run mode** — simulate everything, change nothing.
- **Recursive scanning** to a depth you choose. *(new in 2.0)*
- **Watch mode** — react as files appear instead of polling. *(new in 2.0)*
- **Templated destinations**: `_Cleanup/{YYYY}-{MM}-{DD}`, with `{FILENAME}`,
  `{EXT}` and `{ORIGINAL_FOLDER_NAME}` too.
- **Full history and undo**, grouped by scan run.
- **Explorer right-click** → "Add to AutoTidy". *(now works without admin
  rights — see [Fixed in 2.0](#fixed-in-20))*
- Lives in the system tray. Dark mode follows Windows.

---

## Install

Download the latest installer from
[Releases](https://github.com/KhazP/AutoTidy/releases) and run it.

> **2.0.0 is not released yet.** The version on the Releases page is still
> 1.5.0 (Python). Build 2.0 [from source](#build-from-source) in the meantime.

Windows 10 or 11. The installer is per-user — no administrator rights needed.
WebView2 is already present on Windows 11 and current Windows 10; if it's
missing the installer fetches it.

> **Upgrading from 1.x?** The installer detects the old version and offers to
> remove it first. Take the offer — the two installers use different systems, so
> Windows won't replace it automatically, and leaving both installed means two
> copies of AutoTidy organising the same folders at once.

> **Code signing.** Release binaries are **not signed yet.** An application to
> the [SignPath Foundation](https://signpath.org/)'s free programme for
> open-source projects is pending; the [code signing policy](#code-signing-policy)
> below describes the arrangement it will put in place.
>
> Until then SmartScreen will warn. Choose *More info → Run anyway*, verify the
> SHA-256 checksum published with the release, or build it yourself from source
> below.

---

## How it compares to 1.5.0

Measured on the same machine, same workload:

| | 1.5.0 | 2.0.0 | |
|---|---:|---:|---|
| Installer | 73 MB | **1.8 MB** | 41× smaller |
| Executable | 33.5 MB | **4.9 MB** | 6.9× smaller |
| Launch | unpacked 33.5 MB to `%TEMP%` every time | runs directly | — |
| Right-click → Add folder | 74 ms | **21 ms** | 3.5× faster |
| Organising 8,000 files | 7.4 s | **0.6 s** | 12× faster |
| Scanning 20,000 files recursively | *not supported* | **1.6 s** | — |

Honesty about that speed column: if you're tidying a Downloads folder with a
few dozen files once an hour, **you will not notice any of it**. The old engine
took about 13 ms for that. The size, the launch behaviour, and the two new
scanning modes are the real differences.

Full numbers, methodology and the workload where the rewrite buys you nothing
are in the [2.0.0 release notes](CHANGELOG.md#performance). Reproduce them
yourself with `python tools/bench/benchmark.py --markdown`.

### Fixed in 2.0

Bugs found by diffing the new engine against the old one, all of which existed
in 1.5.0:

- **The Explorer context menu needed administrator rights** and refused to
  install without them. It now uses the per-user registry hive.
- **`--add-folder` could silently discard your other changes.** It launched a
  second process that wrote `config.json` while the running app held a stale
  copy and overwrote it on quit.
- **Renaming destination templates lost the rename.** A destination of
  `{FILENAME}_backup{EXT}` filed the file under its original name.
- **Undoing a whole run left no record**, because only single-item undos were
  logged.
- **Config writes weren't atomic**, so an interrupted save could corrupt
  `config.json`.
- **Undo now tells you up front** when something can't be reversed, instead of
  asking you to confirm and then failing.

---

## Configuration

Settings and rules live in `%APPDATA%\AutoTidy\config.json`; history in
`autotidy_history.jsonl` beside it. Both are plain text and safe to read.

**Archive template** — `_Cleanup/{YYYY}-{MM}-{DD}` by default. Relative paths
resolve inside the monitored folder. Available placeholders: `{YYYY}` `{MM}`
`{DD}` `{FILENAME}` `{EXT}` `{ORIGINAL_FOLDER_NAME}`.

**Exclusion patterns** are checked *before* age and name, so an excluded file is
never touched no matter what else matches:

| Pattern | Effect |
|---|---|
| `*.tmp` | skip temp files |
| `build/` | skip a whole subfolder |
| `~$*.docx` | skip Office autosave files |
| `^backup_\d{4}` | regex, when the rule has regex enabled |

> On Windows, glob patterns are **case-insensitive** — `*.pdf` matches
> `Report.PDF`. This matches how 1.5.0 behaved. Regex patterns are
> case-sensitive.

---

## Build from source

Needs [Rust](https://rustup.rs) (stable), [Node](https://nodejs.org) 20+, and
the MSVC build tools.

```bash
npm install
npm run tauri dev      # run with hot-reloading UI
npm run tauri build    # produce target/release/bundle/nsis/
```

### Layout

| Path | |
|---|---|
| `crates/autotidy-core/` | The engine — matching, actions, history, undo, scanning. No GUI dependencies. |
| `crates/autotidy-cli/` | Headless driver for the engine, used by the parity harness. |
| `src-tauri/` | Desktop shell: tray, window, IPC, Windows registry integration. |
| `src/` | React + TypeScript UI. |
| `tools/parity/` | Differential test harness against the 1.5.0 engine. |
| `legacy/` | The retired Python 1.5.0 engine. Not built, not shipped — [here's why](legacy/README.md). |

Keeping the engine free of GUI dependencies is deliberate: the same code is
driven by the app, by the CLI, and by the test harness.

---

## Verification

```bash
cargo test                          # 251 tests — the actual suite
python tools/parity/run_parity.py   # decisions, 12 rule variants
python tools/parity/wet_parity.py   # resulting files, 11 rule variants
```

The reference engine has its own 76 tests, which exist to guard the thing the
parity harnesses measure against rather than to test shipping code:

```bash
cd legacy && pytest -q
```

Rewriting a program that **deletes people's files** is not something to do on
confidence alone. So the old engine is kept as an executable specification, and
both engines are run over a purpose-built corpus and their output compared.

The corpus targets the places a port silently breaks: files straddling every age
boundary, unicode and spaces and glob metacharacters in names, mixed-case
extensions, pre-seeded collisions in the destination, and files already sitting
inside the archive folder.

Two harnesses, because one isn't enough. The dry-run harness compares the
*decisions* each engine makes. But 1.5.0's collision handling lives inside
`if not dry_run:`, so a dry run can never reach it — the second harness runs
both engines **for real** over disposable copies and diffs the resulting file
trees byte-for-byte.

That's how the case-sensitivity and template-rename bugs above were found.

---

## Known limitations

- **Windows only.** The engine is cross-platform and its tests run on Linux in
  CI, but the tray, autostart and context-menu integration are Windows-specific.
- **Not code-signed yet**, so SmartScreen will warn on first run.
- **Permanent deletion cannot be undone.** Recycle Bin deletions are reversible
  only through Windows itself.
- Filename collisions get a counter (`_1`, `_2`), falling back to a timestamp
  after 100 attempts.

---

## Privacy

**AutoTidy collects nothing.** There is no telemetry, no analytics, no crash
reporting, and no network access of any kind — the application never makes an
outbound connection.

Everything it writes stays on your machine, under `%APPDATA%\AutoTidy`:

| File | Contents |
|---|---|
| `config.json` | Your rules and settings |
| `autotidy_history.jsonl` | A record of every file action taken, so it can be undone |
| `autotidy.log` | Diagnostic log, rotated at 5 MB |

These necessarily contain paths and filenames from the folders you asked
AutoTidy to organise. They are never transmitted anywhere. Deleting the folder
removes all of it.

The installer downloads the Microsoft WebView2 runtime from Microsoft if it
isn't already present on the system. That is the only network activity
associated with the project, it happens once at install time, and it is
performed by Microsoft's own bootstrapper.

---

## Code signing policy

> **Status: pending.** An application to the SignPath Foundation is in progress.
> This policy describes the arrangement that will apply once it is approved, and
> is published here because the Foundation requires a project to have one. No
> release is signed yet — see [Install](#install).

Release binaries are signed by [SignPath.io](https://signpath.io/), with a free
code signing certificate provided by the
[SignPath Foundation](https://signpath.org/) for open-source projects.

Because the certificate is issued in the SignPath Foundation's name, Windows
shows **SignPath Foundation** as the publisher on signed AutoTidy binaries. That
is expected and correct — it identifies who vouches for the signature, not who
wrote the software.

### Roles

AutoTidy is maintained by a single developer, who fills every role:

| Role | Who | Responsibility |
|---|---|---|
| **Author** | [@KhazP](https://github.com/KhazP) | Writes and commits the source |
| **Reviewer** | [@KhazP](https://github.com/KhazP) | Reviews changes before they are merged to `main` |
| **Approver** | [@KhazP](https://github.com/KhazP) | Approves each signing request before a release is signed |

Every signing request is approved manually. Signing is never automatic.

### What gets signed

Only binaries built by [GitHub Actions](.github/workflows/) from source in this
repository, at a tagged commit. Nothing is signed from a developer machine, and
no third-party binary is submitted for signing.

### Data handling

AutoTidy collects no user data — see [Privacy](#privacy) above.

---

## Contributing

1. Fork, then branch: `git checkout -b feat/my-improvement`
2. Make your change, and keep `cargo test`, `cargo clippy`, `cargo fmt --check`
   and `npm run typecheck` clean
3. **If you touch the engine, run both parity harnesses.** They are the safety
   net for a program that moves and deletes files.
4. Open a pull request against `main`

---

## Disclaimer

AutoTidy **moves and deletes files** according to rules you write. Try new rules
against a folder you don't care about first, and use dry-run mode. The authors
aren't liable for data loss.

## License

[MPL-2.0](LICENSE). The Rust and Tauri stack is MIT/Apache-2.0 throughout —
unlike 1.5.0, which shipped GPL-v3 PyQt6 inside an MPL-2.0 project.

Citation metadata: [`CITATION.cff`](CITATION.cff).
