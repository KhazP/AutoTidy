"""Tests for validate_archive_template."""
import pytest


def test_valid_simple_template():
    from utils import validate_archive_template
    ok, err = validate_archive_template("_Cleanup/{YYYY}-{MM}-{DD}")
    assert ok
    assert err == ""


def test_valid_template_with_filename():
    from utils import validate_archive_template
    ok, err = validate_archive_template("archive/{YYYY}/{FILENAME}{EXT}")
    assert ok, f"Should be valid but got: {err}"


def test_empty_template_is_valid():
    from utils import validate_archive_template
    ok, err = validate_archive_template("")
    assert ok


def test_all_allowed_placeholders():
    from utils import validate_archive_template
    ok, err = validate_archive_template("{YYYY}/{MM}/{DD}/{FILENAME}{EXT}_{ORIGINAL_FOLDER_NAME}")
    assert ok, f"Should be valid but got: {err}"


def test_traversal_rejected():
    from utils import validate_archive_template
    ok, err = validate_archive_template("../../etc/passwd")
    assert not ok
    assert ".." in err or "traversal" in err.lower()


def test_traversal_in_middle_rejected():
    from utils import validate_archive_template
    ok, err = validate_archive_template("archive/../../../evil")
    assert not ok


def test_unknown_placeholder_rejected():
    from utils import validate_archive_template
    ok, err = validate_archive_template("{UNKNOWN_FIELD}/file")
    assert not ok
    assert "UNKNOWN_FIELD" in err or "placeholder" in err.lower()


def test_dangerous_pipe_rejected():
    from utils import validate_archive_template
    ok, err = validate_archive_template("folder|cmd")
    assert not ok
    assert "|" in err or "dangerous" in err.lower()


def test_dangerous_semicolon_rejected():
    from utils import validate_archive_template
    ok, err = validate_archive_template("folder;rm -rf /")
    assert not ok


def test_dangerous_ampersand_rejected():
    from utils import validate_archive_template
    ok, err = validate_archive_template("folder&cmd")
    assert not ok


def test_dangerous_backtick_rejected():
    from utils import validate_archive_template
    ok, err = validate_archive_template("folder`whoami`")
    assert not ok
