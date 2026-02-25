# voice/ai_provider.py — Facade: routes AI processing to Gemini or OpenAI

from voice import state


def process(mode: str, text: str) -> str:
    """Route text processing to the configured AI provider."""
    provider = state._CONFIG.get("AI_PROVIDER", "gemini").lower()
    if provider == "openai":
        return _dispatch_openai(mode, text)
    return _dispatch_gemini(mode, text)


def _dispatch_gemini(mode: str, text: str) -> str:
    from voice import gemini
    dispatch = {
        "transcribe": gemini.correct_with_gemini,
        "simple":     gemini.simplify_as_prompt,
        "prompt":     gemini.structure_as_prompt,
        "query":      gemini.query_with_gemini,
        "bullet":     gemini.bullet_dump_with_gemini,
        "email":      gemini.draft_email_with_gemini,
        "translate":  gemini.translate_with_gemini,
    }
    fn = dispatch.get(mode)
    if fn is None:
        return text
    return fn(text)


def _dispatch_openai(mode: str, text: str) -> str:
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
