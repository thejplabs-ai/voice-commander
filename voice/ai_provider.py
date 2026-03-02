# voice/ai_provider.py — Facade: routes AI processing to Gemini or OpenAI

import time

from voice import state


def process(mode: str, text: str) -> str:
    """Route text processing to the configured AI provider.

    Aplica cooldown de _AI_COOLDOWN_SECONDS entre chamadas consecutivas (SEC-05).
    Se dentro do cooldown, loga [SKIP] e retorna o texto original sem chamar a API.
    """
    now = time.monotonic()
    elapsed = now - state._ai_last_call_time
    cooldown = state._AI_COOLDOWN_SECONDS
    if state._ai_last_call_time > 0 and elapsed < cooldown:
        remaining = cooldown - elapsed
        print(f"[SKIP] Cooldown ativo ({remaining:.1f}s restantes) — chamada AI ignorada")
        return text

    state._ai_last_call_time = time.monotonic()

    provider = state._CONFIG.get("AI_PROVIDER", "gemini").lower()
    if provider == "openai":
        return _dispatch_openai(mode, text)
    return _dispatch_gemini(mode, text)


def _dispatch_gemini(mode: str, text: str) -> str:
    from voice import gemini

    # Feature 1: detectar trigger de voz para adicionar ao perfil (só modo transcribe)
    if mode == "transcribe":
        _PROFILE_TRIGGERS = ["adiciona ao meu perfil:", "add to my profile:"]
        for trigger in _PROFILE_TRIGGERS:
            if text.lower().startswith(trigger):
                fact = text[text.index(":") + 1:].strip()
                if fact:
                    try:
                        from voice.user_profile import add_fact, load_profile
                        add_fact(fact)
                        state._user_profile = load_profile()
                    except Exception as _e:
                        print(f"[WARN] Falha ao adicionar fato ao perfil: {_e}")
                    return f"[Perfil atualizado] {fact}"
                return text

    # Story 4.5.4: modo query usa clipboard context se disponível
    if mode == "query":
        clipboard_ctx = state._clipboard_context if hasattr(state, "_clipboard_context") else ""
        if clipboard_ctx and state._CONFIG.get("CLIPBOARD_CONTEXT_ENABLED", "true").lower() == "true":
            return gemini.query_with_clipboard_context(text, clipboard_ctx)
        return gemini.query_with_gemini(text)

    # Feature 3: Visual Query
    if mode == "visual":
        image_bytes = getattr(state, "_screenshot_bytes", None)
        return gemini.visual_query_with_gemini(text, image_bytes)

    # Feature 5: Pipeline Composto
    if mode == "pipeline":
        source = getattr(state, "_clipboard_context", "")
        return gemini.execute_pipeline(text, source)

    dispatch = {
        "transcribe": gemini.correct_with_gemini,
        "simple":     gemini.simplify_as_prompt,
        "prompt":     gemini.structure_as_prompt,
        "bullet":     gemini.bullet_dump_with_gemini,
        "email":      gemini.draft_email_with_gemini,
        "translate":  gemini.translate_with_gemini,
    }
    fn = dispatch.get(mode)
    if fn is None:
        return text
    return fn(text)


def _dispatch_openai(mode: str, text: str) -> str:
    if not state._CONFIG.get("OPENAI_API_KEY"):
        print("[WARN] AI_PROVIDER=openai mas OPENAI_API_KEY não configurada — retornando texto sem processar")
        return text
    from voice import openai_
    dispatch = {
        "transcribe": openai_.correct_with_openai,
        "simple":     openai_.simplify_with_openai,
        "prompt":     openai_.structure_as_prompt_openai,
        "query":      openai_.query_with_openai,
        "bullet":     openai_.bullet_dump_with_openai,
        "email":      openai_.draft_email_with_openai,
        "translate":  openai_.translate_with_openai,
    }
    fn = dispatch.get(mode)
    if fn is None:
        return text
    return fn(text)
