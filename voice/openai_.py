# voice/openai_.py — OpenAI client singleton and text processing helpers

import threading

from voice import state
from voice.ai_provider import retry_api_call

_openai_lock = threading.Lock()

_DEFAULT_QUERY_SYSTEM_PROMPT = (
    "You are a direct and precise assistant. "
    "Answer the user's question clearly, concisely, and helpfully. "
    "Go straight to the point without unnecessary filler. "
    "The text may mix Portuguese and English — respond in the same language as the question."
)


def _get_openai_client():
    """Retorna o cliente OpenAI, criando-o na primeira chamada (lazy init, thread-safe)."""
    if state._openai_client is None:
        with _openai_lock:
            # Double-checked locking: re-verificar após adquirir o lock
            if state._openai_client is None:
                try:
                    import openai
                except ImportError as exc:
                    raise ImportError("openai-not-installed") from exc
                state._OPENAI_API_KEY = state._CONFIG.get("OPENAI_API_KEY")
                state._openai_client = openai.OpenAI(api_key=state._OPENAI_API_KEY)
    return state._openai_client


def _is_rate_limit(e: Exception) -> bool:
    """Detecta rate limit OpenAI (type-safe + string fallback)."""
    try:
        import openai
        if hasattr(openai, "RateLimitError") and isinstance(e, openai.RateLimitError):
            return True
    except (ImportError, TypeError):
        pass
    msg = str(e).lower()
    return "429" in msg or "rate_limit" in msg or "ratelimit" in msg


def _rate_limit_msg() -> str:
    return (
        "[LIMITE ATINGIDO] OpenAI rate limit atingido.\n"
        "Aguarde alguns instantes e use o atalho novamente."
    )


def _missing_package_msg() -> str:
    return (
        "[ERRO] Pacote 'openai' não instalado.\n"
        "Execute: pip install \"openai>=1.0.0\" e reinicie o app."
    )


def _call(system: str, user: str, temperature: float = 0.2) -> str | None:
    client = _get_openai_client()
    model = state._CONFIG.get("OPENAI_MODEL", "gpt-4o-mini")

    def _api_call():
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
        )
        choices = response.choices or []
        if not choices or not choices[0].message.content:
            return None
        return choices[0].message.content.strip()

    return retry_api_call(_api_call, _is_rate_limit)


def correct_with_openai(text: str) -> str:
    if not state._CONFIG.get("OPENAI_API_KEY"):
        return text
    try:
        system = (
            "You are a MINIMALIST voice transcription corrector.\n"
            "ABSOLUTE RULES:\n"
            "- Do NOT translate anything. If a word is in English, keep it in English.\n"
            "- Do NOT change meaning or reorganize sentences.\n"
            "- Do NOT expand abbreviations or acronyms.\n"
            "- Preserve code-switching (PT+EN mix) exactly as-is.\n"
            "- When in doubt, preserve the original text.\n"
            "- Return ONLY the corrected text, no explanations."
        )
        result = _call(system, text, temperature=0.0)
        if result:
            print(f"[OK]   Corrigido (OpenAI): {result[:80]}")
            return result
    except Exception as e:
        if isinstance(e, ImportError):
            return _missing_package_msg()
        if _is_rate_limit(e):
            return _rate_limit_msg()
        print(f"[WARN] OpenAI indisponível ({e}), usando texto original")
    return text


def simplify_with_openai(text: str) -> str:
    if not state._CONFIG.get("OPENAI_API_KEY"):
        return text
    try:
        system = (
            "You are a prompt engineering specialist. "
            "Transform the voice transcription into a clean, direct prompt for any LLM. "
            "ABSOLUTE PRIORITY: Preserve EVERY detail, context and nuance. "
            "No XML, no SYSTEM/USER sections, no headers, no labels like 'Context:' or 'Objective:'. "
            "Bullet points should be complete sentences. "
            "Return ONLY the prompt, no additional explanations."
        )
        result = _call(system, text, temperature=0.1)
        if result:
            print(f"[OK]   Prompt simplificado (OpenAI, {len(result)} chars)")
            return result
    except Exception as e:
        if isinstance(e, ImportError):
            return _missing_package_msg()
        if _is_rate_limit(e):
            return _rate_limit_msg()
        print(f"[WARN] OpenAI indisponível ({e}), retornando texto original")
    return text


def structure_as_prompt_openai(text: str) -> str:
    if not state._CONFIG.get("OPENAI_API_KEY"):
        return text
    try:
        system = (
            "You are a prompt engineering specialist for LLMs (Claude, GPT-4, Gemini). "
            "Transform the voice transcription into a professional structured prompt using the COSTAR framework with XML tags. "
            "Format: SYSTEM PROMPT section with <role>, <behavior>, <output_format> tags; "
            "USER PROMPT section with <context>, <objective>, <style_and_tone>, <response> tags. "
            "Be specific in all sections. Return ONLY the structured prompt, no explanations."
        )
        result = _call(system, text, temperature=0.2)
        if result:
            print(f"[OK]   Prompt COSTAR (OpenAI, {len(result)} chars)")
            return result
    except Exception as e:
        if isinstance(e, ImportError):
            return _missing_package_msg()
        if _is_rate_limit(e):
            return _rate_limit_msg()
        print(f"[WARN] OpenAI indisponível ({e}), retornando texto original")
    return text


def query_with_openai(text: str) -> str:
    if not state._CONFIG.get("OPENAI_API_KEY"):
        return f"[SEM RESPOSTA] {text}"
    try:
        system_prompt = state._CONFIG.get("QUERY_SYSTEM_PROMPT", "").strip()
        if not system_prompt:
            system_prompt = _DEFAULT_QUERY_SYSTEM_PROMPT
        result = _call(system_prompt, text, temperature=0.3)
        if result:
            print(f"[OK]   Resposta OpenAI ({len(result)} chars)")
            return result
    except Exception as e:
        if isinstance(e, ImportError):
            return _missing_package_msg()
        if _is_rate_limit(e):
            return _rate_limit_msg()
        print(f"[WARN] OpenAI indisponível ({e}), retornando transcrição com prefixo")
    return f"[SEM RESPOSTA] {text}"


def bullet_dump_with_openai(text: str) -> str:
    if not state._CONFIG.get("OPENAI_API_KEY"):
        return text
    try:
        system = (
            "Transform the voice transcription into hierarchical bullet points. "
            "Preserve ALL content — zero omission. "
            "Use ## for H1, ### for H2, and - for items where appropriate. "
            "Return ONLY the bullet points, no explanations."
        )
        result = _call(system, text, temperature=0.2)
        if result:
            print(f"[OK]   Bullet dump (OpenAI, {len(result)} chars)")
            return result
    except Exception as e:
        if isinstance(e, ImportError):
            return _missing_package_msg()
        if _is_rate_limit(e):
            return _rate_limit_msg()
        print(f"[WARN] OpenAI indisponível ({e}), retornando texto original")
    return text


def draft_email_with_openai(text: str) -> str:
    if not state._CONFIG.get("OPENAI_API_KEY"):
        return text
    try:
        system = (
            "Transform the voice transcription into a professional email. "
            "Structure: Subject line, body paragraphs, and signature placeholder '{Nome}'. "
            "Direct professional tone, no hype. "
            "Return ONLY the email, no additional explanations."
        )
        result = _call(system, text, temperature=0.3)
        if result:
            print(f"[OK]   Email draft (OpenAI, {len(result)} chars)")
            return result
    except Exception as e:
        if isinstance(e, ImportError):
            return _missing_package_msg()
        if _is_rate_limit(e):
            return _rate_limit_msg()
        print(f"[WARN] OpenAI indisponível ({e}), retornando texto original")
    return text


def translate_with_openai(text: str) -> str:
    if not state._CONFIG.get("OPENAI_API_KEY"):
        return text
    try:
        target_lang = state._CONFIG.get("TRANSLATE_TARGET_LANG", "en")
        lang_name = "English" if target_lang == "en" else "Brazilian Portuguese"
        system = (
            f"Detect the language of the input text and translate it to {lang_name}. "
            "Preserve the original formatting. "
            "Return ONLY the translated text, no explanations."
        )
        result = _call(system, text, temperature=0.1)
        if result:
            print(f"[OK]   Traduzido → {target_lang} (OpenAI, {len(result)} chars)")
            return result
    except Exception as e:
        if isinstance(e, ImportError):
            return _missing_package_msg()
        if _is_rate_limit(e):
            return _rate_limit_msg()
        print(f"[WARN] OpenAI indisponível ({e}), retornando texto original")
    return text
