# voice/openrouter.py — OpenRouter provider implementation + backward-compat shims.
#
# OpenRouter proxies all major providers (Gemini, Llama, Claude, GPT, etc.) via
# a single OpenAI-compatible API endpoint.
#
# Smart routing (driven by PromptSpec.speed_tier):
#   Fast modes (transcribe, email, bullet, translate) → Llama 4 Scout
#   Quality modes (simple, prompt, query, command)    → Gemini 2.5 Flash
#
# After provider-protocol consolidation, the per-mode functions below are thin
# shims through ai_provider._run(). _call() is preserved as the SDK-call
# boundary that test_correction_style.py patches.

import threading

from voice import state, gemini_prompts as _gp
from voice.ai_provider import retry_api_call, _run, Provider

_client_lock = threading.Lock()
_client = None

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_MODEL_FAST = "meta-llama/llama-4-scout-17b-16e-instruct"
_MODEL_QUALITY = "google/gemini-2.5-flash"

# Modos rápidos que usam o modelo fast (legacy compat — PromptSpec.speed_tier
# is the source of truth post-refactor).
FAST_MODES = {"transcribe", "email", "bullet", "translate"}


# ── Client singleton ────────────────────────────────────────────────────────

def _get_client():
    """Retorna o cliente OpenRouter (OpenAI-compatible), criando na primeira chamada."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                try:
                    from openai import OpenAI
                except ImportError as exc:
                    raise ImportError("openai-not-installed") from exc
                api_key = state._CONFIG.get("OPENROUTER_API_KEY")
                _client = OpenAI(
                    api_key=api_key,
                    base_url=_OPENROUTER_BASE_URL,
                )
    return _client


def reset_client() -> None:
    """Reset singleton quando a key muda. Called by config._reload_config()."""
    global _client
    with _client_lock:
        _client = None


def _model_for_speed_tier(tier: str) -> str:
    if tier == "fast":
        return state._CONFIG.get("OPENROUTER_MODEL_FAST", _MODEL_FAST)
    return state._CONFIG.get("OPENROUTER_MODEL_QUALITY", _MODEL_QUALITY)


def _model_for_mode(mode: str) -> str:
    """Legacy: select model by mode name. Use _model_for_speed_tier() in new code."""
    return _model_for_speed_tier("fast" if mode in FAST_MODES else "quality")


def _is_rate_limit(e: Exception) -> bool:
    """Detecta rate limit (type-safe + string fallback)."""
    try:
        import openai
        if hasattr(openai, "RateLimitError") and isinstance(e, openai.RateLimitError):
            return True
    except (ImportError, TypeError):
        pass
    msg = str(e).lower()
    return "429" in msg or "rate_limit" in msg or "ratelimit" in msg


def _rate_limit_msg() -> str:
    return (
        "[LIMITE ATINGIDO] Rate limit atingido.\n"
        "Aguarde alguns instantes e use o atalho novamente."
    )


def _call(system: str, user: str, model: str, temperature: float = 0.2) -> str | None:
    """SDK-call boundary with retry. test_correction_style.py patches this name."""
    client = _get_client()

    def _api_call():
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
        )
        choices = response.choices or []
        if not choices or not choices[0].message.content:
            return None
        return choices[0].message.content.strip()

    return retry_api_call(_api_call, _is_rate_limit)


# ── Backward-compat context-prefix helper ───────────────────────────────────
# Pre-refactor, openrouter mode functions used _ctx_prefix() to lazy-import
# voice.gemini._build_context_prefix and avoid circular imports. After the move
# to voice.ai_provider, this shim is kept for any external caller (unlikely).

def _ctx_prefix() -> str:
    from voice.ai_provider import _build_context_prefix
    return _build_context_prefix()


# ── Provider Protocol implementation ────────────────────────────────────────

class OpenRouterProvider:
    """Provider Protocol implementation for OpenRouter.

    Chat-completions API: system + user are separate messages. Context
    placement: ctx is prepended to USER (matches legacy openrouter.py behavior;
    see test_window_context.py for the equivalence with Gemini's ctx-in-system
    placement).
    """
    name = "OpenRouter"

    def has_key(self) -> bool:
        return bool(state._CONFIG.get("OPENROUTER_API_KEY"))

    def is_rate_limit(self, e: Exception) -> bool:
        return _is_rate_limit(e)

    def rate_limit_msg(self) -> str:
        return _rate_limit_msg()

    def reset(self) -> None:
        reset_client()

    def chat(
        self,
        *,
        system: str,
        user: str,
        ctx: str,
        temperature: float,
        speed_tier: str,
        gemini_uses_sdk_default: bool,  # noqa: ARG002 — only used by GeminiProvider
    ) -> str | None:
        user_with_ctx = (ctx + user) if ctx else user
        model = _model_for_speed_tier(speed_tier)
        return _call(system, user_with_ctx, model, temperature)


_PROVIDER: Provider = OpenRouterProvider()


# ── Module-level mode shims (preserved for tests + ai_provider mocking) ─────

def correct(text: str) -> str:
    """Correção de transcrição de voz. Estilo controlado por CORRECTION_STYLE."""
    correction_style = state._CONFIG.get("CORRECTION_STYLE", "smart")
    if correction_style == "off":
        return text
    if state._CONFIG.get("GEMINI_CORRECT", True) is not True:
        return text
    return _run(_PROVIDER, _gp.PROMPTS["transcribe"], text, fallback=text, cfg=state._CONFIG)


def simplify(text: str) -> str:
    """Organiza transcrição em prompt limpo com bullet points."""
    return _run(_PROVIDER, _gp.PROMPTS["simple"], text, fallback=text, cfg=state._CONFIG)


def structure(text: str) -> str:
    """Estrutura transcrição em prompt COSTAR com XML tags."""
    return _run(_PROVIDER, _gp.PROMPTS["prompt"], text, fallback=text, cfg=state._CONFIG)


def query(text: str) -> str:
    """Envia pergunta e retorna resposta."""
    sentinel = f"[SEM RESPOSTA] {text}"
    return _run(_PROVIDER, _gp.PROMPTS["query"], text, fallback=sentinel, cfg=state._CONFIG)


def query_with_clipboard(text: str, clipboard_content: str) -> str:
    """Query com contexto do clipboard."""
    if not clipboard_content.strip():
        return query(text)
    sentinel = f"[SEM RESPOSTA] {text}"
    return _run(
        _PROVIDER, _gp.PROMPTS["query_with_clipboard"], text,
        fallback=sentinel, cfg=state._CONFIG,
        extra_args={"clipboard": clipboard_content},
    )


def bullet_dump(text: str) -> str:
    """Transforma transcrição em bullets hierárquicos."""
    return _run(_PROVIDER, _gp.PROMPTS["bullet"], text, fallback=text, cfg=state._CONFIG)


def draft_email(text: str) -> str:
    """Transforma transcrição em email profissional."""
    return _run(_PROVIDER, _gp.PROMPTS["email"], text, fallback=text, cfg=state._CONFIG)


def command(instruction: str, selected_text: str) -> str:
    """Epic 5.0: Aplica instrução de voz sobre texto selecionado."""
    return _run(
        _PROVIDER, _gp.PROMPTS["command"], instruction,
        fallback=selected_text, cfg=state._CONFIG,
        extra_args={"selected_text": selected_text},
    )


def translate(text: str) -> str:
    """Detecta idioma e traduz."""
    return _run(_PROVIDER, _gp.PROMPTS["translate"], text, fallback=text, cfg=state._CONFIG)
