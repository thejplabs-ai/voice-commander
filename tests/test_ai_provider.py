"""
Tests for voice/ai_provider.py — Provider Protocol dispatch + mode resolution.

Strategy: monkeypatch each provider's `chat()` method on its module-level
_PROVIDER singleton. Asserts the orchestration contract that _run() and
process() guarantee, without exercising real SDK calls.
Priority: OPENROUTER_API_KEY > GEMINI_API_KEY.
"""
from unittest.mock import MagicMock

import pytest

from voice import ai_provider, state


@pytest.fixture(autouse=True)
def reset_runtime_state(monkeypatch):
    """Each test starts with a clean config."""
    monkeypatch.setattr(state, "_CONFIG", {})
    monkeypatch.setattr(state, "_clipboard_context", "")
    monkeypatch.setattr(state, "_command_selected_text", "")
    monkeypatch.setattr(state, "_GEMINI_API_KEY", None)
    monkeypatch.setattr(state, "_window_context", {})


def _stub_openrouter(monkeypatch, return_value="or_result"):
    """Replace OpenRouter provider chat() with a stub. Returns the mock."""
    from voice import openrouter
    mock_chat = MagicMock(return_value=return_value)
    monkeypatch.setattr(openrouter._PROVIDER, "chat", mock_chat)
    return mock_chat


def _stub_gemini(monkeypatch, return_value="gemini_result"):
    """Replace Gemini provider chat() with a stub. Returns the mock."""
    from voice import gemini
    mock_chat = MagicMock(return_value=return_value)
    monkeypatch.setattr(gemini._PROVIDER, "chat", mock_chat)
    return mock_chat


# ---------------------------------------------------------------------------
# Provider priority routing
# ---------------------------------------------------------------------------

def test_sem_nenhuma_key_retorna_texto_original():
    """Without any API key configured, process() returns the input unchanged."""
    state._CONFIG.clear()
    assert ai_provider.process("transcribe", "hello") == "hello"


def test_gemini_dispatch_quando_so_gemini_key(monkeypatch):
    """When only GEMINI_API_KEY is set, process() routes to GeminiProvider."""
    state._CONFIG["GEMINI_API_KEY"] = "test-key"
    monkeypatch.setattr(state, "_GEMINI_API_KEY", "test-key")
    chat = _stub_gemini(monkeypatch, return_value="gemini_output")

    result = ai_provider.process("transcribe", "text")

    chat.assert_called_once()
    assert result == "gemini_output"


def test_openrouter_tem_prioridade_sobre_gemini(monkeypatch):
    """OPENROUTER_API_KEY wins over GEMINI_API_KEY when both are set."""
    state._CONFIG.update({"OPENROUTER_API_KEY": "or-key", "GEMINI_API_KEY": "g-key"})
    monkeypatch.setattr(state, "_GEMINI_API_KEY", "g-key")
    or_chat = _stub_openrouter(monkeypatch, return_value="or_output")
    g_chat = _stub_gemini(monkeypatch)

    result = ai_provider.process("transcribe", "text")

    or_chat.assert_called_once()
    g_chat.assert_not_called()
    assert result == "or_output"


def test_modo_desconhecido_retorna_texto_original(monkeypatch):
    """Unknown mode returns the original text unchanged."""
    state._CONFIG["GEMINI_API_KEY"] = "k"
    monkeypatch.setattr(state, "_GEMINI_API_KEY", "k")
    _stub_gemini(monkeypatch)

    assert ai_provider.process("modo_inexistente", "texto original") == "texto original"


# ---------------------------------------------------------------------------
# Mode→spec resolution
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["transcribe", "simple", "prompt", "bullet", "email", "translate"])
def test_modes_routam_para_provider_chat(monkeypatch, mode):
    """Each canonical mode dispatches through the active provider's chat()."""
    state._CONFIG["OPENROUTER_API_KEY"] = "or-key"
    state._CONFIG["CORRECTION_STYLE"] = "smart"
    chat = _stub_openrouter(monkeypatch, return_value=f"{mode}_output")

    result = ai_provider.process(mode, "input_text")

    chat.assert_called_once()
    assert result == f"{mode}_output"


def test_query_sem_clipboard_usa_spec_query(monkeypatch):
    """query mode uses PROMPTS['query'] when clipboard context is empty."""
    state._CONFIG.update({"OPENROUTER_API_KEY": "or-key", "CLIPBOARD_CONTEXT_ENABLED": True})
    state._clipboard_context = ""
    chat = _stub_openrouter(monkeypatch, return_value="query_out")

    result = ai_provider.process("query", "minha query")

    chat.assert_called_once()
    # PROMPTS["query"].user_builder(text) == text (no clipboard injected)
    assert chat.call_args.kwargs["user"] == "minha query"
    assert result == "query_out"


def test_query_com_clipboard_usa_spec_query_with_clipboard(monkeypatch):
    """query mode with non-empty clipboard uses PROMPTS['query_with_clipboard']."""
    state._CONFIG.update({"OPENROUTER_API_KEY": "or-key", "CLIPBOARD_CONTEXT_ENABLED": True})
    state._clipboard_context = "contexto do clipboard"
    chat = _stub_openrouter(monkeypatch, return_value="ctx_out")

    result = ai_provider.process("query", "instrução de voz")

    chat.assert_called_once()
    user_msg = chat.call_args.kwargs["user"]
    assert "[CONTEXTO DO CLIPBOARD]" in user_msg
    assert "contexto do clipboard" in user_msg
    assert "instrução de voz" in user_msg
    assert result == "ctx_out"


def test_query_clipboard_desativado_usa_query_normal(monkeypatch):
    """CLIPBOARD_CONTEXT_ENABLED=False falls back to plain query spec."""
    state._CONFIG.update({"OPENROUTER_API_KEY": "or-key", "CLIPBOARD_CONTEXT_ENABLED": False})
    state._clipboard_context = "ignorado"
    chat = _stub_openrouter(monkeypatch, return_value="query_out")

    result = ai_provider.process("query", "pergunta")

    chat.assert_called_once()
    assert chat.call_args.kwargs["user"] == "pergunta"
    assert result == "query_out"


def test_command_mode_injeta_selected_text(monkeypatch):
    """command mode pulls state._command_selected_text into the user message."""
    state._CONFIG["OPENROUTER_API_KEY"] = "or-key"
    state._command_selected_text = "olá amigo"
    chat = _stub_openrouter(monkeypatch, return_value="reformulado")

    result = ai_provider.process("command", "deixa mais formal")

    chat.assert_called_once()
    user_msg = chat.call_args.kwargs["user"]
    assert "[SELECTED TEXT]" in user_msg
    assert "olá amigo" in user_msg
    assert "[INSTRUCTION]" in user_msg
    assert "deixa mais formal" in user_msg
    assert result == "reformulado"


# ---------------------------------------------------------------------------
# Fallback resolution by spec.fallback_kind
# ---------------------------------------------------------------------------

def test_fallback_text_quando_chat_retorna_vazio(monkeypatch):
    """fallback_kind='text' (transcribe/simple/etc.) returns original text on empty response."""
    state._CONFIG["OPENROUTER_API_KEY"] = "or-key"
    _stub_openrouter(monkeypatch, return_value=None)

    assert ai_provider.process("simple", "texto original") == "texto original"


def test_fallback_sentinel_para_query(monkeypatch):
    """fallback_kind='sentinel' for query returns '[SEM RESPOSTA] {text}'."""
    state._CONFIG["OPENROUTER_API_KEY"] = "or-key"
    _stub_openrouter(monkeypatch, return_value=None)

    result = ai_provider.process("query", "pergunta")

    assert result == "[SEM RESPOSTA] pergunta"


def test_fallback_selected_para_command(monkeypatch):
    """fallback_kind='selected' for command returns state._command_selected_text."""
    state._CONFIG["OPENROUTER_API_KEY"] = "or-key"
    state._command_selected_text = "texto preservado"
    _stub_openrouter(monkeypatch, return_value=None)

    result = ai_provider.process("command", "instrução")

    assert result == "texto preservado"


# ---------------------------------------------------------------------------
# Rate limit response surfaces from provider
# ---------------------------------------------------------------------------

def test_rate_limit_propagation(monkeypatch):
    """When provider.chat raises and provider.is_rate_limit is True, returns provider.rate_limit_msg()."""
    from voice import openrouter
    state._CONFIG["OPENROUTER_API_KEY"] = "or-key"

    def _raise_rate_limit(**_):
        raise Exception("429 rate_limit")

    monkeypatch.setattr(openrouter._PROVIDER, "chat", _raise_rate_limit)

    result = ai_provider.process("transcribe", "texto")

    assert "[LIMITE ATINGIDO]" in result


def test_erro_generico_retorna_fallback(monkeypatch):
    """Generic exception (not rate-limit) returns the fallback per spec.fallback_kind."""
    from voice import openrouter
    state._CONFIG["OPENROUTER_API_KEY"] = "or-key"

    def _raise(**_):
        raise Exception("connection timeout")

    monkeypatch.setattr(openrouter._PROVIDER, "chat", _raise)

    assert ai_provider.process("simple", "texto") == "texto"


# ---------------------------------------------------------------------------
# Output guard (W1 reliability sprint — Task 5): transcribe-only ratio guard
# ---------------------------------------------------------------------------


def test_output_guard_descarta_correcao_desproporcional_e_usa_texto_cru(monkeypatch):
    """transcribe: output desproporcional (resposta/expansão do modelo) é descartado — retorna o texto cru."""
    state._CONFIG["OPENROUTER_API_KEY"] = "or-key"
    input_text = "a" * 100
    disproportionate_output = "Entendo! Vamos construir a descrição da vaga juntos. " * 8  # ~400+ chars
    _stub_openrouter(monkeypatch, return_value=disproportionate_output)

    result = ai_provider.process("transcribe", input_text)

    assert result == input_text


def test_output_guard_aceita_correcao_proporcional(monkeypatch):
    """transcribe: output dentro da faixa 0.5-2.0 é aceito normalmente."""
    state._CONFIG["OPENROUTER_API_KEY"] = "or-key"
    input_text = "a" * 100
    proportional_output = "b" * 110
    _stub_openrouter(monkeypatch, return_value=proportional_output)

    result = ai_provider.process("transcribe", input_text)

    assert result == proportional_output


def test_output_guard_nao_afeta_modos_sem_guard(monkeypatch):
    """simple mode não tem output_guard — output desproporcional passa normalmente."""
    state._CONFIG["OPENROUTER_API_KEY"] = "or-key"
    input_text = "a" * 100
    disproportionate_output = "b" * 500
    _stub_openrouter(monkeypatch, return_value=disproportionate_output)

    result = ai_provider.process("simple", input_text)

    assert result == disproportionate_output
