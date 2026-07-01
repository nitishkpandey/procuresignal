"""Unit tests for the smoke test's pure WS-frame validator."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from smoke_test import assert_valid_frame_sequence  # noqa: E402


def test_valid_stream_sequence():
    frames = [
        {"type": "start", "content": ""},
        {"type": "stream", "content": "Hi"},
        {"type": "end", "content": "done"},
    ]
    assert_valid_frame_sequence(frames)  # should not raise


def test_valid_error_sequence():
    frames = [
        {"type": "start", "content": ""},
        {"type": "error", "content": "boom"},
    ]
    assert_valid_frame_sequence(frames)  # start then clean error is valid


def test_missing_start_raises():
    with pytest.raises(AssertionError):
        assert_valid_frame_sequence([{"type": "stream", "content": "x"}])


def test_unknown_type_raises():
    with pytest.raises(AssertionError):
        assert_valid_frame_sequence(
            [{"type": "start", "content": ""}, {"type": "bogus", "content": "x"}]
        )


def test_unterminated_raises():
    with pytest.raises(AssertionError):
        assert_valid_frame_sequence(
            [{"type": "start", "content": ""}, {"type": "stream", "content": "x"}]
        )
