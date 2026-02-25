"""
Tests for _get_gemini_client() singleton.
google.genai is already mocked in sys.modules by conftest.py.
"""

import pytest

import voice


@pytest.fixture(autouse=True)
def reset_gemini_singleton(monkeypatch):
    """Reset the singleton before and after each test to ensure isolation."""
    monkeypatch.setattr(voice.state, "_gemini_client", None)
    yield
    monkeypatch.setattr(voice.state, "_gemini_client", None)


def test_primeira_chamada_cria_cliente():
    """When _gemini_client is None, calling _get_gemini_client() creates an instance."""
    assert voice.state._gemini_client is None

    client = voice._get_gemini_client()

    assert client is not None
    assert voice.state._gemini_client is client


def test_chamadas_subsequentes_reutilizam():
    """Subsequent calls return the exact same instance (singleton pattern)."""
    client1 = voice._get_gemini_client()
    client2 = voice._get_gemini_client()

    assert client1 is client2


def test_reset_recria_cliente(monkeypatch):
    """After manually setting _gemini_client to None, a new instance is created."""
    # Get the initial client
    client1 = voice._get_gemini_client()
    assert client1 is not None

    # Reset the singleton
    monkeypatch.setattr(voice.state, "_gemini_client", None)

    # Next call should create a new instance
    client2 = voice._get_gemini_client()
    assert client2 is not None
    # They may be different objects (new creation), what matters is a new call was made
    # Since genai.Client is mocked, each call returns a new MagicMock instance
    assert voice.state._gemini_client is client2
