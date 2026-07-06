"""
Tests for W2 Task 2 — voice/app.py wiring to voice/hotkeys_win32.py.

Covers the two new helpers passed to hotkeys_win32.start():
  - _hotkey_bindings(): bindings_provider — reads state._CONFIG, returns the
    4 (config_key, combo, callback) tuples with the same defaults as
    voice/config.py.
  - _report_hotkey_failures(failures): failure_reporter — logs [ERRO] per
    failure, beeps once via the voice.audio facade, and notifies via tray
    when available (never silent).
"""
from unittest.mock import MagicMock

from voice import state
from voice import audio
from voice import app


class TestHotkeyBindings:

    def test_reads_custom_config(self, monkeypatch):
        monkeypatch.setattr(state, "_CONFIG", {
            "RECORD_HOTKEY": "ctrl+shift+r",
            "CYCLE_HOTKEY": "ctrl+shift+c",
            "HISTORY_HOTKEY": "ctrl+shift+y",
            "COMMAND_HOTKEY": "ctrl+alt+z",
        })

        bindings = app._hotkey_bindings()

        assert len(bindings) == 4
        combos = {key: combo for key, combo, _ in bindings}
        assert combos == {
            "RECORD_HOTKEY": "ctrl+shift+r",
            "CYCLE_HOTKEY": "ctrl+shift+c",
            "HISTORY_HOTKEY": "ctrl+shift+y",
            "COMMAND_HOTKEY": "ctrl+alt+z",
        }
        callbacks = {key: cb for key, _, cb in bindings}
        assert callbacks["RECORD_HOTKEY"] is app.on_hotkey
        assert callbacks["COMMAND_HOTKEY"] is app.on_command_hotkey
        assert callbacks["CYCLE_HOTKEY"] is app._cycle_mode
        # HISTORY_HOTKEY callback is imported lazily from voice.history_search —
        # just assert it's callable, not identity (avoids import ordering coupling).
        assert callable(callbacks["HISTORY_HOTKEY"])

    def test_defaults_match_config_py(self, monkeypatch):
        """Empty _CONFIG (missing keys) falls back to the same defaults as voice/config.py."""
        monkeypatch.setattr(state, "_CONFIG", {})

        bindings = app._hotkey_bindings()

        combos = {key: combo for key, combo, _ in bindings}
        assert combos == {
            "RECORD_HOTKEY": "ctrl+shift+space",
            "CYCLE_HOTKEY": "ctrl+shift+tab",
            "HISTORY_HOTKEY": "ctrl+shift+h",
            "COMMAND_HOTKEY": "ctrl+alt+space",
        }


class TestReportHotkeyFailures:

    def test_logs_error_and_beeps_once(self, monkeypatch, capsys):
        monkeypatch.setattr(state, "_tray_icon", None)
        monkeypatch.setattr(state, "_tray_available", False)
        mock_play_sound = MagicMock()
        monkeypatch.setattr(audio, "play_sound", mock_play_sound)

        app._report_hotkey_failures([("RECORD_HOTKEY", "ctrl+shift+space", 1409)])

        out = capsys.readouterr().out
        assert "[ERRO]" in out
        assert "RECORD_HOTKEY" in out
        assert "ctrl+shift+space" in out
        assert "1409" in out
        mock_play_sound.assert_called_once_with("error")

    def test_multiple_failures_beeps_only_once(self, monkeypatch, capsys):
        monkeypatch.setattr(state, "_tray_icon", None)
        monkeypatch.setattr(state, "_tray_available", False)
        mock_play_sound = MagicMock()
        monkeypatch.setattr(audio, "play_sound", mock_play_sound)

        app._report_hotkey_failures([
            ("RECORD_HOTKEY", "ctrl+shift+space", 1409),
            ("CYCLE_HOTKEY", "ctrl+shift+tab", 1409),
        ])

        out = capsys.readouterr().out
        assert out.count("[ERRO]") == 2
        mock_play_sound.assert_called_once_with("error")

    def test_notifies_tray_when_available(self, monkeypatch):
        mock_tray = MagicMock()
        monkeypatch.setattr(state, "_tray_icon", mock_tray)
        monkeypatch.setattr(state, "_tray_available", True)
        monkeypatch.setattr(audio, "play_sound", MagicMock())

        app._report_hotkey_failures([("RECORD_HOTKEY", "ctrl+shift+space", 1409)])

        mock_tray.notify.assert_called_once()
        args, _ = mock_tray.notify.call_args
        assert "ctrl+shift+space" in args[0]

    def test_skips_tray_notify_when_icon_none(self, monkeypatch):
        monkeypatch.setattr(state, "_tray_icon", None)
        monkeypatch.setattr(state, "_tray_available", True)
        monkeypatch.setattr(audio, "play_sound", MagicMock())

        # Must not raise even though tray icon is None.
        app._report_hotkey_failures([("RECORD_HOTKEY", "ctrl+shift+space", 1409)])

    def test_skips_tray_notify_when_unavailable(self, monkeypatch):
        mock_tray = MagicMock()
        monkeypatch.setattr(state, "_tray_icon", mock_tray)
        monkeypatch.setattr(state, "_tray_available", False)
        monkeypatch.setattr(audio, "play_sound", MagicMock())

        app._report_hotkey_failures([("RECORD_HOTKEY", "ctrl+shift+space", 1409)])

        mock_tray.notify.assert_not_called()
