# voice/history_search.py — Story 4.5.5: Overlay de busca no histórico de transcrições
# Abre janela CTk com campo de busca e lista de resultados do history.jsonl

import json
import threading

from voice import state


def _load_history() -> list[dict]:
    """Lê todas as entradas do history.jsonl. Retorna lista vazia se falhar."""
    try:
        with open(state._history_path, "r", encoding="utf-8") as f:
            entries = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            return list(reversed(entries))  # mais recente primeiro
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"[WARN] Falha ao ler histórico: {e}")
        return []


def _search_entries(entries: list[dict], query: str) -> list[dict]:
    """Filtra entradas onde query aparece em raw_text ou processed_text."""
    if not query.strip():
        return entries
    q = query.lower()
    return [
        e for e in entries
        if q in (e.get("raw_text") or "").lower()
        or q in (e.get("processed_text") or "").lower()
    ]


def _format_entry(entry: dict) -> str:
    """Formata uma entrada para exibição na lista (80 chars max)."""
    ts = entry.get("timestamp", "")[:16].replace("T", " ")
    mode = entry.get("mode", "?")
    text = entry.get("processed_text") or entry.get("raw_text") or ""
    preview = text[:80] + ("..." if len(text) > 80 else "")
    return f"[{ts}] [{mode}] {preview}"


class HistorySearchWindow:
    """Overlay de busca no histórico — CTk singleton, fecha com ESC ou ao colar."""

    def __init__(self):
        self._root = None
        self._entries: list[dict] = []
        self._filtered: list[dict] = []
        self._search_var = None
        self._listbox = None
        self._status_label = None

    def open(self) -> None:
        """Abre janela em thread daemon."""
        try:
            import customtkinter  # noqa: F401
        except ImportError:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                "Busca de histórico requer customtkinter.\n"
                "Instale com: pip install customtkinter==5.2.2",
                "Voice Commander",
                0x40,
            )
            return
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def _run(self) -> None:
        try:
            self._entries = _load_history()
            self._filtered = self._entries[:]
            self._build()
            self._root.mainloop()
        except Exception as e:
            print(f"[WARN] HistorySearch encerrada: {e}")

    def _build(self) -> None:
        import customtkinter as ctk
        from voice import theme
        from voice.paths import _resource_path

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self._root = ctk.CTk()
        self._root.title("Voice Commander — Histórico")
        self._root.resizable(False, False)
        self._root.configure(fg_color=theme.BG_ABYSS)
        # Não aparece na taskbar
        self._root.wm_attributes("-toolwindow", 1)
        self._root.attributes("-topmost", True)

        _icon = _resource_path("icon.ico")
        if _icon.exists():
            self._root.iconbitmap(str(_icon))

        self._root.protocol("WM_DELETE_WINDOW", self._close)
        self._root.bind("<Escape>", lambda e: self._close())

        # Tamanho e posição — canto inferior direito
        w, h = 600, 480
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x = sw - w - 24
        y = sh - h - 60
        self._root.geometry(f"{w}x{h}+{x}+{y}")

        pad = 16

        # Header
        header = ctk.CTkFrame(self._root, fg_color=theme.BG_DEEP, corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(
            header, text="Histórico de transcrições",
            font=theme.FONT_HEADING_SM(), text_color=theme.TEXT_PRIMARY,
        ).pack(anchor="w", padx=pad, pady=(12, 4))
        ctk.CTkLabel(
            header,
            text=f"{len(self._entries)} entradas | ESC ou Fechar para sair | Enter para colar",
            font=theme.FONT_CAPTION(), text_color=theme.TEXT_MUTED,
        ).pack(anchor="w", padx=pad, pady=(0, 10))

        # Separador
        ctk.CTkFrame(self._root, height=1, fg_color=theme.BORDER_DEFAULT, corner_radius=0).pack(fill="x")

        # Campo de busca
        search_frame = ctk.CTkFrame(self._root, fg_color=theme.BG_NIGHT, corner_radius=0)
        search_frame.pack(fill="x", padx=0, pady=0)
        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", self._on_search_change)
        ctk.CTkEntry(
            search_frame,
            textvariable=self._search_var,
            placeholder_text="Buscar em raw_text e processed_text...",
            font=theme.FONT_BODY(),
            fg_color=theme.BG_DEEP,
            border_color=theme.BORDER_DEFAULT,
            text_color=theme.TEXT_PRIMARY,
            height=40,
        ).pack(fill="x", padx=pad, pady=10)

        # Lista de resultados — usar CTkScrollableFrame + labels clicáveis
        self._list_frame = ctk.CTkScrollableFrame(
            self._root,
            fg_color=theme.BG_ABYSS,
            corner_radius=0,
        )
        self._list_frame.pack(fill="both", expand=True, padx=0, pady=0)

        # Status bar
        status_bar = ctk.CTkFrame(self._root, fg_color=theme.BG_DEEP, height=36, corner_radius=0)
        status_bar.pack(fill="x", side="bottom")
        status_bar.pack_propagate(False)
        self._status_label = ctk.CTkLabel(
            status_bar, text="",
            font=theme.FONT_CAPTION(), text_color=theme.TEXT_MUTED,
        )
        self._status_label.pack(anchor="w", padx=pad, pady=8)

        # Renderizar lista inicial
        self._render_list()

        # Focar campo de busca
        self._root.after(100, lambda: self._root.focus_force())

    def _on_search_change(self, *_) -> None:
        """Chamado cada vez que o texto de busca muda."""
        query = self._search_var.get() if self._search_var else ""
        self._filtered = _search_entries(self._entries, query)
        self._render_list()

    def _render_list(self) -> None:
        """Re-renderiza a lista de resultados filtrados."""
        import customtkinter as ctk
        from voice import theme

        # Limpar lista atual
        for widget in self._list_frame.winfo_children():
            widget.destroy()

        if not self._filtered:
            ctk.CTkLabel(
                self._list_frame,
                text="Nenhum resultado encontrado.",
                font=theme.FONT_BODY(), text_color=theme.TEXT_MUTED,
            ).pack(pady=20)
            if self._status_label:
                self._status_label.configure(text="0 resultados")
            return

        for i, entry in enumerate(self._filtered[:200]):  # limitar a 200 na UI
            label_text = _format_entry(entry)
            row = ctk.CTkFrame(
                self._list_frame,
                fg_color=theme.BG_NIGHT if i % 2 == 0 else theme.BG_ABYSS,
                corner_radius=6,
                cursor="hand2",
            )
            row.pack(fill="x", padx=8, pady=2)

            ctk.CTkLabel(
                row,
                text=label_text,
                font=theme.FONT_CAPTION(),
                text_color=theme.TEXT_SECONDARY,
                anchor="w",
                wraplength=550,
                justify="left",
            ).pack(anchor="w", padx=10, pady=6)

            # Bind click para colar
            def _make_paste_fn(e=entry):
                return lambda event: self._paste_entry(e)

            row.bind("<Button-1>", _make_paste_fn())
            for child in row.winfo_children():
                child.bind("<Button-1>", _make_paste_fn())

        if self._status_label:
            total = len(self._filtered)
            shown = min(total, 200)
            self._status_label.configure(
                text=f"{total} resultado(s)" + (f" — exibindo {shown}" if total > 200 else "")
            )

    def _paste_entry(self, entry: dict) -> None:
        """Cola o processed_text da entrada selecionada e fecha a janela."""
        text = entry.get("processed_text") or entry.get("raw_text") or ""
        if not text:
            return
        try:
            from voice.clipboard import copy_to_clipboard, paste_via_sendinput
            import time
            self._close()
            time.sleep(0.2)  # dar tempo para a janela fechar antes de colar
            copy_to_clipboard(text)
            paste_via_sendinput()
            print(f"[OK]   Histórico colado ({len(text)} chars)")
        except Exception as e:
            print(f"[WARN] Falha ao colar do histórico: {e}")

    def _close(self) -> None:
        """Fecha a janela e libera referência global."""
        global _history_window_ref
        if self._root is not None:
            try:
                if self._root.winfo_exists():
                    self._root.destroy()
            except Exception:
                pass
            self._root = None
        with _history_window_lock:
            if _history_window_ref is self:
                _history_window_ref = None


_history_window_ref: HistorySearchWindow | None = None
_history_window_lock = threading.Lock()


def open_history_search() -> None:
    """Story 4.5.5: Abre o overlay de busca de histórico (singleton)."""
    global _history_window_ref
    with _history_window_lock:
        existing = _history_window_ref
        if existing is not None and existing._root is not None:
            try:
                if existing._root.winfo_exists():
                    existing._root.lift()
                    existing._root.focus_force()
                    return
            except Exception:
                pass
        win = HistorySearchWindow()
        _history_window_ref = win
    win.open()
