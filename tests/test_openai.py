"""
Tests for voice/openai_.py — singleton, dispatch modes, rate limiting, import error.

Strategy: patch sys.modules["openai"] before touching the singleton so the
real package is never required.

IMPORTANT: We do NOT import voice.openai_ at module level. The module-level
import would permanently set the `voice.openai_` package attribute, breaking
test_ai_provider.py's `_mock_openai()` which patches sys.modules["voice.openai_"]
and relies on `from voice import openai_` resolving through sys.modules (not
the package attribute). We access voice.openai_ via sys.modules instead.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

import voice
from voice import state


def _openai():
    """Lazy accessor — returns voice.openai_ module without creating package attribute."""
    # Access directly from sys.modules (was loaded by conftest/_install_stubs indirectly,
    # or loaded on first actual use). We force load without setting voice.openai_ attribute.
    mod_key = "voice.openai_"
    if mod_key not in sys.modules:
        import importlib.util
        spec = importlib.util.find_spec("voice.openai_")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_key] = mod
        spec.loader.exec_module(mod)
    return sys.modules[mod_key]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_openai_stub(response_text: str = "mocked_result"):
    """Return a lightweight stub that mimics the openai.OpenAI interface."""
    stub = MagicMock()
    stub.OpenAI.return_value.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content=response_text))
    ]
    return stub


@pytest.fixture(autouse=True)
def reset_openai_singleton(monkeypatch):
    """Reset the OpenAI singleton and voice.openai_ package attribute."""
    monkeypatch.setattr(state, "_openai_client", None)
    monkeypatch.setattr(state, "_OPENAI_API_KEY", None)
    monkeypatch.setattr(state, "_CONFIG", {
        "OPENAI_API_KEY": "sk-test-key",
        "OPENAI_MODEL": "gpt-4o-mini",
        "TRANSLATE_TARGET_LANG": "en",
        "QUERY_SYSTEM_PROMPT": "",
        "AI_PROVIDER": "openai",
    })
    # Remove package attribute if present so test_ai_provider mocking works
    had_attr = hasattr(voice, "openai_")
    saved_attr = getattr(voice, "openai_", None)
    if had_attr:
        delattr(voice, "openai_")
    yield
    monkeypatch.setattr(state, "_openai_client", None)
    monkeypatch.setattr(state, "_OPENAI_API_KEY", None)
    # Restore state
    if had_attr:
        setattr(voice, "openai_", saved_attr)
    else:
        voice.__dict__.pop("openai_", None)


# ---------------------------------------------------------------------------
# Singleton lazy init
# ---------------------------------------------------------------------------

class TestGetOpenAIClient:
    def test_primeira_chamada_cria_cliente(self, monkeypatch):
        """First call creates the singleton and caches it in state."""
        stub = _make_openai_stub()
        monkeypatch.setitem(sys.modules, "openai", stub)

        assert state._openai_client is None
        client = _openai()._get_openai_client()
        assert client is not None
        assert state._openai_client is client

    def test_chamadas_subsequentes_reutilizam(self, monkeypatch):
        """Subsequent calls return the exact same instance (singleton pattern)."""
        stub = _make_openai_stub()
        monkeypatch.setitem(sys.modules, "openai", stub)

        mod = _openai()
        client1 = mod._get_openai_client()
        client2 = mod._get_openai_client()
        assert client1 is client2

    def test_import_error_levanta_import_error(self, monkeypatch):
        """If openai is not installed, ImportError is raised with sentinel message."""
        monkeypatch.delitem(sys.modules, "openai", raising=False)

        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def fake_import(name, *args, **kwargs):
            if name == "openai":
                raise ImportError("No module named 'openai'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            with pytest.raises(ImportError, match="openai-not-installed"):
                _openai()._get_openai_client()


# ---------------------------------------------------------------------------
# Rate limit detection
# ---------------------------------------------------------------------------

class TestIsRateLimit:
    @pytest.mark.parametrize("msg", [
        "Error 429: rate limit exceeded",
        "rate_limit error occurred",
        "ratelimit exceeded",
    ])
    def test_detecta_rate_limit(self, msg):
        assert _openai()._is_rate_limit(Exception(msg)) is True

    def test_nao_detecta_erro_comum(self):
        assert _openai()._is_rate_limit(Exception("connection refused")) is False


# ---------------------------------------------------------------------------
# The 7 dispatch modes — happy path
# ---------------------------------------------------------------------------

class TestDispatchModes:
    def _setup_client(self, monkeypatch, response: str = "ok_result"):
        stub = _make_openai_stub(response)
        monkeypatch.setitem(sys.modules, "openai", stub)
        return stub

    def test_correct_com_openai(self, monkeypatch):
        self._setup_client(monkeypatch, "Texto corrigido.")
        result = _openai().correct_with_openai("texto errado")
        assert result == "Texto corrigido."

    def test_simplify_com_openai(self, monkeypatch):
        self._setup_client(monkeypatch, "Prompt simplificado.")
        result = _openai().simplify_with_openai("voz informal")
        assert result == "Prompt simplificado."

    def test_structure_as_prompt_openai(self, monkeypatch):
        self._setup_client(monkeypatch, "<role>Dev</role>")
        result = _openai().structure_as_prompt_openai("fazer código")
        assert "<role>" in result

    def test_query_com_openai(self, monkeypatch):
        self._setup_client(monkeypatch, "Resposta da IA.")
        result = _openai().query_with_openai("qual a capital do Brasil?")
        assert result == "Resposta da IA."

    def test_bullet_dump_com_openai(self, monkeypatch):
        self._setup_client(monkeypatch, "- Item 1\n- Item 2")
        result = _openai().bullet_dump_with_openai("lista de coisas")
        assert "Item 1" in result

    def test_draft_email_com_openai(self, monkeypatch):
        self._setup_client(monkeypatch, "Assunto: Teste\n\nOlá,\n\n{Nome}")
        result = _openai().draft_email_with_openai("mandar email sobre projeto")
        assert "Assunto" in result

    def test_translate_com_openai(self, monkeypatch):
        self._setup_client(monkeypatch, "Hello world")
        result = _openai().translate_with_openai("Olá mundo")
        assert result == "Hello world"


# ---------------------------------------------------------------------------
# Fallback behavior — API key ausente
# ---------------------------------------------------------------------------

class TestFallbackSemChave:
    def test_correct_sem_chave_retorna_original(self, monkeypatch):
        monkeypatch.setattr(state, "_CONFIG", {"OPENAI_API_KEY": None})
        result = _openai().correct_with_openai("original text")
        assert result == "original text"

    def test_simplify_sem_chave_retorna_original(self, monkeypatch):
        monkeypatch.setattr(state, "_CONFIG", {"OPENAI_API_KEY": None})
        result = _openai().simplify_with_openai("original text")
        assert result == "original text"

    def test_structure_sem_chave_retorna_original(self, monkeypatch):
        monkeypatch.setattr(state, "_CONFIG", {"OPENAI_API_KEY": None})
        result = _openai().structure_as_prompt_openai("original text")
        assert result == "original text"

    def test_query_sem_chave_retorna_prefixo(self, monkeypatch):
        monkeypatch.setattr(state, "_CONFIG", {"OPENAI_API_KEY": None})
        result = _openai().query_with_openai("pergunta")
        assert result.startswith("[SEM RESPOSTA]")
        assert "pergunta" in result

    def test_bullet_sem_chave_retorna_original(self, monkeypatch):
        monkeypatch.setattr(state, "_CONFIG", {"OPENAI_API_KEY": None})
        result = _openai().bullet_dump_with_openai("original")
        assert result == "original"

    def test_email_sem_chave_retorna_original(self, monkeypatch):
        monkeypatch.setattr(state, "_CONFIG", {"OPENAI_API_KEY": None})
        result = _openai().draft_email_with_openai("original")
        assert result == "original"

    def test_translate_sem_chave_retorna_original(self, monkeypatch):
        monkeypatch.setattr(state, "_CONFIG", {"OPENAI_API_KEY": None})
        result = _openai().translate_with_openai("original")
        assert result == "original"


# ---------------------------------------------------------------------------
# Rate limit response
# ---------------------------------------------------------------------------

class TestRateLimitResponse:
    def test_rate_limit_retorna_mensagem(self, monkeypatch):
        """When API raises 429, function returns the rate limit message (not raises)."""
        stub = MagicMock()
        stub.OpenAI.return_value.chat.completions.create.side_effect = Exception(
            "429 rate_limit exceeded"
        )
        monkeypatch.setitem(sys.modules, "openai", stub)

        result = _openai().correct_with_openai("qualquer texto")
        assert "[LIMITE ATINGIDO]" in result

    def test_rate_limit_query_retorna_mensagem(self, monkeypatch):
        """query_with_openai also returns rate limit message on 429."""
        stub = MagicMock()
        stub.OpenAI.return_value.chat.completions.create.side_effect = Exception(
            "Error 429"
        )
        monkeypatch.setitem(sys.modules, "openai", stub)

        result = _openai().query_with_openai("pergunta")
        assert "[LIMITE ATINGIDO]" in result


# ---------------------------------------------------------------------------
# Import error inside functions (openai not installed at call time)
# ---------------------------------------------------------------------------

class TestImportErrorFallback:
    def test_correct_com_import_error_retorna_mensagem(self, monkeypatch):
        """When openai raises ImportError at call time, returns error message."""
        monkeypatch.setattr(state, "_openai_client", None)
        monkeypatch.delitem(sys.modules, "openai", raising=False)

        def fake_import(name, *args, **kwargs):
            if name == "openai":
                raise ImportError("No module named 'openai'")
            raise ImportError(f"unexpected import: {name}")

        with patch("builtins.__import__", side_effect=fake_import):
            result = _openai().correct_with_openai("texto")
        assert "[ERRO]" in result
        assert "openai" in result.lower()
