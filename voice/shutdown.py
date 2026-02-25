# voice/shutdown.py — graceful_shutdown()
# Local import of audio.transcribe to avoid circular dependency.

import threading

from voice import state
from voice.mutex import _release_named_mutex


def graceful_shutdown() -> None:
    """
    Encerramento seguro quando chamado via Ctrl+C ou menu tray "Encerrar".
    - Se gravando: sinaliza stop, aguarda thread de gravação (até 5s)
    - Se frames capturados: tenta transcrever e colar (timeout 10s)
    - Mutex liberado em qualquer cenário (try/finally)
    - Thread-safe via _toggle_lock para leitura de is_recording
    """
    try:
        # Verificar se está gravando (com lock para thread-safety)
        recording_now = False
        captured_frames: list = []
        captured_mode = "transcribe"

        with state._toggle_lock:
            recording_now = state.is_recording
            if recording_now:
                captured_frames = list(state.frames_buf)
                captured_mode = state.current_mode
                state.is_recording = False

        if recording_now:
            print("[INFO] Shutdown com gravação ativa — sinalizando stop...")
            state.stop_event.set()

            # Aguardar thread de gravação encerrar (até 5s)
            if state.record_thread is not None and state.record_thread.is_alive():
                state.record_thread.join(timeout=5)
                # Capturar frames acumulados após join
                with state._toggle_lock:
                    captured_frames = list(state.frames_buf)

            if captured_frames:
                print("[INFO] Frames capturados — tentando transcrever antes de encerrar...")
                done_event = threading.Event()
                transcribe_error: list = []

                def _shutdown_transcribe():
                    # Local import to avoid circular dependency
                    from voice.audio import transcribe
                    try:
                        transcribe(captured_frames, captured_mode)
                    except Exception as exc:
                        transcribe_error.append(str(exc))
                    finally:
                        done_event.set()

                t = threading.Thread(target=_shutdown_transcribe, daemon=True)
                t.start()
                finished = done_event.wait(timeout=10)

                if not finished:
                    print("[WARN] Shutdown forçado — transcrição abortada")
                else:
                    if transcribe_error:
                        print(f"[WARN] Erro na transcrição de shutdown: {transcribe_error[0]}")
                    else:
                        print("[OK]   Transcrição de shutdown concluída")
            else:
                print("[INFO] Nenhum frame capturado — shutdown sem transcrição")
        else:
            # Não estava gravando, apenas sinalizar stop por segurança
            state.stop_event.set()

        print("[OK]   Shutdown gracioso concluído")

    finally:
        # Garantir liberação do mutex em qualquer cenário
        _release_named_mutex()
