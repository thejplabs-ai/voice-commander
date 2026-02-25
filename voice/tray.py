# voice/tray.py — system tray icon management
# quit_callback injected from app.py — no import of shutdown to avoid cycle

import threading

from voice import state

# Tentar importar pystray e Pillow — fallback silencioso se não disponíveis
try:
    import pystray
    from PIL import Image, ImageDraw
    state._tray_available = True
except ImportError:
    print("[WARN] pystray/Pillow não instalados — system tray desativado. "
          "Instale com: pip install pystray Pillow")


def _make_tray_icon(tray_state: str = "idle") -> "Image.Image":
    """
    Gera ícone 64x64 RGBA com círculo colorido indicando o estado:
    - idle:       cinza  (#808080)
    - recording:  vermelho (#FF3333)
    - processing: amarelo  (#FFD700)
    """
    color_map = {
        "idle":       "#808080",
        "recording":  "#FF3333",
        "processing": "#FFD700",
    }
    color = color_map.get(tray_state, "#808080")
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Círculo preenchido com margem de 4px
    draw.ellipse([4, 4, 60, 60], fill=color)
    return img


def _tray_tooltip() -> str:
    state_labels = {
        "idle":       "Idle",
        "recording":  "Gravando",
        "processing": "Processando",
    }
    label = state_labels.get(state._tray_state, state._tray_state)
    return f"Voice Commander | {label} | Último: {state._tray_last_mode}"


def _update_tray_state(tray_state: str, mode: str | None = None) -> None:
    """Atualiza ícone e tooltip da system tray."""
    state._tray_state = tray_state
    if mode is not None:
        state._tray_last_mode = mode
    if state._tray_icon is not None and state._tray_available:
        try:
            state._tray_icon.icon = _make_tray_icon(tray_state)
            state._tray_icon.title = _tray_tooltip()
        except Exception as e:
            print(f"[WARN] Falha ao atualizar ícone da tray: {e}")


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
        "transcribe": "Transcrição pura",
        "simple":     "Prompt simples",
        "prompt":     "Prompt COSTAR",
        "query":      "Query Gemini",
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
                win.configure(fg_color="#01010D")
                win.resizable(False, False)
                _icon = _resource_path("icon.ico")
                if _icon.exists():
                    win.iconbitmap(str(_icon))
                    _apply_taskbar_icon(win, _icon)
                # Protocolo de fechamento — garante que o X fecha a janela
                win.protocol("WM_DELETE_WINDOW", win.destroy)

                pad_x, pad_y = 28, 12
                _ctk.CTkLabel(win, text="Voice Commander",
                              font=("Segoe UI", 16, "bold"),
                              text_color="#FFFFFF").pack(anchor="w", padx=pad_x, pady=(20, 2))
                _ctk.CTkFrame(win, height=1, fg_color="#2A2A3A",
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
                                  font=("Segoe UI", 11), text_color="#808080",
                                  width=90, anchor="w").pack(side="left")
                    _ctk.CTkLabel(row, text=value,
                                  font=("Segoe UI", 11, "bold"), text_color="#FFFFFF",
                                  anchor="w", wraplength=240, justify="left").pack(
                        side="left", padx=(4, 0))

                _ctk.CTkButton(win, text="Fechar", width=180, height=38,
                               corner_radius=8, fg_color="#6B2FF8",
                               hover_color="#5A28D6",
                               font=("Segoe UI", 12, "bold"),
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
        import os as _os
        print("[INFO] Encerramento solicitado via system tray.")
        try:
            icon.stop()
        except Exception:
            pass
        if quit_callback is not None:
            quit_callback()
        _os._exit(0)

    def _open_settings_from_tray():
        from voice.ui import _open_settings
        _open_settings()

    try:
        menu = pystray.Menu(
            pystray.MenuItem("⚙ Configurações", lambda icon, item: _open_settings_from_tray()),
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
        except Exception:
            pass
        state._tray_icon = None
