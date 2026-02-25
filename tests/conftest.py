"""
Shared fixtures for voice-commander tests.

Strategy: mock all heavy/hardware imports in sys.modules BEFORE importing voice,
so the module-level try/except block never hits the real packages.
The print patch in voice.py uses builtins.print — we restore it after import.
"""
import builtins
import importlib
import sys
import types
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
        "keyboard": MagicMock(),
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


_install_stubs()

# Now import voice safely
import voice  # noqa: E402  (after stubs are in place)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_base_dir(tmp_path, monkeypatch):
    """
    Redirect voice module globals to use tmp_path instead of the real project dir.
    Patches:
      - voice.state._BASE_DIR
      - voice.state._log_path
      - voice.state._history_path
    Returns tmp_path so tests can build expected paths.
    """
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
    monkeypatch.setattr(voice.state, "_log_path", str(tmp_path / "voice.log"))
    monkeypatch.setattr(voice.state, "_history_path", str(tmp_path / "history.jsonl"))
    return tmp_path


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
        "QUERY_HOTKEY": "ctrl+shift+alt+space",
        "QUERY_SYSTEM_PROMPT": "",
        "HISTORY_MAX_ENTRIES": 500,
        "LOG_KEEP_SESSIONS": 5,
    }
    monkeypatch.setattr(voice.state, "_CONFIG", cfg)
    return cfg
