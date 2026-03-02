# voice/overlay.py — Story 4.5.1: Toast/overlay de feedback pós-hotkey
#
# Implementação com tkinter puro em thread daemon com fila de mensagens.
# Usa wm_overrideredirect + wm_attributes("-topmost") para não roubar foco.
# Thread-safe: toda comunicação via queue.Queue.

import queue
import threading
import tkinter as tk

from voice import state
from voice.modes import MODE_LABELS as _MODE_LABELS, MODE_NAMES_PT as _MODE_NAMES_PT

# Estados do overlay
STATE_RECORDING    = "recording"
STATE_PROCESSING   = "processing"
STATE_DONE         = "done"
STATE_MODE_CHANGE  = "mode_change"  # Story 4.6.2: ciclo de modo
STATE_HIDE         = "hide"

# Story 4.6.2: duração do overlay de ciclo de modo (ms)
_MODE_CHANGE_DISMISS_MS = 1500

# Cores inline (sem importar theme para evitar dep de CTk)
_COLORS = {
    "bg":          "#01010D",   # theme.BG_ABYSS
    "bg_card":     "#0D0C25",   # theme.BG_DEEP
    "border":      "#1C1C32",   # theme.BORDER_DEFAULT
    "recording":   "#FF3366",   # theme.ERROR (TRAY_RECORDING)
    "processing":  "#1E38F7",   # theme.BLUE_NEO (TRAY_PROCESSING)
    "done":        "#00FF88",   # theme.SUCCESS
    "text":        "#FFFFFF",   # theme.TEXT_PRIMARY
    "muted":       "#808099",   # theme.TEXT_MUTED
    "purple":      "#6B2FF8",   # theme.PURPLE
}


_OVERLAY_W = 320
_OVERLAY_H = 72
_MARGIN_RIGHT = 24
_MARGIN_BOTTOM = 60
_DONE_DISMISS_MS = 2000  # ms para auto-dismiss no estado "done"


# Resolve font family com fallback — chamado dentro de _build() onde self._root já existe
def _resolve_fonts(root) -> tuple:
    """Retorna (font_heading, font_body) com fallback Segoe UI."""
    try:
        import tkinter.font as tkfont
        available = tkfont.families(root)
        head = "Poppins" if "Poppins" in available else "Segoe UI"
        body = "Inter" if "Inter" in available else "Segoe UI"
    except Exception:
        head = body = "Segoe UI"
    return (head, 11, "bold"), (body, 10)


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

        # DPI awareness — melhora nitidez em monitores HiDPI
        try:
            import ctypes as _ct
            _ct.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                import ctypes as _ct
                _ct.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

        # Resolver fontes com fallback
        self._font_heading, self._font_body = _resolve_fonts(root)

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

        # Canvas 14x14 com glow ring + dot principal
        self._dot_canvas = tk.Canvas(
            top_row, width=14, height=14,
            bg=_COLORS["bg_card"], highlightthickness=0,
        )
        self._dot_canvas.pack(side="left", padx=(0, 8))
        # Glow ring (oval externo)
        self._dot_glow = self._dot_canvas.create_oval(0, 0, 13, 13,
            fill="", outline=_COLORS["recording"], width=1)
        # Dot principal (oval interno)
        self._dot_oval = self._dot_canvas.create_oval(2, 2, 11, 11,
            fill=_COLORS["recording"], outline="")

        self._state_label = tk.Label(
            top_row, text="Gravando...",
            font=self._font_heading,
            fg=_COLORS["text"], bg=_COLORS["bg_card"],
        )
        self._state_label.pack(side="left")

        # Linha inferior: preview do texto
        self._text_label = tk.Label(
            inner, text="",
            font=self._font_body,
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
        elif overlay_state == STATE_MODE_CHANGE:
            # Story 4.6.2: fundo escuro, seta + nome do modo em destaque, 1.5s
            color = _COLORS["purple"]
            label = f"→ {text}" if text else "→ Modo"
            info = ""
            self._dismiss_id = self._root.after(_MODE_CHANGE_DISMISS_MS, self._hide)
        else:
            self._hide()
            return

        self._dot_canvas.itemconfig(self._dot_oval, fill=color)
        if hasattr(self, "_dot_glow"):
            self._dot_canvas.itemconfig(self._dot_glow, outline=color)
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
        if not self._root:
            return
        if self._dot_anim_id is not None:
            self._root.after_cancel(self._dot_anim_id)
            self._dot_anim_id = None
        if self._dismiss_id is not None:
            self._root.after_cancel(self._dismiss_id)
            self._dismiss_id = None
        self._root.withdraw()

    def _start_dot_anim(self) -> None:
        """Pulse suave de 3 frames durante processamento."""
        colors = [_COLORS["processing"], "#4B5EF9", _COLORS["muted"]]
        self._dot_frame = 0

        def _anim():
            if self._current_state != STATE_PROCESSING:
                return
            c = colors[self._dot_frame % 3]
            self._dot_canvas.itemconfig(self._dot_oval, fill=c)
            if hasattr(self, "_dot_glow"):
                self._dot_canvas.itemconfig(self._dot_glow, outline=c)
            self._dot_frame += 1
            self._dot_anim_id = self._root.after(300, _anim)

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
            if not t._ready.is_set():
                print("[WARN] Overlay thread não inicializou — overlay desativado")
                return None
            _thread = t
    return _thread


def show_recording(clipboard_chars: int = 0, window_hint: str = "", screenshot_taken: bool = False) -> None:
    """Exibe overlay no estado 'Gravando'.

    clipboard_chars > 0 indica contexto carregado.
    window_hint: nome do processo da janela ativa (Feature 2).
    screenshot_taken: True se screenshot foi capturado (Feature 3).
    """
    t = _get_thread()
    if t is None:
        return
    parts = []
    if screenshot_taken:
        parts.append("Screenshot capturado")
    elif clipboard_chars > 0:
        parts.append(f"Clipboard carregado ({clipboard_chars} chars)")
    if window_hint:
        parts.append(window_hint)
    info = " · ".join(parts)
    t.send("show", state=STATE_RECORDING, text=info)


def show_processing(mode: str = "") -> None:
    """Exibe overlay no estado 'Processando'."""
    t = _get_thread()
    if t is None:
        return
    label = _MODE_LABELS.get(mode, mode) if mode else ""
    t.send("show", state=STATE_PROCESSING, text=label)


def show_done(output_text: str = "") -> None:
    """Exibe overlay no estado 'Pronto' com preview das primeiras 60 chars."""
    t = _get_thread()
    if t is None:
        return
    t.send("show", state=STATE_DONE, text=output_text)


def show_mode_change(mode: str) -> None:
    """Story 4.6.2: Exibe overlay com nome do novo modo por 1.5s ao ciclar."""
    t = _get_thread()
    if t is None:
        return
    mode_name = _MODE_NAMES_PT.get(mode, mode)
    t.send("show", state=STATE_MODE_CHANGE, text=mode_name)


def hide() -> None:
    """Esconde o overlay imediatamente."""
    t = _get_thread()
    if t is None:
        return
    t.send("hide")
