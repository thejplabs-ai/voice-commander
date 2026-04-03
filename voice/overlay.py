# voice/overlay.py — Story 4.5.1: Toast/overlay de feedback pós-hotkey
#
# Implementação com tkinter puro em thread daemon com fila de mensagens.
# Usa wm_overrideredirect + wm_attributes("-topmost") para não roubar foco.
# Thread-safe: toda comunicação via queue.Queue.

import math
import queue
import threading
import time
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
    "bg":          "#0F0F0F",   # theme.BG_ABYSS
    "bg_card":     "#1A1A1E",   # theme.BG_DEEP
    "border":      "#2A2A2E",   # theme.BORDER_DEFAULT
    "recording":   "#D4626E",   # theme.TRAY_RECORDING (muted rose)
    "processing":  "#6B8EBF",   # theme.TRAY_PROCESSING (steel blue)
    "done":        "#7EC89B",   # theme.SUCCESS (sage green)
    "text":        "#F5F5F0",   # theme.TEXT_PRIMARY (cream-white)
    "muted":       "#807E7A",   # theme.TEXT_MUTED
    "purple":      "#C4956A",   # theme.PURPLE (warm amber)
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
        head = "Figtree" if "Figtree" in available else "Segoe UI"
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
        # Animation state
        self._show_anim_id = None
        self._hide_anim_id = None
        self._pulse_start: float = 0.0
        self._target_y: int = 0

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

        # Cancelar animacoes/dismiss pendentes
        for aid in (self._dismiss_id, self._dot_anim_id, self._show_anim_id, self._hide_anim_id):
            if aid is not None:
                try:
                    self._root.after_cancel(aid)
                except Exception:
                    pass
        self._dismiss_id = self._dot_anim_id = self._show_anim_id = self._hide_anim_id = None

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
            self._dismiss_id = self._root.after(_DONE_DISMISS_MS, self._animate_hide)
        elif overlay_state == STATE_MODE_CHANGE:
            color = _COLORS["purple"]
            label = f"  {text}" if text else "  Modo"
            info = ""
            self._dismiss_id = self._root.after(_MODE_CHANGE_DISMISS_MS, self._animate_hide)
        else:
            self._hide()
            return

        self._dot_canvas.itemconfig(self._dot_oval, fill=color)
        if hasattr(self, "_dot_glow"):
            self._dot_canvas.itemconfig(self._dot_glow, outline=color)
        self._state_label.config(text=label, fg=color if overlay_state == STATE_DONE else _COLORS["text"])
        self._text_label.config(text=info)

        # Calcular posicao final
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x = sw - _OVERLAY_W - _MARGIN_RIGHT
        self._target_y = sh - _OVERLAY_H - _MARGIN_BOTTOM

        # Slide up + fade in (250ms, ease-out-cubic)
        start_y = self._target_y + 20
        self._root.geometry(f"{_OVERLAY_W}x{_OVERLAY_H}+{x}+{start_y}")
        try:
            self._root.wm_attributes("-alpha", 0.0)
        except Exception:
            pass
        self._root.deiconify()
        self._root.update_idletasks()

        # Animate: 8 frames over ~250ms (30fps)
        self._show_frame = 0
        self._show_x = x

        def _anim_show():
            self._show_frame += 1
            t = min(1.0, self._show_frame / 8.0)
            # ease-out-cubic
            t_eased = 1 - (1 - t) ** 3
            y = int(start_y + (self._target_y - start_y) * t_eased)
            alpha = t_eased
            try:
                self._root.geometry(f"{_OVERLAY_W}x{_OVERLAY_H}+{self._show_x}+{y}")
                self._root.wm_attributes("-alpha", alpha)
            except Exception:
                return
            if t < 1.0:
                self._show_anim_id = self._root.after(33, _anim_show)
            else:
                self._show_anim_id = None

        self._show_anim_id = self._root.after(33, _anim_show)

    def _hide(self) -> None:
        """Esconde imediatamente (sem animacao)."""
        self._current_state = STATE_HIDE
        if not self._root:
            return
        for aid in (self._dot_anim_id, self._dismiss_id, self._show_anim_id, self._hide_anim_id):
            if aid is not None:
                try:
                    self._root.after_cancel(aid)
                except Exception:
                    pass
        self._dot_anim_id = self._dismiss_id = self._show_anim_id = self._hide_anim_id = None
        self._root.withdraw()

    def _animate_hide(self) -> None:
        """Fade out em 200ms (6 frames), depois withdraw."""
        if not self._root or self._current_state == STATE_HIDE:
            return
        self._current_state = STATE_HIDE
        # Cancelar animacoes pendentes
        for aid in (self._dot_anim_id, self._dismiss_id, self._show_anim_id):
            if aid is not None:
                try:
                    self._root.after_cancel(aid)
                except Exception:
                    pass
        self._dot_anim_id = self._dismiss_id = self._show_anim_id = None

        self._hide_frame = 0

        def _anim_hide():
            self._hide_frame += 1
            t = min(1.0, self._hide_frame / 6.0)
            alpha = max(0.0, 1.0 - t)
            try:
                self._root.wm_attributes("-alpha", alpha)
            except Exception:
                self._root.withdraw()
                return
            if t < 1.0:
                self._hide_anim_id = self._root.after(33, _anim_hide)
            else:
                self._hide_anim_id = None
                self._root.withdraw()

        self._hide_anim_id = self._root.after(33, _anim_hide)

    def _start_dot_anim(self) -> None:
        """Pulse suave contínuo via sine wave a 30fps durante processamento."""
        self._pulse_start = time.monotonic()
        base_color = _COLORS["processing"]
        bg_color = _COLORS["bg_card"]

        def _hex_to_rgb(h: str) -> tuple:
            h = h.lstrip("#")
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

        def _rgb_to_hex(r: int, g: int, b: int) -> str:
            return f"#{r:02x}{g:02x}{b:02x}"

        r1, g1, b1 = _hex_to_rgb(base_color)
        r0, g0, b0 = _hex_to_rgb(bg_color)

        def _pulse():
            if self._current_state != STATE_PROCESSING:
                return
            elapsed = time.monotonic() - self._pulse_start
            # Sine wave: 0.5-1.0 brightness, 1.5s period
            brightness = 0.5 + 0.5 * math.sin(2 * math.pi * elapsed / 1.5)
            r = int(r0 + (r1 - r0) * brightness)
            g = int(g0 + (g1 - g0) * brightness)
            b = int(b0 + (b1 - b0) * brightness)
            c = _rgb_to_hex(r, g, b)
            try:
                self._dot_canvas.itemconfig(self._dot_oval, fill=c)
                if hasattr(self, "_dot_glow"):
                    self._dot_canvas.itemconfig(self._dot_glow, outline=c)
            except Exception:
                return
            self._dot_anim_id = self._root.after(33, _pulse)  # 30fps

        _pulse()

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
    if state._CONFIG.get("OVERLAY_ENABLED", True) is not True:
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


def show_recording(clipboard_chars: int = 0) -> None:
    """Exibe overlay no estado 'Gravando'.

    clipboard_chars > 0 indica contexto do clipboard carregado.
    """
    t = _get_thread()
    if t is None:
        return
    info = f"Clipboard carregado ({clipboard_chars} chars)" if clipboard_chars > 0 else ""
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
