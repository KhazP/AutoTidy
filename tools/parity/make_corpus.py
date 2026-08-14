#!/usr/bin/env python3
"""Build a deterministic corpus for differential-testing the Rust engine.

The Python 1.5.0 engine and the Rust v2 engine are each run over an identical
copy of this tree in dry-run mode; any divergence in the emitted history is a
port bug. The corpus therefore has to exercise the edges where a port silently
breaks, not just the happy path:

  * ages straddling every age_days threshold the rules use, including exactly-on
    the boundary
  * names that stress fnmatch vs regex-fullmatch semantics
  * unicode, spaces, dots, and names that look like globs
  * pre-existing collisions in the destination, so collision suffixing is
    compared rather than skipped
  * files that already live in the archive folder, which is where recursive
    scanning would loop

Deterministic by construction: no randomness, and mtimes are set relative to a
fixed epoch passed in, so two runs produce byte-identical trees.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Files directly in the monitored root. These carry the parity comparison: the
# 1.5.0 engine scans FLAT (a single os.scandir, no recursion), so anything in a
# subdirectory is invisible to the reference engine and cannot be diffed.
#
# (relative path, age in days, contents)
FLAT_FILES: list[tuple[str, int, str]] = [
    # --- age boundaries around the common thresholds (0, 7, 30, 90) ---
    ("age_brand_new.txt", 0, "new"),
    ("age_six_days.txt", 6, "6d"),
    ("age_exactly_seven.txt", 7, "7d"),          # boundary: > vs >=
    ("age_eight_days.txt", 8, "8d"),
    ("age_twentynine.txt", 29, "29d"),
    ("age_exactly_thirty.txt", 30, "30d"),
    ("age_thirtyone.txt", 31, "31d"),
    ("age_ancient.txt", 400, "old"),

    # --- extension / glob matching ---
    ("glob_report.pdf", 45, "pdf"),
    ("glob_archive.tar.gz", 45, "double ext"),
    ("glob_no_extension", 45, "bare"),
    (".hiddenfile", 45, "dotfile"),
    ("glob_spaces in name.txt", 45, "spaces"),
    ("glob_literal[bracket].txt", 45, "glob metachar in NAME"),

    # fnmatch.fnmatch normcases both operands, so on Windows `*.txt` matches
    # these. check_file uses fnmatch, not fnmatchcase — a case-SENSITIVE port
    # would silently stop matching them, and only a corpus file with a real
    # uppercase extension catches that. NTFS preserves case even though it
    # compares insensitively, so these are distinct filenames on disk.
    ("CASE_UPPER.TXT", 45, "uppercase extension"),
    ("Case_Mixed.TxT", 45, "mixed-case extension"),

    # --- regex fullmatch vs search: 'a.c' must match 'abc' but NOT 'xabcx' ---
    ("regex_abc.log", 45, "fullmatch target"),
    ("regex_xabcx.log", 45, "must NOT match a.c"),
    ("regex_backup_2024.bak", 45, "exclusion probe"),
    ("regex_backup_20.bak", 45, "shorter, should not match ^backup_\\d{4}"),

    # --- unicode and long names ---
    ("unicode_café_notes.txt", 45, "accented"),
    ("unicode_日本語.txt", 45, "cjk"),
    ("unicode_emoji_🎉.txt", 45, "emoji"),
    ("unicode_" + ("n" * 80) + ".txt", 45, "long name"),

    # --- collision: the destination already holds this exact name, so the
    #     collision-suffixing path is compared rather than skipped ---
    ("duplicate.txt", 45, "SOURCE — must not overwrite the archived one"),
]

# Nested files. Invisible to the 1.5.0 flat scan by design — these exist to test
# v2's recursive mode and the archive-loop guard, where there is no Python
# reference to diff against.
NESTED_FILES: list[tuple[str, int, str]] = [
    ("deep/l1/file_l1.txt", 45, "depth 1"),
    ("deep/l1/l2/file_l2.txt", 45, "depth 2"),
    ("deep/l1/l2/l3/file_l3.txt", 45, "depth 3"),

    # Already inside the archive folder. A flat scan cannot reach these; a
    # recursive scan will, and must not re-process them.
    ("_Cleanup/2020-01-01/already_archived.txt", 500, "must never move again"),
]

# NOTE (Windows): `report.PDF` alongside `report.pdf`, and names with a trailing
# dot or a `*`, are not representable on NTFS — the filesystem folds or rejects
# them. Case-sensitivity and those metacharacters therefore can't be covered by
# an on-disk corpus here; they belong in the Rust unit tests instead.

# Rule variants the engines are driven with, one config per variant.
#
# A single OR rule is a poor discriminator: `age_days=7, pattern="*.txt", OR`
# matches a brand-new .txt on pattern AND a 45-day .pdf on age, so an age bug
# and a pattern bug are indistinguishable in the output. Each variant below
# isolates one axis.
#
# Note the `age_days <= 0` shortcut in check_file: it forces age_match=True, so
# isolating the *pattern* requires AND with age_days=0, not OR.
VARIANTS: dict[str, dict] = {
    # Age alone: empty pattern never matches (check_file only tests `if pattern`).
    "age_only": {
        "age_days": 30, "pattern": "", "rule_logic": "OR",
    },
    # Pattern alone: age_days=0 makes the age predicate trivially true, and AND
    # then reduces the rule to the pattern.
    "pattern_only": {
        "age_days": 0, "pattern": "*.txt", "rule_logic": "AND",
    },
    # Both predicates must hold: .txt AND older than 30 days.
    "and_both": {
        "age_days": 30, "pattern": "*.txt", "rule_logic": "AND",
    },
    # Either predicate.
    "or_both": {
        "age_days": 30, "pattern": "*.log", "rule_logic": "OR",
    },
    # Regex is FULL match in Python (`compiled.fullmatch`). This must match
    # regex_abc.log and must NOT match regex_xabcx.log — the single most likely
    # place for a port to silently diverge.
    "regex_fullmatch": {
        "age_days": 0, "pattern": r"regex_a.c\.log", "rule_logic": "AND",
        "use_regex": True,
    },
    "regex_digits": {
        "age_days": 0, "pattern": r"regex_backup_\d{4}\.bak", "rule_logic": "AND",
        "use_regex": True,
    },
    # Exclusions are evaluated before age and pattern.
    "exclusions_glob": {
        "age_days": 0, "pattern": "*", "rule_logic": "AND",
        "exclusions": ["age_*", "*.bak", "unicode_*"],
    },
    # Non-move actions still log; dry-run keeps them harmless.
    "action_copy": {
        "age_days": 0, "pattern": "*.txt", "rule_logic": "AND", "action": "copy",
    },
    "action_trash": {
        "age_days": 0, "pattern": "*.log", "rule_logic": "AND",
        "action": "delete_to_trash",
    },
    # A destination template naming the file itself, so the resolved path is a
    # file rather than a directory.
    "dest_filename_tokens": {
        "age_days": 0, "pattern": "*.txt", "rule_logic": "AND",
        "destination_folder": "_Sorted/{EXT}/{FILENAME}{EXT}",
    },
    "dest_folder_name": {
        "age_days": 0, "pattern": "*.txt", "rule_logic": "AND",
        "destination_folder": "_Sorted/{ORIGINAL_FOLDER_NAME}/{YYYY}",
    },
    # A template that RENAMES the file. 1.5.0 resolves the renamed target
    # correctly and then discards it: utils.py:407 passes the *source* stem and
    # extension to _atomic_claim_path, so the file lands as `name.txt` and the
    # user's `_backup` silently vanishes. The Rust port splits stem/ext from the
    # target instead. The two engines are therefore EXPECTED to disagree here —
    # see EXPECTED_DIVERGENCE in wet_parity.py.
    #
    # The bug lives inside `if not dry_run:`, so a dry run cannot reach it and
    # this variant is only meaningful under wet_parity.py.
    "dest_rename_tokens": {
        "age_days": 0, "pattern": "*.txt", "rule_logic": "AND",
        "destination_folder": "_Sorted/{FILENAME}_backup{EXT}",
    },
}

RULE_DEFAULTS = {
    "age_days": 0,
    "pattern": "*.*",
    "rule_logic": "OR",
    "use_regex": False,
    "action": "move",
    "destination_folder": "",
    "exclusions": [],
    "enabled": True,
}


def build(root: Path, now: datetime, force: bool) -> int:
    if root.exists():
        if not force:
            print(f"error: {root} already exists (use --force to replace)", file=sys.stderr)
            return 1
        shutil.rmtree(root)

    written = 0
    for rel, age_days, contents in FLAT_FILES + NESTED_FILES:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        stamp = (now - timedelta(days=age_days)).timestamp()
        os.utime(path, (stamp, stamp))
        written += 1

    # Pre-seed today's archive folder with a colliding name, so the engines are
    # forced to exercise collision suffixing. The template resolves to today's
    # date, so this has to be computed rather than hard-coded.
    today = datetime.now()
    archive = root / "_Cleanup" / f"{today:%Y-%m-%d}"
    archive.mkdir(parents=True, exist_ok=True)
    collision = archive / "duplicate.txt"
    collision.write_text("PRE-EXISTING — must survive untouched", encoding="utf-8")
    written += 1

    configs_dir = root.parent / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)
    for name, overrides in VARIANTS.items():
        rule = dict(RULE_DEFAULTS, **overrides, path=str(root.resolve()))
        config = {
            "folders": [rule],
            "excluded_folders": [],
            "settings": {
                "archive_path_template": "_Cleanup/{YYYY}-{MM}-{DD}",
                "dry_run_mode": True,
                "interval_minutes": 60,
                "schedule_type": "interval",
                "max_directory_depth": 0,
            },
        }
        (configs_dir / f"{name}.json").write_text(
            json.dumps(config, indent=4), encoding="utf-8"
        )

    print(f"wrote {written} files to {root}")
    print(f"wrote {len(VARIANTS)} rule variants to {configs_dir}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default="tools/parity/corpus/tree", type=Path)
    ap.add_argument(
        "--now",
        default="2026-08-14T12:00:00",
        help="fixed 'now' the ages are computed back from, for reproducibility",
    )
    ap.add_argument("--force", action="store_true", help="replace an existing corpus")
    args = ap.parse_args()

    return build(args.root, datetime.fromisoformat(args.now), args.force)


if __name__ == "__main__":
    raise SystemExit(main())
