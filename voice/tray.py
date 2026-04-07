# voice/tray.py — system tray icon management
# quit_callback injected from app.py — no import of shutdown to avoid cycle

import threading
import time

from voice import state
from voice import theme
from voice.modes import MODE_NAMES_PT as _MODE_NAMES_PT

# Tentar importar pystray e Pillow — fallback silencioso se não disponíveis
try:
    import pystray
    from PIL import Image, ImageDraw
    state._tray_available = True
except ImportError:
    print("[WARN] pystray/Pillow não instalados — system tray desativado. "
          "Instale com: pip install pystray Pillow")


_STATE_COLORS = {
    "idle":       theme.TRAY_IDLE,       # warm amber
    "recording":  theme.TRAY_RECORDING,  # muted rose
    "processing": theme.TRAY_PROCESSING, # steel blue
}


# V-Wave bar layouts at 16x16 (from tray SVGs) — each tuple: (x, y, w, h)
_TRAY_BARS = {
    "idle": [
        (1, 3, 2, 4), (4, 1, 2, 9), (7, 5, 2, 8), (10, 1, 2, 9), (13, 3, 2, 4),
    ],
    "recording": [
        (1, 4, 2, 3), (4, 1, 2, 9), (7, 2, 2, 11), (10, 1, 2, 9), (13, 4, 2, 3),
    ],
    "processing": [
        (1, 4, 2, 3), (4, 3, 2, 7), (7, 5, 2, 8), (10, 3, 2, 7), (13, 4, 2, 3),
    ],
}


def _make_tray_icon(tray_state: str = "idle") -> "Image.Image":
    """
    Gera icone 64x64 RGBA com V-Wave (5 barras formando V + waveform):
    - idle:       amber quente (#C4956A) — balanced
    - recording:  rose (#D4626E) — center bar taller (active capture)
    - processing: steel blue (#6B8EBF) — equalized bars (processing)
    """
    color = _STATE_COLORS.get(tray_state, theme.TRAY_IDLE)
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    bars = _TRAY_BARS.get(tray_state, _TRAY_BARS["idle"])
    scale = 64 / 16.0  # scale from 16x16 SVG to 64x64

    for (bx, by, bw, bh) in bars:
        x0 = int(bx * scale)
        y0 = int(by * scale)
        x1 = int((bx + bw) * scale)
        y1 = int((by + bh) * scale)
        draw.rounded_rectangle([x0, y0, x1, y1], radius=3, fill=color)

    return img



def _tray_tooltip() -> str:
    state_labels = {
        "idle":       "Aguardando",
        "recording":  "Gravando",
        "processing": "Processando",
    }
    estado = state_labels.get(state._tray_state, state._tray_state)
    # QW-6: exibir duração da gravação durante estado recording
    if state._tray_state == "recording" and state._recording_start_time > 0:
        elapsed = int(time.time() - state._recording_start_time)
        m, s = divmod(elapsed, 60)
        estado = f"Gravando: {m}:{s:02d}"
    # Story 4.6.2: formato "Voice Commander — {modo} | {estado}"
    mode_name = _MODE_NAMES_PT.get(state.selected_mode, state.selected_mode)
    return f"Voice Commander — {mode_name} | {estado}"


def _start_recording_tooltip_thread() -> None:
    """QW-6: Inicia (ou reutiliza) thread que atualiza tooltip da tray a cada 1s durante gravação."""
    existing = state._tray_tooltip_thread
    if existing is not None and existing.is_alive():
        return

    def _update_loop():
        while state._tray_state == "recording":
            if state._tray_icon is not None and state._tray_available:
                try:
                    state._tray_icon.title = _tray_tooltip()
                except Exception:
                    pass
            time.sleep(1)

    t = threading.Thread(target=_update_loop, daemon=True)
    t.start()
    state._tray_tooltip_thread = t


def _update_tray_state(tray_state: str, mode: str | None = None) -> None:
    """Atualiza ícone e tooltip da system tray."""
    with state._state_lock:
        state._tray_state = tray_state
        if mode is not None:
            state._tray_last_mode = mode
        # QW-6: rastrear início da gravação para tooltip dinâmico
        if tray_state == "recording":
            state._recording_start_time = time.time()
        elif tray_state != "recording":
            state._recording_start_time = 0.0
    if tray_state == "recording":
        _start_recording_tooltip_thread()
    if state._tray_icon is not None and state._tray_available:
        try:
            state._tray_icon.icon = _make_tray_icon(tray_state)
            state._tray_icon.title = _tray_tooltip()
        except Exception as e:
            print(f"[WARN] Falha ao atualizar ícone da tray: {e}")


_MODES = [
    ("transcribe", "Transcrever"),
    ("simple",     "Prompt Simples"),
    ("prompt",     "Prompt COSTAR"),
    ("query",      "Query AI"),
    ("bullet",     "Bullet Dump"),
    ("email",      "Email Draft"),
    ("translate",  "Traduzir"),
]

def _set_mode(mode: str) -> None:
    """Seleciona o modo ativo e persiste no .env."""
    state.selected_mode = mode
    try:
        from voice.config import _save_env
        _save_env({"SELECTED_MODE": mode})
    except Exception as e:
        print(f"[WARN] Falha ao salvar SELECTED_MODE: {e}")
    print(f"[INFO] Modo selecionado: {mode}")


def _tray_show_status(icon, item) -> None:  # type: ignore[type-arg]
    """Menu item 'Status' — MessageBox nativa em thread separada (nao bloqueia pystray)."""
    import ctypes
    import threading

    state_labels = {
        "idle":       "Idle (aguardando hotkey)",
        "recording":  "Gravando...",
        "processing": "Processando transcrição...",
    }
    gemini_status = "Ativo" if state._GEMINI_API_KEY else "Desativado"
    state_label = state_labels.get(state._tray_state, state._tray_state)
    mode_label  = _MODE_NAMES_PT.get(state.selected_mode, state.selected_mode)

    msg = (
        f"Voice Commander — JP Labs\n\n"
        f"Estado:      {state_label}\n"
        f"Modo ativo:  {mode_label}\n"
        f"Gemini:      {gemini_status}\n"
        f"Whisper:     {state._CONFIG.get('WHISPER_MODEL', 'small')}\n"
        f"Log:         {state._log_path}"
    )
    # MB_ICONINFORMATION | MB_SYSTEMMODAL — thread separada, sempre no topo
    threading.Thread(
        target=lambda: ctypes.windll.user32.MessageBoxW(0, msg, "Voice Commander — Status", 0x1040),
        daemon=True,
    ).start()


def _start_tray(quit_callback=None) -> None:
    """Inicia system tray em thread daemon. Fallback silencioso se pystray indisponível.

    quit_callback: callable invocado ao clicar 'Encerrar' — injected from app.py
    """
    if not state._tray_available:
        return

    def _tray_on_quit(icon, item) -> None:  # type: ignore[type-arg]
        """Menu item 'Encerrar' — shutdown gracioso."""
        print("[INFO] Encerramento solicitado via system tray.")
        try:
            icon.stop()
        except Exception as e:
            print(f"[WARN] Falha ao parar ícone da tray: {e}")
        try:
            if quit_callback is not None:
                quit_callback()
        except Exception as e:
            print(f"[WARN] Erro no quit_callback durante shutdown: {e}")
        # os._exit necessário aqui: threads daemon do pystray impedem sys.exit()
        # quit_callback já executou todo o cleanup (mutex, transcrição pendente)
        import os as _os
        _os._exit(0)

    def _open_settings_from_tray():
        state._settings_requested.set()

    try:
        def _make_mode_item(mode, label):
            def _action(icon, item):
                _set_mode(mode)
            def _checked(item):
                return state.selected_mode == mode
            return pystray.MenuItem(label, _action, checked=_checked, radio=True)

        mode_items = [_make_mode_item(m, lbl) for m, lbl in _MODES]

        # Story 4.6.2: item de modo ativo no topo do menu (não clicável)
        def _active_mode_label(item):
            mode_name = _MODE_NAMES_PT.get(state.selected_mode, state.selected_mode)
            return f"Modo: {mode_name}"

        menu = pystray.Menu(
            pystray.MenuItem(_active_mode_label, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Selecionar Modo", pystray.Menu(*mode_items)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Configurações", lambda icon, item: _open_settings_from_tray()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Status", _tray_show_status),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Encerrar", _tray_on_quit),
        )
        state._tray_icon = pystray.Icon(
            name="VoiceCommander",
            icon=_make_tray_icon("idle"),
            title=_tray_tooltip(),
            menu=menu,
        )

        def _run_tray():
            try:
                state._tray_icon.run()
            except Exception as e:
                print(f"[WARN] System tray encerrada inesperadamente: {e}")

        t = threading.Thread(target=_run_tray, daemon=True)
        t.start()
        print("[OK]   System tray iniciada")
    except Exception as e:
        print(f"[WARN] Falha ao iniciar system tray: {e}")


def _stop_tray() -> None:
    """Remove ícone da tray corretamente (sem fantasma)."""
    if state._tray_icon is not None and state._tray_available:
        try:
            state._tray_icon.stop()
        except Exception as e:
            print(f"[WARN] Falha ao remover ícone da tray: {e}")
        state._tray_icon = None
