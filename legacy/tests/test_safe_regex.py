"""Tests for safe_regex_match ReDoS protection."""
import pytest


def test_normal_match():
    """Normal patterns match correctly."""
    from utils import safe_regex_match
    assert safe_regex_match(r".*\.txt", "file.txt") is not None
    assert safe_regex_match(r".*\.txt", "file.pdf") is None


def test_no_match_returns_none():
    """Non-matching pattern returns None."""
    from utils import safe_regex_match
    result = safe_regex_match(r"^abc$", "xyz")
    assert result is None


def test_invalid_regex_returns_none():
    """Invalid regex returns None gracefully."""
    from utils import safe_regex_match
    result = safe_regex_match(r"[invalid", "test")
    assert result is None


def test_exact_match():
    """Exact filename match works."""
    from utils import safe_regex_match
    result = safe_regex_match(r"report_\d{4}\.pdf", "report_2024.pdf")
    assert result is not None


def test_case_sensitivity():
    """Regex is case-sensitive by default."""
    from utils import safe_regex_match
    assert safe_regex_match(r"file\.TXT", "file.TXT") is not None
    assert safe_regex_match(r"file\.TXT", "file.txt") is None


def test_empty_string():
    """Empty string only matches empty pattern."""
    from utils import safe_regex_match
    assert safe_regex_match(r"", "") is not None
    assert safe_regex_match(r"a+", "") is None


def test_wildcard_pattern():
    """Wildcard .* matches any string."""
    from utils import safe_regex_match
    assert safe_regex_match(r".*", "anything.txt") is not None
