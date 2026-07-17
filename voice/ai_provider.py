# voice/ai_provider.py — Provider Protocol + shared dispatch.
#
# Providers (OpenRouter, Gemini) implement the Provider Protocol and live in
# their own modules (voice/openrouter.py, voice/gemini.py). This file owns:
#   - The Protocol contract
#   - The shared _run() that orchestrates retry/rate-limit/fallback/logging
#   - _build_context_prefix() — Window Context hint used by both providers
#   - process(mode, text) — the single entry point called by transcription.py
#
# Priority: OPENROUTER_API_KEY > GEMINI_API_KEY. OpenAI was dropped — OpenRouter
# proxies GPT models behind the same gateway.

import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from voice import state
from voice.gemini_prompts import PROMPTS, PromptSpec, sanitize_llm_output


# ── Retry utilities (consumed by both providers' _call paths) ────────────────

def _is_transient(e: Exception) -> bool:
    """Detecta erros transientes que justificam retry (timeout, server error)."""
    msg = str(e).lower()
    return any(term in msg for term in (
        "timeout", "timed out", "connection", "unavailable",
        "500", "502", "503", "504", "internal", "server error",
        "overloaded",
    ))


def retry_api_call(
    fn: Callable[[], str | None],
    is_rate_limit: Callable[[Exception], bool],
    max_retries: int = 2,
    base_delay: float = 1.0,
) -> str | None:
    """
    Executa fn() com retry para erros transientes e rate limit.

    - Erros transientes (timeout, 500-504): retry com backoff exponencial
    - Rate limit (429): retry com delay maior (5s, 10s)
    - Outros erros (400, 401, 403): raise imediato, sem retry
    - Retorna resultado de fn() ou levanta a exceção se todos os retries falharem
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt >= max_retries:
                raise
            if is_rate_limit(e):
                delay = 5.0 * (2 ** attempt)  # 5s, 10s
                print(f"[WARN] Rate limit — retry {attempt + 1}/{max_retries} em {delay:.0f}s")
                time.sleep(delay)
            elif _is_transient(e):
                delay = base_delay * (2 ** attempt)  # 1s, 2s
                print(f"[WARN] Erro transiente — retry {attempt + 1}/{max_retries} em {delay:.1f}s")
                time.sleep(delay)
            else:
                raise  # erro não-transiente: sem retry
    raise last_exc  # pragma: no cover


@dataclass
class CallOptions:
    """Legacy options struct preserved for any external caller. Not used by _run()."""
    rate_limit_msg: Callable[[], str]
    rate_limit_log: str
    error_log_prefix: str
    max_retries: int = field(default=2)


def call_with_fallback(
    fn: Callable[[], str | None],
    fallback: str,
    is_rate_limit: Callable[[Exception], bool],
    options: CallOptions,
) -> str:
    """Legacy helper preserved for backward compatibility."""
    try:
        result = retry_api_call(fn, is_rate_limit, max_retries=options.max_retries)
        if result:
            return result
    except Exception as e:
        if is_rate_limit(e):
            print(options.rate_limit_log)
            return options.rate_limit_msg()
        print(f"{options.error_log_prefix} ({e})")
    return fallback


# ── Window Context — Epic 5.5 ────────────────────────────────────────────────
#
# Was in voice/gemini.py:39-58. Moved here so both providers consume it without
# the lazy-import workaround that voice/openrouter.py:103-113 used. A shim in
# voice/gemini.py preserves the name for test_window_context.py + external use.

_CATEGORY_HINTS: dict[str, str] = {
    "email": "O usuário está escrevendo em um cliente de email. Use tom profissional.",
    "code_editor": (
        "O usuário está em um editor de código. "
        "Preserve termos técnicos e formatação de código."
    ),
    "chat": "O usuário está em um chat. Use tom casual e direto.",
    "document": "O usuário está editando um documento. Use linguagem clara e formal.",
    "spreadsheet": "O usuário está em uma planilha. Seja preciso e objetivo.",
    "presentation": "O usuário está em uma apresentação. Prefira linguagem clara e visual.",
    "text_editor": "O usuário está em um editor de texto simples. Seja direto.",
    "terminal": (
        "O usuário está em um terminal. "
        "Preserve comandos e sintaxe exatamente como estão."
    ),
}


def _build_context_prefix() -> str:
    """Epic 5.5: Window Context hint, empty when feature disabled or no relevant context."""
    if not state._CONFIG.get("WINDOW_CONTEXT_ENABLED", False):
        return ""
    ctx = getattr(state, "_window_context", {})
    if not ctx:
        return ""
    category = ctx.get("category", "other")
    hint = _CATEGORY_HINTS.get(category, "")
    if not hint:
        return ""
    return hint + "\n\n"


# ── Provider Protocol ────────────────────────────────────────────────────────

class Provider(Protocol):
    """Each provider (OpenRouter, Gemini) implements this Protocol.

    chat() receives system + user separately and resolves any provider-specific
    concerns (model selection, ctx placement, SDK shape). It returns the raw
    response text on success, raises on API errors, and returns None when the
    API returned an empty payload. _run() interprets the result.
    """
    name: str

    def chat(
        self,
        *,
        system: str,
        user: str,
        ctx: str,
        temperature: float,
        speed_tier: str,
        gemini_uses_sdk_default: bool,
    ) -> str | None: ...

    def is_rate_limit(self, e: Exception) -> bool: ...

    def rate_limit_msg(self) -> str: ...

    def has_key(self) -> bool: ...


# ── Shared orchestrator ──────────────────────────────────────────────────────

def _run(
    provider: Provider,
    spec: PromptSpec,
    text: str,
    *,
    fallback: str,
    cfg: dict,
    extra_args: dict | None = None,
) -> str:
    """Execute spec via provider with shared retry/rate-limit/fallback/logging.

    Replaces the per-mode try/except boilerplate that previously lived in
    every mode function across gemini.py, openrouter.py, and openai_.py.
    """
    if not provider.has_key():
        return fallback

    system = spec.system_resolver(cfg)
    user = spec.user_builder(text, **(extra_args or {}))
    ctx = _build_context_prefix()

    try:
        result = provider.chat(
            system=system,
            user=user,
            ctx=ctx,
            temperature=spec.temperature,
            speed_tier=spec.speed_tier,
            gemini_uses_sdk_default=spec.gemini_uses_sdk_default,
        )
        if result:
            result = sanitize_llm_output(result)
            if spec.output_guard is not None and not spec.output_guard(text, result):
                print(
                    f"[WARN] correção desproporcional descartada "
                    f"(in={len(text)} chars, out={len(result)} chars), usando texto cru"
                )
                return text
            if spec.success_log is not None:
                print(f"[OK]   {spec.success_log(cfg)} ({len(result)} chars)")
            if spec.success_hook is not None:
                spec.success_hook(cfg, text, result)
            return result
    except Exception as e:
        if provider.is_rate_limit(e):
            return provider.rate_limit_msg()
        print(f"[WARN] {provider.name} indisponível ({e})")
    return fallback


# ── Provider selection + mode resolution ────────────────────────────────────

def _select_provider() -> Provider | None:
    """OPENROUTER_API_KEY > GEMINI_API_KEY."""
    if state._CONFIG.get("OPENROUTER_API_KEY"):
        from voice import openrouter
        return openrouter._PROVIDER
    if state._CONFIG.get("GEMINI_API_KEY"):
        from voice import gemini
        return gemini._PROVIDER
    return None


def _resolve_call(mode: str, text: str) -> tuple[PromptSpec | None, dict, str]:
    """Resolve effective spec + extra_args + fallback for a given (mode, text).

    Returns (spec, extra_args, fallback). spec=None signals "unknown mode —
    return text unchanged".
    """
    cfg = state._CONFIG

    if mode == "query":
        clipboard = getattr(state, "_clipboard_context", "")
        if clipboard and cfg.get("CLIPBOARD_CONTEXT_ENABLED", True) is True:
            spec = PROMPTS["query_with_clipboard"]
            return spec, {"clipboard": clipboard}, _resolve_fallback(spec, text)
        spec = PROMPTS["query"]
        return spec, {}, _resolve_fallback(spec, text)

    if mode == "command":
        selected = getattr(state, "_command_selected_text", "")
        spec = PROMPTS["command"]
        return spec, {"selected_text": selected}, _resolve_fallback(spec, text)

    spec = PROMPTS.get(mode)
    if spec is None:
        return None, {}, text
    return spec, {}, _resolve_fallback(spec, text)


def _resolve_fallback(spec: PromptSpec, text: str) -> str:
    kind = spec.fallback_kind
    if kind == "text":
        return text
    if kind == "selected":
        return getattr(state, "_command_selected_text", "")
    if kind == "sentinel":
        return f"[SEM RESPOSTA] {text}"
    return text


# ── Public entry point ──────────────────────────────────────────────────────

def process(mode: str, text: str) -> str:
    """Route text processing to the best available provider.

    Prioridade: OPENROUTER_API_KEY > GEMINI_API_KEY
    """
    provider = _select_provider()
    if provider is None:
        print("[WARN] Nenhuma API key configurada (OPENROUTER_API_KEY ou GEMINI_API_KEY)")
        return text

    spec, extra_args, fallback = _resolve_call(mode, text)
    if spec is None:
        return text

    return _run(provider, spec, text, fallback=fallback, cfg=state._CONFIG, extra_args=extra_args)
