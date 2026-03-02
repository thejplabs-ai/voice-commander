# voice/briefing.py — Feature 4: Briefing Matinal
# Resumo diário das transcrições exibido no startup (não-modal, auto-dismiss 8s).

import json
import os
import threading
import time
from datetime import datetime, timedelta

from voice import state


def run_briefing_check() -> None:
    """Ponto de entrada — chamado em thread daemon após startup.

    Verifica condições e exibe janela de briefing se aplicável.
    """
    if state._CONFIG.get("BRIEFING_ENABLED", "true").lower() != "true":
        return

    # Aguardar 3s para o app estar totalmente inicializado
    time.sleep(3)

    if not _should_show_briefing():
        return

    entries = _load_recent_history(hours=24)
    min_entries = state._CONFIG.get("BRIEFING_MIN_ENTRIES", 3)
    if len(entries) < min_entries:
        print(f"[INFO] Briefing pulado — apenas {len(entries)}/{min_entries} entradas nas últimas 24h")
        return

    print(f"[...]  Gerando briefing matinal ({len(entries)} entradas)...")
    from voice import gemini
    text = gemini.generate_daily_briefing(entries)
    if not text:
        print("[WARN] Briefing vazio — gemini retornou string vazia")
        return

    # Gravar timestamp antes de exibir (evita re-exibição se janela crashar)
    try:
        from voice.user_profile import update_last_briefing
        update_last_briefing()
    except Exception as e:
        print(f"[WARN] Falha ao gravar last_briefing_at: {e}")

    _show_briefing_window(text)


def _should_show_briefing() -> bool:
    """Checa time gate de 8h desde o último briefing."""
    profile = getattr(state, "_user_profile", {})
    last_at = profile.get("last_briefing_at")
    if not last_at:
        return True
    try:
        last_dt = datetime.fromisoformat(last_at)
        gate = timedelta(hours=8)
        if datetime.now() - last_dt < gate:
            elapsed_h = (datetime.now() - last_dt).total_seconds() / 3600
            print(f"[INFO] Briefing suprimido — último há {elapsed_h:.1f}h (gate: 8h)")
            return False
    except Exception:
        pass  # data inválida → mostrar
    return True


def _load_recent_history(hours: int = 24) -> list:
    """Lê history.jsonl e filtra entradas das últimas N horas sem erro."""
    history_path = state._history_path
    if not history_path or not os.path.exists(history_path):
        return []

    cutoff = datetime.now() - timedelta(hours=hours)
    entries = []
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    # Filtrar erros
                    if entry.get("error"):
                        continue
                    # Filtrar por timestamp
                    ts_str = entry.get("timestamp", "")
                    if ts_str:
                        try:
                            ts = datetime.fromisoformat(ts_str)
                            if ts < cutoff:
                                continue
                        except Exception:
                            pass
                    entries.append(entry)
                except Exception:
                    continue
    except Exception as e:
        print(f"[WARN] Falha ao ler history.jsonl para briefing: {e}")

    return entries


def _show_briefing_window(text: str) -> None:
    """Exibe janela CTk não-modal com briefing. Auto-dismiss em 8s com countdown."""
    if not state._ctk_available:
        print(f"[INFO] Briefing (CTk indisponível — printando no console):\n{text}")
        return

    def _run_window():
        try:
            import customtkinter as ctk
            from voice import theme

            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("dark-blue")

            win = ctk.CTk()
            win.overrideredirect(False)
            win.title("Voice Commander — Briefing Matinal")
            win.wm_attributes("-topmost", True)
            win.configure(fg_color=theme.BG_ABYSS)
            win.resizable(False, False)

            # Posicionar no canto superior direito
            win.update_idletasks()
            sw = win.winfo_screenwidth()
            w, h = 380, 200
            x = sw - w - 24
            y = 60
            win.geometry(f"{w}x{h}+{x}+{y}")

            # Título
            header = ctk.CTkFrame(win, fg_color="transparent")
            header.pack(fill="x", padx=16, pady=(12, 4))
            ctk.CTkLabel(
                header, text="☀ Briefing Matinal",
                font=theme.FONT_BODY_BOLD(),
                text_color=theme.TEXT_PRIMARY,
                anchor="w",
            ).pack(side="left")

            countdown_lbl = ctk.CTkLabel(
                header, text="Fechando em 8s...",
                font=theme.FONT_CAPTION(),
                text_color=theme.TEXT_MUTED,
                anchor="e",
            )
            countdown_lbl.pack(side="right")

            # Conteúdo
            ctk.CTkLabel(
                win, text=text,
                font=theme.FONT_CAPTION(),
                text_color=theme.TEXT_SECONDARY,
                anchor="w",
                justify="left",
                wraplength=w - 32,
            ).pack(fill="x", padx=16, pady=(0, 8))

            # Botão fechar
            ctk.CTkButton(
                win, text="Fechar", height=28,
                corner_radius=theme.CORNER_MD,
                fg_color=theme.BG_ELEVATED,
                hover_color=theme.BG_NIGHT,
                font=theme.FONT_CAPTION(),
                text_color=theme.TEXT_MUTED,
                command=win.destroy,
            ).pack(pady=(0, 12))

            # Countdown + auto-dismiss
            _remaining = [8]

            def _tick():
                if not _remaining[0]:
                    try:
                        win.destroy()
                    except Exception:
                        pass
                    return
                _remaining[0] -= 1
                try:
                    if win.winfo_exists():
                        countdown_lbl.configure(text=f"Fechando em {_remaining[0]}s...")
                        win.after(1000, _tick)
                except Exception:
                    pass

            win.after(1000, _tick)
            win.mainloop()

        except Exception as e:
            print(f"[WARN] Briefing window falhou: {e}")

    t = threading.Thread(target=_run_window, daemon=True)
    t.start()
