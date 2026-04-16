# voice/ui_onboarding.py — OnboardingWindow
# Extraído de voice/ui.py (refactor: split god-module)

import ctypes
import sys
import threading

from voice import state
from voice import theme
from voice.paths import _resource_path
from voice.config import validate_license_key, _test_gemini_key
from voice.config import _save_env
from voice.ui_helpers import _apply_taskbar_icon

# Tentar importar customtkinter — fallback silencioso
try:
    import customtkinter as ctk
    state._ctk_available = True
except ImportError:
    pass  # Silencioso — ui.py já exibiu o aviso


# ─────────────────────────────────────────────────────────────────────────────
# OnboardingWindow — Multi-Step Wizard (Linear/Arc DNA)
# ─────────────────────────────────────────────────────────────────────────────

class OnboardingWindow:
    """Wizard de configuração inicial — 5 steps."""

    MODES = [
        ("transcribe", "Transcrever",    "Voz → texto corrigido"),
        ("simple",     "Prompt Simples", "Injeta contexto"),
        ("prompt",     "Prompt COSTAR",  "Formato estruturado XML"),
        ("query",      "Query AI",       "Pergunta direta à IA"),
        ("bullet",     "Bullet Dump",    "Voz → bullets hierárquicos"),
        ("email",      "Email Draft",    "Voz → email profissional"),
        ("translate",  "Traduzir",       "Traduz para EN/PT"),
    ]

    def __init__(self, done_callback=None):
        self._root = None
        self._license_entry = None
        self._license_status = None
        self._gemini_entry = None
        self._gemini_status = None
        self._start_btn = None   # kept for compat (unused in new layout)
        self._license_ok = False
        self._gemini_ok = False
        self._done_callback = done_callback
        # Wizard state
        self._current_step = 1
        self._step_frames = []
        self._dot_frames = []
        self._next_btn = None
        self._prev_btn = None
        self._content_area = None
        self._step_title_lbl = None
        self._step_subtitle_lbl = None

    def run(self) -> None:
        """Abre wizard bloqueante. Retorna quando usuário completa os 5 passos."""
        if not state._ctk_available:
            ctypes.windll.user32.MessageBoxW(
                0,
                "Licença inválida ou não configurada.\n"
                "Configure LICENSE_KEY no arquivo .env\n"
                "ou acesse voice.jplabs.ai para obter uma licença.",
                "Voice Commander — Licença",
                0x30,
            )
            return
        self._build()
        self._root.mainloop()

    def _build(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self._root = ctk.CTk()
        self._root.title("Voice Commander — Configuração Inicial")
        self._root.resizable(False, False)
        self._root.configure(fg_color=theme.BG_ABYSS)
        self._root.attributes("-topmost", True)
        _icon = _resource_path("icon.ico")
        if _icon.exists():
            self._root.iconbitmap(str(_icon))
            _apply_taskbar_icon(self._root, _icon)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Center on screen — fixed 480×600
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        w, h = 480, 600
        x = (sw - w) // 2
        y = (sh - h) // 2
        self._root.geometry(f"{w}x{h}+{x}+{y}")

        # ── Header ──────────────────────────────────────────────────────────
        header = ctk.CTkFrame(self._root, fg_color=theme.BG_DEEP, corner_radius=0)
        header.pack(fill="x")
        hcol = ctk.CTkFrame(header, fg_color="transparent")
        hcol.pack(fill="both", expand=True, padx=24, pady=16)
        self._step_title_lbl = ctk.CTkLabel(
            hcol, text="", anchor="w",
            font=theme.FONT_HEADING(), text_color=theme.TEXT_PRIMARY)
        self._step_title_lbl.pack(anchor="w")
        self._step_subtitle_lbl = ctk.CTkLabel(
            hcol, text="", anchor="w",
            font=theme.FONT_CAPTION(), text_color=theme.TEXT_MUTED)
        self._step_subtitle_lbl.pack(anchor="w")

        # ── Progress dots ────────────────────────────────────────────────────
        dots_outer = ctk.CTkFrame(self._root, fg_color=theme.BG_ABYSS, height=28)
        dots_outer.pack(fill="x", padx=24, pady=(10, 0))
        dots_outer.pack_propagate(False)
        dots_inner = ctk.CTkFrame(dots_outer, fg_color="transparent")
        dots_inner.pack(anchor="w", pady=8)
        self._dot_frames = []
        for i in range(5):
            dot = ctk.CTkFrame(dots_inner, width=12, height=12, corner_radius=6,
                               fg_color=theme.BORDER_HOVER)
            dot.pack(side="left")
            dot.pack_propagate(False)
            self._dot_frames.append(dot)
            if i < 4:
                ctk.CTkFrame(dots_inner, width=20, height=2, fg_color=theme.BORDER_DEFAULT,
                             corner_radius=0).pack(side="left", padx=3)

        # ── Separator ───────────────────────────────────────────────────────
        ctk.CTkFrame(self._root, height=1, fg_color=theme.BORDER_DEFAULT, corner_radius=0).pack(
            fill="x", pady=(8, 0))

        # ── Content area ─────────────────────────────────────────────────────
        self._content_area = ctk.CTkFrame(self._root, fg_color=theme.BG_ABYSS, corner_radius=0)
        self._content_area.pack(fill="both", expand=True)

        # Build all 5 step frames (hidden initially, parented to content_area)
        self._step_frames = []
        for builder in [
            self._build_step_1,
            self._build_step_2,
            self._build_step_3,
            self._build_step_4,
            self._build_step_5,
        ]:
            f = ctk.CTkFrame(self._content_area, fg_color="transparent", corner_radius=0)
            builder(f)
            self._step_frames.append(f)

        # ── Footer nav ───────────────────────────────────────────────────────
        ctk.CTkFrame(self._root, height=1, fg_color=theme.BORDER_DEFAULT, corner_radius=0).pack(fill="x")
        footer = ctk.CTkFrame(self._root, fg_color=theme.BG_ABYSS, height=64, corner_radius=0)
        footer.pack(fill="x")
        footer.pack_propagate(False)
        self._prev_btn = ctk.CTkButton(
            footer, text="Anterior", width=100, height=theme.BTN_HEIGHT,
            corner_radius=theme.CORNER_MD, fg_color="transparent",
            border_color=theme.BORDER_DEFAULT, border_width=1,
            hover_color=theme.BG_NIGHT, font=theme.FONT_BODY(), text_color=theme.TEXT_MUTED,
            command=self._go_prev)
        # prev_btn packed/unpacked by _go_to_step
        self._next_btn = ctk.CTkButton(
            footer, text="Próximo", width=120, height=theme.BTN_HEIGHT,
            corner_radius=theme.CORNER_MD, fg_color=theme.PURPLE, hover_color=theme.PURPLE_HOVER,
            font=theme.FONT_BODY_BOLD(), text_color=theme.TEXT_PRIMARY,
            command=self._go_next)
        self._next_btn.pack(side="right", padx=(0, 16), pady=12)

        # Show first step
        self._go_to_step(1)

    # ── Step builders ──────────────────────────────────────────────────────

    def _build_step_1(self, parent):
        """Step 1 — Bem-vindo — hero card + stat badges + hotkey preview."""
        # Hero card com borda PURPLE
        hero = ctk.CTkFrame(parent, fg_color=theme.BG_DEEP, corner_radius=theme.CORNER_LG,
                            border_width=2, border_color=theme.PURPLE)
        hero.pack(fill="x", pady=(8, 12))
        ctk.CTkLabel(hero, text="\U0001F399",
                     font=theme.FONT_DISPLAY(), text_color=theme.TEXT_PRIMARY).pack(pady=(20, 4))
        ctk.CTkLabel(hero, text="VOICE COMMANDER",
                     font=theme.FONT_DISPLAY(), text_color=theme.TEXT_PRIMARY).pack(pady=(0, 4))
        ctk.CTkLabel(hero, text="Sua voz. Seu texto. Sem fricção.",
                     font=theme.FONT_CAPTION(), text_color=theme.TEXT_SECONDARY).pack(pady=(0, 20))

        # Row de 3 stat badges
        badges_row = ctk.CTkFrame(parent, fg_color="transparent")
        badges_row.pack(fill="x", pady=(0, 10))
        for i, (label, value) in enumerate([
            ("7 Modos",     "Processar"),
            ("Whisper",     "Local"),
            ("Gemini AI",   "Rápido"),
        ]):
            badge = ctk.CTkFrame(badges_row, fg_color=theme.BG_DEEP, corner_radius=theme.CORNER_MD,
                                 border_width=1, border_color=theme.BORDER_DEFAULT)
            badge.pack(side="left", expand=True, fill="x", padx=(0 if i == 0 else 4, 0))
            ctk.CTkLabel(badge, text=label, font=theme.FONT_OVERLINE(),
                         text_color=theme.TEXT_PRIMARY).pack(pady=(8, 2))
            ctk.CTkLabel(badge, text=value, font=theme.FONT_CAPTION(),
                         text_color=theme.TEXT_MUTED).pack(pady=(0, 8))

        # Instrução
        ctk.CTkLabel(parent,
                     text="Levamos ~1 minuto para configurar. Vamos começar.",
                     font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY,
                     justify="center").pack(pady=(0, 8))

        # Card de hotkey preview
        hotkey = state._CONFIG.get("RECORD_HOTKEY", "ctrl+shift+space").title()
        hk_card = ctk.CTkFrame(parent, fg_color=theme.BG_DEEP, corner_radius=theme.CORNER_MD,
                               border_width=1, border_color=theme.BORDER_DEFAULT)
        hk_card.pack(fill="x")
        hk_inner = ctk.CTkFrame(hk_card, fg_color="transparent")
        hk_inner.pack(padx=12, pady=8)
        badge_hk = ctk.CTkFrame(hk_inner, fg_color=theme.BG_ELEVATED, corner_radius=theme.CORNER_SM,
                                border_width=1, border_color=theme.BORDER_ACTIVE)
        badge_hk.pack(side="left")
        ctk.CTkLabel(badge_hk, text=hotkey, font=theme.FONT_MONO_SM(),
                     text_color=theme.TEXT_PRIMARY).pack(padx=8, pady=3)
        ctk.CTkLabel(hk_inner, text="  Pressione para gravar",
                     font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY).pack(side="left")

    def _build_step_2(self, parent):
        """Step 2 — Como funciona — grid 4+3 de mode cards (sem hotkeys)."""
        hotkey = state._CONFIG.get("RECORD_HOTKEY", "ctrl+shift+space").title()
        ctk.CTkLabel(parent, text="COMO FUNCIONA",
                     font=theme.FONT_OVERLINE(), text_color=theme.TEXT_MUTED).pack(
            anchor="w", pady=(0, 4))
        ctk.CTkLabel(parent,
                     text=f"Selecione o modo no ícone da bandeja e pressione {hotkey} para gravar.",
                     font=theme.FONT_CAPTION(), text_color=theme.TEXT_MUTED, wraplength=400,
                     justify="left").pack(anchor="w", pady=(0, 8))
        grid = ctk.CTkFrame(parent, fg_color="transparent")
        grid.pack(fill="both", expand=True)
        cols = 4
        for i in range(cols):
            grid.columnconfigure(i, weight=1)
        for idx, (mode_id, label, desc) in enumerate(self.MODES):
            row_idx, col_idx = divmod(idx, cols)
            padx_l = 0 if col_idx == 0 else 3
            padx_r = 0 if col_idx == cols - 1 else 3
            card = ctk.CTkFrame(grid, fg_color=theme.BG_DEEP, corner_radius=theme.CORNER_MD,
                                border_width=1, border_color=theme.BORDER_DEFAULT)
            card.grid(row=row_idx, column=col_idx, padx=(padx_l, padx_r), pady=(0, 6), sticky="nsew")
            ctk.CTkLabel(card, text=label,
                         font=theme.FONT_OVERLINE(), text_color=theme.TEXT_PRIMARY).pack(
                anchor="w", padx=10)
            ctk.CTkLabel(card, text=desc, font=theme.FONT_CAPTION(), text_color=theme.TEXT_MUTED,
                         wraplength=100, justify="left").pack(
                anchor="w", padx=10, pady=(2, 8))

    def _build_step_3(self, parent):
        """Step 3 — Gemini API."""
        how = ctk.CTkFrame(parent, fg_color=theme.BG_DEEP, corner_radius=theme.CORNER_LG,
                           border_width=1, border_color=theme.BORDER_DEFAULT)
        how.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(how, text="Como obter sua chave",
                     font=theme.FONT_BODY_BOLD(), text_color=theme.TEXT_PRIMARY).pack(
            anchor="w", padx=12, pady=(10, 6))
        for step_txt in [
            "1. Acesse aistudio.google.com/apikey",
            "2. Clique em 'Create API Key'",
            "3. Copie a chave gerada",
            "4. Cole abaixo e clique Testar",
        ]:
            ctk.CTkLabel(how, text=step_txt, font=theme.FONT_CAPTION(),
                         text_color=theme.TEXT_MUTED).pack(anchor="w", padx=12, pady=1)
        ctk.CTkFrame(how, height=8, fg_color="transparent").pack()

        self._gemini_entry = ctk.CTkEntry(
            parent, height=theme.INPUT_HEIGHT, font=theme.FONT_MONO(), fg_color=theme.BG_DEEP,
            border_color=theme.BORDER_DEFAULT, border_width=1, text_color=theme.TEXT_PRIMARY,
            placeholder_text="AIza...")
        self._gemini_entry.pack(fill="x", pady=(0, 8))
        self._gemini_entry.bind("<KeyRelease>", lambda e: self._on_gemini_type())
        self._gemini_entry.bind("<FocusIn>",
            lambda e: self._gemini_entry.configure(border_color=theme.BORDER_ACTIVE))
        self._gemini_entry.bind("<FocusOut>",
            lambda e: self._gemini_entry.configure(border_color=theme.BORDER_DEFAULT))

        ctk.CTkButton(parent, text="Testar Conexão", height=theme.INPUT_HEIGHT,
                      corner_radius=theme.CORNER_MD,
                      fg_color=theme.PURPLE,
                      hover_color=theme.PURPLE_HOVER,
                      font=theme.FONT_BODY_BOLD(),
                      text_color=theme.TEXT_PRIMARY,
                      command=self._test_gemini).pack(fill="x", pady=(0, 8))

        self._gemini_status = ctk.CTkLabel(
            parent, text="● Cole sua chave acima",
            font=theme.FONT_CAPTION(), text_color=theme.TEXT_DISABLED, anchor="w")
        self._gemini_status.pack(anchor="w")

    def _build_step_4(self, parent):
        """Step 4 — Licença (opcional)."""
        ctk.CTkLabel(parent, text="LICENÇA",
                     font=theme.FONT_OVERLINE(), text_color=theme.TEXT_DISABLED).pack(
            anchor="w", pady=(0, 4))
        ctk.CTkLabel(parent, text="Opcional — pular para usar gratuitamente",
                     font=theme.FONT_BODY(), text_color=theme.TEXT_MUTED).pack(
            anchor="w", pady=(0, 16))

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, 8))
        self._license_entry = ctk.CTkEntry(
            row, height=theme.INPUT_HEIGHT, font=theme.FONT_MONO_SM(), fg_color=theme.BG_DEEP,
            border_color=theme.BORDER_DEFAULT, border_width=1, text_color=theme.TEXT_PRIMARY,
            placeholder_text="vc-xxxxxxxxxxxx-xxxxxxxxxxxx")
        self._license_entry.pack(side="left", fill="x", expand=True)
        self._license_entry.bind("<KeyRelease>", lambda e: self._update_license_next_btn())
        self._license_entry.bind("<FocusIn>",
            lambda e: self._license_entry.configure(border_color=theme.BORDER_ACTIVE))
        self._license_entry.bind("<FocusOut>",
            lambda e: self._license_entry.configure(border_color=theme.BORDER_DEFAULT))
        ctk.CTkButton(row, text="Validar", width=76, height=theme.INPUT_HEIGHT,
                      corner_radius=theme.CORNER_MD, fg_color=theme.PURPLE, hover_color=theme.PURPLE_HOVER,
                      font=theme.FONT_BODY_BOLD(),
                      command=self._validate_license).pack(side="left", padx=(6, 0))

        self._license_status = ctk.CTkLabel(
            parent, text="Grátis — sem chave",
            font=theme.FONT_BODY(), text_color=theme.TEXT_DISABLED, anchor="w")
        self._license_status.pack(anchor="w", pady=(0, 8))
        ctk.CTkLabel(parent, text="Comprar em: voice.jplabs.ai",
                     font=theme.FONT_CAPTION(), text_color=theme.BORDER_HOVER).pack(anchor="w")

    def _build_step_5(self, parent):
        """Step 5 — Pronto!"""
        ctk.CTkLabel(parent, text="✓",
                     font=theme.FONT_DISPLAY(), text_color=theme.SUCCESS).pack(pady=(8, 4))
        ctk.CTkLabel(parent, text="Tudo pronto!",
                     font=theme.FONT_HEADING(), text_color=theme.TEXT_PRIMARY).pack(pady=(0, 8))
        hotkey = state._CONFIG.get("RECORD_HOTKEY", "ctrl+shift+space").title()
        card = ctk.CTkFrame(parent, fg_color=theme.BG_DEEP, corner_radius=theme.CORNER_LG,
                            border_width=1, border_color=theme.BORDER_DEFAULT)
        card.pack(fill="x", pady=(0, 8))
        r_hk = ctk.CTkFrame(card, fg_color="transparent")
        r_hk.pack(fill="x", padx=12, pady=(10, 4))
        badge_hk = ctk.CTkFrame(r_hk, fg_color=theme.BG_ELEVATED, corner_radius=theme.CORNER_SM,
                                 border_width=1, border_color=theme.BORDER_ACTIVE)
        badge_hk.pack(side="left")
        ctk.CTkLabel(badge_hk, text=hotkey, font=theme.FONT_MONO_SM(),
                     text_color=theme.TEXT_PRIMARY).pack(padx=8, pady=3)
        ctk.CTkLabel(r_hk, text="  Gravar (modo selecionado na bandeja)",
                     font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY).pack(side="left")
        ctk.CTkFrame(card, height=1, fg_color=theme.BORDER_DEFAULT, corner_radius=0).pack(fill="x", padx=12, pady=4)
        for _, label, desc in self.MODES:
            r = ctk.CTkFrame(card, fg_color="transparent")
            r.pack(fill="x", padx=12, pady=2)
            ctk.CTkLabel(r, text=f"{label}  ", font=theme.FONT_BODY_BOLD(),
                         text_color=theme.TEXT_PRIMARY).pack(side="left")
            ctk.CTkLabel(r, text=desc, font=theme.FONT_BODY(),
                         text_color=theme.TEXT_MUTED).pack(side="left")
        ctk.CTkFrame(card, height=6, fg_color="transparent").pack()
        ctk.CTkLabel(parent,
                     text="Troque o modo a qualquer momento via System Tray > Modo",
                     font=theme.FONT_CAPTION(), text_color=theme.TEXT_MUTED,
                     justify="center").pack()

    # ── Navigation ─────────────────────────────────────────────────────────

    def _go_to_step(self, step: int):
        self._current_step = step
        # Hide all step frames
        for f in self._step_frames:
            f.pack_forget()
        # Show current step
        self._step_frames[step - 1].pack(fill="both", expand=True, padx=24, pady=16)

        # Update header labels
        titles = [
            ("Bem-vindo",    "Sua voz. Seu texto. Sem fricção."),
            ("Como funciona", "7 modos — selecione na bandeja, grave com 1 hotkey"),
            ("Gemini API",   "Necessário para modos com IA"),
            ("Licença",      "Opcional — use gratuitamente"),
            ("Tudo pronto!", "Voice Commander está configurado"),
        ]
        self._step_title_lbl.configure(text=titles[step - 1][0])
        self._step_subtitle_lbl.configure(text=titles[step - 1][1])

        # Update progress dots
        for i, dot in enumerate(self._dot_frames):
            n = i + 1
            if n < step:
                dot.configure(fg_color=theme.PURPLE, width=12, height=12, corner_radius=6)
            elif n == step:
                dot.configure(fg_color=theme.TEXT_PRIMARY, width=14, height=14, corner_radius=7)
            else:
                dot.configure(fg_color=theme.BORDER_HOVER, width=12, height=12, corner_radius=6)

        # Update prev button
        if step == 1:
            self._prev_btn.pack_forget()
        else:
            self._prev_btn.pack(side="left", padx=(16, 0), pady=14)

        # Update next button
        if step == 5:
            self._next_btn.configure(text="Começar", fg_color=theme.SUCCESS,
                                     hover_color="#00CC6E", text_color=theme.BG_ABYSS)
        elif step == 4:
            lic_text = self._license_entry.get().strip() if self._license_entry else ""
            self._next_btn.configure(
                text="Pular" if not lic_text else "Próximo",
                fg_color=theme.PURPLE, hover_color=theme.PURPLE_HOVER,
                text_color=theme.TEXT_PRIMARY)
        else:
            self._next_btn.configure(text="Próximo", fg_color=theme.PURPLE,
                                     hover_color=theme.PURPLE_HOVER,
                                     text_color=theme.TEXT_PRIMARY)

    def _go_next(self):
        if self._current_step < 5:
            self._go_to_step(self._current_step + 1)
        else:
            self._finish()

    def _go_prev(self):
        if self._current_step > 1:
            self._go_to_step(self._current_step - 1)

    def _update_license_next_btn(self):
        if self._next_btn and self._current_step == 4:
            lic_text = self._license_entry.get().strip() if self._license_entry else ""
            self._next_btn.configure(text="Pular" if not lic_text else "Próximo")

    # ── Callbacks (mantidos intactos da versão anterior) ───────────────────

    def _validate_license(self):
        key = self._license_entry.get().strip()
        if not key:
            self._skip_license()
            return
        valid, msg = validate_license_key(key)
        if valid:
            self._license_status.configure(text=f"✓ {msg}", text_color="#22C55E")
            self._license_ok = True
        else:
            self._license_status.configure(text=f"✗ {msg}", text_color="#FF3366")
            self._license_ok = False
        self._update_license_next_btn()

    def _skip_license(self):
        self._license_entry.delete(0, "end")
        self._license_ok = True
        self._license_status.configure(text="Grátis — sem chave", text_color=theme.TEXT_DISABLED)

    def _on_gemini_type(self):
        has_text = bool(self._gemini_entry.get().strip())
        if has_text and not self._gemini_ok:
            self._gemini_status.configure(
                text="● Clique Testar para verificar (opcional)", text_color=theme.TEXT_DISABLED)
            self._gemini_ok = True

    def _test_gemini(self):
        api_key = self._gemini_entry.get().strip()
        if not api_key:
            self._gemini_status.configure(text="● Insira a chave primeiro", text_color="#FF3366")
            return
        self._gemini_status.configure(text="● Testando...", text_color="#FFAA00")

        def _do_test():
            ok, msg = _test_gemini_key(api_key)

            def _update():
                if ok:
                    self._gemini_status.configure(text=f"● {msg}", text_color="#22C55E")
                else:
                    self._gemini_status.configure(
                        text=f"● Aviso: {msg[:60]}", text_color="#FF6B35")
                self._gemini_ok = True

            try:
                self._root.after(0, _update)
            except Exception as e:
                print(f"[WARN] Falha ao atualizar status Gemini na UI: {e}")

        threading.Thread(target=_do_test, daemon=True).start()

    def _finish(self):
        """Salva as chaves, grava sentinel e fecha o wizard."""
        license_key = self._license_entry.get().strip() if self._license_entry else ""
        gemini_key = self._gemini_entry.get().strip() if self._gemini_entry else ""
        _save_env({"LICENSE_KEY": license_key, "GEMINI_API_KEY": gemini_key})
        if self._done_callback is not None:
            self._done_callback()
        self._root.destroy()
        self._root = None

    def _on_close(self):
        """Fechar sem completar encerra o app."""
        # Onboarding é obrigatório — fechar o wizard antes de concluir termina o processo.
        # sys.exit() é seguro aqui: pystray ainda não foi iniciada neste ponto do lifecycle.
        sys.exit(0)
