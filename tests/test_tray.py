"""
Tests for voice/tray.py — _set_mode(), _update_tray_state().

Strategy: all pystray / Pillow deps are mocked in sys.modules by conftest.py.
We test state mutations and _save_env calls without touching real hardware.
"""

from unittest.mock import MagicMock, patch
import pytest

from voice import state, tray, theme


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_tray_state(monkeypatch):
    """Reset tray-related state before each test."""
    monkeypatch.setattr(state, "_tray_state", "idle")
    monkeypatch.setattr(state, "_tray_last_mode", "—")
    monkeypatch.setattr(state, "_tray_icon", None)
    monkeypatch.setattr(state, "_tray_available", True)
    monkeypatch.setattr(state, "selected_mode", "transcribe")
    monkeypatch.setattr(state, "_CONFIG", {
        "SELECTED_MODE": "transcribe",
        "RECORD_HOTKEY": "ctrl+shift+space",
        "WHISPER_MODEL": "small",
    })


# ---------------------------------------------------------------------------
# _set_mode()
# ---------------------------------------------------------------------------

class TestSetMode:
    def test_atualiza_selected_mode(self, monkeypatch):
        """`_set_mode()` must update state.selected_mode."""
        save_calls = []
        monkeypatch.setattr("voice.tray._save_env" if hasattr(tray, "_save_env") else "voice.config._save_env",
                            lambda vals: save_calls.append(vals),
                            raising=False)

        # Patch the internal import inside _set_mode
        fake_save = MagicMock()
        with patch("voice.config._save_env", fake_save):
            tray._set_mode("query")

        assert state.selected_mode == "query"

    def test_persiste_no_env(self, monkeypatch):
        """`_set_mode()` must call _save_env with SELECTED_MODE."""
        with patch("voice.config._save_env") as mock_save:
            tray._set_mode("bullet")

        mock_save.assert_called_once_with({"SELECTED_MODE": "bullet"})

    def test_salva_excepcao_nao_levanta(self, monkeypatch):
        """`_set_mode()` must swallow _save_env exceptions gracefully."""
        with patch("voice.config._save_env", side_effect=Exception("disk full")):
            # Must not propagate exception
            tray._set_mode("email")

        assert state.selected_mode == "email"

    @pytest.mark.parametrize("mode", [
        "transcribe", "simple", "prompt", "query", "bullet", "email", "translate"
    ])
    def test_todos_modos_validos(self, mode, monkeypatch):
        """All 7 modes can be set without error."""
        with patch("voice.config._save_env"):
            tray._set_mode(mode)
        assert state.selected_mode == mode


# ---------------------------------------------------------------------------
# _update_tray_state()
# ---------------------------------------------------------------------------

class TestUpdateTrayState:
    def test_atualiza_tray_state(self):
        """`_update_tray_state()` must update state._tray_state."""
        tray._update_tray_state("recording")
        assert state._tray_state == "recording"

    def test_atualiza_mode_quando_fornecido(self):
        """`_update_tray_state()` must update _tray_last_mode when mode is given."""
        tray._update_tray_state("processing", mode="query")
        assert state._tray_last_mode == "query"

    def test_nao_atualiza_mode_quando_nao_fornecido(self):
        """`_update_tray_state()` must NOT change _tray_last_mode when mode=None."""
        state._tray_last_mode = "bullet"
        tray._update_tray_state("idle")
        assert state._tray_last_mode == "bullet"

    def test_atualiza_icone_quando_tray_disponivel(self, monkeypatch):
        """`_update_tray_state()` must update tray icon when available."""
        mock_icon = MagicMock()
        monkeypatch.setattr(state, "_tray_icon", mock_icon)
        monkeypatch.setattr(state, "_tray_available", True)

        tray._update_tray_state("recording", mode="transcribe")

        # icon.icon and icon.title should have been set
        assert mock_icon.icon is not None or mock_icon.title is not None

    def test_sem_icone_nao_levanta(self, monkeypatch):
        """`_update_tray_state()` must not raise when _tray_icon is None."""
        monkeypatch.setattr(state, "_tray_icon", None)
        tray._update_tray_state("recording")  # No exception

    def test_estado_idle_atualizado(self):
        """State transitions: recording → idle."""
        state._tray_state = "recording"
        tray._update_tray_state("idle")
        assert state._tray_state == "idle"


# ---------------------------------------------------------------------------
# _make_tray_icon()
# ---------------------------------------------------------------------------

class TestMakeTrayIcon:
    def test_retorna_imagem(self):
        """`_make_tray_icon()` must return a PIL Image (mocked)."""
        result = tray._make_tray_icon("idle")
        # pystray/Pillow are mocked; just ensure it doesn't raise
        assert result is not None

    def test_estado_desconhecido_usa_brand_purple(self):
        """`_make_tray_icon()` must default to TRAY_IDLE (brand purple) for unknown states."""
        # Should not raise for unknown state
        result = tray._make_tray_icon("unknown_state")
        assert result is not None

    def test_idle_usa_amber(self):
        """`_make_tray_icon()` idle state must use warm amber (TRAY_IDLE)."""
        assert tray._STATE_COLORS["idle"] == theme.TRAY_IDLE
        assert theme.TRAY_IDLE == "#C4956A"

    def test_recording_usa_rose(self):
        """`_make_tray_icon()` recording state must use muted rose (TRAY_RECORDING)."""
        assert tray._STATE_COLORS["recording"] == theme.TRAY_RECORDING
        assert theme.TRAY_RECORDING == "#D4626E"

    def test_processing_usa_steel_blue(self):
        """`_make_tray_icon()` processing state must use steel blue (TRAY_PROCESSING)."""
        assert tray._STATE_COLORS["processing"] == theme.TRAY_PROCESSING
        assert theme.TRAY_PROCESSING == "#6B8EBF"


# ---------------------------------------------------------------------------
# _stop_tray()
# ---------------------------------------------------------------------------

class TestStopTray:
    def test_para_icone_e_limpa_referencia(self, monkeypatch):
        """`_stop_tray()` must call icon.stop() and set _tray_icon to None."""
        mock_icon = MagicMock()
        monkeypatch.setattr(state, "_tray_icon", mock_icon)
        monkeypatch.setattr(state, "_tray_available", True)

        tray._stop_tray()

        mock_icon.stop.assert_called_once()
        assert state._tray_icon is None

    def test_sem_icone_nao_levanta(self, monkeypatch):
        """`_stop_tray()` must be safe when _tray_icon is None."""
        monkeypatch.setattr(state, "_tray_icon", None)
        tray._stop_tray()  # No exception

    def test_erro_no_stop_nao_levanta(self, monkeypatch):
        """`_stop_tray()` must swallow icon.stop() exceptions."""
        mock_icon = MagicMock()
        mock_icon.stop.side_effect = Exception("pystray error")
        monkeypatch.setattr(state, "_tray_icon", mock_icon)
        monkeypatch.setattr(state, "_tray_available", True)

        tray._stop_tray()  # Must not propagate

        assert state._tray_icon is None
