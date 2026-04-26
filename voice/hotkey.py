# voice/hotkey.py — Toggle / hotkey lifecycle (extracted from voice/audio.py).
#
# Responsibility: orchestrate the hotkey-driven START/STOP flow.
#   - toggle_recording(mode): public entrypoint that mutates recording state
#     under _toggle_lock and dispatches transcribe() after STOP.
#   - on_hotkey(): main record hotkey callback with atomic debounce.
#   - on_command_hotkey(): Command Mode hotkey callback (Epic 5.0).
#
# Test coupling — same lazy-lookup pattern as voice/recording.py /
# voice/transcription.py / voice/hands_free.py / voice/sound.py:
#   - tests patch voice.audio.threading.Thread (test_audio.py:293,323,361,451,462)
#   - tests patch voice.audio.toggle_recording (test_command_mode.py:232,257)
#   - tests patch voice.audio.play_sound (test_command_mode.py:233; test_audio.py:268,290,358,376)
#   - tests reset voice.audio._last_command_hotkey_time = 0.0 (test_command_mode.py:237,260)
#   - tests patch voice.audio._last_hotkey_time via patch.object (test_audio.py:450,461)
#   - tests/test_extended_recording.py exercises toggle_recording via hands_free.
#
# To honor those patches, every cross-module symbol referenced inside the
# functions below resolves at call time via `from voice import audio as _audio`.
# The module-level `_last_hotkey_time`, `_hotkey_debounce_lock`,
# `_last_command_hotkey_time`, `_command_debounce_lock` live HERE physically,
# but voice.audio re-exports them so tests that patch via voice.audio.<name>
# still work because the re-export creates an alias on voice.audio that points
# to the same lock objects (locks are passed by reference; patch.object on
# voice.audio._last_hotkey_time rebinds the float on the audio facade only,
# but the on_hotkey function below reads _audio._last_hotkey_time at call time
# — see lazy lookup pattern).

import threading
import time

from voice import state


# ── Module-level debounce state (re-exported by voice.audio) ─────────────────

_last_hotkey_time: float = 0.0
_hotkey_debounce_lock = threading.Lock()

_command_debounce_lock = threading.Lock()
_last_command_hotkey_time: float = 0.0


# ── Toggle / hotkey ───────────────────────────────────────────────────────────

def toggle_recording(mode: str = "transcribe") -> None:
    # Lazy import: tests patch voice.audio.play_sound, voice.audio.threading.Thread,
    # voice.audio.transcribe, voice.audio._start_recording / _stop_recording_snapshot.
    # All cross-module symbols are resolved through voice.audio so monkeypatches
    # intercept correctly. (Same pattern as voice/recording.py — validated.)
    from voice import audio as _audio

    # Captura snapshot das variáveis STOP fora do lock para o join posterior.
    # Inicializados como None — só preenchidos no path STOP.
    _stop_thread = None
    _stop_mode = None

    with state._toggle_lock:
        if state.is_transcribing:
            print("[SKIP] Aguardando transcrição anterior terminar...\n")
            _audio.play_sound("skip")
            return

        # QW-1: cooldown de 2s após processamento de modo query
        if not state.is_recording and mode == "query":
            now = time.time()
            if now < state._query_cooldown_until:
                remaining = state._query_cooldown_until - now
                print(f"[SKIP] Cooldown ativo — ignorando hotkey ({remaining:.1f}s restantes)\n")
                return

        if not state.is_recording:
            _audio._start_recording(mode)
        else:
            _stop_thread, _stop_mode = _audio._stop_recording_snapshot()
            if _stop_thread is None:
                return

    # ── Fora do lock: join e launch da transcrição ──────────────────────────
    # O join NÃO está dentro do with-block. Isso é intencional: manter o join
    # dentro do lock bloquearia _toggle_lock por até 5s. Qualquer on_hotkey()
    # que chegasse durante esse tempo teria seu thread de toggle_recording()
    # enfileirado e executaria imediatamente após o lock ser liberado —
    # disparando um START espúrio logo após o STOP.
    # Com o debounce atômico de on_hotkey() (1000ms), o lock já está livre
    # durante o join E nenhum novo toggle entra na fila.
    if _stop_thread is not None:
        _stop_thread.join(timeout=5)
        _audio.threading.Thread(
            target=_audio.transcribe,
            args=(list(state.frames_buf), _stop_mode),
            daemon=True,
        ).start()


def on_hotkey() -> None:
    """Hotkey único — usa state.selected_mode para determinar o modo.

    Debounce atômico: o check-and-set de _last_hotkey_time é protegido por um
    Lock para evitar race condition quando o keyboard library dispara o callback
    em múltiplas threads quase simultaneamente (key-down + key-up + bounce do OS
    chegam em ~1-5ms de diferença). Sem o lock, duas threads podem ler
    _last_hotkey_time ao mesmo tempo, ambas passam pelo check, e lançam dois
    toggle_recording() — causando START duplicado ou START+STOP imediatos.
    """
    # Lazy import: tests patch voice.audio.threading.Thread and
    # voice.audio._last_hotkey_time — both must be resolved via the audio facade.
    from voice import audio as _audio

    now = time.time()
    # Lock atômico: apenas uma thread por vez pode ler+atualizar _last_hotkey_time.
    # non-blocking tryacquire: se o lock estiver ocupado (outra thread está passando
    # pelo debounce agora), este fire é descartado imediatamente — é bounce.
    if not _audio._hotkey_debounce_lock.acquire(blocking=False):
        return
    try:
        if now - _audio._last_hotkey_time < 1.0:
            return
        # Atualiza no namespace do facade voice.audio para que tests que
        # `patch.object(audio, "_last_hotkey_time", ...)` vejam o efeito do
        # update e debounce funcione consistentemente entre patches e runtime.
        _audio._last_hotkey_time = now
        # Espelha em hotkey.py para manter o módulo coerente caso algum import
        # direto leia este global.
        global _last_hotkey_time
        _last_hotkey_time = now
    finally:
        _audio._hotkey_debounce_lock.release()
    _audio.threading.Thread(
        target=_audio.toggle_recording,
        args=(state.selected_mode,),
        daemon=True,
    ).start()


def on_command_hotkey() -> None:
    """Epic 5.0: Hotkey do Command Mode.

    1. Simula Ctrl+C para capturar texto selecionado
    2. Lê o clipboard e salva em state._command_selected_text
    3. Se seleção vazia, toca erro e retorna (sem gravar)
    4. Exibe overlay de comando com contagem de chars
    5. Inicia gravação no modo "command" (fluxo normal de transcrição)
    """
    # Lazy import: tests patch voice.audio.toggle_recording, voice.audio.play_sound,
    # voice.audio.threading.Thread, voice.audio._last_command_hotkey_time.
    from voice import audio as _audio

    now = time.time()
    if not _audio._command_debounce_lock.acquire(blocking=False):
        return
    try:
        if now - _audio._last_command_hotkey_time < 1.0:
            return
        _audio._last_command_hotkey_time = now
        global _last_command_hotkey_time
        _last_command_hotkey_time = now
    finally:
        _audio._command_debounce_lock.release()

    def _run():
        from voice.clipboard import simulate_copy, read_clipboard

        # Capturar texto selecionado
        simulate_copy()
        selected = read_clipboard()

        if not selected.strip():
            print("[SKIP] Nenhum texto selecionado para o Comando de Voz\n")
            _audio.play_sound("error")
            return

        state._command_selected_text = selected
        print(f"[INFO] Texto selecionado capturado ({len(selected)} chars) — fale a instrução\n")

        # Overlay de comando (mostra chars capturados)
        try:
            from voice import overlay as _overlay
            _overlay.show_command(len(selected))
        except Exception:
            pass

        # Iniciar gravação no modo "command"
        _audio.toggle_recording("command")

    _audio.threading.Thread(target=_run, daemon=True).start()
