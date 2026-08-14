"""Tests for _atomic_claim_path and two-phase move logic."""
import pytest
from pathlib import Path
from unittest.mock import patch


def test_atomic_claim_creates_file(tmp_path):
    """_atomic_claim_path creates the placeholder file."""
    from utils import _atomic_claim_path

    base = tmp_path / "dest"
    base.mkdir()

    p = _atomic_claim_path(base, "file", ".txt")
    assert p.exists()
    assert p.name == "file.txt"


def test_atomic_claim_unique_on_collision(tmp_path):
    """Second claim gets a different name than first."""
    from utils import _atomic_claim_path

    base = tmp_path / "dest"
    base.mkdir()

    p1 = _atomic_claim_path(base, "file", ".txt")
    p2 = _atomic_claim_path(base, "file", ".txt")
    assert p1 != p2
    assert p1.exists()
    assert p2.exists()


def test_atomic_claim_timestamp_fallback(tmp_path):
    """Falls back to timestamp name after max_attempts collisions."""
    from utils import _atomic_claim_path

    base = tmp_path / "dest"
    base.mkdir()

    # Pre-create file.txt and file_1.txt through file_3.txt
    (base / "file.txt").write_text("x")
    for i in range(1, 4):
        (base / f"file_{i}.txt").write_text("x")

    p = _atomic_claim_path(base, "file", ".txt", max_attempts=3)
    assert p.exists()
    assert p.suffix == ".txt"
    # Should be timestamp-based (longer name)
    assert len(p.stem) > len("file_3")


def test_two_phase_move_same_filesystem(tmp_path):
    """Two-phase move works on same filesystem."""
    from utils import process_file_action

    src_dir = tmp_path / "source"
    dst_dir = tmp_path / "dest"
    src_dir.mkdir()
    src_file = src_dir / "data.txt"
    src_file.write_text("content")

    calls = []
    success, msg = process_file_action(
        file_path=src_file,
        monitored_folder_path=src_dir,
        archive_path_template=str(dst_dir),
        action="move",
        dry_run=False,
        rule_pattern="*",
        rule_age_days=0,
        rule_use_regex=False,
        history_logger_callable=lambda d: calls.append(d),
        run_id="run1",
        destination_folder=None,
    )
    assert success, f"Move failed: {msg}"
    assert not src_file.exists()
    moved = dst_dir / "data.txt"
    assert moved.exists()
    assert moved.read_text() == "content"


def test_two_phase_move_cross_filesystem_fallback(tmp_path):
    """Two-phase move falls back to copy+verify+unlink when rename raises OSError."""
    from utils import process_file_action

    src_dir = tmp_path / "source"
    dst_dir = tmp_path / "dest"
    src_dir.mkdir()
    src_file = src_dir / "data.txt"
    src_file.write_text("content")

    calls = []

    def patched_rename(self, target):
        raise OSError("cross-device link")

    with patch.object(Path, "rename", patched_rename):
        success, msg = process_file_action(
            file_path=src_file,
            monitored_folder_path=src_dir,
            archive_path_template=str(dst_dir),
            action="move",
            dry_run=False,
            rule_pattern="*",
            rule_age_days=0,
            rule_use_regex=False,
            history_logger_callable=lambda d: calls.append(d),
            run_id="run1",
            destination_folder=None,
        )
    assert success, f"Cross-filesystem move failed: {msg}"
    assert not src_file.exists()
    assert (dst_dir / "data.txt").exists()
