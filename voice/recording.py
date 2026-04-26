# voice/recording.py — Recording loop + START/STOP snapshot helpers
# (extracted from voice/audio.py).
#
# Responsibility: capture audio frames from the microphone (record), and the
# transactional helpers that mutate state at the START and STOP edges of a
# recording session (_start_recording, _stop_recording_snapshot).
#
# Test coupling — same lazy-lookup pattern as voice/hands_free.py and
# voice/sound.py: tests patch attributes on the voice.audio facade module
# (e.g. patch("voice.audio.sd"), patch("voice.audio.threading.Thread"),
# patch.object(audio, "play_sound"), patch.object(audio, "_update_tray_state"),
# patch.object(audio, "record"), patch.object(audio, "transcribe")).
#
# To honor those patches, every cross-module symbol referenced inside the
# functions below resolves at call time via `from voice import audio as _audio`.
# Module-level direct imports (sd, np, winsound) are kept here so the file is
# self-consistent for static analysis, but the runtime lookup goes through
# the voice.audio namespace — which is what monkeypatch.setattr targets.

import time

from voice import state
from voice.modes import MODE_ACTIONS as _MODE_ACTIONS  # noqa: F401 — kept for symmetry

# Audio constants (kept in sync with voice.audio.SAMPLE_RATE / CHANNELS).
SAMPLE_RATE = 16000
CHANNELS    = 1


def record() -> None:
    """Grava áudio do microfone, appendando frames diretamente em state.frames_buf."""
    # Lazy import to (a) avoid circular import at module load time and
    # (b) honor monkeypatches on voice.audio.sd / voice.audio.play_sound that
    # tests apply before invoking record() (test_audio.py:210,235,267).
    from voice import audio as _audio

    # stop_event.clear() já foi chamado dentro de _toggle_lock em toggle_recording()
    max_seconds = state._CONFIG.get("MAX_RECORD_SECONDS", 120)
    max_frames = int(max_seconds * SAMPLE_RATE / 1024)
    warn_frames = int((max_seconds - 5) * SAMPLE_RATE / 1024)
    frame_count = 0

    device_index = state._CONFIG.get("AUDIO_DEVICE_INDEX")

    try:
        stream_kwargs: dict = {
            "samplerate": SAMPLE_RATE,
            "channels": CHANNELS,
            "dtype": "float32",
        }
        if device_index is not None:
            stream_kwargs["device"] = device_index

        with _audio.sd.InputStream(**stream_kwargs) as stream:
            while not state.stop_event.is_set():
                data, _ = stream.read(1024)
                with state._toggle_lock:
                    state.frames_buf.append(data.copy())
                frame_count += 1

                if frame_count == warn_frames:
                    _audio.play_sound("warning")
                    print(f"[WARN] Gravação encerra em 5s (limite: {max_seconds}s)")

                if frame_count >= max_frames:
                    print(f"[WARN] Timeout de gravação atingido ({max_seconds}s)")
                    state.stop_event.set()
                    break

    except Exception as e:
        print(f"[ERRO gravação] {e}")


def _start_recording(mode: str) -> None:
    """Executa o path START da gravação (chamado com _toggle_lock adquirido)."""
    # Lazy import: tests patch voice.audio.threading.Thread, voice.audio.play_sound,
    # voice.audio._update_tray_state, voice.audio.record. All cross-module symbols
    # are resolved through the voice.audio namespace so monkeypatches intercept.
    from voice import audio as _audio

    state.current_mode = mode
    state.is_recording = True
    state.frames_buf = []
    state.stop_event.clear()
    state.record_start_time = time.time()

    # Story 4.5.4: capturar clipboard context no início da gravação
    state._clipboard_context = ""
    if state._CONFIG.get("CLIPBOARD_CONTEXT_ENABLED", True) is True:
        try:
            from voice.clipboard import read_clipboard
            max_chars = state._CONFIG.get("CLIPBOARD_CONTEXT_MAX_CHARS", 2000)
            raw_clip = read_clipboard(max_chars=max_chars)
            if raw_clip and max_chars > 0 and len(raw_clip) == max_chars:
                print(f"[INFO] Clipboard truncado para {max_chars} chars")
            state._clipboard_context = raw_clip or ""
        except Exception as _e:
            print(f"[WARN] Falha ao ler clipboard: {_e}")

    # Epic 5.5: capturar window context no início da gravação
    state._window_context = {}
    if state._CONFIG.get("WINDOW_CONTEXT_ENABLED", False) is True:
        try:
            from voice.window_context import get_foreground_window_info
            state._window_context = get_foreground_window_info()
            if state._window_context.get("process"):
                print(f"[INFO] Contexto: {state._window_context['process']} ({state._window_context['category']})")
        except Exception as _wc_e:
            print(f"[WARN] Falha ao capturar window context: {_wc_e}")

    _audio._update_tray_state("recording", mode)

    label = _audio._MODE_LOG_LABELS.get(mode, mode.upper())
    _audio.play_sound("start")
    print(f"[REC]  Gravando para {label}... (mesmo hotkey para parar)\n")

    try:
        from voice import overlay as _overlay
        clip_chars = len(state._clipboard_context) if hasattr(state, "_clipboard_context") else 0
        _overlay.show_recording(clipboard_chars=clip_chars)
    except Exception:
        pass  # overlay nunca deve crashar o recording

    state.record_thread = _audio.threading.Thread(target=_audio.record, daemon=True)
    state.record_thread.start()


def _stop_recording_snapshot() -> "tuple[object, str] | tuple[None, None]":
    """Executa o path STOP da gravação (chamado com _toggle_lock adquirido).

    Retorna (record_thread, current_mode) se STOP for executado, ou (None, None)
    se a gravação for muito curta (guard de 500ms).
    """
    elapsed = time.time() - state.record_start_time
    if elapsed < 0.5:
        print(f"[SKIP] STOP ignorado — gravação muito curta ({elapsed*1000:.0f}ms < 500ms)\n")
        return None, None

    state.is_recording = False
    state.is_transcribing = True
    state.stop_event.set()
    # Capturar refs locais antes de soltar o lock — join e transcribe
    # executam FORA do lock para não bloquear toggles subsequentes.
    _stop_thread = state.record_thread
    _stop_mode = state.current_mode
    print("[STOP] Parando gravação...\n")
    # Nota: frames são capturados APÓS o join (fora do lock) para
    # incluir os últimos frames gravados. Como o debounce atômico de
    # on_hotkey() garante ≥1000ms antes do próximo START, não há
    # risco de frames_buf ser zerado durante o join.
    return _stop_thread, _stop_mode
