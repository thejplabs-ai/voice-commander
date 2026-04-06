# voice/audio.py — recording, transcription, toggle_recording, on_hotkey, validate_microphone

import os
import sys
import tempfile
import threading
import time
import wave

from voice import state
from voice import ai_provider
from voice.tray import _update_tray_state
from voice.logging_ import _append_history
from voice.clipboard import copy_to_clipboard, paste_via_sendinput
from voice.modes import MODE_ACTIONS as _MODE_ACTIONS


# ── CUDA DLL discovery ───────────────────────────────────────────────────────
# ctranslate2 requer cublas64_12.dll e cudnn64_9.dll no DLL search path.
# Quando instalados via pip (nvidia-cublas-cu12, nvidia-cudnn-cu12), ficam
# em site-packages/nvidia/*/bin/ — fora do PATH do sistema.
# Registrar ANTES de qualquer import do faster_whisper/ctranslate2.
def _register_cuda_dlls() -> None:
    if sys.platform != "win32" or not hasattr(os, "add_dll_directory"):
        return
    # PyInstaller: DLLs ficam no _MEIPASS (mesma pasta do exe)
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass and os.path.isdir(meipass):
            os.add_dll_directory(meipass)
        return
    # Dev: DLLs nos pacotes nvidia pip (site-packages/nvidia/*/bin/)
    try:
        import nvidia.cublas
        import nvidia.cudnn
        for pkg in (nvidia.cublas, nvidia.cudnn):
            bin_dir = os.path.join(os.path.dirname(pkg.__path__[0]), pkg.__name__.split(".")[-1], "bin")
            if os.path.isdir(bin_dir):
                os.add_dll_directory(bin_dir)
    except (ImportError, Exception):
        pass  # pacotes nvidia não instalados — CUDA via toolkit ou indisponível

_register_cuda_dlls()

SAMPLE_RATE = 16000
CHANNELS    = 1

_FAST_MODES    = {"transcribe", "bullet", "email", "translate"}
_QUALITY_MODES = {"simple", "prompt", "query"}

_HOTWORDS = (
    "deploy, build, pipeline, debounce, commit, branch, merge, "
    "webhook, script, frontend, backend, API, token, workflow, "
    "debug, SOP, prompt, buffer, cache, endpoint, payload, query"
)

_DEFAULT_INITIAL_PROMPT = (
    "Falo português brasileiro com termos técnicos em inglês. "
    "Exemplos: 'o build falhou', 'faz o deploy', 'testa o pipeline', "
    "'o debounce não funciona', 'criar um SOP', 'estruturar o prompt', "
    "'o webhook está caindo', 'revisar o script', 'o frontend quebrou', "
    "'configurar a API', 'commitar as mudanças', 'fazer o merge', "
    "'o token expirou', 'rodar o workflow', 'debug do backend'."
)

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
    sequence = beeps.get(event, [])

    def _beep_thread():
        for freq, dur in sequence:
            winsound.Beep(freq, dur)

    threading.Thread(target=_beep_thread, daemon=True).start()


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

def _resolve_hf_model_path(model_name: str) -> str | None:
    """Resolve o path real de um modelo HuggingFace, resolvendo symlinks.

    ctranslate2 (C++) não segue symlinks do HuggingFace no Windows em certos
    contextos (pós-install do Inno Setup, UAC elevation). Esta função encontra
    o snapshot directory e resolve model.bin para o blob real.
    Retorna o path do diretório com arquivos reais, ou None se não encontrar.
    """
    hf_cache = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    model_dir = os.path.join(hf_cache, f"models--Systran--faster-whisper-{model_name}", "snapshots")
    if not os.path.isdir(model_dir):
        return None
    # Pegar o snapshot mais recente
    try:
        snapshots = [d for d in os.listdir(model_dir) if os.path.isdir(os.path.join(model_dir, d))]
    except OSError:
        return None
    if not snapshots:
        return None
    snapshot = os.path.join(model_dir, snapshots[-1])
    model_bin = os.path.join(snapshot, "model.bin")
    # Se model.bin é symlink, resolver para o path real
    if os.path.islink(model_bin):
        real_path = os.path.realpath(model_bin)
        if os.path.exists(real_path):
            # Retornar o diretório do snapshot — ctranslate2 espera um diretório
            # com model.bin, config.json, etc. Precisamos criar um temp dir com
            # os arquivos resolvidos? Não — mais simples: substituir symlinks por hardlinks.
            _resolve_symlinks_in_dir(snapshot)
            return snapshot
    elif os.path.exists(model_bin):
        return snapshot  # Arquivo real, sem symlink
    return None


def _resolve_symlinks_in_dir(directory: str) -> None:
    """Substitui symlinks por hardlinks no diretório (Windows-safe).

    Hardlinks funcionam sem privilégios especiais no mesmo filesystem.
    Se hardlink falhar (cross-device), faz copy.
    """
    import shutil
    for entry in os.listdir(directory):
        full_path = os.path.join(directory, entry)
        if os.path.islink(full_path):
            real_target = os.path.realpath(full_path)
            if os.path.exists(real_target):
                try:
                    os.remove(full_path)
                    os.link(real_target, full_path)
                except OSError:
                    # Cross-device ou sem permissão para hardlink — copiar
                    try:
                        os.remove(full_path) if os.path.exists(full_path) else None
                        shutil.copy2(real_target, full_path)
                    except Exception as e:
                        print(f"[WARN] Falha ao resolver symlink {entry}: {e}")


def get_whisper_model(mode: str = "transcribe"):
    """Lazy-load Whisper. Seleciona modelo e device com base no modo.

    Fallback chain: configured model/cuda → configured model/cpu → tiny/cpu.
    Se ctranslate2 falhar com 'Unable to open file' (symlinks do HuggingFace no
    Windows), resolve symlinks para hardlinks e tenta novamente.
    """
    device = state._CONFIG.get("WHISPER_DEVICE", "cpu")
    if device == "auto":
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"

    if mode in _FAST_MODES:
        model_name = state._CONFIG.get("WHISPER_MODEL_FAST") or state._CONFIG.get("WHISPER_MODEL", "tiny")
    elif mode in _QUALITY_MODES:
        model_name = state._CONFIG.get("WHISPER_MODEL_QUALITY") or state._CONFIG.get("WHISPER_MODEL", "tiny")
    else:
        model_name = state._CONFIG.get("WHISPER_MODEL", "tiny")

    cache_key = (model_name, device)
    if state._whisper_model is not None and state._whisper_cache_key == cache_key:
        return state._whisper_model

    if state._whisper_model is not None:
        print(f"[INFO] Whisper reconfigurando: {state._whisper_cache_key} → {cache_key}")
    else:
        print(f"[...] Carregando Whisper {model_name} em {device} (modo: {mode})...")

    from faster_whisper import WhisperModel
    try:
        state._whisper_model = WhisperModel(model_name, device=device, compute_type="int8")
        state._whisper_cache_key = cache_key
        print(f"[OK]  Whisper {model_name}/{device} pronto (PT-BR âncora + termos EN via hotwords)")
    except Exception as _err:
        err_msg = str(_err).lower()
        # Symlink issue: ctranslate2 não segue symlinks do HuggingFace no Windows
        if "unable to open" in err_msg and "model.bin" in err_msg:
            resolved = _resolve_hf_model_path(model_name)
            if resolved:
                print("[INFO] Symlinks HuggingFace resolvidos — tentando novamente...")
                try:
                    state._whisper_model = WhisperModel(resolved, device=device, compute_type="int8")
                    state._whisper_cache_key = cache_key
                    print(f"[OK]  Whisper {model_name}/{device} pronto (symlinks resolvidos)")
                    return state._whisper_model
                except Exception as _resolved_err:
                    print(f"[WARN] Ainda falhou após resolver symlinks: {_resolved_err}")
                    _err = _resolved_err

        # Fallback 1: CUDA → CPU com mesmo modelo
        if device == "cuda":
            print(f"[WARN] CUDA indisponível ({type(_err).__name__}: {_err}) — fallback para CPU")
            device = "cpu"
            try:
                state._whisper_model = WhisperModel(model_name, device=device, compute_type="int8")
                state._whisper_cache_key = (model_name, device)
                print(f"[OK]  Whisper {model_name}/cpu pronto (fallback CPU)")
                return state._whisper_model
            except Exception as _cpu_err:
                print(f"[WARN] Modelo {model_name}/cpu também falhou ({_cpu_err})")
                # Continua para fallback 2

        # Fallback 2: modelo de emergência tiny/cpu (sempre disponível, ~75MB)
        if model_name != "tiny":
            print("[WARN] Fallback emergencial: tiny/cpu")
            try:
                state._whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
                state._whisper_cache_key = ("tiny", "cpu")
                print("[OK]  Whisper tiny/cpu pronto (fallback emergencial)")
                return state._whisper_model
            except Exception as _tiny_err:
                print(f"[ERRO] Fallback tiny/cpu falhou: {_tiny_err}")
                raise
        raise
    return state._whisper_model


# ── Recording ─────────────────────────────────────────────────────────────────

def record() -> None:
    """Grava áudio do microfone, appendando frames diretamente em state.frames_buf."""
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

        with sd.InputStream(**stream_kwargs) as stream:
            while not state.stop_event.is_set():
                data, _ = stream.read(1024)
                with state._toggle_lock:
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


def _do_transcription(temp_path: str, mode: str, audio_data) -> str:
    """Executa transcrição no arquivo WAV e retorna o texto transcrito.

    Roteia para Gemini STT ou Whisper local com base em STT_PROVIDER.
    audio_data: numpy array concatenado (usado para calcular duração sem re-abrir WAV).
    Tenta com VAD primeiro; se VAD falhar, tenta sem VAD. Se o texto
    ficar vazio, tenta fallback sem VAD. Retorna string vazia se nada
    for reconhecido.
    """
    stt_provider = state._CONFIG.get("STT_PROVIDER", "whisper").lower()

    if stt_provider == "gemini":
        from voice import gemini as _gemini_mod
        try:
            result = _gemini_mod.transcribe_audio_with_gemini(temp_path)
            if result:
                return result
            print("[WARN] Gemini STT retornou vazio — usando Whisper como fallback\n")
        except Exception as e:
            print(f"[WARN] Gemini STT falhou ({e}), usando Whisper como fallback\n")
        # Continua para Whisper abaixo

    model = get_whisper_model(mode)
    lang_hint = state._CONFIG.get("WHISPER_LANGUAGE") or None
    vad_threshold = state._CONFIG.get("VAD_THRESHOLD", 0.3)
    info = None

    initial_prompt = state._CONFIG.get("WHISPER_INITIAL_PROMPT") or _DEFAULT_INITIAL_PROMPT
    try:
        from voice import vocabulary as _vocab
        initial_prompt += _vocab.get_initial_prompt_suffix()
    except Exception:
        pass  # vocabulário nunca deve crashar a transcrição

    # Detectar se faster-whisper suporta o parâmetro hotwords (introduzido em ≥1.0).
    # Se não suportado, omitir silenciosamente para manter compatibilidade.
    import inspect as _inspect
    _transcribe_sig = _inspect.signature(model.transcribe)
    _supports_hotwords = "hotwords" in _transcribe_sig.parameters

    beam_size = state._CONFIG.get("WHISPER_BEAM_SIZE", 1)

    _transcribe_kwargs: dict = dict(
        language=lang_hint,
        task="transcribe",
        initial_prompt=initial_prompt,
        condition_on_previous_text=False,
        temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
        beam_size=beam_size,
    )
    if _supports_hotwords:
        try:
            from voice import vocabulary as _vocab
            _transcribe_kwargs["hotwords"] = _vocab.get_hotwords_string()
        except Exception:
            _transcribe_kwargs["hotwords"] = _HOTWORDS

    _vad_params = dict(
        threshold=vad_threshold,
        min_silence_duration_ms=500,
        speech_pad_ms=200,
    )

    try:
        segments, info = model.transcribe(
            temp_path,
            vad_filter=True,
            vad_parameters=_vad_params,
            **_transcribe_kwargs,
        )
        raw_text = " ".join(s.text for s in segments).strip()
    except Exception as _vad_err:
        err_msg = str(_vad_err).lower()
        if "silero" in err_msg or "onnx" in err_msg or "nosuchfile" in err_msg:
            print(f"[WARN]  VAD model indisponível ({type(_vad_err).__name__}) — usando transcrição sem VAD")
            segments_novad, info = model.transcribe(
                temp_path,
                vad_filter=False,
                **_transcribe_kwargs,
            )
            raw_text = " ".join(s.text for s in segments_novad).strip()
        elif "cublas" in err_msg or "cuda" in err_msg or "cudnn" in err_msg or "library" in err_msg:
            # Fallback automático CUDA → CPU quando DLLs CUDA ausentes no ambiente.
            # Acontece quando WHISPER_DEVICE=cuda mas cublas64_12.dll/cudart não
            # está no PATH do sistema (PyInstaller, CUDA desatualizado, etc.).
            # WhisperModel.__init__ pode ter sucesso com cuda mas model.transcribe()
            # falha ao carregar o modelo na GPU para processamento real.
            print(f"[WARN]  CUDA indisponível durante transcrição ({type(_vad_err).__name__}) — fallback CPU")
            print("[WARN]  Configure WHISPER_DEVICE=cpu em Configurações para evitar este fallback.")
            # Forçar reload do modelo em CPU (invalida o cache)
            # Usa tiny/cpu como fallback rápido (evita reload de modelo grande)
            state._whisper_model = None
            state._whisper_cache_key = ()
            state._CONFIG["WHISPER_DEVICE"] = "cpu"  # override para esta sessão
            model_cpu = get_whisper_model(mode)
            segments_cpu, info = model_cpu.transcribe(
                temp_path,
                vad_filter=True,
                vad_parameters=_vad_params,
                **_transcribe_kwargs,
            )
            raw_text = " ".join(s.text for s in segments_cpu).strip()
        elif "unable to open" in err_msg or "model.bin" in err_msg or "no such file" in err_msg:
            # Modelo não encontrado no disco (download incompleto, symlink quebrado)
            print(f"[WARN]  Modelo indisponível ({type(_vad_err).__name__}: {_vad_err})")
            state._whisper_model = None
            state._whisper_cache_key = ()
            state._CONFIG["WHISPER_DEVICE"] = "cpu"
            model_fallback = get_whisper_model(mode)  # get_whisper_model tem fallback chain
            segments_fb, info = model_fallback.transcribe(
                temp_path,
                vad_filter=True,
                vad_parameters=_vad_params,
                **_transcribe_kwargs,
            )
            raw_text = " ".join(s.text for s in segments_fb).strip()
        else:
            raise

    if not raw_text and info is not None:
        # VAD descartou o áudio — calcular duração a partir do audio_data já em memória
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
                vad_filter=False,
                **_transcribe_kwargs,
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

    return raw_text


def _post_process_and_paste(raw_text: str, mode: str) -> tuple:
    """Processa texto via AI, copia para clipboard e cola.

    Retorna (texto_processado, gemini_ms, paste_ms).
    """
    action = _MODE_ACTIONS.get(mode, "Processando")
    print(f"[...]  {action}...")

    t_gemini_start = time.monotonic()
    text = ai_provider.process(mode, raw_text)
    gemini_ms = int((time.monotonic() - t_gemini_start) * 1000)

    copy_to_clipboard(text)
    print(f"[OK]   Texto no clipboard ({len(text)} chars)")

    play_sound("success")
    paste_delay_ms = state._CONFIG.get("PASTE_DELAY_MS", 50)
    paste_delay_s = max(0, paste_delay_ms) / 1000.0 + 0.1  # base 100ms + configurável

    t_paste_start = time.monotonic()
    time.sleep(paste_delay_s)
    paste_via_sendinput()
    paste_ms = int((time.monotonic() - t_paste_start) * 1000)

    print("[OK]   Colado!\n")
    return text, gemini_ms, paste_ms


def transcribe(frames: list, mode: str = "transcribe") -> None:
    import traceback as _tb
    t_start = time.time()
    t_mono_start = time.monotonic()
    temp_path = None

    # Story 4.6.6: guardar tempo de gravação (capturado de state)
    recording_ms = 0
    if hasattr(state, "record_start_time") and state.record_start_time > 0:
        recording_ms = int((time.time() - state.record_start_time) * 1000)

    try:
        if not frames:
            print("[ERRO]  Sem áudio\n")
            play_sound("error")
            _append_history(mode, "", None, 0.0, error=True)
            return

        _update_tray_state("processing", mode)

        # Story 4.5.1: overlay "Processando"
        try:
            from voice import overlay as _overlay
            _overlay.show_processing(mode)
        except Exception:
            pass

        stt_provider = state._CONFIG.get("STT_PROVIDER", "whisper").title()
        print(f"[...]  Transcrevendo ({stt_provider})...")
        audio_data = np.concatenate(frames, axis=0)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name

        with wave.open(temp_path, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes((audio_data * 32767).astype(np.int16).tobytes())

        # Story 4.6.6: medir fase Whisper
        t_whisper_start = time.monotonic()
        raw_text = _do_transcription(temp_path, mode, audio_data)
        whisper_ms = int((time.monotonic() - t_whisper_start) * 1000)

        if not raw_text:
            print(
                "[ERRO]  Não entendi. Verifique o volume do microfone"
                " (Configurações > Som > Dispositivos de entrada).\n"
            )
            play_sound("error")
            duration = time.time() - t_start
            _append_history(mode, "", None, duration, error=True)
            return

        print(f"[OK]   {stt_provider}: {raw_text}")

        # Epic 5.2: Snippet matching — expandir antes do processamento AI
        try:
            from voice import snippets as _snippets
            snippet_text = _snippets.match_snippet(raw_text)
            if snippet_text is not None:
                copy_to_clipboard(snippet_text)
                play_sound("success")
                paste_delay_ms = state._CONFIG.get("PASTE_DELAY_MS", 50)
                time.sleep(max(0, paste_delay_ms) / 1000.0 + 0.1)
                paste_via_sendinput()
                print(f"[OK]   Snippet expandido ({len(snippet_text)} chars)")
                try:
                    from voice import overlay as _overlay
                    _overlay.show_done(snippet_text)
                except Exception:
                    pass
                duration = time.time() - t_start
                _append_history(mode, raw_text, snippet_text, duration)
                return
        except Exception:
            pass  # snippets nunca devem crashar a transcrição

        text, gemini_ms, paste_ms = _post_process_and_paste(raw_text, mode)

        # Story 4.5.1: overlay "Pronto" com preview do output
        try:
            from voice import overlay as _overlay
            _overlay.show_done(text)
        except Exception:
            pass

        # QW-1: definir cooldown de 2s após processamento de query
        if mode == "query":
            state._query_cooldown_until = time.time() + state._QUERY_HOTKEY_COOLDOWN

        duration = time.time() - t_start
        total_ms = int((time.monotonic() - t_mono_start) * 1000)

        # Story 4.6.6: montar timing breakdown
        timing: dict = {
            "recording": recording_ms,
            "whisper": whisper_ms,
            "total": total_ms,
        }
        if gemini_ms > 0:
            timing["gemini"] = gemini_ms
        if paste_ms > 0:
            timing["paste"] = paste_ms

        # Story 4.6.6: log de performance (controlado por DEBUG_PERF)
        if state._CONFIG.get("DEBUG_PERF", False) is True:
            parts = [f"Gravação: {recording_ms/1000:.1f}s", f"Whisper: {whisper_ms/1000:.1f}s"]
            if gemini_ms > 0:
                parts.append(f"Gemini: {gemini_ms/1000:.1f}s")
            if paste_ms > 0:
                parts.append(f"Paste: {paste_ms/1000:.1f}s")
            parts.append(f"Total: {total_ms/1000:.1f}s")
            print(f"[PERF] {' | '.join(parts)}")

        _append_history(mode, raw_text, text, duration, timing_ms=timing)

    except Exception as e:
        print(f"[ERRO]  {type(e).__name__}: {e}\n")
        print(f"[DEBUG] {_tb.format_exc()}")
        play_sound("error")
        duration = time.time() - t_start
        _append_history(mode, "", None, duration, error=True)
    finally:
        state.is_transcribing = False
        # Limpar dados de sessão para evitar memory leak
        state._clipboard_context = ""
        if temp_path:
            try:
                os.unlink(temp_path)
            except Exception as e:
                print(f"[WARN] Falha ao deletar arquivo temporário {temp_path}: {e}")
        _update_tray_state("idle")
        # Story 4.5.1: esconder overlay se não foi para "done" (erro path)
        try:
            from voice import overlay as _overlay
            if _overlay._thread and _overlay._thread._current_state not in ("done", "hide"):
                _overlay.hide()
        except Exception:
            pass


# ── Toggle / hotkey ───────────────────────────────────────────────────────────

_MODE_LOG_LABELS = {
    "transcribe": "TRANSCRIÇÃO",
    "simple":     "PROMPT SIMPLES",
    "prompt":     "PROMPT COSTAR",
    "query":      "QUERY AI",
    "bullet":     "BULLET DUMP",
    "email":      "EMAIL DRAFT",
    "translate":  "TRADUZIR",
    "command":    "COMANDO DE VOZ",
}


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

            _update_tray_state("recording", mode)

            label = _MODE_LOG_LABELS.get(mode, mode.upper())
            play_sound("start")
            print(f"[REC]  Gravando para {label}... (mesmo hotkey para parar)\n")

            # Story 4.5.1: overlay de feedback
            try:
                from voice import overlay as _overlay
                clip_chars = len(state._clipboard_context) if hasattr(state, "_clipboard_context") else 0
                _overlay.show_recording(clipboard_chars=clip_chars)
            except Exception as _ov_e:
                pass  # overlay nunca deve crashar o recording

            state.record_thread = threading.Thread(target=record, daemon=True)
            state.record_thread.start()
        else:
            # Minimum recording time guard: ignore STOP if < 500ms from START.
            # Prevents the keyboard library double-fire (key-down + key-up ~350-400ms apart)
            # from triggering a premature STOP with frames=[] → error beep.
            elapsed = time.time() - state.record_start_time
            if elapsed < 0.5:
                print(f"[SKIP] STOP ignorado — gravação muito curta ({elapsed*1000:.0f}ms < 500ms)\n")
                return

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


# ── Hands-Free (VAD Auto-Start/Stop) ─────────────────────────────────────────

def hands_free_loop() -> None:
    """Background loop que monitora o microfone via VAD e auto-start/stop a gravação.

    Usa RMS como proxy simples de energia (sem dependência de Silero para este loop).
    Só executa se HANDS_FREE_ENABLED=true no .env.
    Thread daemon=True — nunca bloqueia o encerramento do app.
    """
    if state._CONFIG.get("HANDS_FREE_ENABLED", False) is not True:
        return

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

        with sd.InputStream(**stream_kwargs) as stream:
            while not state._shutdown_event.is_set():
                data, _ = stream.read(chunk_samples)

                # RMS do chunk como proxy de energia de fala
                rms = float(np.sqrt(np.mean(data ** 2)))
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
                            target=toggle_recording,
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
                            target=toggle_recording,
                            args=(state.selected_mode,),
                            daemon=True,
                        ).start()
                        time.sleep(1.0)
                        speech_frame_count = 0
                        silence_frame_count = 0

    except Exception as e:
        print(f"[ERRO] Hands-free loop: {e}")


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
