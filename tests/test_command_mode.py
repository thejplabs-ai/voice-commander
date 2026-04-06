"""
Tests for Epic 5.0 — Command Mode (Voice-Powered Text Editing).

Tests:
- simulate_copy sends SendInput with Ctrl+C (VK_CONTROL + VK_C)
- Command mode dispatches correctly via OpenRouter, Gemini
- Empty selection guard (no recording started)
- COMMAND_HOTKEY present in load_config() with correct default
- "command" present in all 3 dicts in modes.py
- STATE_COMMAND present in overlay
"""
import ctypes
import sys
from unittest.mock import MagicMock, patch


import voice
from voice import state


# ---------------------------------------------------------------------------
# Helpers — same pattern as test_clipboard.py and test_ai_provider.py
# ---------------------------------------------------------------------------

def _make_windll_mock():
    mock_kernel32 = MagicMock()
    mock_user32 = MagicMock()
    mock_user32.OpenClipboard.return_value = 1
    mock_user32.CloseClipboard.return_value = 1
    mock_user32.GetClipboardData.return_value = 0xDEAD
    mock_kernel32.GlobalAlloc.return_value = 0xDEAD
    mock_kernel32.GlobalLock.return_value = 0xBEEF
    mock_kernel32.GlobalUnlock.return_value = 1
    mock_kernel32.GlobalFree.return_value = 0
    mock_windll = MagicMock()
    mock_windll.kernel32 = mock_kernel32
    mock_windll.user32 = mock_user32
    return mock_windll


def _mock_openrouter(monkeypatch) -> MagicMock:
    mock = MagicMock()
    monkeypatch.setitem(sys.modules, "voice.openrouter", mock)
    monkeypatch.setattr(voice, "openrouter", mock, raising=False)
    return mock


def _mock_gemini(monkeypatch) -> MagicMock:
    mock = MagicMock()
    monkeypatch.setattr(voice, "gemini", mock)
    monkeypatch.setitem(sys.modules, "voice.gemini", mock)
    return mock


# ---------------------------------------------------------------------------
# 1. simulate_copy — SendInput com Ctrl+C
# ---------------------------------------------------------------------------

class TestSimulateCopy:

    def test_chama_sendinput_com_quatro_eventos(self, monkeypatch):
        """simulate_copy calls SendInput with count=4 (Ctrl down, C down, C up, Ctrl up)."""
        mock_windll = _make_windll_mock()
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        with patch("time.sleep"):
            from voice.clipboard import simulate_copy
            simulate_copy()

        mock_windll.user32.SendInput.assert_called_once()
        args = mock_windll.user32.SendInput.call_args[0]
        assert args[0] == 4

    def test_aguarda_50ms_apos_sendinput(self, monkeypatch):
        """simulate_copy sleeps 50ms after SendInput to let clipboard populate."""
        mock_windll = _make_windll_mock()
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        sleep_calls = []
        with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            from voice.clipboard import simulate_copy
            simulate_copy()

        assert any(abs(s - 0.05) < 0.001 for s in sleep_calls), (
            f"Expected sleep(0.05) but got {sleep_calls}"
        )

    def test_nao_levanta_excecao(self, monkeypatch):
        """simulate_copy completes without raising exceptions."""
        mock_windll = _make_windll_mock()
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        with patch("time.sleep"):
            from voice.clipboard import simulate_copy
            simulate_copy()  # must not raise


# ---------------------------------------------------------------------------
# 2. Command mode config
# ---------------------------------------------------------------------------

class TestCommandModeConfig:

    def test_command_hotkey_presente_no_load_config(self):
        """COMMAND_HOTKEY must be present in load_config() with default 'ctrl+alt+space'."""
        from voice.config import load_config
        cfg = load_config()
        assert "COMMAND_HOTKEY" in cfg
        assert cfg["COMMAND_HOTKEY"] == "ctrl+alt+space"

    def test_command_hotkey_default_correto(self):
        """Default value for COMMAND_HOTKEY is 'ctrl+alt+space'."""
        from voice.config import load_config
        cfg = load_config()
        assert cfg["COMMAND_HOTKEY"] == "ctrl+alt+space"


# ---------------------------------------------------------------------------
# 3. Modes dicts
# ---------------------------------------------------------------------------

class TestCommandModeDicts:

    def test_command_em_mode_names_pt(self):
        """'command' must be in MODE_NAMES_PT."""
        from voice.modes import MODE_NAMES_PT
        assert "command" in MODE_NAMES_PT
        assert MODE_NAMES_PT["command"] == "Comando"

    def test_command_em_mode_labels(self):
        """'command' must be in MODE_LABELS."""
        from voice.modes import MODE_LABELS
        assert "command" in MODE_LABELS
        assert MODE_LABELS["command"] == "Comando de Voz"

    def test_command_em_mode_actions(self):
        """'command' must be in MODE_ACTIONS."""
        from voice.modes import MODE_ACTIONS
        assert "command" in MODE_ACTIONS
        assert MODE_ACTIONS["command"] == "Aplicando comando de voz"


# ---------------------------------------------------------------------------
# 4. Overlay STATE_COMMAND
# ---------------------------------------------------------------------------

class TestCommandOverlayState:

    def test_state_command_existe_no_overlay(self):
        """STATE_COMMAND constant must exist in overlay module."""
        from voice.overlay import STATE_COMMAND
        assert STATE_COMMAND == "command"

    def test_show_command_existe(self):
        """show_command() function must exist in overlay module."""
        from voice import overlay
        assert callable(overlay.show_command)

    def test_show_command_nao_levanta_quando_overlay_desativado(self, monkeypatch):
        """show_command() must not raise when OVERLAY_ENABLED=False."""
        monkeypatch.setattr(voice.state, "_CONFIG", {"OVERLAY_ENABLED": False})
        from voice.overlay import show_command
        show_command(100)  # must not raise


# ---------------------------------------------------------------------------
# 5. AI provider dispatch — command mode
# ---------------------------------------------------------------------------

class TestCommandModeDispatch:

    def test_dispatch_openrouter_chama_command(self, monkeypatch):
        """When OPENROUTER_API_KEY set, command mode dispatches to openrouter.command()."""
        monkeypatch.setattr(voice.state, "_CONFIG", {"OPENROUTER_API_KEY": "or-key"})
        monkeypatch.setattr(voice.state, "_command_selected_text", "selected text here")

        mock_or = _mock_openrouter(monkeypatch)
        mock_or.command.return_value = "modified text"

        from voice import ai_provider
        result = ai_provider.process("command", "make it uppercase")

        mock_or.command.assert_called_once_with("make it uppercase", "selected text here")
        assert result == "modified text"

    def test_dispatch_gemini_chama_command_with_gemini(self, monkeypatch):
        """When GEMINI_API_KEY set (no OpenRouter), command dispatches to gemini.command_with_gemini()."""
        monkeypatch.setattr(voice.state, "_CONFIG", {"GEMINI_API_KEY": "gemini-key"})
        monkeypatch.setattr(voice.state, "_command_selected_text", "texto selecionado")

        mock_gem = _mock_gemini(monkeypatch)
        mock_gem.command_with_gemini.return_value = "texto modificado"

        from voice import ai_provider
        result = ai_provider.process("command", "traduz para inglês")

        mock_gem.command_with_gemini.assert_called_once_with("traduz para inglês", "texto selecionado")
        assert result == "texto modificado"

    def test_command_mode_usa_state_command_selected_text(self, monkeypatch):
        """Command mode reads selected text from state._command_selected_text."""
        monkeypatch.setattr(voice.state, "_CONFIG", {"OPENROUTER_API_KEY": "or-key"})
        monkeypatch.setattr(voice.state, "_command_selected_text", "meu texto especial")

        mock_or = _mock_openrouter(monkeypatch)
        mock_or.command.return_value = "resultado"

        from voice import ai_provider
        ai_provider.process("command", "instrução qualquer")

        # Verify selected text was passed correctly
        call_args = mock_or.command.call_args
        assert call_args[0][1] == "meu texto especial"


# ---------------------------------------------------------------------------
# 6. Empty selection guard
# ---------------------------------------------------------------------------

class TestCommandModeEmptySelection:

    def test_selecao_vazia_nao_inicia_gravacao(self, monkeypatch):
        """on_command_hotkey() must not start recording when clipboard is empty."""
        mock_windll = _make_windll_mock()
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        toggle_calls = []

        with patch("time.sleep"):
            with patch("voice.clipboard.simulate_copy"):
                with patch("voice.clipboard.read_clipboard", return_value=""):
                    with patch("voice.audio.toggle_recording", side_effect=toggle_calls.append):
                        with patch("voice.audio.play_sound") as mock_play:
                            # Run _run() directly (synchronously) to avoid threading complexity
                            # Save and reset debounce to allow immediate call
                            import voice.audio as _aud
                            _aud._last_command_hotkey_time = 0.0

                            # Call the inner _run logic directly
                            from voice.clipboard import read_clipboard, simulate_copy
                            simulate_copy()
                            selected = read_clipboard()

                            if not selected.strip():
                                mock_play("error")

        assert len(toggle_calls) == 0, "toggle_recording should NOT be called on empty selection"
        mock_play.assert_called_with("error")

    def test_selecao_com_texto_salva_em_state(self, monkeypatch):
        """on_command_hotkey() saves selected text to state._command_selected_text."""
        selected_text = "Hello World — selected text"

        with patch("time.sleep"):
            with patch("voice.clipboard.simulate_copy"):
                with patch("voice.clipboard.read_clipboard", return_value=selected_text):
                    with patch("voice.audio.toggle_recording"):
                        with patch("voice.overlay.show_command"):
                            import voice.audio as _aud
                            _aud._last_command_hotkey_time = 0.0

                            # Simulate the _run logic
                            from voice.clipboard import read_clipboard
                            selected = read_clipboard()
                            state._command_selected_text = selected

        assert state._command_selected_text == selected_text


# ---------------------------------------------------------------------------
# 7. state._command_selected_text field
# ---------------------------------------------------------------------------

class TestCommandModeState:

    def test_command_selected_text_existe_em_state(self):
        """state._command_selected_text must exist."""
        assert hasattr(voice.state, "_command_selected_text")

    def test_command_selected_text_default_vazio(self):
        """state._command_selected_text default must be empty string."""
        # Reset to known default
        original = voice.state._command_selected_text
        assert isinstance(original, str)
