"""
Tests for _rotate_log() — renames current voice.log and trims old archived logs.
Uses tmp_base_dir fixture + monkeypatching datetime for a fixed timestamp.
"""
import datetime
import glob
import os
import time
from unittest.mock import patch, MagicMock

import pytest

import voice


FIXED_TS = "2026-01-15_10-30-00"
FIXED_DT = datetime.datetime(2026, 1, 15, 10, 30, 0)


def test_renomeia_voice_log(tmp_base_dir, mock_config):
    """Existing voice.log is renamed to voice.YYYY-MM-DD_HH-MM-SS.log."""
    log_file = tmp_base_dir / "voice.log"
    log_file.write_text("log content", encoding="utf-8")

    with patch("voice.logging_.datetime") as mock_dt:
        mock_dt.datetime.now.return_value = FIXED_DT
        mock_dt.date.today.return_value = datetime.date.today()
        mock_dt.date.fromisoformat = datetime.date.fromisoformat
        voice._rotate_log()

    archived = tmp_base_dir / f"voice.{FIXED_TS}.log"
    assert archived.exists(), f"Expected archived log at {archived}"
    assert not log_file.exists(), "Original voice.log should have been renamed"


def test_sem_voice_log_sem_erro(tmp_base_dir, mock_config):
    """When voice.log does not exist, _rotate_log() completes without raising."""
    log_file = tmp_base_dir / "voice.log"
    assert not log_file.exists()

    # Should not raise
    with patch("voice.logging_.datetime") as mock_dt:
        mock_dt.datetime.now.return_value = FIXED_DT
        mock_dt.date.today.return_value = datetime.date.today()
        mock_dt.date.fromisoformat = datetime.date.fromisoformat
        voice._rotate_log()


def _create_archived_logs(tmp_base_dir, count: int) -> list:
    """Create `count` archived log files with incrementally older mtimes."""
    paths = []
    base_time = time.time()
    for i in range(count):
        # Name uses zero-padded minutes to ensure glob matches the pattern
        name = f"voice.2026-01-{i + 1:02d}_10-00-00.log"
        p = tmp_base_dir / name
        p.write_text(f"session {i}", encoding="utf-8")
        # Set mtime: older files have smaller mtime (further in the past)
        mtime = base_time - (count - i) * 60  # most recent = largest mtime
        os.utime(str(p), (mtime, mtime))
        paths.append(str(p))
    return paths


def test_deleta_logs_antigos(tmp_base_dir, mock_config):
    """With 7 archived logs and keep=5, the 2 oldest are deleted."""
    mock_config["LOG_KEEP_SESSIONS"] = 5

    _create_archived_logs(tmp_base_dir, 7)

    # No current voice.log → rotation only does cleanup
    with patch("voice.logging_.datetime") as mock_dt:
        mock_dt.datetime.now.return_value = FIXED_DT
        mock_dt.date.today.return_value = datetime.date.today()
        mock_dt.date.fromisoformat = datetime.date.fromisoformat
        voice._rotate_log()

    pattern = str(tmp_base_dir / "voice.????-??-??_??-??-??.log")
    remaining = glob.glob(pattern)
    assert len(remaining) == 5, f"Expected 5 logs, got {len(remaining)}: {remaining}"


def test_resiliencia_erro_delete(tmp_base_dir, mock_config):
    """If os.remove raises an error, _rotate_log() continues without crashing."""
    mock_config["LOG_KEEP_SESSIONS"] = 1

    _create_archived_logs(tmp_base_dir, 3)

    original_remove = os.remove

    def failing_remove(path):
        raise PermissionError(f"Cannot delete {path}")

    with patch("voice.logging_.datetime") as mock_dt, patch("os.remove", side_effect=failing_remove):
        mock_dt.datetime.now.return_value = FIXED_DT
        mock_dt.date.today.return_value = datetime.date.today()
        mock_dt.date.fromisoformat = datetime.date.fromisoformat
        # Should NOT raise even though os.remove fails
        voice._rotate_log()
