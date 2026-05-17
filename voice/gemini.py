# voice/gemini.py — Gemini provider implementation + backward-compat shims.
#
# After provider-protocol consolidation, the per-mode functions below are thin
# shims through ai_provider._run(). The real work lives in:
#   - GeminiProvider.chat() — SDK call shape + context placement
#   - voice/ai_provider.py::_run — retry/rate-limit/fallback/logging
#   - voice/gemini_prompts.py::PROMPTS — per-mode prompt + behavior config
#
# Module-level names (_get_gemini_client, _is_rate_limit, _call_gemini,
# _build_context_prefix, correct_with_gemini, etc.) are preserved as shims so
# test_gemini.py, test_correction_style.py, test_window_context.py, and
# test_ai_provider.py (which mocks the module) keep passing without rewrites.

import threading

from voice import state, gemini_prompts as _gp
from voice.ai_provider import (
    retry_api_call,
    _build_context_prefix as _bcp,
    _run,
    Provider,
)


_gemini_lock = threading.Lock()


# ── Backward-compat re-export ───────────────────────────────────────────────
# voice/__init__.py:28 + voice/openrouter.py + test_window_context.py rely on
# these names living on this module.

def _build_context_prefix() -> str:
    """Re-export of ai_provider._build_context_prefix for backward compat."""
    return _bcp()


# ── Client singleton ────────────────────────────────────────────────────────

def _get_gemini_client():
    """Retorna o cliente Gemini, criando-o na primeira chamada (lazy init, thread-safe)."""
    with _gemini_lock:
        if state._gemini_client is None:
            from google import genai
            state._gemini_client = genai.Client(api_key=state._GEMINI_API_KEY)
    return state._gemini_client


def _is_rate_limit(e: Exception) -> bool:
    """Detecta erro 429 / RESOURCE_EXHAUSTED do Gemini (type-safe + string fallback)."""
    try:
        from google.api_core.exceptions import ResourceExhausted, TooManyRequests
        if isinstance(e, (ResourceExhausted, TooManyRequests)):
            return True
    except ImportError:
        pass
    msg = str(e).lower()
    return "429" in msg or "resource_exhausted" in msg or "exhausted" in msg or "quota" in msg


def _safe_text(response) -> str:
    """Extrai texto da resposta Gemini com null safety."""
    return (getattr(response, "text", None) or "").strip()


def _rate_limit_msg() -> str:
    return (
        "[LIMITE ATINGIDO] Gemini free tier: máx 15 req/min.\n"
        "Aguarde 1 minuto e use o atalho novamente."
    )


# ── Raw API call (used by both _call_gemini shim and GeminiProvider.chat) ──

def _api_call_gemini(prompt: str, *, temperature: float | None) -> str | None:
    """Single SDK call with retry. Returns text or empty string; raises on failure."""
    from google import genai
    client = _get_gemini_client()

    def _do():
        kwargs = {
            "model": state._CONFIG.get("GEMINI_MODEL", "gemini-2.5-flash"),
            "contents": prompt,
        }
        if temperature is not None:
            kwargs["config"] = genai.types.GenerateContentConfig(temperature=temperature)
        return _safe_text(client.models.generate_content(**kwargs))

    return retry_api_call(_do, _is_rate_limit)


def _call_gemini(
    prompt: str,
    *,
    fallback: str,
    temperature: float | None = None,
    success_log: str | None = None,
    fallback_log: str = "Gemini indisponível",
) -> str:
    """Backward-compat centralized call wrapper.

    Tests exercise this directly (test_gemini.py::TestCallGemini). The newer
    Provider Protocol path lives in GeminiProvider.chat() + ai_provider._run().
    Both paths share _api_call_gemini() under the hood.

    Args:
        prompt: Full prompt string already built by caller.
        fallback: Text to return on any failure (no API key, generic exception,
            empty response). Callers that need a sentinel (e.g. query_with_gemini's
            "[SEM RESPOSTA GEMINI] ...") pass it here.
        temperature: If None, the `config` kwarg is OMITTED from the SDK call
            (preserves legacy default behavior of correct_with_gemini /
            structure_as_prompt). If float, GenerateContentConfig(temperature=X)
            is passed.
        success_log: If provided, prints "[OK]   {success_log} ({len} chars)" on
            success. If None, no success log.
        fallback_log: Message used in the "[WARN] {fallback_log} ({e})" line on
            generic exception.
    """
    if not state._GEMINI_API_KEY:
        return fallback
    try:
        result = _api_call_gemini(prompt, temperature=temperature)
        if result:
            if success_log:
                print(f"[OK]   {success_log} ({len(result)} chars)")
            return result
    except Exception as e:
        if _is_rate_limit(e):
            print("[WARN] Gemini: rate limit 429 — aguardar 1 min")
            return _rate_limit_msg()
        print(f"[WARN] {fallback_log} ({e})")
    return fallback


# ── STT (audio in, not text in) — separate concern, kept verbatim ───────────

def transcribe_audio_with_gemini(wav_path: str) -> str:
    """
    Transcreve áudio diretamente via Gemini Flash (audio input).
    Substitui Whisper local — melhor PT-BR + code-switching EN.
    Requer google-genai >= 1.0 (usa Part.from_bytes, não dict inline_data legado).
    """
    from google import genai
    client = _get_gemini_client()

    with open(wav_path, "rb") as f:
        audio_bytes = f.read()

    audio_part = genai.types.Part.from_bytes(
        data=audio_bytes,
        mime_type="audio/wav",
    )

    prompt = _gp.TRANSCRIBE_AUDIO

    def _api_call():
        return _safe_text(client.models.generate_content(
            model=state._CONFIG.get("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=[audio_part, prompt],
        ))

    return retry_api_call(_api_call, _is_rate_limit)


# ── Provider Protocol implementation ────────────────────────────────────────

class GeminiProvider:
    """Provider Protocol implementation for Gemini.

    Single-prompt API: chat() concatenates ctx + system + user into one string.
    Context placement matches legacy build_X behavior (ctx BEFORE system).
    """
    name = "Gemini"

    def has_key(self) -> bool:
        return bool(state._GEMINI_API_KEY)

    def is_rate_limit(self, e: Exception) -> bool:
        return _is_rate_limit(e)

    def rate_limit_msg(self) -> str:
        return _rate_limit_msg()

    def reset(self) -> None:
        state._gemini_client = None

    def chat(
        self,
        *,
        system: str,
        user: str,
        ctx: str,
        temperature: float,
        speed_tier: str,  # noqa: ARG002 — only used by OpenRouterProvider
        gemini_uses_sdk_default: bool,
    ) -> str | None:
        prompt = f"{ctx}{system}\n\n{user}" if ctx else f"{system}\n\n{user}"
        effective_temp = None if gemini_uses_sdk_default else temperature
        return _api_call_gemini(prompt, temperature=effective_temp)


_PROVIDER: Provider = GeminiProvider()


# ── Module-level mode shims (preserved for tests + backward compat) ─────────

def correct_with_gemini(text: str) -> str:
    """Correção de transcrição de voz. Estilo controlado por CORRECTION_STYLE."""
    correction_style = state._CONFIG.get("CORRECTION_STYLE", "smart")
    if correction_style == "off":
        return text
    if state._CONFIG.get("GEMINI_CORRECT", True) is not True:
        return text
    return _run(_PROVIDER, _gp.PROMPTS["transcribe"], text, fallback=text, cfg=state._CONFIG)


def simplify_as_prompt(text: str) -> str:
    """Organiza a transcrição em prompt limpo com bullet points."""
    return _run(_PROVIDER, _gp.PROMPTS["simple"], text, fallback=text, cfg=state._CONFIG)


def structure_as_prompt(text: str) -> str:
    """COSTAR XML structured prompt (SYSTEM + USER)."""
    if not state._GEMINI_API_KEY:
        print("[WARN] Gemini sem chave — retornando texto original")
        return text
    return _run(_PROVIDER, _gp.PROMPTS["prompt"], text, fallback=text, cfg=state._CONFIG)


def query_with_gemini(text: str) -> str:
    """Envia a transcrição diretamente ao Gemini como pergunta/query."""
    sentinel = f"[SEM RESPOSTA GEMINI] {text}"
    if not state._GEMINI_API_KEY:
        print("[WARN] Gemini sem chave — retornando transcrição com prefixo")
        return sentinel
    return _run(_PROVIDER, _gp.PROMPTS["query"], text, fallback=sentinel, cfg=state._CONFIG)


def query_with_clipboard_context(text: str, clipboard_content: str) -> str:
    """Story 4.5.4: Query Gemini com contexto do clipboard."""
    if not clipboard_content.strip():
        print("[INFO] Clipboard vazio — modo query direto")
        return query_with_gemini(text)
    sentinel = f"[SEM RESPOSTA GEMINI] {text}"
    if not state._GEMINI_API_KEY:
        return sentinel
    return _run(
        _PROVIDER, _gp.PROMPTS["query_with_clipboard"], text,
        fallback=sentinel, cfg=state._CONFIG,
        extra_args={"clipboard": clipboard_content},
    )


def bullet_dump_with_gemini(text: str) -> str:
    """Transforma transcrição em bullets hierárquicos. Preserva TODO o conteúdo."""
    return _run(_PROVIDER, _gp.PROMPTS["bullet"], text, fallback=text, cfg=state._CONFIG)


def draft_email_with_gemini(text: str) -> str:
    """Transforma transcrição em email profissional com assunto + corpo + assinatura."""
    return _run(_PROVIDER, _gp.PROMPTS["email"], text, fallback=text, cfg=state._CONFIG)


def command_with_gemini(instruction: str, selected_text: str) -> str:
    """Epic 5.0: Aplica instrução de voz sobre texto selecionado via Gemini."""
    return _run(
        _PROVIDER, _gp.PROMPTS["command"], instruction,
        fallback=selected_text, cfg=state._CONFIG,
        extra_args={"selected_text": selected_text},
    )


def translate_with_gemini(text: str) -> str:
    """Detecta idioma e traduz para TRANSLATE_TARGET_LANG. Preserva formatação."""
    return _run(_PROVIDER, _gp.PROMPTS["translate"], text, fallback=text, cfg=state._CONFIG)
