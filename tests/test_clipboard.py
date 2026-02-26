"""
Tests for voice/clipboard.py — copy_to_clipboard and paste_via_sendinput.

Strategy: monkeypatch ctypes.windll with a MagicMock that has controlled
return values, and patch ctypes.memmove to avoid real memory access.
All Win32 API calls are intercepted — no hardware interaction.
"""
import ctypes
import ctypes.wintypes
from unittest.mock import MagicMock, patch

import pytest

from voice.clipboard import copy_to_clipboard, paste_via_sendinput, read_clipboard


def _make_windll_mock():
    """Build a windll mock with defaults for a successful clipboard write."""
    mock_kernel32 = MagicMock()
    mock_user32 = MagicMock()

    # OpenClipboard: success on first try
    mock_user32.OpenClipboard.return_value = 1
    mock_user32.EmptyClipboard.return_value = 1
    mock_user32.SetClipboardData.return_value = 1
    mock_user32.CloseClipboard.return_value = 1

    # Fake handles for GlobalAlloc / GlobalLock
    mock_kernel32.GlobalAlloc.return_value = 0xDEAD
    mock_kernel32.GlobalLock.return_value = 0xBEEF
    mock_kernel32.GlobalUnlock.return_value = 1
    mock_kernel32.GlobalFree.return_value = 0

    mock_windll = MagicMock()
    mock_windll.kernel32 = mock_kernel32
    mock_windll.user32 = mock_user32
    return mock_windll


# ---------------------------------------------------------------------------
# copy_to_clipboard — happy path
# ---------------------------------------------------------------------------

class TestCopyToClipboard:

    def test_happy_path(self, monkeypatch):
        """copy_to_clipboard completes successfully on first OpenClipboard call."""
        mock_windll = _make_windll_mock()
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        with patch("ctypes.memmove") as mock_memmove:
            copy_to_clipboard("hello")

        mock_windll.user32.OpenClipboard.assert_called_once_with(None)
        mock_windll.user32.EmptyClipboard.assert_called_once()
        mock_windll.kernel32.GlobalAlloc.assert_called_once()
        mock_windll.kernel32.GlobalLock.assert_called_once_with(0xDEAD)
        mock_memmove.assert_called_once()
        mock_windll.user32.SetClipboardData.assert_called_once()
        mock_windll.user32.CloseClipboard.assert_called_once()

    def test_clipboard_fechado_no_finally(self, monkeypatch):
        """CloseClipboard is called via finally even when SetClipboardData raises."""
        mock_windll = _make_windll_mock()
        mock_windll.user32.SetClipboardData.side_effect = RuntimeError("set failed")
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        with patch("ctypes.memmove"):
            with pytest.raises(RuntimeError):
                copy_to_clipboard("text")

        mock_windll.user32.CloseClipboard.assert_called_once()

    def test_retry_abre_clipboard_na_segunda_tentativa(self, monkeypatch):
        """When OpenClipboard fails once, it retries and succeeds on the second call."""
        mock_windll = _make_windll_mock()
        mock_windll.user32.OpenClipboard.side_effect = [0, 1]  # fail, then succeed
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        with patch("ctypes.memmove"):
            with patch("time.sleep"):
                copy_to_clipboard("hello")

        assert mock_windll.user32.OpenClipboard.call_count == 2

    def test_falha_em_todas_tentativas_levanta_runtime_error(self, monkeypatch):
        """When OpenClipboard fails all 10 retries, RuntimeError is raised."""
        mock_windll = _make_windll_mock()
        mock_windll.user32.OpenClipboard.return_value = 0  # always fail
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        with patch("time.sleep"):
            with pytest.raises(RuntimeError, match="clipboard"):
                copy_to_clipboard("text")

        assert mock_windll.user32.OpenClipboard.call_count == 10

    def test_global_alloc_falha_levanta_runtime_error(self, monkeypatch):
        """If GlobalAlloc returns 0, RuntimeError is raised and CloseClipboard called."""
        mock_windll = _make_windll_mock()
        mock_windll.kernel32.GlobalAlloc.return_value = 0  # failure
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        with patch("ctypes.memmove"):
            with pytest.raises(RuntimeError, match="GlobalAlloc"):
                copy_to_clipboard("text")

        mock_windll.user32.CloseClipboard.assert_called_once()

    def test_global_lock_falha_libera_memoria_e_levanta_erro(self, monkeypatch):
        """If GlobalLock returns 0, GlobalFree is called and RuntimeError raised."""
        mock_windll = _make_windll_mock()
        mock_windll.kernel32.GlobalLock.return_value = 0  # failure
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        with patch("ctypes.memmove"):
            with pytest.raises(RuntimeError, match="GlobalLock"):
                copy_to_clipboard("text")

        mock_windll.kernel32.GlobalFree.assert_called_once_with(0xDEAD)
        mock_windll.user32.CloseClipboard.assert_called_once()

    def test_texto_unicode_codificado_corretamente(self, monkeypatch):
        """memmove is called with the correct UTF-16-LE-encoded text."""
        mock_windll = _make_windll_mock()
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        captured = []
        def fake_memmove(dst, src, count):
            captured.append((dst, bytes(src), count))

        with patch("ctypes.memmove", side_effect=fake_memmove):
            copy_to_clipboard("AB")

        # "AB\0" encoded in UTF-16-LE = b'\x41\x00\x42\x00\x00\x00' (6 bytes)
        assert len(captured) == 1
        _, encoded_bytes, size = captured[0]
        assert encoded_bytes == "AB\0".encode("utf-16-le")
        assert size == len("AB\0".encode("utf-16-le"))


# ---------------------------------------------------------------------------
# paste_via_sendinput
# ---------------------------------------------------------------------------

class TestPasteViaSendInput:

    def test_chama_sendinput_com_quatro_eventos(self, monkeypatch):
        """paste_via_sendinput calls SendInput with count=4."""
        mock_windll = _make_windll_mock()
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        paste_via_sendinput()

        mock_windll.user32.SendInput.assert_called_once()
        args = mock_windll.user32.SendInput.call_args[0]
        assert args[0] == 4  # first arg is count

    def test_sem_excecao(self, monkeypatch):
        """paste_via_sendinput completes without raising exceptions."""
        mock_windll = _make_windll_mock()
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        # Must not raise
        paste_via_sendinput()


# ---------------------------------------------------------------------------
# read_clipboard — Story 4.5.4
# ---------------------------------------------------------------------------

class TestReadClipboard:

    def test_retorna_texto_do_clipboard(self, monkeypatch):
        """read_clipboard() returns text from clipboard via Win32 API."""
        mock_windll = _make_windll_mock()
        mock_windll.user32.GetClipboardData.return_value = 0xDEAD
        mock_windll.kernel32.GlobalLock.return_value = 0xBEEF
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        with patch("ctypes.wstring_at", return_value="texto copiado"):
            result = read_clipboard()

        assert result == "texto copiado"
        mock_windll.user32.OpenClipboard.assert_called_once_with(None)
        mock_windll.user32.CloseClipboard.assert_called_once()

    def test_retorna_vazio_se_open_clipboard_falha(self, monkeypatch):
        """read_clipboard() returns empty string when OpenClipboard fails."""
        mock_windll = _make_windll_mock()
        mock_windll.user32.OpenClipboard.return_value = 0  # always fail
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        with patch("time.sleep"):
            result = read_clipboard()

        assert result == ""

    def test_retorna_vazio_se_get_clipboard_data_null(self, monkeypatch):
        """read_clipboard() returns empty string when GetClipboardData returns 0."""
        mock_windll = _make_windll_mock()
        mock_windll.user32.GetClipboardData.return_value = 0  # no data
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        result = read_clipboard()

        assert result == ""
        mock_windll.user32.CloseClipboard.assert_called_once()

    def test_retorna_vazio_se_global_lock_falha(self, monkeypatch):
        """read_clipboard() returns empty string when GlobalLock fails."""
        mock_windll = _make_windll_mock()
        mock_windll.user32.GetClipboardData.return_value = 0xDEAD
        mock_windll.kernel32.GlobalLock.return_value = 0  # lock fails
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        result = read_clipboard()

        assert result == ""

    def test_fecha_clipboard_mesmo_em_excecao(self, monkeypatch):
        """read_clipboard() calls CloseClipboard even when wstring_at raises."""
        mock_windll = _make_windll_mock()
        mock_windll.user32.GetClipboardData.return_value = 0xDEAD
        mock_windll.kernel32.GlobalLock.return_value = 0xBEEF
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        with patch("ctypes.wstring_at", side_effect=OSError("oops")):
            result = read_clipboard()

        assert result == ""
        mock_windll.user32.CloseClipboard.assert_called_once()

    def test_trunca_texto_quando_max_chars_excedido(self, monkeypatch):
        """read_clipboard() truncates text to max_chars when the limit is exceeded."""
        mock_windll = _make_windll_mock()
        mock_windll.user32.GetClipboardData.return_value = 0xDEAD
        mock_windll.kernel32.GlobalLock.return_value = 0xBEEF
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        long_text = "A" * 500
        with patch("ctypes.wstring_at", return_value=long_text):
            result = read_clipboard(max_chars=100)

        assert result == "A" * 100
        assert len(result) == 100

    def test_nao_trunca_se_max_chars_zero(self, monkeypatch):
        """read_clipboard() returns full text when max_chars=0 (no limit)."""
        mock_windll = _make_windll_mock()
        mock_windll.user32.GetClipboardData.return_value = 0xDEAD
        mock_windll.kernel32.GlobalLock.return_value = 0xBEEF
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        long_text = "B" * 500
        with patch("ctypes.wstring_at", return_value=long_text):
            result = read_clipboard(max_chars=0)

        assert result == long_text
        assert len(result) == 500

    def test_retorna_vazio_se_wstring_at_retorna_none(self, monkeypatch):
        """read_clipboard() returns empty string when wstring_at returns None/empty."""
        mock_windll = _make_windll_mock()
        mock_windll.user32.GetClipboardData.return_value = 0xDEAD
        mock_windll.kernel32.GlobalLock.return_value = 0xBEEF
        monkeypatch.setattr(ctypes, "windll", mock_windll)

        with patch("ctypes.wstring_at", return_value=""):
            result = read_clipboard()

        assert result == ""
