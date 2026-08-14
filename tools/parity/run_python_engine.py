#!/usr/bin/env python3
"""Produce the reference history JSONL by driving the 1.5.0 Python engine.

`MonitoringWorker` can't be reused directly — it's a daemon thread wrapped in an
infinite sleep loop. Instead this mirrors its per-file scan body exactly, using
the *real* `check_file` and `process_file_action` from utils.py so the actual
decision logic under test is the shipped code, not a paraphrase of it.

The mirrored section is worker.py lines ~128-214. If that loop changes, this
must change with it; it is deliberately kept short and literal so the
correspondence stays checkable by eye.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# The 1.5.0 engine lives under legacy/ so the repository root reads as the Rust
# project it now is. Importing it here is the whole point of this script: the
# comparison must run the *shipped* Python code, not a paraphrase of it.
LEGACY_ROOT = REPO_ROOT / "legacy"
if not LEGACY_ROOT.is_dir():
    raise SystemExit(f"error: legacy engine not found at {LEGACY_ROOT}")
sys.path.insert(0, str(LEGACY_ROOT))

import constants  # noqa: E402
from utils import check_file, process_file_action, safe_regex_match, _compile_pattern  # noqa: E402


def scan_folder(rule: dict, archive_template: str, run_id: str, records: list,
                dry_run: bool = True) -> None:
    """Mirror of the per-folder body of MonitoringWorker.run()."""
    monitored_path = Path(rule["path"])
    age_days = rule.get("age_days", 0)
    pattern = rule.get("pattern", "*.*")
    use_regex = rule.get("use_regex", False)
    exclusions = rule.get("exclusions", [])
    rule_logic = rule.get("rule_logic", "OR")
    action = rule.get("action", "move")
    destination_folder = rule.get("destination_folder", "")

    if not monitored_path.is_dir():
        print(f"warning: {monitored_path} is not a directory", file=sys.stderr)
        return

    # Pre-compile, as worker.py does.
    if use_regex and pattern:
        _compile_pattern(pattern)
    compiled_exclusions = []
    for excl in exclusions:
        if not excl:
            continue
        if use_regex:
            compiled_exclusions.append(("regex", excl))
            _compile_pattern(excl)
        else:
            compiled_exclusions.append(("glob", excl))

    with os.scandir(str(monitored_path)) as scanner:
        dir_entries = list(scanner)

    for entry in dir_entries:
        if entry.is_symlink():
            continue
        if not entry.is_file(follow_symlinks=False):
            continue

        item_name = entry.name
        item_path = Path(entry.path)

        # Exclusions first, matching worker.py's documented ordering.
        is_excluded = False
        for excl_type, excl_val in compiled_exclusions:
            if excl_type == "regex":
                result = safe_regex_match(excl_val, item_name)
                if result is not None and result:
                    is_excluded = True
                    break
            else:
                if fnmatch.fnmatch(item_name, excl_val):
                    is_excluded = True
                    break

        if is_excluded:
            records.append({
                "original_path": str(item_path),
                "action_taken": constants.ACTION_SKIPPED,
                "destination_path": None,
                "monitored_folder": str(monitored_path),
                "rule_pattern": pattern,
                "rule_age_days": age_days,
                "rule_use_regex": use_regex,
                "rule_action_config": action,
                "status": constants.STATUS_SKIPPED,
                "details": f"Skipped excluded file: {item_name}",
                "run_id": run_id,
            })
            continue

        entry_stat = entry.stat(follow_symlinks=False)
        if check_file(item_path, age_days, pattern, use_regex, rule_logic,
                      precomputed_stat=entry_stat):
            process_file_action(
                item_path,
                monitored_path,
                archive_template,
                action,
                dry_run,
                pattern,
                age_days,
                use_regex,
                records.append,
                run_id,
                destination_folder,
            )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument(
        "--wet",
        action="store_true",
        help="actually move/copy/delete files. Only ever point this at a "
             "disposable copy of a corpus — it is how the commit path "
             "(collision claiming, real renames) gets compared, which a "
             "dry run structurally cannot reach.",
    )
    args = ap.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    archive_template = config.get("settings", {}).get(
        "archive_path_template", "_Cleanup/{YYYY}-{MM}-{DD}"
    )

    run_id = str(uuid.uuid4())
    records: list = []
    for rule in config.get("folders", []):
        if not rule.get("enabled", True):
            continue
        scan_folder(rule, archive_template, run_id, records, dry_run=not args.wet)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, sort_keys=True) + "\n")

    print(f"{len(records)} record(s) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
