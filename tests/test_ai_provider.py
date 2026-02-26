"""
Tests for voice/ai_provider.py — provider dispatch routing.

Strategy: patch sys.modules to inject mock Gemini/OpenAI modules,
and control AI_PROVIDER via state._CONFIG.
"""
import sys
from unittest.mock import MagicMock

import pytest

import voice
from voice import ai_provider


@pytest.fixture(autouse=True)
def clean_config(monkeypatch):
    """Start each test with a known config."""
    cfg = {"AI_PROVIDER": "gemini"}
    monkeypatch.setattr(voice.state, "_CONFIG", cfg)
    return cfg


def _mock_gemini(monkeypatch) -> MagicMock:
    """
    Return a MagicMock for voice.gemini and wire it into both sys.modules
    and the package attribute that `from voice import gemini` resolves.

    `from voice import gemini` reads the *package attribute* (set when
    __init__.py ran `from voice.gemini import _get_gemini_client`), not
    sys.modules directly.  Patching the attribute is required.
    """
    mock = MagicMock()
    monkeypatch.setattr(voice, "gemini", mock)
    monkeypatch.setitem(sys.modules, "voice.gemini", mock)
    return mock


def _mock_openai(monkeypatch) -> MagicMock:
    """Return a MagicMock for voice.openai_ wired into sys.modules."""
    mock = MagicMock()
    monkeypatch.setitem(sys.modules, "voice.openai_", mock)
    return mock


# ---------------------------------------------------------------------------
# Provider routing
# ---------------------------------------------------------------------------

def test_default_provider_e_gemini_quando_chave_ausente(monkeypatch):
    """When AI_PROVIDER is absent from config, routes to Gemini."""
    monkeypatch.setattr(voice.state, "_CONFIG", {})
    mock = _mock_gemini(monkeypatch)
    mock.correct_with_gemini.return_value = "corrected"

    result = ai_provider.process("transcribe", "hello")

    mock.correct_with_gemini.assert_called_once_with("hello")
    assert result == "corrected"


def test_gemini_provider_dispatch(monkeypatch):
    """When AI_PROVIDER=gemini, routes to Gemini functions."""
    monkeypatch.setattr(voice.state, "_CONFIG", {"AI_PROVIDER": "gemini"})
    mock = _mock_gemini(monkeypatch)
    mock.correct_with_gemini.return_value = "gemini_result"

    result = ai_provider.process("transcribe", "text")

    mock.correct_with_gemini.assert_called_once_with("text")
    assert result == "gemini_result"


def test_openai_provider_dispatch(monkeypatch):
    """When AI_PROVIDER=openai, routes to OpenAI functions."""
    monkeypatch.setattr(voice.state, "_CONFIG", {"AI_PROVIDER": "openai"})
    mock = _mock_openai(monkeypatch)
    mock.correct_with_openai.return_value = "openai_result"

    result = ai_provider.process("transcribe", "text")

    mock.correct_with_openai.assert_called_once_with("text")
    assert result == "openai_result"


def test_modo_desconhecido_retorna_texto_original(monkeypatch):
    """Unknown mode returns the original text unchanged."""
    monkeypatch.setattr(voice.state, "_CONFIG", {"AI_PROVIDER": "gemini"})
    mock = _mock_gemini(monkeypatch)

    result = ai_provider.process("modo_inexistente", "texto original")

    assert result == "texto original"
    mock.correct_with_gemini.assert_not_called()


def test_modo_desconhecido_openai_retorna_texto_original(monkeypatch):
    """Unknown mode returns the original text unchanged for OpenAI too."""
    monkeypatch.setattr(voice.state, "_CONFIG", {"AI_PROVIDER": "openai"})
    _mock_openai(monkeypatch)

    result = ai_provider.process("modo_inexistente", "texto original")

    assert result == "texto original"


# ---------------------------------------------------------------------------
# Todos os 7 modos — Gemini
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
    """Each of the 7 non-query modes dispatches to the correct Gemini function."""
    monkeypatch.setattr(voice.state, "_CONFIG", {"AI_PROVIDER": "gemini"})
    mock = _mock_gemini(monkeypatch)
    getattr(mock, gemini_fn).return_value = f"{mode}_output"

    result = ai_provider.process(mode, "input_text")

    getattr(mock, gemini_fn).assert_called_once_with("input_text")
    assert result == f"{mode}_output"


def test_query_modo_sem_clipboard_usa_query_with_gemini(monkeypatch):
    """Query mode dispatches to query_with_gemini when clipboard context is empty."""
    monkeypatch.setattr(voice.state, "_CONFIG", {
        "AI_PROVIDER": "gemini",
        "CLIPBOARD_CONTEXT_ENABLED": "true",
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
        "AI_PROVIDER": "gemini",
        "CLIPBOARD_CONTEXT_ENABLED": "true",
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
        "AI_PROVIDER": "gemini",
        "CLIPBOARD_CONTEXT_ENABLED": "false",
    })
    monkeypatch.setattr(voice.state, "_clipboard_context", "tem conteúdo mas ignorado")
    mock = _mock_gemini(monkeypatch)
    mock.query_with_gemini.return_value = "query_output"

    result = ai_provider.process("query", "pergunta")

    mock.query_with_gemini.assert_called_once_with("pergunta")
    assert result == "query_output"


# ---------------------------------------------------------------------------
# Todos os 7 modos — OpenAI
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
    monkeypatch.setattr(voice.state, "_CONFIG", {"AI_PROVIDER": "openai"})
    mock = _mock_openai(monkeypatch)
    getattr(mock, openai_fn).return_value = f"{mode}_output"

    result = ai_provider.process(mode, "input_text")

    getattr(mock, openai_fn).assert_called_once_with("input_text")
    assert result == f"{mode}_output"
