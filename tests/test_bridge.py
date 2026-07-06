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
