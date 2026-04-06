# tests/test_correction_style.py — Epic 5.3: Pontuação Inteligente
#
# Testa que CORRECTION_STYLE routing direciona para o prompt correto
# em gemini.py e openrouter.py, sem fazer chamadas reais à API.

from unittest.mock import MagicMock, patch

import pytest

import voice.state as state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_config(**overrides):
    """Monta um dict de config mínimo com overrides aplicados."""
    base = {
        "GEMINI_CORRECT": True,
        "GEMINI_MODEL": "gemini-2.5-flash",
        "CORRECTION_STYLE": "smart",
        "OPENROUTER_MODEL_FAST": "meta-llama/llama-4-scout-17b-16e-instruct",
        "OPENROUTER_MODEL_QUALITY": "google/gemini-2.5-flash",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Config default
# ---------------------------------------------------------------------------

def test_correction_style_default():
    """CORRECTION_STYLE default deve ser 'smart' em load_config()."""
    from voice.config import load_config
    with patch("os.path.exists", return_value=False):
        cfg = load_config()
    assert cfg["CORRECTION_STYLE"] == "smart"


# ---------------------------------------------------------------------------
# gemini.py — CORRECTION_STYLE=off
# ---------------------------------------------------------------------------

def test_correction_style_off_gemini():
    """CORRECTION_STYLE=off deve retornar o texto original sem chamar o cliente Gemini."""
    state._CONFIG = _set_config(CORRECTION_STYLE="off")
    state._GEMINI_API_KEY = "AIzaFAKEKEY"

    mock_client = MagicMock()
    with patch("voice.gemini._get_gemini_client", return_value=mock_client):
        from voice.gemini import correct_with_gemini
        result = correct_with_gemini("texto sem pontuacao")

    assert result == "texto sem pontuacao"
    mock_client.models.generate_content.assert_not_called()


# ---------------------------------------------------------------------------
# openrouter.py — CORRECTION_STYLE=off
# ---------------------------------------------------------------------------

def test_correction_style_off_openrouter():
    """CORRECTION_STYLE=off deve retornar o texto original sem chamar o cliente OpenRouter."""
    state._CONFIG = _set_config(CORRECTION_STYLE="off")

    with patch("voice.openrouter._call") as mock_call:
        from voice.openrouter import correct
        result = correct("texto sem pontuacao")

    assert result == "texto sem pontuacao"
    mock_call.assert_not_called()


# ---------------------------------------------------------------------------
# gemini.py — CORRECTION_STYLE=minimal
# ---------------------------------------------------------------------------

def test_correction_style_minimal_gemini():
    """CORRECTION_STYLE=minimal deve usar o prompt MINIMALISTA."""
    state._CONFIG = _set_config(CORRECTION_STYLE="minimal")
    state._GEMINI_API_KEY = "AIzaFAKEKEY"

    captured_prompt: list[str] = []

    mock_response = MagicMock()
    mock_response.text = "texto corrigido"

    mock_client = MagicMock()

    def _fake_generate(model, contents):
        captured_prompt.append(contents)
        return mock_response

    mock_client.models.generate_content.side_effect = _fake_generate

    with patch("voice.gemini._get_gemini_client", return_value=mock_client):
        from voice.gemini import correct_with_gemini
        result = correct_with_gemini("texto sem pontuacao")

    assert result == "texto corrigido"
    assert captured_prompt, "generate_content não foi chamado"
    prompt_text = str(captured_prompt[0])
    assert "MINIMALISTA" in prompt_text


# ---------------------------------------------------------------------------
# gemini.py — CORRECTION_STYLE=smart
# ---------------------------------------------------------------------------

def test_correction_style_smart_gemini():
    """CORRECTION_STYLE=smart deve usar o prompt inteligente com pontuação automática."""
    state._CONFIG = _set_config(CORRECTION_STYLE="smart")
    state._GEMINI_API_KEY = "AIzaFAKEKEY"

    captured_prompt: list[str] = []

    mock_response = MagicMock()
    mock_response.text = "Texto com pontuação."

    mock_client = MagicMock()

    def _fake_generate(model, contents):
        captured_prompt.append(contents)
        return mock_response

    mock_client.models.generate_content.side_effect = _fake_generate

    with patch("voice.gemini._get_gemini_client", return_value=mock_client):
        from voice.gemini import correct_with_gemini
        result = correct_with_gemini("texto sem pontuacao")

    assert result == "Texto com pontuação."
    assert captured_prompt, "generate_content não foi chamado"
    prompt_text = str(captured_prompt[0])
    # Verifica marcadores do prompt smart
    assert "inteligente" in prompt_text or "pontuação automaticamente" in prompt_text


# ---------------------------------------------------------------------------
# openrouter.py — CORRECTION_STYLE=minimal
# ---------------------------------------------------------------------------

def test_correction_style_minimal_openrouter():
    """CORRECTION_STYLE=minimal deve passar o system prompt MINIMALIST ao _call."""
    state._CONFIG = _set_config(CORRECTION_STYLE="minimal")

    captured_system: list[str] = []

    def _fake_call(system, user, model, temperature=0.2):
        captured_system.append(system)
        return "texto corrigido"

    with patch("voice.openrouter._call", side_effect=_fake_call):
        from voice.openrouter import correct
        result = correct("texto sem pontuacao")

    assert result == "texto corrigido"
    assert captured_system, "_call não foi chamado"
    assert "MINIMALIST" in captured_system[0]


# ---------------------------------------------------------------------------
# openrouter.py — CORRECTION_STYLE=smart
# ---------------------------------------------------------------------------

def test_correction_style_smart_openrouter():
    """CORRECTION_STYLE=smart deve passar o system prompt smart ao _call."""
    state._CONFIG = _set_config(CORRECTION_STYLE="smart")

    captured_system: list[str] = []

    def _fake_call(system, user, model, temperature=0.2):
        captured_system.append(system)
        return "Texto com pontuação."

    with patch("voice.openrouter._call", side_effect=_fake_call):
        from voice.openrouter import correct
        result = correct("texto sem pontuacao")

    assert result == "Texto com pontuação."
    assert captured_system, "_call não foi chamado"
    # Verifica marcadores do prompt smart
    system_text = captured_system[0]
    assert "smart" in system_text.lower() or "punctuation automatically" in system_text.lower()
