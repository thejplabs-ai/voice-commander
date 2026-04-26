# voice/transcription.py — Transcription pipeline (extracted from voice/audio.py).
#
# Responsibility: orchestrate the post-recording pipeline:
#   capture WAV → STT (Whisper or Gemini) → snippet match → AI dispatch →
#   paste → overlay → cooldown → history → cleanup.
#
# The public entrypoint is `transcribe(frames, mode)`. It is decomposed into
# 9 helpers (`_capture_recording_ms`, `_validate_frames`, `_set_processing_state`,
# `_prepare_wav`, `_run_stt`, `_emit_empty_audio_error`,
# `_dispatch_transcribed_text`, `_handle_transcribe_error`, `_cleanup_transcribe`)
# so that `transcribe()` itself stays under 50 lines (HIGH-2 fix from SENTINEL).
#
# Test coupling — same lazy-lookup pattern as voice/recording.py / hands_free.py /
# sound.py. Tests patch attributes on the voice.audio facade module:
#   - patch("voice.audio.np"), patch("voice.audio.wave"), patch("voice.audio.tempfile")
#     (test_audio.py:394-396, 420-422)
#   - patch("voice.audio.os.unlink") (test_snippets.py:356,404)
#   - patch("voice.audio.ai_provider.process") (test_snippets.py:357,405)
#   - patch.object(audio, "_do_transcription", ...) (test_audio.py:397,423; test_snippets.py:328,375)
#   - patch.object(audio, "_post_process_and_paste", ...) (test_audio.py:398,424)
#   - patch.object(audio, "_update_tray_state") (test_audio.py:291,322,359,377,399,425)
#   - monkeypatch.setattr(audio, "copy_to_clipboard"|"paste_via_sendinput"|"play_sound"|
#     "_append_history"|"get_whisper_model", ...) (test_vad_fix.py + test_snippets.py)
#
# To honor those patches, every cross-module symbol referenced inside the
# functions below resolves at call time via `from voice import audio as _audio`.
# Module-level direct imports are kept here for static analysis but the runtime
# lookup goes through the voice.audio namespace — which is what monkeypatch
# targets.

import time

from voice import state


# ── Module-level constants (re-exported by voice.audio) ─────────────────────

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


# ── Whisper transcribe kwarg builder + fallback chain ────────────────────────

def _build_transcribe_kwargs(model, mode: str) -> tuple[dict, dict]:
    """Monta transcribe_kwargs e vad_params para model.transcribe.

    Retorna (transcribe_kwargs, vad_params).
    """
    import inspect as _inspect
    from voice.whisper import _DEFAULT_INITIAL_PROMPT as _PROMPT, _HOTWORDS as _HW

    lang_hint = state._CONFIG.get("WHISPER_LANGUAGE") or None
    vad_threshold = state._CONFIG.get("VAD_THRESHOLD", 0.3)
    beam_size = state._CONFIG.get("WHISPER_BEAM_SIZE", 1)

    initial_prompt = state._CONFIG.get("WHISPER_INITIAL_PROMPT") or _PROMPT
    try:
        from voice import vocabulary as _vocab
        initial_prompt += _vocab.get_initial_prompt_suffix()
    except Exception as _vocab_e:
        # Vocabulário nunca deve crashar a transcrição, mas regressões devem ser visíveis.
        print(f"[WARN] Vocabulário (initial_prompt) falhou ({type(_vocab_e).__name__}: {_vocab_e})")

    _transcribe_sig = _inspect.signature(model.transcribe)
    _supports_hotwords = "hotwords" in _transcribe_sig.parameters

    kwargs: dict = dict(
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
            kwargs["hotwords"] = _vocab.get_hotwords_string()
        except Exception:
            kwargs["hotwords"] = _HW

    vad_params = dict(
        threshold=vad_threshold,
        min_silence_duration_ms=500,
        speech_pad_ms=200,
    )
    return kwargs, vad_params


def _transcribe_no_vad_fallback(model, temp_path: str, kwargs: dict, err: Exception) -> tuple[str, object]:
    """Fallback: transcreve sem VAD quando silero/onnx indisponível.

    Retorna (raw_text, info).
    """
    print(f"[WARN]  VAD model indisponível ({type(err).__name__}) — usando transcrição sem VAD")
    segments, info = model.transcribe(temp_path, vad_filter=False, **kwargs)
    return " ".join(s.text for s in segments).strip(), info


def _transcribe_cpu_fallback(mode: str, temp_path: str, kwargs: dict, vad_params: dict, err: Exception) -> tuple[str, object]:
    """Fallback CUDA → CPU quando DLLs CUDA ausentes.

    Retorna (raw_text, info).
    """
    from voice import audio as _audio
    print(f"[WARN]  CUDA indisponível durante transcrição ({type(err).__name__}) — fallback CPU")
    print("[WARN]  Configure WHISPER_DEVICE=cpu em Configurações para evitar este fallback.")
    state._whisper_model = None
    state._whisper_cache_key = ()
    state._CONFIG["WHISPER_DEVICE"] = "cpu"
    model_cpu = _audio.get_whisper_model(mode)
    segments, info = model_cpu.transcribe(temp_path, vad_filter=True, vad_parameters=vad_params, **kwargs)
    return " ".join(s.text for s in segments).strip(), info


def _transcribe_model_fallback(mode: str, temp_path: str, kwargs: dict, vad_params: dict, err: Exception) -> tuple[str, object]:
    """Fallback quando modelo não encontrado no disco (symlink quebrado, download incompleto).

    Retorna (raw_text, info).
    """
    from voice import audio as _audio
    print(f"[WARN]  Modelo indisponível ({type(err).__name__}: {err})")
    state._whisper_model = None
    state._whisper_cache_key = ()
    state._CONFIG["WHISPER_DEVICE"] = "cpu"
    model_fallback = _audio.get_whisper_model(mode)
    segments, info = model_fallback.transcribe(temp_path, vad_filter=True, vad_parameters=vad_params, **kwargs)
    return " ".join(s.text for s in segments).strip(), info


def _transcribe_without_vad_on_empty(model, temp_path: str, kwargs: dict, info, audio_data, vad_threshold: float) -> str:
    """Fallback sem VAD quando VAD descartou o áudio.

    Chamado apenas quando raw_text vazio e audio_duration >= 2s com vad_duration == 0.
    Retorna raw_text (pode ser vazio se fallback retornar conteúdo suspeito).
    """
    from voice import audio as _audio
    audio_duration = len(audio_data) / _audio.SAMPLE_RATE
    vad_duration = getattr(info, "duration_after_vad", 0.0) or 0.0
    print(
        f"[WARN]  VAD descartou áudio (threshold={vad_threshold:.1f}, "
        f"gravação={audio_duration:.1f}s, fala_detectada={vad_duration:.1f}s)"
    )
    if audio_duration < 2.0 or vad_duration != 0.0:
        return ""

    print("[...]  Tentando sem filtro VAD (fallback)...")
    segments_fallback, _ = model.transcribe(temp_path, vad_filter=False, **kwargs)
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
        return raw_text_fallback
    print(f"[WARN]  Fallback retornou conteúdo suspeito — descartado: [{raw_text_fallback}]")
    return ""


# ── Core STT dispatch (Whisper or Gemini, with full fallback chain) ──────────

def _do_transcription(temp_path: str, mode: str, audio_data) -> str:
    """Executa transcrição no arquivo WAV e retorna o texto transcrito.

    Roteia para Gemini STT ou Whisper local com base em STT_PROVIDER.
    audio_data: numpy array concatenado (usado para calcular duração sem re-abrir WAV).
    Tenta com VAD primeiro; se VAD falhar, tenta sem VAD. Se o texto
    ficar vazio, tenta fallback sem VAD. Retorna string vazia se nada
    for reconhecido.
    """
    from voice import audio as _audio

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

    model = _audio.get_whisper_model(mode)
    vad_threshold = state._CONFIG.get("VAD_THRESHOLD", 0.3)
    kwargs, vad_params = _build_transcribe_kwargs(model, mode)
    info = None

    try:
        segments, info = model.transcribe(temp_path, vad_filter=True, vad_parameters=vad_params, **kwargs)
        raw_text = " ".join(s.text for s in segments).strip()
    except Exception as _vad_err:
        err_msg = str(_vad_err).lower()
        # Bug #2: OOM durante transcrição — log claro ANTES do fallback CUDA→CPU.
        # Check explícito antes do matcher genérico "cuda" para melhor diagnóstico.
        is_oom = (
            "out of memory" in err_msg
            or "oom" in err_msg
            or "cuda failed" in err_msg
        )
        if is_oom:
            current_device = state._CONFIG.get("WHISPER_DEVICE", "cpu")
            print(f"[ERRO] VRAM insuficiente durante transcrição em {current_device}. Fallback acionado.")
        if "silero" in err_msg or "onnx" in err_msg or "nosuchfile" in err_msg:
            raw_text, info = _transcribe_no_vad_fallback(model, temp_path, kwargs, _vad_err)
        elif is_oom or "cublas" in err_msg or "cuda" in err_msg or "cudnn" in err_msg or "library" in err_msg:
            raw_text, info = _transcribe_cpu_fallback(mode, temp_path, kwargs, vad_params, _vad_err)
        elif "unable to open" in err_msg or "model.bin" in err_msg or "no such file" in err_msg:
            raw_text, info = _transcribe_model_fallback(mode, temp_path, kwargs, vad_params, _vad_err)
        else:
            raise

    if not raw_text and info is not None:
        raw_text = _transcribe_without_vad_on_empty(model, temp_path, kwargs, info, audio_data, vad_threshold)

    return raw_text


# ── WAV writer ───────────────────────────────────────────────────────────────

def _write_audio_to_wav(frames: list, temp_path: str) -> object:
    """Escreve frames no arquivo WAV em temp_path.

    Retorna audio_data (numpy array concatenado).

    Lazy lookup via voice.audio: tests patch voice.audio.np and voice.audio.wave
    (test_audio.py:394-396, test_vad_fix.py:_patch_wav_pipeline) — resolving
    np/wave via the audio namespace ensures monkeypatches intercept.
    """
    from voice import audio as _audio
    audio_data = _audio.np.concatenate(frames, axis=0)
    with _audio.wave.open(temp_path, "wb") as wf:
        wf.setnchannels(_audio.CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(_audio.SAMPLE_RATE)
        wf.writeframes((audio_data * 32767).astype(_audio.np.int16).tobytes())
    return audio_data


# ── Snippet matching ─────────────────────────────────────────────────────────

def _try_snippet_match(raw_text: str, mode: str, t_start: float) -> bool:
    """Tenta match de snippet. Se encontrado, cola e registra history.

    Retorna True se snippet foi expandido (caller deve fazer early return).
    """
    from voice import audio as _audio
    try:
        from voice import snippets as _snippets
        snippet_text = _snippets.match_snippet(raw_text)
        if snippet_text is None:
            return False
        _audio.copy_to_clipboard(snippet_text)
        _audio.play_sound("success")
        paste_delay_ms = state._CONFIG.get("PASTE_DELAY_MS", 50)
        time.sleep(max(0, paste_delay_ms) / 1000.0 + 0.1)
        _audio.paste_via_sendinput()
        print(f"[OK]   Snippet expandido ({len(snippet_text)} chars)")
        try:
            from voice import overlay as _overlay
            _overlay.show_done(snippet_text)
        except Exception:
            pass
        duration = time.time() - t_start
        _audio._append_history(mode, raw_text, snippet_text, duration)
        return True
    except Exception:
        return False  # snippets nunca devem crashar a transcrição


# ── Timing log ───────────────────────────────────────────────────────────────

def _build_timing_and_log(recording_ms: int, whisper_ms: int, gemini_ms: int, paste_ms: int, t_mono_start: float) -> dict:
    """Monta timing dict e emite log [PERF] se DEBUG_PERF=true.

    Retorna timing dict.
    """
    total_ms = int((time.monotonic() - t_mono_start) * 1000)
    timing: dict = {
        "recording": recording_ms,
        "whisper": whisper_ms,
        "total": total_ms,
    }
    if gemini_ms > 0:
        timing["gemini"] = gemini_ms
    if paste_ms > 0:
        timing["paste"] = paste_ms

    if state._CONFIG.get("DEBUG_PERF", False) is True:
        parts = [f"Gravação: {recording_ms/1000:.1f}s", f"Whisper: {whisper_ms/1000:.1f}s"]
        if gemini_ms > 0:
            parts.append(f"Gemini: {gemini_ms/1000:.1f}s")
        if paste_ms > 0:
            parts.append(f"Paste: {paste_ms/1000:.1f}s")
        parts.append(f"Total: {total_ms/1000:.1f}s")
        print(f"[PERF] {' | '.join(parts)}")

    return timing


# ── AI dispatch + paste ──────────────────────────────────────────────────────

def _post_process_and_paste(raw_text: str, mode: str) -> tuple:
    """Processa texto via AI, copia para clipboard e cola.

    Retorna (texto_processado, gemini_ms, paste_ms).

    Lazy lookup via voice.audio: tests patch voice.audio.ai_provider.process
    (test_snippets.py:357,405), voice.audio.copy_to_clipboard, voice.audio.play_sound,
    voice.audio.paste_via_sendinput (test_vad_fix.py + test_snippets.py).
    """
    from voice import audio as _audio
    action = _audio._MODE_ACTIONS.get(mode, "Processando")
    print(f"[...]  {action}...")

    t_gemini_start = time.monotonic()
    text = _audio.ai_provider.process(mode, raw_text)
    gemini_ms = int((time.monotonic() - t_gemini_start) * 1000)

    _audio.copy_to_clipboard(text)
    print(f"[OK]   Texto no clipboard ({len(text)} chars)")

    _audio.play_sound("success")
    paste_delay_ms = state._CONFIG.get("PASTE_DELAY_MS", 50)
    paste_delay_s = max(0, paste_delay_ms) / 1000.0 + 0.1  # base 100ms + configurável

    t_paste_start = time.monotonic()
    time.sleep(paste_delay_s)
    _audio.paste_via_sendinput()
    paste_ms = int((time.monotonic() - t_paste_start) * 1000)

    print("[OK]   Colado!\n")
    return text, gemini_ms, paste_ms


# ── VRAM cleanup ─────────────────────────────────────────────────────────────

def _release_vram_if_cuda() -> None:
    """Libera VRAM fragmentada pós-transcrição em CUDA.

    Só executa se o device atual é CUDA — evita custo no hot path de CPU.
    Silencioso: é otimização, não crítico. Fallback para gc.collect() quando
    torch não está instalado (faster-whisper traz ctranslate2, não torch).
    """
    device = state._CONFIG.get("WHISPER_DEVICE", "cpu")
    if device != "cuda":
        return
    try:
        import torch  # noqa: PLC0415 — lazy, torch é opcional
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            return
    except Exception:
        pass
    # Fallback: sem torch instalado, ao menos provoca coleta de objetos ctranslate2
    try:
        import gc
        gc.collect()
    except Exception:
        pass


# ── transcribe() decomposition — 9 helpers + orchestrator ────────────────────

def _capture_recording_ms() -> int:
    """Story 4.6.6: captura tempo de gravação a partir de state.record_start_time."""
    if hasattr(state, "record_start_time") and state.record_start_time > 0:
        return int((time.time() - state.record_start_time) * 1000)
    return 0


def _validate_frames(frames: list, mode: str) -> bool:
    """Valida que há frames para transcrever. Loga erro e atualiza history se vazio.

    Retorna True se válido (caller continua), False se inválido (caller faz early return).
    """
    from voice import audio as _audio
    if frames:
        return True
    print("[ERRO]  Sem áudio\n")
    _audio.play_sound("error")
    _audio._append_history(mode, "", None, 0.0, error=True)
    return False


def _set_processing_state(mode: str) -> None:
    """Atualiza tray + overlay para o estado 'processando' e emite log."""
    from voice import audio as _audio
    _audio._update_tray_state("processing", mode)

    # Story 4.5.1: overlay "Processando"
    try:
        from voice import overlay as _overlay
        _overlay.show_processing(mode)
    except Exception:
        pass

    stt_provider = state._CONFIG.get("STT_PROVIDER", "whisper").title()
    print(f"[...]  Transcrevendo ({stt_provider})...")


def _prepare_wav(frames: list) -> tuple:
    """Cria arquivo temporário WAV e escreve frames nele.

    Retorna (temp_path, audio_data). audio_data é numpy array concatenado.
    """
    from voice import audio as _audio
    with _audio.tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        temp_path = f.name
    audio_data = _write_audio_to_wav(frames, temp_path)
    return temp_path, audio_data


def _run_stt(temp_path: str, mode: str, audio_data) -> tuple:
    """Executa STT medindo latência da fase Whisper/Gemini.

    Retorna (raw_text, whisper_ms).
    """
    from voice import audio as _audio
    t_whisper_start = time.monotonic()
    raw_text = _audio._do_transcription(temp_path, mode, audio_data)
    whisper_ms = int((time.monotonic() - t_whisper_start) * 1000)
    return raw_text, whisper_ms


def _emit_empty_audio_error(mode: str, t_start: float) -> None:
    """Emite mensagem de erro 'não entendi' + beep + history quando STT retorna vazio."""
    from voice import audio as _audio
    print(
        "[ERRO]  Não entendi. Verifique o volume do microfone"
        " (Configurações > Som > Dispositivos de entrada).\n"
    )
    _audio.play_sound("error")
    duration = time.time() - t_start
    _audio._append_history(mode, "", None, duration, error=True)


def _dispatch_transcribed_text(
    raw_text: str,
    mode: str,
    t_start: float,
    t_mono_start: float,
    recording_ms: int,
    whisper_ms: int,
) -> None:
    """Despacha texto transcrito: log → snippet match → AI → overlay → cooldown → history.

    Caso o snippet match seja bem-sucedido, retorna sem chamar AI.
    """
    from voice import audio as _audio
    stt_provider = state._CONFIG.get("STT_PROVIDER", "whisper").title()
    print(f"[OK]   {stt_provider}: {raw_text}")

    # Epic 5.2: Snippet matching — expandir antes do processamento AI
    if _audio._try_snippet_match(raw_text, mode, t_start):
        return

    text, gemini_ms, paste_ms = _audio._post_process_and_paste(raw_text, mode)

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
    timing = _build_timing_and_log(recording_ms, whisper_ms, gemini_ms, paste_ms, t_mono_start)
    _audio._append_history(mode, raw_text, text, duration, timing_ms=timing)


def _handle_transcribe_error(e: Exception, mode: str, t_start: float) -> None:
    """Trata exceção inesperada em transcribe(): log + traceback + history error."""
    import traceback as _tb
    from voice import audio as _audio
    print(f"[ERRO]  {type(e).__name__}: {e}\n")
    print(f"[DEBUG] {_tb.format_exc()}")
    _audio.play_sound("error")
    duration = time.time() - t_start
    _audio._append_history(mode, "", None, duration, error=True)


def _cleanup_transcribe(temp_path) -> None:
    """Cleanup pós-transcrição: state, temp file, VRAM, tray, overlay.

    Chamado no finally do transcribe(). Não levanta exceções.
    """
    from voice import audio as _audio
    state.is_transcribing = False
    # Limpar dados de sessão para evitar memory leak
    state._clipboard_context = ""
    if temp_path:
        try:
            _audio.os.unlink(temp_path)
        except Exception as e:
            print(f"[WARN] Falha ao deletar arquivo temporário {temp_path}: {e}")
    # Bug #2: limpar VRAM fragmentada entre transcrições. Só executa em CUDA
    # — evita custo desnecessário no hot path de CPU. Silencioso porque é
    # otimização, não crítico.
    _release_vram_if_cuda()
    _audio._update_tray_state("idle")
    # Story 4.5.1: esconder overlay se não foi para "done" (erro path)
    try:
        from voice import overlay as _overlay
        if _overlay._thread and _overlay._thread._current_state not in ("done", "hide"):
            _overlay.hide()
    except Exception:
        pass


def transcribe(frames: list, mode: str = "transcribe") -> None:
    """Top-level orchestrator. Coordinates capture → dispatch → cleanup."""
    t_start = time.time()
    t_mono_start = time.monotonic()
    recording_ms = _capture_recording_ms()
    temp_path = None

    try:
        if not _validate_frames(frames, mode):
            return

        _set_processing_state(mode)

        temp_path, audio_data = _prepare_wav(frames)
        raw_text, whisper_ms = _run_stt(temp_path, mode, audio_data)

        if not raw_text:
            _emit_empty_audio_error(mode, t_start)
            return

        _dispatch_transcribed_text(
            raw_text, mode, t_start, t_mono_start, recording_ms, whisper_ms
        )
    except Exception as e:
        _handle_transcribe_error(e, mode, t_start)
    finally:
        _cleanup_transcribe(temp_path)
