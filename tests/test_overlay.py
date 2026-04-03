"""
Tests for voice/overlay.py — OverlayManager queue interface.

Strategy: patch tkinter entirely (no display needed) and test only the
public API and queue/command semantics. _OverlayThread is never started.
All assertions target the queue contents or public function behavior
against a mock thread object.
"""
import queue
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Ensure heavy deps are stubbed before importing overlay
# ---------------------------------------------------------------------------
import sys

# tkinter is available in standard Python but requires a display to run
# mainloop(); we stub it at module level to prevent test failures on CI.
_tk_stub = MagicMock()
sys.modules.setdefault("tkinter", _tk_stub)

import voice.state as state  # noqa: E402

# Provide a minimal _CONFIG so overlay._get_thread() can read OVERLAY_ENABLED
state._CONFIG = {"OVERLAY_ENABLED": True}

from voice.overlay import (  # noqa: E402
    _OverlayThread,
    show_recording,
    show_processing,
    show_done,
    hide,
    STATE_RECORDING,
    STATE_PROCESSING,
    STATE_DONE,
    STATE_HIDE,
)


# ---------------------------------------------------------------------------
# Helper: build a real _OverlayThread WITHOUT starting it (no mainloop)
# ---------------------------------------------------------------------------

def _make_thread() -> _OverlayThread:
    """Return an _OverlayThread instance whose run() method is never called."""
    t = _OverlayThread()
    # Mark as alive via mock so _get_thread() doesn't restart it
    t.is_alive = MagicMock(return_value=True)
    return t


# ---------------------------------------------------------------------------
# _OverlayThread.send() — queue interface
# ---------------------------------------------------------------------------

class TestOverlayThreadSend:

    def test_send_enfileira_comando_show(self):
        """send('show', ...) puts (cmd, data) tuple into the queue."""
        t = _make_thread()
        t.send("show", state=STATE_RECORDING, text="hello")

        cmd, data = t._q.get_nowait()
        assert cmd == "show"
        assert data["state"] == STATE_RECORDING
        assert data["text"] == "hello"

    def test_send_enfileira_comando_hide(self):
        """send('hide') puts ('hide', {}) into the queue."""
        t = _make_thread()
        t.send("hide")

        cmd, data = t._q.get_nowait()
        assert cmd == "hide"
        assert data == {}

    def test_fila_vazia_por_padrao(self):
        """A newly created _OverlayThread has an empty queue."""
        t = _make_thread()
        assert t._q.empty()

    def test_multiplos_comandos_preservam_ordem(self):
        """Commands are FIFO — order is preserved."""
        t = _make_thread()
        t.send("show", state=STATE_RECORDING, text="a")
        t.send("show", state=STATE_PROCESSING, text="b")
        t.send("hide")

        first_cmd, first_data = t._q.get_nowait()
        second_cmd, second_data = t._q.get_nowait()
        third_cmd, _ = t._q.get_nowait()

        assert first_cmd == "show" and first_data["state"] == STATE_RECORDING
        assert second_cmd == "show" and second_data["state"] == STATE_PROCESSING
        assert third_cmd == "hide"


# ---------------------------------------------------------------------------
# Public API — show_recording / show_processing / show_done / hide
# Commands sent to the mock thread are verified.
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_thread(monkeypatch):
    """Replace _get_thread() with a factory returning a fresh mock thread."""
    t = _make_thread()
    monkeypatch.setattr("voice.overlay._thread", t)
    monkeypatch.setattr("voice.overlay._get_thread", lambda: t)
    return t


class TestPublicAPI:

    def test_show_recording_envia_estado_correto(self, mock_thread):
        """show_recording() sends state=STATE_RECORDING to the queue."""
        show_recording(clipboard_chars=0)

        cmd, data = mock_thread._q.get_nowait()
        assert cmd == "show"
        assert data["state"] == STATE_RECORDING

    def test_show_recording_com_clipboard_inclui_texto(self, mock_thread):
        """show_recording(clipboard_chars=100) includes clipboard info in text."""
        show_recording(clipboard_chars=100)

        cmd, data = mock_thread._q.get_nowait()
        assert cmd == "show"
        assert data["state"] == STATE_RECORDING
        assert "100" in data["text"]  # deve mencionar o número de chars

    def test_show_recording_sem_clipboard_texto_vazio(self, mock_thread):
        """show_recording(clipboard_chars=0) sends empty info text."""
        show_recording(clipboard_chars=0)

        cmd, data = mock_thread._q.get_nowait()
        assert data["text"] == ""

    def test_show_processing_envia_estado_correto(self, mock_thread):
        """show_processing() sends state=STATE_PROCESSING to the queue."""
        show_processing("Corrigindo")

        cmd, data = mock_thread._q.get_nowait()
        assert cmd == "show"
        assert data["state"] == STATE_PROCESSING

    def test_show_processing_inclui_descricao_do_modo(self, mock_thread):
        """show_processing(mode) forwards mode string as text."""
        show_processing("Traduzindo")

        cmd, data = mock_thread._q.get_nowait()
        assert data["text"] == "Traduzindo"

    def test_show_done_envia_estado_correto(self, mock_thread):
        """show_done() sends state=STATE_DONE to the queue."""
        show_done("resultado aqui")

        cmd, data = mock_thread._q.get_nowait()
        assert cmd == "show"
        assert data["state"] == STATE_DONE

    def test_show_done_inclui_texto_do_output(self, mock_thread):
        """show_done(text) forwards the output text."""
        show_done("texto gerado")

        cmd, data = mock_thread._q.get_nowait()
        assert data["text"] == "texto gerado"

    def test_hide_envia_comando_hide(self, mock_thread):
        """hide() sends ('hide', {}) to the queue."""
        hide()

        cmd, data = mock_thread._q.get_nowait()
        assert cmd == "hide"

    def test_show_done_texto_vazio(self, mock_thread):
        """show_done() without args sends empty text."""
        show_done()

        cmd, data = mock_thread._q.get_nowait()
        assert cmd == "show"
        assert data["state"] == STATE_DONE
        assert data["text"] == ""


# ---------------------------------------------------------------------------
# _OverlayThread._show() — preview truncation logic (STATE_DONE)
# Tested via _handle() to avoid running the mainloop.
# ---------------------------------------------------------------------------

class TestShowDonePreviewTruncation:
    """Test the 60-char preview truncation in _OverlayThread._show()."""

    def _make_thread_with_mocked_root(self):
        """Create thread with all tkinter widgets replaced by MagicMock."""
        t = _make_thread()
        t._root = MagicMock()
        t._dot_canvas = MagicMock()
        t._state_label = MagicMock()
        t._text_label = MagicMock()
        t._dot_oval = "oval_id"
        t._dismiss_id = None
        t._dot_anim_id = None
        return t

    def test_texto_curto_nao_truncado(self):
        """Text shorter than 60 chars is not truncated in STATE_DONE."""
        t = self._make_thread_with_mocked_root()
        short = "texto curto"
        t._show(STATE_DONE, short)

        calls = t._text_label.config.call_args_list
        assert any(short in str(c) for c in calls)

    def test_texto_longo_truncado_em_60_chars(self):
        """Text longer than 60 chars is truncated to 60 + '...' in STATE_DONE."""
        t = self._make_thread_with_mocked_root()
        long_text = "X" * 80
        t._show(STATE_DONE, long_text)

        calls = t._text_label.config.call_args_list
        # Expected: first 60 chars + "..."
        expected_preview = "X" * 60 + "..."
        assert any(expected_preview in str(c) for c in calls)

    def test_texto_exatamente_60_chars_nao_truncado(self):
        """Text of exactly 60 chars is not truncated."""
        t = self._make_thread_with_mocked_root()
        exact = "Y" * 60
        t._show(STATE_DONE, exact)

        calls = t._text_label.config.call_args_list
        # Should not contain "..." suffix from truncation
        # The label should receive the exact text without "..."
        assert any(exact in str(c) and "..." not in str(c).replace(exact, "") for c in calls)

    def test_texto_vazio_em_done_nao_levanta(self):
        """show_done with empty text does not raise and sends empty preview."""
        t = self._make_thread_with_mocked_root()
        t._show(STATE_DONE, "")  # must not raise

        t._text_label.config.assert_called()


# ---------------------------------------------------------------------------
# _OverlayThread — initial state
# ---------------------------------------------------------------------------

class TestOverlayThreadInitialState:

    def test_estado_inicial_e_hide(self):
        """_OverlayThread starts with _current_state == STATE_HIDE."""
        t = _make_thread()
        assert t._current_state == STATE_HIDE

    def test_fila_criada_como_queue_Queue(self):
        """_q is a queue.Queue instance."""
        t = _make_thread()
        assert isinstance(t._q, queue.Queue)

    def test_thread_e_daemon(self):
        """_OverlayThread is a daemon thread."""
        t = _make_thread()
        assert t.daemon is True
