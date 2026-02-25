# voice/audio.py — recording, transcription, toggle_recording, on_hotkey, validate_microphone

import os
import tempfile
import threading
import time
import wave

from voice import state
from voice.tray import _update_tray_state
from voice.gemini import correct_with_gemini, simplify_as_prompt, structure_as_prompt, query_with_gemini
from voice.logging_ import _append_history
from voice.clipboard import copy_to_clipboard, paste_via_sendinput

SAMPLE_RATE = 16000
CHANNELS    = 1

try:
    import sounddevice as sd
    import numpy as np
    import winsound
except Exception as _e:
    print(f"[ERRO IMPORT] {_e}")
    import sys
    sys.exit(1)


def get_whisper_model():
    if state._whisper_model is None:
        model_name = state._CONFIG.get("WHISPER_MODEL", "small")
        print(f"[...] Carregando Whisper {model_name} (primeira vez — pode demorar ~30s)...")
        from faster_whisper import WhisperModel
        state._whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
        print("[OK]  Whisper pronto (PT+EN bilíngue)")
    return state._whisper_model


def record() -> None:
    """Grava áudio do microfone, appendando frames diretamente em state.frames_buf.

    Escreve em state.frames_buf incrementalmente (não acumula em lista local)
    para evitar race condition: se join(timeout) expirar antes da thread terminar,
    os frames gravados até aquele momento já estão disponíveis em state.frames_buf.
    """
    state.stop_event.clear()
    max_seconds = state._CONFIG.get("MAX_RECORD_SECONDS", 120)
    max_frames = int(max_seconds * SAMPLE_RATE / 1024)
    warn_frames = int((max_seconds - 5) * SAMPLE_RATE / 1024)  # aviso 5s antes
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
                state.frames_buf.append(data.copy())  # escrita incremental no buffer global
                frame_count += 1

                if frame_count == warn_frames:
                    winsound.Beep(600, 200)  # bip de aviso 5s antes (frequência distinta)
                    print(f"[WARN] Gravação encerra em 5s (limite: {max_seconds}s)")

                if frame_count >= max_frames:
                    print(f"[WARN] Timeout de gravação atingido ({max_seconds}s)")
                    state.stop_event.set()
                    break

    except Exception as e:
        print(f"[ERRO gravação] {e}")


def transcribe(frames: list, mode: str = "transcribe") -> None:
    t_start = time.time()

    if not frames:
        print("[ERRO]  Sem áudio\n")
        winsound.Beep(200, 300)
        state.is_transcribing = False
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

            # Fallback sem VAD se havia audio suficiente (> 2s) e VAD zerou tudo
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
                # Heurística anti-alucinação: texto muito curto ou sem letras do alfabeto
                # latino/português é provavelmente alucinação do Whisper
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
        state.is_transcribing = False
        if temp_path:
            try:
                os.unlink(temp_path)
            except Exception:
                pass
        # Voltar tray para idle após finalizar
        _update_tray_state("idle")


def toggle_recording(mode: str = "transcribe") -> None:
    with state._toggle_lock:
        if state.is_transcribing:
            print("[SKIP] Aguardando transcrição anterior terminar...\n")
            winsound.Beep(300, 150)
            return

        if not state.is_recording:
            state.current_mode = mode
            state.is_recording = True
            state.frames_buf = []
            state.stop_event.clear()

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

            state.record_thread = threading.Thread(target=record, daemon=True)
            state.record_thread.start()
        else:
            state.is_recording = False
            state.is_transcribing = True
            state.stop_event.set()
            print("[STOP] Parando gravação...\n")
            if state.record_thread:
                # Aguarda a thread de gravação encerrar (max 5s).
                # frames_buf já contém todos os dados acumulados incrementalmente,
                # então mesmo em timeout os frames capturados até agora são válidos.
                state.record_thread.join(timeout=5)
            threading.Thread(
                target=transcribe,
                args=(list(state.frames_buf), state.current_mode),
                daemon=True,
            ).start()


def on_hotkey(mode: str = "transcribe") -> None:
    threading.Thread(target=toggle_recording, args=(mode,), daemon=True).start()


def validate_microphone() -> None:
    """
    Testa o sd.InputStream com o dispositivo configurado.
    Timeout: 3 segundos via thread com join(timeout=3).
    App continua mesmo se a validação falhar.
    """
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
