# Legacy — AutoTidy 1.5.0 (Python / PyQt6)

**This is not the application.** AutoTidy 2.0.0 is a Rust + Tauri app; its
source lives in [`crates/`](../crates), [`src-tauri/`](../src-tauri) and
[`src/`](../src). Nothing in this directory is built, packaged or shipped.

## Why it is still here

It is the **executable specification** for the rewrite.

The 2.0 port had to reproduce a decade of accumulated behaviour exactly —
including behaviour that is not obvious from reading the code, and some that is
arguably wrong but which users depend on. Rather than trusting a careful read,
the two engines are run over an identical corpus and their output diffed:

```bash
python tools/parity/run_parity.py    # compares the decisions each engine makes
python tools/parity/wet_parity.py    # compares the files each engine produces
```

Delete this directory and that verification stops working.

## What it caught

Real divergences found by diffing against this code, each of which would have
shipped silently:

- **Glob matching is case-insensitive on Windows.** `check_file` uses
  `fnmatch.fnmatch`, not `fnmatchcase`, and `fnmatch` normcases both operands.
  A straight port to a case-sensitive matcher would have quietly stopped
  matching files that users' rules match today, with no error to notice.
- **Renaming destination templates silently lost the rename.**
  `_atomic_claim_path` was passed the *source* stem and extension
  (`utils.py:407`), discarding what a `{FILENAME}_backup{EXT}` template had just
  computed. Reachable only on a real run, never in a dry run.
- **77 history records carry no `run_id`.** In Python `None == ""` is false so
  they never grouped; in Rust they deserialise to `""` and would have collapsed
  into one undoable "run" that a single click would unwind.

The first two are pinned by parity variants; the third by unit tests.

## Running it

The GUI needs PyQt6, which the parity harness does not:

```bash
cd legacy
pip install -r requirements.txt        # engine only
pip install -e ".[gui]"                # add PyQt6 to run the old UI
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest
```

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` avoids unrelated plugins in the ambient
environment interfering with collection.

## Licensing note

1.5.0 was published under MPL-2.0 while shipping a binary that bundled PyQt6,
which is GPL-v3-or-commercial — not a clean combination. This is one of the
problems 2.0.0 resolves: the Rust and Tauri stack is MIT/Apache-2.0 throughout.
