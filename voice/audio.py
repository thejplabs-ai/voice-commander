# voice/audio.py — recording, transcription, toggle_recording, on_hotkey, validate_microphone

import os
import tempfile
import threading
import time
import wave

from voice import state
from voice import ai_provider
from voice.tray import _update_tray_state
from voice.logging_ import _append_history
from voice.clipboard import copy_to_clipboard, paste_via_sendinput

SAMPLE_RATE = 16000
CHANNELS    = 1

_FAST_MODES    = {"transcribe", "bullet", "email", "translate"}
_QUALITY_MODES = {"simple", "prompt", "query"}

try:
    import sounddevice as sd
    import numpy as np
    import winsound
except Exception as _e:
    print(f"[ERRO IMPORT] {_e}")
    import sys
    sys.exit(1)


# ── Sound helpers ─────────────────────────────────────────────────────────────

def _default_beep(event: str) -> None:
    beeps = {
        "start":   [(880, 200)],
        "success": [(440, 100), (440, 100)],
        "error":   [(200, 300)],
        "warning": [(600, 200)],
        "skip":    [(300, 150)],
    }
    for freq, dur in beeps.get(event, []):
        winsound.Beep(freq, dur)


def play_sound(event: str) -> None:
    """Toca custom .wav ou fallback para beep padrão."""
    wav = state._CONFIG.get(f"SOUND_{event.upper()}", "")
    if wav and os.path.exists(wav):
        try:
            winsound.PlaySound(wav, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return
        except Exception as e:
            print(f"[WARN] Sound file error ({wav}): {e}")
    _default_beep(event)


# ── Whisper model ─────────────────────────────────────────────────────────────

def get_whisper_model(mode: str = "transcribe"):
    """Lazy-load Whisper. Seleciona modelo e device com base no modo."""
    device = state._CONFIG.get("WHISPER_DEVICE", "cpu")
    if device == "auto":
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"

    if mode in _FAST_MODES:
        model_name = state._CONFIG.get("WHISPER_MODEL_FAST") or state._CONFIG.get("WHISPER_MODEL", "small")
    elif mode in _QUALITY_MODES:
        model_name = state._CONFIG.get("WHISPER_MODEL_QUALITY") or state._CONFIG.get("WHISPER_MODEL", "small")
    else:
        model_name = state._CONFIG.get("WHISPER_MODEL", "small")

    cache_key = (model_name, device)
    if state._whisper_model is not None and state._whisper_cache_key == cache_key:
        return state._whisper_model

    if state._whisper_model is not None:
        print(f"[INFO] Whisper reconfigurando: {state._whisper_cache_key} → {cache_key}")
    else:
        print(f"[...] Carregando Whisper {model_name} em {device} (modo: {mode})...")

    from faster_whisper import WhisperModel
    state._whisper_model = WhisperModel(model_name, device=device, compute_type="int8")
    state._whisper_cache_key = cache_key
    print(f"[OK]  Whisper {model_name}/{device} pronto (PT+EN bilíngue)")
    return state._whisper_model


# ── Recording ─────────────────────────────────────────────────────────────────

def record() -> None:
    """Grava áudio do microfone, appendando frames diretamente em state.frames_buf."""
    state.stop_event.clear()
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

        with sd.InputStream(**stream_kwargs) as stream:
            while not state.stop_event.is_set():
                data, _ = stream.read(1024)
                state.frames_buf.append(data.copy())
                frame_count += 1

                if frame_count == warn_frames:
                    play_sound("warning")
                    print(f"[WARN] Gravação encerra em 5s (limite: {max_seconds}s)")

                if frame_count >= max_frames:
                    print(f"[WARN] Timeout de gravação atingido ({max_seconds}s)")
                    state.stop_event.set()
                    break

    except Exception as e:
        print(f"[ERRO gravação] {e}")


# ── Transcription ─────────────────────────────────────────────────────────────

def transcribe(frames: list, mode: str = "transcribe") -> None:
    import traceback as _tb
    t_start = time.time()
    temp_path = None

    _MODE_ACTIONS = {
        "transcribe": "Corrigindo",
        "simple":     "Simplificando prompt",
        "prompt":     "Estruturando prompt (COSTAR)",
        "query":      "Consultando AI (query direta)",
        "bullet":     "Gerando bullets",
        "email":      "Rascunhando email",
        "translate":  "Traduzindo",
    }

    try:
        if not frames:
            print("[ERRO]  Sem áudio\n")
            play_sound("error")
            _append_history(mode, "", None, 0.0, error=True)
            return

        _update_tray_state("processing", mode)

        print("[...]  Transcrevendo (Whisper)...")
        audio_data = np.concatenate(frames, axis=0)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name

        with wave.open(temp_path, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes((audio_data * 32767).astype(np.int16).tobytes())

        model = get_whisper_model(mode)
        lang_hint = state._CONFIG.get("WHISPER_LANGUAGE") or None
        vad_threshold = state._CONFIG.get("VAD_THRESHOLD", 0.3)
        segments, info = model.transcribe(
            temp_path,
            language=lang_hint,
            task="transcribe",
            vad_filter=True,
            vad_parameters=dict(
                threshold=vad_threshold,
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            ),
            initial_prompt="Transcrição bilíngue em português brasileiro e inglês.",
        )
        raw_text = " ".join(s.text for s in segments).strip()

        if not raw_text:
            audio_duration = len(audio_data) / SAMPLE_RATE
            vad_duration = getattr(info, "duration_after_vad", 0.0) or 0.0
            print(
                f"[WARN]  VAD descartou áudio (threshold={vad_threshold:.1f}, "
                f"gravação={audio_duration:.1f}s, fala_detectada={vad_duration:.1f}s)"
            )

            if audio_duration >= 2.0 and vad_duration == 0.0:
                print("[...]  Tentando sem filtro VAD (fallback)...")
                segments_fallback, _ = model.transcribe(
                    temp_path,
                    language=lang_hint,
                    task="transcribe",
                    vad_filter=False,
                    initial_prompt="Transcrição bilíngue em português brasileiro e inglês.",
                )
                raw_text_fallback = " ".join(s.text for s in segments_fallback).strip()
                has_real_content = (
                    len(raw_text_fallback) >= 8
                    and any(c.isalpha() for c in raw_text_fallback)
                    and raw_text_fallback.lower() not in {
                        "you", "thank you", "thank you.", "thanks.",
                        "gracias.", "obrigado.", "obrigado",
                    }
                )
                if has_real_content:
                    print(f"[OK]   Fallback VAD: {raw_text_fallback}")
                    raw_text = raw_text_fallback
                else:
                    print(f"[WARN]  Fallback retornou conteúdo suspeito — descartado: [{raw_text_fallback}]")

        if not raw_text:
            print(
                "[ERRO]  Não entendi. Verifique o volume do microfone"
                " (Configurações > Som > Dispositivos de entrada).\n"
            )
            play_sound("error")
            duration = time.time() - t_start
            _append_history(mode, "", None, duration, error=True)
            return

        print(f"[OK]   Whisper: {raw_text}")

        action = _MODE_ACTIONS.get(mode, "Processando")
        print(f"[...]  {action}...")
        text = ai_provider.process(mode, raw_text)

        copy_to_clipboard(text)
        print(f"[OK]   Texto no clipboard ({len(text)} chars)")

        play_sound("success")

        time.sleep(0.5)
        paste_via_sendinput()

        print("[OK]   Colado!\n")

        duration = time.time() - t_start
        _append_history(mode, raw_text, text, duration)

    except Exception as e:
        print(f"[ERRO]  {type(e).__name__}: {e}\n")
        print(f"[DEBUG] {_tb.format_exc()}")
        play_sound("error")
        duration = time.time() - t_start
        _append_history(mode, "", None, duration, error=True)
    finally:
        state.is_transcribing = False
        if temp_path:
            try:
                os.unlink(temp_path)
            except Exception:
                pass
        _update_tray_state("idle")


# ── Toggle / hotkey ───────────────────────────────────────────────────────────

_MODE_LABELS = {
    "transcribe": "TRANSCRIÇÃO",
    "simple":     "PROMPT SIMPLES",
    "prompt":     "PROMPT COSTAR",
    "query":      "QUERY AI",
    "bullet":     "BULLET DUMP",
    "email":      "EMAIL DRAFT",
    "translate":  "TRADUZIR",
}


def toggle_recording(mode: str = "transcribe") -> None:
    with state._toggle_lock:
        if state.is_transcribing:
            print("[SKIP] Aguardando transcrição anterior terminar...\n")
            play_sound("skip")
            return

        if not state.is_recording:
            state.current_mode = mode
            state.is_recording = True
            state.frames_buf = []
            state.stop_event.clear()

            _update_tray_state("recording", mode)

            label = _MODE_LABELS.get(mode, mode.upper())
            play_sound("start")
            print(f"[REC]  Gravando para {label}... (mesmo hotkey para parar)\n")

            state.record_thread = threading.Thread(target=record, daemon=True)
            state.record_thread.start()
        else:
            state.is_recording = False
            state.is_transcribing = True
            state.stop_event.set()
            print("[STOP] Parando gravação...\n")
            if state.record_thread:
                state.record_thread.join(timeout=5)
            threading.Thread(
                target=transcribe,
                args=(list(state.frames_buf), state.current_mode),
                daemon=True,
            ).start()


def on_hotkey() -> None:
    """Hotkey único — usa state.selected_mode para determinar o modo."""
    threading.Thread(target=toggle_recording, args=(state.selected_mode,), daemon=True).start()


# ── Microphone validation ─────────────────────────────────────────────────────

def validate_microphone() -> None:
    """Testa o sd.InputStream com o dispositivo configurado. Timeout: 3s."""
    device_index = state._CONFIG.get("AUDIO_DEVICE_INDEX")
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
                stream.read(64)
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
