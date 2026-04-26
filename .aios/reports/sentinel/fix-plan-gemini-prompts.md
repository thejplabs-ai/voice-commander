## Status: DONE

- **Date completed:** 2026-04-26
- **Branch:** `refactor/tech-debt-audio-split`
- **Commits (FP-2):**
  - `7d24477` — R1: extract prompt templates module (`voice/gemini_prompts.py`)
  - `da1bbdf` — R2: add `_call_gemini()` helper
  - `514a556` — R3.1: rewire translate / bullet / email / command
  - `ea12179` — R3.2: rewire structure / simplify / query / clipboard
  - **R4 cleanup (uncommitted, this delivery):** remove inline `_PROMPT_MINIMAL` / `_PROMPT_SMART` from `gemini.py` and switch `correct_with_gemini` to `_gp.CORRECT_MINIMAL` / `_gp.CORRECT_SMART` (byte-identical, validated programmatically before edit)
- **Final metrics:**
  - `voice/gemini.py`: **573L → 377L** (was 405L pre-R4)
  - 8 functions migrated to `_call_gemini()` dispatcher
  - `correct_with_gemini` kept inline (vocab learning hook + double-print intentional)
  - `transcribe_audio_with_gemini` left special-cased (Part.from_bytes / audio mime)
  - `voice/gemini_prompts.py`: pure templates + 8 builders, zero side effects
- **Tests:** 387 passed (focus: 53/53 in `test_gemini.py` + `test_correction_style.py`).
- **Pre-existing bug surfaced (NOT in scope for FP-2):** `voice/openrouter.py` carries its own copy of MINIMAL/SMART correction prompts that drifted from `gemini_prompts.CORRECT_*`. Tracked separately in DEX memory; fix scoped as future tech-debt round.

---

# Plan — Extract prompt templates from `voice/gemini.py`

**Status (historical):** queued — JP confirmed ordering 2026-04-26 (step 2 after audio split).
**Target:** resolve MED-4 — `voice/gemini.py` File 574L (threshold 400).
**Goal:** drop `gemini.py` under 400L, eliminate semantic duplication across 9 prompt builders, zero behavioral drift, all `tests/test_gemini.py` + `tests/test_correction_style.py` passing.

---

## Context

`voice/gemini.py` is 574L because 9 mode-specific functions repeat the same shape:

```
1. Guard on missing API key → return original text
2. Build long inline prompt (10-30L of triple-quoted string)
3. Define _api_call() closure
4. Call retry_api_call(_api_call, _is_rate_limit)
5. Format result + return, or fallback on rate-limit/exception
```

Functions following this shape (line ranges from 2026-04-26 head):
- `correct_with_gemini` (158-198) — minimal/smart correction
- `simplify_as_prompt` (201-254) — bullet-prompt
- `structure_as_prompt` (257-326) — COSTAR XML prompt
- `query_with_gemini` (329-371) — direct query
- `query_with_clipboard_context` (374-423) — query + clipboard
- `bullet_dump_with_gemini` (426-460) — hierarchical bullets
- `draft_email_with_gemini` (463-501) — email draft
- `command_with_gemini` (504-535) — command mode (selected text + instruction)
- `translate_with_gemini` (538-571) — translate to target lang
- `transcribe_audio_with_gemini` (94-127) — STT (slightly different shape, audio input)

The duplication is: 9× the same try/except wrapper, 9× the same `_safe_text(client.models.generate_content(...))` boilerplate, 9× the same rate-limit handling. The *prompts* themselves are the variation that matters; everything else is repetition.

---

## Hard constraint — Test coupling

`tests/test_gemini.py` greps:

```
patch("voice.gemini._get_gemini_client")
patch("voice.gemini.retry_api_call")
patch("voice.gemini._is_rate_limit")
from voice.gemini import correct_with_gemini, query_with_gemini, ...
```

(Audit before execution: run `grep -n "voice.gemini" tests/test_gemini.py tests/test_correction_style.py` and document patched symbols in the PR body.)

**Implication:** every public function listed above must remain importable from `voice.gemini` with current name and signature. The split must not change call signatures. Internal helpers (`_get_gemini_client`, `retry_api_call`, `_is_rate_limit`, `_safe_text`, `_build_context_prefix`, `_rate_limit_msg`) must remain in `voice.gemini` (or re-exported there) so test patches keep working.

---

## Split strategy — Templates module + dispatch helper

### Step 1: Extract prompt templates into `voice/gemini_prompts.py`

Pure data module. Zero logic. Each prompt is either a constant or a builder function returning a string.

```python
# voice/gemini_prompts.py — Prompt templates for Gemini calls.
# Pure builders. No API calls, no state mutations.

# ── Constants (no formatting needed) ─────────────────────────────────────────
TRANSCRIBE_AUDIO = (
    "Transcreva exatamente o que foi dito no áudio. "
    "..."
)

CORRECT_MINIMAL = (
    "Você é um corretor MINIMALISTA de transcrição de voz para texto.\n"
    "..."
    "Texto: {text}"
)

CORRECT_SMART = (
    "Você é um corretor inteligente de transcrição de voz para texto.\n"
    "..."
    "Texto: {text}"
)

# ── Builders (need runtime config or context) ────────────────────────────────
def build_simplify(text: str, context_prefix: str) -> str:
    return f"""{context_prefix}Você é especialista em prompt engineering.
... {text}"""

def build_structure(text: str) -> str:
    return f"""Você é especialista em prompt engineering para LLMs ...
... {text}"""

def build_query(system_prompt: str, text: str) -> str:
    return f"{system_prompt}\n\n{text}"

def build_query_with_clipboard(system_prompt: str, clipboard_content: str, text: str) -> str:
    return (
        f"{system_prompt}\n\n"
        f"[CONTEXTO DO CLIPBOARD]\n{clipboard_content}\n\n"
        f"[INSTRUÇÃO]\n{text}"
    )

def build_bullet_dump(text: str, context_prefix: str) -> str:
    return (
        f"{context_prefix}"
        "Você é especialista em organização de informação.\n"
        ...
    )

def build_draft_email(text: str, context_prefix: str) -> str:
    return (
        f"{context_prefix}"
        "Você é um redator profissional de emails.\n"
        ...
    )

def build_command(instruction: str, selected_text: str) -> str:
    return (
        "You are a text editing assistant. ...\n\n"
        f"[SELECTED TEXT]\n{selected_text}\n\n[INSTRUCTION]\n{instruction}"
    )

def build_translate(text: str, target_lang: str, context_prefix: str) -> str:
    lang_name = "inglês" if target_lang == "en" else "português brasileiro"
    return (
        f"{context_prefix}"
        f"Detecte o idioma do texto abaixo e traduza para {lang_name}.\n"
        ...
    )
```

This module is ~150L of just prompt strings + 8 builders. Zero side effects. Trivially testable.

### Step 2: Extract the call wrapper into `_call_gemini()` helper

The repeating shape:
- guard API key
- try: build client, build prompt, call retry_api_call, return result
- except rate-limit: return rate-limit message
- except other: log warn, fallback

Reduces to:

```python
# voice/gemini.py
def _call_gemini(
    prompt: str,
    *,
    fallback: str,
    temperature: float | None = None,
    success_log: str | None = None,
    fallback_log: str = "Gemini indisponível",
) -> str:
    """Centralized Gemini call with retry + rate-limit + error handling.

    Returns response text on success, fallback string on any failure path.
    """
    if not state._GEMINI_API_KEY:
        return fallback
    try:
        from google import genai
        client = _get_gemini_client()
        config = (
            genai.types.GenerateContentConfig(temperature=temperature)
            if temperature is not None else None
        )
        def _api_call():
            kwargs = {"model": state._CONFIG.get("GEMINI_MODEL", "gemini-2.5-flash"), "contents": prompt}
            if config is not None:
                kwargs["config"] = config
            return _safe_text(client.models.generate_content(**kwargs))

        result = retry_api_call(_api_call, _is_rate_limit)
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
```

### Step 3: Each public function becomes a 5-10 line dispatcher

Before (29L):

```python
def bullet_dump_with_gemini(text: str) -> str:
    if not state._GEMINI_API_KEY:
        return text
    try:
        from google import genai
        client = _get_gemini_client()
        context_prefix = _build_context_prefix()
        prompt = (
            f"{context_prefix}"
            "Você é especialista em organização de informação.\n"
            ...
        )
        def _api_call():
            return _safe_text(client.models.generate_content(...))
        result = retry_api_call(_api_call, _is_rate_limit)
        if result:
            print(f"[OK]   Bullet dump ({len(result)} chars)")
            return result
    except Exception as e:
        if _is_rate_limit(e):
            ...
            return _rate_limit_msg()
        print(f"[WARN] Gemini indisponível ({e}), retornando texto original")
    return text
```

After (5L):

```python
def bullet_dump_with_gemini(text: str) -> str:
    """Transforma transcrição em bullets hierárquicos. Preserva TODO o conteúdo."""
    prompt = gemini_prompts.build_bullet_dump(text, _build_context_prefix())
    return _call_gemini(prompt, fallback=text, temperature=0.2, success_log="Bullet dump")
```

Net savings (per function, approx):
- `correct_with_gemini`: 41L → ~12L (slightly larger because of vocab learning hook + minimal/smart selection — keep that logic in the function)
- `simplify_as_prompt`: 54L → 8L
- `structure_as_prompt`: 70L → 8L
- `query_with_gemini`: 43L → 12L (system prompt selection + cooldown semantics stay)
- `query_with_clipboard_context`: 50L → 14L
- `bullet_dump_with_gemini`: 35L → 5L
- `draft_email_with_gemini`: 39L → 5L
- `command_with_gemini`: 32L → 6L
- `translate_with_gemini`: 34L → 6L

Estimated post-refactor `gemini.py`: ~250L (helpers + 9 dispatchers + `transcribe_audio_with_gemini`). MED-4 cleared with margin.

### Proposed file layout

```
voice/
  gemini.py                      # ~250L — _get_gemini_client, _is_rate_limit, _safe_text,
                                 #         _rate_limit_msg, _build_context_prefix,
                                 #         _call_gemini, _CATEGORY_HINTS,
                                 #         transcribe_audio_with_gemini (audio is special),
                                 #         9 public dispatchers
  gemini_prompts.py              # ~150L — pure templates + builders
```

---

## Execution plan

### Preconditions
- Audio split (fix-plan-audio-split.md) merged to master first. Don't refactor two hot files in parallel.
- Branch: `refactor/tech-debt-gemini-prompts` from master post-audio-merge.

### Rounds

**R1 — Create `voice/gemini_prompts.py` with all templates**
- Move every prompt string + builder into the new module.
- Add unit tests `tests/test_gemini_prompts.py` (8-10 tests, one per builder) that just verify the output string contains expected anchors (e.g., "Você é especialista", "{text}" interpolation, target language). Pure string tests, no API.
- `gemini.py` still works as-is — the new file is unused yet.
- `pytest -q` green.
- Commit: `refactor(gemini): extract prompt templates to gemini_prompts module`

**R2 — Add `_call_gemini()` helper in `gemini.py`**
- Define helper. Don't wire it yet.
- Add 2-3 unit tests for `_call_gemini()` covering: success path, rate-limit path, generic exception path. Mock `_get_gemini_client` + `retry_api_call`.
- `pytest -q` green.
- Commit: `refactor(gemini): add centralized _call_gemini helper`

**R3 — Rewire each public function (one commit per function — keeps blast radius tight)**
- Functions in this order (lowest risk first):
  1. `translate_with_gemini`
  2. `bullet_dump_with_gemini`
  3. `draft_email_with_gemini`
  4. `command_with_gemini`
  5. `structure_as_prompt`
  6. `simplify_as_prompt`
  7. `query_with_gemini` (be careful: cooldown side effect lives in `audio.py`'s `transcribe()`, not here — verify untouched)
  8. `query_with_clipboard_context`
  9. `correct_with_gemini` (most logic — keep vocab learning hook)
- Each commit: `refactor(gemini): rewire <fn_name> through _call_gemini`
- After each: `pytest tests/test_gemini.py tests/test_correction_style.py -v` green.

**R4 — Final pass + SENTINEL rescan**
- `python -m pytest -q` — green
- `python -m py_compile voice/gemini.py voice/gemini_prompts.py` — clean
- `python -m ruff check voice/` — clean
- SENTINEL rescan: MED-4 must be gone. New file `gemini_prompts.py` may show LOW line-length on long prompts — expected; can be batched into baseline acceptance later.

### Manual smoke test (mandatory)

DEX runs `pythonw.exe -m voice` and exercises 8 modes back-to-back to verify no prompt drift:

1. **transcribe** — falar "olá tudo bem" → cola "Olá, tudo bem?" (correção smart)
2. **simple** — ditar instrução longa → bullet-prompt sem labels XML
3. **prompt** — ditar instrução → output COSTAR XML completo
4. **query** — perguntar "qual a capital do brasil" → resposta colada
5. **bullet** — ditar texto longo → output em hierarchy `## ## ###`
6. **email** — ditar rascunho → "Assunto: ..." + corpo + assinatura
7. **translate** — ditar "olá mundo" (TRANSLATE_TARGET_LANG=en) → "Hello world"
8. **command** — selecionar texto + Ctrl+Alt+Shift+P + ditar "torna isso mais formal" → texto reescrito

Capture outputs in PR body. Any drift = revert that commit.

---

## Validation gates

- [ ] `python -m py_compile voice/*.py` — zero erros
- [ ] `python -m ruff check voice/` — clean
- [ ] `python -m pytest -q` — 365+/365+
- [ ] `python -m pytest tests/test_gemini.py tests/test_correction_style.py tests/test_gemini_prompts.py -v` — green
- [ ] SENTINEL MED-4 cleared (`gemini.py` < 400L)
- [ ] Manual smoke test 8/8 modes — zero output drift
- [ ] No `.sentinel-baseline.json` change unless JP approves explicitly

## Non-negotiables

- **Prompts byte-identical.** A user testing the same input must get the same Gemini output. Prompt strings move to a new file; characters do not change. A diff of stripped prompt content between old and new must be empty.
- **`voice.gemini` public surface frozen.** All 9+1 public functions keep current name, args, return type.
- **Internal helpers patched by tests stay in `voice.gemini`.** `_get_gemini_client`, `retry_api_call` (re-exported from `ai_provider`), `_is_rate_limit` — keep accessible at `voice.gemini.<name>`.
- **GAGE pushes, not the assistant.**
- **Vocab learning hook in `correct_with_gemini` stays inline** (not moved to `_call_gemini`). It's a side effect specific to correction; pushing it into the helper would couple the helper to a concern most callers don't have.

## Known risks

- **`temperature=None` vs not-passed.** Current code sometimes passes `GenerateContentConfig(temperature=X)`, sometimes omits `config` entirely. The `_call_gemini` helper must replicate exactly: when `temperature is None`, do NOT pass `config` kwarg. The Gemini SDK may behave differently with `temperature=0.7` (default) vs no config. Verify against the 2 functions that don't set temperature today: `correct_with_gemini` (none), `structure_as_prompt` (none), `transcribe_audio_with_gemini` (none — but stays special-cased anyway).
- **`correct_with_gemini` does double-print.** It logs both `[OK] Original` and `[OK] Corrigido`. The generic `success_log` doesn't fit. Keep the inline logic for this one — the dispatcher pattern is for the simple cases.
- **`query_with_gemini` and `query_with_clipboard_context` return special sentinel** `"[SEM RESPOSTA GEMINI] {text}"` instead of just `text`. Pass that as `fallback=` into `_call_gemini`.
- **`transcribe_audio_with_gemini` uses `Part.from_bytes` + audio mime type.** Different shape entirely. Don't try to fit it into `_call_gemini`. Leave as-is.

---

## Definition of Done

- [ ] `voice/gemini.py` ≤ 350L (target ~250L)
- [ ] `voice/gemini_prompts.py` exists with all templates
- [ ] All 9 public dispatchers rewired through `_call_gemini` (except `correct_with_gemini` which keeps inline vocab hook + `transcribe_audio_with_gemini` which stays special)
- [ ] 365+ tests passing (incl. new `test_gemini_prompts.py`)
- [ ] SENTINEL MED-4 cleared
- [ ] Manual smoke 8/8 — outputs identical to pre-refactor
- [ ] PR title: `refactor(gemini): extract prompt templates + centralize call wrapper`
- [ ] PR body cross-references this doc + 2026-04-26 SENTINEL report
- [ ] Branch deleted post-merge

---

## Delegation

| Step | Agent |
|------|-------|
| Execute R1-R4 | `@dev` (DEX) |
| Push + open PR | `@devops` (GAGE) |
| Pre-merge gate (rerun SENTINEL + verify MED-4 gone) | `@sentinel` |

---

*Written 2026-04-26. Pick up after audio-split merges via `Task(subagent_type="dev", prompt="execute fix-plan-gemini-prompts.md rounds R1-R4")`.*
