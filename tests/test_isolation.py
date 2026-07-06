"""
Meta-test for the global autouse isolation fixture (tests/conftest.py::_isolate_voice_paths).

PRD-mandated safety net: the suite must never write into the repo's real voice.log /
history.jsonl. voice/paths.py computes state._BASE_DIR / _log_path / _history_path at
import time; voice/logging_.py reads those fields at call time (_log_print, _append_history).
If the autouse fixture in conftest.py is ever removed or broken, this test fails.
"""
import os

from voice import state
from voice.logging_ import _append_history


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_REAL_LOG_PATH = os.path.join(_REPO_ROOT, "voice.log")
_REAL_HISTORY_PATH = os.path.join(_REPO_ROOT, "history.jsonl")


def _snapshot(path):
    """(mtime, size) of a file, or None if it doesn't exist."""
    if not os.path.exists(path):
        return None
    st = os.stat(path)
    return (st.st_mtime, st.st_size)


def test_state_paths_point_inside_tmp(tmp_path):
    """state._BASE_DIR/_log_path/_history_path must be redirected into the pytest tmp dir."""
    assert state._BASE_DIR == str(tmp_path)
    assert state._log_path == str(tmp_path / "voice.log")
    assert state._history_path == str(tmp_path / "history.jsonl")


def test_real_writes_land_in_tmp_and_repo_files_are_untouched(tmp_path, mock_config):
    """Exercise the actual write paths (_append_history + print) and prove the real
    repo files never change, by comparing mtime/size before and after."""
    before_log = _snapshot(_REAL_LOG_PATH)
    before_history = _snapshot(_REAL_HISTORY_PATH)

    _append_history("transcribe", "raw text", "processed text", 1.23)
    print("[TEST] isolation smoke write")

    tmp_history = tmp_path / "history.jsonl"
    tmp_log = tmp_path / "voice.log"
    assert tmp_history.exists()
    assert tmp_log.exists()
    assert "raw text" in tmp_history.read_text(encoding="utf-8")
    assert "[TEST] isolation smoke write" in tmp_log.read_text(encoding="utf-8")

    after_log = _snapshot(_REAL_LOG_PATH)
    after_history = _snapshot(_REAL_HISTORY_PATH)
    assert after_log == before_log, "real repo voice.log changed — isolation leaked"
    assert after_history == before_history, "real repo history.jsonl changed — isolation leaked"
