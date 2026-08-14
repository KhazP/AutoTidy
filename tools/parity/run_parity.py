#!/usr/bin/env python3
"""Run both engines over every rule variant and report parity.

One command for the whole loop:

    python tools/parity/run_parity.py

Regenerates the corpus, runs the Python 1.5.0 engine and the Rust v2 engine over
each rule variant in dry-run, diffs the emitted history, and exits non-zero if
any variant diverges. Suitable as a CI gate.

Both engines read the SAME corpus tree. Dry-run means neither writes to it, so a
single copy is safe and keeps the comparison honest — differing mtimes between
two copies would be a source of spurious divergence.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True, **kwargs)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-corpus", action="store_true",
                    help="reuse the existing corpus instead of regenerating it")
    ap.add_argument("--variant", action="append",
                    help="run only this variant (repeatable)")
    ap.add_argument("--strict-details", action="store_true",
                    help="also require the human-readable 'details' text to match")
    args = ap.parse_args()

    corpus = HERE / "corpus"
    tree = corpus / "tree"
    configs = corpus / "configs"
    out = HERE / "out"

    if not args.skip_corpus:
        r = run([sys.executable, str(HERE / "make_corpus.py"), "--force"])
        if r.returncode != 0:
            print(r.stdout + r.stderr, file=sys.stderr)
            return r.returncode
        print(r.stdout.strip())

    if not configs.is_dir():
        print(f"error: no configs at {configs}; run without --skip-corpus", file=sys.stderr)
        return 2

    # Build the Rust CLI once up front so a compile error is reported plainly
    # rather than as N identical per-variant failures.
    print("\nbuilding rust engine...")
    r = run(["cargo", "build", "-q", "-p", "autotidy-cli"])
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        print("error: rust engine failed to build", file=sys.stderr)
        return 2

    names = sorted(p.stem for p in configs.glob("*.json"))
    if args.variant:
        names = [n for n in names if n in set(args.variant)]
        if not names:
            print("error: no matching variants", file=sys.stderr)
            return 2

    out.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    print()

    for name in names:
        cfg = configs / f"{name}.json"
        py_out = out / f"python.{name}.jsonl"
        rs_out = out / f"rust.{name}.jsonl"

        r = run([sys.executable, str(HERE / "run_python_engine.py"),
                 "--config", str(cfg), "--out", str(py_out)])
        if r.returncode != 0:
            print(f"{name:24} PYTHON ENGINE FAILED")
            print(r.stdout + r.stderr, file=sys.stderr)
            failures.append(name)
            continue

        r = run(["cargo", "run", "-q", "-p", "autotidy-cli", "--",
                 "scan", "--config", str(cfg), "--dry-run",
                 "--history-out", str(rs_out)])
        if r.returncode != 0:
            print(f"{name:24} RUST ENGINE FAILED")
            print(r.stdout + r.stderr, file=sys.stderr)
            failures.append(name)
            continue

        diff = [sys.executable, str(HERE / "diff_history.py"),
                "--python", str(py_out), "--python-root", str(tree),
                "--rust", str(rs_out), "--rust-root", str(tree)]
        if args.strict_details:
            diff.append("--strict-details")
        r = run(diff)

        if r.returncode == 0:
            summary = [l for l in r.stdout.splitlines() if l.startswith("python records")]
            print(f"{name:24} OK    {summary[0] if summary else ''}")
        else:
            print(f"{name:24} FAILED")
            print("\n".join("    " + l for l in r.stdout.splitlines()))
            failures.append(name)

    print()
    if failures:
        print(f"PARITY FAILED in {len(failures)}/{len(names)} variant(s): {', '.join(failures)}")
        return 1
    print(f"PARITY OK across all {len(names)} variant(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
