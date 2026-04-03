"""
Tests for voice/ai_provider.py — provider dispatch routing.

Strategy: patch sys.modules to inject mock Gemini/OpenAI/OpenRouter modules,
and control provider priority via config keys.
Priority: OPENROUTER_API_KEY > GEMINI_API_KEY > OPENAI_API_KEY
"""
import sys
from unittest.mock import MagicMock

import pytest

import voice
from voice import ai_provider


@pytest.fixture(autouse=True)
def clean_config(monkeypatch):
    """Start each test with a known config."""
    cfg = {"GEMINI_API_KEY": "test-gemini-key"}
    monkeypatch.setattr(voice.state, "_CONFIG", cfg)
    return cfg


def _mock_gemini(monkeypatch) -> MagicMock:
    mock = MagicMock()
    monkeypatch.setattr(voice, "gemini", mock)
    monkeypatch.setitem(sys.modules, "voice.gemini", mock)
    return mock


def _mock_openai(monkeypatch) -> MagicMock:
    mock = MagicMock()
    monkeypatch.setitem(sys.modules, "voice.openai_", mock)
    return mock


def _mock_openrouter(monkeypatch) -> MagicMock:
    mock = MagicMock()
    monkeypatch.setitem(sys.modules, "voice.openrouter", mock)
    # Also set package attr so `from voice import openrouter` resolves
    monkeypatch.setattr(voice, "openrouter", mock, raising=False)
    return mock


# ---------------------------------------------------------------------------
# Provider priority routing
# ---------------------------------------------------------------------------

def test_sem_nenhuma_key_retorna_texto_original(monkeypatch):
    """When no API keys configured, returns original text."""
    monkeypatch.setattr(voice.state, "_CONFIG", {})
    result = ai_provider.process("transcribe", "hello")
    assert result == "hello"


def test_gemini_dispatch_quando_so_gemini_key(monkeypatch):
    """When only GEMINI_API_KEY is set, routes to Gemini."""
    monkeypatch.setattr(voice.state, "_CONFIG", {"GEMINI_API_KEY": "test-key"})
    mock = _mock_gemini(monkeypatch)
    mock.correct_with_gemini.return_value = "gemini_result"

    result = ai_provider.process("transcribe", "text")

    mock.correct_with_gemini.assert_called_once_with("text")
    assert result == "gemini_result"


def test_openrouter_tem_prioridade_sobre_gemini(monkeypatch):
    """When OPENROUTER_API_KEY is set, it takes priority over GEMINI_API_KEY."""
    monkeypatch.setattr(voice.state, "_CONFIG", {
        "OPENROUTER_API_KEY": "or-key",
        "GEMINI_API_KEY": "gemini-key",
    })
    mock_or = _mock_openrouter(monkeypatch)
    mock_or.correct.return_value = "openrouter_result"
    mock_gem = _mock_gemini(monkeypatch)

    result = ai_provider.process("transcribe", "text")

    mock_or.correct.assert_called_once_with("text")
    mock_gem.correct_with_gemini.assert_not_called()
    assert result == "openrouter_result"


def test_openai_provider_dispatch(monkeypatch):
    """When only OPENAI_API_KEY is set, routes to OpenAI."""
    monkeypatch.setattr(voice.state, "_CONFIG", {"OPENAI_API_KEY": "test-key"})
    mock = _mock_openai(monkeypatch)
    mock.correct_with_openai.return_value = "openai_result"

    result = ai_provider.process("transcribe", "text")

    mock.correct_with_openai.assert_called_once_with("text")
    assert result == "openai_result"


def test_modo_desconhecido_retorna_texto_original(monkeypatch):
    """Unknown mode returns the original text unchanged."""
    monkeypatch.setattr(voice.state, "_CONFIG", {"GEMINI_API_KEY": "k"})
    _mock_gemini(monkeypatch)

    result = ai_provider.process("modo_inexistente", "texto original")

    assert result == "texto original"


# ---------------------------------------------------------------------------
# Todos os 6 modos nao-query — Gemini
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode,gemini_fn", [
    ("transcribe", "correct_with_gemini"),
    ("simple",     "simplify_as_prompt"),
    ("prompt",     "structure_as_prompt"),
    ("bullet",     "bullet_dump_with_gemini"),
    ("email",      "draft_email_with_gemini"),
    ("translate",  "translate_with_gemini"),
])
def test_todos_modos_gemini(monkeypatch, mode, gemini_fn):
    """Each non-query mode dispatches to the correct Gemini function."""
    monkeypatch.setattr(voice.state, "_CONFIG", {"GEMINI_API_KEY": "k"})
    mock = _mock_gemini(monkeypatch)
    getattr(mock, gemini_fn).return_value = f"{mode}_output"

    result = ai_provider.process(mode, "input_text")

    getattr(mock, gemini_fn).assert_called_once_with("input_text")
    assert result == f"{mode}_output"


def test_query_modo_sem_clipboard_usa_query_with_gemini(monkeypatch):
    """Query mode dispatches to query_with_gemini when clipboard context is empty."""
    monkeypatch.setattr(voice.state, "_CONFIG", {
        "GEMINI_API_KEY": "k",
        "CLIPBOARD_CONTEXT_ENABLED": True,
    })
    monkeypatch.setattr(voice.state, "_clipboard_context", "")
    mock = _mock_gemini(monkeypatch)
    mock.query_with_gemini.return_value = "query_output"

    result = ai_provider.process("query", "minha query")

    mock.query_with_gemini.assert_called_once_with("minha query")
    assert result == "query_output"


def test_query_modo_com_clipboard_usa_query_with_clipboard_context(monkeypatch):
    """Query mode dispatches to query_with_clipboard_context when clipboard is set."""
    monkeypatch.setattr(voice.state, "_CONFIG", {
        "GEMINI_API_KEY": "k",
        "CLIPBOARD_CONTEXT_ENABLED": True,
    })
    monkeypatch.setattr(voice.state, "_clipboard_context", "contexto do clipboard")
    mock = _mock_gemini(monkeypatch)
    mock.query_with_clipboard_context.return_value = "context_output"

    result = ai_provider.process("query", "instrução de voz")

    mock.query_with_clipboard_context.assert_called_once_with("instrução de voz", "contexto do clipboard")
    assert result == "context_output"


def test_query_clipboard_desativado_usa_query_normal(monkeypatch):
    """When CLIPBOARD_CONTEXT_ENABLED=false, query uses query_with_gemini."""
    monkeypatch.setattr(voice.state, "_CONFIG", {
        "GEMINI_API_KEY": "k",
        "CLIPBOARD_CONTEXT_ENABLED": False,
    })
    monkeypatch.setattr(voice.state, "_clipboard_context", "tem conteudo mas ignorado")
    mock = _mock_gemini(monkeypatch)
    mock.query_with_gemini.return_value = "query_output"

    result = ai_provider.process("query", "pergunta")

    mock.query_with_gemini.assert_called_once_with("pergunta")
    assert result == "query_output"


# ---------------------------------------------------------------------------
# OpenRouter — smart routing por modo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode,or_fn", [
    ("transcribe", "correct"),
    ("simple",     "simplify"),
    ("prompt",     "structure"),
    ("bullet",     "bullet_dump"),
    ("email",      "draft_email"),
    ("translate",  "translate"),
])
def test_todos_modos_openrouter(monkeypatch, mode, or_fn):
    """Each mode dispatches to the correct OpenRouter function."""
    monkeypatch.setattr(voice.state, "_CONFIG", {"OPENROUTER_API_KEY": "or-key"})
    mock = _mock_openrouter(monkeypatch)
    getattr(mock, or_fn).return_value = f"{mode}_output"

    result = ai_provider.process(mode, "input_text")

    getattr(mock, or_fn).assert_called_once_with("input_text")
    assert result == f"{mode}_output"


def test_openrouter_query_com_clipboard(monkeypatch):
    """OpenRouter query with clipboard context."""
    monkeypatch.setattr(voice.state, "_CONFIG", {
        "OPENROUTER_API_KEY": "or-key",
        "CLIPBOARD_CONTEXT_ENABLED": True,
    })
    monkeypatch.setattr(voice.state, "_clipboard_context", "clipboard text")
    mock = _mock_openrouter(monkeypatch)
    mock.query_with_clipboard.return_value = "or_query_output"

    result = ai_provider.process("query", "pergunta")

    mock.query_with_clipboard.assert_called_once_with("pergunta", "clipboard text")
    assert result == "or_query_output"


# ---------------------------------------------------------------------------
# Todos os 7 modos — OpenAI (legacy)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode,openai_fn", [
    ("transcribe", "correct_with_openai"),
    ("simple",     "simplify_with_openai"),
    ("prompt",     "structure_as_prompt_openai"),
    ("query",      "query_with_openai"),
    ("bullet",     "bullet_dump_with_openai"),
    ("email",      "draft_email_with_openai"),
    ("translate",  "translate_with_openai"),
])
def test_todos_modos_openai(monkeypatch, mode, openai_fn):
    """Each of the 7 modes dispatches to the correct OpenAI function."""
    monkeypatch.setattr(voice.state, "_CONFIG", {"OPENAI_API_KEY": "test-key"})
    mock = _mock_openai(monkeypatch)
    getattr(mock, openai_fn).return_value = f"{mode}_output"

    result = ai_provider.process(mode, "input_text")

    getattr(mock, openai_fn).assert_called_once_with("input_text")
    assert result == f"{mode}_output"
