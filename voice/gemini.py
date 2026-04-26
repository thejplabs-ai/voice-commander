# voice/gemini.py — Gemini client singleton and text processing helpers

import threading

from voice import state, gemini_prompts as _gp
from voice.ai_provider import retry_api_call

_gemini_lock = threading.Lock()

_DEFAULT_QUERY_SYSTEM_PROMPT = (
    "Você é um assistente direto e preciso. "
    "Responda à pergunta do usuário de forma clara, concisa e útil. "
    "Vá direto ao ponto sem rodeios desnecessários. "
    "O texto pode misturar português e inglês — responda no mesmo idioma da pergunta."
)

# ── Epic 5.5: Hints de contexto por categoria ─────────────────────────────────
# Dicas adicionais injetadas nos prompts quando WINDOW_CONTEXT_ENABLED=true.
# Categorias sem hint ("other", "browser", etc.) não adicionam texto ao prompt.

_CATEGORY_HINTS: dict[str, str] = {
    "email": "O usuário está escrevendo em um cliente de email. Use tom profissional.",
    "code_editor": (
        "O usuário está em um editor de código. "
        "Preserve termos técnicos e formatação de código."
    ),
    "chat": "O usuário está em um chat. Use tom casual e direto.",
    "document": "O usuário está editando um documento. Use linguagem clara e formal.",
    "spreadsheet": "O usuário está em uma planilha. Seja preciso e objetivo.",
    "presentation": "O usuário está em uma apresentação. Prefira linguagem clara e visual.",
    "text_editor": "O usuário está em um editor de texto simples. Seja direto.",
    "terminal": (
        "O usuário está em um terminal. "
        "Preserve comandos e sintaxe exatamente como estão."
    ),
}


def _build_context_prefix() -> str:
    """
    Epic 5.5: Constrói prefixo de contexto para injeção nos prompts de AI.

    Combina contexto de janela (processo/categoria) quando WINDOW_CONTEXT_ENABLED=true.
    Retorna string vazia se a feature está desabilitada ou sem contexto relevante.
    """
    if not state._CONFIG.get("WINDOW_CONTEXT_ENABLED", False):
        return ""

    ctx = getattr(state, "_window_context", {})
    if not ctx:
        return ""

    category = ctx.get("category", "other")
    hint = _CATEGORY_HINTS.get(category, "")
    if not hint:
        return ""

    return hint + "\n\n"


def _get_gemini_client():
    """Retorna o cliente Gemini, criando-o na primeira chamada (lazy init, thread-safe)."""
    with _gemini_lock:
        if state._gemini_client is None:
            from google import genai
            state._gemini_client = genai.Client(api_key=state._GEMINI_API_KEY)
    return state._gemini_client


def _is_rate_limit(e: Exception) -> bool:
    """Detecta erro 429 / RESOURCE_EXHAUSTED do Gemini (type-safe + string fallback)."""
    try:
        from google.api_core.exceptions import ResourceExhausted, TooManyRequests
        if isinstance(e, (ResourceExhausted, TooManyRequests)):
            return True
    except ImportError:
        pass
    msg = str(e).lower()
    return "429" in msg or "resource_exhausted" in msg or "exhausted" in msg or "quota" in msg


def _safe_text(response) -> str:
    """Extrai texto da resposta Gemini com null safety."""
    return (getattr(response, "text", None) or "").strip()


def _rate_limit_msg() -> str:
    return (
        "[LIMITE ATINGIDO] Gemini free tier: máx 15 req/min.\n"
        "Aguarde 1 minuto e use o atalho novamente."
    )


def _call_gemini(
    prompt: str,
    *,
    fallback: str,
    temperature: float | None = None,
    success_log: str | None = None,
    fallback_log: str = "Gemini indisponível",
) -> str:
    """
    Centralized Gemini call with retry + rate-limit + error handling.

    Returns response text on success, fallback string on any failure path.

    Args:
        prompt: Full prompt string already built by caller.
        fallback: Text to return on any failure (no API key, generic exception,
            empty response). Callers that need a sentinel (e.g. query_with_gemini's
            "[SEM RESPOSTA GEMINI] ...") pass it here.
        temperature: If None, the `config` kwarg is OMITTED from the SDK call
            (preserves legacy default behavior of correct_with_gemini /
            structure_as_prompt). If float, GenerateContentConfig(temperature=X)
            is passed.
        success_log: If provided, prints "[OK]   {success_log} ({len} chars)" on
            success. If None, no success log (caller handles its own logging,
            e.g. correct_with_gemini's double-print).
        fallback_log: Message used in the "[WARN] {fallback_log} ({e})" line on
            generic exception.

    Note:
        Rate-limit (429) is intercepted and returns _rate_limit_msg() — NOT the
        fallback. This matches existing per-function behavior across gemini.py.
    """
    if not state._GEMINI_API_KEY:
        return fallback
    try:
        from google import genai
        client = _get_gemini_client()

        def _api_call():
            kwargs = {
                "model": state._CONFIG.get("GEMINI_MODEL", "gemini-2.5-flash"),
                "contents": prompt,
            }
            if temperature is not None:
                kwargs["config"] = genai.types.GenerateContentConfig(temperature=temperature)
            return _safe_text(client.models.generate_content(**kwargs))

        result = retry_api_call(_api_call, _is_rate_limit)
        if result:
            if success_log:
                print(f"[OK]   {success_log} ({len(result)} chars)")
            return result
    except Exception as e:
        if _is_rate_limit(e):
            print("[WARN] Gemini: rate limit 429 — aguardar 1 min")
            return _rate_limit_msg()
        print(f"[WARN] {fallback_log} ({e})")
    return fallback


def transcribe_audio_with_gemini(wav_path: str) -> str:
    """
    Transcreve áudio diretamente via Gemini Flash (audio input).
    Substitui Whisper local — melhor PT-BR + code-switching EN.
    Requer google-genai >= 1.0 (usa Part.from_bytes, não dict inline_data legado).
    """
    from google import genai
    client = _get_gemini_client()

    with open(wav_path, "rb") as f:
        audio_bytes = f.read()

    audio_part = genai.types.Part.from_bytes(
        data=audio_bytes,
        mime_type="audio/wav",
    )

    prompt = (
        "Transcreva exatamente o que foi dito no áudio. "
        "O falante usa português brasileiro com termos técnicos em inglês misturados "
        "(ex: 'o build falhou', 'faz o deploy', 'o pipeline está quebrado'). "
        "REGRAS: "
        "- Preserve termos em inglês como estão (deploy, build, pipeline, API, etc). "
        "- NÃO traduza, NÃO corrija, NÃO resuma. "
        "- Retorne APENAS o texto transcrito, sem pontuação excessiva, sem explicações."
    )

    def _api_call():
        return _safe_text(client.models.generate_content(
            model=state._CONFIG.get("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=[audio_part, prompt],
        ))

    return retry_api_call(_api_call, _is_rate_limit)


def correct_with_gemini(text: str) -> str:
    correction_style = state._CONFIG.get("CORRECTION_STYLE", "smart")

    # "off" bypassa completamente — sem chamada à API
    if correction_style == "off":
        return text

    if state._CONFIG.get("GEMINI_CORRECT", True) is not True:
        return text  # bypass legado — retorna raw sem correção
    if not state._GEMINI_API_KEY:
        return text
    try:
        client = _get_gemini_client()
        template = _gp.CORRECT_MINIMAL if correction_style == "minimal" else _gp.CORRECT_SMART
        prompt = template.format(text=text)

        def _api_call():
            return _safe_text(client.models.generate_content(
                model=state._CONFIG.get("GEMINI_MODEL", "gemini-2.5-flash"), contents=prompt))

        corrected = retry_api_call(_api_call, _is_rate_limit)
        if corrected:
            print(f"[OK]   Original : {text}")
            print(f"[OK]   Corrigido: {corrected}")
            # Aprendizado de vocabulário por correção
            try:
                from voice import vocabulary as _vocab
                candidates = _vocab.learn_from_correction(text, corrected)
                if candidates:
                    for word in candidates:
                        _vocab.add_word(word)
                    print(f"[INFO] Vocabulário: +{len(candidates)} palavras ({', '.join(candidates)})")
            except Exception as _vocab_e:
                # Vocabulário nunca deve crashar a correção, mas regressões devem ser visíveis.
                print(f"[WARN] Vocabulário falhou ({type(_vocab_e).__name__}: {_vocab_e})")
            return corrected
    except Exception as e:
        if _is_rate_limit(e):
            print("[WARN] Gemini: rate limit 429 — aguardar 1 min")
            return _rate_limit_msg()
        print(f"[WARN] Gemini indisponível ({e}), usando texto original")
    return text


def simplify_as_prompt(text: str) -> str:
    """
    Organiza a transcrição em prompt limpo com bullet points — sem XML, sem COSTAR.
    Fidelidade total ao input: nenhum detalhe omitido, output proporcional à riqueza do input.
    """
    if not state._GEMINI_API_KEY:
        return text

    word_count = len(text.split())
    print(f"[...]  Input: {word_count} palavras → modo prompt simples (fidelidade total)")

    prompt = _gp.build_simplify(text, _build_context_prefix())
    return _call_gemini(
        prompt,
        fallback=text,
        temperature=0.1,
        success_log="Prompt simplificado",
    )


def structure_as_prompt(text: str) -> str:
    """COSTAR XML structured prompt (SYSTEM + USER). No config (temperature=None)."""
    if not state._GEMINI_API_KEY:
        print("[WARN] Gemini sem chave — retornando texto original")
        return text
    prompt = _gp.build_structure(text)
    return _call_gemini(
        prompt,
        fallback=text,
        success_log="Prompt estruturado",
    )


def query_with_gemini(text: str) -> str:
    """
    Envia a transcrição diretamente ao Gemini como pergunta/query e retorna a resposta.
    Fallback sem Gemini: retorna texto original com prefixo informativo.
    """
    sentinel = f"[SEM RESPOSTA GEMINI] {text}"

    if not state._GEMINI_API_KEY:
        print("[WARN] Gemini sem chave — retornando transcrição com prefixo")
        return sentinel

    system_prompt = state._CONFIG.get("QUERY_SYSTEM_PROMPT", "").strip()
    if not system_prompt:
        system_prompt = _DEFAULT_QUERY_SYSTEM_PROMPT

    context_prefix = _build_context_prefix()
    if context_prefix:
        system_prompt = context_prefix + system_prompt

    print(f"[...]  Query Gemini ({len(text)} chars)...")

    prompt = _gp.build_query(system_prompt, text)
    return _call_gemini(
        prompt,
        fallback=sentinel,
        temperature=0.3,
        success_log="Resposta Gemini",
        fallback_log="Gemini indisponível, retornando transcrição com prefixo",
    )


def query_with_clipboard_context(text: str, clipboard_content: str) -> str:
    """
    Story 4.5.4: Query Gemini com contexto do clipboard.
    clipboard_content: texto copiado pelo usuário antes de acionar o hotkey (max 2000 chars).
    Fallback para query_with_gemini() se clipboard vazio.
    """
    if not clipboard_content.strip():
        print("[INFO] Clipboard vazio — modo query direto")
        return query_with_gemini(text)

    sentinel = f"[SEM RESPOSTA GEMINI] {text}"

    if not state._GEMINI_API_KEY:
        return sentinel

    system_prompt = state._CONFIG.get("QUERY_SYSTEM_PROMPT", "").strip()
    if not system_prompt:
        system_prompt = _DEFAULT_QUERY_SYSTEM_PROMPT

    context_prefix = _build_context_prefix()
    if context_prefix:
        system_prompt = context_prefix + system_prompt

    print(f"[...]  Query com clipboard ({len(clipboard_content)} chars contexto + {len(text)} chars instrução)...")

    prompt = _gp.build_query_with_clipboard(system_prompt, clipboard_content, text)
    return _call_gemini(
        prompt,
        fallback=sentinel,
        temperature=0.3,
        success_log="Resposta Gemini clipboard-context",
        fallback_log="Gemini indisponível, retornando transcrição com prefixo",
    )


def bullet_dump_with_gemini(text: str) -> str:
    """Transforma transcrição em bullets hierárquicos. Preserva TODO o conteúdo."""
    prompt = _gp.build_bullet_dump(text, _build_context_prefix())
    return _call_gemini(
        prompt,
        fallback=text,
        temperature=0.2,
        success_log="Bullet dump",
    )


def draft_email_with_gemini(text: str) -> str:
    """Transforma transcrição em email profissional com assunto + corpo + assinatura."""
    prompt = _gp.build_draft_email(text, _build_context_prefix())
    return _call_gemini(
        prompt,
        fallback=text,
        temperature=0.3,
        success_log="Email draft",
    )


def command_with_gemini(instruction: str, selected_text: str) -> str:
    """Epic 5.0: Aplica instrução de voz sobre texto selecionado via Gemini."""
    prompt = _gp.build_command(instruction, selected_text)
    return _call_gemini(
        prompt,
        fallback=selected_text,
        temperature=0.2,
        success_log="Comando aplicado",
        fallback_log="Gemini indisponível, retornando texto selecionado",
    )


def translate_with_gemini(text: str) -> str:
    """Detecta idioma e traduz para TRANSLATE_TARGET_LANG. Preserva formatação."""
    target_lang = state._CONFIG.get("TRANSLATE_TARGET_LANG", "en")
    prompt = _gp.build_translate(text, target_lang, _build_context_prefix())
    return _call_gemini(
        prompt,
        fallback=text,
        temperature=0.1,
        success_log=f"Traduzido → {target_lang}",
    )


