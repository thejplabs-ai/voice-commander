# voice/app.py — main(), _license_check_loop(), _needs_onboarding()

import ctypes
import datetime
import glob
import os
import tempfile
import threading
import time

from voice import state
from voice import hotkeys_win32
from voice import audio as _audio
from voice.config import load_config
from voice.config import validate_license_key, _show_license_expired_notification
from voice.logging_ import _rotate_log
from voice.mutex import _acquire_named_mutex
from voice.tray import _start_tray, _stop_tray
from voice.audio import on_hotkey, on_command_hotkey, validate_microphone, get_whisper_model
from voice.shutdown import graceful_shutdown


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
    sentinel_path = os.path.join(state._BASE_DIR, ".onboarding_done")

    # Sem sentinel → nunca completou o onboarding
    if not os.path.exists(sentinel_path):
        return True

    # Completou antes mas nenhuma chave de AI configurada
    has_ai_key = (
        state._CONFIG.get("GEMINI_API_KEY")
        or state._CONFIG.get("OPENROUTER_API_KEY")
    )
    if not has_ai_key:
        return True

    return False


def _mark_onboarding_done() -> None:
    """Cria arquivo sentinel indicando que o onboarding foi concluído com sucesso."""
    sentinel_path = os.path.join(state._BASE_DIR, ".onboarding_done")
    try:
        with open(sentinel_path, "w", encoding="utf-8") as f:
            f.write(datetime.datetime.now().isoformat() + "\n")
    except Exception as e:
        print(f"[WARN] Falha ao criar sentinel de onboarding: {e}")


def _run_onboarding() -> None:
    """Abre wizard de configuração inicial (bloqueante)."""
    from voice.webui import run_onboarding
    run_onboarding(done_callback=_mark_onboarding_done)


def _license_check_loop() -> None:
    """Background thread — verifica expiração da licença a cada 60s.
    Só notifica se o usuário TEM uma licença e ela expirou.
    Free mode (sem chave) nunca dispara notificação.
    """
    while True:
        time.sleep(60)
        key = state._CONFIG.get("LICENSE_KEY", "") or ""
        if not key:
            continue  # free mode — sem chave, sem notificação
        valid, _ = validate_license_key(key)
        if not valid and not state._LICENSE_EXPIRED_NOTIFIED:
            _show_license_expired_notification()
            state._LICENSE_EXPIRED_NOTIFIED = True


def _cleanup_temp_wavs() -> None:
    """W-02: Remove arquivos .wav temporários em tempfile.gettempdir() deixados por sessões anteriores.

    Critérios de seleção (todos devem ser atendidos):
    - Padrão: tmp*.wav  (prefixo padrão do tempfile do Python no Windows)
    - mtime > 1 hora    (evita deletar WAV em uso por outra sessão ativa)
    """
    tmp_dir = tempfile.gettempdir()
    pattern = os.path.join(tmp_dir, "tmp*.wav")
    wav_files = glob.glob(pattern)
    now = time.time()
    cutoff = 60 * 60  # 1 hora em segundos
    removed = 0
    for f in wav_files:
        try:
            if now - os.path.getmtime(f) > cutoff:
                os.remove(f)
                removed += 1
        except Exception:
            pass
    if removed > 0:
        print(f"[INFO] {removed} arquivo(s) temporário(s) removidos")


def _log_startup_info() -> None:
    """Imprime banner de inicialização com configurações atuais."""
    gemini_ok = state._GEMINI_API_KEY is not None
    key_display = f"***{state._GEMINI_API_KEY[-4:]}" if gemini_ok else "não configurada"
    device_display = (
        str(state._CONFIG["AUDIO_DEVICE_INDEX"])
        if state._CONFIG["AUDIO_DEVICE_INDEX"] is not None
        else "padrão do sistema"
    )
    record_hotkey = state._CONFIG.get("RECORD_HOTKEY", "ctrl+shift+space")
    _lic_valid, _lic_msg = validate_license_key(state._CONFIG.get("LICENSE_KEY", "") or "")

    print("═" * 54)
    print("  Voice Commander  |  Standalone")
    print("═" * 54)
    print(f"  [{record_hotkey.title()}]  Gravar (modo ativo: {state.selected_mode})")
    print("  Trocar modo : System Tray > Modo")
    print("  Idiomas     : PT-BR + EN (automático)")
    gemini_model = state._CONFIG.get("GEMINI_MODEL", "gemini-2.5-flash")
    or_key = state._CONFIG.get("OPENROUTER_API_KEY")
    if or_key:
        fast_or = state._CONFIG.get("OPENROUTER_MODEL_FAST", "gemini-3.1-flash-lite")
        qual_or = state._CONFIG.get("OPENROUTER_MODEL_QUALITY", "gemini-3.1-flash-lite")
        print(f"  AI      : OpenRouter (fast: {fast_or.split('/')[-1]} | quality: {qual_or.split('/')[-1]})")
    elif gemini_ok:
        print(f"  AI      : Gemini ({key_display}) [{gemini_model}]")
    else:
        print("  AI      : sem chave configurada")
    print(f"  Licença : {_lic_msg}")
    whisper_device = state._CONFIG.get("WHISPER_DEVICE", "cpu")
    beam_size = state._CONFIG.get("WHISPER_BEAM_SIZE", 1)
    paste_delay = state._CONFIG.get("PASTE_DELAY_MS", 50)
    fast_model = state._CONFIG.get("WHISPER_MODEL_FAST", "tiny")
    quality_model = state._CONFIG.get("WHISPER_MODEL_QUALITY", "small")
    if fast_model == quality_model:
        whisper_display = f"{fast_model} / {whisper_device} (beam={beam_size})"
    else:
        whisper_display = f"{fast_model} (fast) / {quality_model} (quality) / {whisper_device} (beam={beam_size})"
    print(f"  Whisper : {whisper_display}")
    print(f"  Timeout : {state._CONFIG['MAX_RECORD_SECONDS']}s")
    print(f"  Paste   : +{paste_delay}ms delay")
    print(f"  Mic     : {device_display}")
    print("  Sair    : Ctrl+C (ou menu System Tray > Encerrar)")
    print("═" * 54 + "\n")


def _cycle_mode() -> None:
    """Story 4.5.3/4.6.4: Cicla entre modos configurados em CYCLE_MODES."""
    from voice.tray import _set_mode, _update_tray_state
    from voice.audio import play_sound
    # Story 4.6.4: usar CYCLE_MODES do config (default: 5 modos, sem visual/pipeline)
    raw_cycle = state._CONFIG.get("CYCLE_MODES", "transcribe,email,simple,prompt,query")
    modes = [m.strip() for m in raw_cycle.split(",") if m.strip()]
    if not modes:
        modes = ["transcribe", "email", "simple", "prompt", "query"]
    current = state.selected_mode
    try:
        idx = modes.index(current)
    except ValueError:
        idx = 0
    next_idx = (idx + 1) % len(modes)
    next_mode = modes[next_idx]
    _set_mode(next_mode)
    _update_tray_state("idle")
    print(f"[INFO] Modo ciclado: {current} → {next_mode}")
    play_sound("skip")  # bip distinto ao ciclar
    # Story 4.6.2: overlay mostrando novo modo por 1.5s
    try:
        from voice import overlay as _overlay
        _overlay.show_mode_change(next_mode)
    except Exception:
        pass


def _hotkey_bindings() -> list:
    """bindings_provider passado a hotkeys_win32.start()/request_rebind().

    Lê state._CONFIG a cada (re)registro — defaults idênticos aos de
    voice/config.py:load_config(). Retorna [(config_key, combo, callback)].
    """
    from voice.history_search import open_history_search

    cfg = state._CONFIG
    return [
        ("RECORD_HOTKEY", cfg.get("RECORD_HOTKEY", "ctrl+shift+space"), on_hotkey),
        ("CYCLE_HOTKEY", cfg.get("CYCLE_HOTKEY", "ctrl+alt+m"), _cycle_mode),
        ("HISTORY_HOTKEY", cfg.get("HISTORY_HOTKEY", "ctrl+alt+h"), open_history_search),
        ("COMMAND_HOTKEY", cfg.get("COMMAND_HOTKEY", "ctrl+alt+space"), on_command_hotkey),
    ]


def _report_hotkey_failures(failures: list) -> None:
    """failure_reporter passado a hotkeys_win32.start() — chamado da thread do pump.

    Nunca silêncio: loga cada combo que falhou, bipa uma vez e notifica via
    tray quando disponível (precedente: voice/config.py:_show_license_expired_notification).
    """
    for config_key, combo, code in failures:
        print(f"[ERRO] Hotkey nao registrado: {config_key} ({combo}) — combo em uso por outro app? (win err {code})")

    _audio.play_sound("error")

    if state._tray_icon is not None and state._tray_available:
        combos = ", ".join(combo for _, combo, _ in failures)
        try:
            state._tray_icon.notify(
                f"Falha ao registrar: {combos}. Troque o atalho nas Configurações.",
                "Voice Commander",
            )
        except Exception:
            pass


def _main_event_loop() -> None:
    """Main thread loop — handles settings requests (pywebview requires main thread).

    Blocks until _shutdown_event is set (Ctrl+C or tray quit).
    IMPORTANTE: usa _shutdown_event (não stop_event). stop_event é usado pelo
    ciclo de gravação e é setado a cada STOP — não deve encerrar o app.
    """
    from voice.webui import open_settings_blocking
    try:
        while not state._shutdown_event.is_set():
            # Wait for either settings request or shutdown (poll every 0.5s for Ctrl+C)
            if state._settings_requested.wait(timeout=0.5):
                state._settings_requested.clear()
                open_settings_blocking()
    except KeyboardInterrupt:
        pass


def main() -> None:
    # Faz o Windows tratar o processo como "VoiceCommander" no taskbar
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("VoiceCommander.App")
    except Exception:
        pass

    # Carrega configurações uma vez (antes da rotação para ter LOG_KEEP_SESSIONS)
    state._CONFIG = load_config()
    state._GEMINI_API_KEY = state._CONFIG.get("GEMINI_API_KEY")
    state.selected_mode = state._CONFIG.get("SELECTED_MODE", "transcribe")

    # Primeira execução — abre wizard de setup se necessário
    if _needs_onboarding():
        _run_onboarding()
        state._CONFIG = load_config()
        state._GEMINI_API_KEY = state._CONFIG.get("GEMINI_API_KEY")
        state.selected_mode = state._CONFIG.get("SELECTED_MODE", "transcribe")

    # Story 3.2 — Rotação de log (antes de abrir novo log)
    _rotate_log()

    # QW-7 — Limpar WAVs temporários de sessões anteriores
    _cleanup_temp_wavs()

    try:
        with open(state._log_path, "w", encoding="utf-8") as f:
            f.write(f"=== voice.py iniciado {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    except Exception:
        pass

    _log_startup_info()

    _acquire_named_mutex()

    # Pre-load Whisper em background (evita delay na 1ª transcrição)
    def _preload_whisper():
        try:
            get_whisper_model(state.selected_mode)
        except Exception as e:
            print(f"[WARN] Pre-load Whisper falhou: {e}")
    threading.Thread(target=_preload_whisper, daemon=True).start()

    validate_microphone()
    _start_tray(quit_callback=graceful_shutdown)
    threading.Thread(target=_license_check_loop, daemon=True).start()

    # Story 5.4.2: Hands-free mode (VAD auto-start/stop)
    if state._CONFIG.get("HANDS_FREE_ENABLED", False) is True:
        from voice.audio import hands_free_loop
        threading.Thread(target=hands_free_loop, daemon=True, name="HandsFree").start()

    # Hotkeys via Win32 RegisterHotKey — thread própria do módulo (pump precisa
    # da sua própria message queue; main thread fica livre para webview).
    hotkeys_win32.start(_hotkey_bindings, _report_hotkey_failures)

    # Main loop: atende requests de settings (webview) e aguarda shutdown
    _main_event_loop()

    # Story 3.3 — Shutdown gracioso (libera mutex internamente)
    hotkeys_win32.stop()
    _stop_tray()
    graceful_shutdown()
    print("\nSaindo...")
