"""
Regression tests for bug: empty transcription (error beep, no paste).

Root cause: vad_filter=True with default threshold=0.5 was discarding all
audio as silence when microphone volume was low.

Fix: configurable VAD_THRESHOLD (default 0.3).

Task 3 (W1 reliability sprint): the sem-VAD fallback (retranscribing without
VAD when duration_after_vad==0, with a Whisper-hallucination blocklist) was
removed entirely — it kept pasting artifacts like "Amara.org" / "Thank you
for watching" on genuinely silent recordings. VAD-gate is now strict: no
speech detected -> SKIP (beep + overlay "Não detectei fala" + history
error=True), never a paste.

Related history.jsonl entry: {"duration_seconds": 20.82, "raw_text": "", "error": true}
"""

from unittest.mock import MagicMock
import pytest
import voice
from voice import state, audio


# ---------------------------------------------------------------------------
# Config: VAD_THRESHOLD loading
# ---------------------------------------------------------------------------

def _write_env(tmp_path, content: str) -> None:
    (tmp_path / ".env").write_text(content, encoding="utf-8")


def test_vad_threshold_default(tmp_path, monkeypatch):
    """VAD_THRESHOLD defaults to 0.3 when not set in .env."""
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
    cfg = voice.load_config()
    assert cfg["VAD_THRESHOLD"] == 0.3
    assert isinstance(cfg["VAD_THRESHOLD"], float)


def test_vad_threshold_from_env(tmp_path, monkeypatch):
    """VAD_THRESHOLD is parsed as float from .env."""
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
    _write_env(tmp_path, "VAD_THRESHOLD=0.5\n")
    cfg = voice.load_config()
    assert cfg["VAD_THRESHOLD"] == 0.5
    assert isinstance(cfg["VAD_THRESHOLD"], float)


def test_vad_threshold_invalid_falls_back_to_default(tmp_path, monkeypatch):
    """Invalid float value for VAD_THRESHOLD keeps default 0.3."""
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
    _write_env(tmp_path, "VAD_THRESHOLD=not_a_number\n")
    cfg = voice.load_config()
    assert cfg["VAD_THRESHOLD"] == 0.3


def test_vad_threshold_empty_keeps_default(tmp_path, monkeypatch):
    """Empty VAD_THRESHOLD= keeps the default 0.3."""
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
    _write_env(tmp_path, "VAD_THRESHOLD=\n")
    cfg = voice.load_config()
    assert cfg["VAD_THRESHOLD"] == 0.3


# ---------------------------------------------------------------------------
# audio.transcribe: VAD parameters and fallback behaviour
#
# Strategy: patch the heavy I/O operations (np.concatenate, wave.open,
# tempfile.NamedTemporaryFile) so we never write a real WAV file.
# This lets us control exactly what model.transcribe receives.
# ---------------------------------------------------------------------------

@pytest.fixture
def audio_env(tmp_path, monkeypatch):
    """Minimal environment for testing voice.audio.transcribe without hardware."""
    monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
    monkeypatch.setattr(state, "_log_path", str(tmp_path / "voice.log"))
    monkeypatch.setattr(state, "_history_path", str(tmp_path / "history.jsonl"))
    monkeypatch.setattr(state, "_CONFIG", {
        "GEMINI_API_KEY": None,
        "GEMINI_MODEL": "gemini-2.5-flash",
        "WHISPER_MODEL": "small",
        "WHISPER_LANGUAGE": "",
        "VAD_THRESHOLD": 0.3,
        "HISTORY_MAX_ENTRIES": 500,
        "LOG_KEEP_SESSIONS": 5,
        "MAX_RECORD_SECONDS": 120,
    })
    monkeypatch.setattr(state, "is_transcribing", False)

    import sys
    sys.modules["winsound"] = MagicMock()

    return tmp_path


def _patch_wav_pipeline(monkeypatch, audio_duration_s: float):
    """
    Patch np.concatenate, wave.open, and tempfile so transcribe() never
    writes a real WAV file but still computes the correct audio_duration.

    audio_duration_s controls len(audio_data)/SAMPLE_RATE inside transcribe().
    """
    import voice.audio as _audio_mod

    # np.concatenate returns a fake array with the correct len()
    fake_audio = MagicMock()
    fake_audio.__len__ = lambda self: int(audio_duration_s * _audio_mod.SAMPLE_RATE)
    # Support arithmetic: audio_data * 32767
    fake_audio.__mul__ = lambda self, other: fake_audio
    # Support .astype().tobytes()
    fake_audio.astype.return_value.tobytes.return_value = b""

    import sys
    np_stub = sys.modules.get("numpy", MagicMock())
    np_stub.concatenate = MagicMock(return_value=fake_audio)

    # Patch wave.open so writeframes doesn't blow up
    mock_wf = MagicMock()
    mock_wf.__enter__ = MagicMock(return_value=mock_wf)
    mock_wf.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("wave.open", MagicMock(return_value=mock_wf))

    # Patch tempfile so temp_path is a predictable string
    import tempfile
    monkeypatch.setattr(
        tempfile, "NamedTemporaryFile",
        MagicMock(return_value=MagicMock(
            __enter__=MagicMock(return_value=MagicMock(name="/tmp/fake.wav")),
            __exit__=MagicMock(return_value=False),
        ))
    )

    return fake_audio


def _make_model_mock(results: list):
    """
    Returns (model, call_kwargs_list, call_count_list).

    results: [(segments, info_mock), ...]
    """
    call_kwargs: list = []
    call_count = [0]

    def fake_transcribe(path, **kwargs):
        call_kwargs.append(kwargs)
        i = call_count[0]
        call_count[0] += 1
        if i < len(results):
            return results[i]
        return [], MagicMock(duration_after_vad=0.0)

    model = MagicMock()
    model.transcribe.side_effect = fake_transcribe
    return model, call_kwargs, call_count


def test_transcribe_passes_vad_threshold_to_model(audio_env, monkeypatch):
    """transcribe() must pass VAD_THRESHOLD=0.3 from config to model.transcribe vad_parameters."""
    _patch_wav_pipeline(monkeypatch, audio_duration_s=1.0)

    seg = MagicMock()
    seg.text = "hello"
    info = MagicMock()
    info.duration_after_vad = 0.5

    model, call_kwargs, _ = _make_model_mock([([ seg], info)])
    monkeypatch.setattr(audio, "get_whisper_model", lambda mode="transcribe": model)
    monkeypatch.setattr(audio, "copy_to_clipboard", lambda t: None)
    monkeypatch.setattr(audio, "paste_via_sendinput", lambda: None)

    # Use a single non-empty fake frame
    frames = [MagicMock()]
    audio.transcribe(frames, "transcribe")

    assert len(call_kwargs) >= 1, "model.transcribe must be called at least once"
    first = call_kwargs[0]
    assert first.get("vad_filter") is True
    vad_params = first.get("vad_parameters", {})
    assert "threshold" in vad_params, "vad_parameters must include 'threshold'"
    assert vad_params["threshold"] == pytest.approx(0.3)
    assert "speech_pad_ms" in vad_params, "vad_parameters must include 'speech_pad_ms'"


def test_transcribe_skip_when_vad_detects_no_speech(audio_env, monkeypatch):
    """Task 3 (W1 reliability sprint): VAD-gate estrito, sem fallback.

    Quando o VAD não detecta fala (0 segments), a gravação vira SKIP:
    beep de erro + overlay de erro "Não detectei fala" + history com
    error=True + NENHUM paste. O fallback de retranscrição sem VAD foi
    removido por completo — não deve haver 2a chamada a model.transcribe.
    """
    _patch_wav_pipeline(monkeypatch, audio_duration_s=2.5)

    results = [([], MagicMock(duration_after_vad=0.0))]
    model, _, call_count = _make_model_mock(results)
    monkeypatch.setattr(audio, "get_whisper_model", lambda mode="transcribe": model)

    played = []
    monkeypatch.setattr(audio, "play_sound", lambda kind: played.append(kind))

    history_calls = []
    monkeypatch.setattr(
        audio, "_append_history",
        lambda *a, **k: history_calls.append((a, k)),
    )

    pasted = []
    monkeypatch.setattr(audio, "copy_to_clipboard", lambda t: None)
    monkeypatch.setattr(audio, "paste_via_sendinput", lambda: pasted.append(True))

    overlay_errors = []
    monkeypatch.setattr("voice.overlay.show_error", lambda text="": overlay_errors.append(text))

    frames = [MagicMock()]
    audio.transcribe(frames, "transcribe")

    assert call_count[0] == 1, (
        f"No fallback expected — only 1 model.transcribe call, got {call_count[0]}"
    )
    assert played == ["error"], f"Expected play_sound('error'), got {played}"
    assert len(history_calls) == 1, "History must be recorded once for the skip"
    assert history_calls[0][1].get("error") is True, "History entry must have error=True"
    assert len(overlay_errors) == 1, "Overlay error must be shown exactly once"
    assert "Não detectei fala" in overlay_errors[0]
    assert pasted == [], "No paste must happen when VAD detects no speech"


def test_transcribe_skip_no_second_model_call(audio_env, monkeypatch):
    """Task 3: model.transcribe is called exactly once — the sem-VAD fallback no longer exists."""
    _patch_wav_pipeline(monkeypatch, audio_duration_s=5.0)

    results = [([], MagicMock(duration_after_vad=0.0))]
    model, _, call_count = _make_model_mock(results)
    monkeypatch.setattr(audio, "get_whisper_model", lambda mode="transcribe": model)
    monkeypatch.setattr(audio, "copy_to_clipboard", lambda t: None)
    monkeypatch.setattr(audio, "paste_via_sendinput", lambda: None)
    monkeypatch.setattr("voice.overlay.show_error", lambda text="": None)

    frames = [MagicMock()]
    audio.transcribe(frames, "transcribe")

    assert call_count[0] == 1, (
        f"Expected exactly 1 model.transcribe call regardless of audio duration, got {call_count[0]}"
    )
