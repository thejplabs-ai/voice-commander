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


# ---------------------------------------------------------------------------
# SYSTEM_* + user_* split (R1 — chat-completions API support)
# ---------------------------------------------------------------------------
# Garante que SYSTEM + user combinados produzem output BYTE-IDENTICAL ao
# build_X correspondente. Source of truth única consumida tanto pelo Gemini
# SDK (single prompt via build_X) quanto pelo OpenRouter (chat completions
# via SYSTEM_X + user_X separados).


def test_system_plus_user_simplify_matches_build_simplify():
    """f'{ctx}{SYSTEM_SIMPLIFY}\\n\\n{user_simplify(text)}' == build_simplify(text, ctx)."""
    text = "transcrição arbitrária com PT e EN"
    ctx = "CONTEXT> "
    combined = f"{ctx}{gp.SYSTEM_SIMPLIFY}\n\n{gp.user_simplify(text)}"
    assert combined == gp.build_simplify(text, ctx)
    # Também com context_prefix vazio
    combined_empty = f"{gp.SYSTEM_SIMPLIFY}\n\n{gp.user_simplify(text)}"
    assert combined_empty == gp.build_simplify(text, "")


def test_system_plus_user_structure_matches_build_structure():
    """SYSTEM_STRUCTURE + user_structure == build_structure (sem context_prefix)."""
    text = "rascunho COSTAR"
    combined = f"{gp.SYSTEM_STRUCTURE}\n\n{gp.user_structure(text)}"
    assert combined == gp.build_structure(text)


def test_system_plus_user_bullet_dump_matches_build_bullet_dump():
    """SYSTEM_BULLET_DUMP + user_bullet_dump == build_bullet_dump byte-identical."""
    text = "conteúdo extenso com bullets"
    ctx = "CTX> "
    combined = f"{ctx}{gp.SYSTEM_BULLET_DUMP}\n\n{gp.user_bullet_dump(text)}"
    assert combined == gp.build_bullet_dump(text, ctx)
    combined_empty = f"{gp.SYSTEM_BULLET_DUMP}\n\n{gp.user_bullet_dump(text)}"
    assert combined_empty == gp.build_bullet_dump(text, "")


def test_system_plus_user_draft_email_matches_build_draft_email():
    """SYSTEM_DRAFT_EMAIL + user_draft_email == build_draft_email byte-identical."""
    text = "rascunho de email para cliente"
    ctx = "CTX> "
    combined = f"{ctx}{gp.SYSTEM_DRAFT_EMAIL}\n\n{gp.user_draft_email(text)}"
    assert combined == gp.build_draft_email(text, ctx)


def test_system_plus_user_translate_matches_build_translate():
    """SYSTEM_TRANSLATE.format(lang_name=...) + user_translate == build_translate."""
    text = "olá mundo"
    ctx = "CTX> "
    # target_lang='en' → lang_name='inglês'
    sys_en = gp.SYSTEM_TRANSLATE.format(lang_name="inglês")
    combined_en = f"{ctx}{sys_en}\n\n{gp.user_translate(text)}"
    assert combined_en == gp.build_translate(text, "en", ctx)
    # target_lang!='en' → lang_name='português brasileiro'
    sys_pt = gp.SYSTEM_TRANSLATE.format(lang_name="português brasileiro")
    combined_pt = f"{sys_pt}\n\n{gp.user_translate(text)}"
    assert combined_pt == gp.build_translate(text, "pt", "")


def test_system_plus_user_command_matches_build_command():
    """SYSTEM_COMMAND + user_command == build_command byte-identical."""
    instruction = "make this more formal"
    selected = "oi cara, qual a boa?"
    combined = f"{gp.SYSTEM_COMMAND}\n\n{gp.user_command(instruction, selected)}"
    assert combined == gp.build_command(instruction, selected)


def test_system_correct_minimal_plus_user_correct_matches_legacy_template():
    """SYSTEM_CORRECT_MINIMAL + user_correct == CORRECT_MINIMAL.format() byte-identical."""
    text = "hello world"
    combined = f"{gp.SYSTEM_CORRECT_MINIMAL}\n\n{gp.user_correct(text)}"
    legacy = gp.CORRECT_MINIMAL.format(text=text)
    assert combined == legacy


def test_system_correct_smart_plus_user_correct_matches_legacy_template():
    """SYSTEM_CORRECT_SMART + user_correct == CORRECT_SMART.format() byte-identical."""
    text = "texto exemplo aqui"
    combined = f"{gp.SYSTEM_CORRECT_SMART}\n\n{gp.user_correct(text)}"
    legacy = gp.CORRECT_SMART.format(text=text)
    assert combined == legacy


def test_user_simplify_with_context_prefix_param():
    """user_simplify(text, context_prefix='X') prepends X (uso direto pelo openrouter)."""
    out = gp.user_simplify("foo", "PFX> ")
    assert out == "PFX> Transcrição: foo"
    # Sem context_prefix, prefixo vazio
    assert gp.user_simplify("foo") == "Transcrição: foo"


def test_user_command_orders_selected_before_instruction():
    """user_command preserva ordem [SELECTED TEXT] antes de [INSTRUCTION]."""
    out = gp.user_command("instr", "sel")
    assert out == "[SELECTED TEXT]\nsel\n\n[INSTRUCTION]\ninstr"


def test_system_simplify_does_not_have_trailing_newline():
    """SYSTEM_SIMPLIFY não termina com newline (separador \\n\\n vem do builder)."""
    assert not gp.SYSTEM_SIMPLIFY.endswith("\n")


def test_system_translate_template_has_lang_name_placeholder():
    """SYSTEM_TRANSLATE é template com placeholder {lang_name}."""
    assert "{lang_name}" in gp.SYSTEM_TRANSLATE
    out = gp.SYSTEM_TRANSLATE.format(lang_name="inglês")
    assert "{lang_name}" not in out
    assert "traduza para inglês" in out


def test_system_correct_minimal_does_not_contain_text_placeholder():
    """SYSTEM_CORRECT_MINIMAL é o system isolado, sem 'Texto: {text}'."""
    assert "{text}" not in gp.SYSTEM_CORRECT_MINIMAL
    assert "Texto:" not in gp.SYSTEM_CORRECT_MINIMAL
    assert "MINIMALISTA" in gp.SYSTEM_CORRECT_MINIMAL
