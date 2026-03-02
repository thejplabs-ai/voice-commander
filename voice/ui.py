# voice/ui.py — OnboardingWindow, SettingsWindow, _apply_taskbar_icon
# done_callback injected from app.py — no import of app to avoid cycle

import ctypes
import ctypes.wintypes
import pathlib
import sys
import threading

from voice import state
from voice import theme
from voice.paths import _resource_path
from voice.license import validate_license_key, _test_gemini_key
from voice.config import _save_env, _reload_config

__version__ = "1.0.15"

# Tentar importar customtkinter — fallback silencioso
try:
    import customtkinter as ctk
    state._ctk_available = True
except ImportError:
    print("[WARN] customtkinter não instalado — janela de configurações desativada. "
          "Instale com: pip install customtkinter==5.2.2")


def _apply_taskbar_icon(root, ico_path: pathlib.Path) -> None:
    """Força o ícone correto no taskbar do Windows via Win32 API.

    GetParent(winfo_id()) retorna 0 para janelas top-level no Tk/CTk — por isso
    usamos FindWindowW pelo título da janela, que devolve o HWND real que o
    Windows usa para o botão na taskbar.
    """
    if not ico_path.exists():
        return
    try:
        root.update_idletasks()
        title = root.title()
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        if not hwnd:
            hwnd = root.winfo_id()
        if not hwnd:
            return
        LR_LOADFROMFILE, IMAGE_ICON, WM_SETICON = 0x10, 1, 0x0080
        for size, kind in ((32, 1), (16, 0)):
            hicon = ctypes.windll.user32.LoadImageW(
                None, str(ico_path), IMAGE_ICON, size, size, LR_LOADFROMFILE)
            if hicon:
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, kind, hicon)
    except Exception as e:
        print(f"[WARN] Falha ao aplicar ícone no taskbar: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# OnboardingWindow — Multi-Step Wizard (Linear/Arc DNA)
# ─────────────────────────────────────────────────────────────────────────────

class OnboardingWindow:
    """Wizard de configuração inicial — 5 steps."""

    MODES = [
        ("transcribe", "Transcrever",    "Voz → texto corrigido",        "✍"),
        ("simple",     "Prompt Simples", "Injeta contexto",               "⚙"),
        ("prompt",     "Prompt COSTAR",  "Formato estruturado XML",       "☰"),
        ("query",      "Query AI",       "Pergunta direta à IA",          "❓"),
        ("bullet",     "Bullet Dump",    "Voz → bullets hierárquicos",    "•"),
        ("email",      "Email Draft",    "Voz → email profissional",      "✉"),
        ("translate",  "Traduzir",       "Traduz para EN/PT",             "⇄"),
        ("visual",     "Visual Query",   "Screenshot + voz → Gemini",    "👁"),
        ("pipeline",   "Pipeline",       "Clipboard + instrução de voz",  "⛓"),
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
        for idx, (mode_id, label, desc, icon) in enumerate(self.MODES):
            row_idx, col_idx = divmod(idx, cols)
            padx_l = 0 if col_idx == 0 else 3
            padx_r = 0 if col_idx == cols - 1 else 3
            card = ctk.CTkFrame(grid, fg_color=theme.BG_DEEP, corner_radius=theme.CORNER_MD,
                                border_width=1, border_color=theme.BORDER_DEFAULT)
            card.grid(row=row_idx, column=col_idx, padx=(padx_l, padx_r), pady=(0, 6), sticky="nsew")
            ctk.CTkLabel(card, text=icon, font=theme.FONT_CAPTION(),
                         text_color=theme.TEXT_SECONDARY).pack(anchor="w", padx=10, pady=(8, 2))
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
        for _, label, desc, icon in self.MODES:
            r = ctk.CTkFrame(card, fg_color="transparent")
            r.pack(fill="x", padx=12, pady=2)
            ctk.CTkLabel(r, text=icon, font=theme.FONT_CAPTION(), text_color=theme.TEXT_SECONDARY,
                         width=14).pack(side="left")
            ctk.CTkLabel(r, text=f" {label}  ", font=theme.FONT_BODY_BOLD(),
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


# ─────────────────────────────────────────────────────────────────────────────
# SettingsWindow — Sidebar Commander (Raycast DNA)
# ─────────────────────────────────────────────────────────────────────────────

class SettingsWindow:
    """Settings window com sidebar — Raycast DNA, 640×540px."""

    MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]
    LANGUAGES = ["auto-detect", "pt", "en"]

    # Grid 3x3 — ordem: (mode_id, icon, label, desc)
    MODES_GRID = [
        ("transcribe", "✍",  "Transcrever",    "Voz → texto"),
        ("simple",     "⚙",  "Prompt Simples",  "+contexto"),
        ("prompt",     "☰",  "COSTAR",          "XML estruturado"),
        ("query",      "❓", "Perguntar",        "Gemini responde"),
        ("bullet",     "•",  "Bullet Points",   "Lista hierárquica"),
        ("email",      "✉",  "Email",           "Profissional"),
        ("translate",  "⇄",  "Traduzir",        "EN/PT"),
        ("visual",     "👁", "Visual",          "Screenshot+Voz"),
        ("pipeline",   "⛓",  "Pipeline",        "Clipboard"),
    ]

    # Mantida para compatibilidade com OnboardingWindow e step_5
    MODES = [
        ("transcribe", "Transcrever",    "Voz → texto corrigido",        "✍"),
        ("simple",     "Prompt Simples", "Injeta contexto",               "⚙"),
        ("prompt",     "Prompt COSTAR",  "Formato estruturado XML",       "☰"),
        ("query",      "Query AI",       "Pergunta direta à IA",          "❓"),
        ("bullet",     "Bullet Dump",    "Voz → bullets hierárquicos",    "•"),
        ("email",      "Email Draft",    "Voz → email profissional",      "✉"),
        ("translate",  "Traduzir",       "Traduz para EN/PT",             "⇄"),
        ("visual",     "Visual Query",   "Screenshot + voz → Gemini",    "👁"),
        ("pipeline",   "Pipeline",       "Clipboard + instrução de voz",  "⛓"),
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
        # New fields
        self._hotkey_entry = None
        self._provider_var = None
        self._openai_key_entry = None
        self._openai_eye_btn = None
        self._openai_key_frame = None
        self._device_var = None
        self._translate_lang_var = None
        self._wake_enabled_var = None
        self._wake_keyword_var = None
        self._wake_status_label = None
        self._sound_entries: dict = {}
        self._mode_card_refs: dict = {}
        self._speed_var = None
        # Sidebar navigation state
        self._current_section = "status"
        self._content_area = None
        self._section_btns = {}
        self._section_frames = {}

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

        # Build all section frames (6 nav items — ai e license agora dentro de general)
        self._build_section_status()
        self._build_section_modes()
        self._build_section_general()
        self._build_section_advanced()
        self._build_section_profile()
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
            ("status",   "● Status"),
            ("modes",    "🎤 Modo Ativo"),
            ("general",  "⚙ Geral"),
            ("advanced", "⚒ Avançado"),
            ("profile",  "👤 Perfil"),
            ("about",    "ℹ Sobre"),
        ]
        for section_id, label in nav_items:
            btn = ctk.CTkButton(
                parent, text=label, anchor="w",
                height=theme.BTN_HEIGHT, corner_radius=theme.CORNER_MD,
                fg_color="transparent", hover_color=theme.BG_ELEVATED,
                font=theme.FONT_BODY(), text_color=theme.TEXT_MUTED,
                command=lambda sid=section_id: self._switch_section(sid))
            btn.pack(fill="x", padx=8, pady=2)
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
            "visual":           "Screenshot + Voz",
            "pipeline":         "Pipeline",
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
        for idx, (mode_id, icon, label, desc) in enumerate(self.MODES_GRID):
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
            ctk.CTkLabel(card, text=icon, font=theme.FONT_HEADING(),
                         text_color=theme.TEXT_SECONDARY).pack(pady=(12, 4))
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
        """Seção de configuração do provedor de IA (Gemini / OpenAI)."""
        ac = ctk.CTkFrame(parent, fg_color=theme.BG_DEEP, corner_radius=theme.CORNER_LG,
                          border_width=1, border_color=theme.BORDER_DEFAULT)
        ac.pack(fill="x", padx=20, pady=(0, 8))
        ctk.CTkLabel(ac, text="PROVEDOR DE IA",
                     font=theme.FONT_OVERLINE(), text_color=theme.TEXT_MUTED).pack(
            anchor="w", padx=16, pady=(12, 4))

        ctk.CTkLabel(ac, text="Provedor",
                     font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY).pack(
            anchor="w", padx=16, pady=(0, 2))
        self._provider_var = ctk.StringVar(value=state._CONFIG.get("AI_PROVIDER", "gemini"))
        ctk.CTkOptionMenu(ac, variable=self._provider_var, values=["gemini", "openai"],
                          height=theme.INPUT_HEIGHT, corner_radius=theme.CORNER_MD,
                          fg_color=theme.BG_ABYSS, button_color=theme.PURPLE,
                          button_hover_color=theme.PURPLE_DARK,
                          text_color=theme.TEXT_PRIMARY,
                          command=lambda _: self._update_openai_visibility(ac)).pack(
            fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(ac, text="Gemini API Key",
                     font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY).pack(
            anchor="w", padx=16, pady=(0, 2))
        key_row = ctk.CTkFrame(ac, fg_color="transparent")
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
            key_row, text="👁", width=theme.INPUT_HEIGHT, height=theme.INPUT_HEIGHT,
            fg_color=theme.BG_ABYSS, hover_color=theme.BG_NIGHT,
            border_color=theme.BORDER_DEFAULT, border_width=1, corner_radius=theme.CORNER_MD,
            command=self._toggle_key_visibility)
        self._eye_btn.pack(side="left", padx=(6, 0))

        self._openai_key_frame = ctk.CTkFrame(ac, fg_color="transparent")
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
            oai_row, text="👁", width=theme.INPUT_HEIGHT, height=theme.INPUT_HEIGHT,
            fg_color=theme.BG_ABYSS, hover_color=theme.BG_NIGHT,
            border_color=theme.BORDER_DEFAULT, border_width=1, corner_radius=theme.CORNER_MD,
            command=self._toggle_openai_key_visibility)
        self._openai_eye_btn.pack(side="left", padx=(6, 0))
        self._update_openai_visibility(ac)
        ctk.CTkFrame(ac, height=4, fg_color="transparent").pack()

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

    def _build_wakeword_section(self, parent) -> None:
        """Seção de configuração do wake word."""
        wc = ctk.CTkFrame(parent, fg_color=theme.BG_DEEP, corner_radius=theme.CORNER_LG,
                          border_width=1, border_color=theme.BORDER_DEFAULT)
        wc.pack(fill="x", padx=20, pady=(0, 8))
        ctk.CTkLabel(wc, text="WAKE WORD",
                     font=theme.FONT_OVERLINE(), text_color=theme.TEXT_MUTED).pack(
            anchor="w", padx=16, pady=(12, 4))

        ww_enabled = state._CONFIG.get("WAKE_WORD_ENABLED", "false").lower() == "true"
        self._wake_enabled_var = ctk.BooleanVar(value=ww_enabled)
        ctk.CTkCheckBox(wc, text="Ativar wake word",
                        variable=self._wake_enabled_var,
                        font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY,
                        fg_color=theme.PURPLE, hover_color=theme.PURPLE_DARK,
                        checkmark_color=theme.TEXT_PRIMARY,
                        command=self._on_wakeword_toggle).pack(
            anchor="w", padx=16, pady=(0, 6))

        self._wake_status_label = ctk.CTkLabel(
            wc, text="", font=theme.FONT_CAPTION(), text_color=theme.TEXT_DISABLED)
        self._wake_status_label.pack(anchor="w", padx=16, pady=(0, 8))

        ctk.CTkLabel(wc, text="Keyword",
                     font=theme.FONT_BODY(), text_color=theme.TEXT_SECONDARY).pack(
            anchor="w", padx=16, pady=(0, 2))
        self._wake_keyword_var = ctk.StringVar(
            value=state._CONFIG.get("WAKE_WORD_KEYWORD", "hey_jarvis"))
        ctk.CTkOptionMenu(wc, variable=self._wake_keyword_var,
                          values=["hey_jarvis", "hey_mycroft", "alexa"],
                          height=theme.INPUT_HEIGHT, corner_radius=theme.CORNER_MD,
                          fg_color=theme.BG_ABYSS, button_color=theme.PURPLE,
                          button_hover_color=theme.PURPLE_DARK,
                          text_color=theme.TEXT_PRIMARY).pack(fill="x", padx=16, pady=(0, 12))

        # Show current install status on open
        self._refresh_wakeword_status()

    def _refresh_wakeword_status(self) -> None:
        """Atualiza label de status baseado se openwakeword está instalado."""
        if self._wake_status_label is None:
            return
        try:
            import openwakeword  # noqa: F401
            import onnxruntime   # noqa: F401
            self._wake_status_label.configure(
                text="✓ Dependências instaladas", text_color=theme.SUCCESS)
        except ImportError:
            self._wake_status_label.configure(
                text="Dependências não instaladas — ative para instalar automaticamente",
                text_color=theme.TEXT_DISABLED)

    def _on_wakeword_toggle(self) -> None:
        """Chamado quando o checkbox Wake Word é clicado."""
        if not self._wake_enabled_var.get():
            return  # Desativando — nada a fazer

        # Verificar se dependências já estão instaladas
        try:
            import openwakeword  # noqa: F401
            import onnxruntime   # noqa: F401
            self._wake_status_label.configure(
                text="✓ Dependências instaladas", text_color=theme.SUCCESS)
            return  # Já instalado — pode ativar normalmente
        except ImportError:
            pass

        # Dependências ausentes — instalar automaticamente
        self._wake_enabled_var.set(False)  # Desmarcar enquanto instala
        self._wake_status_label.configure(
            text="⟳ Instalando openwakeword + onnxruntime...", text_color=theme.WARNING)

        def _install():
            import subprocess
            import sys as _sys
            try:
                subprocess.check_call(
                    [_sys.executable, "-m", "pip", "install", "openwakeword", "onnxruntime"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                def _on_success():
                    self._wake_enabled_var.set(True)
                    self._wake_status_label.configure(
                        text="✓ Instalado! Salve e reinicie o Voice Commander.",
                        text_color=theme.SUCCESS)
                self._root.after(0, _on_success)
            except Exception as exc:
                _err_msg = str(exc)
                def _on_error(_msg=_err_msg):
                    self._wake_status_label.configure(
                        text=f"✗ Falha na instalação: {_msg}",
                        text_color=theme.ERROR)
                self._root.after(0, _on_error)

        threading.Thread(target=_install, daemon=True).start()

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
        self._build_wakeword_section(f)
        self._build_sounds_section(f)

    def _build_section_profile(self):
        """Feature 1: User Profile — lista de fatos injetados em todas as chamadas Gemini."""
        f = ctk.CTkScrollableFrame(
            self._content_area, fg_color="transparent",
            scrollbar_button_color=theme.BORDER_HOVER,
            scrollbar_button_hover_color=theme.BORDER_ACTIVE)
        self._section_frames["profile"] = f

        # Header
        hdr = ctk.CTkFrame(f, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        ctk.CTkLabel(hdr, text="PERFIL DO USUÁRIO",
                     font=theme.FONT_OVERLINE(), text_color=theme.TEXT_DISABLED).pack(anchor="w")
        ctk.CTkLabel(hdr,
                     text='Fatos injetados em todas as chamadas Gemini · Voz: "adiciona ao meu perfil: ..."',
                     font=theme.FONT_CAPTION(), text_color=theme.TEXT_MUTED).pack(anchor="w")

        # Facts list frame (refreshable)
        self._profile_facts_frame = ctk.CTkFrame(f, fg_color="transparent")
        self._profile_facts_frame.pack(fill="x", padx=20, pady=(8, 0))

        # Add fact row
        add_row = ctk.CTkFrame(f, fg_color="transparent")
        add_row.pack(fill="x", padx=20, pady=(12, 4))
        self._profile_new_fact_entry = ctk.CTkEntry(
            add_row, placeholder_text="Novo fato (ex: Prefere respostas em inglês)",
            font=theme.FONT_BODY(), height=theme.BTN_HEIGHT,
            fg_color=theme.BG_DEEP, border_color=theme.BORDER_DEFAULT,
            text_color=theme.TEXT_PRIMARY,
        )
        self._profile_new_fact_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            add_row, text="Adicionar", width=90, height=theme.BTN_HEIGHT,
            corner_radius=theme.CORNER_MD, fg_color=theme.PURPLE,
            hover_color=theme.PURPLE_HOVER, font=theme.FONT_BODY_BOLD(),
            command=self._profile_add_fact,
        ).pack(side="left")

        self._profile_refresh_facts()

    def _profile_refresh_facts(self):
        """Limpa e reconstrói a lista de fatos do perfil."""
        for widget in self._profile_facts_frame.winfo_children():
            widget.destroy()

        try:
            from voice.user_profile import load_profile
            profile = load_profile()
            state._user_profile = profile
        except Exception:
            profile = {"facts": []}

        facts = profile.get("facts", [])
        if not facts:
            ctk.CTkLabel(
                self._profile_facts_frame,
                text="Nenhum fato cadastrado.",
                font=theme.FONT_CAPTION(), text_color=theme.TEXT_MUTED,
                anchor="w",
            ).pack(anchor="w", pady=4)
            return

        for i, fact in enumerate(facts):
            row = ctk.CTkFrame(
                self._profile_facts_frame, fg_color=theme.BG_DEEP,
                corner_radius=theme.CORNER_MD, border_width=1,
                border_color=theme.BORDER_DEFAULT)
            row.pack(fill="x", pady=(0, 4))
            ctk.CTkLabel(
                row, text=f"• {fact}",
                font=theme.FONT_BODY(), text_color=theme.TEXT_PRIMARY,
                anchor="w", justify="left", wraplength=400,
            ).pack(side="left", padx=12, pady=8, fill="x", expand=True)
            idx = i  # capture for closure

            def _make_delete(index):
                def _delete():
                    try:
                        from voice.user_profile import remove_fact
                        remove_fact(index)
                        self._profile_refresh_facts()
                    except Exception as e:
                        print(f"[WARN] Falha ao remover fato: {e}")
                return _delete

            ctk.CTkButton(
                row, text="✕", width=28, height=28,
                corner_radius=theme.CORNER_MD,
                fg_color="transparent", hover_color=theme.BG_ELEVATED,
                font=theme.FONT_CAPTION(), text_color=theme.TEXT_MUTED,
                command=_make_delete(idx),
            ).pack(side="right", padx=8)

    def _profile_add_fact(self):
        fact = self._profile_new_fact_entry.get().strip()
        if not fact:
            return
        try:
            from voice.user_profile import add_fact
            add_fact(fact)
        except Exception as e:
            print(f"[WARN] Falha ao adicionar fato: {e}")
        self._profile_new_fact_entry.delete(0, "end")
        self._profile_refresh_facts()

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

    # ── Callbacks (mantidos intactos da versão anterior) ───────────────────

    def _toggle_key_visibility(self):
        self._show_key = not self._show_key
        self._api_entry.configure(show="" if self._show_key else "*")

    def _toggle_openai_key_visibility(self):
        self._show_openai_key = not self._show_openai_key
        if self._openai_key_entry:
            self._openai_key_entry.configure(show="" if self._show_openai_key else "*")

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
        if self._device_var:
            new_values["WHISPER_DEVICE"] = self._device_var.get()
        if self._translate_lang_var:
            new_values["TRANSLATE_TARGET_LANG"] = self._translate_lang_var.get()
        if self._wake_enabled_var is not None:
            new_values["WAKE_WORD_ENABLED"] = "true" if self._wake_enabled_var.get() else "false"
        if self._wake_keyword_var:
            new_values["WAKE_WORD_KEYWORD"] = self._wake_keyword_var.get()
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


def _open_settings() -> None:
    """Abre janela de Settings (singleton — foca se já aberta)."""
    if not state._ctk_available:
        ctypes.windll.user32.MessageBoxW(
            0,
            "customtkinter não instalado.\nInstale com: pip install customtkinter==5.2.2",
            "Voice Commander — Configurações",
            0x40,
        )
        return
    SettingsWindow().open()
