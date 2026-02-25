"""
Tests for load_config() — pure .env parsing logic.
No hardware or network deps touched.
"""
import os

import pytest

import voice


def _write_env(tmp_path, content: str) -> None:
    """Write a .env file in tmp_path."""
    (tmp_path / ".env").write_text(content, encoding="utf-8")


def test_defaults_sem_env(tmp_path, monkeypatch):
    """When no .env file exists, load_config returns all correct defaults."""
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
    # Ensure no .env in tmp_path
    env_path = tmp_path / ".env"
    assert not env_path.exists()

    cfg = voice.load_config()

    assert cfg["GEMINI_API_KEY"] is None
    assert cfg["LICENSE_KEY"] is None
    assert cfg["WHISPER_MODEL"] == "small"
    assert cfg["WHISPER_LANGUAGE"] == ""
    assert cfg["MAX_RECORD_SECONDS"] == 120
    assert cfg["AUDIO_DEVICE_INDEX"] is None
    assert cfg["QUERY_HOTKEY"] == "ctrl+shift+alt+space"
    assert cfg["QUERY_SYSTEM_PROMPT"] == ""
    assert cfg["HISTORY_MAX_ENTRIES"] == 500
    assert cfg["LOG_KEEP_SESSIONS"] == 5


def test_parse_valores_int(tmp_path, monkeypatch):
    """MAX_RECORD_SECONDS, HISTORY_MAX_ENTRIES, LOG_KEEP_SESSIONS become int."""
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
    _write_env(tmp_path, (
        "MAX_RECORD_SECONDS=60\n"
        "HISTORY_MAX_ENTRIES=200\n"
        "LOG_KEEP_SESSIONS=3\n"
    ))

    cfg = voice.load_config()

    assert cfg["MAX_RECORD_SECONDS"] == 60
    assert isinstance(cfg["MAX_RECORD_SECONDS"], int)
    assert cfg["HISTORY_MAX_ENTRIES"] == 200
    assert isinstance(cfg["HISTORY_MAX_ENTRIES"], int)
    assert cfg["LOG_KEEP_SESSIONS"] == 3
    assert isinstance(cfg["LOG_KEEP_SESSIONS"], int)


def test_placeholder_gemini_key(tmp_path, monkeypatch):
    """The placeholder 'your_gemini_api_key_here' is normalized to None."""
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
    _write_env(tmp_path, "GEMINI_API_KEY=your_gemini_api_key_here\n")

    cfg = voice.load_config()

    assert cfg["GEMINI_API_KEY"] is None


def test_comentarios_ignorados(tmp_path, monkeypatch):
    """Lines starting with '#' are treated as comments and ignored."""
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
    _write_env(tmp_path, (
        "# This is a comment\n"
        "WHISPER_MODEL=base\n"
        "# Another comment\n"
    ))

    cfg = voice.load_config()

    assert cfg["WHISPER_MODEL"] == "base"


def test_aspas_removidas(tmp_path, monkeypatch):
    """KEY=\"value\" and KEY='value' → stored without surrounding quotes."""
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
    _write_env(tmp_path, (
        'WHISPER_MODEL="base"\n'
        'QUERY_HOTKEY=\'ctrl+alt+space\'\n'
    ))

    cfg = voice.load_config()

    assert cfg["WHISPER_MODEL"] == "base"
    assert cfg["QUERY_HOTKEY"] == "ctrl+alt+space"


def test_chave_vazia_ignorada(tmp_path, monkeypatch):
    """KEY= (empty value) does not overwrite the default for int keys."""
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
    _write_env(tmp_path, (
        "MAX_RECORD_SECONDS=\n"
        "LOG_KEEP_SESSIONS=\n"
    ))

    cfg = voice.load_config()

    # Empty value → val is "" → `if key in config and val:` is False → default kept
    assert cfg["MAX_RECORD_SECONDS"] == 120
    assert cfg["LOG_KEEP_SESSIONS"] == 5
