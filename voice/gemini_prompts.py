# voice/gemini_prompts.py — Prompt templates for Gemini calls.
#
# Pure data + builders. Zero side effects, no API calls, no state mutations.
# Extracted from voice/gemini.py to keep the API surface module slim.
#
# Public surface:
#   Constants:
#     - DEFAULT_QUERY_SYSTEM_PROMPT
#     - TRANSCRIBE_AUDIO
#     - CORRECT_MINIMAL  (template: format with text=...)
#     - CORRECT_SMART    (template: format with text=...)
#     - SYSTEM_CORRECT_MINIMAL / SYSTEM_CORRECT_SMART  (chat-API system messages)
#     - SYSTEM_SIMPLIFY / SYSTEM_STRUCTURE / SYSTEM_BULLET_DUMP
#     - SYSTEM_DRAFT_EMAIL / SYSTEM_TRANSLATE (template, format with lang_name=...)
#     - SYSTEM_COMMAND
#   Builders (combined system + user, used by Gemini SDK single-prompt API):
#     - build_simplify(text, context_prefix)
#     - build_structure(text)
#     - build_query(system_prompt, text)
#     - build_query_with_clipboard(system_prompt, clipboard_content, text)
#     - build_bullet_dump(text, context_prefix)
#     - build_draft_email(text, context_prefix)
#     - build_command(instruction, selected_text)
#     - build_translate(text, target_lang, context_prefix)
#   User-side message builders (for chat-completions APIs e.g. OpenRouter):
#     - user_simplify(text, context_prefix="")
#     - user_structure(text)
#     - user_bullet_dump(text, context_prefix="")
#     - user_draft_email(text, context_prefix="")
#     - user_translate(text, context_prefix="")
#     - user_command(instruction, selected_text)
#     - user_correct(text)
#
# SYSTEM_* constants + user_* helpers exist so OpenRouter (chat completions)
# can reuse the same source-of-truth as the Gemini single-prompt builders.
# Combining f"{SYSTEM_X}\n\n{user_X(text)}" must yield byte-identical output
# to build_X(text, "") for every mode (asserted in tests).
#
# Byte-identical to the inline strings in voice/gemini.py as of 2026-04-26.
# Any change here must be reviewed against the smoke-test matrix in
# .aios/reports/sentinel/fix-plan-gemini-prompts.md.


# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_QUERY_SYSTEM_PROMPT = (
    "Você é um assistente direto e preciso. "
    "Responda à pergunta do usuário de forma clara, concisa e útil. "
    "Vá direto ao ponto sem rodeios desnecessários. "
    "O texto pode misturar português e inglês — responda no mesmo idioma da pergunta."
)


TRANSCRIBE_AUDIO = (
    "Transcreva exatamente o que foi dito no áudio. "
    "O falante usa português brasileiro com termos técnicos em inglês misturados "
    "(ex: 'o build falhou', 'faz o deploy', 'o pipeline está quebrado'). "
    "REGRAS: "
    "- Preserve termos em inglês como estão (deploy, build, pipeline, API, etc). "
    "- NÃO traduza, NÃO corrija, NÃO resuma. "
    "- Retorne APENAS o texto transcrito, sem pontuação excessiva, sem explicações."
)


# ── Correction system prompts (chat-API style: system msg sem o "Texto: …") ──

SYSTEM_CORRECT_MINIMAL = (
    "Você é um corretor MINIMALISTA de transcrição de voz para texto.\n"
    "REGRAS ABSOLUTAS:\n"
    "- NÃO traduza nada. Se a palavra está em inglês, deixe em inglês.\n"
    "- NÃO mude o sentido ou reorganize frases.\n"
    "- NÃO expanda abreviações ou siglas.\n"
    "- Preserve code-switching (mistura PT+EN) exatamente como está.\n"
    "- Em caso de dúvida, preserve o texto original.\n"
    "- Retorne APENAS o texto corrigido, sem explicações."
)


SYSTEM_CORRECT_SMART = (
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
    "- Retorne APENAS o texto corrigido, sem explicações."
)


# Legacy single-string templates (used by voice/gemini.py via .format(text=...)).
# Kept byte-identical for backward compatibility — built from SYSTEM_* + user_correct
# template so source of truth is unique.
CORRECT_MINIMAL = SYSTEM_CORRECT_MINIMAL + "\n\nTexto: {text}"


CORRECT_SMART = SYSTEM_CORRECT_SMART + "\n\nTexto: {text}"


# ── System prompts por modo (para uso em chat-API style: openrouter etc.) ────

SYSTEM_SIMPLIFY = (
    "Você é especialista em prompt engineering.\n"
    "O texto abaixo é transcrição de voz informal (pode misturar PT e EN).\n"
    "Transforme-o em um prompt limpo e direto para usar em qualquer LLM.\n"
    "\n"
    "PRIORIDADE ABSOLUTA: Preservar CADA detalhe, contexto e nuance que o usuário mencionou.\n"
    "Não comprima, não resuma, não omita nenhuma informação do input.\n"
    "Se o input for longo e detalhado, o output também deve ser longo e detalhado.\n"
    "\n"
    "ESTRUTURA:\n"
    "1. Um ou mais parágrafos explicando o contexto e o que se quer — sem label, só texto corrido\n"
    "2. Requisitos, detalhes específicos ou etapas listados como bullet points logo abaixo\n"
    "\n"
    "REGRAS:\n"
    "- Sem XML, sem seções SYSTEM/USER, sem headers, sem labels como \"Contexto:\" ou \"Objetivo:\"\n"
    "- Os bullet points devem ser frases completas, não palavras soltas\n"
    "- Preserve a intenção original completamente — não invente nem omita nada do input\n"
    "- A quantidade de linhas e bullets deve ser proporcional à riqueza do input\n"
    "- Retorne APENAS o prompt, sem explicações adicionais"
)


SYSTEM_STRUCTURE = (
    "Você é especialista em prompt engineering para LLMs (Claude, GPT-4, Gemini).\n"
    "O texto abaixo é transcrição de voz informal (pode misturar PT e EN).\n"
    "Transforme-o em prompt estruturado profissional usando o framework COSTAR com XML tags.\n"
    "\n"
    "Siga EXATAMENTE este formato (substitua os colchetes pelo conteúdo):\n"
    "\n"
    "═══════════════════════════════════════\n"
    "SYSTEM PROMPT\n"
    "═══════════════════════════════════════\n"
    "<role>\n"
    "[Papel e persona ideal para executar esta tarefa]\n"
    "</role>\n"
    "\n"
    "<behavior>\n"
    "[2-4 diretrizes comportamentais específicas e relevantes]\n"
    "</behavior>\n"
    "\n"
    "<output_format>\n"
    "[Formato exato do output: markdown, JSON, lista, prosa, etc.]\n"
    "</output_format>\n"
    "\n"
    "═══════════════════════════════════════\n"
    "USER PROMPT\n"
    "═══════════════════════════════════════\n"
    "<context>\n"
    "[Background, situação atual, dados relevantes]\n"
    "</context>\n"
    "\n"
    "<objective>\n"
    "[Tarefa específica e clara — o que exatamente deve ser feito]\n"
    "</objective>\n"
    "\n"
    "<style_and_tone>\n"
    "[Estilo de escrita, tom (formal/direto/técnico) e audiência-alvo]\n"
    "</style_and_tone>\n"
    "\n"
    "<response>\n"
    "[Formato e constraints da resposta: tamanho, idioma, estrutura]\n"
    "</response>\n"
    "\n"
    "REGRAS:\n"
    "- Infira o papel ideal com base na natureza da tarefa\n"
    "- Seja específico em todas as seções (nunca deixe vago)\n"
    "- Preserve a intenção original do usuário\n"
    "- Retorne APENAS o prompt estruturado, sem explicações adicionais"
)


SYSTEM_BULLET_DUMP = (
    "Você é especialista em organização de informação.\n"
    "Transforme a transcrição abaixo em bullet points hierárquicos.\n"
    "REGRAS ABSOLUTAS:\n"
    "- Preserve TODO o conteúdo — zero omissão.\n"
    "- Use estrutura H1 (##) → H2 (###) → itens (- ) onde aplicável.\n"
    "- Retorne APENAS os bullets, sem explicações."
)


SYSTEM_DRAFT_EMAIL = (
    "Você é um redator profissional de emails.\n"
    "Transforme a transcrição abaixo em um email profissional.\n"
    "ESTRUTURA OBRIGATÓRIA:\n"
    "Assunto: [linha de assunto]\n"
    "\n"
    "[corpo do email — direto, sem hype]\n"
    "\n"
    "Atenciosamente,\n"
    "{Nome}\n"
    "\n"
    "REGRAS:\n"
    "- Tom direto e profissional, sem linguagem excessivamente formal.\n"
    "- Preserve toda a intenção e detalhes da transcrição.\n"
    "- Retorne APENAS o email, sem explicações adicionais."
)


# Template — format with lang_name=... before sending to chat-API.
SYSTEM_TRANSLATE = (
    "Detecte o idioma do texto abaixo e traduza para {lang_name}.\n"
    "Preserve a formatação original.\n"
    "Retorne APENAS o texto traduzido, sem explicações."
)


SYSTEM_COMMAND = (
    "You are a text editing assistant. The user has selected text and spoken an instruction.\n"
    "Apply the instruction to the selected text.\n"
    "Return ONLY the modified text, no explanations, no quotes, no markdown formatting "
    "unless the instruction specifically asks for it."
)


# ── User-side message builders (for chat-completions APIs) ───────────────────

def user_simplify(text: str, context_prefix: str = "") -> str:
    """User message para o modo simplify (Prompt Simples)."""
    return f"{context_prefix}Transcrição: {text}"


def user_structure(text: str) -> str:
    """User message para o modo structure (COSTAR)."""
    return f"Transcrição: {text}"


def user_bullet_dump(text: str, context_prefix: str = "") -> str:
    """User message para o modo bullet dump."""
    return f"{context_prefix}Transcrição: {text}"


def user_draft_email(text: str, context_prefix: str = "") -> str:
    """User message para o modo email."""
    return f"{context_prefix}Transcrição: {text}"


def user_translate(text: str, context_prefix: str = "") -> str:
    """User message para o modo translate. lang_name vai no SYSTEM via format()."""
    return f"{context_prefix}Texto: {text}"


def user_command(instruction: str, selected_text: str) -> str:
    """User message para o modo command (Epic 5.0)."""
    return f"[SELECTED TEXT]\n{selected_text}\n\n[INSTRUCTION]\n{instruction}"


def user_correct(text: str) -> str:
    """User message para correction (minimal/smart)."""
    return f"Texto: {text}"


# ── Builders (combined system + user, used by Gemini SDK single-prompt API) ──

def build_simplify(text: str, context_prefix: str) -> str:
    """Bullet-prompt simples (sem XML, sem COSTAR). Fidelidade total ao input."""
    return f"{context_prefix}{SYSTEM_SIMPLIFY}\n\n{user_simplify(text)}"


def build_structure(text: str) -> str:
    """Prompt estruturado COSTAR XML completo (SYSTEM + USER)."""
    return f"{SYSTEM_STRUCTURE}\n\n{user_structure(text)}"


def build_query(system_prompt: str, text: str) -> str:
    """Query direta: system prompt + pergunta."""
    return f"{system_prompt}\n\n{text}"


def build_query_with_clipboard(
    system_prompt: str, clipboard_content: str, text: str
) -> str:
    """Query Gemini com clipboard injetado como contexto."""
    return (
        f"{system_prompt}\n\n"
        f"[CONTEXTO DO CLIPBOARD]\n{clipboard_content}\n\n"
        f"[INSTRUÇÃO]\n{text}"
    )


def build_bullet_dump(text: str, context_prefix: str) -> str:
    """Transforma transcrição em bullets hierárquicos preservando todo o conteúdo."""
    return f"{context_prefix}{SYSTEM_BULLET_DUMP}\n\n{user_bullet_dump(text)}"


def build_draft_email(text: str, context_prefix: str) -> str:
    """Email profissional com assunto + corpo + assinatura."""
    return f"{context_prefix}{SYSTEM_DRAFT_EMAIL}\n\n{user_draft_email(text)}"


def build_command(instruction: str, selected_text: str) -> str:
    """Aplica instrução de voz sobre texto selecionado (Epic 5.0)."""
    return f"{SYSTEM_COMMAND}\n\n{user_command(instruction, selected_text)}"


def build_translate(text: str, target_lang: str, context_prefix: str) -> str:
    """Detecta idioma e traduz para target_lang ('en' → inglês; outro → PT-BR)."""
    lang_name = "inglês" if target_lang == "en" else "português brasileiro"
    system = SYSTEM_TRANSLATE.format(lang_name=lang_name)
    return f"{context_prefix}{system}\n\n{user_translate(text)}"
