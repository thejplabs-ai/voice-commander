"""
Shared fixtures for voice-commander tests.

Strategy: mock all heavy/hardware imports in sys.modules BEFORE importing voice,
so the module-level try/except block never hits the real packages.
The print patch in voice.py uses builtins.print — we restore it after import.
"""
import sys
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Build stub modules for every heavy dependency voice.py imports at module level
# ---------------------------------------------------------------------------

def _install_stubs():
    """Install lightweight stub modules so voice.py can be imported in tests."""
    stubs = {
        "sounddevice": MagicMock(),
        "numpy": MagicMock(),
        "winsound": MagicMock(),
        # google.generativeai (old-style, imported in tests for _get_gemini_client)
        "google": MagicMock(),
        "google.genai": MagicMock(),
        # pystray / Pillow / customtkinter — not needed for unit tests but may be imported
        "pystray": MagicMock(),
        "PIL": MagicMock(),
        "PIL.Image": MagicMock(),
        "customtkinter": MagicMock(),
    }
    for name, stub in stubs.items():
        sys.modules.setdefault(name, stub)
    # numpy was already imported for real just above (see _real_numpy) so setdefault
    # kept the genuine module in place — force the stub in now for the rest of the suite.
    sys.modules["numpy"] = stubs["numpy"]


# Capture the genuine numpy module BEFORE the stub is installed. Reused by the
# `real_numpy` fixture below so tests needing real numpy (e.g. test_extended_recording.py)
# never have to delete+reimport it from sys.modules — that reload path triggers numpy's
# own "The NumPy module was reloaded" UserWarning.
import numpy as _real_numpy  # noqa: E402

_install_stubs()

# Now import voice safely
import voice  # noqa: E402  (after stubs are in place)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_voice_paths(tmp_path, monkeypatch, request):
    """
    Global isolation (runs for every test by default): redirects
    voice.state._BASE_DIR / _log_path / _history_path to a per-test tmp dir,
    so the suite never writes into the repo's real voice.log / history.jsonl
    (voice/paths.py computes these at import time; consumers read them at call time).

    Opt-out: tests/test_openrouter_smoke.py needs the real repo .env/_BASE_DIR when
    RUN_OPENROUTER_SMOKE=1 (see its own module-scoped _bootstrap_state fixture) —
    skipped by filename rather than a marker to avoid registering a new pytest marker.
    """
    if request.fspath.basename == "test_openrouter_smoke.py":
        yield
        return
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
    monkeypatch.setattr(voice.state, "_log_path", str(tmp_path / "voice.log"))
    monkeypatch.setattr(voice.state, "_history_path", str(tmp_path / "history.jsonl"))
    yield


@pytest.fixture
def tmp_base_dir(tmp_path):
    """
    Thin alias: `_isolate_voice_paths` (autouse, above) already redirected
    voice.state._BASE_DIR/_log_path/_history_path to this same tmp_path.
    Kept so existing tests can still build expected paths off the returned value.
    """
    return tmp_path


@pytest.fixture
def real_numpy():
    """Genuine numpy module (not the MagicMock stub), captured once at conftest
    import time — see `_real_numpy` above. Avoids per-test delete+reimport reload
    warnings for tests that need real numpy math (e.g. test_extended_recording.py)."""
    return _real_numpy


@pytest.fixture
def mock_config(monkeypatch):
    """
    Return a controlled _CONFIG dict and patch voice.state._CONFIG with it.
    Tests can modify the returned dict as needed.
    """
    cfg = {
        "GEMINI_API_KEY": None,
        "LICENSE_KEY": None,
        "WHISPER_MODEL": "small",
        "WHISPER_LANGUAGE": "",
        "MAX_RECORD_SECONDS": 120,
        "AUDIO_DEVICE_INDEX": None,
        "QUERY_SYSTEM_PROMPT": "",
        "HISTORY_MAX_ENTRIES": 500,
        "LOG_KEEP_SESSIONS": 5,
        "VAD_THRESHOLD": 0.3,
    }
    monkeypatch.setattr(voice.state, "_CONFIG", cfg)
    return cfg
