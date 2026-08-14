#!/usr/bin/env python3
"""Diff two engines' history output and report any divergence.

Fields that are legitimately non-deterministic (`timestamp`, `run_id`) and
derived (`severity`) are dropped. Absolute paths are rewritten relative to each
run's own corpus root and slash-normalized, so the two engines can be run over
separate copies of the same tree.

Exit code is non-zero when the engines disagree, so this can gate CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VOLATILE_FIELDS = {"timestamp", "run_id", "severity"}
PATH_FIELDS = ("original_path", "destination_path", "monitored_folder")

# `details` is a human-readable message. The Rust port deliberately does not
# reproduce Python's phrasing byte-for-byte, so it is compared only when
# --strict-details is passed.
PROSE_FIELDS = {"details"}


def normalize(record: dict, root: Path, strict_details: bool) -> dict:
    out = {}
    for key, value in record.items():
        if key in VOLATILE_FIELDS:
            continue
        if key in PROSE_FIELDS and not strict_details:
            continue
        if key in PATH_FIELDS and isinstance(value, str):
            value = relativize(value, root)
        out[key] = value
    return out


def relativize(raw: str, root: Path) -> str:
    path = Path(raw)
    try:
        rel = path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        rel = path
    return str(rel).replace("\\", "/")


def load(path: Path, root: Path, strict_details: bool) -> dict[str, dict]:
    """Key records by normalized original_path so ordering never matters."""
    keyed: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        norm = normalize(record, root, strict_details)
        keyed[norm.get("original_path", "?")] = norm
    return keyed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--python", required=True, type=Path, help="reference JSONL")
    ap.add_argument("--python-root", required=True, type=Path)
    ap.add_argument("--rust", required=True, type=Path, help="JSONL under test")
    ap.add_argument("--rust-root", required=True, type=Path)
    ap.add_argument("--strict-details", action="store_true",
                    help="also require the human-readable 'details' text to match")
    args = ap.parse_args()

    ref = load(args.python, args.python_root, args.strict_details)
    got = load(args.rust, args.rust_root, args.strict_details)

    only_python = sorted(set(ref) - set(got))
    only_rust = sorted(set(got) - set(ref))
    differing = []
    for key in sorted(set(ref) & set(got)):
        if ref[key] != got[key]:
            differing.append(key)

    for key in only_python:
        print(f"MISSING IN RUST   {key}\n    python: {ref[key]}")
    for key in only_rust:
        print(f"EXTRA IN RUST     {key}\n    rust:   {got[key]}")
    for key in differing:
        print(f"DIVERGENT         {key}")
        for field in sorted(set(ref[key]) | set(got[key])):
            a, b = ref[key].get(field), got[key].get(field)
            if a != b:
                print(f"    {field}: python={a!r}  rust={b!r}")

    total = len(only_python) + len(only_rust) + len(differing)
    print()
    print(f"python records: {len(ref)}   rust records: {len(got)}")
    print(f"missing: {len(only_python)}   extra: {len(only_rust)}   divergent: {len(differing)}")
    if total == 0:
        print("PARITY OK")
        return 0
    print(f"PARITY FAILED ({total} discrepancies)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
