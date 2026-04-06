"""
Tests for Epic 5.4 — Extended Recording + Hands-Free (VAD Auto-Start).

Story 5.4.1: MAX_RECORD_SECONDS default = 600 (10 min)
Story 5.4.2: hands_free_loop() — VAD-based auto-start/stop
"""

import sys
import threading
from unittest.mock import MagicMock


from voice import state
from voice.config import load_config


def _get_real_numpy():
    """Return the real numpy module, bypassing the MagicMock stub in sys.modules."""
    # Temporarily restore real numpy to get the actual module object
    mock_np = sys.modules.get("numpy")
    try:
        del sys.modules["numpy"]
        import numpy as _real
        return _real
    except ImportError:
        return mock_np
    finally:
        sys.modules["numpy"] = mock_np


# ---------------------------------------------------------------------------
# Story 5.4.1: Extended Recording — defaults and memory footprint
# ---------------------------------------------------------------------------

class TestExtendedRecordingConfig:
    def test_max_record_seconds_default(self, tmp_path, monkeypatch):
        """MAX_RECORD_SECONDS default must be 600 (10 minutes) when no .env overrides it."""
        # Use tmp_path to isolate from local .env which may have a different value
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        cfg = load_config()
        assert cfg["MAX_RECORD_SECONDS"] == 600

    def test_max_record_seconds_memory_footprint(self):
        """600s at 16kHz mono float32 = ~38MB — acceptable in-memory buffer."""
        sample_rate = 16000
        channels = 1
        bytes_per_sample = 4  # float32
        max_seconds = 600

        total_bytes = sample_rate * channels * bytes_per_sample * max_seconds
        total_mb = total_bytes / (1024 * 1024)

        # Should be ~38MB — well under 100MB practical limit
        assert total_mb < 100, f"Buffer too large: {total_mb:.1f}MB"
        assert total_mb > 30, f"Unexpected calculation: {total_mb:.1f}MB"

    def test_max_record_seconds_override_from_env(self, tmp_path, monkeypatch):
        """MAX_RECORD_SECONDS can be overridden via .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text("MAX_RECORD_SECONDS=300\n", encoding="utf-8")
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))

        cfg = load_config()
        assert cfg["MAX_RECORD_SECONDS"] == 300


# ---------------------------------------------------------------------------
# Story 5.4.2: Hands-Free Config
# ---------------------------------------------------------------------------

class TestHandsFreeConfig:
    def test_hands_free_enabled_default_false(self):
        """HANDS_FREE_ENABLED must default to False (bool, not string)."""
        cfg = load_config()
        assert cfg["HANDS_FREE_ENABLED"] is False

    def test_hands_free_silence_ms_default(self):
        """HANDS_FREE_SILENCE_MS default must be 2000."""
        cfg = load_config()
        assert cfg["HANDS_FREE_SILENCE_MS"] == 2000
        assert isinstance(cfg["HANDS_FREE_SILENCE_MS"], int)

    def test_hands_free_speech_ms_default(self):
        """HANDS_FREE_SPEECH_MS default must be 500."""
        cfg = load_config()
        assert cfg["HANDS_FREE_SPEECH_MS"] == 500
        assert isinstance(cfg["HANDS_FREE_SPEECH_MS"], int)

    def test_hands_free_enabled_from_env(self, tmp_path, monkeypatch):
        """HANDS_FREE_ENABLED=true in .env must parse to bool True."""
        env_file = tmp_path / ".env"
        env_file.write_text("HANDS_FREE_ENABLED=true\n", encoding="utf-8")
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))

        cfg = load_config()
        assert cfg["HANDS_FREE_ENABLED"] is True

    def test_hands_free_silence_ms_from_env(self, tmp_path, monkeypatch):
        """HANDS_FREE_SILENCE_MS from .env must parse as int."""
        env_file = tmp_path / ".env"
        env_file.write_text("HANDS_FREE_SILENCE_MS=3000\n", encoding="utf-8")
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))

        cfg = load_config()
        assert cfg["HANDS_FREE_SILENCE_MS"] == 3000

    def test_hands_free_speech_ms_from_env(self, tmp_path, monkeypatch):
        """HANDS_FREE_SPEECH_MS from .env must parse as int."""
        env_file = tmp_path / ".env"
        env_file.write_text("HANDS_FREE_SPEECH_MS=1000\n", encoding="utf-8")
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))

        cfg = load_config()
        assert cfg["HANDS_FREE_SPEECH_MS"] == 1000


# ---------------------------------------------------------------------------
# Story 5.4.2: hands_free_loop() behaviour
# ---------------------------------------------------------------------------

class TestHandsFreeLoop:
    def _base_config(self, hands_free_enabled: bool = True) -> dict:
        return {
            "HANDS_FREE_ENABLED": hands_free_enabled,
            "VAD_THRESHOLD": 0.3,
            "HANDS_FREE_SPEECH_MS": 500,
            "HANDS_FREE_SILENCE_MS": 2000,
            "AUDIO_DEVICE_INDEX": None,
        }

    def test_hands_free_disabled_returns_immediately(self, monkeypatch):
        """hands_free_loop() must return immediately when HANDS_FREE_ENABLED=False."""
        from voice import audio

        monkeypatch.setattr(state, "_CONFIG", self._base_config(hands_free_enabled=False))

        # Run synchronously — must return without blocking
        audio.hands_free_loop()  # should return immediately

    def test_hands_free_speech_detection_triggers_start(self, monkeypatch):
        """High-RMS frames for >= speech_ms should call toggle_recording (START)."""
        from voice import audio

        real_np = _get_real_numpy()

        monkeypatch.setattr(state, "_CONFIG", self._base_config())
        monkeypatch.setattr(state, "is_recording", False)
        monkeypatch.setattr(state, "is_transcribing", False)
        monkeypatch.setattr(state, "selected_mode", "transcribe")
        # Inject real numpy so RMS calculation inside hands_free_loop is accurate
        monkeypatch.setattr(audio, "np", real_np)

        toggle_calls: list = []

        def _fake_toggle(mode: str) -> None:
            toggle_calls.append(mode)

        monkeypatch.setattr(audio, "toggle_recording", _fake_toggle)

        # chunk_ms=50 → speech_frames_needed = 500/50 = 10 chunks
        # Feed 12 high-energy chunks (all ones → RMS=1.0 >> threshold 0.03)
        rng = [0]

        def _fake_read(n):
            rng[0] += 1
            if rng[0] > 12:
                state._shutdown_event.set()
            data = real_np.ones((n, 1), dtype="float32")
            return data, True

        mock_stream = MagicMock()
        mock_stream.__enter__ = lambda s: s
        mock_stream.__exit__ = MagicMock(return_value=False)
        mock_stream.read = _fake_read

        sd_mock = sys.modules["sounddevice"]
        original_InputStream = sd_mock.InputStream
        sd_mock.InputStream = MagicMock(return_value=mock_stream)

        state._shutdown_event.clear()

        try:
            audio.hands_free_loop()
        finally:
            sd_mock.InputStream = original_InputStream
            state._shutdown_event.clear()

        assert len(toggle_calls) >= 1, "toggle_recording should have been called for speech detection"
        assert toggle_calls[0] == "transcribe"

    def test_hands_free_silence_detection_triggers_stop(self, monkeypatch):
        """Silence frames >= silence_ms while recording should call toggle_recording (STOP)."""
        from voice import audio

        real_np = _get_real_numpy()

        monkeypatch.setattr(state, "_CONFIG", self._base_config())
        monkeypatch.setattr(state, "is_recording", True)   # already recording
        monkeypatch.setattr(state, "is_transcribing", False)
        monkeypatch.setattr(state, "selected_mode", "transcribe")
        # Inject real numpy so RMS=0.0 for zero-filled frames
        monkeypatch.setattr(audio, "np", real_np)

        toggle_calls: list = []
        toggle_called_event = threading.Event()

        def _fake_toggle(mode: str) -> None:
            toggle_calls.append(mode)
            toggle_called_event.set()

        monkeypatch.setattr(audio, "toggle_recording", _fake_toggle)

        # chunk_ms=50 → silence_frames_needed = 2000/50 = 40 chunks
        # Feed 45 silent chunks (zeros → RMS=0.0 < 0.03), then shutdown
        rng = [0]

        def _fake_read(n):
            rng[0] += 1
            if rng[0] > 45:
                state._shutdown_event.set()
            data = real_np.zeros((n, 1), dtype="float32")
            return data, True

        mock_stream = MagicMock()
        mock_stream.__enter__ = lambda s: s
        mock_stream.__exit__ = MagicMock(return_value=False)
        mock_stream.read = _fake_read

        sd_mock = sys.modules["sounddevice"]
        original_InputStream = sd_mock.InputStream
        sd_mock.InputStream = MagicMock(return_value=mock_stream)

        state._shutdown_event.clear()

        try:
            audio.hands_free_loop()
            # Toggle is fired in a daemon thread — wait for it to execute
            toggle_called_event.wait(timeout=3.0)
        finally:
            sd_mock.InputStream = original_InputStream
            state._shutdown_event.clear()

        assert len(toggle_calls) >= 1, "toggle_recording should have been called for silence detection"

    def test_hands_free_exception_does_not_propagate(self, monkeypatch):
        """hands_free_loop() must catch exceptions and not raise."""
        from voice import audio

        monkeypatch.setattr(state, "_CONFIG", self._base_config())
        monkeypatch.setattr(state, "is_recording", False)
        monkeypatch.setattr(state, "is_transcribing", False)

        sd_mock = sys.modules["sounddevice"]
        original_InputStream = sd_mock.InputStream
        sd_mock.InputStream = MagicMock(side_effect=RuntimeError("Mic unavailable"))

        try:
            # Should not raise — exception must be caught internally
            audio.hands_free_loop()
        finally:
            sd_mock.InputStream = original_InputStream

    def test_hands_free_no_double_start_while_recording(self, monkeypatch):
        """Speech detection must NOT trigger start if is_recording=True."""
        from voice import audio

        real_np = _get_real_numpy()

        monkeypatch.setattr(state, "_CONFIG", self._base_config())
        monkeypatch.setattr(state, "is_recording", True)   # already recording
        monkeypatch.setattr(state, "is_transcribing", False)
        monkeypatch.setattr(state, "selected_mode", "transcribe")
        monkeypatch.setattr(audio, "np", real_np)

        toggle_calls: list = []

        def _fake_toggle(mode: str) -> None:
            toggle_calls.append(mode)

        monkeypatch.setattr(audio, "toggle_recording", _fake_toggle)

        rng = [0]

        def _fake_read(n):
            rng[0] += 1
            if rng[0] > 12:
                state._shutdown_event.set()
            # High energy (all ones → RMS=1.0) — but is_recording=True, so start must NOT fire
            data = real_np.ones((n, 1), dtype="float32")
            return data, True

        mock_stream = MagicMock()
        mock_stream.__enter__ = lambda s: s
        mock_stream.__exit__ = MagicMock(return_value=False)
        mock_stream.read = _fake_read

        sd_mock = sys.modules["sounddevice"]
        original_InputStream = sd_mock.InputStream
        sd_mock.InputStream = MagicMock(return_value=mock_stream)

        state._shutdown_event.clear()

        try:
            audio.hands_free_loop()
        finally:
            sd_mock.InputStream = original_InputStream
            state._shutdown_event.clear()

        # With is_recording=True, the speech detection branch skips auto-start
        # (high-energy → 0 silence frames → no stop either)
        assert toggle_calls == [], "Should not auto-start when already recording"
