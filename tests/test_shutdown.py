"""
Tests for voice/shutdown.py — graceful_shutdown() scenarios.

Strategy: monkeypatch state variables, mock _release_named_mutex (imported
by name in shutdown.py), and inject a fake voice.audio into sys.modules when
testing the transcription path.
"""
import sys
from unittest.mock import MagicMock, patch

import pytest

from voice import state, shutdown


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    """Reset all recording-related state before each test."""
    monkeypatch.setattr(state, "is_recording", False)
    monkeypatch.setattr(state, "frames_buf", [])
    monkeypatch.setattr(state, "current_mode", "transcribe")
    monkeypatch.setattr(state, "record_thread", None)
    monkeypatch.setattr(state, "_mutex_handle", None)
    state.stop_event.clear()
    yield
    state.stop_event.clear()


# ---------------------------------------------------------------------------
# Cenário 1: não estava gravando
# ---------------------------------------------------------------------------

def test_shutdown_sem_gravacao_sinaliza_stop():
    """When not recording, shutdown signals stop_event and releases mutex."""
    with patch("voice.shutdown._release_named_mutex") as mock_release:
        shutdown.graceful_shutdown()

    assert state.stop_event.is_set()
    mock_release.assert_called_once()


# ---------------------------------------------------------------------------
# Cenário 2: gravando mas sem frames capturados
# ---------------------------------------------------------------------------

def test_shutdown_com_gravacao_sem_frames(monkeypatch):
    """When recording but frames_buf is empty, no transcription is attempted."""
    monkeypatch.setattr(state, "is_recording", True)
    monkeypatch.setattr(state, "frames_buf", [])

    mock_thread = MagicMock()
    mock_thread.is_alive.return_value = False
    monkeypatch.setattr(state, "record_thread", mock_thread)

    mock_audio = MagicMock()

    with patch("voice.shutdown._release_named_mutex") as mock_release:
        with patch.dict(sys.modules, {"voice.audio": mock_audio}):
            shutdown.graceful_shutdown()

    mock_audio.transcribe.assert_not_called()
    assert state.stop_event.is_set()
    mock_release.assert_called_once()


# ---------------------------------------------------------------------------
# Cenário 3: gravando com frames — deve transcrever
# ---------------------------------------------------------------------------

def test_shutdown_com_gravacao_e_frames_transcreve(monkeypatch):
    """When recording with frames, shutdown calls transcribe before exiting."""
    monkeypatch.setattr(state, "is_recording", True)
    monkeypatch.setattr(state, "frames_buf", [b"frame1", b"frame2"])
    monkeypatch.setattr(state, "current_mode", "query")

    mock_thread = MagicMock()
    mock_thread.is_alive.return_value = False
    monkeypatch.setattr(state, "record_thread", mock_thread)

    transcribe_calls = []

    def fake_transcribe(frames, mode):
        transcribe_calls.append((list(frames), mode))

    mock_audio = MagicMock()
    mock_audio.transcribe = fake_transcribe

    with patch("voice.shutdown._release_named_mutex"):
        with patch.dict(sys.modules, {"voice.audio": mock_audio}):
            shutdown.graceful_shutdown()

    assert len(transcribe_calls) == 1
    assert transcribe_calls[0][1] == "query"
    assert b"frame1" in transcribe_calls[0][0]


# ---------------------------------------------------------------------------
# Cenário 4: mutex liberado mesmo quando ocorre exceção
# ---------------------------------------------------------------------------

def test_mutex_liberado_mesmo_em_excecao(monkeypatch):
    """Mutex is released via finally even if an exception occurs during shutdown."""
    monkeypatch.setattr(state, "is_recording", False)

    with patch("voice.shutdown._release_named_mutex") as mock_release:
        with patch.object(state.stop_event, "set", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                shutdown.graceful_shutdown()

    mock_release.assert_called_once()


# ---------------------------------------------------------------------------
# Cenário 5: thread de gravação ainda ativa — join é chamado
# ---------------------------------------------------------------------------

def test_shutdown_aguarda_thread_de_gravacao(monkeypatch):
    """When recording thread is alive, join(timeout=5) is called."""
    monkeypatch.setattr(state, "is_recording", True)
    monkeypatch.setattr(state, "frames_buf", [])

    mock_thread = MagicMock()
    mock_thread.is_alive.return_value = True  # Thread still running
    monkeypatch.setattr(state, "record_thread", mock_thread)

    with patch("voice.shutdown._release_named_mutex"):
        shutdown.graceful_shutdown()

    mock_thread.join.assert_called_once_with(timeout=5)
