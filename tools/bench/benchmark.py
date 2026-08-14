#!/usr/bin/env python3
"""Benchmark AutoTidy 2.0.0 (Rust) against the 1.5.0 Python engine.

Every number in the README's Benchmarks section comes from this script, so it
can be re-run and disputed rather than taken on trust:

    python tools/bench/benchmark.py --markdown

What it measures, and why each one:

* **Cold start** — the Explorer context menu spawns a fresh process per click,
  so process startup is user-visible latency, not a micro-benchmark curiosity.
* **Flat scan** — one pass over a folder where every file matches. This is
  dominated by per-file work (template expansion, record building, JSON), which
  is where an interpreted engine actually costs you.
* **Selective scan** — the same folder where almost nothing matches. Included
  deliberately because it is the *realistic* case, and it is the one where the
  rewrite buys you nothing. A benchmark that only shows favourable workloads is
  marketing.
* **Recursive scan** — 1.5.0 has no equivalent; its scan is a single flat
  `os.scandir`. Reported as a capability, not a speedup.

Both engines run in dry-run mode over the same tree, so neither mutates it and
the comparison is repeatable. Timing is wall-clock around the whole process,
including interpreter and runtime startup, because that is what a user waits
for.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RUST = REPO / "target" / "release" / "autotidy.exe"
RUST_APP = REPO / "target" / "release" / "AutoTidy.exe"
PY_DRIVER = REPO / "tools" / "parity" / "run_python_engine.py"
LEGACY_MAIN = REPO / "legacy" / "main.py"


def build_tree(root: Path, flat: int, nested_dirs: int, nested_each: int) -> int:
    root.mkdir(parents=True, exist_ok=True)
    for i in range(flat):
        (root / f"file_{i:05d}.txt").write_bytes(b"x")
    n = 0
    for d in range(nested_dirs):
        sub = root / f"d{d:02d}" / "a" / "b"
        sub.mkdir(parents=True, exist_ok=True)
        for i in range(nested_each):
            (sub / f"nested_{i:04d}.txt").write_bytes(b"x")
            n += 1
    return flat + n


def write_config(path: Path, tree: Path, pattern: str, depth: int = 0) -> None:
    path.write_text(json.dumps({
        "folders": [{
            "path": str(tree), "age_days": 0, "pattern": pattern, "rule_logic": "AND",
            "use_regex": False, "action": "move", "destination_folder": "",
            "exclusions": [], "enabled": True,
        }],
        "excluded_folders": [],
        "settings": {
            "archive_path_template": "_Cleanup/{YYYY}-{MM}-{DD}",
            "dry_run_mode": True, "interval_minutes": 60,
            "schedule_type": "interval", "max_directory_depth": depth,
        },
    }, indent=2), encoding="utf-8")


def interference() -> list[str]:
    """Processes whose presence would invalidate the measurements.

    Two specific hazards, both hit in practice:

    * **A running AutoTidy instance changes what is being measured.** The cold
      start path short-circuits before the Tauri runtime only when no GUI
      instance exists; with one running, the same command takes the argv
      forwarding path instead. That is a ~15x difference in the number, for a
      reason that has nothing to do with the code under test.
    * **A concurrent `cargo build` rewrites the binary mid-run** and competes
      for the same cores.
    """
    if platform.system() != "Windows":
        return []
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process AutoTidy,autotidy,cargo,rustc,link -ErrorAction SilentlyContinue "
             "| Select-Object -ExpandProperty Name -Unique"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except Exception:
        return []
    return sorted({line.strip() for line in out.splitlines() if line.strip()})


def timed(cmd: list[str], reps: int, env: dict | None = None) -> float | None:
    """Median wall-clock seconds, after one warm-up. None if the command fails."""
    r = subprocess.run(cmd, capture_output=True, env=env, cwd=REPO)
    if r.returncode != 0:
        return None
    samples = []
    for _ in range(reps):
        t0 = time.perf_counter()
        subprocess.run(cmd, capture_output=True, env=env, cwd=REPO)
        samples.append(time.perf_counter() - t0)
    return statistics.median(samples)


def fmt_ms(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    ms = seconds * 1000
    return f"{ms:,.0f} ms" if ms < 1000 else f"{seconds:.2f} s"


def size_mb(p: Path) -> float | None:
    return round(p.stat().st_size / 1024 / 1024, 2) if p.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--flat", type=int, default=8000, help="files directly in the tree")
    ap.add_argument("--nested-dirs", type=int, default=60)
    ap.add_argument("--nested-each", type=int, default=200)
    ap.add_argument("--markdown", action="store_true", help="emit a README-ready table")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="run even when interfering processes are detected")
    args = ap.parse_args()

    busy = interference()
    if busy and not args.force:
        print(f"error: these would skew the results: {', '.join(busy)}\n"
              f"       close any running AutoTidy and let builds finish, "
              f"or pass --force to measure anyway.", file=sys.stderr)
        return 2

    if not RUST.exists():
        print(f"error: {RUST} missing — run: cargo build --release -p autotidy-cli", file=sys.stderr)
        return 2
    if not LEGACY_MAIN.exists():
        print(f"error: legacy engine missing at {LEGACY_MAIN}", file=sys.stderr)
        return 2

    scratch = Path(tempfile.mkdtemp(prefix="autotidy-bench-"))
    tree = scratch / "tree"
    print(f"building corpus in {scratch} …", file=sys.stderr)
    total = build_tree(tree, args.flat, args.nested_dirs, args.nested_each)
    print(f"  {total:,} files ({args.flat:,} flat)", file=sys.stderr)

    cfg_all = scratch / "all.json"        # *.txt — everything matches
    cfg_few = scratch / "few.json"        # *.zzz — nothing matches
    write_config(cfg_all, tree, "*.txt")
    write_config(cfg_few, tree, "*.zzz")
    cfg_deep = scratch / "deep.json"
    write_config(cfg_deep, tree, "*.txt", depth=9)

    py_env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    app_env = dict(os.environ, APPDATA=str(scratch / "appdata"))
    (scratch / "appdata").mkdir(parents=True, exist_ok=True)
    (scratch / "cold").mkdir(parents=True, exist_ok=True)

    rows: list[tuple[str, str, str, str]] = []

    print("cold start …", file=sys.stderr)
    r = timed([str(RUST_APP), "--add-folder", str(scratch / "cold")], args.reps, app_env) \
        if RUST_APP.exists() else None
    p = timed([sys.executable, str(LEGACY_MAIN), "--add-folder", str(scratch / "cold")],
              args.reps, dict(py_env, APPDATA=str(scratch / "appdata")))
    rows.append(("Cold start (right-click → Add folder)", fmt_ms(p), fmt_ms(r), speedup(p, r)))

    print(f"flat scan, {args.flat:,} matching …", file=sys.stderr)
    r = timed([str(RUST), "scan", "--config", str(cfg_all), "--dry-run"], args.reps)
    p = timed([sys.executable, str(PY_DRIVER), "--config", str(cfg_all),
               "--out", str(scratch / "py.jsonl")], args.reps, py_env)
    rows.append((f"Organise {args.flat:,} files (all match)", fmt_ms(p), fmt_ms(r), speedup(p, r)))

    print(f"selective scan, {args.flat:,} scanned / 0 matching …", file=sys.stderr)
    r = timed([str(RUST), "scan", "--config", str(cfg_few), "--dry-run"], args.reps)
    p = timed([sys.executable, str(PY_DRIVER), "--config", str(cfg_few),
               "--out", str(scratch / "py2.jsonl")], args.reps, py_env)
    rows.append((f"Scan {args.flat:,} files (none match)", fmt_ms(p), fmt_ms(r), speedup(p, r)))

    print(f"recursive scan, {total:,} files …", file=sys.stderr)
    r = timed([str(RUST), "scan", "--config", str(cfg_deep), "--dry-run", "--depth", "9"], args.reps)
    rows.append((f"Scan {total:,} files recursively", "not supported", fmt_ms(r), "—"))

    installer = REPO / "target/release/bundle/nsis/AutoTidy_2.0.0_x64-setup.exe"
    legacy_installer = REPO / "Output" / "AutoTidy-1.1.0-setup.exe"
    legacy_exe = REPO / "dist" / "AutoTidy.exe"

    print()
    if args.markdown:
        print(f"<!-- generated by tools/bench/benchmark.py on "
              f"{platform.system()} {platform.release()} -->\n")
        print("| | 1.5.0 (Python) | 2.0.0 (Rust) | |")
        print("|---|---:|---:|---|")
        for label, old, new, delta in rows:
            print(f"| {label} | {old} | **{new}** | {delta} |")
        for label, old_p, new_p in (
            ("Installer", legacy_installer, installer),
            ("Executable", legacy_exe, RUST_APP),
        ):
            o, n = size_mb(old_p), size_mb(new_p)
            if o and n:
                print(f"| {label} | {o} MB | **{n} MB** | {o/n:.0f}× smaller |")
    else:
        for label, old, new, delta in rows:
            print(f"  {label:44} {old:>14} -> {new:>10}  {delta}")

    print(f"\nmachine: {platform.processor() or platform.machine()}, "
          f"{os.cpu_count()} logical cores, {platform.system()} {platform.release()}",
          file=sys.stderr)
    print(f"python: {sys.version.split()[0]}   reps: {args.reps} (median)", file=sys.stderr)

    if not args.keep:
        shutil.rmtree(scratch, ignore_errors=True)
    else:
        print(f"corpus kept at {scratch}", file=sys.stderr)
    return 0


def speedup(old: float | None, new: float | None) -> str:
    if not old or not new:
        return "—"
    ratio = old / new
    return f"{ratio:.1f}× faster" if ratio >= 1 else f"{1/ratio:.1f}× SLOWER"


if __name__ == "__main__":
    raise SystemExit(main())
