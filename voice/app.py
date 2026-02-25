# voice/app.py — main(), _license_check_loop(), _needs_onboarding()

import ctypes
import datetime
import os
import sys
import threading
import time

from voice import state
from voice.config import load_config
from voice.license import validate_license_key, _show_license_expired_notification
from voice.logging_ import _rotate_log
from voice.mutex import _acquire_named_mutex
from voice.tray import _start_tray, _stop_tray
from voice.audio import on_hotkey, validate_microphone
from voice.shutdown import graceful_shutdown

try:
    import keyboard
except Exception as _e:
    print(f"[ERRO IMPORT] {_e}")
    sys.exit(1)


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

    # Completou antes mas a chave sumiu (ex: usuário editou .env manualmente)
    if not state._CONFIG.get("GEMINI_API_KEY"):
        return True

    return False


def _mark_onboarding_done() -> None:
    """Cria arquivo sentinel indicando que o onboarding foi concluído com sucesso."""
    sentinel_path = os.path.join(state._BASE_DIR, ".onboarding_done")
    try:
        with open(sentinel_path, "w", encoding="utf-8") as f:
            f.write(datetime.datetime.now().isoformat() + "\n")
    except Exception:
        pass


def _run_onboarding() -> None:
    """Abre wizard de configuração inicial (bloqueante)."""
    from voice.ui import OnboardingWindow
    OnboardingWindow(done_callback=_mark_onboarding_done).run()


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


def main() -> None:
    # Faz o Windows tratar o processo como "VoiceCommander" no taskbar
    # (sem isso, agrupa pelo executável pythonw.exe e mostra ícone do Python)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("VoiceCommander.App")
    except Exception:
        pass

    # Carrega configurações uma vez (antes da rotação para ter LOG_KEEP_SESSIONS)
    state._CONFIG = load_config()
    state._GEMINI_API_KEY = state._CONFIG.get("GEMINI_API_KEY")

    # Primeira execução — abre wizard de setup se necessário.
    # Licença é opcional (free tier disponível).
    if _needs_onboarding():
        _run_onboarding()
        # Recarregar config após wizard completar
        state._CONFIG = load_config()
        state._GEMINI_API_KEY = state._CONFIG.get("GEMINI_API_KEY")

    # Story 3.2 — Rotação de log (antes de abrir novo log)
    _rotate_log()

    # Abre novo log da sessão
    try:
        with open(state._log_path, "w", encoding="utf-8") as f:
            f.write(f"=== voice.py iniciado {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    except Exception:
        pass

    # Log de startup
    gemini_ok = state._GEMINI_API_KEY is not None
    key_display = f"***{state._GEMINI_API_KEY[-4:]}" if gemini_ok else "não configurada"
    device_display = str(state._CONFIG["AUDIO_DEVICE_INDEX"]) if state._CONFIG["AUDIO_DEVICE_INDEX"] is not None else "padrão do sistema"
    query_hotkey = state._CONFIG.get("QUERY_HOTKEY", "ctrl+shift+alt+space")
    _lic_valid, _lic_msg = validate_license_key(state._CONFIG.get("LICENSE_KEY", "") or "")

    print("═" * 54)
    print("  Voice-to-text v2  |  JP Labs")
    print("═" * 54)
    print("  [Ctrl+Shift+Space]          Transcrição pura")
    print("  [Ctrl+Alt+Space]            Prompt simples (bullet points)")
    print("  [Ctrl+CapsLock+Space]       Prompt estruturado (COSTAR)")
    print(f"  [{query_hotkey.title()}]  Query direta Gemini")
    print("  Idiomas : PT-BR + EN (automático)")
    gemini_model = state._CONFIG.get("GEMINI_MODEL", "gemini-2.5-flash")
    print(f"  Gemini  : {'ativo (' + key_display + ')' if gemini_ok else 'desativado (sem .env)'} [{gemini_model}]")
    print(f"  Licença : {_lic_msg}")
    print(f"  Whisper : {state._CONFIG['WHISPER_MODEL']}")
    print(f"  Timeout : {state._CONFIG['MAX_RECORD_SECONDS']}s")
    print(f"  Mic     : {device_display}")
    print("  Sair    : Ctrl+C (ou menu System Tray > Encerrar)")
    print("═" * 54 + "\n")

    _acquire_named_mutex()

    # Story 2.3 — Validar microfone após adquirir mutex
    validate_microphone()

    # Story 2.1 — Iniciar system tray (thread daemon, fallback silencioso)
    _start_tray(quit_callback=graceful_shutdown)

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
                state._CONFIG.get("QUERY_HOTKEY", "ctrl+shift+alt+space"),
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
