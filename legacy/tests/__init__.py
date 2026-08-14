"""Test package for AutoTidy.

This module ensures the project root is on ``sys.path`` so that tests can
import application modules after being moved into the dedicated ``tests``
package."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if (root_str := str(ROOT_DIR)) not in sys.path:
    sys.path.insert(0, root_str)

__all__ = []
