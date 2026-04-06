# voice/gemini.py — Gemini client singleton and text processing helpers

import threading

from voice import state
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


_PROMPT_MINIMAL = (
    "Você é um corretor MINIMALISTA de transcrição de voz para texto.\n"
    "REGRAS ABSOLUTAS:\n"
    "- NÃO traduza nada. Se a palavra está em inglês, deixe em inglês.\n"
    "- NÃO mude o sentido ou reorganize frases.\n"
    "- NÃO expanda abreviações ou siglas.\n"
    "- Preserve code-switching (mistura PT+EN) exatamente como está.\n"
    "- Em caso de dúvida, preserve o texto original.\n"
    "- Retorne APENAS o texto corrigido, sem explicações.\n\n"
    "Texto: {text}"
)

_PROMPT_SMART = (
    "Você é um corretor inteligente de transcrição de voz para texto.\n"
    "REGRAS:\n"
    "- Adicione pontuação automaticamente (pontos finais, vírgulas, interrogações, exclamações).\n"
    "- Capitalize o início de frases.\n"
    "- Formate números naturalmente (ex: 'duzentos e cinquenta' -> '250').\n"
    "- Corrija erros ortográficos óbvios da transcrição.\n"
    "- NÃO traduza nada. Se a palavra está em inglês, deixe em inglês.\n"
    "- NÃO mude o sentido ou reorganize frases.\n"
    "- NÃO expanda abreviações ou siglas.\n"
    "- Preserve code-switching (mistura PT+EN) exatamente como está.\n"
    "- Retorne APENAS o texto corrigido, sem explicações.\n\n"
    "Texto: {text}"
)


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
        template = _PROMPT_MINIMAL if correction_style == "minimal" else _PROMPT_SMART
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
            except Exception:
                pass  # vocabulário nunca deve crashar a correção
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

    context_prefix = _build_context_prefix()
    meta_prompt = f"""{context_prefix}Você é especialista em prompt engineering.
O texto abaixo é transcrição de voz informal (pode misturar PT e EN).
Transforme-o em um prompt limpo e direto para usar em qualquer LLM.

PRIORIDADE ABSOLUTA: Preservar CADA detalhe, contexto e nuance que o usuário mencionou.
Não comprima, não resuma, não omita nenhuma informação do input.
Se o input for longo e detalhado, o output também deve ser longo e detalhado.

ESTRUTURA:
1. Um ou mais parágrafos explicando o contexto e o que se quer — sem label, só texto corrido
2. Requisitos, detalhes específicos ou etapas listados como bullet points logo abaixo

REGRAS:
- Sem XML, sem seções SYSTEM/USER, sem headers, sem labels como "Contexto:" ou "Objetivo:"
- Os bullet points devem ser frases completas, não palavras soltas
- Preserve a intenção original completamente — não invente nem omita nada do input
- A quantidade de linhas e bullets deve ser proporcional à riqueza do input
- Retorne APENAS o prompt, sem explicações adicionais

Transcrição: {text}"""

    try:
        from google import genai
        client = _get_gemini_client()

        def _api_call():
            return _safe_text(client.models.generate_content(
                model=state._CONFIG.get("GEMINI_MODEL", "gemini-2.5-flash"),
                contents=meta_prompt,
                config=genai.types.GenerateContentConfig(temperature=0.1),
            ))

        simplified = retry_api_call(_api_call, _is_rate_limit)
        if simplified:
            print(f"[OK]   Prompt simplificado ({len(simplified)} chars)")
            return simplified
    except Exception as e:
        if _is_rate_limit(e):
            print("[WARN] Gemini: rate limit 429 — aguardar 1 min")
            return _rate_limit_msg()
        print(f"[WARN] Gemini indisponível ({e}), retornando texto original")
    return text


def structure_as_prompt(text: str) -> str:
    if not state._GEMINI_API_KEY:
        print("[WARN] Gemini sem chave — retornando texto original")
        return text

    meta_prompt = f"""Você é especialista em prompt engineering para LLMs (Claude, GPT-4, Gemini).
O texto abaixo é transcrição de voz informal (pode misturar PT e EN).
Transforme-o em prompt estruturado profissional usando o framework COSTAR com XML tags.

Siga EXATAMENTE este formato (substitua os colchetes pelo conteúdo):

═══════════════════════════════════════
SYSTEM PROMPT
═══════════════════════════════════════
<role>
[Papel e persona ideal para executar esta tarefa]
</role>

<behavior>
[2-4 diretrizes comportamentais específicas e relevantes]
</behavior>

<output_format>
[Formato exato do output: markdown, JSON, lista, prosa, etc.]
</output_format>

═══════════════════════════════════════
USER PROMPT
═══════════════════════════════════════
<context>
[Background, situação atual, dados relevantes]
</context>

<objective>
[Tarefa específica e clara — o que exatamente deve ser feito]
</objective>

<style_and_tone>
[Estilo de escrita, tom (formal/direto/técnico) e audiência-alvo]
</style_and_tone>

<response>
[Formato e constraints da resposta: tamanho, idioma, estrutura]
</response>

REGRAS:
- Infira o papel ideal com base na natureza da tarefa
- Seja específico em todas as seções (nunca deixe vago)
- Preserve a intenção original do usuário
- Retorne APENAS o prompt estruturado, sem explicações adicionais

Transcrição: {text}"""

    try:
        client = _get_gemini_client()

        def _api_call():
            return _safe_text(client.models.generate_content(
                model=state._CONFIG.get("GEMINI_MODEL", "gemini-2.5-flash"), contents=meta_prompt))

        structured = retry_api_call(_api_call, _is_rate_limit)
        if structured:
            print(f"[OK]   Prompt estruturado ({len(structured)} chars)")
            return structured
    except Exception as e:
        if _is_rate_limit(e):
            print("[WARN] Gemini: rate limit 429 — aguardar 1 min")
            return _rate_limit_msg()
        print(f"[WARN] Gemini indisponível ({e}), retornando texto original")
    return text


def query_with_gemini(text: str) -> str:
    """
    Envia a transcrição diretamente ao Gemini como pergunta/query e retorna a resposta.
    Fallback sem Gemini: retorna texto original com prefixo informativo.
    """
    if not state._GEMINI_API_KEY:
        print("[WARN] Gemini sem chave — retornando transcrição com prefixo")
        return f"[SEM RESPOSTA GEMINI] {text}"

    system_prompt = state._CONFIG.get("QUERY_SYSTEM_PROMPT", "").strip()
    if not system_prompt:
        system_prompt = _DEFAULT_QUERY_SYSTEM_PROMPT

    context_prefix = _build_context_prefix()
    if context_prefix:
        system_prompt = context_prefix + system_prompt

    print(f"[...]  Query Gemini ({len(text)} chars)...")

    try:
        from google import genai
        client = _get_gemini_client()

        full_prompt = f"{system_prompt}\n\n{text}"

        def _api_call():
            return _safe_text(client.models.generate_content(
                model=state._CONFIG.get("GEMINI_MODEL", "gemini-2.5-flash"),
                contents=full_prompt,
                config=genai.types.GenerateContentConfig(temperature=0.3),
            ))

        answer = retry_api_call(_api_call, _is_rate_limit)
        if answer:
            print(f"[OK]   Resposta Gemini ({len(answer)} chars)")
            return answer
    except Exception as e:
        if _is_rate_limit(e):
            print("[WARN] Gemini: rate limit 429 — aguardar 1 min")
            return _rate_limit_msg()
        print(f"[WARN] Gemini indisponível ({e}), retornando transcrição com prefixo")

    return f"[SEM RESPOSTA GEMINI] {text}"


def query_with_clipboard_context(text: str, clipboard_content: str) -> str:
    """
    Story 4.5.4: Query Gemini com contexto do clipboard.
    clipboard_content: texto copiado pelo usuário antes de acionar o hotkey (max 2000 chars).
    Fallback para query_with_gemini() se clipboard vazio.
    """
    if not clipboard_content.strip():
        print("[INFO] Clipboard vazio — modo query direto")
        return query_with_gemini(text)

    if not state._GEMINI_API_KEY:
        return f"[SEM RESPOSTA GEMINI] {text}"

    system_prompt = state._CONFIG.get("QUERY_SYSTEM_PROMPT", "").strip()
    if not system_prompt:
        system_prompt = _DEFAULT_QUERY_SYSTEM_PROMPT

    context_prefix = _build_context_prefix()
    if context_prefix:
        system_prompt = context_prefix + system_prompt

    full_prompt = (
        f"{system_prompt}\n\n"
        f"[CONTEXTO DO CLIPBOARD]\n{clipboard_content}\n\n"
        f"[INSTRUÇÃO]\n{text}"
    )

    print(f"[...]  Query com clipboard ({len(clipboard_content)} chars contexto + {len(text)} chars instrução)...")

    try:
        from google import genai
        client = _get_gemini_client()
        def _api_call():
            return _safe_text(client.models.generate_content(
                model=state._CONFIG.get("GEMINI_MODEL", "gemini-2.5-flash"),
                contents=full_prompt,
                config=genai.types.GenerateContentConfig(temperature=0.3),
            ))

        answer = retry_api_call(_api_call, _is_rate_limit)
        if answer:
            print(f"[OK]   Resposta Gemini clipboard-context ({len(answer)} chars)")
            return answer
    except Exception as e:
        if _is_rate_limit(e):
            print("[WARN] Gemini: rate limit 429 — aguardar 1 min")
            return _rate_limit_msg()
        print(f"[WARN] Gemini indisponível ({e}), retornando transcrição com prefixo")

    return f"[SEM RESPOSTA GEMINI] {text}"


def bullet_dump_with_gemini(text: str) -> str:
    """Transforma transcrição em bullets hierárquicos. Preserva TODO o conteúdo."""
    if not state._GEMINI_API_KEY:
        return text
    try:
        from google import genai
        client = _get_gemini_client()
        context_prefix = _build_context_prefix()
        prompt = (
            f"{context_prefix}"
            "Você é especialista em organização de informação.\n"
            "Transforme a transcrição abaixo em bullet points hierárquicos.\n"
            "REGRAS ABSOLUTAS:\n"
            "- Preserve TODO o conteúdo — zero omissão.\n"
            "- Use estrutura H1 (##) → H2 (###) → itens (- ) onde aplicável.\n"
            "- Retorne APENAS os bullets, sem explicações.\n\n"
            f"Transcrição: {text}"
        )
        def _api_call():
            return _safe_text(client.models.generate_content(
                model=state._CONFIG.get("GEMINI_MODEL", "gemini-2.5-flash"),
                contents=prompt,
                config=genai.types.GenerateContentConfig(temperature=0.2),
            ))

        result = retry_api_call(_api_call, _is_rate_limit)
        if result:
            print(f"[OK]   Bullet dump ({len(result)} chars)")
            return result
    except Exception as e:
        if _is_rate_limit(e):
            print("[WARN] Gemini: rate limit 429 — aguardar 1 min")
            return _rate_limit_msg()
        print(f"[WARN] Gemini indisponível ({e}), retornando texto original")
    return text


def draft_email_with_gemini(text: str) -> str:
    """Transforma transcrição em email profissional com assunto + corpo + assinatura."""
    if not state._GEMINI_API_KEY:
        return text
    try:
        from google import genai
        client = _get_gemini_client()
        context_prefix = _build_context_prefix()
        prompt = (
            f"{context_prefix}"
            "Você é um redator profissional de emails.\n"
            "Transforme a transcrição abaixo em um email profissional.\n"
            "ESTRUTURA OBRIGATÓRIA:\n"
            "Assunto: [linha de assunto]\n\n"
            "[corpo do email — direto, sem hype]\n\n"
            "Atenciosamente,\n{Nome}\n\n"
            "REGRAS:\n"
            "- Tom direto e profissional, sem linguagem excessivamente formal.\n"
            "- Preserve toda a intenção e detalhes da transcrição.\n"
            "- Retorne APENAS o email, sem explicações adicionais.\n\n"
            f"Transcrição: {text}"
        )
        def _api_call():
            return _safe_text(client.models.generate_content(
                model=state._CONFIG.get("GEMINI_MODEL", "gemini-2.5-flash"),
                contents=prompt,
                config=genai.types.GenerateContentConfig(temperature=0.3),
            ))

        result = retry_api_call(_api_call, _is_rate_limit)
        if result:
            print(f"[OK]   Email draft ({len(result)} chars)")
            return result
    except Exception as e:
        if _is_rate_limit(e):
            print("[WARN] Gemini: rate limit 429 — aguardar 1 min")
            return _rate_limit_msg()
        print(f"[WARN] Gemini indisponível ({e}), retornando texto original")
    return text


def command_with_gemini(instruction: str, selected_text: str) -> str:
    """Epic 5.0: Aplica instrução de voz sobre texto selecionado via Gemini."""
    if not state._GEMINI_API_KEY:
        return selected_text
    try:
        from google import genai
        client = _get_gemini_client()
        prompt = (
            "You are a text editing assistant. The user has selected text and spoken an instruction.\n"
            "Apply the instruction to the selected text.\n"
            "Return ONLY the modified text, no explanations, no quotes, no markdown formatting "
            "unless the instruction specifically asks for it.\n\n"
            f"[SELECTED TEXT]\n{selected_text}\n\n[INSTRUCTION]\n{instruction}"
        )

        def _api_call():
            return _safe_text(client.models.generate_content(
                model=state._CONFIG.get("GEMINI_MODEL", "gemini-2.5-flash"),
                contents=prompt,
                config=genai.types.GenerateContentConfig(temperature=0.2),
            ))

        result = retry_api_call(_api_call, _is_rate_limit)
        if result:
            print(f"[OK]   Comando aplicado ({len(result)} chars)")
            return result
    except Exception as e:
        if _is_rate_limit(e):
            print("[WARN] Gemini: rate limit 429 — aguardar 1 min")
            return _rate_limit_msg()
        print(f"[WARN] Gemini indisponível ({e}), retornando texto selecionado")
    return selected_text


def translate_with_gemini(text: str) -> str:
    """Detecta idioma e traduz para TRANSLATE_TARGET_LANG. Preserva formatação."""
    if not state._GEMINI_API_KEY:
        return text
    try:
        from google import genai
        client = _get_gemini_client()
        target_lang = state._CONFIG.get("TRANSLATE_TARGET_LANG", "en")
        lang_name = "inglês" if target_lang == "en" else "português brasileiro"
        context_prefix = _build_context_prefix()
        prompt = (
            f"{context_prefix}"
            f"Detecte o idioma do texto abaixo e traduza para {lang_name}.\n"
            "Preserve a formatação original.\n"
            "Retorne APENAS o texto traduzido, sem explicações.\n\n"
            f"Texto: {text}"
        )
        def _api_call():
            return _safe_text(client.models.generate_content(
                model=state._CONFIG.get("GEMINI_MODEL", "gemini-2.5-flash"),
                contents=prompt,
                config=genai.types.GenerateContentConfig(temperature=0.1),
            ))

        result = retry_api_call(_api_call, _is_rate_limit)
        if result:
            print(f"[OK]   Traduzido → {target_lang} ({len(result)} chars)")
            return result
    except Exception as e:
        if _is_rate_limit(e):
            print("[WARN] Gemini: rate limit 429 — aguardar 1 min")
            return _rate_limit_msg()
        print(f"[WARN] Gemini indisponível ({e}), retornando texto original")
    return text


