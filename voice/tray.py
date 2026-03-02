# voice/tray.py — system tray icon management
# quit_callback injected from app.py — no import of shutdown to avoid cycle

import threading
import time

from voice import state
from voice import theme

# Tentar importar pystray e Pillow — fallback silencioso se não disponíveis
try:
    import pystray
    from PIL import Image, ImageDraw
    state._tray_available = True
except ImportError:
    print("[WARN] pystray/Pillow não instalados — system tray desativado. "
          "Instale com: pip install pystray Pillow")


_STATE_COLORS = {
    "idle":       theme.TRAY_IDLE,       # #6B2FF8 purple-labs
    "recording":  theme.TRAY_RECORDING,  # #FF3366 error red
    "processing": theme.TRAY_PROCESSING, # #1E38F7 blue-neo
}


def _make_tray_icon(tray_state: str = "idle") -> "Image.Image":
    """
    Gera ícone 64x64 RGBA com rounded square + wave bars indicando o estado:
    - idle:       roxo   (#6B2FF8) — brand purple
    - recording:  vermelho (#FF3366) — error red
    - processing: azul   (#1E38F7) — blue-neo
    """
    color = _STATE_COLORS.get(tray_state, theme.TRAY_IDLE)
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Rounded square background
    draw.rounded_rectangle([4, 4, 60, 60], radius=14, fill=color)
    # Wave bars (sound visualization) — white 80% opacity
    bar = (255, 255, 255, 200)
    draw.rounded_rectangle([19, 24, 25, 40], radius=3, fill=bar)  # short
    draw.rounded_rectangle([29, 18, 35, 46], radius=3, fill=bar)  # tall
    draw.rounded_rectangle([39, 22, 45, 42], radius=3, fill=bar)  # medium
    return img


# Story 4.6.2: mapeamento de nomes de modo em português claro
_MODE_NAMES_PT = {
    "transcribe":        "Transcrever",
    "email":             "Email",
    "simple":            "Prompt Simples",
    "prompt":            "Prompt COSTAR",
    "query":             "Perguntar ao Gemini",
    "visual":            "Screenshot + Voz",
    "pipeline":          "Pipeline",
    "clipboard_context": "Contexto do Clipboard",
    "bullet":            "Bullet Dump",
    "translate":         "Traduzir",
    "—":                 "—",
}


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
    """QW-6: Inicia thread que atualiza o tooltip da tray a cada 1s durante gravação."""
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
    state._tray_state = tray_state
    if mode is not None:
        state._tray_last_mode = mode
    # QW-6: rastrear início da gravação para tooltip dinâmico
    if tray_state == "recording":
        state._recording_start_time = time.time()
        _start_recording_tooltip_thread()
    elif tray_state != "recording":
        state._recording_start_time = 0.0
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

# Inclui modos com hotkey dedicado (visual/pipeline) — para status e labels
_MODES_EXTENDED = _MODES + [
    ("visual",   "Visual Query"),
    ("pipeline", "Pipeline"),
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
    """Menu item 'Status' — abre popup CTk (ou MessageBox fallback) com info atual."""
    import ctypes
    from voice.paths import _resource_path
    from voice.ui import _apply_taskbar_icon

    state_labels = {
        "idle":       "Idle (aguardando hotkey)",
        "recording":  "Gravando...",
        "processing": "Processando transcrição...",
    }
    mode_labels = {
        "transcribe": "Transcrever",
        "simple":     "Prompt Simples",
        "prompt":     "Prompt COSTAR",
        "query":      "Query AI",
        "bullet":     "Bullet Dump",
        "email":      "Email Draft",
        "translate":  "Traduzir",
        "visual":     "Visual Query",
        "pipeline":   "Pipeline",
        "—":          "—",
    }
    gemini_status = "Ativo" if state._GEMINI_API_KEY else "Desativado"
    state_label = state_labels.get(state._tray_state, state._tray_state)
    mode_label  = mode_labels.get(state._tray_last_mode, state._tray_last_mode)

    if state._ctk_available:
        # Popup CTk com botão Fechar e protocolo WM_DELETE_WINDOW — fecha corretamente
        def _show_ctk_status():
            try:
                import customtkinter as _ctk
                _ctk.set_appearance_mode("dark")
                _ctk.set_default_color_theme("dark-blue")
                win = _ctk.CTk()
                win.title("Voice Commander — Status")
                win.attributes("-topmost", True)
                win.configure(fg_color=theme.BG_ABYSS)
                win.resizable(False, False)
                _icon = _resource_path("icon.ico")
                if _icon.exists():
                    win.iconbitmap(str(_icon))
                    _apply_taskbar_icon(win, _icon)
                # Protocolo de fechamento — garante que o X fecha a janela
                win.protocol("WM_DELETE_WINDOW", win.destroy)

                pad_x, pad_y = 28, 12
                _ctk.CTkLabel(win, text="Voice Commander",
                              font=theme.FONT_HEADING_SM(),
                              text_color=theme.TEXT_PRIMARY).pack(anchor="w", padx=pad_x, pady=(20, 2))
                _ctk.CTkFrame(win, height=1, fg_color=theme.BORDER_DEFAULT,
                              corner_radius=0).pack(fill="x", padx=pad_x, pady=(0, 12))

                rows = [
                    ("Estado",       state_label),
                    ("Último modo",  mode_label),
                    ("Gemini",       gemini_status),
                    ("Whisper",      state._CONFIG.get("WHISPER_MODEL", "small")),
                    ("Log",          state._log_path),
                ]
                for label, value in rows:
                    row = _ctk.CTkFrame(win, fg_color="transparent")
                    row.pack(fill="x", padx=pad_x, pady=(0, pad_y))
                    _ctk.CTkLabel(row, text=f"{label}:",
                                  font=theme.FONT_CAPTION(), text_color=theme.TEXT_MUTED,
                                  width=90, anchor="w").pack(side="left")
                    _ctk.CTkLabel(row, text=value,
                                  font=theme.FONT_BODY_BOLD(), text_color=theme.TEXT_PRIMARY,
                                  anchor="w", wraplength=240, justify="left").pack(
                        side="left", padx=(4, 0))

                _ctk.CTkButton(win, text="Fechar", width=180, height=theme.BTN_HEIGHT,
                               corner_radius=theme.CORNER_MD, fg_color=theme.PURPLE,
                               hover_color=theme.PURPLE_HOVER,
                               font=theme.FONT_BODY_BOLD(),
                               command=win.destroy).pack(pady=(8, 20))

                win.update_idletasks()
                sw = win.winfo_screenwidth()
                sh = win.winfo_screenheight()
                w  = win.winfo_reqwidth()  + 16
                h  = win.winfo_reqheight() + 16
                x  = (sw - w) // 2
                y  = (sh - h) // 2
                win.geometry(f"{w}x{h}+{x}+{y}")
                win.mainloop()
            except Exception as exc:
                print(f"[WARN] Falha ao abrir popup de status: {exc}")

        threading.Thread(target=_show_ctk_status, daemon=True).start()
    else:
        # Fallback: MessageBox nativa (só um botão OK — fecha ao clicar OK)
        msg = (
            f"Voice Commander — JP Labs\n\n"
            f"Estado:      {state_label}\n"
            f"Último modo: {mode_label}\n"
            f"Gemini:      {gemini_status}\n"
            f"Whisper:     {state._CONFIG.get('WHISPER_MODEL', 'small')}\n"
            f"Log:         {state._log_path}"
        )
        ctypes.windll.user32.MessageBoxW(0, msg, "Voice Commander — Status", 0x40)


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
        from voice.ui import _open_settings
        _open_settings()

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
            pystray.MenuItem("Configuracoes", lambda icon, item: _open_settings_from_tray()),
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
