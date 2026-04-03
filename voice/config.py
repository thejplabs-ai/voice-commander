# voice/config.py — load_config(), _save_env(), _reload_config(), license validation

import base64
import datetime
import hashlib
import hmac
import os

from voice import state


# ── License validation (migrado de license.py) ────────────────────────────────

# Obfuscated secret (evita extração por grep no .exe)
_K = [ord(c) ^ 0x42 for c in "jp-labs-vc-secret-2026"]


def _get_secret() -> str:
    return "".join(chr(c ^ 0x42) for c in _K)


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
    if state._tray_icon is not None and state._tray_available:
        try:
            state._tray_icon.notify(
                "Licença expirada — renove em voice.jplabs.ai",
                "Voice Commander",
            )
            return
        except Exception:
            pass
    # Fallback: só loga, não abre dialog bloqueante
    print("[WARN] Licença expirada — renove em voice.jplabs.ai")


def load_config() -> dict:
    """Carrega todas as configurações do .env uma vez no startup."""
    env_path = os.path.join(state._BASE_DIR, ".env")
    config: dict = {
        "GEMINI_API_KEY": None,
        "GEMINI_MODEL": "gemini-2.5-flash",
        "LICENSE_KEY": None,
        "WHISPER_MODEL": "tiny",
        "WHISPER_LANGUAGE": "",
        "MAX_RECORD_SECONDS": 120,
        "AUDIO_DEVICE_INDEX": None,
        "QUERY_SYSTEM_PROMPT": "",
        "HISTORY_MAX_ENTRIES": 500,
        "LOG_KEEP_SESSIONS": 5,
        "VAD_THRESHOLD": 0.3,
        # Mode selection
        "SELECTED_MODE": "transcribe",
        "RECORD_HOTKEY": "ctrl+shift+space",
        # Custom sounds (empty = use default beeps)
        "SOUND_START": "",
        "SOUND_SUCCESS": "",
        "SOUND_ERROR": "",
        "SOUND_WARNING": "",
        "SOUND_SKIP": "",
        # Performance
        "WHISPER_DEVICE": "cpu",
        "WHISPER_MODEL_FAST": "tiny",
        "WHISPER_MODEL_QUALITY": "small",
        # AI Provider — OpenRouter (gateway unico, recomendado)
        "OPENROUTER_API_KEY": None,
        "OPENROUTER_MODEL_FAST": "meta-llama/llama-4-scout-17b-16e-instruct",
        "OPENROUTER_MODEL_QUALITY": "google/gemini-2.5-flash",
        # Legacy providers (fallback se OPENROUTER_API_KEY nao configurada)
        "OPENAI_API_KEY": None,
        "OPENAI_MODEL": "gpt-4o-mini",
        # Translate
        "TRANSLATE_TARGET_LANG": "en",
        # Whisper initial prompt — vazio usa o padrão PT-BR + termos EN
        "WHISPER_INITIAL_PROMPT": "",
        # STT Provider — "whisper" (local, offline) | "gemini" (cloud, melhor PT-BR)
        "STT_PROVIDER": "whisper",
        # Gemini correction — "true" (default) | "false" (bypass, retorna raw Whisper)
        "GEMINI_CORRECT": "true",
        # QW-4: Whisper beam size — 1 (rápido) a 10 (mais preciso) | default: 1
        "WHISPER_BEAM_SIZE": 1,
        # QW-4: Delay adicional antes de colar (ms) — ajustar se o paste falha em apps lentos
        "PASTE_DELAY_MS": 50,
        # Story 4.5.3: Hotkey de ciclo de modo
        "CYCLE_HOTKEY": "ctrl+shift+tab",
        # Story 4.5.4: Clipboard Context
        "CLIPBOARD_CONTEXT_ENABLED": "true",
        "CLIPBOARD_CONTEXT_MAX_CHARS": 2000,
        # Story 4.5.5: Hotkey para abrir busca no histórico
        "HISTORY_HOTKEY": "ctrl+shift+h",
        # Story 4.5.1: Overlay de feedback visual
        "OVERLAY_ENABLED": "true",
        # Story 4.6.4: Ciclo de modos
        "CYCLE_MODES": "transcribe,email,simple,prompt,query",
        # Story 4.6.6: Debug de performance — imprime [PERF] após cada transcrição
        "DEBUG_PERF": "false",
    }
    if os.path.exists(env_path):
        _load_env_file(config, env_path)

    # Filtrar placeholder
    if config["GEMINI_API_KEY"] == "your_gemini_api_key_here":
        config["GEMINI_API_KEY"] = None

    # Converter configs booleanas de string para bool nativo
    _BOOL_KEYS = (
        "OVERLAY_ENABLED", "CLIPBOARD_CONTEXT_ENABLED",
        "GEMINI_CORRECT", "DEBUG_PERF",
    )
    for key in _BOOL_KEYS:
        val = config.get(key)
        if isinstance(val, bool):
            continue
        config[key] = str(val).strip().lower() in ("true", "1", "yes")

    return config


def _load_env_file(config: dict, env_path: str) -> None:
    """Carrega variáveis do .env no dict config."""
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" not in line or line.startswith("#"):
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key in config and val:
                if key in ("MAX_RECORD_SECONDS", "HISTORY_MAX_ENTRIES", "LOG_KEEP_SESSIONS",
                           "WHISPER_BEAM_SIZE", "PASTE_DELAY_MS", "CLIPBOARD_CONTEXT_MAX_CHARS"):
                    try:
                        config[key] = int(val)
                    except ValueError:
                        print(f"[WARN] Config {key}={val} nao e inteiro valido, usando default {config[key]}")
                elif key == "VAD_THRESHOLD":
                    try:
                        config[key] = float(val)
                    except ValueError:
                        print(f"[WARN] Config {key}={val} nao e float valido, usando default {config[key]}")
                elif key == "AUDIO_DEVICE_INDEX":
                    try:
                        config[key] = int(val)
                    except ValueError:
                        print(f"[WARN] Config {key}={val} nao e inteiro valido, ignorando")
                else:
                    config[key] = val


def _save_env(new_values: dict) -> None:
    """Reescreve o .env preservando comentários, apenas atualizando os keys fornecidos.

    Escreve em .env.tmp primeiro e usa os.replace() para atomicidade —
    evita corrupção do .env em caso de falha durante a escrita.
    """
    env_path = os.path.join(state._BASE_DIR, ".env")
    tmp_path = os.path.join(state._BASE_DIR, ".env.tmp")
    example_path = os.path.join(state._BASE_DIR, ".env.example")
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
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        os.replace(tmp_path, env_path)
    except Exception:
        # Limpar arquivo temporário em caso de falha
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def _reload_config() -> None:
    """Recarrega _CONFIG e _GEMINI_API_KEY do .env sem restart."""
    old_key = state._GEMINI_API_KEY
    old_model = state._CONFIG.get("WHISPER_MODEL", "tiny")
    old_device = state._CONFIG.get("WHISPER_DEVICE", "cpu")
    old_openai_key = state._CONFIG.get("OPENAI_API_KEY")

    state._CONFIG = load_config()
    state._GEMINI_API_KEY = state._CONFIG.get("GEMINI_API_KEY")
    state.selected_mode = state._CONFIG.get("SELECTED_MODE", "transcribe")

    new_model = state._CONFIG.get("WHISPER_MODEL", "tiny")
    new_device = state._CONFIG.get("WHISPER_DEVICE", "cpu")
    if new_model != old_model or new_device != old_device:
        state._whisper_model = None
        state._whisper_cache_key = ()
        print("[INFO] Whisper config mudou — reload no próximo uso")

    if state._GEMINI_API_KEY != old_key:
        state._gemini_client = None
        print("[INFO] API key Gemini mudou — singleton resetado")

    new_openai_key = state._CONFIG.get("OPENAI_API_KEY")
    if new_openai_key != old_openai_key:
        state._openai_client = None
        state._OPENAI_API_KEY = new_openai_key
        print("[INFO] OpenAI key mudou — singleton resetado")

    # OpenRouter singleton reset
    old_or_key = getattr(state, "_OPENROUTER_API_KEY", None)
    new_or_key = state._CONFIG.get("OPENROUTER_API_KEY")
    if new_or_key != old_or_key:
        try:
            from voice.openrouter import reset_client
            reset_client()
        except Exception:
            pass
        state._OPENROUTER_API_KEY = new_or_key
        print("[INFO] OpenRouter API key mudou — singleton resetado")

    print("[OK]   Config recarregada do .env")
