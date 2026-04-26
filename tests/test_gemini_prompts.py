"""
Tests for voice/gemini_prompts.py — pure prompt templates + builders.

Pure string tests, no API calls, no mocks. Each test verifies:
  - Builder output contains the expected anchor strings
  - Variable interpolation works correctly
  - Byte-identical output to the inline templates that previously lived in
    voice/gemini.py (regression safety net for the R3 rewire).
"""

from voice import gemini_prompts as gp


# ---------------------------------------------------------------------------
# Constants — sanity checks
# ---------------------------------------------------------------------------

def test_default_query_system_prompt_anchors():
    """DEFAULT_QUERY_SYSTEM_PROMPT mantém anchors que definem comportamento."""
    p = gp.DEFAULT_QUERY_SYSTEM_PROMPT
    assert "assistente direto e preciso" in p
    assert "português e inglês" in p
    # Não termina com newline (composto via build_query com '\n\n')
    assert not p.endswith("\n")


def test_transcribe_audio_anchors():
    """TRANSCRIBE_AUDIO preserva regras críticas de transcrição."""
    p = gp.TRANSCRIBE_AUDIO
    assert "Transcreva exatamente" in p
    assert "português brasileiro" in p
    assert "NÃO traduza" in p
    assert "deploy" in p  # exemplo de termo técnico EN


def test_correct_minimal_template_has_text_placeholder():
    """CORRECT_MINIMAL é template para .format(text=...) — placeholder presente."""
    p = gp.CORRECT_MINIMAL
    assert "{text}" in p
    assert "MINIMALISTA" in p
    assert "NÃO traduza nada" in p
    formatted = p.format(text="hello world")
    assert "hello world" in formatted
    assert "{text}" not in formatted


def test_correct_smart_template_has_text_placeholder():
    """CORRECT_SMART é template para .format(text=...) — placeholder presente."""
    p = gp.CORRECT_SMART
    assert "{text}" in p
    assert "Adicione pontuação" in p
    assert "Capitalize" in p
    formatted = p.format(text="texto exemplo")
    assert "texto exemplo" in formatted
    assert "{text}" not in formatted


# ---------------------------------------------------------------------------
# Builders — anchors + interpolation
# ---------------------------------------------------------------------------

def test_build_simplify_interpolates_text_and_context():
    """build_simplify injeta context_prefix no início e text no final."""
    out = gp.build_simplify("transcrição teste", "CONTEXT_PREFIX> ")
    assert out.startswith("CONTEXT_PREFIX> ")
    assert "transcrição teste" in out
    assert "prompt engineering" in out
    assert "PRIORIDADE ABSOLUTA" in out
    # Sem labels XML/COSTAR
    assert "<role>" not in out
    assert "SYSTEM PROMPT" not in out


def test_build_simplify_empty_context_prefix():
    """build_simplify com context_prefix vazio não introduz prefixo espúrio."""
    out = gp.build_simplify("foo", "")
    assert out.startswith("Você é especialista")
    assert "foo" in out


def test_build_structure_interpolates_text():
    """build_structure produz COSTAR XML completo com SYSTEM e USER."""
    out = gp.build_structure("transcrição teste")
    assert "transcrição teste" in out
    assert "SYSTEM PROMPT" in out
    assert "USER PROMPT" in out
    assert "<role>" in out
    assert "<behavior>" in out
    assert "<output_format>" in out
    assert "<context>" in out
    assert "<objective>" in out
    assert "<style_and_tone>" in out
    assert "<response>" in out


def test_build_query_concatenates_system_and_text():
    """build_query: system_prompt + '\\n\\n' + text — sem extras."""
    out = gp.build_query("SYS", "TXT")
    assert out == "SYS\n\nTXT"


def test_build_query_with_clipboard_includes_labels():
    """build_query_with_clipboard preserva labels [CONTEXTO DO CLIPBOARD] e [INSTRUÇÃO]."""
    out = gp.build_query_with_clipboard("SYS", "CLIP_DATA", "INSTRUCT")
    assert "SYS" in out
    assert "[CONTEXTO DO CLIPBOARD]" in out
    assert "CLIP_DATA" in out
    assert "[INSTRUÇÃO]" in out
    assert "INSTRUCT" in out
    # Order matters: system first, then clipboard, then instruction
    sys_idx = out.find("SYS")
    clip_idx = out.find("CLIP_DATA")
    instr_idx = out.find("INSTRUCT")
    assert sys_idx < clip_idx < instr_idx


def test_build_bullet_dump_demands_zero_omission():
    """build_bullet_dump preserva regra crítica de não omissão + estrutura H1/H2."""
    out = gp.build_bullet_dump("conteúdo longo", "CTX> ")
    assert out.startswith("CTX> ")
    assert "Preserve TODO o conteúdo" in out
    assert "zero omissão" in out
    assert "H1 (##)" in out
    assert "H2 (###)" in out
    assert "conteúdo longo" in out


def test_build_draft_email_has_required_structure():
    """build_draft_email contém marcadores Assunto + Atenciosamente + {Nome}."""
    out = gp.build_draft_email("rascunho", "")
    assert "Assunto:" in out
    assert "Atenciosamente," in out
    assert "{Nome}" in out  # placeholder literal — Gemini substitui
    assert "rascunho" in out
    assert "redator profissional" in out


def test_build_command_orders_selected_text_before_instruction():
    """build_command: ordem [SELECTED TEXT] antes de [INSTRUCTION]."""
    out = gp.build_command("make formal", "olá!")
    assert "[SELECTED TEXT]" in out
    assert "[INSTRUCTION]" in out
    sel_idx = out.find("[SELECTED TEXT]")
    instr_idx = out.find("[INSTRUCTION]")
    assert sel_idx < instr_idx
    assert "olá!" in out
    assert "make formal" in out
    assert "text editing assistant" in out


def test_build_translate_en_uses_ingles():
    """build_translate('en') aponta para 'inglês' como destino."""
    out = gp.build_translate("olá mundo", "en", "")
    assert "traduza para inglês" in out
    assert "olá mundo" in out
    assert "Preserve a formatação" in out


def test_build_translate_other_uses_portugues_brasileiro():
    """build_translate(target != 'en') aponta para 'português brasileiro'."""
    out = gp.build_translate("hello world", "pt", "")
    assert "traduza para português brasileiro" in out
    assert "hello world" in out


def test_build_translate_includes_context_prefix():
    """build_translate respeita context_prefix quando fornecido."""
    out = gp.build_translate("texto", "en", "CTX> ")
    assert out.startswith("CTX> ")
