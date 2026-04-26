# Plan — Empty-catch cleanup (Camada 2 findings)

**Status:** DONE — applied 2026-04-26 on branch `refactor/tech-debt-audio-split` (post FP-2 commit `92c3e94`). Awaiting JP commit.
**Target:** address 4 Camada 2 contextual findings on bare `except: pass` patterns.
**Goal:** improve observability without changing behavior. Replace silent swallow with `[WARN]` log so regressions in adjacent modules become visible. Zero functional change.

---

## Context

SENTINEL Camada 2 (LLM contextual review on 2026-04-26) flagged 4 empty-catch patterns. Two are **actionable**, two are **OK as-is** (intent documented, kept). This plan covers the 2 actionable + the 2 LOW patterns identified during the same review.

### Findings to act on

**C2-1 — `voice/whisper.py:30` (MEDIUM, confidence 70)**
Current:
```python
try:
    import nvidia.cublas
    import nvidia.cudnn
    for pkg in (nvidia.cublas, nvidia.cudnn):
        bin_dir = os.path.join(os.path.dirname(pkg.__path__[0]), pkg.__name__.split(".")[-1], "bin")
        if os.path.isdir(bin_dir):
            os.add_dll_directory(bin_dir)
except (ImportError, Exception):
    pass  # pacotes nvidia não instalados — CUDA via toolkit ou indisponível
```
**Issue:** `(ImportError, Exception)` is redundant — `Exception` subsumes `ImportError`. Hides legitimate bugs (e.g., `AttributeError` on `pkg.__path__[0]` if pkg is namespace-packaged differently in a future numpy/nvidia release).
**Fix:** narrow to expected types + log warn on non-import errors.

**C2-2 — `voice/whisper.py:115` (LOW, confidence 65)**
Current:
```python
except Exception as e:
    print(f"[WARN] Falha ao resolver symlink {entry}: {e}")
```
**Reclassified:** already logs `[WARN]`. **OK as-is** — no action needed. The C2 finding originally suggested propagation, but on second read the warning is sufficient: the caller flow can survive a missed symlink because `WhisperModel(...)` will then error with a clear "Unable to open model.bin" downstream and trigger fallback chain. **Drop from this plan.**

**C2-3 — `voice/audio.py:336` (`_try_snippet_match`)**
Reclassified by SENTINEL itself: docstring says "snippets nunca devem crashar a transcrição" — intent documented. **OK as-is, no action.**

**C2-4 — `voice/gemini.py:190-191` (LOW, confidence 70)**
Current pattern (repeats in `correct_with_gemini` and 6+ other places):
```python
try:
    from voice import vocabulary as _vocab
    candidates = _vocab.learn_from_correction(text, corrected)
    ...
except Exception:
    pass  # vocabulário nunca deve crashar a correção
```
**Issue:** intent is right (don't crash), but a regression in `vocabulary.py` (e.g., `learn_from_correction` raises `KeyError` after a refactor) is invisible. User sees no symptom; engineer never knows.
**Fix:** convert silent `pass` to `print(f"[WARN] Vocabulário falhou: {e}")` — preserves non-crash semantics, gains observability.

**C2-5 — `voice/audio.py:114-115` (LOW, confidence 60)**
Current:
```python
except Exception as e:
    print(f"[ERRO gravação] {e}")
```
**Reclassified:** already logs `[ERRO]`. The C2 concern was about caller getting feedback, but `transcribe()` already detects empty `frames` and shows generic error. Improving the user-facing message (audio device error vs. "Não entendi") is a UX improvement, not an observability fix — tracked separately, not in this plan. **OK as-is for this round.**

**Pattern C2 — `voice/gemini.py` repeated `vocabulary` swallow**
The same `try: ... except Exception: pass` for vocabulary appears in multiple Gemini functions. Audit reveals the swallow happens after vocab calls in `correct_with_gemini` (line 190). Other Gemini functions don't currently call vocabulary. This plan focuses on the one occurrence; if the gemini-prompts refactor (fix-plan-gemini-prompts.md) lands first, this hook stays in `correct_with_gemini` (per that plan's "vocab learning hook stays inline" non-negotiable).

---

## Net scope

Only 2 actual code changes:

1. **`voice/whisper.py:30`** — narrow exception tuple + add warn log on unexpected.
2. **`voice/gemini.py:190-191`** — replace `pass` with `print("[WARN] ...")`.

Plus: 1 similar pattern at **`voice/audio.py:135-137`** (in `_build_transcribe_kwargs`) — same vocab hook pattern, same fix:
```python
try:
    from voice import vocabulary as _vocab
    initial_prompt += _vocab.get_initial_prompt_suffix()
except Exception:
    pass  # vocabulário nunca deve crashar a transcrição
```
And `voice/audio.py:151-155` (same function, hotwords path):
```python
if _supports_hotwords:
    try:
        from voice import vocabulary as _vocab
        kwargs["hotwords"] = _vocab.get_hotwords_string()
    except Exception:
        kwargs["hotwords"] = _HW
```
Last one is intentional — falls back to default hotwords. **OK as-is**, no action (the fallback IS the observability — `_HW` is the visible default).

---

## Hard constraint — Test coupling

`tests/test_gemini.py` and `tests/test_correction_style.py` patch `voice.gemini` heavily but do not assert on log output (they assert on return values). Adding a `print("[WARN] ...")` line is invisible to these tests.

`tests/test_audio.py` doesn't patch `voice.vocabulary` — the vocab calls in `_build_transcribe_kwargs` typically run as-is in test fixtures. If they raise during test setup, current code silently swallows and continues. Adding a warn print might appear in stdout during tests; acceptable as long as no test asserts on stdout. Audit before commit: `grep -n "capsys\|capfd\|stdout" tests/test_audio.py tests/test_gemini.py` — if those asserts are absent, change is safe.

---

## Execution plan

### Preconditions
- Audio split + gemini refactor merged (this is step 3 — last in JP's ordering).
- Branch: `chore/empty-catch-cleanup` from master.
- This is a small surgical commit; do NOT bundle with anything else.

### Single-round execution

**R1 — Apply 2 changes**

Change 1 — `voice/whisper.py` line ~30:
```python
# BEFORE
    try:
        import nvidia.cublas
        import nvidia.cudnn
        for pkg in (nvidia.cublas, nvidia.cudnn):
            bin_dir = os.path.join(os.path.dirname(pkg.__path__[0]), pkg.__name__.split(".")[-1], "bin")
            if os.path.isdir(bin_dir):
                os.add_dll_directory(bin_dir)
    except (ImportError, Exception):
        pass  # pacotes nvidia não instalados — CUDA via toolkit ou indisponível

# AFTER
    try:
        import nvidia.cublas
        import nvidia.cudnn
        for pkg in (nvidia.cublas, nvidia.cudnn):
            bin_dir = os.path.join(os.path.dirname(pkg.__path__[0]), pkg.__name__.split(".")[-1], "bin")
            if os.path.isdir(bin_dir):
                os.add_dll_directory(bin_dir)
    except ImportError:
        pass  # nvidia.cublas/cudnn não instalados — CUDA via toolkit ou indisponível
    except (AttributeError, OSError) as e:
        print(f"[WARN] CUDA DLL discovery falhou ({type(e).__name__}: {e}) — continuando sem add_dll_directory")
```

Change 2 — `voice/gemini.py` line ~190:
```python
# BEFORE
            try:
                from voice import vocabulary as _vocab
                candidates = _vocab.learn_from_correction(text, corrected)
                if candidates:
                    for word in candidates:
                        _vocab.add_word(word)
                    print(f"[INFO] Vocabulário: +{len(candidates)} palavras ({', '.join(candidates)})")
            except Exception:
                pass  # vocabulário nunca deve crashar a correção

# AFTER
            try:
                from voice import vocabulary as _vocab
                candidates = _vocab.learn_from_correction(text, corrected)
                if candidates:
                    for word in candidates:
                        _vocab.add_word(word)
                    print(f"[INFO] Vocabulário: +{len(candidates)} palavras ({', '.join(candidates)})")
            except Exception as _vocab_e:
                # Vocabulário nunca deve crashar a correção, mas regressões devem ser visíveis.
                print(f"[WARN] Vocabulário falhou ({type(_vocab_e).__name__}: {_vocab_e})")
```

Change 3 — `voice/audio.py` line ~135 (in `_build_transcribe_kwargs`):
```python
# BEFORE
    try:
        from voice import vocabulary as _vocab
        initial_prompt += _vocab.get_initial_prompt_suffix()
    except Exception:
        pass  # vocabulário nunca deve crashar a transcrição

# AFTER
    try:
        from voice import vocabulary as _vocab
        initial_prompt += _vocab.get_initial_prompt_suffix()
    except Exception as _vocab_e:
        # Vocabulário nunca deve crashar a transcrição, mas regressões devem ser visíveis.
        print(f"[WARN] Vocabulário (initial_prompt) falhou ({type(_vocab_e).__name__}: {_vocab_e})")
```

(Note: if audio split merged first, this change applies to `voice/transcription.py` instead. DEX follows whichever file owns `_build_transcribe_kwargs` at execution time.)

### Validation

- [ ] `python -m py_compile voice/whisper.py voice/gemini.py voice/audio.py` — zero erros (or `voice/transcription.py` if audio split merged)
- [ ] `python -m ruff check voice/whisper.py voice/gemini.py voice/audio.py` — clean
- [ ] `python -m pytest -q` — green (no test should newly fail; warn prints don't break stdout-asserting tests if any exist — audit first)
- [ ] SENTINEL rescan: C2-1 + C2-4 + the audio.py vocab swallow no longer flagged

### Manual smoke (light)

`pythonw.exe -m voice`, exercise transcribe mode 2-3 times. Verify:
- No new errors in console.
- If `vocabulary.py` raises (force a regression by temporarily breaking `learn_from_correction`), `[WARN] Vocabulário falhou` appears — confirms observability works.
- Revert the deliberate break before commit.

(This second part is optional — the change is mechanical enough that a static review covers it. JP can decide whether to actually break vocabulary to test.)

---

## Validation gates

- [ ] `pytest -q` green
- [ ] No stdout-asserting test newly fails
- [ ] SENTINEL Camada 2 findings on whisper.py:30 + gemini.py:190 + audio.py:135 cleared next scan
- [ ] No `.sentinel-baseline.json` change

## Non-negotiables

- **Behavior frozen.** Adding `print("[WARN] ...")` does not change return values, control flow, or side effects.
- **Single small commit.** Don't bundle with refactors. Reverts cheaply if anything goes wrong.
- **GAGE pushes.**

## Known risks

- **`pythonw.exe` has no stdout.** The `print` calls land in `sys.stdout = None` and silently no-op when running production via `pythonw.exe`. CLAUDE.md gotcha already covers this. The warn is captured by the in-app log handler if one is wired in `voice/logging_.py`. Verify: `grep -n "print" voice/logging_.py` shows logging is captured to file, so warns appear in `voice-commander.log` even when pythonw silences stdout. **OK.**

- **Test stdout pollution.** If tests enable `capsys` or `capfd` and assert no stdout output, a new `[WARN] ...` could fail them. Mitigation: audit `tests/` for `capsys` / `capfd` / `caplog` usage before commit. If any test patches `voice.vocabulary.learn_from_correction` to raise, that test will newly emit a warn — test must be updated to expect it. Greps to run before commit:
  - `grep -rn "capsys\|capfd\|caplog" tests/`
  - `grep -rn "vocabulary.*side_effect\|vocabulary.*Mock\|vocabulary\.learn_from_correction" tests/`

---

## Definition of Done

- [x] 3 code changes applied (whisper.py + gemini.py + transcription.py — audio split moved `_build_transcribe_kwargs` to transcription.py)
- [x] Tests green — 387 passed, 0 failed (2 pre-existing numpy reload warnings, unrelated)
- [x] py_compile clean (full voice/)
- [x] ruff clean (full voice/)
- [ ] SENTINEL C2 findings cleared (next scan — pending)
- [ ] PR title: `chore(observability): replace silent swallow with [WARN] in vocabulary + CUDA DLL hooks`
- [ ] PR body lists the 3 files + the C2 finding IDs cleared
- [ ] Branch deleted post-merge

### Applied changes (2026-04-26)

1. `voice/whisper.py:30` — narrowed `(ImportError, Exception)` → `ImportError` for not-installed case + separate `(AttributeError, OSError)` clause logging `[WARN] CUDA DLL discovery falhou (...)`
2. `voice/gemini.py:222-224` — replaced `pass` with `print(f"[WARN] Vocabulário falhou ({type(e).__name__}: {e})")` in `correct_with_gemini` vocab learning hook
3. `voice/transcription.py:65-70` — replaced `pass` with `print(f"[WARN] Vocabulário (initial_prompt) falhou ({type(e).__name__}: {e})")` in `_build_transcribe_kwargs`

Plan-cited audio.py:135 path was relocated to transcription.py by FP-1 (audio split). C2-2 (whisper.py:115 symlink) and audio.py:151-155 (hotwords fallback) confirmed OK-as-is and left untouched.

---

## Delegation

| Step | Agent |
|------|-------|
| Apply changes | `@dev` (DEX) |
| Push + open PR | `@devops` (GAGE) |
| Pre-merge gate (rerun SENTINEL Camada 2, verify findings cleared) | `@sentinel` |

---

*Written 2026-04-26. Pick up after gemini-prompts merges via `Task(subagent_type="dev", prompt="execute fix-plan-empty-catch-cleanup.md")`.*
