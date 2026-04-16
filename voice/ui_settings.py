# voice/ui_settings.py — SettingsWindow (Sidebar Commander, Raycast DNA)
# Extracted from voice/ui.py — see voice/ui.py for backward-compat re-exports.

import threading

from voice import state
from voice import theme
from voice.paths import _resource_path
from voice.config import validate_license_key
from voice.config import _save_env, _reload_config
from voice import __version__

# Imported here so ui.py can re-export without duplication
from voice.ui_helpers import _apply_taskbar_icon  # noqa: F401

# Tentar importar customtkinter — fallback silencioso
try:
    import customtkinter as ctk
except ImportError:
    ctk = None  # type: ignore[assignment]


class SettingsWindow:
    """Settings window com sidebar — Raycast DNA, 640×540px."""

    MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]
    LANGUAGES = ["auto-detect", "pt", "en"]

    # Grid 3x3 — ordem: (mode_id, label, desc)
    MODES_GRID = [
        ("transcribe", "Transcrever",    "Voz → texto"),
        ("simple",     "Prompt Simples", "+contexto"),
        ("prompt",     "COSTAR",         "XML estruturado"),
        ("query",      "Perguntar",      "Gemini responde"),
        ("bullet",     "Bullet Points",  "Lista hierárquica"),
        ("email",      "Email",          "Profissional"),
        ("translate",  "Traduzir",       "EN/PT"),
    ]

    # Mantida para compatibilidade com OnboardingWindow e step_5
    MODES = [
        ("transcribe", "Transcrever",    "Voz → texto corrigido"),
        ("simple",     "Prompt Simples", "Injeta contexto"),
        ("prompt",     "Prompt COSTAR",  "Formato estruturado XML"),
        ("query",      "Query AI",       "Pergunta direta à IA"),
        ("bullet",     "Bullet Dump",    "Voz → bullets hierárquicos"),
        ("email",      "Email Draft",    "Voz → email profissional"),
        ("translate",  "Traduzir",       "Traduz para EN/PT"),
    ]

    def __init__(self):
        self._root = None
        self._scroll = None       # kept for compat
        self._api_entry = None
        self._license_entry = None
        self._license_status_label = None
        self._model_var = None
        self._lang_var = None
        self._dot = None
        self._state_label = None
        self._save_btn = None
        self._eye_btn = None
        self._show_key = False
        self._show_openai_key = False
        self._show_openrouter_key = False
        self._openrouter_key_entry = None
        # New fields
        self._hotkey_entry = None
        self._provider_var = None
        self._openai_key_entry = None
        self._openai_eye_btn = None
        self._openai_key_frame = None
        self._device_var = None
        self._translate_lang_var = None
        self._sound_entries: dict = {}
        self._mode_card_refs: dict = {}
        self._speed_var = None
        # Sidebar navigation state
        self._current_section = "status"
        self._content_area = None
        self._section_btns = {}
        self._section_frames = {}
        self._indicator_bars = {}  # section_id -> CTkFrame (accent bar)

    def open(self):
        """Abre a janela em thread daemon. Singleton — foca se já aberta."""
        with state._settings_window_lock:
            existing = state._settings_window_ref
            if existing is not None:
                try:
                    # QW-8: verificar winfo_exists() antes de interagir com a janela
                    if existing._root is not None and existing._root.winfo_exists():
                        existing._root.lift()
                        existing._root.focus_force()
                        return
                    else:
                        # Janela foi destruída mas ref ainda existe — limpar
                        state._settings_window_ref = None
                except Exception as e:
                    print(f"[WARN] Falha ao focar janela de settings existente: {e}")
                    state._settings_window_ref = None
            state._settings_window_ref = self
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def _run(self):
        try:
            self._build()
            self._root.mainloop()
        except Exception as e:
            print(f"[WARN] SettingsWindow encerrada: {e}")
        finally:
            with state._settings_window_lock:
                if state._settings_window_ref is self:
                    state._settings_window_ref = None

    def _build(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self._root = ctk.CTk()
        # W-04: inicializar _model_var aqui (após CTk root) para que _on_speed_change
        # na seção Geral funcione mesmo sem visitar a seção Avançado primeiro.
        cur_model = state._CONFIG.get("WHISPER_MODEL", "tiny")
        self._model_var = ctk.StringVar(value=cur_model)
        self._root.title("Voice Commander — Configurações")
        self._root.attributes("-topmost", True)
        self._root.configure(fg_color=theme.BG_ABYSS)
        _icon = _resource_path("icon.ico")
        if _icon.exists():
            self._root.iconbitmap(str(_icon))
            _apply_taskbar_icon(self._root, _icon)

        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        w, h = 640, 540
        x = (sw - w) // 2
        y = (sh - h) // 2
        self._root.geometry(f"{w}x{h}+{x}+{y}")
        self._root.minsize(480, 400)
        self._root.resizable(True, True)

        # ── Main: sidebar + right panel ──────────────────────────────────────
        main = ctk.CTkFrame(self._root, fg_color=theme.BG_ABYSS, corner_radius=0)
        main.pack(fill="both", expand=True)

        # Sidebar (200px fixed)
        sidebar = ctk.CTkFrame(main, fg_color=theme.BG_DEEP, corner_radius=0, width=theme.SIDEBAR_WIDTH)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        self._build_sidebar(sidebar)

        # Vertical divider
        ctk.CTkFrame(main, width=1, fg_color=theme.BORDER_DEFAULT, corner_radius=0).pack(
            side="left", fill="y")

        # Right side: content area + footer
        right = ctk.CTkFrame(main, fg_color=theme.BG_ABYSS, corner_radius=0)
        right.pack(side="left", fill="both", expand=True)

        self._content_area = ctk.CTkFrame(right, fg_color=theme.BG_ABYSS, corner_radius=0)
        self._content_area.pack(fill="both", expand=True)

        # Build all section frames (5 nav items)
        self._build_section_status()
        self._build_section_modes()
        self._build_section_general()
        self._build_section_advanced()
        self._build_section_about()

        # Footer
        ctk.CTkFrame(right, height=1, fg_color=theme.BORDER_DEFAULT, corner_radius=0).pack(fill="x")
        self._build_footer(right)

        # Activate default section + start live refresh
        self._switch_section("status")
        self._refresh_status()

    def _build_sidebar(self, parent):
        """Logo + version + nav items (6 items)."""
        logo = ctk.CTkFrame(parent, fg_color="transparent")
        logo.pack(fill="x", padx=16, pady=(20, 4))
        ctk.CTkLabel(logo, text="Voice Commander",
                     font=theme.FONT_HEADING_SM(), text_color=theme.TEXT_PRIMARY,
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(logo, text=f"v{__version__}",
                     font=theme.FONT_CAPTION(), text_color=theme.TEXT_MUTED,
                     anchor="w").pack(anchor="w")
        ctk.CTkFrame(parent, height=1, fg_color=theme.BORDER_DEFAULT, corner_radius=0).pack(
            fill="x", padx=12, pady=(12, 8))

        nav_items = [
            ("status",   "Status"),
            ("modes",    "Modo Ativo"),
            ("general",  "Geral"),
            ("advanced", "Avançado"),
            ("about",    "Sobre"),
        ]
        for section_id, label in nav_items:
            # Row wrapper so indicator bar + button sit side-by-side
            row = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
            row.pack(fill="x", padx=8, pady=2)

            # Vertical accent bar (3px wide, hidden by default)
            bar = ctk.CTkFrame(row, width=3, height=theme.BTN_HEIGHT,
                               corner_radius=2, fg_color="transparent")
            bar.pack(side="left", fill="y")
            bar.pack_propagate(False)
            self._indicator_bars[section_id] = bar

            btn = ctk.CTkButton(
                row, text=label, anchor="w",
                height=theme.BTN_HEIGHT, corner_radius=theme.CORNER_MD,
                fg_color="transparent", hover_color=theme.BG_ELEVATED,
                font=theme.FONT_BODY(), text_color=theme.TEXT_MUTED,
                command=lambda sid=section_id: self._switch_section(sid))
            btn.pack(side="left", fill="x", expand=True)
            btn.bind("<Enter>",
                lambda e, b=btn, sid=section_id: self._on_nav_hover(b, sid, True))
            btn.bind("<Leave>",
                lambda e, b=btn, sid=section_id: self._on_nav_hover(b, sid, False))
            self._section_btns[section_id] = btn

    def _on_nav_hover(self, btn, section_id: str, entering: bool):
        if section_id == self._current_section:
            return
        btn.configure(text_color=theme.TEXT_SECONDARY if entering else theme.TEXT_MUTED)

    def _switch_section(self, section_id: str):
        for f in self._section_frames.values():
            f.pack_forget()
        for sid, btn in self._section_btns.items():
            if sid == section_id:
                btn.configure(fg_color=theme.BG_NIGHT, text_color=theme.TEXT_PRIMARY)
            else:
                btn.configure(fg_color="transparent", text_color=theme.TEXT_MUTED)
        for sid, bar in self._indicator_bars.items():
            bar.configure(fg_color=theme.PURPLE if sid == section_id else "transparent")
        self._current_section = section_id
        if section_id in self._section_frames:
            self._section_frames[section_id].pack(fill="both", expand=True)

    # ── Helper ─────────────────────────────────────────────────────────────

    def _get_mode_display_name(self, mode_id: str) -> str:
        names = {
            "transcribe":       "Transcrever",
            "email":            "Email",
            "simple":           "Prompt Simples",
            "prompt":           "Prompt COSTAR",
            "query":            "Perguntar ao Gemini",
            "clipboard_context": "Contexto do Clipboard",
            "bullet":           "Bullet Points",
            "translate":        "Traduzir",
        }
        return names.get(mode_id, mode_id)

    # ── Section builders ───────────────────────────────────────────────────

    def _build_section_status(self):
        f = ctk.CTkScrollableFrame(
            self._content_area, fg_color="transparent",
            scrollbar_button_color=theme.BORDER_HOVER,
            scrollbar_button_hover_color=theme.BORDER_ACTIVE)
        self._section_frames["status"] = f

        # ── Resumo Rápido (acima do status card) ──────────────────────────
        summary_card = ctk.CTkFrame(
            f, fg_color=theme.BG_DEEP, corner_radius=theme.CORNER_LG,
            border_width=1, border_color=theme.BORDER_DEFAULT)
        summary_card.pack(fill="x", padx=20, pady=(16, 8))

        ctk.CTkLabel(
            summary_card, text="RESUMO RÁPIDO",
            font=theme.FONT_OVERLINE(), text_color=theme.TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(12, 8))

        # Row: Modo ativo
        mode_row = ctk.CTkFrame(summary_card, fg_color="transparent")
        mode_row.pack(fill="x", padx=16, pady=(0, 6))
        ctk.CTkLabel(
            mode_row, text="Modo ativo", width=100,
            font=theme.FONT_CAPTION(), text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(side="left")
        mode_badge_frame = ctk.CTkFrame(
            mode_row, fg_color=theme.BG_NIGHT, corner_radius=theme.CORNER_SM,
            border_width=1, border_color=theme.BORDER_ACTIVE)
        mode_badge_frame.pack(side="left")
        ctk.CTkLabel(
            mode_badge_frame,
            text=self._get_mode_display_name(state.selected_mode),
            font=theme.FONT_BODY_BOLD(), text_color=theme.TEXT_PRIMARY,
        ).pack(padx=8, pady=3)

        # Row: Whisper
        whisper_row = ctk.CTkFrame(summary_card, fg_color="transparent")
        whisper_row.pack(fill="x", padx=16, pady=(0, 6))
        ctk.CTkLabel(
            whisper_row, text="Whisper", width=100,
            font=theme.FONT_CAPTION(), text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(side="left")
        whisper_model = state._CONFIG.get("WHISPER_MODEL", "small")
        fast_model = state._CONFIG.get("WHISPER_MODEL_FAST", "tiny")
        speed_label = "Rápido" if whisper_model == fast_model else "Qualidade"
        ctk.CTkLabel(
            whisper_row, text=f"{whisper_model} ({speed_label})",
            font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY,
        ).pack(side="left")

        # Row: Hotkey
        hotkey_row = ctk.CTkFrame(summary_card, fg_color="transparent")
        hotkey_row.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(
            hotkey_row, text="Hotkey", width=100,
            font=theme.FONT_CAPTION(), text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(side="left")
        hotkey_val = state._CONFIG.get("RECORD_HOTKEY", "ctrl+shift+space").title()
        hk_badge = ctk.CTkFrame(
            hotkey_row, fg_color=theme.BG_ELEVATED, corner_radius=theme.CORNER_SM,
            border_width=1, border_color=theme.BORDER_ACTIVE)
        hk_badge.pack(side="left")
        ctk.CTkLabel(
            hk_badge, text=hotkey_val,
            font=theme.FONT_MONO_SM(), text_color=theme.TEXT_PRIMARY,
        ).pack(padx=8, pady=3)

        # ── Status card (existente) ────────────────────────────────────────
        card = ctk.CTkFrame(f, fg_color=theme.BG_DEEP, corner_radius=theme.CORNER_LG,
                            border_width=1, border_color=theme.BORDER_DEFAULT)
        card.pack(fill="x", padx=20, pady=(0, 8))

        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", padx=20, pady=(16, 4))
        self._dot = ctk.CTkLabel(row1, text="●", font=theme.FONT_HEADING(), text_color=theme.SUCCESS)
        self._dot.pack(side="left")
        self._state_label = ctk.CTkLabel(
            row1, text="IDLE", font=theme.FONT_HEADING(), text_color=theme.TEXT_PRIMARY)
        self._state_label.pack(side="left", padx=(10, 0))

        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=20, pady=(0, 16))
        model_name = state._CONFIG.get("WHISPER_MODEL", "small")
        gemini_ok = bool(state._GEMINI_API_KEY)
        ctk.CTkLabel(row2, text=f"Whisper: {model_name}",
                     font=theme.FONT_CAPTION(), text_color=theme.TEXT_MUTED).pack(side="left")
        ctk.CTkLabel(row2, text="  |  ", font=theme.FONT_CAPTION(),
                     text_color=theme.BORDER_DEFAULT).pack(side="left")
        ctk.CTkLabel(row2, text=f"Gemini: {'on' if gemini_ok else 'off'}",
                     font=theme.FONT_CAPTION(),
                     text_color=theme.SUCCESS if gemini_ok else theme.TEXT_MUTED).pack(side="left")

    def _build_section_modes(self):
        f = ctk.CTkScrollableFrame(
            self._content_area, fg_color="transparent",
            scrollbar_button_color=theme.BORDER_HOVER,
            scrollbar_button_hover_color=theme.BORDER_ACTIVE)
        self._section_frames["modes"] = f

        # Header
        hdr = ctk.CTkFrame(f, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(16, 8))
        ctk.CTkLabel(hdr, text="MODO ATIVO",
                     font=theme.FONT_OVERLINE(), text_color=theme.TEXT_DISABLED).pack(anchor="w")
        ctk.CTkLabel(hdr, text="Clique para selecionar",
                     font=theme.FONT_CAPTION(), text_color=theme.TEXT_MUTED).pack(anchor="w")

        # Grid 3x3
        grid = ctk.CTkFrame(f, fg_color="transparent")
        grid.pack(fill="x", padx=20, pady=(0, 8))
        for i in range(3):
            grid.columnconfigure(i, weight=1)

        self._mode_card_refs = {}
        for idx, (mode_id, label, desc) in enumerate(self.MODES_GRID):
            row_idx, col_idx = divmod(idx, 3)
            is_active = (state.selected_mode == mode_id)
            card = ctk.CTkFrame(
                grid,
                fg_color=theme.BG_NIGHT if is_active else theme.BG_DEEP,
                corner_radius=theme.CORNER_MD,
                border_width=2 if is_active else 1,
                border_color=theme.BORDER_ACTIVE if is_active else theme.BORDER_DEFAULT,
                cursor="hand2",
            )
            card.grid(row=row_idx, column=col_idx, padx=3, pady=3, sticky="nsew")
            ctk.CTkLabel(card, text=label, font=theme.FONT_BODY_BOLD(),
                         text_color=theme.TEXT_PRIMARY).pack(pady=(0, 2))
            ctk.CTkLabel(card, text=desc, font=theme.FONT_CAPTION(),
                         text_color=theme.TEXT_MUTED, wraplength=110,
                         justify="center").pack(pady=(0, 12))
            # Bind click on card and all children
            for w in [card] + list(card.winfo_children()):
                w.bind("<Button-1>", lambda e, m=mode_id: self._select_mode(m))
            card.bind("<Enter>", lambda e, c=card, m=mode_id: self._on_mode_card_hover(c, m, True))
            card.bind("<Leave>", lambda e, c=card, m=mode_id: self._on_mode_card_hover(c, m, False))
            self._mode_card_refs[mode_id] = card

        # Card de hotkeys
        hk_card = ctk.CTkFrame(f, fg_color=theme.BG_DEEP, corner_radius=theme.CORNER_LG,
                                border_width=1, border_color=theme.BORDER_DEFAULT)
        hk_card.pack(fill="x", padx=20, pady=(8, 16))
        ctk.CTkLabel(hk_card, text="HOTKEYS",
                     font=theme.FONT_OVERLINE(), text_color=theme.TEXT_MUTED).pack(
            anchor="w", padx=16, pady=(12, 8))
        for key, desc in [
            (state._CONFIG.get("RECORD_HOTKEY", "ctrl+shift+space"), "Gravar"),
            (state._CONFIG.get("CYCLE_HOTKEY", "ctrl+shift+tab"), "Alternar modo"),
            (state._CONFIG.get("HISTORY_HOTKEY", "ctrl+shift+h"), "Buscar histórico"),
        ]:
            hk_row = ctk.CTkFrame(hk_card, fg_color="transparent")
            hk_row.pack(fill="x", padx=16, pady=(0, 6))
            badge_frame = ctk.CTkFrame(
                hk_row, fg_color=theme.BG_ELEVATED, corner_radius=theme.CORNER_SM,
                border_width=1, border_color=theme.BORDER_ACTIVE)
            badge_frame.pack(side="left", padx=(0, 8))
            ctk.CTkLabel(badge_frame, text=key.title(),
                         font=theme.FONT_MONO_SM(), text_color=theme.TEXT_PRIMARY).pack(padx=8, pady=3)
            ctk.CTkLabel(hk_row, text=desc,
                         font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY).pack(side="left")
        ctk.CTkFrame(hk_card, fg_color="transparent", height=4).pack()

    def _select_mode(self, mode: str) -> None:
        state.selected_mode = mode
        try:
            from voice.config import _save_env as _sv
            _sv({"SELECTED_MODE": mode})
        except Exception as e:
            print(f"[WARN] Falha ao salvar SELECTED_MODE: {e}")
        self._refresh_mode_cards()

    def _refresh_mode_cards(self) -> None:
        for m, card in self._mode_card_refs.items():
            is_active = (state.selected_mode == m)
            card.configure(
                fg_color=theme.BG_NIGHT if is_active else theme.BG_DEEP,
                border_width=2 if is_active else 1,
                border_color=theme.BORDER_ACTIVE if is_active else theme.BORDER_DEFAULT,
            )

    def _on_mode_card_hover(self, card, mode_id: str, entering: bool) -> None:
        is_active = (state.selected_mode == mode_id)
        if is_active:
            return
        if entering:
            card.configure(fg_color=theme.BG_ELEVATED, border_color=theme.BORDER_HOVER)
        else:
            card.configure(fg_color=theme.BG_DEEP, border_color=theme.BORDER_DEFAULT)

    # Alias mantido para compatibilidade interna (usado em _build_section_modes anterior)
    def _on_mode_hover(self, card, mode_id: str, entering: bool) -> None:
        self._on_mode_card_hover(card, mode_id, entering)

    def _build_hotkey_section(self, parent) -> None:
        """Seção de configuração do hotkey de gravação."""
        hkc = ctk.CTkFrame(parent, fg_color=theme.BG_DEEP, corner_radius=theme.CORNER_LG,
                            border_width=1, border_color=theme.BORDER_DEFAULT)
        hkc.pack(fill="x", padx=20, pady=(0, 8))
        ctk.CTkLabel(hkc, text="HOTKEY",
                     font=theme.FONT_OVERLINE(), text_color=theme.TEXT_MUTED).pack(
            anchor="w", padx=16, pady=(12, 4))
        ctk.CTkLabel(hkc, text="Hotkey de Gravação",
                     font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY).pack(
            anchor="w", padx=16, pady=(0, 2))
        self._hotkey_entry = ctk.CTkEntry(
            hkc, height=theme.INPUT_HEIGHT, font=theme.FONT_MONO(), fg_color=theme.BG_ABYSS,
            border_color=theme.BORDER_DEFAULT, border_width=1, text_color=theme.TEXT_PRIMARY,
            corner_radius=theme.CORNER_MD, placeholder_text="ctrl+shift+space")
        self._hotkey_entry.insert(0, state._CONFIG.get("RECORD_HOTKEY", "ctrl+shift+space"))
        self._hotkey_entry.pack(fill="x", padx=16, pady=(0, 12))

    def _build_model_section(self, parent) -> None:
        """Seção de configuração de modelo Whisper e idioma (dropdown completo — Avançado)."""
        mc = ctk.CTkFrame(parent, fg_color=theme.BG_DEEP, corner_radius=theme.CORNER_LG,
                          border_width=1, border_color=theme.BORDER_DEFAULT)
        mc.pack(fill="x", padx=20, pady=(0, 8))
        ctk.CTkLabel(mc, text="MODELO E IDIOMA",
                     font=theme.FONT_OVERLINE(), text_color=theme.TEXT_MUTED).pack(
            anchor="w", padx=16, pady=(12, 4))

        ctk.CTkLabel(mc, text="Modelo Whisper",
                     font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY).pack(
            anchor="w", padx=16, pady=(0, 2))
        # W-04: _model_var já inicializado em _build() — apenas ajustar valor se necessário
        cur_model = self._model_var.get()
        if cur_model not in self.MODELS:
            self._model_var.set("small")
        ctk.CTkOptionMenu(mc, variable=self._model_var, values=self.MODELS,
                          height=theme.INPUT_HEIGHT, corner_radius=theme.CORNER_MD,
                          fg_color=theme.BG_ABYSS, button_color=theme.PURPLE,
                          button_hover_color=theme.PURPLE_DARK,
                          text_color=theme.TEXT_PRIMARY).pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(mc, text="Idioma de transcrição",
                     font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY).pack(
            anchor="w", padx=16, pady=(0, 2))
        raw_lang = state._CONFIG.get("WHISPER_LANGUAGE", "") or "auto-detect"
        lang_val = raw_lang if raw_lang in self.LANGUAGES else "auto-detect"
        self._lang_var = ctk.StringVar(value=lang_val)
        ctk.CTkOptionMenu(mc, variable=self._lang_var, values=self.LANGUAGES,
                          height=theme.INPUT_HEIGHT, corner_radius=theme.CORNER_MD,
                          fg_color=theme.BG_ABYSS, button_color=theme.PURPLE,
                          button_hover_color=theme.PURPLE_DARK,
                          text_color=theme.TEXT_PRIMARY).pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(mc, text="Device Whisper",
                     font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY).pack(
            anchor="w", padx=16, pady=(0, 2))
        self._device_var = ctk.StringVar(value=state._CONFIG.get("WHISPER_DEVICE", "cpu"))
        ctk.CTkOptionMenu(mc, variable=self._device_var, values=["cpu", "cuda", "auto"],
                          height=theme.INPUT_HEIGHT, corner_radius=theme.CORNER_MD,
                          fg_color=theme.BG_ABYSS, button_color=theme.PURPLE,
                          button_hover_color=theme.PURPLE_DARK,
                          text_color=theme.TEXT_PRIMARY).pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(mc, text="Idioma de tradução (modo Traduzir)",
                     font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY).pack(
            anchor="w", padx=16, pady=(0, 2))
        self._translate_lang_var = ctk.StringVar(
            value=state._CONFIG.get("TRANSLATE_TARGET_LANG", "en"))
        ctk.CTkOptionMenu(mc, variable=self._translate_lang_var, values=["en", "pt"],
                          height=theme.INPUT_HEIGHT, corner_radius=theme.CORNER_MD,
                          fg_color=theme.BG_ABYSS, button_color=theme.PURPLE,
                          button_hover_color=theme.PURPLE_DARK,
                          text_color=theme.TEXT_PRIMARY).pack(fill="x", padx=16, pady=(0, 12))

    def _build_ai_provider_section(self, parent) -> None:
        """Seção de configuração do provedor de IA — orquestra sub-helpers."""
        ac = ctk.CTkFrame(parent, fg_color=theme.BG_DEEP, corner_radius=theme.CORNER_LG,
                          border_width=1, border_color=theme.BORDER_DEFAULT)
        ac.pack(fill="x", padx=20, pady=(0, 8))
        ctk.CTkLabel(ac, text="PROVEDOR DE IA",
                     font=theme.FONT_OVERLINE(), text_color=theme.TEXT_MUTED).pack(
            anchor="w", padx=16, pady=(12, 4))

        self._build_provider_selector(ac)
        self._build_openrouter_input(ac)

        # Separador — fallback Gemini
        ctk.CTkLabel(ac, text="Alternativa (usado se OpenRouter vazio)",
                     font=theme.FONT_CAPTION(), text_color=theme.TEXT_DISABLED).pack(
            anchor="w", padx=16, pady=(4, 4))

        self._build_gemini_input(ac)
        self._build_openai_input(ac)
        ctk.CTkFrame(ac, height=4, fg_color="transparent").pack()

    def _build_provider_selector(self, parent) -> None:
        """Radio/dropdown para escolher provedor (gemini / openai)."""
        ctk.CTkLabel(parent, text="Provedor",
                     font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY).pack(
            anchor="w", padx=16, pady=(0, 2))
        self._provider_var = ctk.StringVar(value=state._CONFIG.get("AI_PROVIDER", "gemini"))
        ctk.CTkOptionMenu(parent, variable=self._provider_var, values=["gemini", "openai"],
                          height=theme.INPUT_HEIGHT, corner_radius=theme.CORNER_MD,
                          fg_color=theme.BG_ABYSS, button_color=theme.PURPLE,
                          button_hover_color=theme.PURPLE_DARK,
                          text_color=theme.TEXT_PRIMARY,
                          command=lambda _: self._update_openai_visibility(parent)).pack(
            fill="x", padx=16, pady=(0, 8))

    def _build_openrouter_input(self, parent) -> None:
        """Input de API Key para OpenRouter (provedor primário recomendado)."""
        ctk.CTkLabel(parent, text="OpenRouter API Key (Recomendado)",
                     font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY).pack(
            anchor="w", padx=16, pady=(0, 2))
        ctk.CTkLabel(parent,
                     text="Gateway unico. Modos rapidos usam Llama 4 Scout, complexos usam Gemini 2.5 Flash",
                     font=theme.FONT_CAPTION(), text_color=theme.TEXT_MUTED).pack(
            anchor="w", padx=16, pady=(0, 4))
        or_row = ctk.CTkFrame(parent, fg_color="transparent")
        or_row.pack(fill="x", padx=16, pady=(0, 4))
        self._openrouter_key_entry = ctk.CTkEntry(
            or_row, height=theme.INPUT_HEIGHT, show="*",
            font=theme.FONT_MONO(), fg_color=theme.BG_ABYSS,
            border_color=theme.BORDER_DEFAULT, border_width=1, text_color=theme.TEXT_PRIMARY,
            corner_radius=theme.CORNER_MD, placeholder_text="sk-or-...")
        self._openrouter_key_entry.pack(side="left", fill="x", expand=True)
        self._openrouter_key_entry.bind("<FocusIn>",
            lambda e: self._openrouter_key_entry.configure(border_color=theme.BORDER_ACTIVE))
        self._openrouter_key_entry.bind("<FocusOut>",
            lambda e: self._openrouter_key_entry.configure(border_color=theme.BORDER_DEFAULT))
        if state._CONFIG.get("OPENROUTER_API_KEY"):
            self._openrouter_key_entry.insert(0, state._CONFIG.get("OPENROUTER_API_KEY"))
        ctk.CTkButton(
            or_row, text="***", width=theme.INPUT_HEIGHT, height=theme.INPUT_HEIGHT,
            fg_color=theme.BG_ABYSS, hover_color=theme.BG_NIGHT,
            border_color=theme.BORDER_DEFAULT, border_width=1, corner_radius=theme.CORNER_MD,
            command=self._toggle_openrouter_key_visibility).pack(side="left", padx=(6, 0))
        ctk.CTkLabel(parent, text="Obter em openrouter.ai/keys",
                     font=theme.FONT_CAPTION(), text_color=theme.BORDER_HOVER).pack(
            anchor="w", padx=16, pady=(0, 8))

    def _build_gemini_input(self, parent) -> None:
        """Input de API Key para Gemini (fallback direto)."""
        ctk.CTkLabel(parent, text="Gemini API Key",
                     font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY).pack(
            anchor="w", padx=16, pady=(0, 2))
        key_row = ctk.CTkFrame(parent, fg_color="transparent")
        key_row.pack(fill="x", padx=16, pady=(0, 8))
        self._api_entry = ctk.CTkEntry(
            key_row, height=theme.INPUT_HEIGHT, show="*",
            font=theme.FONT_MONO(), fg_color=theme.BG_ABYSS,
            border_color=theme.BORDER_DEFAULT, border_width=1, text_color=theme.TEXT_PRIMARY,
            corner_radius=theme.CORNER_MD, placeholder_text="AIza...")
        self._api_entry.pack(side="left", fill="x", expand=True)
        self._api_entry.bind("<FocusIn>",
            lambda e: self._api_entry.configure(border_color=theme.BORDER_ACTIVE))
        self._api_entry.bind("<FocusOut>",
            lambda e: self._api_entry.configure(border_color=theme.BORDER_DEFAULT))
        if state._GEMINI_API_KEY:
            self._api_entry.insert(0, state._GEMINI_API_KEY)
        self._eye_btn = ctk.CTkButton(
            key_row, text="***", width=theme.INPUT_HEIGHT, height=theme.INPUT_HEIGHT,
            fg_color=theme.BG_ABYSS, hover_color=theme.BG_NIGHT,
            border_color=theme.BORDER_DEFAULT, border_width=1, corner_radius=theme.CORNER_MD,
            command=self._toggle_key_visibility)
        self._eye_btn.pack(side="left", padx=(6, 0))

    def _build_openai_input(self, parent) -> None:
        """Input de API Key para OpenAI (visibilidade controlada pelo provider selector)."""
        self._openai_key_frame = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkLabel(self._openai_key_frame, text="OpenAI API Key",
                     font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY).pack(
            anchor="w", pady=(0, 2))
        oai_row = ctk.CTkFrame(self._openai_key_frame, fg_color="transparent")
        oai_row.pack(fill="x", pady=(0, 4))
        self._openai_key_entry = ctk.CTkEntry(
            oai_row, height=theme.INPUT_HEIGHT, show="*",
            font=theme.FONT_MONO(), fg_color=theme.BG_ABYSS,
            border_color=theme.BORDER_DEFAULT, border_width=1, text_color=theme.TEXT_PRIMARY,
            corner_radius=theme.CORNER_MD, placeholder_text="sk-...")
        self._openai_key_entry.pack(side="left", fill="x", expand=True)
        if state._CONFIG.get("OPENAI_API_KEY"):
            self._openai_key_entry.insert(0, state._CONFIG.get("OPENAI_API_KEY"))
        self._openai_eye_btn = ctk.CTkButton(
            oai_row, text="***", width=theme.INPUT_HEIGHT, height=theme.INPUT_HEIGHT,
            fg_color=theme.BG_ABYSS, hover_color=theme.BG_NIGHT,
            border_color=theme.BORDER_DEFAULT, border_width=1, corner_radius=theme.CORNER_MD,
            command=self._toggle_openai_key_visibility)
        self._openai_eye_btn.pack(side="left", padx=(6, 0))
        self._update_openai_visibility(parent)

    def _build_license_section(self, parent) -> None:
        """Seção de configuração da chave de licença."""
        kc = ctk.CTkFrame(parent, fg_color=theme.BG_DEEP, corner_radius=theme.CORNER_LG,
                          border_width=1, border_color=theme.BORDER_DEFAULT)
        kc.pack(fill="x", padx=20, pady=(0, 8))
        ctk.CTkLabel(kc, text="LICENÇA",
                     font=theme.FONT_OVERLINE(), text_color=theme.TEXT_MUTED).pack(
            anchor="w", padx=16, pady=(12, 4))

        ctk.CTkLabel(kc, text="Chave de Licença",
                     font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY).pack(
            anchor="w", padx=16, pady=(0, 2))
        lic_row = ctk.CTkFrame(kc, fg_color="transparent")
        lic_row.pack(fill="x", padx=16, pady=(0, 4))
        self._license_entry = ctk.CTkEntry(
            lic_row, height=theme.INPUT_HEIGHT, font=theme.FONT_MONO_SM(), fg_color=theme.BG_ABYSS,
            border_color=theme.BORDER_DEFAULT, border_width=1, text_color=theme.TEXT_PRIMARY,
            corner_radius=theme.CORNER_MD, placeholder_text="vc-xxxxxxxxxxxx-xxxxxxxxxxxx")
        self._license_entry.pack(side="left", fill="x", expand=True)
        self._license_entry.bind("<FocusIn>",
            lambda e: self._license_entry.configure(border_color=theme.BORDER_ACTIVE))
        self._license_entry.bind("<FocusOut>",
            lambda e: self._license_entry.configure(border_color=theme.BORDER_DEFAULT))
        ctk.CTkButton(lic_row, text="✓", width=theme.INPUT_HEIGHT, height=theme.INPUT_HEIGHT,
                      fg_color=theme.BG_ABYSS, hover_color=theme.BG_NIGHT,
                      border_color=theme.BORDER_DEFAULT, border_width=1, corner_radius=theme.CORNER_MD,
                      command=self._check_license).pack(side="left", padx=(6, 0))
        cur_lic = state._CONFIG.get("LICENSE_KEY") or ""
        if cur_lic:
            self._license_entry.insert(0, cur_lic)
        self._license_status_label = ctk.CTkLabel(
            kc, text="", font=theme.FONT_CAPTION(), text_color=theme.TEXT_MUTED)
        self._license_status_label.pack(anchor="w", padx=16, pady=(0, 12))
        self._refresh_license_status()

    def _build_sounds_section(self, parent) -> None:
        """Seção de sons customizados."""
        sc = ctk.CTkFrame(parent, fg_color=theme.BG_DEEP, corner_radius=theme.CORNER_LG,
                          border_width=1, border_color=theme.BORDER_DEFAULT)
        sc.pack(fill="x", padx=20, pady=(0, 16))
        ctk.CTkLabel(sc, text="SONS CUSTOMIZADOS",
                     font=theme.FONT_OVERLINE(), text_color=theme.TEXT_MUTED).pack(
            anchor="w", padx=16, pady=(12, 2))
        ctk.CTkLabel(sc, text="Vazio = beep padrão. Selecione arquivo .wav",
                     font=theme.FONT_CAPTION(), text_color=theme.TEXT_DISABLED).pack(
            anchor="w", padx=16, pady=(0, 8))
        _SOUND_EVENTS = [
            ("SOUND_START",   "Iniciar gravação"),
            ("SOUND_SUCCESS", "Sucesso"),
            ("SOUND_ERROR",   "Erro"),
            ("SOUND_WARNING", "Aviso"),
            ("SOUND_SKIP",    "Skip"),
        ]
        self._sound_entries = {}
        for key, label in _SOUND_EVENTS:
            ctk.CTkLabel(sc, text=label, font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY).pack(
                anchor="w", padx=16, pady=(0, 2))
            snd_row = ctk.CTkFrame(sc, fg_color="transparent")
            snd_row.pack(fill="x", padx=16, pady=(0, 8))
            entry = ctk.CTkEntry(
                snd_row, height=theme.INPUT_HEIGHT, font=theme.FONT_CAPTION(), fg_color=theme.BG_ABYSS,
                border_color=theme.BORDER_DEFAULT, border_width=1, text_color=theme.TEXT_PRIMARY,
                corner_radius=theme.CORNER_MD, placeholder_text="caminho/para/arquivo.wav")
            entry.pack(side="left", fill="x", expand=True)
            cur_val = state._CONFIG.get(key, "")
            if cur_val:
                entry.insert(0, cur_val)
            ctk.CTkButton(
                snd_row, text="...", width=theme.INPUT_HEIGHT, height=theme.INPUT_HEIGHT,
                fg_color=theme.BG_ABYSS, hover_color=theme.BG_NIGHT,
                border_color=theme.BORDER_DEFAULT, border_width=1, corner_radius=theme.CORNER_MD,
                font=theme.FONT_BODY(),
                command=lambda e=entry: self._pick_sound_file(e),
            ).pack(side="left", padx=(4, 0))
            self._sound_entries[key] = entry
        ctk.CTkFrame(sc, height=4, fg_color="transparent").pack()

    def _build_section_general(self):
        """Seção Geral: Whisper SegmentedButton + Provedor IA + Licença."""
        f = ctk.CTkScrollableFrame(
            self._content_area, fg_color="transparent",
            scrollbar_button_color=theme.BORDER_HOVER,
            scrollbar_button_hover_color=theme.BORDER_ACTIVE)
        self._section_frames["general"] = f

        # ── Whisper card com SegmentedButton ──────────────────────────────
        whisper_card = ctk.CTkFrame(f, fg_color=theme.BG_DEEP, corner_radius=theme.CORNER_LG,
                                    border_width=1, border_color=theme.BORDER_DEFAULT)
        whisper_card.pack(fill="x", padx=20, pady=(16, 8))
        ctk.CTkLabel(whisper_card, text="WHISPER",
                     font=theme.FONT_OVERLINE(), text_color=theme.TEXT_MUTED).pack(
            anchor="w", padx=16, pady=(12, 4))
        ctk.CTkLabel(whisper_card, text="Velocidade de transcrição",
                     font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY).pack(
            anchor="w", padx=16, pady=(0, 8))

        fast_model = state._CONFIG.get("WHISPER_MODEL_FAST", "tiny")
        quality_model = state._CONFIG.get("WHISPER_MODEL_QUALITY", "small")
        cur_model = state._CONFIG.get("WHISPER_MODEL", "tiny")
        initial_speed = "Qualidade" if cur_model == quality_model else "Rápido"

        self._speed_var = ctk.StringVar(value=initial_speed)
        speed_seg = ctk.CTkSegmentedButton(
            whisper_card,
            values=["Rápido", "Qualidade"],
            variable=self._speed_var,
            fg_color=theme.BG_ABYSS,
            selected_color=theme.PURPLE,
            selected_hover_color=theme.PURPLE_HOVER,
            unselected_color=theme.BG_DEEP,
            unselected_hover_color=theme.BG_ELEVATED,
            text_color=theme.TEXT_PRIMARY,
            corner_radius=theme.CORNER_MD,
            height=36,
            font=theme.FONT_BODY_BOLD(),
            command=self._on_speed_change,
        )
        speed_seg.pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(
            whisper_card,
            text=f"Rápido = {fast_model} | Qualidade = {quality_model}",
            font=theme.FONT_CAPTION(), text_color=theme.TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 12))

        # ── Provedor IA ───────────────────────────────────────────────────
        self._build_ai_provider_section(f)

        # ── Licença ───────────────────────────────────────────────────────
        self._build_license_section(f)

    def _on_speed_change(self, value: str) -> None:
        """Atualiza _model_var (dropdown completo em Avançado) ao mudar velocidade."""
        fast_model = state._CONFIG.get("WHISPER_MODEL_FAST", "tiny")
        quality_model = state._CONFIG.get("WHISPER_MODEL_QUALITY", "small")
        if value == "Rápido":
            model = fast_model
        else:
            model = quality_model
        self._model_var.set(model)

    def _build_section_advanced(self):
        """Seção Avançado: hotkey + modelo completo + wakeword + sons."""
        f = ctk.CTkScrollableFrame(
            self._content_area, fg_color="transparent",
            scrollbar_button_color=theme.BORDER_HOVER,
            scrollbar_button_hover_color=theme.BORDER_ACTIVE)
        self._section_frames["advanced"] = f

        self._build_hotkey_section(f)
        self._build_model_section(f)
        self._build_sounds_section(f)

    def _build_section_about(self):
        f = ctk.CTkFrame(self._content_area, fg_color="transparent", corner_radius=0)
        self._section_frames["about"] = f
        ctk.CTkFrame(f, height=24, fg_color="transparent").pack()
        ctk.CTkLabel(f, text=f"Voice Commander v{__version__}",
                     font=theme.FONT_HEADING(), text_color=theme.TEXT_PRIMARY).pack()
        ctk.CTkLabel(f, text="JP Labs Creative Studio",
                     font=theme.FONT_BODY(), text_color=theme.TEXT_MUTED).pack(pady=(4, 0))
        ctk.CTkFrame(f, height=16, fg_color="transparent").pack()
        ctk.CTkLabel(f, text="voice.jplabs.ai",
                     font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY).pack()

    @staticmethod
    def _bind_press_feedback(button, normal_color: str, pressed_color: str) -> None:
        """Adds press/release visual feedback to a CTkButton."""
        button.bind("<ButtonPress-1>",   lambda e: button.configure(fg_color=pressed_color))
        button.bind("<ButtonRelease-1>", lambda e: button.configure(fg_color=normal_color))

    def _build_footer(self, parent):
        foot = ctk.CTkFrame(parent, fg_color=theme.BG_ABYSS, height=64, corner_radius=0)
        foot.pack(fill="x")
        foot.pack_propagate(False)
        btn_row = ctk.CTkFrame(foot, fg_color="transparent")
        btn_row.pack(side="right", padx=16, pady=12)
        ctk.CTkButton(btn_row, text="Fechar", width=100, height=theme.BTN_HEIGHT,
                      corner_radius=theme.CORNER_MD, fg_color="transparent",
                      border_color=theme.BORDER_DEFAULT, border_width=1,
                      hover_color=theme.BG_NIGHT, font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY,
                      command=self._root.destroy).pack(side="left", padx=(0, 8))
        self._save_btn = ctk.CTkButton(
            btn_row, text="Salvar", width=100, height=theme.BTN_HEIGHT,
            corner_radius=theme.CORNER_MD, fg_color=theme.PURPLE, hover_color=theme.PURPLE_HOVER,
            font=theme.FONT_BODY_BOLD(), text_color=theme.TEXT_PRIMARY,
            command=self._save)
        self._save_btn.pack(side="left")
        self._bind_press_feedback(self._save_btn, theme.PURPLE, theme.PURPLE_DARK)

    def _update_openai_visibility(self, parent=None) -> None:
        """Mostra/oculta campo OpenAI Key baseado no provider selecionado."""
        if self._openai_key_frame is None:
            return
        if self._provider_var and self._provider_var.get() == "openai":
            self._openai_key_frame.pack(fill="x", padx=16, before=None)
        else:
            self._openai_key_frame.pack_forget()

    def _pick_sound_file(self, entry) -> None:
        """Abre file picker para selecionar .wav customizado."""
        try:
            import tkinter.filedialog as fd
            path = fd.askopenfilename(
                title="Selecionar arquivo de som",
                filetypes=[("WAV files", "*.wav"), ("All files", "*.*")],
            )
            if path:
                entry.delete(0, "end")
                entry.insert(0, path)
        except Exception as e:
            print(f"[WARN] File picker error: {e}")

    # ── Callbacks ─────────────────────────────────────────────────────────

    def _toggle_key_visibility(self):
        self._show_key = not self._show_key
        self._api_entry.configure(show="" if self._show_key else "*")

    def _toggle_openai_key_visibility(self):
        self._show_openai_key = not self._show_openai_key
        if self._openai_key_entry:
            self._openai_key_entry.configure(show="" if self._show_openai_key else "*")

    def _toggle_openrouter_key_visibility(self):
        self._show_openrouter_key = not self._show_openrouter_key
        if self._openrouter_key_entry:
            self._openrouter_key_entry.configure(show="" if self._show_openrouter_key else "*")

    def _check_license(self):
        key = self._license_entry.get().strip() if self._license_entry else ""
        self._show_license_result(key)

    def _refresh_license_status(self):
        key = state._CONFIG.get("LICENSE_KEY") or ""
        self._show_license_result(key)

    def _show_license_result(self, key: str):
        if not self._license_status_label:
            return
        if not key:
            self._license_status_label.configure(text="Não configurada", text_color=theme.TEXT_MUTED)
            return
        valid, msg = validate_license_key(key)
        if valid:
            self._license_status_label.configure(text=f"✓ {msg}", text_color="#22C55E")
        else:
            expired = "Expirada" in msg
            color = "#FF6B35" if expired else "#FF3366"
            suffix = "  Renovar → voice.jplabs.ai" if expired else ""
            self._license_status_label.configure(text=f"✗ {msg}{suffix}", text_color=color)

    def _on_save_success(self):
        """Feedback visual: botão Salvar fica verde por 1.5s."""
        self._save_btn.configure(
            fg_color=theme.SUCCESS, hover_color="#00CC6E",
            text_color=theme.BG_ABYSS, text="Salvo ✓")
        self._root.after(1500, self._reset_save_btn)

    def _reset_save_btn(self):
        self._save_btn.configure(
            fg_color=theme.PURPLE, hover_color=theme.PURPLE_HOVER,
            text_color=theme.TEXT_PRIMARY, text="Salvar")

    def _save(self):
        model_val = self._model_var.get() if self._model_var else "small"
        lang_val = self._lang_var.get() if self._lang_var else "auto-detect"
        api_key = self._api_entry.get().strip() if self._api_entry else ""
        license_key = self._license_entry.get().strip() if self._license_entry else ""
        new_values: dict = {
            "WHISPER_MODEL": model_val,
            "WHISPER_LANGUAGE": "" if lang_val == "auto-detect" else lang_val,
        }
        if api_key:
            new_values["GEMINI_API_KEY"] = api_key
        if license_key:
            new_values["LICENSE_KEY"] = license_key
        # New fields
        if self._hotkey_entry:
            hk = self._hotkey_entry.get().strip()
            if hk:
                new_values["RECORD_HOTKEY"] = hk
        if self._provider_var:
            new_values["AI_PROVIDER"] = self._provider_var.get()
        if self._openai_key_entry:
            oai_key = self._openai_key_entry.get().strip()
            if oai_key:
                new_values["OPENAI_API_KEY"] = oai_key
        if self._openrouter_key_entry:
            or_key = self._openrouter_key_entry.get().strip()
            if or_key:
                new_values["OPENROUTER_API_KEY"] = or_key
        if self._device_var:
            new_values["WHISPER_DEVICE"] = self._device_var.get()
        if self._translate_lang_var:
            new_values["TRANSLATE_TARGET_LANG"] = self._translate_lang_var.get()
        for key, entry in self._sound_entries.items():
            new_values[key] = entry.get().strip()
        new_values["SELECTED_MODE"] = state.selected_mode
        _save_env(new_values)
        _reload_config()
        self._refresh_license_status()
        if self._mode_card_refs:
            self._refresh_mode_cards()
        self._on_save_success()

    def _refresh_status(self):
        if self._root is None:
            return
        try:
            state_map = {
                "idle":       ("●", theme.SUCCESS,  "IDLE"),
                "recording":  ("●", theme.ERROR,    "GRAVANDO"),
                "processing": ("●", theme.WARNING,  "PROCESSANDO"),
            }
            dot_text, dot_color, state_text = state_map.get(
                state._tray_state, ("●", theme.TEXT_MUTED, state._tray_state.upper()))
            self._dot.configure(text=dot_text, text_color=dot_color)
            self._state_label.configure(text=state_text)
            self._root.after(1000, self._refresh_status)
        except Exception:
            pass
