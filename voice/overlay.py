# voice/overlay.py — Story 4.5.1: Toast/overlay de feedback pós-hotkey
#
# Implementação com tkinter puro em thread daemon com fila de mensagens.
# Usa wm_overrideredirect + wm_attributes("-topmost") para não roubar foco.
# Thread-safe: toda comunicação via queue.Queue.

import queue
import threading
import tkinter as tk

from voice import state

# Estados do overlay
STATE_RECORDING  = "recording"
STATE_PROCESSING = "processing"
STATE_DONE       = "done"
STATE_HIDE       = "hide"

# Cores inline (sem importar theme para evitar dep de CTk)
_COLORS = {
    "bg":          "#0A0A0F",   # BG_ABYSS
    "bg_card":     "#12121A",   # BG_DEEP
    "border":      "#2A2A3E",   # BORDER_DEFAULT
    "recording":   "#FF3366",   # TRAY_RECORDING
    "processing":  "#1E38F7",   # TRAY_PROCESSING
    "done":        "#00E68A",   # SUCCESS
    "text":        "#E8E8F0",   # TEXT_PRIMARY
    "muted":       "#6B6B8A",   # TEXT_MUTED
    "purple":      "#6B2FF8",   # PURPLE
}

_OVERLAY_W = 320
_OVERLAY_H = 72
_MARGIN_RIGHT = 24
_MARGIN_BOTTOM = 60
_DONE_DISMISS_MS = 2000  # ms para auto-dismiss no estado "done"


class _OverlayThread(threading.Thread):
    """Thread daemon que mantém a janela tkinter viva e processa comandos da fila."""

    def __init__(self):
        super().__init__(daemon=True, name="OverlayThread")
        self._q: queue.Queue = queue.Queue()
        self._root: tk.Tk | None = None
        self._state_label = None
        self._text_label = None
        self._dot_canvas = None
        self._dot_anim_id = None
        self._dot_frame = 0
        self._dismiss_id = None
        self._current_state: str = STATE_HIDE
        self._ready = threading.Event()

    def run(self) -> None:
        try:
            self._root = tk.Tk()
            self._root.withdraw()
            self._build()
            self._ready.set()
            # Processar fila a cada 50ms
            self._root.after(50, self._poll_queue)
            self._root.mainloop()
        except Exception as e:
            print(f"[WARN] Overlay thread encerrada: {e}")
            self._ready.set()

    def _build(self) -> None:
        root = self._root

        # Sem borda, título, taskbar
        root.wm_overrideredirect(True)
        root.wm_attributes("-topmost", True)
        root.wm_attributes("-toolwindow", 1)

        root.configure(bg=_COLORS["bg_card"])
        root.resizable(False, False)

        # Posicionar no canto inferior direito
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x = sw - _OVERLAY_W - _MARGIN_RIGHT
        y = sh - _OVERLAY_H - _MARGIN_BOTTOM
        root.geometry(f"{_OVERLAY_W}x{_OVERLAY_H}+{x}+{y}")

        # Frame principal com borda simulada
        outer = tk.Frame(root, bg=_COLORS["border"], padx=1, pady=1)
        outer.pack(fill="both", expand=True)

        inner = tk.Frame(outer, bg=_COLORS["bg_card"], padx=14, pady=10)
        inner.pack(fill="both", expand=True)

        # Linha superior: indicador + estado
        top_row = tk.Frame(inner, bg=_COLORS["bg_card"])
        top_row.pack(fill="x")

        # Indicador colorido (canvas pequeno 10x10)
        self._dot_canvas = tk.Canvas(
            top_row, width=10, height=10,
            bg=_COLORS["bg_card"], highlightthickness=0,
        )
        self._dot_canvas.pack(side="left", padx=(0, 8))
        self._dot_oval = self._dot_canvas.create_oval(1, 1, 9, 9, fill=_COLORS["recording"], outline="")

        self._state_label = tk.Label(
            top_row, text="Gravando...",
            font=("Segoe UI", 10, "bold"),
            fg=_COLORS["text"], bg=_COLORS["bg_card"],
        )
        self._state_label.pack(side="left")

        # Linha inferior: preview do texto
        self._text_label = tk.Label(
            inner, text="",
            font=("Segoe UI", 9),
            fg=_COLORS["muted"], bg=_COLORS["bg_card"],
            anchor="w", justify="left",
            wraplength=_OVERLAY_W - 40,
        )
        self._text_label.pack(fill="x", pady=(4, 0))

    def _poll_queue(self) -> None:
        """Drena a fila de comandos e re-agenda."""
        try:
            while True:
                cmd, data = self._q.get_nowait()
                self._handle(cmd, data)
        except queue.Empty:
            pass
        if self._root:
            self._root.after(50, self._poll_queue)

    def _handle(self, cmd: str, data: dict) -> None:
        if cmd == "show":
            self._show(data.get("state", STATE_RECORDING), data.get("text", ""))
        elif cmd == "hide":
            self._hide()

    def _show(self, overlay_state: str, text: str) -> None:
        self._current_state = overlay_state

        # Cancelar auto-dismiss pendente
        if self._dismiss_id is not None:
            self._root.after_cancel(self._dismiss_id)
            self._dismiss_id = None

        # Parar animação anterior
        if self._dot_anim_id is not None:
            self._root.after_cancel(self._dot_anim_id)
            self._dot_anim_id = None

        # Atualizar conteúdo
        if overlay_state == STATE_RECORDING:
            color = _COLORS["recording"]
            label = "Gravando..."
            info = text or "Pressione o hotkey novamente para parar"
        elif overlay_state == STATE_PROCESSING:
            color = _COLORS["processing"]
            label = "Processando..."
            info = text or "Aguarde..."
            self._start_dot_anim()
        elif overlay_state == STATE_DONE:
            color = _COLORS["done"]
            label = "Pronto!"
            info = text[:60] + ("..." if len(text) > 60 else "") if text else ""
            # Auto-dismiss após 2s
            self._dismiss_id = self._root.after(_DONE_DISMISS_MS, self._hide)
        else:
            self._hide()
            return

        self._dot_canvas.itemconfig(self._dot_oval, fill=color)
        self._state_label.config(text=label, fg=color if overlay_state == STATE_DONE else _COLORS["text"])
        self._text_label.config(text=info)

        # Atualizar posição (resolução pode ter mudado)
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x = sw - _OVERLAY_W - _MARGIN_RIGHT
        y = sh - _OVERLAY_H - _MARGIN_BOTTOM
        self._root.geometry(f"{_OVERLAY_W}x{_OVERLAY_H}+{x}+{y}")

        self._root.deiconify()
        self._root.update_idletasks()

    def _hide(self) -> None:
        self._current_state = STATE_HIDE
        if self._dot_anim_id is not None:
            self._root.after_cancel(self._dot_anim_id)
            self._dot_anim_id = None
        if self._dismiss_id is not None:
            self._root.after_cancel(self._dismiss_id)
            self._dismiss_id = None
        if self._root:
            self._root.withdraw()

    def _start_dot_anim(self) -> None:
        """Anima o indicador piscando durante processamento."""
        colors = [_COLORS["processing"], _COLORS["muted"]]
        self._dot_frame = 0

        def _anim():
            if self._current_state != STATE_PROCESSING:
                return
            c = colors[self._dot_frame % 2]
            self._dot_canvas.itemconfig(self._dot_oval, fill=c)
            self._dot_frame += 1
            self._dot_anim_id = self._root.after(500, _anim)

        _anim()

    def send(self, cmd: str, **data) -> None:
        """Thread-safe: envia comando para a thread do overlay."""
        self._q.put((cmd, data))


# ---------------------------------------------------------------------------
# Singleton + API pública
# ---------------------------------------------------------------------------

_thread: _OverlayThread | None = None
_thread_lock = threading.Lock()


def _get_thread() -> _OverlayThread | None:
    """Retorna a thread do overlay, criando-a na primeira chamada se OVERLAY_ENABLED."""
    global _thread
    if not state._CONFIG.get("OVERLAY_ENABLED", "true").lower() == "true":
        return None
    with _thread_lock:
        if _thread is None or not _thread.is_alive():
            t = _OverlayThread()
            t.start()
            t._ready.wait(timeout=3)
            _thread = t
    return _thread


def show_recording(clipboard_chars: int = 0) -> None:
    """Exibe overlay no estado 'Gravando'. clipboard_chars > 0 indica contexto carregado."""
    t = _get_thread()
    if t is None:
        return
    info = ""
    if clipboard_chars > 0:
        info = f"Clipboard carregado ({clipboard_chars} chars)"
    t.send("show", state=STATE_RECORDING, text=info)


def show_processing(mode: str = "") -> None:
    """Exibe overlay no estado 'Processando'."""
    t = _get_thread()
    if t is None:
        return
    t.send("show", state=STATE_PROCESSING, text=mode)


def show_done(output_text: str = "") -> None:
    """Exibe overlay no estado 'Pronto' com preview das primeiras 60 chars."""
    t = _get_thread()
    if t is None:
        return
    t.send("show", state=STATE_DONE, text=output_text)


def hide() -> None:
    """Esconde o overlay imediatamente."""
    t = _get_thread()
    if t is None:
        return
    t.send("hide")
