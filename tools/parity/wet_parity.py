#!/usr/bin/env python3
"""Wet-run parity: compare the two engines by the *filesystem they produce*.

The dry-run harness (`run_parity.py`) compares emitted history, which is the
right check for the decision logic — but it structurally cannot reach the
commit path. In 1.5.0 the collision-claiming code lives inside `if not dry_run:`
(utils.py:403), so a dry run never exercises `_atomic_claim_path`, never renames
anything, and never suffixes a colliding name for real.

That is precisely where a file-destroying bug would live, so this runs both
engines FOR REAL over two disposable copies of the same corpus and compares the
resulting trees by relative path and content hash.

Everything happens under a scratch directory. It never touches the source
corpus, and never runs against a real user config.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# The corpus deliberately contains unicode filenames; a cp1252 console would
# crash the report rather than showing the divergence it was run to find.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]

# The headless engine driver. Named `autotidy-cli`, NOT `autotidy`: the Tauri
# app's binary is `AutoTidy`, and Windows filenames are case-insensitive, so the
# two would be the same file on disk and whichever built last would win. When
# that happened this harness silently "ran the engine", actually launched the
# GUI, moved nothing, and reported every variant as a divergence.
RUST_CLI = REPO_ROOT / "target" / "release" / (
    "autotidy-cli.exe" if sys.platform == "win32" else "autotidy-cli"
)

# Variants where the engines are SUPPOSED to disagree, because the Rust port
# fixes a bug rather than reproducing it. For these, matching trees are the
# failure: it would mean the fix regressed back to 1.5.0's behaviour.
EXPECTED_DIVERGENCE: dict[str, str] = {
    "dest_rename_tokens": (
        "1.5.0 passes the SOURCE stem/ext to _atomic_claim_path (utils.py:407), "
        "discarding the rename a {FILENAME}-style template just performed, so "
        "files land as `name.txt` instead of `name_backup.txt`. Rust splits "
        "stem/ext from the resolved target and keeps the rename."
    ),
}


def snapshot(root: Path) -> dict[str, str]:
    """Map every file's path (relative, slash-normalised) to a content hash.

    Path keys are casefolded on Windows because NTFS is case-insensitive: a
    comparison that distinguishes `_Sorted/.txt/a` from `_Sorted/.TXT/a` is
    modelling a filesystem the user does not have, and reports as a defect
    something that is a single directory on disk.

    This is not hypothetical. With a `{EXT}` template and a corpus containing
    both `.txt` and `.TXT` files, the destination directory takes the case of
    whichever file is processed first — so the two engines legitimately differ:
    Python follows NTFS enumeration order, while the Rust scanner sorts its
    discovery list (deliberately, so collision suffixes are reproducible).
    Every file still lands in the same directory with identical content.
    """
    fold = (lambda s: s.casefold()) if sys.platform == "win32" else (lambda s: s)
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = fold(path.relative_to(root).as_posix())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        out[rel] = digest
    return out


def write_config(template: Path, tree: Path, dest: Path) -> None:
    """Re-point a variant config at a specific tree copy, wet."""
    config = json.loads(template.read_text(encoding="utf-8"))
    for rule in config.get("folders", []):
        rule["path"] = str(tree)
    config.setdefault("settings", {})["dry_run_mode"] = False
    dest.write_text(json.dumps(config, indent=4), encoding="utf-8")


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True)


def compare(name: str, py: dict[str, str], rs: dict[str, str], verbose: bool) -> int:
    """Return 0 when the variant behaved as expected, non-zero otherwise."""
    only_py = sorted(set(py) - set(rs))
    only_rs = sorted(set(rs) - set(py))
    differing = sorted(k for k in set(py) & set(rs) if py[k] != rs[k])
    total = len(only_py) + len(only_rs) + len(differing)

    expected = EXPECTED_DIVERGENCE.get(name)
    if expected is not None:
        if total:
            print(f"{name:24} {'DIVERGED (expected)':20} "
                  f"python {len(py)} / rust {len(rs)} files")
            print(f"    reason: {expected}")
            if verbose:
                for k in only_py[:4]:
                    print(f"      python-only: {k}")
                for k in only_rs[:4]:
                    print(f"      rust-only:   {k}")
            return 0
        print(f"{name:24} {'REGRESSED':20} trees match, but this variant must "
              f"diverge — the fix was lost")
        print(f"    expected: {expected}")
        return 1

    if total and verbose:
        for k in only_py:
            print(f"    ONLY IN PYTHON TREE  {k}")
        for k in only_rs:
            print(f"    ONLY IN RUST TREE    {k}")
        for k in differing:
            print(f"    CONTENT DIFFERS      {k}")

    status = "OK" if total == 0 else f"FAILED ({total})"
    print(f"{name:24} {status:20} python {len(py)} / rust {len(rs)} files")
    return total


def verify_cli() -> str | None:
    """Confirm RUST_CLI is the engine driver and not something else entirely.

    Worth the round-trip because the failure it catches is silent and total: if
    another binary occupies this path, every variant reports as a divergence and
    the output reads like a catastrophic engine regression rather than a build
    problem. Returns an error message, or None when the binary looks right.
    """
    if not RUST_CLI.exists():
        return f"{RUST_CLI} does not exist"
    try:
        proc = subprocess.run([str(RUST_CLI), "--help"], cwd=REPO_ROOT,
                              text=True, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"could not run {RUST_CLI}: {exc}"

    blob = (proc.stdout or "") + (proc.stderr or "")
    if "headless AutoTidy engine" not in blob:
        return (
            f"{RUST_CLI} is not the AutoTidy CLI — `--help` printed "
            f"{len(blob)} bytes and none of it was the usage banner.\n"
            "    A GUI binary here produces no console output at all, which is "
            "exactly what a name collision looks like.\n"
            "    A plain rebuild will NOT fix this: cargo sees the crate's own\n"
            "    sources unchanged and skips relinking, leaving the wrong file\n"
            "    in place. Force it:\n"
            "        cargo clean -p autotidy-cli --release\n"
            "        cargo build --release -p autotidy-cli"
        )
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant", action="append",
                    help="run only this variant (repeatable)")
    ap.add_argument("--keep", action="store_true",
                    help="keep the scratch directory for inspection")
    ap.add_argument("--skip-trash", action="store_true", default=True,
                    help="skip variants that send files to the recycle bin "
                         "(default: on, so a test run does not fill it)")
    ap.add_argument("--include-trash", dest="skip_trash", action="store_false")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="list every differing path")
    args = ap.parse_args()

    corpus = HERE / "corpus"
    tree = corpus / "tree"
    configs = corpus / "configs"
    if not tree.is_dir():
        print("error: no corpus; run make_corpus.py first", file=sys.stderr)
        return 2

    r = run(["cargo", "build", "-q", "--release", "-p", "autotidy-cli"])
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        return 2

    # Cargo skips relinking when the crate's own sources are unchanged, so a
    # successful build here does NOT guarantee the right binary is on disk.
    if problem := verify_cli():
        print(f"error: {problem}", file=sys.stderr)
        return 2

    names = sorted(p.stem for p in configs.glob("*.json"))
    if args.variant:
        names = [n for n in names if n in set(args.variant)]
    elif args.skip_trash:
        # A wet run of these really does move files to the user's recycle bin.
        names = [n for n in names if "trash" not in n]

    scratch = Path(tempfile.mkdtemp(prefix="autotidy-wet-"))
    failures: list[str] = []
    print(f"scratch: {scratch}\n")

    try:
        for name in names:
            case = scratch / name
            py_tree, rs_tree = case / "python" / "tree", case / "rust" / "tree"
            # Two pristine copies, so neither engine sees the other's writes.
            shutil.copytree(tree, py_tree)
            shutil.copytree(tree, rs_tree)

            py_cfg, rs_cfg = case / "python.json", case / "rust.json"
            write_config(configs / f"{name}.json", py_tree, py_cfg)
            write_config(configs / f"{name}.json", rs_tree, rs_cfg)

            r = run([sys.executable, str(HERE / "run_python_engine.py"),
                     "--config", str(py_cfg), "--out", str(case / "python.jsonl"), "--wet"])
            if r.returncode != 0:
                print(f"{name:24} PYTHON FAILED\n{r.stdout}{r.stderr}", file=sys.stderr)
                failures.append(name)
                continue

            r = run([str(RUST_CLI), "scan", "--config", str(rs_cfg),
                     "--history-out", str(case / "rust.jsonl")])
            if r.returncode != 0:
                print(f"{name:24} RUST FAILED\n{r.stdout}{r.stderr}", file=sys.stderr)
                failures.append(name)
                continue

            if compare(name, snapshot(py_tree), snapshot(rs_tree), args.verbose):
                failures.append(name)

        print()
        if failures:
            print(f"WET PARITY FAILED in {len(failures)}/{len(names)}: {', '.join(failures)}")
            print(f"scratch kept at {scratch}")
            return 1
        print(f"WET PARITY OK across all {len(names)} variant(s)")
        return 0
    finally:
        if not args.keep and not failures:
            shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
