# tests/test_window_context.py — Epic 5.5: Window Context testes

import sys
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers / imports
# ---------------------------------------------------------------------------

# voice.state must be importable without hardware
import voice.state as state
import voice.window_context as wc


# ---------------------------------------------------------------------------
# _PROCESS_CATEGORIES / get_app_category
# ---------------------------------------------------------------------------

class TestProcessCategories:
    def test_known_code_editors(self):
        for exe in ("code.exe", "cursor.exe", "pycharm64.exe", "devenv.exe"):
            assert wc.get_app_category(exe) == "code_editor", f"Failed for {exe}"

    def test_known_email_clients(self):
        for exe in ("outlook.exe", "thunderbird.exe"):
            assert wc.get_app_category(exe) == "email", f"Failed for {exe}"

    def test_known_browsers(self):
        for exe in ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"):
            assert wc.get_app_category(exe) == "browser", f"Failed for {exe}"

    def test_known_chat_apps(self):
        for exe in ("slack.exe", "discord.exe", "teams.exe", "telegram.exe"):
            assert wc.get_app_category(exe) == "chat", f"Failed for {exe}"

    def test_known_terminals(self):
        for exe in ("windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe"):
            assert wc.get_app_category(exe) == "terminal", f"Failed for {exe}"

    def test_known_document_apps(self):
        assert wc.get_app_category("winword.exe") == "document"
        assert wc.get_app_category("excel.exe") == "spreadsheet"
        assert wc.get_app_category("powerpnt.exe") == "presentation"
        assert wc.get_app_category("notepad.exe") == "text_editor"

    def test_unknown_exe_returns_other(self):
        assert wc.get_app_category("unknownapp.exe") == "other"
        assert wc.get_app_category("random_tool.exe") == "other"
        assert wc.get_app_category("") == "other"

    def test_case_insensitive_lookup(self):
        """Categoria deve ser igual independente do case do exe name."""
        assert wc.get_app_category("Code.exe") == "code_editor"
        assert wc.get_app_category("CHROME.EXE") == "browser"
        assert wc.get_app_category("Outlook.Exe") == "email"
        assert wc.get_app_category("SLACK.EXE") == "chat"


# ---------------------------------------------------------------------------
# get_foreground_window_info — estrutura e campos
# ---------------------------------------------------------------------------

class TestGetForegroundWindowInfo:
    def test_returns_dict_with_required_keys(self):
        """Deve retornar dict com title, process, category sempre."""
        with patch("voice.window_context.ctypes") as mock_ctypes:
            # Simula HWND válido
            mock_user32 = MagicMock()
            mock_user32.GetForegroundWindow.return_value = 12345
            mock_user32.GetWindowTextW.return_value = 0

            def fake_buf(size):
                b = MagicMock()
                b.value = "Test Window"
                return b

            mock_ctypes.create_unicode_buffer.side_effect = fake_buf
            mock_ctypes.windll.user32 = mock_user32

            # Garante que get_process_name não explode
            with patch("voice.window_context.get_process_name", return_value="code.exe"):
                result = wc.get_foreground_window_info()

        assert isinstance(result, dict)
        assert "title" in result
        assert "process" in result
        assert "category" in result

    def test_category_derived_from_process(self):
        with patch("voice.window_context.get_process_name", return_value="outlook.exe"):
            with patch("voice.window_context.ctypes") as mock_ctypes:
                mock_user32 = MagicMock()
                mock_user32.GetForegroundWindow.return_value = 99
                buf = MagicMock()
                buf.value = "Inbox - Outlook"
                mock_ctypes.create_unicode_buffer.return_value = buf
                mock_ctypes.windll.user32 = mock_user32

                result = wc.get_foreground_window_info()

        assert result["process"] == "outlook.exe"
        assert result["category"] == "email"

    def test_returns_fallback_dict_on_exception(self):
        """Nunca deve levantar exceção — retorna dict seguro em qualquer falha."""
        with patch("voice.window_context.ctypes") as mock_ctypes:
            mock_ctypes.windll.user32.GetForegroundWindow.side_effect = OSError("Access denied")
            result = wc.get_foreground_window_info()

        assert result == {"title": "", "process": "", "category": "other"}

    def test_empty_process_category_is_other(self):
        """Se get_process_name retornar "" a categoria deve ser 'other'."""
        with patch("voice.window_context.get_process_name", return_value=""):
            with patch("voice.window_context.ctypes") as mock_ctypes:
                mock_user32 = MagicMock()
                mock_user32.GetForegroundWindow.return_value = 1
                buf = MagicMock()
                buf.value = "Notepad"
                mock_ctypes.create_unicode_buffer.return_value = buf
                mock_ctypes.windll.user32 = mock_user32

                result = wc.get_foreground_window_info()

        assert result["category"] == "other"
        assert result["process"] == ""


# ---------------------------------------------------------------------------
# get_process_name — comportamento com ctypes mockado
# ---------------------------------------------------------------------------

class TestGetProcessName:
    def test_no_foreground_window_returns_empty(self):
        """GetForegroundWindow retorna 0 → retorna ''."""
        with patch("voice.window_context.ctypes") as mock_ctypes:
            mock_ctypes.windll.user32.GetForegroundWindow.return_value = 0
            result = wc.get_process_name()
        assert result == ""

    def test_no_pid_returns_empty(self):
        """PID 0 → retorna ''."""
        with patch("voice.window_context.ctypes") as mock_ctypes:
            mock_user32 = MagicMock()
            mock_user32.GetForegroundWindow.return_value = 1

            pid_mock = MagicMock()
            pid_mock.value = 0
            mock_ctypes.wintypes.DWORD.return_value = pid_mock
            mock_ctypes.windll.user32 = mock_user32

            result = wc.get_process_name()

        assert result == ""

    def test_exception_returns_empty(self):
        """Qualquer exceção interna → retorna '' sem propagar."""
        with patch("voice.window_context.ctypes") as mock_ctypes:
            mock_ctypes.windll.user32.GetForegroundWindow.side_effect = RuntimeError("fail")
            result = wc.get_process_name()

        assert result == ""


# ---------------------------------------------------------------------------
# _build_context_prefix — injeção nos prompts Gemini
# ---------------------------------------------------------------------------

class TestBuildContextPrefix:
    def setup_method(self):
        """Reset state before each test."""
        state._CONFIG = {}
        state._window_context = {}

    def test_disabled_returns_empty(self, monkeypatch):
        monkeypatch.setattr(state, "_CONFIG", {"WINDOW_CONTEXT_ENABLED": False})
        monkeypatch.setattr(state, "_window_context", {"title": "x", "process": "outlook.exe", "category": "email"})

        from voice.gemini import _build_context_prefix
        assert _build_context_prefix() == ""

    def test_enabled_no_context_returns_empty(self, monkeypatch):
        monkeypatch.setattr(state, "_CONFIG", {"WINDOW_CONTEXT_ENABLED": True})
        monkeypatch.setattr(state, "_window_context", {})

        from voice.gemini import _build_context_prefix
        assert _build_context_prefix() == ""

    def test_context_injection_email(self, monkeypatch):
        """category=email → prefixo menciona 'profissional'."""
        monkeypatch.setattr(state, "_CONFIG", {"WINDOW_CONTEXT_ENABLED": True})
        monkeypatch.setattr(state, "_window_context", {
            "title": "Inbox - Outlook",
            "process": "outlook.exe",
            "category": "email",
        })

        from voice.gemini import _build_context_prefix
        prefix = _build_context_prefix()
        assert prefix != ""
        assert "profissional" in prefix.lower()

    def test_context_injection_code_editor(self, monkeypatch):
        """category=code_editor → prefixo menciona preservação de código."""
        monkeypatch.setattr(state, "_CONFIG", {"WINDOW_CONTEXT_ENABLED": True})
        monkeypatch.setattr(state, "_window_context", {
            "title": "app.py - VSCode",
            "process": "code.exe",
            "category": "code_editor",
        })

        from voice.gemini import _build_context_prefix
        prefix = _build_context_prefix()
        assert prefix != ""
        assert "código" in prefix.lower() or "code" in prefix.lower()

    def test_context_injection_chat(self, monkeypatch):
        """category=chat → prefixo menciona tom casual."""
        monkeypatch.setattr(state, "_CONFIG", {"WINDOW_CONTEXT_ENABLED": True})
        monkeypatch.setattr(state, "_window_context", {
            "title": "Slack",
            "process": "slack.exe",
            "category": "chat",
        })

        from voice.gemini import _build_context_prefix
        prefix = _build_context_prefix()
        assert prefix != ""
        assert "casual" in prefix.lower() or "chat" in prefix.lower()

    def test_context_injection_other_no_hint(self, monkeypatch):
        """category=other → sem hint, retorna ''."""
        monkeypatch.setattr(state, "_CONFIG", {"WINDOW_CONTEXT_ENABLED": True})
        monkeypatch.setattr(state, "_window_context", {
            "title": "Unknown App",
            "process": "randomapp.exe",
            "category": "other",
        })

        from voice.gemini import _build_context_prefix
        assert _build_context_prefix() == ""

    def test_context_injection_browser_no_hint(self, monkeypatch):
        """category=browser → sem hint definido, retorna ''."""
        monkeypatch.setattr(state, "_CONFIG", {"WINDOW_CONTEXT_ENABLED": True})
        monkeypatch.setattr(state, "_window_context", {
            "title": "Google Chrome",
            "process": "chrome.exe",
            "category": "browser",
        })

        from voice.gemini import _build_context_prefix
        assert _build_context_prefix() == ""
