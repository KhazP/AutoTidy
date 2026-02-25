"""Pytest configuration for AutoTidy tests."""
import sys
from pathlib import Path

# Ensure project root is on sys.path so tests can import project modules
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
