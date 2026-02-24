#!/usr/bin/env python3
"""
Voice-to-text v2  |  JP Labs
Ctrl+Shift+Space        = gravar / parar  →  transcrição pura (PT+EN bilíngue)
Ctrl+Alt+Space          = gravar / parar  →  prompt simples (bullet points)
Ctrl+CapsLock+Space     = gravar / parar  →  prompt estruturado COSTAR via Gemini
Ctrl+Shift+Alt+Space    = gravar / parar  →  query direta Gemini (resposta imediata)

Proteções contra garbling:
- Named mutex (Windows): mata instância anterior automaticamente
- Paste via ctypes.SendInput: bypass total da lib keyboard (zero re-entrada)
- suppress=False nos hotkeys: evita latência em Ctrl/Shift/Alt globais
  (suppress=True causava delay perceptível em Ctrl+C, Ctrl+V, Shift+seta, etc.)
- _toggle_lock: evita dois ciclos paralelos dentro da mesma instância
- current_mode salvo ao INICIAR gravação (não ao parar)
"""

import os
import sys
import pathlib
import glob
import json
import builtins
import datetime
import threading
import time
import tempfile
import wave
import ctypes
import ctypes.wintypes
import hmac
import hashlib
import base64

# ---------------------------------------------------------------------------
# Caminhos base
# ---------------------------------------------------------------------------
if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "VoiceCommander")
    os.makedirs(_BASE_DIR, exist_ok=True)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_log_path = os.path.join(_BASE_DIR, "voice.log")
_history_path = os.path.join(_BASE_DIR, "history.jsonl")

# ---------------------------------------------------------------------------
# License — validação HMAC local (sem servidor)
# ---------------------------------------------------------------------------
_LICENSE_EXPIRED_NOTIFIED: bool = False
# Obfuscated secret (evita extração por grep no .exe)
_K = [ord(c) ^ 0x42 for c in "jp-labs-vc-secret-2026"]


def _get_secret() -> str:
    return "".join(chr(c ^ 0x42) for c in _K)

# Reconfigurar stdout/stderr para UTF-8 (evita UnicodeEncodeError com ═, etc.)
# Quando rodando via pythonw.exe, stdout/stderr são None — tratar gracefully
if sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr is not None:
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_orig_print = builtins.print

def _log_print(*args, **kwargs):
    msg = " ".join(str(a) for a in args)
    # Só chama _orig_print se stdout existir (pythonw não tem console)
    if sys.stdout is not None:
        try:
            _orig_print(*args, **kwargs)
        except Exception:
            pass
    try:
        with open(_log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass

builtins.print = _log_print

# ---------------------------------------------------------------------------
# Imports que podem falhar (logamos o erro)
# ---------------------------------------------------------------------------
try:
    import sounddevice as sd
    import numpy as np
    import winsound
    import keyboard
except Exception as _e:
    print(f"[ERRO IMPORT] {_e}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Named mutex — instância única garantida pelo SO
# ---------------------------------------------------------------------------
_MUTEX_NAME = "Global\\VoiceJPLabs_SingleInstance"
_mutex_handle = None


def _acquire_named_mutex():
    global _mutex_handle
    _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    last_error = ctypes.windll.kernel32.GetLastError()
    ERROR_ALREADY_EXISTS = 183
    if last_error == ERROR_ALREADY_EXISTS:
        print("[ERRO] Outra instância do voice.py já está rodando.")
        sys.exit(1)
    print(f"[OK]   Mutex adquirido (PID {os.getpid()})")


def _release_named_mutex():
    global _mutex_handle
    if _mutex_handle:
        ctypes.windll.kernel32.ReleaseMutex(_mutex_handle)
        ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        _mutex_handle = None


# ---------------------------------------------------------------------------
# Configuração — carregada uma vez no startup
# ---------------------------------------------------------------------------
_CONFIG: dict = {}
_GEMINI_API_KEY: str | None = None

_DEFAULT_QUERY_SYSTEM_PROMPT = (
    "Você é um assistente direto e preciso. "
    "Responda à pergunta do usuário de forma clara, concisa e útil. "
    "Vá direto ao ponto sem rodeios desnecessários. "
    "O texto pode misturar português e inglês — responda no mesmo idioma da pergunta."
)


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


def load_config() -> dict:
    """Carrega todas as configurações do .env uma vez no startup."""
    env_path = os.path.join(_BASE_DIR, ".env")
    config: dict = {
        "GEMINI_API_KEY": None,
        "LICENSE_KEY": None,
        "WHISPER_MODEL": "small",
        "WHISPER_LANGUAGE": "",
        "MAX_RECORD_SECONDS": 120,
        "AUDIO_DEVICE_INDEX": None,
        "QUERY_HOTKEY": "ctrl+shift+alt+space",
        "QUERY_SYSTEM_PROMPT": "",
        "HISTORY_MAX_ENTRIES": 500,
        "LOG_KEEP_SESSIONS": 5,
    }
    if not os.path.exists(env_path):
        return config
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" not in line or line.startswith("#"):
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key in config and val:
                if key in ("MAX_RECORD_SECONDS", "HISTORY_MAX_ENTRIES", "LOG_KEEP_SESSIONS"):
                    try:
                        config[key] = int(val)
                    except ValueError:
                        pass
                elif key == "AUDIO_DEVICE_INDEX":
                    try:
                        config[key] = int(val)
                    except ValueError:
                        pass
                else:
                    config[key] = val
    # Filtrar placeholder
    if config["GEMINI_API_KEY"] == "your_gemini_api_key_here":
        config["GEMINI_API_KEY"] = None
    return config


# ---------------------------------------------------------------------------
# License — validate_license_key, _test_gemini_key, notificação
# ---------------------------------------------------------------------------
def validate_license_key(key: str) -> tuple[bool, str]:
    """Valida chave de licença via HMAC local (sem servidor necessário)."""
    try:
        parts = key.strip().split("-", 2)  # ["vc", expiry_b64, sig]
        if len(parts) != 3 or parts[0] != "vc":
            return False, "Formato inválido"
        expiry_b64, sig = parts[1], parts[2]
        expiry = base64.urlsafe_b64decode(expiry_b64 + "==").decode()
        expected_sig = hmac.new(_get_secret().encode(), expiry.encode(), hashlib.sha256).hexdigest()[:12]
        if not hmac.compare_digest(sig, expected_sig):
            return False, "Chave inválida"
        expiry_date = datetime.date.fromisoformat(expiry)
        if datetime.date.today() > expiry_date:
            return False, f"Expirada em {expiry}"
        return True, f"Válida até {expiry}"
    except Exception:
        return False, "Chave inválida"


def _test_gemini_key(api_key: str) -> tuple[bool, str]:
    """Valida formato da chave Gemini sem fazer chamada à API.

    Não consumimos quota no setup — a chave é validada de verdade
    na primeira transcrição real. Formato AI Studio: AIza + ~35 chars.
    """
    key = api_key.strip()
    if not key:
        return False, "Chave vazia"
    if not key.startswith("AIza"):
        return False, "Formato inválido — chave deve começar com 'AIza'"
    if len(key) < 30:
        return False, "Chave muito curta — verifique se copiou completo"
    if len(key) > 60:
        return False, "Chave muito longa — verifique se há espaços extras"
    return True, "Formato OK"


def _show_license_expired_notification() -> None:
    """Notifica licença expirada via tray balloon — não bloqueia o teclado."""
    # Tray balloon: aparece e some, sem modal, sem travar Ctrl+V
    if _tray_icon is not None and _tray_available:
        try:
            _tray_icon.notify(
                "Licença expirada — renove em voice.jplabs.ai",
                "Voice Commander",
            )
            return
        except Exception:
            pass
    # Fallback: só loga, não abre dialog bloqueante
    print("[WARN] Licença expirada — renove em voice.jplabs.ai")


# ---------------------------------------------------------------------------
# Story 3.2 — Rotação de log por sessão
# ---------------------------------------------------------------------------
def _rotate_log() -> None:
    """
    Renomeia voice.log atual → voice.YYYY-MM-DD_HH-MM-SS.log (se existir).
    Mantém apenas LOG_KEEP_SESSIONS arquivos de sessão (os mais recentes por mtime).
    Silencioso — erros são ignorados; o log será registrado após abertura do novo arquivo.
    """
    keep = _CONFIG.get("LOG_KEEP_SESSIONS", 5)

    # Renomear log atual se existir
    if os.path.exists(_log_path):
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        archived = os.path.join(_BASE_DIR, f"voice.{ts}.log")
        try:
            os.rename(_log_path, archived)
        except Exception:
            pass

    # Listar e ordenar sessões arquivadas por mtime (mais recente primeiro)
    pattern = os.path.join(_BASE_DIR, "voice.????-??-??_??-??-??.log")
    session_logs = glob.glob(pattern)
    if session_logs:
        session_logs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        # Deletar as sessões além do limite
        for old_log in session_logs[keep:]:
            try:
                os.remove(old_log)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Story 3.1 — Histórico de transcrições (history.jsonl)
# ---------------------------------------------------------------------------
def _append_history(
    mode: str,
    raw_text: str,
    processed_text: str | None,
    duration_seconds: float,
    error: bool = False,
) -> None:
    """
    Acrescenta uma entrada ao history.jsonl (append-only).
    Faz trim automático se o número de entradas ultrapassar HISTORY_MAX_ENTRIES.
    """
    max_entries = _CONFIG.get("HISTORY_MAX_ENTRIES", 500)

    entry: dict = {
        "timestamp": datetime.datetime.now().isoformat(),
        "mode": mode,
        "raw_text": raw_text,
        "processed_text": processed_text,
        "duration_seconds": round(duration_seconds, 2),
        "chars": len(processed_text) if processed_text else 0,
    }
    if error:
        entry["error"] = True
        entry["processed_text"] = None

    try:
        # Append da nova entrada
        with open(_history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Trim: manter apenas as max_entries mais recentes
        with open(_history_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if len(lines) > max_entries:
            lines = lines[-max_entries:]
            with open(_history_path, "w", encoding="utf-8") as f:
                f.writelines(lines)

    except Exception as e:
        print(f"[WARN] Falha ao salvar histórico: {e}")


# ---------------------------------------------------------------------------
# Story 3.3 — Graceful shutdown
# ---------------------------------------------------------------------------
def graceful_shutdown() -> None:
    """
    Encerramento seguro quando chamado via Ctrl+C ou menu tray "Encerrar".
    - Se gravando: sinaliza stop, aguarda thread de gravação (até 5s)
    - Se frames capturados: tenta transcrever e colar (timeout 10s)
    - Mutex liberado em qualquer cenário (try/finally)
    - Thread-safe via _toggle_lock para leitura de is_recording
    """
    global is_recording, is_transcribing, frames_buf, record_thread

    try:
        # Verificar se está gravando (com lock para thread-safety)
        recording_now = False
        captured_frames: list = []
        captured_mode = "transcribe"

        with _toggle_lock:
            recording_now = is_recording
            if recording_now:
                captured_frames = list(frames_buf)
                captured_mode = current_mode
                is_recording = False

        if recording_now:
            print("[INFO] Shutdown com gravação ativa — sinalizando stop...")
            stop_event.set()

            # Aguardar thread de gravação encerrar (até 5s)
            if record_thread is not None and record_thread.is_alive():
                record_thread.join(timeout=5)
                # Capturar frames acumulados após join
                with _toggle_lock:
                    captured_frames = list(frames_buf)

            if captured_frames:
                print("[INFO] Frames capturados — tentando transcrever antes de encerrar...")
                done_event = threading.Event()
                transcribe_error: list = []

                def _shutdown_transcribe():
                    try:
                        transcribe(captured_frames, captured_mode)
                    except Exception as exc:
                        transcribe_error.append(str(exc))
                    finally:
                        done_event.set()

                t = threading.Thread(target=_shutdown_transcribe, daemon=True)
                t.start()
                finished = done_event.wait(timeout=10)

                if not finished:
                    print("[WARN] Shutdown forçado — transcrição abortada")
                else:
                    if transcribe_error:
                        print(f"[WARN] Erro na transcrição de shutdown: {transcribe_error[0]}")
                    else:
                        print("[OK]   Transcrição de shutdown concluída")
            else:
                print("[INFO] Nenhum frame capturado — shutdown sem transcrição")
        else:
            # Não estava gravando, apenas sinalizar stop por segurança
            stop_event.set()

        print("[OK]   Shutdown gracioso concluído")

    finally:
        # Garantir liberação do mutex em qualquer cenário
        _release_named_mutex()


# ---------------------------------------------------------------------------
# Configuração de áudio
# ---------------------------------------------------------------------------
SAMPLE_RATE     = 16000
CHANNELS        = 1
stop_event      = threading.Event()
is_recording    = False
is_transcribing = False
frames_buf      = []
record_thread   = None
_toggle_lock    = threading.Lock()
current_mode    = "transcribe"  # "transcribe" | "simple" | "prompt" | "query"

# ---------------------------------------------------------------------------
# Story 2.1 — System Tray (pystray + Pillow)
# ---------------------------------------------------------------------------
_tray_icon = None
_tray_available = False
_tray_state = "idle"        # "idle" | "recording" | "processing"
_tray_last_mode = "—"

# Tentar importar pystray e Pillow — fallback silencioso se não disponíveis
try:
    import pystray
    from PIL import Image, ImageDraw
    _tray_available = True
except ImportError:
    print("[WARN] pystray/Pillow não instalados — system tray desativado. "
          "Instale com: pip install pystray Pillow")


def _make_tray_icon(state: str = "idle") -> "Image.Image":
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
    color = color_map.get(state, "#808080")
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
    label = state_labels.get(_tray_state, _tray_state)
    return f"Voice Commander | {label} | Último: {_tray_last_mode}"


def _update_tray_state(state: str, mode: str | None = None) -> None:
    """Atualiza ícone e tooltip da system tray."""
    global _tray_state, _tray_last_mode
    _tray_state = state
    if mode is not None:
        _tray_last_mode = mode
    if _tray_icon is not None and _tray_available:
        try:
            _tray_icon.icon = _make_tray_icon(state)
            _tray_icon.title = _tray_tooltip()
        except Exception as e:
            print(f"[WARN] Falha ao atualizar ícone da tray: {e}")


def _tray_show_status(icon, item) -> None:  # type: ignore[type-arg]
    """Menu item 'Status' — abre popup CTk (ou MessageBox fallback) com info atual."""
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
    gemini_status = "Ativo" if _GEMINI_API_KEY else "Desativado"
    state_label = state_labels.get(_tray_state, _tray_state)
    mode_label  = mode_labels.get(_tray_last_mode, _tray_last_mode)

    if _ctk_available:
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
                _icon = pathlib.Path(__file__).parent / "build" / "icon.ico"
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
                    ("Whisper",      _CONFIG.get("WHISPER_MODEL", "small")),
                    ("Log",          _log_path),
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
            f"Whisper:     {_CONFIG.get('WHISPER_MODEL', 'small')}\n"
            f"Log:         {_log_path}"
        )
        ctypes.windll.user32.MessageBoxW(0, msg, "Voice Commander — Status", 0x40)


def _tray_on_quit(icon, item) -> None:  # type: ignore[type-arg]
    """Menu item 'Encerrar' — shutdown gracioso."""
    print("[INFO] Encerramento solicitado via system tray.")
    try:
        icon.stop()
    except Exception:
        pass
    graceful_shutdown()
    os._exit(0)


def _start_tray() -> None:
    """Inicia system tray em thread daemon. Fallback silencioso se pystray indisponível."""
    global _tray_icon

    if not _tray_available:
        return

    try:
        menu = pystray.Menu(
            pystray.MenuItem("⚙ Configurações", lambda icon, item: _open_settings()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Status", _tray_show_status),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Encerrar", _tray_on_quit),
        )
        _tray_icon = pystray.Icon(
            name="VoiceCommander",
            icon=_make_tray_icon("idle"),
            title=_tray_tooltip(),
            menu=menu,
        )

        def _run_tray():
            try:
                _tray_icon.run()
            except Exception as e:
                print(f"[WARN] System tray encerrada inesperadamente: {e}")

        t = threading.Thread(target=_run_tray, daemon=True)
        t.start()
        print("[OK]   System tray iniciada")
    except Exception as e:
        print(f"[WARN] Falha ao iniciar system tray: {e}")


def _stop_tray() -> None:
    """Remove ícone da tray corretamente (sem fantasma)."""
    global _tray_icon
    if _tray_icon is not None and _tray_available:
        try:
            _tray_icon.stop()
        except Exception:
            pass
        _tray_icon = None


# ---------------------------------------------------------------------------
# Onboarding Window — wizard 2 passos (bloqueante, modal)
# ---------------------------------------------------------------------------
# _ctk_available e ctk definidos logo abaixo — OnboardingWindow só é
# instanciada após aquele bloco executar, então a referência é segura.


class OnboardingWindow:
    """Wizard de configuração inicial — 2 passos obrigatórios."""

    def __init__(self):
        self._root = None
        self._license_entry = None
        self._license_status = None
        self._gemini_entry = None
        self._gemini_status = None
        self._start_btn = None
        self._license_ok = False
        self._gemini_ok = False

    def run(self) -> None:
        """Abre wizard bloqueante. Retorna quando usuário completa os 2 passos."""
        if not _ctk_available:
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
        _icon = pathlib.Path(__file__).parent / "build" / "icon.ico"
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
        _mark_onboarding_done()
        self._root.destroy()
        self._root = None

    def _on_close(self):
        """Fechar sem completar encerra o app."""
        os._exit(0)


def _run_onboarding() -> None:
    """Abre wizard de configuração inicial (bloqueante)."""
    OnboardingWindow().run()


# ---------------------------------------------------------------------------
# Settings Window (CustomTkinter — Deep Glass design)
# ---------------------------------------------------------------------------
_ctk_available = False
_settings_window_ref = None
_settings_window_lock = threading.Lock()

try:
    import customtkinter as ctk
    _ctk_available = True
except ImportError:
    print("[WARN] customtkinter não instalado — janela de configurações desativada. "
          "Instale com: pip install customtkinter==5.2.2")


def _reload_config() -> None:
    """Recarrega _CONFIG e _GEMINI_API_KEY do .env sem restart."""
    global _CONFIG, _GEMINI_API_KEY, _whisper_model
    old_model = _CONFIG.get("WHISPER_MODEL", "small")
    _CONFIG = load_config()
    _GEMINI_API_KEY = _CONFIG.get("GEMINI_API_KEY")
    new_model = _CONFIG.get("WHISPER_MODEL", "small")
    if new_model != old_model:
        _whisper_model = None  # forçar reload no próximo uso
        print(f"[INFO] Modelo Whisper mudou: {old_model} → {new_model} (reload no próximo uso)")
    print("[OK]   Config recarregada do .env")


def _save_env(new_values: dict) -> None:
    """Reescreve o .env preservando comentários, apenas atualizando os keys fornecidos."""
    env_path = os.path.join(_BASE_DIR, ".env")
    example_path = os.path.join(_BASE_DIR, ".env.example")
    source = env_path if os.path.exists(env_path) else example_path
    lines = []
    if os.path.exists(source):
        with open(source, "r", encoding="utf-8") as f:
            lines = f.readlines()
    updated: set = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in new_values:
                new_lines.append(f"{key}={new_values[key]}\n")
                updated.add(key)
                continue
        new_lines.append(line)
    for key, val in new_values.items():
        if key not in updated:
            new_lines.append(f"{key}={val}\n")
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


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
        global _settings_window_ref
        with _settings_window_lock:
            existing = _settings_window_ref
            if existing is not None:
                try:
                    existing._root.lift()
                    existing._root.focus_force()
                    return
                except Exception:
                    pass  # janela foi fechada, criar nova
            _settings_window_ref = self
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def _run(self):
        global _settings_window_ref
        try:
            self._build()
            self._root.mainloop()
        except Exception as e:
            print(f"[WARN] SettingsWindow encerrada: {e}")
        finally:
            with _settings_window_lock:
                if _settings_window_ref is self:
                    _settings_window_ref = None

    def _build(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self._root = ctk.CTk()
        self._root.title("Voice Commander — Configurações")
        self._root.attributes("-topmost", True)
        self._root.configure(fg_color="#01010D")
        _icon = pathlib.Path(__file__).parent / "build" / "icon.ico"
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
        ctk.CTkLabel(h, text="v1.3",
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
        model_name = _CONFIG.get("WHISPER_MODEL", "small")
        gemini_ok = bool(_GEMINI_API_KEY)
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
            (_CONFIG.get("QUERY_HOTKEY", "ctrl+shift+alt+space").title(), "Query Gemini"),
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
        cur_model = _CONFIG.get("WHISPER_MODEL", "small")
        self._model_var = ctk.StringVar(value=cur_model if cur_model in self.MODELS else "small")
        ctk.CTkOptionMenu(f, variable=self._model_var, values=self.MODELS,
                          width=312, height=36, corner_radius=6,
                          fg_color="#0D0C25", button_color="#6B2FF8",
                          button_hover_color="#5A28D6", text_color="#FFFFFF").pack(padx=20)

        # Idioma Whisper
        ctk.CTkLabel(f, text="Idioma de transcrição",
                     font=("Segoe UI", 12), text_color="#B3B3B3").pack(anchor="w", padx=20, pady=(8, 2))
        raw_lang = _CONFIG.get("WHISPER_LANGUAGE", "") or "auto-detect"
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
        cur_lic = _CONFIG.get("LICENSE_KEY") or ""
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
        if _GEMINI_API_KEY:
            self._api_entry.insert(0, _GEMINI_API_KEY)
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
        key = _CONFIG.get("LICENSE_KEY") or ""
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
                _tray_state, ("●", "#808080", _tray_state))
            self._dot.configure(text=dot_text, text_color=dot_color)
            self._state_label.configure(text=state_text)
            self._root.after(1000, self._refresh_status)
        except Exception:
            pass


def _open_settings() -> None:
    """Abre janela de Settings (singleton — foca se já aberta)."""
    if not _ctk_available:
        ctypes.windll.user32.MessageBoxW(
            0,
            "customtkinter não instalado.\nInstale com: pip install customtkinter==5.2.2",
            "Voice Commander — Configurações",
            0x40,
        )
        return
    SettingsWindow().open()


# ---------------------------------------------------------------------------
# Whisper — lazy load
# ---------------------------------------------------------------------------
_whisper_model = None


def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        model_name = _CONFIG.get("WHISPER_MODEL", "small")
        print(f"[...] Carregando Whisper {model_name} (primeira vez — pode demorar ~30s)...")
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
        print("[OK]  Whisper pronto (PT+EN bilíngue)")
    return _whisper_model


# ---------------------------------------------------------------------------
# Gemini helpers
# ---------------------------------------------------------------------------
def load_gemini_key() -> str | None:
    """Mantido para compatibilidade. No startup, use _GEMINI_API_KEY global."""
    return _CONFIG.get("GEMINI_API_KEY")


def _is_rate_limit(e: Exception) -> bool:
    """Detecta erro 429 / RESOURCE_EXHAUSTED do Gemini."""
    msg = str(e).lower()
    return "429" in msg or "resource_exhausted" in msg or "exhausted" in msg or "quota" in msg


def _rate_limit_msg() -> str:
    return (
        "[LIMITE ATINGIDO] Gemini free tier: máx 15 req/min.\n"
        "Aguarde 1 minuto e use o atalho novamente."
    )


def correct_with_gemini(text: str) -> str:
    if not _GEMINI_API_KEY:
        return text
    try:
        from google import genai
        client = genai.Client(api_key=_GEMINI_API_KEY)
        prompt = (
            "Você é um corretor MINIMALISTA de transcrição de voz para texto.\n"
            "REGRAS ABSOLUTAS:\n"
            "- NÃO traduza nada. Se a palavra está em inglês, deixe em inglês.\n"
            "- NÃO mude o sentido ou reorganize frases.\n"
            "- NÃO expanda abreviações ou siglas.\n"
            "- Preserve code-switching (mistura PT+EN) exatamente como está.\n"
            "- Em caso de dúvida, preserve o texto original.\n"
            "- Retorne APENAS o texto corrigido, sem explicações.\n\n"
            f"Texto: {text}"
        )
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        corrected = response.text.strip()
        if corrected:
            print(f"[OK]   Original : {text}")
            print(f"[OK]   Corrigido: {corrected}")
            return corrected
    except Exception as e:
        if _is_rate_limit(e):
            print("[WARN] Gemini: rate limit 429 — aguardar 1 min")
            return _rate_limit_msg()
        print(f"[WARN] Gemini indisponível ({e}), usando texto original")
    return text


def simplify_as_prompt(text: str) -> str:
    """
    Organiza a transcrição em prompt limpo com bullet points — sem XML, sem COSTAR.
    Fidelidade total ao input: nenhum detalhe omitido, output proporcional à riqueza do input.
    """
    if not _GEMINI_API_KEY:
        return text

    word_count = len(text.split())
    print(f"[...]  Input: {word_count} palavras → modo prompt simples (fidelidade total)")

    meta_prompt = f"""Você é especialista em prompt engineering.
O texto abaixo é transcrição de voz informal (pode misturar PT e EN).
Transforme-o em um prompt limpo e direto para usar em qualquer LLM.

PRIORIDADE ABSOLUTA: Preservar CADA detalhe, contexto e nuance que o usuário mencionou.
Não comprima, não resuma, não omita nenhuma informação do input.
Se o input for longo e detalhado, o output também deve ser longo e detalhado.

ESTRUTURA:
1. Um ou mais parágrafos explicando o contexto e o que se quer — sem label, só texto corrido
2. Requisitos, detalhes específicos ou etapas listados como bullet points logo abaixo

REGRAS:
- Sem XML, sem seções SYSTEM/USER, sem headers, sem labels como "Contexto:" ou "Objetivo:"
- Os bullet points devem ser frases completas, não palavras soltas
- Preserve a intenção original completamente — não invente nem omita nada do input
- A quantidade de linhas e bullets deve ser proporcional à riqueza do input
- Retorne APENAS o prompt, sem explicações adicionais

Transcrição: {text}"""

    try:
        from google import genai
        client = genai.Client(api_key=_GEMINI_API_KEY)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=meta_prompt,
            config=genai.types.GenerateContentConfig(temperature=0.1),
        )
        simplified = response.text.strip()
        if simplified:
            print(f"[OK]   Prompt simplificado ({len(simplified)} chars)")
            return simplified
    except Exception as e:
        if _is_rate_limit(e):
            print("[WARN] Gemini: rate limit 429 — aguardar 1 min")
            return _rate_limit_msg()
        print(f"[WARN] Gemini indisponível ({e}), retornando texto original")
    return text


def structure_as_prompt(text: str) -> str:
    if not _GEMINI_API_KEY:
        print("[WARN] Gemini sem chave — retornando texto original")
        return text

    meta_prompt = f"""Você é especialista em prompt engineering para LLMs (Claude, GPT-4, Gemini).
O texto abaixo é transcrição de voz informal (pode misturar PT e EN).
Transforme-o em prompt estruturado profissional usando o framework COSTAR com XML tags.

Siga EXATAMENTE este formato (substitua os colchetes pelo conteúdo):

═══════════════════════════════════════
SYSTEM PROMPT
═══════════════════════════════════════
<role>
[Papel e persona ideal para executar esta tarefa]
</role>

<behavior>
[2-4 diretrizes comportamentais específicas e relevantes]
</behavior>

<output_format>
[Formato exato do output: markdown, JSON, lista, prosa, etc.]
</output_format>

═══════════════════════════════════════
USER PROMPT
═══════════════════════════════════════
<context>
[Background, situação atual, dados relevantes]
</context>

<objective>
[Tarefa específica e clara — o que exatamente deve ser feito]
</objective>

<style_and_tone>
[Estilo de escrita, tom (formal/direto/técnico) e audiência-alvo]
</style_and_tone>

<response>
[Formato e constraints da resposta: tamanho, idioma, estrutura]
</response>

REGRAS:
- Infira o papel ideal com base na natureza da tarefa
- Seja específico em todas as seções (nunca deixe vago)
- Preserve a intenção original do usuário
- Retorne APENAS o prompt estruturado, sem explicações adicionais

Transcrição: {text}"""

    try:
        from google import genai
        client = genai.Client(api_key=_GEMINI_API_KEY)
        response = client.models.generate_content(model="gemini-2.0-flash", contents=meta_prompt)
        structured = response.text.strip()
        if structured:
            print(f"[OK]   Prompt estruturado ({len(structured)} chars)")
            return structured
    except Exception as e:
        if _is_rate_limit(e):
            print("[WARN] Gemini: rate limit 429 — aguardar 1 min")
            return _rate_limit_msg()
        print(f"[WARN] Gemini indisponível ({e}), retornando texto original")
    return text


# ---------------------------------------------------------------------------
# Story 2.2 — Modo 4: Query Direta Gemini
# ---------------------------------------------------------------------------
def query_with_gemini(text: str) -> str:
    """
    Envia a transcrição diretamente ao Gemini como pergunta/query e retorna a resposta.
    Fallback sem Gemini: retorna texto original com prefixo informativo.
    """
    if not _GEMINI_API_KEY:
        print("[WARN] Gemini sem chave — retornando transcrição com prefixo")
        return f"[SEM RESPOSTA GEMINI] {text}"

    system_prompt = _CONFIG.get("QUERY_SYSTEM_PROMPT", "").strip()
    if not system_prompt:
        system_prompt = _DEFAULT_QUERY_SYSTEM_PROMPT

    print(f"[...]  Query Gemini ({len(text)} chars)...")

    try:
        from google import genai
        client = genai.Client(api_key=_GEMINI_API_KEY)

        # Combina system prompt + query do usuário em um único contents
        full_prompt = f"{system_prompt}\n\n{text}"

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=full_prompt,
            config=genai.types.GenerateContentConfig(temperature=0.3),
        )
        answer = response.text.strip()
        if answer:
            print(f"[OK]   Resposta Gemini ({len(answer)} chars)")
            return answer
    except Exception as e:
        if _is_rate_limit(e):
            print("[WARN] Gemini: rate limit 429 — aguardar 1 min")
            return _rate_limit_msg()
        print(f"[WARN] Gemini indisponível ({e}), retornando transcrição com prefixo")

    return f"[SEM RESPOSTA GEMINI] {text}"


# ---------------------------------------------------------------------------
# Clipboard + Paste
# ---------------------------------------------------------------------------
def copy_to_clipboard(text: str) -> None:
    import subprocess
    proc = subprocess.Popen('clip', stdin=subprocess.PIPE, shell=True)
    proc.communicate(input=text.encode('utf-16le'))
    proc.wait()


def paste_via_sendinput() -> None:
    INPUT_KEYBOARD  = 1
    KEYEVENTF_KEYUP = 0x0002

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk",         ctypes.wintypes.WORD),
            ("wScan",       ctypes.wintypes.WORD),
            ("dwFlags",     ctypes.wintypes.DWORD),
            ("time",        ctypes.wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.wintypes.DWORD), ("union", INPUT_UNION)]

    VK_CONTROL = 0x11
    VK_V       = 0x56

    inputs = (INPUT * 4)(
        INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=VK_CONTROL, dwFlags=0))),
        INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=VK_V,       dwFlags=0))),
        INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=VK_V,       dwFlags=KEYEVENTF_KEYUP))),
        INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=VK_CONTROL, dwFlags=KEYEVENTF_KEYUP))),
    )
    ctypes.windll.user32.SendInput(4, inputs, ctypes.sizeof(INPUT))


# ---------------------------------------------------------------------------
# Gravação
# ---------------------------------------------------------------------------
def record() -> list:
    frames = []
    stop_event.clear()
    max_seconds = _CONFIG.get("MAX_RECORD_SECONDS", 120)
    max_frames = int(max_seconds * SAMPLE_RATE / 1024)
    warn_frames = int((max_seconds - 5) * SAMPLE_RATE / 1024)  # aviso 5s antes
    frame_count = 0

    device_index = _CONFIG.get("AUDIO_DEVICE_INDEX")

    try:
        stream_kwargs: dict = {
            "samplerate": SAMPLE_RATE,
            "channels": CHANNELS,
            "dtype": "float32",
        }
        if device_index is not None:
            stream_kwargs["device"] = device_index

        with sd.InputStream(**stream_kwargs) as stream:
            while not stop_event.is_set():
                data, _ = stream.read(1024)
                frames.append(data.copy())
                frame_count += 1

                if frame_count == warn_frames:
                    winsound.Beep(600, 200)  # bip de aviso 5s antes (frequência distinta)
                    print(f"[WARN] Gravação encerra em 5s (limite: {max_seconds}s)")

                if frame_count >= max_frames:
                    print(f"[WARN] Timeout de gravação atingido ({max_seconds}s)")
                    stop_event.set()
                    break

    except Exception as e:
        print(f"[ERRO gravação] {e}")
    return frames


# ---------------------------------------------------------------------------
# Transcrição + pós-processamento
# ---------------------------------------------------------------------------
def transcribe(frames: list, mode: str = "transcribe") -> None:
    global is_transcribing
    t_start = time.time()

    if not frames:
        print("[ERRO]  Sem áudio\n")
        winsound.Beep(200, 300)
        is_transcribing = False
        _update_tray_state("idle")
        _append_history(mode, "", None, 0.0, error=True)
        return

    # Atualizar tray para "processando"
    _update_tray_state("processing", mode)

    print("[...]  Transcrevendo (Whisper)...")
    audio_data = np.concatenate(frames, axis=0)
    temp_path = None

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        temp_path = f.name

    try:
        with wave.open(temp_path, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes((audio_data * 32767).astype(np.int16).tobytes())

        model = get_whisper_model()
        lang_hint = _CONFIG.get("WHISPER_LANGUAGE") or None
        segments, _ = model.transcribe(
            temp_path,
            language=lang_hint,
            task="transcribe",
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            initial_prompt="Transcrição bilíngue em português brasileiro e inglês.",
        )
        raw_text = " ".join(s.text for s in segments).strip()

        if not raw_text:
            print("[ERRO]  Não entendi. Tente novamente.\n")
            winsound.Beep(200, 300)
            duration = time.time() - t_start
            _append_history(mode, "", None, duration, error=True)
            return

        print(f"[OK]   Whisper: {raw_text}")

        if mode == "prompt":
            print("[...]  Estruturando prompt (COSTAR)...")
            text = structure_as_prompt(raw_text)
        elif mode == "simple":
            print("[...]  Simplificando prompt...")
            text = simplify_as_prompt(raw_text)
        elif mode == "query":
            print("[...]  Consultando Gemini (query direta)...")
            text = query_with_gemini(raw_text)
        else:
            print("[...]  Corrigindo...")
            text = correct_with_gemini(raw_text)

        copy_to_clipboard(text)
        print(f"[OK]   Texto no clipboard ({len(text)} chars)")

        winsound.Beep(440, 100)
        winsound.Beep(440, 100)

        time.sleep(0.5)
        paste_via_sendinput()

        print("[OK]   Colado!\n")

        # Story 3.1 — Registrar no histórico (sucesso)
        duration = time.time() - t_start
        _append_history(mode, raw_text, text, duration)

    except Exception as e:
        print(f"[ERRO]  {e}\n")
        winsound.Beep(200, 300)
        # Story 3.1 — Registrar no histórico (erro)
        duration = time.time() - t_start
        _append_history(mode, "", None, duration, error=True)
    finally:
        is_transcribing = False
        if temp_path:
            try:
                os.unlink(temp_path)
            except Exception:
                pass
        # Voltar tray para idle após finalizar
        _update_tray_state("idle")


# ---------------------------------------------------------------------------
# Toggle recording
# ---------------------------------------------------------------------------
def toggle_recording(mode: str = "transcribe") -> None:
    global is_recording, is_transcribing, frames_buf, record_thread, current_mode

    with _toggle_lock:
        if is_transcribing:
            print("[SKIP] Aguardando transcrição anterior terminar...\n")
            winsound.Beep(300, 150)
            return

        if not is_recording:
            current_mode = mode
            is_recording = True
            frames_buf = []
            stop_event.clear()

            # Atualizar tray para "gravando"
            _update_tray_state("recording", mode)

            if mode == "transcribe":
                winsound.Beep(880, 200)
                print("[REC]  Gravando... (Ctrl+Shift+Space para parar)\n")
            elif mode == "simple":
                winsound.Beep(880, 150)
                time.sleep(0.05)
                winsound.Beep(880, 150)
                time.sleep(0.05)
                winsound.Beep(880, 150)
                print("[REC]  Gravando para PROMPT SIMPLES... (Ctrl+Alt+Space para parar)\n")
            elif mode == "query":
                # Bip distinto: 1 longo (880Hz 400ms) + 1 curto (1100Hz 150ms)
                winsound.Beep(880, 400)
                time.sleep(0.05)
                winsound.Beep(1100, 150)
                print("[REC]  Gravando para QUERY GEMINI... (mesmo hotkey para parar)\n")
            else:
                winsound.Beep(880, 150)
                time.sleep(0.05)
                winsound.Beep(880, 150)
                print("[REC]  Gravando para PROMPT COSTAR... (Ctrl+CapsLock+Space para parar)\n")

            def do_record():
                global frames_buf
                frames_buf = record()

            record_thread = threading.Thread(target=do_record, daemon=True)
            record_thread.start()
        else:
            is_recording = False
            is_transcribing = True
            stop_event.set()
            print("[STOP] Parando gravação...\n")
            if record_thread:
                record_thread.join(timeout=3)
            threading.Thread(
                target=transcribe,
                args=(list(frames_buf), current_mode),
                daemon=True,
            ).start()


# ---------------------------------------------------------------------------
# Hotkeys
# ---------------------------------------------------------------------------
def on_hotkey(mode: str = "transcribe") -> None:
    threading.Thread(target=toggle_recording, args=(mode,), daemon=True).start()


# ---------------------------------------------------------------------------
# Story 2.3 — Validação de microfone no startup
# ---------------------------------------------------------------------------
def validate_microphone() -> None:
    """
    Testa o sd.InputStream com o dispositivo configurado.
    Timeout: 3 segundos via thread com join(timeout=3).
    App continua mesmo se a validação falhar.
    """
    device_index = _CONFIG.get("AUDIO_DEVICE_INDEX")
    device_display = str(device_index) if device_index is not None else "padrão"

    mic_ok_flag = [False]
    mic_error: list = []

    def _test_mic():
        try:
            stream_kwargs: dict = {
                "samplerate": SAMPLE_RATE,
                "channels": CHANNELS,
                "dtype": "float32",
            }
            if device_index is not None:
                stream_kwargs["device"] = device_index

            with sd.InputStream(**stream_kwargs) as stream:
                stream.read(64)  # Leitura mínima para confirmar abertura
            mic_ok_flag[0] = True
        except Exception as e:
            mic_error.append(str(e))

    t = threading.Thread(target=_test_mic, daemon=True)
    t.start()
    t.join(timeout=3)

    if mic_ok_flag[0]:
        print(f"[OK]   Microfone validado (dispositivo: {device_display})")
    else:
        error_detail = mic_error[0] if mic_error else "timeout"
        print(
            f"[WARN] Microfone não acessível (dispositivo: {device_display}) "
            f"— verifique permissões de áudio ({error_detail})"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def _license_check_loop() -> None:
    """Background thread — verifica expiração da licença a cada 60s.
    Só notifica se o usuário TEM uma licença e ela expirou.
    Free mode (sem chave) nunca dispara notificação.
    """
    global _LICENSE_EXPIRED_NOTIFIED
    while True:
        time.sleep(60)
        key = _CONFIG.get("LICENSE_KEY", "") or ""
        if not key:
            continue  # free mode — sem chave, sem notificação
        valid, _ = validate_license_key(key)
        if not valid and not _LICENSE_EXPIRED_NOTIFIED:
            _show_license_expired_notification()
            _LICENSE_EXPIRED_NOTIFIED = True


def _needs_onboarding() -> bool:
    """
    Retorna True se o onboarding deve ser exibido.

    Critérios (qualquer um é suficiente):
    1. Nenhum .env existe ainda (primeira execução real)
    2. .env existe mas GEMINI_API_KEY não está configurada
    3. Arquivo sentinel .onboarding_done NÃO existe
       — garante que o onboarding seja exibido mesmo se o .env foi
         criado externamente sem a chave, ou se o usuário fechou o
         wizard antes de completar.
    """
    env_path      = os.path.join(_BASE_DIR, ".env")
    sentinel_path = os.path.join(_BASE_DIR, ".onboarding_done")

    # Sem sentinel → nunca completou o onboarding
    if not os.path.exists(sentinel_path):
        return True

    # Completou antes mas a chave sumiu (ex: usuário editou .env manualmente)
    if not _CONFIG.get("GEMINI_API_KEY"):
        return True

    return False


def _mark_onboarding_done() -> None:
    """Cria arquivo sentinel indicando que o onboarding foi concluído com sucesso."""
    sentinel_path = os.path.join(_BASE_DIR, ".onboarding_done")
    try:
        with open(sentinel_path, "w", encoding="utf-8") as f:
            f.write(datetime.datetime.now().isoformat() + "\n")
    except Exception:
        pass


def main() -> None:
    global _CONFIG, _GEMINI_API_KEY

    # Faz o Windows tratar o processo como "VoiceCommander" no taskbar
    # (sem isso, agrupa pelo executável pythonw.exe e mostra ícone do Python)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("VoiceCommander.App")
    except Exception:
        pass

    # Carrega configurações uma vez (antes da rotação para ter LOG_KEEP_SESSIONS)
    _CONFIG = load_config()
    _GEMINI_API_KEY = _CONFIG.get("GEMINI_API_KEY")

    # Primeira execução — abre wizard de setup se necessário.
    # Licença é opcional (free tier disponível).
    if _needs_onboarding():
        _run_onboarding()
        # Recarregar config após wizard completar
        _CONFIG = load_config()
        _GEMINI_API_KEY = _CONFIG.get("GEMINI_API_KEY")

    # Story 3.2 — Rotação de log (antes de abrir novo log)
    _rotate_log()

    # Abre novo log da sessão
    try:
        with open(_log_path, "w", encoding="utf-8") as f:
            f.write(f"=== voice.py iniciado {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    except Exception:
        pass

    # Log de startup
    gemini_ok = _GEMINI_API_KEY is not None
    key_display = f"***{_GEMINI_API_KEY[-4:]}" if gemini_ok else "não configurada"
    device_display = str(_CONFIG["AUDIO_DEVICE_INDEX"]) if _CONFIG["AUDIO_DEVICE_INDEX"] is not None else "padrão do sistema"
    query_hotkey = _CONFIG.get("QUERY_HOTKEY", "ctrl+shift+alt+space")
    _lic_valid, _lic_msg = validate_license_key(_CONFIG.get("LICENSE_KEY", "") or "")

    print("═" * 54)
    print("  Voice-to-text v2  |  JP Labs")
    print("═" * 54)
    print("  [Ctrl+Shift+Space]          Transcrição pura")
    print("  [Ctrl+Alt+Space]            Prompt simples (bullet points)")
    print("  [Ctrl+CapsLock+Space]       Prompt estruturado (COSTAR)")
    print(f"  [{query_hotkey.title()}]  Query direta Gemini")
    print("  Idiomas : PT-BR + EN (automático)")
    print(f"  Gemini  : {'ativo (' + key_display + ')' if gemini_ok else 'desativado (sem .env)'}")
    print(f"  Licença : {_lic_msg}")
    print(f"  Whisper : {_CONFIG['WHISPER_MODEL']}")
    print(f"  Timeout : {_CONFIG['MAX_RECORD_SECONDS']}s")
    print(f"  Mic     : {device_display}")
    print("  Sair    : Ctrl+C (ou menu System Tray > Encerrar)")
    print("═" * 54 + "\n")

    _acquire_named_mutex()

    # Story 2.3 — Validar microfone após adquirir mutex
    validate_microphone()

    # Story 2.1 — Iniciar system tray (thread daemon, fallback silencioso)
    _start_tray()

    # Iniciar verificação periódica de expiração de licença (daemon)
    threading.Thread(target=_license_check_loop, daemon=True).start()

    # Loop de resiliência: se keyboard.wait() retornar inesperadamente
    # (exception não capturada, sinal externo, etc.), os hotkeys são
    # re-registrados e o loop recomeça. Ctrl+C encerra limpo.
    _restart_count = 0
    while True:
        # Limpa hotkeys anteriores antes de re-registrar (evita duplicatas no restart)
        try:
            keyboard.unhook_all()
        except Exception:
            pass

        try:
            # suppress=False: sem latência em Ctrl/Shift/Alt globais.
            # O Space que "vaza" para a aplicação ativa é inofensivo na prática.
            keyboard.add_hotkey("ctrl+shift+space",     lambda: on_hotkey("transcribe"), suppress=False)
            keyboard.add_hotkey("ctrl+alt+space",       lambda: on_hotkey("simple"),     suppress=False)
            keyboard.add_hotkey("ctrl+caps lock+space", lambda: on_hotkey("prompt"),     suppress=False)
            keyboard.add_hotkey(
                _CONFIG.get("QUERY_HOTKEY", "ctrl+shift+alt+space"),
                lambda: on_hotkey("query"),
                suppress=False,
            )

            if _restart_count == 0:
                print("[OK]   Hotkeys registrados. Aguardando...\n")
            else:
                print(f"[OK]   Hotkeys re-registrados (restart #{_restart_count}). Aguardando...\n")

            keyboard.wait()

            # keyboard.wait() retornou sem exceção — significa saída limpa (ex: Ctrl+C capturado
            # internamente pela lib). Encerrar.
            break

        except KeyboardInterrupt:
            # Ctrl+C explícito — saída intencional
            break

        except Exception as e:
            _restart_count += 1
            print(f"[ERRO] Loop de hotkeys crashou: {e}")
            print(f"[INFO] Reiniciando hotkeys em 3s (tentativa #{_restart_count})...\n")
            time.sleep(3)
            continue  # Reinicia o while

    # Story 3.3 — Shutdown gracioso (libera mutex internamente)
    _stop_tray()
    graceful_shutdown()
    print("\nSaindo...")


if __name__ == "__main__":
    main()
