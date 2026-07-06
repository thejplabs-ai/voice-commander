"""
Tests for W2 Task 3 — voice/webui/bridge.py WebBridge.save_config() rebind hook.

Covers: after _save_env() + _reload_config(), save_config() must call
voice.hotkeys_win32.request_rebind() so a new hotkey combo is live immediately
(no more waiting for the 5-min heartbeat, removed in Task 2). Rebind is lazy-
imported (repo convention to avoid bridge import cost/cycles) and guarded —
a failure must not break the save.
"""
from unittest.mock import MagicMock

from voice.webui.bridge import WebBridge


class TestSaveConfigRebind:

    def test_calls_request_rebind_after_reload_config(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "voice.webui.bridge._save_env", lambda values: calls.append("save_env")
        )
        monkeypatch.setattr(
            "voice.webui.bridge._reload_config", lambda: calls.append("reload_config")
        )
        mock_rebind = MagicMock(side_effect=lambda: calls.append("request_rebind"))
        monkeypatch.setattr("voice.hotkeys_win32.request_rebind", mock_rebind)

        bridge = WebBridge()
        result = bridge.save_config({"RECORD_HOTKEY": "ctrl+shift+r"})

        assert result == {"ok": True}
        mock_rebind.assert_called_once()
        assert calls == ["save_env", "reload_config", "request_rebind"]

    def test_rebind_failure_does_not_break_save(self, monkeypatch, capsys):
        monkeypatch.setattr("voice.webui.bridge._save_env", lambda values: None)
        monkeypatch.setattr("voice.webui.bridge._reload_config", lambda: None)
        monkeypatch.setattr(
            "voice.hotkeys_win32.request_rebind",
            MagicMock(side_effect=RuntimeError("pump exploded")),
        )

        bridge = WebBridge()
        result = bridge.save_config({"RECORD_HOTKEY": "ctrl+shift+r"})

        assert result == {"ok": True}
        out = capsys.readouterr().out
        assert "[WARN]" in out


class TestSaveConfigMaskedKeyGuard:
    """Server-side guard: save_config() must drop masked GEMINI_API_KEY/
    OPENROUTER_API_KEY values (values starting with '***', as returned by
    get_config()) instead of persisting them over the real key. The JS
    filter in settings.html is defense in depth, not the only guard.
    """

    def _patch_save_env(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            "voice.webui.bridge._save_env", lambda values: captured.update(values)
        )
        monkeypatch.setattr("voice.webui.bridge._reload_config", lambda: None)
        monkeypatch.setattr("voice.hotkeys_win32.request_rebind", lambda: None)
        return captured

    def test_masked_keys_are_dropped_before_save_env(self, monkeypatch):
        captured = self._patch_save_env(monkeypatch)

        bridge = WebBridge()
        result = bridge.save_config({
            "OPENROUTER_API_KEY": "***abcd",
            "GEMINI_API_KEY": "***efgh",
            "VAD_THRESHOLD": "0.3",
        })

        assert result == {"ok": True}
        assert "OPENROUTER_API_KEY" not in captured
        assert "GEMINI_API_KEY" not in captured
        assert captured == {"VAD_THRESHOLD": "0.3"}

    def test_real_key_passes_through(self, monkeypatch):
        captured = self._patch_save_env(monkeypatch)

        bridge = WebBridge()
        result = bridge.save_config({"OPENROUTER_API_KEY": "sk-or-nova"})

        assert result == {"ok": True}
        assert captured == {"OPENROUTER_API_KEY": "sk-or-nova"}
