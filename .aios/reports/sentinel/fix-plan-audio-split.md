# Plan — Split `voice/audio.py` (last HIGH cluster)

**Status:** queued — JP confirmed ordering 2026-04-26.
**Target:** zero out the 2 active SENTINEL HIGH findings on `voice/audio.py`:
- `voice/audio.py:1` — File 834L (threshold 800).
- `voice/audio.py:421` — `transcribe()` 103L (threshold 100).
**Goal:** SENTINEL HIGH 2 → 0, zero behavioral drift, all 365+ tests still green.

---

## Context

`voice/audio.py` was already partially split during the 2026-04-16 sprint — `whisper.py` (model loader, fallback chain) and `mic.py` (microphone validation) were extracted. What's left in `audio.py` is still a god-module with 6+ reasons to change:

1. Recording loop (`record`, `_start_recording`, `_stop_recording_snapshot`)
2. Transcription orchestration (`transcribe`, `_do_transcription`, fallback helpers, `_write_audio_to_wav`)
3. Toggle / hotkey lifecycle (`toggle_recording`, `on_hotkey`, `on_command_hotkey`, debounce locks)
4. Snippet matching (`_try_snippet_match`)
5. Post-process + paste (`_post_process_and_paste`, `_release_vram_if_cuda`, `_build_timing_and_log`)
6. Hands-free VAD loop (`hands_free_loop`)
7. Sound playback (`play_sound`, `_default_beep`)

This is SRP violated 6 ways. `transcribe()` itself orchestrates capture → STT → snippet → AI dispatch → history in 103 lines.

---

## Hard constraint — Test coupling

Tests under `tests/` patch `voice.audio.*` heavily:
- `test_audio.py:210,235,267,293,323,361,394+,420+,451,462` — patches `voice.audio.sd`, `voice.audio.threading.Thread`, `voice.audio.np`, `voice.audio.wave`, `voice.audio.tempfile`
- `test_command_mode.py:232,233,236,257,259` — patches `voice.audio.toggle_recording`, `voice.audio.play_sound`
- `test_extended_recording.py:133,142,193,247,265` — `from voice import audio`
- `test_snippets.py:320,354+,368,402+` — patches `voice.audio.tempfile.NamedTemporaryFile`, `voice.audio.wave.open`, `voice.audio.os.unlink`, `voice.audio.ai_provider.process`
- `test_vad_fix.py:99` — `import voice.audio as _audio_mod`
- `test_shutdown.py:58,89` — injects fake `voice.audio` into `sys.modules`

**Implication:** every public symbol that tests patch must remain importable from `voice.audio`. The split must keep `voice.audio` as the public facade — extract internals to sibling modules and re-export from `audio.py`. Same pattern already proven by the `whisper.py` extraction (`from voice.whisper import get_whisper_model, ...` re-bound at module-level for monkeypatching).

The re-export pattern is documented in lines 17-31 of current `audio.py` for `whisper.py` symbols. Keep that pattern.

---

## Split strategy — Extract by responsibility, keep `audio.py` as facade

### Proposed file layout

```
voice/
  audio.py                       # ~120L — facade only: imports + re-exports + module-level constants
  recording.py                   # ~180L — record(), _start_recording(), _stop_recording_snapshot()
                                 #         + SAMPLE_RATE, CHANNELS, sounddevice/winsound init
  transcription.py               # ~280L — transcribe(), _do_transcription(),
                                 #         _build_transcribe_kwargs(),
                                 #         _transcribe_no_vad_fallback(),
                                 #         _transcribe_cpu_fallback(),
                                 #         _transcribe_model_fallback(),
                                 #         _transcribe_without_vad_on_empty(),
                                 #         _write_audio_to_wav(),
                                 #         _try_snippet_match(),
                                 #         _post_process_and_paste(),
                                 #         _build_timing_and_log(),
                                 #         _release_vram_if_cuda(),
                                 #         _MODE_LOG_LABELS
  hotkey.py                      # ~120L — toggle_recording(), on_hotkey(), on_command_hotkey()
                                 #         + _last_hotkey_time, _hotkey_debounce_lock,
                                 #           _command_debounce_lock, _last_command_hotkey_time
  hands_free.py                  # ~100L — hands_free_loop()
  sound.py                       # ~30L  — play_sound(), _default_beep()
                                 # (already small but lives logically in its own concern)
```

Plus `audio.py` facade (re-exports for backward compat — tests + `app.py` are happy):

```python
# voice/audio.py — facade preserving backward compat for tests and app.py imports.
# Public API: record, transcribe, toggle_recording, on_hotkey, on_command_hotkey,
# hands_free_loop, play_sound, validate_microphone, get_whisper_model, _do_transcription.

# Re-exports (so monkeypatch.setattr("voice.audio.<name>", ...) keeps working).
from voice.sound import play_sound, _default_beep  # noqa: F401
from voice.recording import (  # noqa: F401
    record, _start_recording, _stop_recording_snapshot,
    SAMPLE_RATE, CHANNELS, sd, np, winsound,
)
from voice.transcription import (  # noqa: F401
    transcribe, _do_transcription,
    _build_transcribe_kwargs,
    _transcribe_no_vad_fallback,
    _transcribe_cpu_fallback,
    _transcribe_model_fallback,
    _transcribe_without_vad_on_empty,
    _write_audio_to_wav,
    _try_snippet_match,
    _post_process_and_paste,
    _build_timing_and_log,
    _release_vram_if_cuda,
    _MODE_LOG_LABELS,
    tempfile, wave, os,  # tests patch these via voice.audio.*
)
from voice.hotkey import (  # noqa: F401
    toggle_recording, on_hotkey, on_command_hotkey,
    threading,  # tests patch voice.audio.threading.Thread
)
from voice.hands_free import hands_free_loop  # noqa: F401
from voice.mic import validate_microphone  # noqa: F401
from voice.whisper import (  # noqa: F401
    get_whisper_model, _FAST_MODES, _QUALITY_MODES, _HOTWORDS,
    _DEFAULT_INITIAL_PROMPT, _register_cuda_dlls,
    _resolve_hf_model_path, _resolve_symlinks_in_dir,
)
from voice import ai_provider  # noqa: F401 — tests patch voice.audio.ai_provider.process
```

After split: `audio.py` is ~70-100L of imports/re-exports. HIGH-1 (file too large) gone. HIGH-2 (`transcribe` 103L) refactored as part of the move (see "Decompose `transcribe()`" below).

### Decompose `transcribe()` into 3 phases (HIGH-2)

Current `transcribe()` (103L) does:
- Setup + recording_ms snapshot (lines 421-450)
- Capture phase: write WAV → `_do_transcription()` → empty check (lines 451-471)
- Dispatch phase: snippet match → AI process → paste → overlay → cooldown → history (lines 473-492)
- Error path + finally cleanup (lines 494-520)

Proposed extract:

```python
def transcribe(frames: list, mode: str = "transcribe") -> None:
    """Top-level orchestrator. Coordinates capture → dispatch → cleanup."""
    t_start = time.time()
    t_mono_start = time.monotonic()
    recording_ms = _capture_recording_ms()

    temp_path = None
    try:
        if not _validate_frames(frames, mode):
            return
        _set_processing_state(mode)

        temp_path, audio_data = _prepare_wav(frames)
        raw_text, whisper_ms = _run_stt(temp_path, mode, audio_data)

        if not raw_text:
            _emit_empty_audio_error(mode, t_start)
            return

        _dispatch_transcribed_text(
            raw_text, mode, t_start, t_mono_start, recording_ms, whisper_ms
        )
    except Exception as e:
        _handle_transcribe_error(e, mode, t_start)
    finally:
        _cleanup_transcribe(temp_path)
```

The extracted helpers (`_capture_recording_ms`, `_validate_frames`, `_set_processing_state`, `_prepare_wav`, `_run_stt`, `_emit_empty_audio_error`, `_dispatch_transcribed_text`, `_handle_transcribe_error`, `_cleanup_transcribe`) are 5-15 lines each. `transcribe()` itself drops to ~30L. HIGH-2 cleared.

---

## Execution plan (DEX runs, mirrors PR #10 + ui_settings-split flow)

### Preconditions
- `master` is up to date.
- Branch: `refactor/tech-debt-audio-split` from master.
- This doc + `2026-04-26-full.md` available as context.

### Rounds (DEX executes; tests between each)

**R1 — Extract sound + hands_free (low risk, no test patches)**
- Create `voice/sound.py` with `play_sound` + `_default_beep`.
- Create `voice/hands_free.py` with `hands_free_loop`.
- `audio.py` re-exports both via `from voice.sound import ...` / `from voice.hands_free import ...`.
- `pytest -q` must stay green (374/374).
- Commit: `refactor(audio): extract sound + hands_free into dedicated modules`

**R2 — Extract recording**
- Create `voice/recording.py` with `record`, `_start_recording`, `_stop_recording_snapshot`, plus `SAMPLE_RATE`, `CHANNELS`, the `sounddevice/numpy/winsound` imports.
- `audio.py` re-exports `record`, `_start_recording`, `_stop_recording_snapshot`, `SAMPLE_RATE`, `CHANNELS`, `sd`, `np`, `winsound`.
- Run `pytest tests/test_audio.py tests/test_audio_recording.py tests/test_extended_recording.py -v` — all patches on `voice.audio.sd`, `voice.audio.np`, `voice.audio.threading.Thread` must still work because the re-exports preserve attribute lookups.
- Commit: `refactor(audio): extract record/start/stop into recording module`

**R3 — Extract transcription**
- Create `voice/transcription.py` with all transcribe helpers + `transcribe()` itself + `_MODE_LOG_LABELS` + `tempfile`, `wave`, `os` imports (the test-patched module attrs).
- Apply the `transcribe()` decomposition (HIGH-2 fix) inside the new module.
- `audio.py` re-exports everything tests reference.
- Run `pytest tests/test_audio.py tests/test_snippets.py tests/test_vad_fix.py -v`.
- Commit: `refactor(audio): extract transcription pipeline + decompose transcribe()`

**R4 — Extract hotkey**
- Create `voice/hotkey.py` with `toggle_recording`, `on_hotkey`, `on_command_hotkey`, debounce locks/state, plus `threading` import (test-patched as `voice.audio.threading.Thread`).
- `audio.py` re-exports.
- Run `pytest tests/test_audio.py tests/test_command_mode.py -v`.
- Commit: `refactor(audio): extract toggle + hotkey handlers`

**R5 — Final pass + SENTINEL rescan**
- Run full suite: `python -m pytest -q` — must be 374/374.
- `python -m py_compile voice/*.py` — zero errors.
- `python -m ruff check voice/` — clean.
- SENTINEL rescan:
  ```bash
  node "C:/Users/joaop/AIOS JP Labs/scripts/sentinel/report.js" --quick --json --target "C:/Users/joaop/voice-commander"
  ```
  Active HIGH must be 0. MEDIUM count expected to drop too (MED-1 `hands_free_loop` 91L is now in its own 100L file — likely under threshold; MED-6 `_do_transcription` and MED-8 helper-params clusters might need their own follow-up but are not blockers).
- If new SENTINEL findings appeared on the new files (likely some `whisper.py`-style line-length LOWs), do NOT auto-baseline; mention them in the PR body so JP can `*accept-baseline` deliberately.

### Manual smoke test (mandatory before PR)

DEX must execute these 7 steps with `pythonw.exe -m voice` (production-equivalent path). Capture output for the PR body.

1. App boots, tray icon appears, no crash.
2. `Ctrl+Shift+Space` → fala "teste de transcrição" → release → text pasted into active window.
3. `Ctrl+Shift+Tab` cycles modes (overlay shows new mode label).
4. Email mode end-to-end: ditar rascunho → recebe email formatado.
5. Query mode: pergunta → resposta colada.
6. Snippet test: ditar palavra mapeada em `voice/snippets.py` → snippet expandido (verifica `_try_snippet_match` ainda funciona após move).
7. Hands-free (se `HANDS_FREE_ENABLED=true`): falar → auto-start → silêncio → auto-stop.

---

## Validation gates (pare se qualquer um falhar)

- [ ] `python -m py_compile voice/*.py` — zero erros
- [ ] `python -m ruff check voice/` — clean
- [ ] `python -m pytest -q` — 365+/365+
- [ ] `python -m pytest tests/test_audio.py tests/test_command_mode.py tests/test_snippets.py tests/test_vad_fix.py -v` — green
- [ ] SENTINEL active HIGH = 0
- [ ] Manual smoke test 7/7 steps OK with `pythonw.exe`
- [ ] No new files committed under `dist/`, no `.env` changes, no `.sentinel-baseline.json` change unless JP approves explicitly

## Non-negotiables

- **Behavior frozen.** Zero UI/logic drift. Every `print()` line, every error path, every state mutation must remain identical.
- **`voice.audio` public surface is frozen.** Tests are the contract; if a test patch breaks, the split is wrong, not the test.
- **No renames.** `transcribe`, `record`, `toggle_recording`, `on_hotkey`, `play_sound` keep current names. Internal helpers can be renamed in their new home if it improves clarity, but the names exposed via `audio.py` re-exports must match current names exactly.
- **GAGE pushes, not the assistant.** PR #10 had a slip where the main assistant pushed a lint fix directly. Avoid that pattern.
- **Do not commit `.sentinel-baseline.json` updates** unless JP runs `*accept-baseline` explicitly. Same trap as PR #10 round 2.

## Known risks

- **Module attribute lookup vs. monkeypatch semantics.** When tests do `patch("voice.audio.sd")`, mock replaces the `sd` attribute on the `voice.audio` module object. If `recording.py` does `import sounddevice as sd` and `record()` references `sd.InputStream`, the patch on `voice.audio.sd` will NOT intercept. Solution: in `recording.py`, define `record()` with `sd.InputStream(...)` AND also expose `sd` as module attr. Then `audio.py` does `from voice.recording import sd` so `voice.audio.sd is voice.recording.sd`. The patch on `voice.audio.sd` rebinds the name on `voice.audio` only — but tests patch BEFORE calling `record()`, and `record()` lives in `voice.recording`, which still has the original `sd`. **This will break tests.**
  - **Fix option A (preferred):** keep `record()` definition in `voice/recording.py`, but inside `record()` do `from voice import audio as _audio` and reference `_audio.sd.InputStream` instead of `sd.InputStream`. Confirms test-patched `voice.audio.sd` is the one used.
  - **Fix option B (safer):** keep `record()` physically in `voice/audio.py` and only extract the helpers that tests don't patch. Pure size win is smaller, but zero risk.
  - **Decision before R2:** DEX must explicitly choose A or B and document in commit message. Default: B (safer). If B doesn't drop file under 800L, escalate to JP for option A.

- **Same trap for `voice.audio.np`, `voice.audio.wave`, `voice.audio.tempfile`, `voice.audio.os`, `voice.audio.threading`, `voice.audio.ai_provider`** — all patched in tests. Apply the same logic per-symbol. Audit `tests/` greps in this doc before each round.

- **Circular imports.** `recording.py` and `transcription.py` likely both need `state`, `tray._update_tray_state`, `clipboard.*`. Should be fine — these are already imported by the current `audio.py` without cycles. But: `transcription.py` calls `_post_process_and_paste()` which calls `ai_provider.process()`. If `ai_provider` imports from `voice.audio` for any reason, cycle. Audit before R3.

- **`_release_vram_if_cuda()` lazy `import torch`.** Already lazy + try/except — move as-is.

- **`hands_free_loop()` references `toggle_recording`.** After split, `hands_free.py` imports `toggle_recording` from `voice.hotkey`. Cycle risk: `hotkey.py` imports `record` from `voice.recording`, which is fine. `hands_free.py` does NOT need to be imported from `hotkey.py`, so no cycle. Confirm.

- **Hidden global state.** `_last_hotkey_time` and `_last_command_hotkey_time` are module-level globals in `audio.py`. After move to `hotkey.py`, ensure no test patches them by name on `voice.audio`. Greps shows none — safe.

---

## Definition of Done

- [ ] `voice/audio.py` ≤ 200L (target ~100L)
- [ ] `transcribe()` ≤ 50L
- [ ] All public symbols re-exported from `voice.audio` (test patches still work)
- [ ] 365+ tests passing
- [ ] SENTINEL active HIGH = 0
- [ ] Manual smoke test 7/7 with `pythonw.exe`
- [ ] PR title: `refactor(audio): split god-module into recording/transcription/hotkey/hands_free/sound`
- [ ] PR body cross-references this doc + 2026-04-26 SENTINEL report + commits HIGH 2 → 0
- [ ] PR merged to master
- [ ] Branch deleted
- [ ] `.sentinel-baseline.json` only updated if JP explicitly approves new baseline post-merge

---

## Delegation

| Step | Agent |
|------|-------|
| Execute R1-R5 | `@dev` (DEX) |
| Push + open PR | `@devops` (GAGE) |
| Pre-merge gate (rerun SENTINEL + verify counts) | `@sentinel` (this agent) |
| Optional architecture review on facade pattern | `@architect` |

DEX takes this doc as the spec. SENTINEL re-runs at end of R5 and posts updated counts in PR body before GAGE pushes for merge.

---

*Written 2026-04-26 after `*scan-full` flagged 2 HIGH on `voice/audio.py`. Pick up via `Task(subagent_type="dev", prompt="execute fix-plan-audio-split.md rounds R1-R5")`.*
