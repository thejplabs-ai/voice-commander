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
#   Builders:
#     - build_simplify(text, context_prefix)
#     - build_structure(text)
#     - build_query(system_prompt, text)
#     - build_query_with_clipboard(system_prompt, clipboard_content, text)
#     - build_bullet_dump(text, context_prefix)
#     - build_draft_email(text, context_prefix)
#     - build_command(instruction, selected_text)
#     - build_translate(text, target_lang, context_prefix)
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


CORRECT_MINIMAL = (
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


CORRECT_SMART = (
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


# ── Builders ─────────────────────────────────────────────────────────────────

def build_simplify(text: str, context_prefix: str) -> str:
    """Bullet-prompt simples (sem XML, sem COSTAR). Fidelidade total ao input."""
    return f"""{context_prefix}Você é especialista em prompt engineering.
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


def build_structure(text: str) -> str:
    """Prompt estruturado COSTAR XML completo (SYSTEM + USER)."""
    return f"""Você é especialista em prompt engineering para LLMs (Claude, GPT-4, Gemini).
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
    return (
        f"{context_prefix}"
        "Você é especialista em organização de informação.\n"
        "Transforme a transcrição abaixo em bullet points hierárquicos.\n"
        "REGRAS ABSOLUTAS:\n"
        "- Preserve TODO o conteúdo — zero omissão.\n"
        "- Use estrutura H1 (##) → H2 (###) → itens (- ) onde aplicável.\n"
        "- Retorne APENAS os bullets, sem explicações.\n\n"
        f"Transcrição: {text}"
    )


def build_draft_email(text: str, context_prefix: str) -> str:
    """Email profissional com assunto + corpo + assinatura."""
    return (
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


def build_command(instruction: str, selected_text: str) -> str:
    """Aplica instrução de voz sobre texto selecionado (Epic 5.0)."""
    return (
        "You are a text editing assistant. The user has selected text and spoken an instruction.\n"
        "Apply the instruction to the selected text.\n"
        "Return ONLY the modified text, no explanations, no quotes, no markdown formatting "
        "unless the instruction specifically asks for it.\n\n"
        f"[SELECTED TEXT]\n{selected_text}\n\n[INSTRUCTION]\n{instruction}"
    )


def build_translate(text: str, target_lang: str, context_prefix: str) -> str:
    """Detecta idioma e traduz para target_lang ('en' → inglês; outro → PT-BR)."""
    lang_name = "inglês" if target_lang == "en" else "português brasileiro"
    return (
        f"{context_prefix}"
        f"Detecte o idioma do texto abaixo e traduza para {lang_name}.\n"
        "Preserve a formatação original.\n"
        "Retorne APENAS o texto traduzido, sem explicações.\n\n"
        f"Texto: {text}"
    )
