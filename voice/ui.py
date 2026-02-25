# voice/ui.py — OnboardingWindow, SettingsWindow, _apply_taskbar_icon
# done_callback injected from app.py — no import of app to avoid cycle

import ctypes
import ctypes.wintypes
import pathlib
import threading

from voice import state
from voice.paths import _resource_path
from voice.license import validate_license_key, _test_gemini_key
from voice.config import _save_env, _reload_config

__version__ = "1.0.11"

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
        # FindWindowW procura pelo título exato — retorna o HWND da janela top-level
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        if not hwnd:
            # Fallback: tentar winfo_id() direto (funciona em alguns ambientes)
            hwnd = root.winfo_id()
        if not hwnd:
            return
        LR_LOADFROMFILE, IMAGE_ICON, WM_SETICON = 0x10, 1, 0x0080
        for size, kind in ((32, 1), (16, 0)):
            hicon = ctypes.windll.user32.LoadImageW(
                None, str(ico_path), IMAGE_ICON, size, size, LR_LOADFROMFILE)
            if hicon:
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, kind, hicon)
    except Exception:
        pass


class OnboardingWindow:
    """Wizard de configuração inicial — 2 passos obrigatórios."""

    def __init__(self, done_callback=None):
        self._root = None
        self._license_entry = None
        self._license_status = None
        self._gemini_entry = None
        self._gemini_status = None
        self._start_btn = None
        self._license_ok = False
        self._gemini_ok = False
        self._done_callback = done_callback  # injected from app.py

    def run(self) -> None:
        """Abre wizard bloqueante. Retorna quando usuário completa os 2 passos."""
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
        self._root.attributes("-topmost", True)
        self._root.configure(fg_color="#01010D")
        _icon = _resource_path("icon.ico")
        if _icon.exists():
            self._root.iconbitmap(str(_icon))
            _apply_taskbar_icon(self._root, _icon)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Container scrollável — permite rolar em monitores pequenos
        scroll = ctk.CTkScrollableFrame(self._root, fg_color="transparent",
                                        scrollbar_button_color="#2A2A3A",
                                        scrollbar_button_hover_color="#3A3A5A")
        scroll.pack(fill="both", expand=True)

        # Header
        h = ctk.CTkFrame(scroll, fg_color="transparent")
        h.pack(fill="x", padx=16, pady=(20, 8))
        ctk.CTkLabel(h, text="Voice Commander",
                     font=("Segoe UI", 20, "bold"), text_color="#FFFFFF").pack(anchor="w")
        ctk.CTkLabel(h, text="Configuração inicial — leva menos de 1 minuto",
                     font=("Segoe UI", 12), text_color="#808080").pack(anchor="w")
        ctk.CTkFrame(scroll, height=1, fg_color="#2A2A3A", corner_radius=0).pack(
            fill="x", padx=16, pady=(0, 8))

        # Como funciona
        finfo = ctk.CTkFrame(scroll, fg_color="#0D0C25", corner_radius=12)
        finfo.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(finfo, text="COMO FUNCIONA",
                     font=("Segoe UI", 10, "bold"), text_color="#6B2FF8").pack(
            anchor="w", padx=20, pady=(12, 6))
        steps = [
            ("1", "Ctrl+Shift+Space",    "Pressione para iniciar a gravação de voz"),
            ("2", "Fale normalmente",     "O app grava enquanto a tecla estiver ativa"),
            ("3", "Pressione novamente",  "Solta o atalho — o texto é transcrito e colado"),
        ]
        for num, title, desc in steps:
            row = ctk.CTkFrame(finfo, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=(0, 6))
            ctk.CTkLabel(row, text=num,
                         font=("Segoe UI", 11, "bold"), text_color="#6B2FF8",
                         width=18).pack(side="left", anchor="n", pady=2)
            col = ctk.CTkFrame(row, fg_color="transparent")
            col.pack(side="left", padx=(6, 0), fill="x", expand=True)
            ctk.CTkLabel(col, text=title,
                         font=("Segoe UI", 11, "bold"), text_color="#FFFFFF",
                         anchor="w").pack(anchor="w")
            ctk.CTkLabel(col, text=desc,
                         font=("Segoe UI", 10), text_color="#808080",
                         anchor="w").pack(anchor="w")
        ctk.CTkLabel(finfo,
                     text="4 modos: Transcrever  |  Prompt simples  |  Prompt COSTAR  |  Query Gemini",
                     font=("Segoe UI", 10), text_color="#4A4A6A",
                     wraplength=320, justify="left").pack(anchor="w", padx=20, pady=(0, 12))

        # Licença (opcional)
        f1 = ctk.CTkFrame(scroll, fg_color="#0D0C25", corner_radius=12)
        f1.pack(fill="x", padx=16, pady=(0, 8))
        lic_header = ctk.CTkFrame(f1, fg_color="transparent")
        lic_header.pack(fill="x", padx=20, pady=(12, 4))
        ctk.CTkLabel(lic_header, text="LICENÇA  ",
                     font=("Segoe UI", 10, "bold"), text_color="#4A4A6A").pack(side="left")
        ctk.CTkLabel(lic_header, text="opcional — pular para usar gratuitamente",
                     font=("Segoe UI", 10), text_color="#2A2A4A").pack(side="left")
        lic_row = ctk.CTkFrame(f1, fg_color="transparent")
        lic_row.pack(fill="x", padx=20, pady=(0, 4))
        self._license_entry = ctk.CTkEntry(
            lic_row, width=180, height=36,
            font=("Consolas", 11), fg_color="#0D0C25",
            border_color="#1F1F1F", border_width=1, text_color="#FFFFFF",
            placeholder_text="vc-xxxxxxxxxxxx-xxxxxxxxxxxx")
        self._license_entry.pack(side="left")
        ctk.CTkButton(lic_row, text="Validar", width=76, height=36,
                      corner_radius=6, fg_color="#6B2FF8", hover_color="#5A28D6",
                      font=("Segoe UI", 11, "bold"),
                      command=self._validate_license).pack(side="left", padx=(6, 0))
        ctk.CTkButton(lic_row, text="Pular", width=76, height=36,
                      corner_radius=6, fg_color="transparent", hover_color="#1A1A2A",
                      border_color="#2A2A3A", border_width=1,
                      font=("Segoe UI", 11), text_color="#808080",
                      command=self._skip_license).pack(side="left", padx=(6, 0))
        self._license_status = ctk.CTkLabel(f1, text="Grátis — sem chave",
                                            font=("Segoe UI", 11), text_color="#4A4A6A")
        self._license_status.pack(anchor="w", padx=20)
        ctk.CTkLabel(f1, text="Comprar em: voice.jplabs.ai",
                     font=("Segoe UI", 10), text_color="#2A2A4A").pack(
            anchor="w", padx=20, pady=(2, 12))

        # Gemini API
        f2 = ctk.CTkFrame(scroll, fg_color="#0D0C25", corner_radius=12)
        f2.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(f2, text="GEMINI API KEY",
                     font=("Segoe UI", 10, "bold"), text_color="#4A4A6A").pack(
            anchor="w", padx=20, pady=(12, 4))
        ctk.CTkLabel(f2, text="Obter grátis em: aistudio.google.com/apikey",
                     font=("Segoe UI", 10), text_color="#4A4A6A").pack(
            anchor="w", padx=20, pady=(0, 4))
        gem_row = ctk.CTkFrame(f2, fg_color="transparent")
        gem_row.pack(fill="x", padx=20, pady=(0, 4))
        self._gemini_entry = ctk.CTkEntry(
            gem_row, width=240, height=36, show="*",
            font=("Consolas", 11), fg_color="#0D0C25",
            border_color="#1F1F1F", border_width=1, text_color="#FFFFFF",
            placeholder_text="AIza...")
        self._gemini_entry.pack(side="left")
        ctk.CTkButton(gem_row, text="Testar", width=80, height=36,
                      corner_radius=6, fg_color="#6B2FF8", hover_color="#5A28D6",
                      font=("Segoe UI", 12, "bold"),
                      command=self._test_gemini).pack(side="left", padx=(8, 0))
        self._gemini_status = ctk.CTkLabel(f2, text="Cole sua chave — só valida o formato, sem chamar a API",
                                           font=("Segoe UI", 10), text_color="#4A4A6A")
        self._gemini_status.pack(anchor="w", padx=20)
        # Bind: habilita botão ao digitar a key (sem precisar testar)
        self._gemini_entry.bind("<KeyRelease>", lambda e: self._on_gemini_type())
        ctk.CTkFrame(f2, height=12, fg_color="transparent").pack()

        # Footer
        ffoot = ctk.CTkFrame(scroll, fg_color="transparent")
        ffoot.pack(fill="x", padx=16, pady=(0, 16))
        self._start_btn = ctk.CTkButton(
            ffoot, text="Começar a usar", width=352, height=42,
            corner_radius=8, fg_color="#1A1A2A", hover_color="#1A1A2A",
            font=("Segoe UI", 13, "bold"), text_color="#4A4A6A",
            state="disabled", command=self._finish)
        self._start_btn.pack(pady=12)

        # Auto-size — janela responsiva, usuário pode redimensionar
        self._root.update_idletasks()
        req_h = self._root.winfo_reqheight() + 16
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        # Limita a altura inicial à tela disponível (para monitores pequenos)
        init_h = min(req_h, sh - 80)
        x = (sw - 384) // 2
        y = max((sh - init_h) // 2, 0)
        self._root.geometry(f"384x{init_h}+{x}+{y}")
        # Tamanho mínimo: largura 320px (conteúdo não quebra), altura dinâmica
        self._root.minsize(320, min(req_h, 400))
        self._root.resizable(True, True)

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
        self._update_start_btn()

    def _skip_license(self):
        """Pular licença — usar gratuitamente."""
        self._license_entry.delete(0, "end")
        self._license_ok = True
        self._license_status.configure(text="Grátis — sem chave", text_color="#4A4A6A")
        self._update_start_btn()

    def _on_gemini_type(self):
        """Habilita 'Começar a usar' assim que há texto na key — sem depender do teste."""
        has_text = bool(self._gemini_entry.get().strip())
        if has_text and not self._gemini_ok:
            self._gemini_status.configure(
                text="Clique Testar para verificar (opcional)", text_color="#4A4A6A")
            self._gemini_ok = True  # aceitar sem teste obrigatório
            self._update_start_btn()

    def _test_gemini(self):
        api_key = self._gemini_entry.get().strip()
        if not api_key:
            self._gemini_status.configure(text="Insira a chave primeiro", text_color="#FF3366")
            return
        self._gemini_status.configure(text="Testando...", text_color="#FFAA00")

        def _do_test():
            ok, msg = _test_gemini_key(api_key)

            def _update():
                if ok:
                    self._gemini_status.configure(text=f"✓ {msg}", text_color="#22C55E")
                else:
                    # Teste falhou, mas não bloqueia — key pode ainda funcionar
                    self._gemini_status.configure(
                        text=f"Aviso: {msg[:60]}", text_color="#FF6B35")
                self._gemini_ok = True  # key digitada = aceita em qualquer caso
                self._update_start_btn()

            try:
                self._root.after(0, _update)
            except Exception:
                pass

        threading.Thread(target=_do_test, daemon=True).start()

    def _update_start_btn(self):
        # Licença é opcional — só Gemini é obrigatória
        if self._gemini_ok:
            self._start_btn.configure(
                state="normal", fg_color="#6B2FF8", hover_color="#5A28D6",
                text_color="#FFFFFF")
        else:
            self._start_btn.configure(
                state="disabled", fg_color="#1A1A2A", hover_color="#1A1A2A",
                text_color="#4A4A6A")

    def _finish(self):
        """Salva as chaves, grava sentinel e fecha o wizard."""
        license_key = self._license_entry.get().strip()
        gemini_key = self._gemini_entry.get().strip()
        _save_env({"LICENSE_KEY": license_key, "GEMINI_API_KEY": gemini_key})
        if self._done_callback is not None:
            self._done_callback()
        self._root.destroy()
        self._root = None

    def _on_close(self):
        """Fechar sem completar encerra o app."""
        import os as _os
        _os._exit(0)


class SettingsWindow:
    """Mini janela de configurações — Flat Dark Premium design (JP Labs DNA)."""

    MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]
    LANGUAGES = ["auto-detect", "pt", "en"]

    def __init__(self):
        self._root = None
        self._scroll = None  # CTkScrollableFrame — container de todo o conteúdo
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

    def open(self):
        """Abre a janela em thread daemon. Singleton — foca se já aberta."""
        with state._settings_window_lock:
            existing = state._settings_window_ref
            if existing is not None:
                try:
                    existing._root.lift()
                    existing._root.focus_force()
                    return
                except Exception:
                    pass  # janela foi fechada, criar nova
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
        self._root.title("Voice Commander — Configurações")
        self._root.attributes("-topmost", True)
        self._root.configure(fg_color="#01010D")
        _icon = _resource_path("icon.ico")
        if _icon.exists():
            self._root.iconbitmap(str(_icon))
            _apply_taskbar_icon(self._root, _icon)

        # Container scrollável — permite rolar em monitores pequenos
        self._scroll = ctk.CTkScrollableFrame(
            self._root, fg_color="transparent",
            scrollbar_button_color="#2A2A3A",
            scrollbar_button_hover_color="#3A3A5A",
        )
        self._scroll.pack(fill="both", expand=True)

        self._build_header()
        self._build_status()
        self._build_commands()
        self._build_settings()
        self._build_footer()
        self._refresh_status()

        # Auto-size: janela ajusta à altura real do conteúdo — responsiva
        self._root.update_idletasks()
        req_h = self._root.winfo_reqheight() + 16
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        # Limita a altura inicial à tela disponível (para monitores pequenos)
        init_h = min(req_h, sh - 80)
        x = (sw - 384) // 2
        y = max((sh - init_h) // 2, 0)
        self._root.geometry(f"384x{init_h}+{x}+{y}")
        # Tamanho mínimo: largura 320px (conteúdo não quebra), altura dinâmica
        self._root.minsize(320, min(req_h, 400))
        self._root.resizable(True, True)

    def _card(self) -> "ctk.CTkFrame":
        f = ctk.CTkFrame(self._scroll, fg_color="#0D0C25", corner_radius=12)
        f.pack(fill="x", padx=16, pady=(0, 8))
        return f

    def _section_title(self, parent, text: str) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(12, 8))
        ctk.CTkFrame(row, height=1, fg_color="#2A2A3A", corner_radius=0).pack(
            side="left", fill="x", expand=True, pady=9)
        ctk.CTkLabel(row, text=f"  {text}  ",
                     font=("Segoe UI", 10, "bold"), text_color="#4A4A6A").pack(side="left")
        ctk.CTkFrame(row, height=1, fg_color="#2A2A3A", corner_radius=0).pack(
            side="left", fill="x", expand=True, pady=9)

    def _build_header(self):
        h = ctk.CTkFrame(self._scroll, fg_color="transparent")
        h.pack(fill="x", padx=16, pady=(20, 8))
        ctk.CTkLabel(h, text="Voice Commander",
                     font=("Segoe UI", 20, "bold"), text_color="#FFFFFF").pack(anchor="w")
        ctk.CTkLabel(h, text=f"v{__version__}",
                     font=("Segoe UI", 12), text_color="#808080").pack(anchor="w")
        # Separador sutil abaixo do header
        ctk.CTkFrame(self._scroll, height=1, fg_color="#2A2A3A", corner_radius=0).pack(
            fill="x", padx=16, pady=(0, 8))

    def _build_status(self):
        f = self._card()
        row1 = ctk.CTkFrame(f, fg_color="transparent")
        row1.pack(fill="x", padx=20, pady=(16, 2))
        self._dot = ctk.CTkLabel(row1, text="●", font=("Segoe UI", 14), text_color="#808080")
        self._dot.pack(side="left")
        self._state_label = ctk.CTkLabel(row1, text="Idle",
                                         font=("Segoe UI", 13, "bold"), text_color="#FFFFFF")
        self._state_label.pack(side="left", padx=(8, 0))
        row2 = ctk.CTkFrame(f, fg_color="transparent")
        row2.pack(fill="x", padx=20, pady=(0, 16))
        model_name = state._CONFIG.get("WHISPER_MODEL", "small")
        gemini_ok = bool(state._GEMINI_API_KEY)
        ctk.CTkLabel(row2, text=f"Whisper: {model_name}",
                     font=("Segoe UI", 11), text_color="#808080").pack(side="left")
        ctk.CTkLabel(row2, text="  |  ",
                     font=("Segoe UI", 11), text_color="#2A2A3A").pack(side="left")
        ctk.CTkLabel(row2, text=f"Gemini: {'on' if gemini_ok else 'off'}",
                     font=("Segoe UI", 11),
                     text_color="#22C55E" if gemini_ok else "#808080").pack(side="left")

    def _build_commands(self):
        f = self._card()
        self._section_title(f, "ATALHOS")
        hotkeys = [
            ("Ctrl+Shift+Space",    "Transcrição pura"),
            ("Ctrl+Alt+Space",      "Prompt simples"),
            ("Ctrl+CapsLock+Space", "Prompt COSTAR"),
            (state._CONFIG.get("QUERY_HOTKEY", "ctrl+shift+alt+space").title(), "Query Gemini"),
        ]
        for i, (key, desc) in enumerate(hotkeys):
            ctk.CTkLabel(f, text=key,
                         font=("Consolas", 12, "bold"), text_color="#FFFFFF", anchor="w").pack(
                fill="x", padx=20, pady=(8, 0))
            ctk.CTkLabel(f, text=desc,
                         font=("Segoe UI", 11), text_color="#808080", anchor="w").pack(
                fill="x", padx=20, pady=(2, 0))
            # Separador fino entre hotkeys (não após o último)
            if i < len(hotkeys) - 1:
                ctk.CTkFrame(f, height=1, fg_color="#1A1A2A", corner_radius=0).pack(
                    fill="x", padx=20, pady=(8, 0))
        # Padding bottom
        ctk.CTkFrame(f, height=12, fg_color="transparent").pack()

    def _build_settings(self):
        f = self._card()
        self._section_title(f, "CONFIGURAÇÕES")

        # Modelo Whisper
        ctk.CTkLabel(f, text="Modelo Whisper",
                     font=("Segoe UI", 12), text_color="#B3B3B3").pack(anchor="w", padx=20, pady=(8, 2))
        cur_model = state._CONFIG.get("WHISPER_MODEL", "small")
        self._model_var = ctk.StringVar(value=cur_model if cur_model in self.MODELS else "small")
        ctk.CTkOptionMenu(f, variable=self._model_var, values=self.MODELS,
                          width=312, height=36, corner_radius=6,
                          fg_color="#0D0C25", button_color="#6B2FF8",
                          button_hover_color="#5A28D6", text_color="#FFFFFF").pack(padx=20)

        # Idioma Whisper
        ctk.CTkLabel(f, text="Idioma de transcrição",
                     font=("Segoe UI", 12), text_color="#B3B3B3").pack(anchor="w", padx=20, pady=(8, 2))
        raw_lang = state._CONFIG.get("WHISPER_LANGUAGE", "") or "auto-detect"
        lang_val = raw_lang if raw_lang in self.LANGUAGES else "auto-detect"
        self._lang_var = ctk.StringVar(value=lang_val)
        ctk.CTkOptionMenu(f, variable=self._lang_var, values=self.LANGUAGES,
                          width=312, height=36, corner_radius=6,
                          fg_color="#0D0C25", button_color="#6B2FF8",
                          button_hover_color="#5A28D6", text_color="#FFFFFF").pack(padx=20)

        # Chave de Licença
        ctk.CTkLabel(f, text="Chave de Licença",
                     font=("Segoe UI", 12), text_color="#B3B3B3").pack(anchor="w", padx=20, pady=(8, 2))
        lic_row = ctk.CTkFrame(f, fg_color="transparent")
        lic_row.pack(fill="x", padx=20, pady=(0, 4))
        self._license_entry = ctk.CTkEntry(lic_row, width=268, height=36,
                                           font=("Consolas", 11), fg_color="#0D0C25",
                                           border_color="#1F1F1F", border_width=1,
                                           text_color="#FFFFFF",
                                           placeholder_text="vc-xxxxxxxxxxxx-xxxxxxxxxxxx")
        self._license_entry.pack(side="left")
        ctk.CTkButton(lic_row, text="✓", width=36, height=36,
                      fg_color="#0D0C25", hover_color="#170433",
                      border_color="#1F1F1F", border_width=1, corner_radius=6,
                      command=self._check_license).pack(side="left", padx=(8, 0))
        cur_lic = state._CONFIG.get("LICENSE_KEY") or ""
        if cur_lic:
            self._license_entry.insert(0, cur_lic)
        self._license_status_label = ctk.CTkLabel(f, text="",
                                                  font=("Segoe UI", 11), text_color="#808080")
        self._license_status_label.pack(anchor="w", padx=20, pady=(0, 4))
        self._refresh_license_status()

        # Gemini API Key
        ctk.CTkLabel(f, text="Gemini API Key",
                     font=("Segoe UI", 12), text_color="#B3B3B3").pack(anchor="w", padx=20, pady=(8, 2))
        key_row = ctk.CTkFrame(f, fg_color="transparent")
        key_row.pack(fill="x", padx=20, pady=(0, 16))
        self._api_entry = ctk.CTkEntry(key_row, width=268, height=36, show="*",
                                       font=("Consolas", 12), fg_color="#0D0C25",
                                       border_color="#1F1F1F", border_width=1,
                                       text_color="#FFFFFF",
                                       placeholder_text="sua chave Gemini...")
        self._api_entry.pack(side="left")
        if state._GEMINI_API_KEY:
            self._api_entry.insert(0, state._GEMINI_API_KEY)
        self._eye_btn = ctk.CTkButton(key_row, text="👁", width=36, height=36,
                                      fg_color="#0D0C25", hover_color="#170433",
                                      border_color="#1F1F1F", border_width=1, corner_radius=6,
                                      command=self._toggle_key_visibility)
        self._eye_btn.pack(side="left", padx=(8, 0))

    def _build_footer(self):
        f = ctk.CTkFrame(self._scroll, fg_color="transparent")
        f.pack(fill="x", padx=16, pady=(0, 16))
        self._save_btn = ctk.CTkButton(f, text="Salvar", width=172, height=42,
                                       corner_radius=8, fg_color="#6B2FF8",
                                       hover_color="#5A28D6",
                                       font=("Segoe UI", 13, "bold"),
                                       command=self._save)
        self._save_btn.pack(side="left", pady=12)
        ctk.CTkButton(f, text="Fechar", width=172, height=42, corner_radius=8,
                      fg_color="transparent", border_color="#1F1F1F", border_width=1,
                      hover_color="#170433", font=("Segoe UI", 13), text_color="#B3B3B3",
                      command=self._root.destroy).pack(side="left", padx=(8, 0), pady=12)

    def _toggle_key_visibility(self):
        self._show_key = not self._show_key
        self._api_entry.configure(show="" if self._show_key else "*")

    def _check_license(self):
        """Botão ✓ na linha da licença — valida e mostra status."""
        key = self._license_entry.get().strip() if self._license_entry else ""
        self._show_license_result(key)

    def _refresh_license_status(self):
        """Mostra status atual da licença carregada no .env."""
        key = state._CONFIG.get("LICENSE_KEY") or ""
        self._show_license_result(key)

    def _show_license_result(self, key: str):
        if not self._license_status_label:
            return
        if not key:
            self._license_status_label.configure(text="Não configurada", text_color="#808080")
            return
        valid, msg = validate_license_key(key)
        if valid:
            self._license_status_label.configure(text=f"✓ {msg}", text_color="#22C55E")
        else:
            expired = "Expirada" in msg
            color = "#FF6B35" if expired else "#FF3366"
            suffix = "  Renovar → voice.jplabs.ai" if expired else ""
            self._license_status_label.configure(text=f"✗ {msg}{suffix}", text_color=color)

    def _save(self):
        model_val = self._model_var.get()
        lang_val = self._lang_var.get()
        api_key = self._api_entry.get().strip()
        license_key = self._license_entry.get().strip() if self._license_entry else ""
        new_values: dict = {
            "WHISPER_MODEL": model_val,
            "WHISPER_LANGUAGE": "" if lang_val == "auto-detect" else lang_val,
        }
        if api_key:
            new_values["GEMINI_API_KEY"] = api_key
        if license_key:
            new_values["LICENSE_KEY"] = license_key
        _save_env(new_values)
        _reload_config()
        self._refresh_license_status()
        self._save_btn.configure(text="Salvo!", fg_color="#22C55E", hover_color="#16A34A")
        self._root.after(1500, lambda: self._save_btn.configure(
            text="Salvar", fg_color="#6B2FF8", hover_color="#5A28D6"))

    def _refresh_status(self):
        if self._root is None:
            return
        try:
            state_map = {
                "idle":       ("●", "#808080", "Idle"),
                "recording":  ("●", "#FF3366", "Gravando"),
                "processing": ("●", "#FFAA00", "Processando"),
            }
            dot_text, dot_color, state_text = state_map.get(
                state._tray_state, ("●", "#808080", state._tray_state))
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
