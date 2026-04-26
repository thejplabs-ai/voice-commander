# voice/audio.py — Public facade for the recording / transcription / hotkey
# subsystem. Originally this was a god-module owning all of those concerns
# (834L, SENTINEL HIGH×2). The implementation has since been split across
# sibling modules:
#   - voice/recording.py       record(), _start_recording(), _stop_recording_snapshot()
#   - voice/transcription.py   transcribe() + helpers (this module's previous core)
#   - voice/hands_free.py      hands_free_loop()
#   - voice/sound.py           play_sound(), _default_beep()
#   - voice/whisper.py         get_whisper_model() + fallback chain
#   - voice/mic.py             validate_microphone()
#
# This file remains the **public surface**: tests + app.py import from
# voice.audio, monkeypatch.setattr targets attributes on this module
# (e.g. patch("voice.audio.sd"), patch("voice.audio.np"),
# patch("voice.audio._do_transcription"), patch.object(audio, "play_sound"),
# patch.object(audio, "_update_tray_state"), etc.).
#
# Each sibling module performs **lazy lookup via voice.audio** for symbols
# that tests patch. That is why the re-exports below are sufficient: when a
# test does `monkeypatch.setattr("voice.audio.np", mock)`, the patched
# binding lives on this module's namespace, and recording/transcription
# resolve `_audio.np` against this module — so the patch is honored.

# Imports below are part of the public facade — voice/transcription.py +
# voice/recording.py + voice/hands_free.py resolve these via
# `from voice import audio as _audio` + `_audio.<name>` at call time, so tests
# can monkeypatch them on this module (patch("voice.audio.np"),
# patch("voice.audio.tempfile"), patch.object(audio, "_update_tray_state"),
# etc.). Static analysis sees them as unused — they are not, they are the
# contract. Hence the F401 noqa on every line.
import os  # noqa: F401 — facade re-export (tests patch voice.audio.os)
import tempfile  # noqa: F401 — facade re-export (tests patch voice.audio.tempfile)
import threading
import time  # noqa: F401 — preserved for downstream tests/imports
import wave  # noqa: F401 — facade re-export (tests patch voice.audio.wave)

from voice import state  # noqa: F401 — facade convenience for tests
from voice import ai_provider  # noqa: F401 — facade re-export (tests patch voice.audio.ai_provider.process)
from voice.tray import _update_tray_state  # noqa: F401 — facade re-export
from voice.logging_ import _append_history  # noqa: F401 — facade re-export
from voice.clipboard import copy_to_clipboard, paste_via_sendinput  # noqa: F401 — facade re-export
from voice.modes import MODE_ACTIONS as _MODE_ACTIONS  # noqa: F401 — facade re-export

# Re-exports from whisper module for backward compatibility.
# Tests patch voice.audio.get_whisper_model, so the name must exist in this
# module's namespace. monkeypatch.setattr(audio, "get_whisper_model", mock)
# replaces this binding, and transcription.py resolves get_whisper_model via
# `from voice import audio as _audio` + `_audio.get_whisper_model(...)` so
# patches are correctly intercepted.
from voice.whisper import (  # noqa: F401
    get_whisper_model,
    _FAST_MODES,
    _QUALITY_MODES,
    _HOTWORDS,
    _DEFAULT_INITIAL_PROMPT,
    _register_cuda_dlls,
    _resolve_hf_model_path,
    _resolve_symlinks_in_dir,
)

SAMPLE_RATE = 16000
CHANNELS    = 1

try:
    import sounddevice as sd  # noqa: F401 — facade re-export (tests patch voice.audio.sd)
    import numpy as np  # noqa: F401 — facade re-export (tests patch voice.audio.np)
except Exception as _e:
    print(f"[ERRO IMPORT] {_e}")
    import sys
    sys.exit(1)


# ── Sound (extracted to voice/sound.py — re-exported here) ───────────────────
# Tests patch `voice.audio.play_sound` (test_command_mode.py), so we re-bind
# play_sound + _default_beep here at module level. monkeypatch.setattr on
# voice.audio.play_sound replaces this binding; every internal call (snippets,
# transcribe helpers, recording) resolves play_sound via the voice.audio
# namespace, so patches still intercept correctly.
from voice.sound import play_sound, _default_beep  # noqa: F401, E402


# ── Transcription (extracted to voice/transcription.py — re-exported here) ──
# transcribe() is decomposed into 9 helpers in voice/transcription.py so the
# top-level orchestrator stays under 50 lines (HIGH-2 fix). All cross-module
# symbols (np, wave, tempfile, os, ai_provider, _do_transcription,
# _post_process_and_paste, copy_to_clipboard, paste_via_sendinput, play_sound,
# _append_history, _update_tray_state, get_whisper_model, _MODE_ACTIONS,
# SAMPLE_RATE, CHANNELS) are resolved by voice.transcription via lazy lookup
# through this voice.audio facade. So the public surface preserved here
# (tempfile, wave, os, np, ai_provider, _MODE_ACTIONS, etc.) plus the
# re-exports of the helper names ARE the contract test patches rely on.
from voice.transcription import (  # noqa: F401, E402
    transcribe,
    _do_transcription,
    _build_transcribe_kwargs,
    _transcribe_no_vad_fallback,
    _transcribe_cpu_fallback,
    _transcribe_model_fallback,
    _transcribe_without_vad_on_empty,
    _write_audio_to_wav,
    _try_snippet_match,
    _post_process_and_paste,
    _build_timing_and_log,
    _release_vram_if_cuda,
    _MODE_LOG_LABELS,
    # transcribe() decomposition helpers (so tests that need to patch any of
    # them can still target them via voice.audio.<helper> — none currently do
    # but the re-export keeps the facade complete and symmetrical).
    _capture_recording_ms,
    _validate_frames,
    _set_processing_state,
    _prepare_wav,
    _run_stt,
    _emit_empty_audio_error,
    _dispatch_transcribed_text,
    _handle_transcribe_error,
    _cleanup_transcribe,
)


# ── Toggle / hotkey ───────────────────────────────────────────────────────────

def toggle_recording(mode: str = "transcribe") -> None:
    # Captura snapshot das variáveis STOP fora do lock para o join posterior.
    # Inicializados como None — só preenchidos no path STOP.
    _stop_thread = None
    _stop_mode = None

    with state._toggle_lock:
        if state.is_transcribing:
            print("[SKIP] Aguardando transcrição anterior terminar...\n")
            play_sound("skip")
            return

        # QW-1: cooldown de 2s após processamento de modo query
        if not state.is_recording and mode == "query":
            now = time.time()
            if now < state._query_cooldown_until:
                remaining = state._query_cooldown_until - now
                print(f"[SKIP] Cooldown ativo — ignorando hotkey ({remaining:.1f}s restantes)\n")
                return

        if not state.is_recording:
            _start_recording(mode)
        else:
            _stop_thread, _stop_mode = _stop_recording_snapshot()
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
        threading.Thread(
            target=transcribe,
            args=(list(state.frames_buf), _stop_mode),
            daemon=True,
        ).start()


_last_hotkey_time: float = 0.0
_hotkey_debounce_lock = threading.Lock()


def on_hotkey() -> None:
    """Hotkey único — usa state.selected_mode para determinar o modo.

    Debounce atômico: o check-and-set de _last_hotkey_time é protegido por um
    Lock para evitar race condition quando o keyboard library dispara o callback
    em múltiplas threads quase simultaneamente (key-down + key-up + bounce do OS
    chegam em ~1-5ms de diferença). Sem o lock, duas threads podem ler
    _last_hotkey_time ao mesmo tempo, ambas passam pelo check, e lançam dois
    toggle_recording() — causando START duplicado ou START+STOP imediatos.
    """
    global _last_hotkey_time
    now = time.time()
    # Lock atômico: apenas uma thread por vez pode ler+atualizar _last_hotkey_time.
    # non-blocking tryacquire: se o lock estiver ocupado (outra thread está passando
    # pelo debounce agora), este fire é descartado imediatamente — é bounce.
    if not _hotkey_debounce_lock.acquire(blocking=False):
        return
    try:
        if now - _last_hotkey_time < 1.0:
            return
        _last_hotkey_time = now
    finally:
        _hotkey_debounce_lock.release()
    threading.Thread(target=toggle_recording, args=(state.selected_mode,), daemon=True).start()


_command_debounce_lock = threading.Lock()
_last_command_hotkey_time: float = 0.0


def on_command_hotkey() -> None:
    """Epic 5.0: Hotkey do Command Mode.

    1. Simula Ctrl+C para capturar texto selecionado
    2. Lê o clipboard e salva em state._command_selected_text
    3. Se seleção vazia, toca erro e retorna (sem gravar)
    4. Exibe overlay de comando com contagem de chars
    5. Inicia gravação no modo "command" (fluxo normal de transcrição)
    """
    global _last_command_hotkey_time

    now = time.time()
    if not _command_debounce_lock.acquire(blocking=False):
        return
    try:
        if now - _last_command_hotkey_time < 1.0:
            return
        _last_command_hotkey_time = now
    finally:
        _command_debounce_lock.release()

    def _run():
        from voice.clipboard import simulate_copy, read_clipboard

        # Capturar texto selecionado
        simulate_copy()
        selected = read_clipboard()

        if not selected.strip():
            print("[SKIP] Nenhum texto selecionado para o Comando de Voz\n")
            play_sound("error")
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
        toggle_recording("command")

    threading.Thread(target=_run, daemon=True).start()


# ── Recording (extracted to voice/recording.py — re-exported below) ─────────
# Tests call audio.record() and patch voice.audio.sd / voice.audio.threading.Thread
# / voice.audio.play_sound / voice.audio._update_tray_state. The recording
# module resolves all those via the voice.audio namespace lazily at call time
# (same lazy-lookup pattern validated in voice/hands_free.py). Re-exporting
# here preserves backward compat for tests + audio.toggle_recording above,
# which calls _start_recording / _stop_recording_snapshot from this module's
# globals.
from voice.recording import (  # noqa: F401, E402
    record,
    _start_recording,
    _stop_recording_snapshot,
)


# ── Hands-Free (extracted to voice/hands_free.py — re-exported below) ───────
# app.py imports `from voice.audio import hands_free_loop`, so the re-export
# preserves backward compat. The hands_free module reads voice.audio.np /
# voice.audio.sd / voice.audio.toggle_recording lazily at call time, so test
# monkeypatches on those symbols are honored.
from voice.hands_free import hands_free_loop  # noqa: F401, E402


# ── Microphone validation ─────────────────────────────────────────────────────
# Movido para voice/mic.py. Re-exportado aqui para backward compat com app.py.
from voice.mic import validate_microphone  # noqa: F401, E402
