# voice/ai_provider.py — Facade: smart routing via OpenRouter (primary) or Gemini (fallback)
#
# Prioridade: OpenRouter (1 key, todos os modelos) > Gemini direto > OpenAI (legacy)
#
# Via OpenRouter, smart routing automático:
#   Modos rápidos (transcribe, email, bullet, translate) → Llama 4 Scout (402 t/s)
#   Modos complexos (simple, prompt, query) → Gemini 2.5 Flash

import time
from dataclasses import dataclass, field
from typing import Callable

from voice import state


# ── Utilitários de retry (migrados de ai_utils.py) ────────────────────────────

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
    """Opções acessórias para call_with_fallback."""
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
    """
    Executa fn() com retry + tratamento padronizado:
    - Rate limit exaurido após retries → loga options.rate_limit_log e retorna options.rate_limit_msg()
    - Outra exceção → loga options.error_log_prefix + erro e retorna fallback
    - fn() retorna falsy → retorna fallback
    - fn() retorna str → retorna resultado
    """
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


def process(mode: str, text: str) -> str:
    """Route text processing to the best available provider.

    Prioridade: OPENROUTER_API_KEY > GEMINI_API_KEY > OPENAI_API_KEY
    Aplica cooldown de _AI_COOLDOWN_SECONDS entre chamadas (SEC-05).
    """
    with state._state_lock:
        now = time.monotonic()
        elapsed = now - state._ai_last_call_time
        cooldown = state._AI_COOLDOWN_SECONDS
        if state._ai_last_call_time > 0 and elapsed < cooldown:
            remaining = cooldown - elapsed
            print(f"[SKIP] Cooldown ativo ({remaining:.1f}s restantes) — chamada AI ignorada")
            return text
        state._ai_last_call_time = time.monotonic()

    # Prioridade 1: OpenRouter (gateway unico, smart routing por modo)
    if state._CONFIG.get("OPENROUTER_API_KEY"):
        return _dispatch_openrouter(mode, text)

    # Prioridade 2: Gemini direto (legacy, para quem ja tem a key)
    if state._CONFIG.get("GEMINI_API_KEY"):
        return _dispatch_gemini(mode, text)

    # Prioridade 3: OpenAI (legacy)
    if state._CONFIG.get("OPENAI_API_KEY"):
        return _dispatch_openai(mode, text)

    print("[WARN] Nenhuma API key configurada (OPENROUTER_API_KEY, GEMINI_API_KEY ou OPENAI_API_KEY)")
    return text


def _dispatch_openrouter(mode: str, text: str) -> str:
    """Dispatch via OpenRouter — modelo selecionado automaticamente por modo."""
    from voice import openrouter

    if mode == "command":
        selected = getattr(state, "_command_selected_text", "")
        return openrouter.command(text, selected)

    if mode == "query":
        clipboard_ctx = state._clipboard_context if hasattr(state, "_clipboard_context") else ""
        if clipboard_ctx and state._CONFIG.get("CLIPBOARD_CONTEXT_ENABLED", True) is True:
            return openrouter.query_with_clipboard(text, clipboard_ctx)
        return openrouter.query(text)

    dispatch = {
        "transcribe": openrouter.correct,
        "simple":     openrouter.simplify,
        "prompt":     openrouter.structure,
        "bullet":     openrouter.bullet_dump,
        "email":      openrouter.draft_email,
        "translate":  openrouter.translate,
    }
    fn = dispatch.get(mode)
    if fn is None:
        return text
    return fn(text)


def _dispatch_gemini(mode: str, text: str) -> str:
    """Dispatch direto para Gemini API (fallback/legacy)."""
    from voice import gemini

    if mode == "command":
        selected = getattr(state, "_command_selected_text", "")
        return gemini.command_with_gemini(text, selected)

    if mode == "query":
        clipboard_ctx = state._clipboard_context if hasattr(state, "_clipboard_context") else ""
        if clipboard_ctx and state._CONFIG.get("CLIPBOARD_CONTEXT_ENABLED", True) is True:
            return gemini.query_with_clipboard_context(text, clipboard_ctx)
        return gemini.query_with_gemini(text)

    dispatch = {
        "transcribe": gemini.correct_with_gemini,
        "simple":     gemini.simplify_as_prompt,
        "prompt":     gemini.structure_as_prompt,
        "bullet":     gemini.bullet_dump_with_gemini,
        "email":      gemini.draft_email_with_gemini,
        "translate":  gemini.translate_with_gemini,
    }
    fn = dispatch.get(mode)
    if fn is None:
        return text
    return fn(text)


def _dispatch_openai(mode: str, text: str) -> str:
    """Dispatch para OpenAI direto (legacy)."""
    from voice import openai_
    if mode == "command":
        selected = getattr(state, "_command_selected_text", "")
        # OpenAI legacy: usar query_with_openai com prompt inline
        user_prompt = f"[SELECTED TEXT]\n{selected}\n\n[INSTRUCTION]\n{text}"
        try:
            result = openai_.query_with_openai(user_prompt)
            return result if result else selected
        except Exception:
            return selected

    dispatch = {
        "transcribe": openai_.correct_with_openai,
        "simple":     openai_.simplify_with_openai,
        "prompt":     openai_.structure_as_prompt_openai,
        "query":      openai_.query_with_openai,
        "bullet":     openai_.bullet_dump_with_openai,
        "email":      openai_.draft_email_with_openai,
        "translate":  openai_.translate_with_openai,
    }
    fn = dispatch.get(mode)
    if fn is None:
        return text
    return fn(text)


