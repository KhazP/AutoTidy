# Icons

Only the sizes a Windows build actually consumes are committed. `icon.ico` is
the application and tray icon; the PNGs cover the bundler's other references.

Regenerate them all from the 1024px source:

```bash
cargo tauri icon assets/autotidy-1024.png --output src-tauri/icons
```

That command also emits macOS (`.icns`), iOS and Android icon sets. Those are
deliberately **not** committed — AutoTidy ships for Windows only, and they were
2.1 MB of the 2.5 MB this directory used to occupy. If the project ever targets
another platform, rerun the command and commit what that platform needs.
