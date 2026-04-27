"""Smoke tests para voice/openrouter.py — chamadas REAIS à API OpenRouter.

Validação ESTRUTURAL (não semântica) dos prompts pós-FP-4 alignment.
Custo: ~$0.005 por teste, ~$0.04 a suíte completa.

Gated por env var RUN_OPENROUTER_SMOKE=1. Skipped por default.

Uso:
    RUN_OPENROUTER_SMOKE=1 python -m pytest tests/test_openrouter_smoke.py -v

Pré-requisitos:
    - OPENROUTER_API_KEY no .env (ou no environment)
    - Conexão de internet
"""
from __future__ import annotations

import os

import pytest

from voice import state


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_OPENROUTER_SMOKE") != "1",
    reason="Smoke real-API test (custa tokens). Set RUN_OPENROUTER_SMOKE=1.",
)


@pytest.fixture(scope="module", autouse=True)
def _bootstrap_state():
    """Carrega config mínima de .env antes dos smokes."""
    # conftest.py pode ter atribuído _BASE_DIR para tmp_path. Reset para o repo real.
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    state._BASE_DIR = repo_root

    env_path = os.path.join(repo_root, ".env")
    assert os.path.exists(env_path), f".env not found at {env_path}"

    from voice import config

    cfg = config.load_config()
    api_key = cfg.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        pytest.skip("OPENROUTER_API_KEY ausente no .env")

    # Mesclar config completa (preserva todas as outras keys já carregadas)
    state._CONFIG.clear()
    state._CONFIG.update(cfg)
    state._OPENROUTER_API_KEY = api_key

    # Workaround: OpenAI SDK em algumas versões ignora api_key= parameter
    # e só respeita env var. Setamos OPENAI_API_KEY (test apenas, em memória).
    os.environ["OPENAI_API_KEY"] = api_key

    from voice import openrouter
    openrouter.reset_client()

    assert state._CONFIG.get("OPENROUTER_API_KEY"), "key não persistiu em state._CONFIG após bootstrap"

    state._CONFIG.setdefault("CORRECTION_STYLE", "smart")
    state._CONFIG.setdefault("GEMINI_CORRECT", True)
    state._CONFIG.setdefault("TRANSLATE_TARGET_LANG", "en")
    state._CONFIG.setdefault("QUERY_SYSTEM_PROMPT", "")
    state._CONFIG.setdefault("OPENROUTER_MODEL_FAST", "meta-llama/llama-4-scout-17b-16e-instruct")
    state._CONFIG.setdefault("OPENROUTER_MODEL_QUALITY", "google/gemini-2.5-flash")
    yield


# ── R3 critical (the bug that started FP-4) ──────────────────────────────────


def test_structure_returns_costar_xml():
    """Modo prompt deve retornar COSTAR XML, não prosa corrigida.

    Esse é o bug que disparou FP-4: openrouter.structure() vinha retornando
    prosa porque o system prompt inline era curto demais para o modelo
    estruturar corretamente.
    """
    from voice import openrouter

    result = openrouter.structure(
        "quero auditar o pipeline de processamento de imagens, hoje está cheio de ifs"
    )
    assert "[LIMITE ATINGIDO]" not in result, "rate limit — repete depois"
    has_costar_marker = (
        "═══" in result
        or ("<role>" in result and "<context>" in result)
        or ("SYSTEM PROMPT" in result and "USER PROMPT" in result)
    )
    assert has_costar_marker, (
        "Modo prompt retornou prosa em vez de COSTAR XML. "
        f"Output (primeiros 300 chars): {result[:300]}"
    )


def test_simplify_returns_no_xml():
    """Modo simple NÃO deve retornar tags XML nem headers SYSTEM/USER."""
    from voice import openrouter

    result = openrouter.simplify(
        "preciso revisar o pipeline de imagens hoje está bagunçado vou organizar"
    )
    assert "[LIMITE ATINGIDO]" not in result
    assert "<role>" not in result, f"simplify contaminado com XML: {result[:200]}"
    assert "═══" not in result, f"simplify contaminado com COSTAR header: {result[:200]}"
    assert "SYSTEM PROMPT" not in result.upper()


def test_query_returns_ptbr_default():
    """Modo query default deve responder em PT-BR (após FP-4 R3)."""
    from voice import openrouter

    result = openrouter.query("qual a capital do Brasil")
    assert "[LIMITE ATINGIDO]" not in result
    assert "[SEM RESPOSTA]" not in result
    assert "Brasília" in result or "brasília" in result.lower(), (
        f"Esperado 'Brasília' na resposta. Output: {result[:200]}"
    )


def test_query_with_clipboard_uses_context():
    """query_with_clipboard deve incorporar contexto do clipboard."""
    from voice import openrouter

    clipboard = "O preço do produto X é R$ 250 com desconto de 10%."
    result = openrouter.query_with_clipboard(
        "qual o preço com desconto",
        clipboard,
    )
    assert "[LIMITE ATINGIDO]" not in result
    assert "[SEM RESPOSTA]" not in result
    # Esperado: 225 (250 - 10%). Aceita "225" ou "R$ 225" em qualquer formato
    has_answer = "225" in result or "R$ 225" in result
    assert has_answer, f"Não usou contexto do clipboard. Output: {result[:300]}"


# ── R2 lower-risk (já smoke-passed manualmente, mas barato validar) ──────────


def test_correct_smart_preserves_meaning():
    """Modo transcribe (correct smart) deve preservar texto e adicionar pontuação."""
    from voice import openrouter

    raw = "ola tudo bom hoje vou comer pizza"
    result = openrouter.correct(raw)
    assert "[LIMITE ATINGIDO]" not in result
    # Deve ter pontuação (vírgula ou ponto) e capitalização
    has_punctuation = "," in result or "." in result or "?" in result
    has_capital = result and result[0].isupper()
    assert has_punctuation, f"Não adicionou pontuação: {result}"
    assert has_capital, f"Não capitalizou: {result}"
    # Não pode ter mudado idioma — "pizza" deve continuar como "pizza"
    assert "pizza" in result.lower(), f"Mudou conteúdo: {result}"


def test_translate_to_english():
    """Modo translate (target=en) deve traduzir PT-BR para EN."""
    from voice import openrouter

    state._CONFIG["TRANSLATE_TARGET_LANG"] = "en"
    result = openrouter.translate("olá mundo, hoje está fazendo sol")
    assert "[LIMITE ATINGIDO]" not in result
    # Esperado: "Hello world" / "today" / "sunny"
    has_english_markers = any(
        word in result.lower() for word in ("hello", "world", "today", "sunny", "sun")
    )
    assert has_english_markers, f"Não parece traduzido para EN: {result[:200]}"


def test_bullet_dump_has_bullets():
    """Modo bullet deve retornar bullet points hierárquicos."""
    from voice import openrouter

    result = openrouter.bullet_dump(
        "preciso fazer várias coisas hoje primeiro arrumar a casa depois trabalhar "
        "no relatório e no fim do dia ir ao mercado comprar pão e leite"
    )
    assert "[LIMITE ATINGIDO]" not in result
    has_bullet_marker = "-" in result or "•" in result or "*" in result or "##" in result
    assert has_bullet_marker, f"Sem bullets: {result[:200]}"


def test_draft_email_has_subject_and_signature():
    """Modo email deve retornar com Assunto + corpo + assinatura."""
    from voice import openrouter

    result = openrouter.draft_email(
        "manda email pro joão dizendo que a reunião amanhã foi cancelada por causa de "
        "imprevisto pessoal vamos reagendar pra sexta"
    )
    assert "[LIMITE ATINGIDO]" not in result
    has_subject = "ssunto" in result.lower() or "subject" in result.lower()
    has_signature = "{Nome}" in result or "atenciosamente" in result.lower()
    assert has_subject, f"Sem 'Assunto:'. Output: {result[:300]}"
    assert has_signature, f"Sem assinatura. Output: {result[:300]}"
