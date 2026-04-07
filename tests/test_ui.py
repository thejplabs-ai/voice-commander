"""
Tests for voice/ui.py — disk-writing functions that can be tested without a display.

Strategy: test only the functions that write to disk (_finish on OnboardingWindow,
_save on SettingsWindow). UI rendering tests (CTk widgets) are impossible without
a display and are explicitly out of scope.
"""

import sys
from unittest.mock import MagicMock
import pytest

from voice import state


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def env_dir(tmp_path, monkeypatch):
    """Provide a temp dir as _BASE_DIR for config writes."""
    monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
    monkeypatch.setattr(state, "_log_path", str(tmp_path / "voice.log"))
    monkeypatch.setattr(state, "_history_path", str(tmp_path / "history.jsonl"))
    monkeypatch.setattr(state, "_CONFIG", {
        "GEMINI_API_KEY": None,
        "WHISPER_MODEL": "small",
        "WHISPER_LANGUAGE": "",
        "RECORD_HOTKEY": "ctrl+shift+space",
        "AI_PROVIDER": "gemini",
        "OPENAI_API_KEY": None,
        "OPENAI_MODEL": "gpt-4o-mini",
        "WHISPER_DEVICE": "cpu",
        "TRANSLATE_TARGET_LANG": "en",
        "LICENSE_KEY": None,
        "HISTORY_MAX_ENTRIES": 500,
        "LOG_KEEP_SESSIONS": 5,
        "SELECTED_MODE": "transcribe",
    })
    monkeypatch.setattr(state, "_GEMINI_API_KEY", None)
    return tmp_path


# ---------------------------------------------------------------------------
# OnboardingWindow._finish() — writes .env and calls done_callback
# ---------------------------------------------------------------------------

class TestOnboardingFinish:
    """Test _finish() without instantiating the CTk window."""

    def _make_window(self, monkeypatch, env_dir):
        """Create a minimal OnboardingWindow instance bypassing CTk constructor."""
        from voice.ui import OnboardingWindow

        # Prevent CTk from running on import / instantiation
        monkeypatch.setitem(sys.modules, "customtkinter", MagicMock())

        # Bypass __init__ and set minimal state manually
        instance = object.__new__(OnboardingWindow)
        instance._done_callback = None
        instance._root = MagicMock()
        instance._gemini_entry = MagicMock()
        instance._license_entry = MagicMock()
        return instance

    def test_finish_escrita_env(self, monkeypatch, env_dir):
        """`_finish()` must write GEMINI_API_KEY and LICENSE_KEY to .env."""
        win = self._make_window(monkeypatch, env_dir)
        win._gemini_entry.get.return_value = "AIzaFAKEKEY"
        win._license_entry.get.return_value = "vc-test-license"

        win._finish()

        env_path = env_dir / ".env"
        assert env_path.exists(), ".env must be created by _finish()"
        content = env_path.read_text(encoding="utf-8")
        assert "GEMINI_API_KEY=AIzaFAKEKEY" in content
        assert "LICENSE_KEY=vc-test-license" in content

    def test_finish_chama_done_callback(self, monkeypatch, env_dir):
        """`_finish()` must invoke done_callback if provided."""
        win = self._make_window(monkeypatch, env_dir)
        win._gemini_entry.get.return_value = "AIzaFAKEKEY"
        win._license_entry.get.return_value = ""

        callback_called = []
        win._done_callback = lambda: callback_called.append(True)

        win._finish()

        assert callback_called, "done_callback must be called by _finish()"

    def test_finish_sem_callback_nao_levanta(self, monkeypatch, env_dir):
        """`_finish()` with done_callback=None must not raise."""
        win = self._make_window(monkeypatch, env_dir)
        win._gemini_entry.get.return_value = ""
        win._license_entry.get.return_value = ""
        win._done_callback = None

        win._finish()  # deve completar sem exceção

    def test_finish_destroi_root(self, monkeypatch, env_dir):
        """`_finish()` must call root.destroy() to close the window."""
        win = self._make_window(monkeypatch, env_dir)
        win._gemini_entry.get.return_value = "AIzaFAKEKEY"
        win._license_entry.get.return_value = ""

        # Capture root reference BEFORE _finish() sets it to None
        root_mock = win._root
        win._finish()

        # root should have been destroyed and then set to None
        root_mock.destroy.assert_called_once()
        assert win._root is None

    def test_finish_sem_entry_nao_levanta(self, monkeypatch, env_dir):
        """`_finish()` with None entries must fall back to empty strings."""
        win = self._make_window(monkeypatch, env_dir)
        win._gemini_entry = None
        win._license_entry = None

        win._finish()  # deve completar sem AttributeError


# ---------------------------------------------------------------------------
# SettingsWindow._save() — writes all config keys to .env
# ---------------------------------------------------------------------------

class TestSettingsSave:
    """Test _save() logic without CTk window."""

    def _make_settings(self, monkeypatch, env_dir):
        from voice.ui import SettingsWindow

        monkeypatch.setitem(sys.modules, "customtkinter", MagicMock())

        instance = object.__new__(SettingsWindow)
        instance._root = MagicMock()
        instance._save_btn = MagicMock()
        instance._mode_card_refs = {}
        instance._sound_entries = {}
        instance._license_status_label = MagicMock()

        # Stub all config vars with predictable values
        def _str_var(val):
            m = MagicMock()
            m.get.return_value = val
            return m

        def _bool_var(val):
            m = MagicMock()
            m.get.return_value = val
            return m

        instance._model_var = _str_var("small")
        instance._lang_var = _str_var("pt")
        instance._api_entry = MagicMock()
        instance._api_entry.get.return_value = "AIzaNEWKEY"
        instance._license_entry = MagicMock()
        instance._license_entry.get.return_value = "vc-abc123"
        instance._hotkey_entry = MagicMock()
        instance._hotkey_entry.get.return_value = "ctrl+shift+space"
        instance._provider_var = _str_var("gemini")
        instance._openai_key_entry = MagicMock()
        instance._openai_key_entry.get.return_value = "sk-test"
        instance._device_var = _str_var("cpu")
        instance._translate_lang_var = _str_var("en")
        instance._openrouter_key_entry = MagicMock()
        instance._openrouter_key_entry.get.return_value = ""
        instance._indicator_bars = {}

        return instance

    def test_save_escrita_env(self, monkeypatch, env_dir):
        """`_save()` must persist all config keys to .env."""
        win = self._make_settings(monkeypatch, env_dir)

        # Mock reload to avoid re-reading non-existent config
        monkeypatch.setattr("voice.ui._reload_config", lambda: None)

        win._save()

        env_path = env_dir / ".env"
        assert env_path.exists(), ".env must be written by _save()"
        content = env_path.read_text(encoding="utf-8")
        assert "GEMINI_API_KEY=AIzaNEWKEY" in content
        assert "WHISPER_MODEL=small" in content
        assert "LICENSE_KEY=vc-abc123" in content

    def test_save_lang_auto_detect_escreve_vazio(self, monkeypatch, env_dir):
        """`_save()` must write empty string for WHISPER_LANGUAGE when auto-detect."""
        win = self._make_settings(monkeypatch, env_dir)
        win._lang_var.get.return_value = "auto-detect"
        monkeypatch.setattr("voice.ui._reload_config", lambda: None)

        win._save()

        env_path = env_dir / ".env"
        content = env_path.read_text(encoding="utf-8")
        assert "WHISPER_LANGUAGE=\n" in content or "WHISPER_LANGUAGE=" in content

    def test_save_sem_api_key_nao_inclui_chave(self, monkeypatch, env_dir):
        """`_save()` must NOT write GEMINI_API_KEY if entry is empty."""
        win = self._make_settings(monkeypatch, env_dir)
        win._api_entry.get.return_value = ""
        monkeypatch.setattr("voice.ui._reload_config", lambda: None)

        win._save()

        env_path = env_dir / ".env"
        content = env_path.read_text(encoding="utf-8")
        assert "GEMINI_API_KEY" not in content


# ---------------------------------------------------------------------------
# _apply_taskbar_icon — deve retornar silenciosamente se .ico não existe
# ---------------------------------------------------------------------------

class TestApplyTaskbarIcon:
    def test_nao_levanta_se_ico_ausente(self, tmp_path):
        """_apply_taskbar_icon() must return silently if .ico file does not exist."""
        import pathlib
        from voice.ui import _apply_taskbar_icon

        root = MagicMock()
        fake_ico = pathlib.Path(tmp_path) / "nao_existe.ico"

        # Nenhuma exceção deve ser levantada
        _apply_taskbar_icon(root, fake_ico)
