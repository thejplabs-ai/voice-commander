# voice/hands_free.py — Hands-Free VAD auto-start/stop loop (extracted from voice/audio.py).
#
# Responsibility: background loop that monitors the microphone via simple RMS
# energy threshold and auto-fires toggle_recording() on speech start / silence.
# Only runs if HANDS_FREE_ENABLED=true.
#
# Test coupling: tests in test_extended_recording.py patch `voice.audio.np`,
# `voice.audio.toggle_recording`, and `sys.modules["sounddevice"].InputStream`.
# To preserve those patches, this module looks up np / sd / toggle_recording
# via the `voice.audio` module attribute namespace at call time (not at import
# time). The lazy `from voice import audio as _audio` inside hands_free_loop()
# is intentional: it both avoids the circular import (audio.py re-exports this
# module's symbols) and ensures monkeypatch.setattr(audio, "np", ...) on the
# audio module is honored when this loop reads _audio.np.

import threading
import time

from voice import state


# Audio constants (kept in sync with voice.audio.SAMPLE_RATE / CHANNELS).
# Re-imported at call time below if needed; using local module-level constants
# avoids touching voice.audio at import time.
SAMPLE_RATE = 16000
CHANNELS    = 1


def hands_free_loop() -> None:
    """Background loop que monitora o microfone via VAD e auto-start/stop a gravação.

    Usa RMS como proxy simples de energia (sem dependência de Silero para este loop).
    Só executa se HANDS_FREE_ENABLED=true no .env.
    Thread daemon=True — nunca bloqueia o encerramento do app.
    """
    if state._CONFIG.get("HANDS_FREE_ENABLED", False) is not True:
        return

    # Lazy import to (a) avoid circular import at module load time and
    # (b) honor monkeypatches on voice.audio.np / voice.audio.toggle_recording
    # that tests apply before invoking this loop.
    from voice import audio as _audio

    vad_threshold = state._CONFIG.get("VAD_THRESHOLD", 0.3)
    speech_ms = state._CONFIG.get("HANDS_FREE_SPEECH_MS", 500)
    silence_ms = state._CONFIG.get("HANDS_FREE_SILENCE_MS", 2000)
    device_index = state._CONFIG.get("AUDIO_DEVICE_INDEX")

    # Intervalo de amostragem para detecção de voz
    chunk_ms = 50  # 50ms por chunk
    chunk_samples = int(SAMPLE_RATE * chunk_ms / 1000)

    speech_frames_needed = int(speech_ms / chunk_ms)    # chunks consecutivos para confirmar fala
    silence_frames_needed = int(silence_ms / chunk_ms)  # chunks consecutivos para confirmar silêncio

    speech_frame_count = 0
    silence_frame_count = 0

    # Escalar threshold VAD (config) para RMS — VAD Silero usa 0-1 em outro domínio;
    # aqui usamos 10% do valor configurado como limite de energia RMS (float32 normalizado).
    rms_threshold = vad_threshold * 0.1

    print("[INFO] Hands-free ativo — monitorando microfone...")

    try:
        stream_kwargs: dict = {
            "samplerate": SAMPLE_RATE,
            "channels": CHANNELS,
            "dtype": "float32",
        }
        if device_index is not None:
            stream_kwargs["device"] = device_index

        with _audio.sd.InputStream(**stream_kwargs) as stream:
            while not state._shutdown_event.is_set():
                data, _ = stream.read(chunk_samples)

                # RMS do chunk como proxy de energia de fala
                rms = float(_audio.np.sqrt(_audio.np.mean(data ** 2)))
                is_speech = rms > rms_threshold

                if is_speech:
                    speech_frame_count += 1
                    silence_frame_count = 0

                    # Fala detectada por tempo suficiente — disparar auto-start
                    if (
                        speech_frame_count >= speech_frames_needed
                        and not state.is_recording
                        and not state.is_transcribing
                    ):
                        print("[INFO] Hands-free: fala detectada — auto-start")
                        threading.Thread(
                            target=_audio.toggle_recording,
                            args=(state.selected_mode,),
                            daemon=True,
                        ).start()
                        # Aguardar gravação iniciar e estabilizar antes do próximo ciclo
                        time.sleep(1.0)
                        speech_frame_count = 0
                        silence_frame_count = 0
                else:
                    silence_frame_count += 1
                    speech_frame_count = 0

                    # Silêncio prolongado durante gravação — disparar auto-stop
                    if silence_frame_count >= silence_frames_needed and state.is_recording:
                        print("[INFO] Hands-free: silêncio detectado — auto-stop")
                        threading.Thread(
                            target=_audio.toggle_recording,
                            args=(state.selected_mode,),
                            daemon=True,
                        ).start()
                        time.sleep(1.0)
                        speech_frame_count = 0
                        silence_frame_count = 0

    except Exception as e:
        print(f"[ERRO] Hands-free loop: {e}")
