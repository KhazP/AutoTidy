"""Pytest tests for UndoManager logic using tmp_path fixtures."""
import json
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from undo_manager import UndoManager


class MockConfigManager:
    def __init__(self, config_dir: Path):
        self._dir = config_dir

    def get_config_dir_path(self) -> Path:
        return self._dir


def _write_history(history_file: Path, entries: list[dict]):
    with open(history_file, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def history_dir(tmp_path):
    return tmp_path


@pytest.fixture
def undo_mgr(history_dir):
    cm = MockConfigManager(history_dir)
    return UndoManager(cm)


@pytest.fixture
def history_file(history_dir):
    return history_dir / "autotidy_history.jsonl"


# ── get_history_runs ──────────────────────────────────────────────────────────

def test_get_history_runs_empty(undo_mgr):
    assert undo_mgr.get_history_runs() == []


def test_get_history_runs_sorted_most_recent_first(undo_mgr, history_file):
    _write_history(history_file, [
        {"run_id": "run-1", "timestamp": "2023-10-26T10:00:00Z", "action_taken": "MOVED",
         "original_path": "/a", "destination_path": "/b"},
        {"run_id": "run-2", "timestamp": "2023-10-27T10:00:00Z", "action_taken": "MOVED",
         "original_path": "/c", "destination_path": "/d"},
        {"run_id": "run-1", "timestamp": "2023-10-26T10:01:00Z", "action_taken": "MOVED",
         "original_path": "/e", "destination_path": "/f"},
    ])
    runs = undo_mgr.get_history_runs()
    assert len(runs) == 2
    assert [r["run_id"] for r in runs] == ["run-2", "run-1"]


def test_get_history_runs_action_count(undo_mgr, history_file):
    _write_history(history_file, [
        {"run_id": "r1", "timestamp": "2023-01-01T00:00:00Z", "action_taken": "MOVED",
         "original_path": "/a", "destination_path": "/b"},
        {"run_id": "r1", "timestamp": "2023-01-01T00:01:00Z", "action_taken": "COPIED",
         "original_path": "/c", "destination_path": "/d"},
        {"run_id": "r2", "timestamp": "2023-01-02T00:00:00Z", "action_taken": "MOVED",
         "original_path": "/e", "destination_path": "/f"},
    ])
    runs = {r["run_id"]: r for r in undo_mgr.get_history_runs()}
    assert runs["r1"]["action_count"] == 2
    assert runs["r2"]["action_count"] == 1


# ── get_run_actions ───────────────────────────────────────────────────────────

def test_get_run_actions_sorted_ascending(undo_mgr, history_file):
    _write_history(history_file, [
        {"run_id": "r1", "timestamp": "2023-01-01T10:01:00Z", "action_taken": "MOVED",
         "original_path": "/b", "destination_path": "/dest/b"},
        {"run_id": "r1", "timestamp": "2023-01-01T10:00:00Z", "action_taken": "MOVED",
         "original_path": "/a", "destination_path": "/dest/a"},
    ])
    actions = undo_mgr.get_run_actions("r1")
    assert len(actions) == 2
    assert actions[0]["original_path"] == "/a"
    assert actions[1]["original_path"] == "/b"


def test_get_run_actions_missing_run(undo_mgr, history_file):
    _write_history(history_file, [
        {"run_id": "r1", "timestamp": "2023-01-01T10:00:00Z", "action_taken": "MOVED",
         "original_path": "/a", "destination_path": "/dest/a"},
    ])
    assert undo_mgr.get_run_actions("nonexistent") == []


# ── undo_action MOVED ─────────────────────────────────────────────────────────

def test_undo_moved_success(tmp_path, undo_mgr):
    source = tmp_path / "original.txt"
    dest = tmp_path / "archive" / "original.txt"
    dest.parent.mkdir()
    dest.write_text("content")

    action = {
        "action_taken": "MOVED",
        "original_path": str(source),
        "destination_path": str(dest),
    }
    success, msg = undo_mgr.undo_action(action)
    assert success, msg
    assert source.exists()
    assert not dest.exists()


def test_undo_moved_destination_missing(tmp_path, undo_mgr):
    action = {
        "action_taken": "MOVED",
        "original_path": str(tmp_path / "orig.txt"),
        "destination_path": str(tmp_path / "ghost.txt"),
    }
    success, msg = undo_mgr.undo_action(action)
    assert not success
    assert "does not exist" in msg.lower()


def test_undo_moved_original_already_exists(tmp_path, undo_mgr):
    source = tmp_path / "original.txt"
    source.write_text("existing")
    dest = tmp_path / "archive" / "original.txt"
    dest.parent.mkdir()
    dest.write_text("archive copy")

    action = {
        "action_taken": "MOVED",
        "original_path": str(source),
        "destination_path": str(dest),
    }
    success, msg = undo_mgr.undo_action(action)
    assert not success
    assert "already exists" in msg.lower()


# ── undo_action COPIED ────────────────────────────────────────────────────────

def test_undo_copied_success(tmp_path, undo_mgr):
    dest = tmp_path / "copy.txt"
    dest.write_text("copy content")
    stat = dest.stat()

    action = {
        "action_taken": "COPIED",
        "destination_path": str(dest),
        "copy_size": stat.st_size,
        "copy_mtime": stat.st_mtime,
    }
    success, msg = undo_mgr.undo_action(action)
    assert success, msg
    assert not dest.exists()


def test_undo_copied_size_changed(tmp_path, undo_mgr):
    dest = tmp_path / "copy.txt"
    dest.write_text("copy content")

    action = {
        "action_taken": "COPIED",
        "destination_path": str(dest),
        "copy_size": 9999,  # Wrong size
        "copy_mtime": dest.stat().st_mtime,
    }
    success, msg = undo_mgr.undo_action(action)
    assert not success
    assert "size" in msg.lower()
    assert dest.exists()  # File should NOT have been deleted


def test_undo_copied_no_metadata_still_works(tmp_path, undo_mgr):
    """Undo copy without stored metadata should still work (backward compat)."""
    dest = tmp_path / "copy.txt"
    dest.write_text("data")

    action = {
        "action_taken": "COPIED",
        "destination_path": str(dest),
    }
    success, msg = undo_mgr.undo_action(action)
    assert success, msg
    assert not dest.exists()


def test_undo_copied_missing_destination(tmp_path, undo_mgr):
    action = {
        "action_taken": "COPIED",
        "destination_path": str(tmp_path / "ghost.txt"),
    }
    success, msg = undo_mgr.undo_action(action)
    assert not success
    assert "does not exist" in msg.lower()


# ── undo_batch ────────────────────────────────────────────────────────────────

def test_undo_batch_success(tmp_path, undo_mgr, history_file):
    f1_orig = tmp_path / "f1.txt"
    f1_dest = tmp_path / "arch" / "f1.txt"
    f1_dest.parent.mkdir()
    f1_dest.write_text("file1")

    f2_orig = tmp_path / "f2.txt"
    f2_dest = tmp_path / "arch" / "f2.txt"
    f2_dest.write_text("file2")

    _write_history(history_file, [
        {"run_id": "batch-1", "timestamp": "2023-01-01T10:00:00Z", "action_taken": "MOVED",
         "original_path": str(f1_orig), "destination_path": str(f1_dest)},
        {"run_id": "batch-1", "timestamp": "2023-01-01T10:01:00Z", "action_taken": "MOVED",
         "original_path": str(f2_orig), "destination_path": str(f2_dest)},
    ])

    result = undo_mgr.undo_batch("batch-1")
    assert result["success_count"] == 2
    assert result["failure_count"] == 0
    assert f1_orig.exists()
    assert f2_orig.exists()


def test_undo_batch_partial_failure(tmp_path, undo_mgr, history_file):
    f1_orig = tmp_path / "ok.txt"
    f1_dest = tmp_path / "arch" / "ok.txt"
    f1_dest.parent.mkdir()
    f1_dest.write_text("data")

    _write_history(history_file, [
        {"run_id": "batch-2", "timestamp": "2023-01-01T10:00:00Z", "action_taken": "MOVED",
         "original_path": str(f1_orig), "destination_path": str(f1_dest)},
        {"run_id": "batch-2", "timestamp": "2023-01-01T10:01:00Z", "action_taken": "MOVED",
         "original_path": str(tmp_path / "ghost_orig.txt"),
         "destination_path": str(tmp_path / "ghost_dest.txt")},  # Missing
    ])

    result = undo_mgr.undo_batch("batch-2")
    assert result["success_count"] == 1
    assert result["failure_count"] == 1


def test_undo_batch_empty_run(undo_mgr):
    result = undo_mgr.undo_batch("nonexistent-run")
    assert result["success_count"] == 0
    assert result["failure_count"] == 0


# ── unsupported action ────────────────────────────────────────────────────────

def test_undo_unsupported_action(undo_mgr):
    action = {"action_taken": "DELETED_TO_TRASH"}
    success, msg = undo_mgr.undo_action(action)
    assert not success
    assert "not supported" in msg.lower()
