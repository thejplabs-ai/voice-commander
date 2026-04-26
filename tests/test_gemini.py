"""
Tests for voice/gemini.py — Gemini client singleton and text processing helpers.

Strategy: google.genai is already mocked in sys.modules by conftest.py.
Per-test: patch state._GEMINI_API_KEY and state._gemini_client as needed.
"""

from unittest.mock import MagicMock, patch

import pytest

import voice
from voice import state, gemini


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_gemini_singleton(monkeypatch):
    """Reset the singleton before and after each test to ensure isolation."""
    monkeypatch.setattr(state, "_gemini_client", None)
    monkeypatch.setattr(state, "_GEMINI_API_KEY", "test-api-key")
    monkeypatch.setattr(state, "_CONFIG", {
        "GEMINI_MODEL": "gemini-2.5-flash",
        "GEMINI_CORRECT": True,
        "QUERY_SYSTEM_PROMPT": "",
        "TRANSLATE_TARGET_LANG": "en",
    })
    yield
    monkeypatch.setattr(state, "_gemini_client", None)


def _make_response(text: str) -> MagicMock:
    """Helper: create a mock Gemini response with .text attribute."""
    resp = MagicMock()
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# _get_gemini_client() — singleton pattern
# ---------------------------------------------------------------------------

def test_primeira_chamada_cria_cliente():
    """When _gemini_client is None, calling _get_gemini_client() creates an instance."""
    assert state._gemini_client is None

    client = voice._get_gemini_client()

    assert client is not None
    assert state._gemini_client is client


def test_chamadas_subsequentes_reutilizam():
    """Subsequent calls return the exact same instance (singleton pattern)."""
    client1 = voice._get_gemini_client()
    client2 = voice._get_gemini_client()

    assert client1 is client2


def test_reset_recria_cliente(monkeypatch):
    """After manually setting _gemini_client to None, a new instance is created."""
    client1 = voice._get_gemini_client()
    assert client1 is not None

    monkeypatch.setattr(state, "_gemini_client", None)

    client2 = voice._get_gemini_client()
    assert client2 is not None
    assert state._gemini_client is client2


# ---------------------------------------------------------------------------
# _is_rate_limit()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("msg,expected", [
    ("429 error", True),
    ("RESOURCE_EXHAUSTED", True),
    ("resource_exhausted quota exceeded", True),
    ("quota limit reached", True),
    ("Connection timeout", False),
    ("Internal server error 500", False),
    ("", False),
])
def test_rate_limit_detection(msg, expected):
    """_is_rate_limit() correctly identifies rate limit errors."""
    e = Exception(msg)
    assert gemini._is_rate_limit(e) == expected


# ---------------------------------------------------------------------------
# _call_gemini() — centralized call wrapper (FP-2 R2)
# ---------------------------------------------------------------------------

class TestCallGemini:
    """Tests for the centralized _call_gemini() helper.

    Helper is isolated from public dispatchers (R3 wires them up). These tests
    validate behavior contracts in isolation.
    """

    def test_success_returns_api_text_and_logs(self, monkeypatch, capsys):
        """Success path: returns API text; logs '[OK]   {success_log}' when provided."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _make_response("response text")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            result = gemini._call_gemini(
                "test prompt",
                fallback="FALLBACK",
                success_log="Test op",
            )

        assert result == "response text"
        captured = capsys.readouterr()
        assert "[OK]   Test op" in captured.out
        assert "(13 chars)" in captured.out  # len("response text") == 13

    def test_success_no_log_when_success_log_none(self, monkeypatch, capsys):
        """When success_log is None, no [OK] line is printed (preserves
        correct_with_gemini's double-print pattern)."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _make_response("ok")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            result = gemini._call_gemini("prompt", fallback="fb", success_log=None)

        assert result == "ok"
        captured = capsys.readouterr()
        assert "[OK]" not in captured.out

    def test_no_api_key_returns_fallback(self, monkeypatch):
        """When _GEMINI_API_KEY is falsy, returns fallback without calling client."""
        monkeypatch.setattr(state, "_GEMINI_API_KEY", None)
        mock_client = MagicMock()

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            result = gemini._call_gemini("prompt", fallback="MY_FALLBACK")

        assert result == "MY_FALLBACK"
        mock_client.models.generate_content.assert_not_called()

    def test_rate_limit_returns_rate_limit_msg_not_fallback(self, monkeypatch):
        """Rate-limit (429) returns _rate_limit_msg(), NOT the caller's fallback.

        Matches existing per-function behavior across gemini.py.
        """
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("429 RESOURCE_EXHAUSTED")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            result = gemini._call_gemini("prompt", fallback="ORIGINAL_TEXT")

        assert "[LIMITE ATINGIDO]" in result
        assert result != "ORIGINAL_TEXT"

    def test_generic_exception_returns_fallback_and_warns(self, monkeypatch, capsys):
        """Generic exception: returns fallback, prints '[WARN] {fallback_log} ({e})'."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("connection timeout")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            result = gemini._call_gemini(
                "prompt",
                fallback="FALLBACK_TEXT",
                fallback_log="Custom fallback msg",
            )

        assert result == "FALLBACK_TEXT"
        captured = capsys.readouterr()
        assert "[WARN] Custom fallback msg" in captured.out
        assert "connection timeout" in captured.out

    def test_temperature_none_omits_config_kwarg(self, monkeypatch):
        """When temperature=None, the SDK call must NOT receive a `config` kwarg.

        Critical: matches legacy correct_with_gemini / structure_as_prompt behavior
        where the SDK uses its internal default instead of an explicit
        GenerateContentConfig(temperature=None).
        """
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _make_response("out")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            gemini._call_gemini("prompt", fallback="fb", temperature=None)

        call_kwargs = mock_client.models.generate_content.call_args.kwargs
        assert "config" not in call_kwargs
        assert call_kwargs["contents"] == "prompt"
        assert call_kwargs["model"] == "gemini-2.5-flash"

    def test_temperature_value_passes_config_kwarg(self, monkeypatch):
        """When temperature is a float, the SDK call receives `config` with the value."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _make_response("out")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            gemini._call_gemini("prompt", fallback="fb", temperature=0.3)

        call_kwargs = mock_client.models.generate_content.call_args.kwargs
        assert "config" in call_kwargs


# ---------------------------------------------------------------------------
# correct_with_gemini()
# ---------------------------------------------------------------------------

class TestCorrectWithGemini:
    def test_retorna_texto_corrigido(self, monkeypatch):
        """correct_with_gemini() returns corrected text from API."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _make_response("Texto corrigido.")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        result = gemini.correct_with_gemini("texto original")

        assert result == "Texto corrigido."
        mock_client.models.generate_content.assert_called_once()

    def test_sem_api_key_retorna_texto_original(self, monkeypatch):
        """correct_with_gemini() returns original text when API key is absent."""
        monkeypatch.setattr(state, "_GEMINI_API_KEY", None)

        result = gemini.correct_with_gemini("texto original")

        assert result == "texto original"

    def test_gemini_correct_false_bypassa_api(self, monkeypatch):
        """correct_with_gemini() bypasses API when GEMINI_CORRECT=false."""
        monkeypatch.setattr(state, "_CONFIG", {
            **state._CONFIG,
            "GEMINI_CORRECT": False,
        })
        mock_client = MagicMock()
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        result = gemini.correct_with_gemini("texto original")

        assert result == "texto original"
        mock_client.models.generate_content.assert_not_called()

    def test_rate_limit_retorna_mensagem_erro(self, monkeypatch):
        """correct_with_gemini() returns rate limit message on 429."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("429 RESOURCE_EXHAUSTED")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        result = gemini.correct_with_gemini("texto")

        assert "[LIMITE ATINGIDO]" in result

    def test_erro_generico_retorna_texto_original(self, monkeypatch):
        """correct_with_gemini() returns original text on generic error."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("Connection timeout")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        result = gemini.correct_with_gemini("texto original")

        assert result == "texto original"

    def test_resposta_vazia_retorna_texto_original(self, monkeypatch):
        """correct_with_gemini() returns original text when API returns empty string."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _make_response("")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        result = gemini.correct_with_gemini("texto original")

        assert result == "texto original"

    def test_prompt_inclui_texto_original(self, monkeypatch):
        """correct_with_gemini() includes original text in the prompt sent to API."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _make_response("corrigido")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        gemini.correct_with_gemini("meu texto especial 12345")

        call_args = mock_client.models.generate_content.call_args
        contents = call_args[1].get("contents") or call_args[0][1]
        assert "meu texto especial 12345" in contents


# ---------------------------------------------------------------------------
# simplify_as_prompt()
# ---------------------------------------------------------------------------

class TestSimplifyAsPrompt:
    def test_sem_api_key_retorna_original(self, monkeypatch):
        """simplify_as_prompt() returns original text without API key."""
        monkeypatch.setattr(state, "_GEMINI_API_KEY", None)

        result = gemini.simplify_as_prompt("texto original")

        assert result == "texto original"

    def test_retorna_prompt_simplificado(self, monkeypatch):
        """simplify_as_prompt() returns simplified prompt from API."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _make_response("Prompt simplificado")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            result = gemini.simplify_as_prompt("texto de voz longo")

        assert result == "Prompt simplificado"

    def test_rate_limit_retorna_mensagem(self, monkeypatch):
        """simplify_as_prompt() returns rate limit message on 429."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("resource_exhausted")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            result = gemini.simplify_as_prompt("texto")

        assert "[LIMITE ATINGIDO]" in result

    def test_erro_generico_retorna_original(self, monkeypatch):
        """simplify_as_prompt() returns original text on error."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("timeout")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            result = gemini.simplify_as_prompt("texto original")

        assert result == "texto original"


# ---------------------------------------------------------------------------
# query_with_gemini()
# ---------------------------------------------------------------------------

class TestQueryWithGemini:
    def test_sem_api_key_retorna_prefixo(self, monkeypatch):
        """query_with_gemini() returns prefixed text without API key."""
        monkeypatch.setattr(state, "_GEMINI_API_KEY", None)

        result = gemini.query_with_gemini("minha pergunta")

        assert "[SEM RESPOSTA GEMINI]" in result
        assert "minha pergunta" in result

    def test_retorna_resposta_da_api(self, monkeypatch):
        """query_with_gemini() returns Gemini response to query."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _make_response("Resposta da query")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            result = gemini.query_with_gemini("qual é a capital do Brasil?")

        assert result == "Resposta da query"

    def test_usa_system_prompt_padrao_quando_vazio(self, monkeypatch):
        """query_with_gemini() uses default system prompt when QUERY_SYSTEM_PROMPT is empty."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _make_response("Resposta")
        monkeypatch.setattr(state, "_gemini_client", mock_client)
        monkeypatch.setattr(state, "_CONFIG", {
            **state._CONFIG,
            "QUERY_SYSTEM_PROMPT": "",
        })

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            gemini.query_with_gemini("pergunta")

        # Verify generate_content was called (default prompt used)
        mock_client.models.generate_content.assert_called_once()

    def test_usa_system_prompt_customizado(self, monkeypatch):
        """query_with_gemini() uses QUERY_SYSTEM_PROMPT from config."""
        custom_prompt = "Você é um expert em Python."
        monkeypatch.setattr(state, "_CONFIG", {
            **state._CONFIG,
            "QUERY_SYSTEM_PROMPT": custom_prompt,
        })
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _make_response("Resposta")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            gemini.query_with_gemini("pergunta")

        call_args = mock_client.models.generate_content.call_args
        contents = call_args[1].get("contents") or call_args[0][1]
        assert custom_prompt in contents

    def test_rate_limit_retorna_mensagem(self, monkeypatch):
        """query_with_gemini() returns rate limit message on 429."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("429 quota")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            result = gemini.query_with_gemini("pergunta")

        assert "[LIMITE ATINGIDO]" in result

    def test_erro_generico_retorna_prefixo(self, monkeypatch):
        """query_with_gemini() returns prefixed text on generic error."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("timeout")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            result = gemini.query_with_gemini("minha query")

        assert "[SEM RESPOSTA GEMINI]" in result


# ---------------------------------------------------------------------------
# bullet_dump_with_gemini()
# ---------------------------------------------------------------------------

class TestBulletDumpWithGemini:
    def test_sem_api_key_retorna_original(self, monkeypatch):
        """bullet_dump_with_gemini() returns original text without API key."""
        monkeypatch.setattr(state, "_GEMINI_API_KEY", None)

        result = gemini.bullet_dump_with_gemini("texto")

        assert result == "texto"

    def test_retorna_bullets(self, monkeypatch):
        """bullet_dump_with_gemini() returns bullet points from API."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _make_response("## T\n- A\n- B")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            result = gemini.bullet_dump_with_gemini("texto longo")

        assert "## T" in result or "- A" in result

    def test_erro_retorna_original(self, monkeypatch):
        """bullet_dump_with_gemini() returns original on error."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("error")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            result = gemini.bullet_dump_with_gemini("texto original")

        assert result == "texto original"


# ---------------------------------------------------------------------------
# draft_email_with_gemini()
# ---------------------------------------------------------------------------

class TestDraftEmailWithGemini:
    def test_sem_api_key_retorna_original(self, monkeypatch):
        """draft_email_with_gemini() returns original text without API key."""
        monkeypatch.setattr(state, "_GEMINI_API_KEY", None)

        result = gemini.draft_email_with_gemini("texto")

        assert result == "texto"

    def test_retorna_email_formatado(self, monkeypatch):
        """draft_email_with_gemini() returns formatted email from API."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _make_response(
            "Assunto: Reunião\n\nPrezados,\n\nCorpo do email."
        )
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            result = gemini.draft_email_with_gemini("agendar reunião semana que vem")

        assert "Assunto" in result or "email" in result.lower()


# ---------------------------------------------------------------------------
# translate_with_gemini()
# ---------------------------------------------------------------------------

class TestTranslateWithGemini:
    def test_sem_api_key_retorna_original(self, monkeypatch):
        """translate_with_gemini() returns original text without API key."""
        monkeypatch.setattr(state, "_GEMINI_API_KEY", None)

        result = gemini.translate_with_gemini("Olá")

        assert result == "Olá"

    def test_traduz_texto(self, monkeypatch):
        """translate_with_gemini() returns translated text from API."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _make_response("Hello!")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            result = gemini.translate_with_gemini("Olá!")

        assert result == "Hello!"

    def test_usa_translate_target_lang(self, monkeypatch):
        """translate_with_gemini() uses TRANSLATE_TARGET_LANG from config."""
        monkeypatch.setattr(state, "_CONFIG", {
            **state._CONFIG,
            "TRANSLATE_TARGET_LANG": "pt",
        })
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _make_response("Olá!")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            gemini.translate_with_gemini("Hello!")

        # Verify the prompt includes the target language
        call_args = mock_client.models.generate_content.call_args
        contents = call_args[1].get("contents") or call_args[0][1]
        assert "português brasileiro" in contents

    def test_erro_retorna_original(self, monkeypatch):
        """translate_with_gemini() returns original on error."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("error")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            result = gemini.translate_with_gemini("texto")

        assert result == "texto"


# ---------------------------------------------------------------------------
# structure_as_prompt()
# ---------------------------------------------------------------------------

class TestStructureAsPrompt:
    def test_sem_api_key_retorna_original(self, monkeypatch):
        """structure_as_prompt() returns original text without API key."""
        monkeypatch.setattr(state, "_GEMINI_API_KEY", None)

        result = gemini.structure_as_prompt("texto")

        assert result == "texto"

    def test_retorna_prompt_estruturado(self, monkeypatch):
        """structure_as_prompt() returns structured COSTAR prompt from API."""
        expected = "SYSTEM PROMPT\n<role>\nExpert\n</role>"
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _make_response(expected)
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            result = gemini.structure_as_prompt("faça um prompt para analisar código")

        assert result == expected

    def test_rate_limit_retorna_mensagem(self, monkeypatch):
        """structure_as_prompt() returns rate limit message on 429."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("resource_exhausted")
        monkeypatch.setattr(state, "_gemini_client", mock_client)

        with patch("voice.gemini._get_gemini_client", return_value=mock_client):
            result = gemini.structure_as_prompt("texto")

        assert "[LIMITE ATINGIDO]" in result
