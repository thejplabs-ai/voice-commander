"""
Tests for voice/gemini_prompts.py::sanitize_llm_output — deterministic cleanup
of LLM correction output (preamble lines, <<< >>> delimiter leftovers).

Bug B (production audit 2026-07): 218/530 correction outputs pasted junk from
the correction model — preamble text ("Aqui está o texto corrigido:") and/or
leftover <<< >>> delimiters from the user_correct() prompt template
(voice/gemini_prompts.py:264). No sanitization existed anywhere before this.

Rules applied at the EDGES only — never touch content in the middle.
"""
from unittest.mock import MagicMock

from voice import ai_provider, gemini_prompts as gp, state


# ---------------------------------------------------------------------------
# sanitize_llm_output — pure function tests
# ---------------------------------------------------------------------------


def test_preamble_and_delimiters_stripped():
    """Real production pattern: preamble line + <<< >>> wrapping."""
    raw = "Aqui está o texto corrigido:\n\n<<< \nOlá mundo.\n>>>"
    assert gp.sanitize_llm_output(raw) == "Olá mundo."


def test_only_delimiters_stripped():
    raw = "<<<\ntexto\n>>>"
    assert gp.sanitize_llm_output(raw) == "texto"


def test_inline_preamble_same_line_preserved():
    """Preamble sharing the line with real content is NOT a full-line match —
    must be preserved verbatim (never strip mid-line content)."""
    raw = "Texto corrigido: Olá."
    assert gp.sanitize_llm_output(raw) == "Texto corrigido: Olá."


def test_preamble_only_line_then_content_stripped():
    """Real case: preamble occupies its own line, content follows after a
    blank line — preamble line removed, content preserved."""
    raw = "Aqui está o texto corrigido:\n\nOlá."
    assert gp.sanitize_llm_output(raw) == "Olá."


def test_trailing_delimiter_residual_stripped():
    raw = "texto certo >>>"
    assert gp.sanitize_llm_output(raw) == "texto certo"


def test_clean_text_unchanged():
    assert gp.sanitize_llm_output("Olá, tudo bem?") == "Olá, tudo bem?"


def test_idempotent():
    raw = "Aqui está o texto corrigido:\n\n<<< \nOlá mundo.\n>>>"
    once = gp.sanitize_llm_output(raw)
    twice = gp.sanitize_llm_output(once)
    assert once == twice


def test_delimiter_in_the_middle_preserved():
    """<<< dictated by the user deep in the text (beyond the 80-char lead-in
    window) must never be touched — only edge leftovers from the prompt
    template are junk."""
    padding = "Isso é uma frase bem longa que o usuário realmente ditou " * 2
    raw = f"{padding}e ele disse <<< isso aqui >>> como parte do conteúdo."
    assert gp.sanitize_llm_output(raw) == raw.strip()
    assert "<<<" in gp.sanitize_llm_output(raw)


def test_legit_www_preserved():
    raw = "Confira www.example.com para mais detalhes."
    assert gp.sanitize_llm_output(raw) == raw


def test_empty_after_strip_returns_original_input():
    """Fail-safe: never degrade a non-empty output to empty."""
    raw = "<<<>>>"
    assert gp.sanitize_llm_output(raw) == raw


# ---------------------------------------------------------------------------
# Integration — ai_provider._run() sanitizes before output_guard/success_hook
# ---------------------------------------------------------------------------


def _stub_openrouter(monkeypatch, return_value):
    from voice import openrouter
    mock_chat = MagicMock(return_value=return_value)
    monkeypatch.setattr(openrouter._PROVIDER, "chat", mock_chat)
    return mock_chat


def test_process_transcribe_sanitizes_and_feeds_clean_text_to_vocab_hook(monkeypatch):
    """process('transcribe', ...) returns sanitized text, and the vocabulary
    success hook receives the already-clean result (not the raw LLM junk)."""
    monkeypatch.setattr(state, "_CONFIG", {"OPENROUTER_API_KEY": "or-key"})
    dirty = "Aqui está o texto corrigido:\n\n<<< \nresultado limpo\n>>>"
    _stub_openrouter(monkeypatch, dirty)

    from voice import vocabulary
    mock_learn = MagicMock(return_value=[])
    monkeypatch.setattr(vocabulary, "learn_from_correction", mock_learn)

    result = ai_provider.process("transcribe", "input original")

    assert result == "resultado limpo"
    mock_learn.assert_called_once()
    _raw_arg, corrected_arg = mock_learn.call_args.args
    assert corrected_arg == "resultado limpo"
