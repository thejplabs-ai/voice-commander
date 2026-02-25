# voice/config.py — load_config(), _save_env(), _reload_config()

import os

from voice import state


def load_config() -> dict:
    """Carrega todas as configurações do .env uma vez no startup."""
    env_path = os.path.join(state._BASE_DIR, ".env")
    config: dict = {
        "GEMINI_API_KEY": None,
        "GEMINI_MODEL": "gemini-2.5-flash",
        "LICENSE_KEY": None,
        "WHISPER_MODEL": "small",
        "WHISPER_LANGUAGE": "",
        "MAX_RECORD_SECONDS": 120,
        "AUDIO_DEVICE_INDEX": None,
        "QUERY_HOTKEY": "ctrl+shift+alt+space",
        "QUERY_SYSTEM_PROMPT": "",
        "HISTORY_MAX_ENTRIES": 500,
        "LOG_KEEP_SESSIONS": 5,
        "VAD_THRESHOLD": 0.3,
        # Mode selection
        "SELECTED_MODE": "transcribe",
        "RECORD_HOTKEY": "ctrl+shift+space",
        # Wake word
        "WAKE_WORD_ENABLED": "false",
        "WAKE_WORD_KEYWORD": "hey_jarvis",
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
        # AI Provider
        "AI_PROVIDER": "gemini",
        "OPENAI_API_KEY": None,
        "OPENAI_MODEL": "gpt-4o-mini",
        # Translate
        "TRANSLATE_TARGET_LANG": "en",
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
                elif key == "VAD_THRESHOLD":
                    try:
                        config[key] = float(val)
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


def _save_env(new_values: dict) -> None:
    """Reescreve o .env preservando comentários, apenas atualizando os keys fornecidos."""
    env_path = os.path.join(state._BASE_DIR, ".env")
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
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def _reload_config() -> None:
    """Recarrega _CONFIG e _GEMINI_API_KEY do .env sem restart."""
    old_key = state._GEMINI_API_KEY
    old_model = state._CONFIG.get("WHISPER_MODEL", "small")
    old_device = state._CONFIG.get("WHISPER_DEVICE", "cpu")
    old_provider = state._CONFIG.get("AI_PROVIDER", "gemini")
    old_openai_key = state._CONFIG.get("OPENAI_API_KEY")

    state._CONFIG = load_config()
    state._GEMINI_API_KEY = state._CONFIG.get("GEMINI_API_KEY")
    state.selected_mode = state._CONFIG.get("SELECTED_MODE", "transcribe")

    new_model = state._CONFIG.get("WHISPER_MODEL", "small")
    new_device = state._CONFIG.get("WHISPER_DEVICE", "cpu")
    if new_model != old_model or new_device != old_device:
        state._whisper_model = None
        state._whisper_cache_key = ()
        print(f"[INFO] Whisper config mudou — reload no próximo uso")

    if state._GEMINI_API_KEY != old_key:
        state._gemini_client = None
        print("[INFO] API key Gemini mudou — singleton resetado")

    new_provider = state._CONFIG.get("AI_PROVIDER", "gemini")
    new_openai_key = state._CONFIG.get("OPENAI_API_KEY")
    if new_provider != old_provider or new_openai_key != old_openai_key:
        state._openai_client = None
        state._OPENAI_API_KEY = new_openai_key
        print("[INFO] AI provider/OpenAI key mudou — singleton resetado")

    print("[OK]   Config recarregada do .env")
