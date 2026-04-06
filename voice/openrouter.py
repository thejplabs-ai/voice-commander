# voice/openrouter.py — OpenRouter gateway (single API key for all models)
#
# OpenRouter proxies all major providers (Gemini, Llama, Claude, GPT, etc.)
# via a single OpenAI-compatible API endpoint.
#
# Smart routing:
#   Fast modes (transcribe, email, bullet, translate) → Llama 4 Scout
#   Quality modes (simple, prompt, query) → Gemini 2.5 Flash

import threading

from voice import state
from voice.ai_provider import retry_api_call

_client_lock = threading.Lock()
_client = None

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Modelos default
_MODEL_FAST = "meta-llama/llama-4-scout-17b-16e-instruct"
_MODEL_QUALITY = "google/gemini-2.5-flash"

# Modos rápidos que usam o modelo fast
FAST_MODES = {"transcribe", "email", "bullet", "translate"}


def _get_client():
    """Retorna o cliente OpenRouter (OpenAI-compatible), criando na primeira chamada."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                try:
                    from openai import OpenAI
                except ImportError as exc:
                    raise ImportError("openai-not-installed") from exc
                api_key = state._CONFIG.get("OPENROUTER_API_KEY")
                _client = OpenAI(
                    api_key=api_key,
                    base_url=_OPENROUTER_BASE_URL,
                )
    return _client


def reset_client() -> None:
    """Reset singleton quando a key muda."""
    global _client
    with _client_lock:
        _client = None


def _model_for_mode(mode: str) -> str:
    """Retorna o modelo correto para o modo."""
    if mode in FAST_MODES:
        return state._CONFIG.get("OPENROUTER_MODEL_FAST", _MODEL_FAST)
    return state._CONFIG.get("OPENROUTER_MODEL_QUALITY", _MODEL_QUALITY)


def _is_rate_limit(e: Exception) -> bool:
    """Detecta rate limit (type-safe + string fallback)."""
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
        "[LIMITE ATINGIDO] Rate limit atingido.\n"
        "Aguarde alguns instantes e use o atalho novamente."
    )


def _call(system: str, user: str, model: str, temperature: float = 0.2) -> str | None:
    """Chamada generica ao OpenRouter."""
    client = _get_client()

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


# ── Mode functions ────────────────────────────────────────────────────────────

_SYSTEM_MINIMAL = (
    "You are a MINIMALIST voice transcription corrector.\n"
    "ABSOLUTE RULES:\n"
    "- Do NOT translate anything. If a word is in English, keep it in English.\n"
    "- Do NOT change meaning or reorganize sentences.\n"
    "- Do NOT expand abbreviations or acronyms.\n"
    "- Preserve code-switching (PT+EN mix) exactly as-is.\n"
    "- When in doubt, preserve the original text.\n"
    "- Return ONLY the corrected text, no explanations."
)

_SYSTEM_SMART = (
    "You are a smart voice transcription corrector.\n"
    "RULES:\n"
    "- Add punctuation automatically (periods, commas, question marks, exclamation marks).\n"
    "- Capitalize sentence beginnings.\n"
    "- Format numbers naturally (e.g., 'two hundred fifty' -> '250').\n"
    "- Fix obvious transcription spelling errors.\n"
    "- Do NOT translate anything. If a word is in English, keep it in English.\n"
    "- Do NOT change meaning or reorganize sentences.\n"
    "- Do NOT expand abbreviations or acronyms.\n"
    "- Preserve code-switching (PT+EN mix) exactly as-is.\n"
    "- Return ONLY the corrected text, no explanations."
)


def correct(text: str) -> str:
    """Correção de transcrição de voz. Estilo controlado por CORRECTION_STYLE."""
    correction_style = state._CONFIG.get("CORRECTION_STYLE", "smart")

    # "off" bypassa completamente — sem chamada à API
    if correction_style == "off":
        return text

    if state._CONFIG.get("GEMINI_CORRECT", True) is not True:
        return text
    try:
        system = _SYSTEM_MINIMAL if correction_style == "minimal" else _SYSTEM_SMART
        result = _call(system, text, _model_for_mode("transcribe"), temperature=0.0)
        if result:
            print(f"[OK]   Original : {text}")
            print(f"[OK]   Corrigido: {result}")
            # Aprendizado de vocabulário por correção
            try:
                from voice import vocabulary as _vocab
                candidates = _vocab.learn_from_correction(text, result)
                if candidates:
                    for word in candidates:
                        _vocab.add_word(word)
                    print(f"[INFO] Vocabulário: +{len(candidates)} palavras ({', '.join(candidates)})")
            except Exception:
                pass  # vocabulário nunca deve crashar a correção
            return result
    except Exception as e:
        if _is_rate_limit(e):
            return _rate_limit_msg()
        print(f"[WARN] OpenRouter indisponível ({e}), usando texto original")
    return text


def simplify(text: str) -> str:
    """Organiza transcrição em prompt limpo com bullet points."""
    try:
        system = (
            "You are a prompt engineering specialist. "
            "Transform the voice transcription into a clean, direct prompt for any LLM. "
            "ABSOLUTE PRIORITY: Preserve EVERY detail, context and nuance. "
            "No XML, no SYSTEM/USER sections, no headers, no labels like 'Context:' or 'Objective:'. "
            "Bullet points should be complete sentences. "
            "Return ONLY the prompt, no additional explanations."
        )
        result = _call(system, text, _model_for_mode("simple"), temperature=0.1)
        if result:
            print(f"[OK]   Prompt simplificado ({len(result)} chars)")
            return result
    except Exception as e:
        if _is_rate_limit(e):
            return _rate_limit_msg()
        print(f"[WARN] OpenRouter indisponível ({e}), retornando texto original")
    return text


def structure(text: str) -> str:
    """Estrutura transcrição em prompt COSTAR com XML tags."""
    try:
        system = (
            "You are a prompt engineering specialist for LLMs (Claude, GPT-4, Gemini). "
            "Transform the voice transcription into a professional structured prompt using the COSTAR framework with XML tags. "
            "Format: SYSTEM PROMPT section with <role>, <behavior>, <output_format> tags; "
            "USER PROMPT section with <context>, <objective>, <style_and_tone>, <response> tags. "
            "Be specific in all sections. Return ONLY the structured prompt, no explanations."
        )
        result = _call(system, text, _model_for_mode("prompt"), temperature=0.2)
        if result:
            print(f"[OK]   Prompt estruturado ({len(result)} chars)")
            return result
    except Exception as e:
        if _is_rate_limit(e):
            return _rate_limit_msg()
        print(f"[WARN] OpenRouter indisponível ({e}), retornando texto original")
    return text


def query(text: str) -> str:
    """Envia pergunta e retorna resposta."""
    try:
        system_prompt = state._CONFIG.get("QUERY_SYSTEM_PROMPT", "").strip()
        if not system_prompt:
            system_prompt = (
                "You are a direct and precise assistant. "
                "Answer the user's question clearly, concisely, and helpfully. "
                "Go straight to the point without unnecessary filler. "
                "The text may mix Portuguese and English — respond in the same language as the question."
            )
        system = system_prompt
        result = _call(system, text, _model_for_mode("query"), temperature=0.3)
        if result:
            print(f"[OK]   Resposta ({len(result)} chars)")
            return result
    except Exception as e:
        if _is_rate_limit(e):
            return _rate_limit_msg()
        print(f"[WARN] OpenRouter indisponível ({e})")
    return f"[SEM RESPOSTA] {text}"


def query_with_clipboard(text: str, clipboard_content: str) -> str:
    """Query com contexto do clipboard."""
    if not clipboard_content.strip():
        return query(text)
    try:
        system_prompt = state._CONFIG.get("QUERY_SYSTEM_PROMPT", "").strip()
        if not system_prompt:
            system_prompt = (
                "You are a direct and precise assistant. "
                "Answer the user's question clearly, concisely, and helpfully."
            )
        system = system_prompt
        user = f"[CONTEXTO DO CLIPBOARD]\n{clipboard_content}\n\n[INSTRUCAO]\n{text}"
        result = _call(system, user, _model_for_mode("query"), temperature=0.3)
        if result:
            print(f"[OK]   Resposta clipboard-context ({len(result)} chars)")
            return result
    except Exception as e:
        if _is_rate_limit(e):
            return _rate_limit_msg()
        print(f"[WARN] OpenRouter indisponível ({e})")
    return f"[SEM RESPOSTA] {text}"


def bullet_dump(text: str) -> str:
    """Transforma transcrição em bullets hierárquicos."""
    try:
        system = (
            "Transform the voice transcription into hierarchical bullet points. "
            "Preserve ALL content — zero omission. "
            "Use ## for H1, ### for H2, and - for items where appropriate. "
            "Return ONLY the bullet points, no explanations."
        )
        result = _call(system, text, _model_for_mode("bullet"), temperature=0.2)
        if result:
            print(f"[OK]   Bullet dump ({len(result)} chars)")
            return result
    except Exception as e:
        if _is_rate_limit(e):
            return _rate_limit_msg()
        print(f"[WARN] OpenRouter indisponível ({e}), retornando texto original")
    return text


def draft_email(text: str) -> str:
    """Transforma transcrição em email profissional."""
    try:
        system = (
            "Transform the voice transcription into a professional email. "
            "Structure: Subject line, body paragraphs, and signature placeholder '{Nome}'. "
            "Direct professional tone, no hype. "
            "Return ONLY the email, no additional explanations."
        )
        result = _call(system, text, _model_for_mode("email"), temperature=0.3)
        if result:
            print(f"[OK]   Email draft ({len(result)} chars)")
            return result
    except Exception as e:
        if _is_rate_limit(e):
            return _rate_limit_msg()
        print(f"[WARN] OpenRouter indisponível ({e}), retornando texto original")
    return text


def command(instruction: str, selected_text: str) -> str:
    """Epic 5.0: Aplica instrução de voz sobre texto selecionado e retorna o resultado."""
    try:
        system = (
            "You are a text editing assistant. The user has selected text and spoken an instruction. "
            "Apply the instruction to the selected text. "
            "Return ONLY the modified text, no explanations, no quotes, no markdown formatting "
            "unless the instruction specifically asks for it."
        )
        user = f"[SELECTED TEXT]\n{selected_text}\n\n[INSTRUCTION]\n{instruction}"
        result = _call(system, user, _model_for_mode("query"), temperature=0.2)
        if result:
            print(f"[OK]   Comando aplicado ({len(result)} chars)")
            return result
    except Exception as e:
        if _is_rate_limit(e):
            return _rate_limit_msg()
        print(f"[WARN] OpenRouter indisponível ({e}), retornando texto selecionado")
    return selected_text


def translate(text: str) -> str:
    """Detecta idioma e traduz."""
    try:
        target_lang = state._CONFIG.get("TRANSLATE_TARGET_LANG", "en")
        lang_name = "English" if target_lang == "en" else "Brazilian Portuguese"
        system = (
            f"Detect the language of the input text and translate it to {lang_name}. "
            "Preserve the original formatting. "
            "Return ONLY the translated text, no explanations."
        )
        result = _call(system, text, _model_for_mode("translate"), temperature=0.1)
        if result:
            print(f"[OK]   Traduzido -> {target_lang} ({len(result)} chars)")
            return result
    except Exception as e:
        if _is_rate_limit(e):
            return _rate_limit_msg()
        print(f"[WARN] OpenRouter indisponível ({e}), retornando texto original")
    return text


