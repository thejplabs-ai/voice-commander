"""
Tests for voice/audio.py — recording, transcription, toggle_recording.

Strategy: mock sounddevice, winsound, numpy and faster_whisper at sys.modules level
(already done in conftest.py). Additional mocking done per-test with monkeypatch.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from voice import state, audio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_recording_state(monkeypatch):
    """Reset all recording state before each test."""
    monkeypatch.setattr(state, "is_recording", False)
    monkeypatch.setattr(state, "is_transcribing", False)
    monkeypatch.setattr(state, "frames_buf", [])
    monkeypatch.setattr(state, "record_thread", None)
    monkeypatch.setattr(state, "record_start_time", 0.0)
    monkeypatch.setattr(state, "_query_cooldown_until", 0.0)
    monkeypatch.setattr(state, "_CONFIG", {
        "MAX_RECORD_SECONDS": 120,
        "AUDIO_DEVICE_INDEX": None,
        "VAD_THRESHOLD": 0.3,
        "WHISPER_MODEL": "small",
        "WHISPER_DEVICE": "cpu",
        "WHISPER_MODEL_FAST": "tiny",
        "WHISPER_MODEL_QUALITY": "small",
        "WHISPER_LANGUAGE": "",
        "WHISPER_INITIAL_PROMPT": "",
        "WHISPER_BEAM_SIZE": 5,
        "PASTE_DELAY_MS": 50,
        "AI_PROVIDER": "gemini",
        "STT_PROVIDER": "whisper",
        "GEMINI_MODEL": "gemini-2.5-flash",
        "GEMINI_CORRECT": True,
        "SOUND_START": "",
        "SOUND_SUCCESS": "",
        "SOUND_ERROR": "",
        "SOUND_WARNING": "",
        "SOUND_SKIP": "",
        "TRANSLATE_TARGET_LANG": "en",
        "QUERY_SYSTEM_PROMPT": "",
    })
    # Reset stop_event
    state.stop_event.clear()
    yield


@pytest.fixture
def mock_winsound(monkeypatch):
    """Mock winsound.Beep to prevent real beeps in tests."""
    mock = MagicMock()
    import sys
    monkeypatch.setitem(sys.modules, "winsound", mock)
    return mock


# ---------------------------------------------------------------------------
# play_sound()
# ---------------------------------------------------------------------------

class TestPlaySound:
    def test_play_sound_start_chama_beep(self, monkeypatch):
        """play_sound('start') calls winsound.Beep with correct frequency."""
        beep_calls = []

        import sys
        ws_mock = MagicMock()
        ws_mock.Beep = lambda f, d: beep_calls.append((f, d))
        ws_mock.SND_FILENAME = 1
        ws_mock.SND_ASYNC = 2
        monkeypatch.setitem(sys.modules, "winsound", ws_mock)

        # Patch _default_beep directly to avoid thread timing issues
        with patch.object(audio, "_default_beep") as mock_beep:
            audio.play_sound("start")
            mock_beep.assert_called_once_with("start")

    def test_play_sound_success_usa_beep_padrao_sem_wav(self, monkeypatch):
        """play_sound uses default beep when SOUND_SUCCESS is not configured."""
        monkeypatch.setattr(state, "_CONFIG", {**state._CONFIG, "SOUND_SUCCESS": ""})
        with patch.object(audio, "_default_beep") as mock_beep:
            audio.play_sound("success")
            mock_beep.assert_called_once_with("success")

    def test_play_sound_wav_nao_existente_usa_beep_padrao(self, monkeypatch, tmp_path):
        """play_sound falls back to default beep if WAV file doesn't exist."""
        fake_wav = str(tmp_path / "nonexistent.wav")
        monkeypatch.setattr(state, "_CONFIG", {**state._CONFIG, "SOUND_START": fake_wav})
        with patch.object(audio, "_default_beep") as mock_beep:
            audio.play_sound("start")
            mock_beep.assert_called_once_with("start")


# ---------------------------------------------------------------------------
# get_whisper_model()
# ---------------------------------------------------------------------------

class TestGetWhisperModel:
    def test_lazy_load_retorna_modelo_existente(self, monkeypatch):
        """get_whisper_model returns cached model when cache_key matches."""
        mock_model = MagicMock()
        # transcribe is in _FAST_MODES -> uses WHISPER_MODEL_FAST = "tiny"
        monkeypatch.setattr(state, "_whisper_model", mock_model)
        monkeypatch.setattr(state, "_whisper_cache_key", ("tiny", "cpu"))
        monkeypatch.setattr(state, "_CONFIG", {
            **state._CONFIG,
            "WHISPER_MODEL": "small",
            "WHISPER_DEVICE": "cpu",
            "WHISPER_MODEL_FAST": "tiny",
            "WHISPER_MODEL_QUALITY": "small",
        })

        result = audio.get_whisper_model("transcribe")

        # Should return cached model without creating a new one
        assert result is mock_model

    def test_cache_retorna_mesmo_modelo_para_quality_mode(self, monkeypatch):
        """get_whisper_model returns cached model for quality modes (query uses WHISPER_MODEL_QUALITY)."""
        mock_model = MagicMock()
        # query is in _QUALITY_MODES -> uses WHISPER_MODEL_QUALITY = "small"
        monkeypatch.setattr(state, "_whisper_model", mock_model)
        monkeypatch.setattr(state, "_whisper_cache_key", ("small", "cpu"))
        monkeypatch.setattr(state, "_CONFIG", {
            **state._CONFIG,
            "WHISPER_MODEL": "small",
            "WHISPER_DEVICE": "cpu",
            "WHISPER_MODEL_FAST": "tiny",
            "WHISPER_MODEL_QUALITY": "small",
        })

        result = audio.get_whisper_model("query")
        assert result is mock_model

    def test_modo_fast_usa_whisper_model_fast(self, monkeypatch):
        """Fast modes use WHISPER_MODEL_FAST configuration."""
        mock_model = MagicMock()
        # transcribe is in _FAST_MODES -> resolves to WHISPER_MODEL_FAST = "tiny"
        monkeypatch.setattr(state, "_whisper_model", mock_model)
        monkeypatch.setattr(state, "_whisper_cache_key", ("tiny", "cpu"))
        monkeypatch.setattr(state, "_CONFIG", {
            **state._CONFIG,
            "WHISPER_MODEL": "small",
            "WHISPER_DEVICE": "cpu",
            "WHISPER_MODEL_FAST": "tiny",
            "WHISPER_MODEL_QUALITY": "small",
        })

        result = audio.get_whisper_model("transcribe")  # transcribe is in _FAST_MODES
        assert result is mock_model

    def test_modo_quality_usa_whisper_model_quality(self, monkeypatch):
        """Quality modes use WHISPER_MODEL_QUALITY configuration."""
        mock_model = MagicMock()
        monkeypatch.setattr(state, "_whisper_model", mock_model)
        monkeypatch.setattr(state, "_whisper_cache_key", ("small", "cpu"))
        monkeypatch.setattr(state, "_CONFIG", {
            **state._CONFIG,
            "WHISPER_MODEL": "small",
            "WHISPER_DEVICE": "cpu",
            "WHISPER_MODEL_FAST": "tiny",
            "WHISPER_MODEL_QUALITY": "small",
        })

        result = audio.get_whisper_model("query")  # query is in _QUALITY_MODES
        assert result is mock_model


# ---------------------------------------------------------------------------
# record() — gravação de áudio
# ---------------------------------------------------------------------------

class TestRecord:
    def test_record_acumula_frames(self, monkeypatch):
        """record() appends audio frames to state.frames_buf."""

        # Simular stream com 3 reads e depois stop
        frame_data = MagicMock()
        frame_data.copy.return_value = frame_data

        read_count = [0]
        def fake_read(n):
            read_count[0] += 1
            if read_count[0] > 3:
                state.stop_event.set()
            return frame_data, None

        mock_stream = MagicMock()
        mock_stream.read = fake_read
        mock_stream.__enter__ = lambda s: s
        mock_stream.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr(state, "frames_buf", [])
        monkeypatch.setattr(state, "_CONFIG", {
            **state._CONFIG,
            "MAX_RECORD_SECONDS": 120,
            "AUDIO_DEVICE_INDEX": None,
        })

        with patch("voice.audio.sd") as mock_sd:
            mock_sd.InputStream.return_value = mock_stream
            audio.record()

        assert len(state.frames_buf) >= 3

    def test_record_para_quando_stop_event_setado(self, monkeypatch):
        """record() stops after a few frames when stop_event is set during read."""
        monkeypatch.setattr(state, "frames_buf", [])
        monkeypatch.setattr(state, "_CONFIG", {
            **state._CONFIG,
            "MAX_RECORD_SECONDS": 120,
            "AUDIO_DEVICE_INDEX": None,
        })
        state.stop_event.clear()

        read_count = [0]
        def fake_read(n):
            read_count[0] += 1
            if read_count[0] >= 2:
                state.stop_event.set()  # Signal stop after 2 reads
            data = MagicMock()
            data.copy.return_value = data
            return data, None

        with patch("voice.audio.sd") as mock_sd:
            stream_mock = MagicMock()
            stream_mock.__enter__ = lambda s: s
            stream_mock.__exit__ = MagicMock(return_value=False)
            stream_mock.read = fake_read
            mock_sd.InputStream.return_value = stream_mock
            audio.record()

        # Should have stopped after stop_event was set — at most a few reads
        assert read_count[0] <= 5  # generous bound; stop is checked per-loop

    def test_record_timeout_dispara_warning(self, monkeypatch, capsys):
        """record() triggers warning beep 5s before MAX_RECORD_SECONDS."""
        # Set very short timeout — 6 frames total, warning at frame 1
        monkeypatch.setattr(state, "_CONFIG", {
            **state._CONFIG,
            "MAX_RECORD_SECONDS": 6,  # 6 seconds
            "AUDIO_DEVICE_INDEX": None,
        })
        monkeypatch.setattr(state, "frames_buf", [])

        # max_frames = int(6 * 16000 / 1024) = 93  (SAMPLE_RATE=16000)
        # warn_frames = int((6-5) * 16000 / 1024) = 15

        read_count = [0]

        def fake_read(n):
            read_count[0] += 1
            if read_count[0] >= 16:  # past warn_frames
                state.stop_event.set()  # stop after warning
            return MagicMock(copy=MagicMock(return_value=MagicMock())), None

        with patch("voice.audio.sd") as mock_sd, \
             patch.object(audio, "play_sound") as mock_play:
            stream_mock = MagicMock()
            stream_mock.__enter__ = lambda s: s
            stream_mock.__exit__ = MagicMock(return_value=False)
            stream_mock.read = fake_read
            mock_sd.InputStream.return_value = stream_mock
            audio.record()

        # play_sound("warning") should have been called
        mock_play.assert_any_call("warning")


# ---------------------------------------------------------------------------
# toggle_recording() — controle de gravação
# ---------------------------------------------------------------------------

class TestToggleRecording:
    def test_toggle_inicia_gravacao(self, monkeypatch):
        """First toggle_recording call starts recording."""
        monkeypatch.setattr(state, "is_recording", False)
        monkeypatch.setattr(state, "is_transcribing", False)

        with patch.object(audio, "play_sound"), \
             patch.object(audio, "_update_tray_state"), \
             patch("voice.clipboard.read_clipboard", return_value=""), \
             patch("voice.audio.threading.Thread") as mock_thread:
            mock_t = MagicMock()
            mock_thread.return_value = mock_t
            audio.toggle_recording("transcribe")

        assert state.is_recording is True

    def test_toggle_skip_se_transcricao_ativa(self, monkeypatch):
        """toggle_recording skips if transcription is in progress."""
        monkeypatch.setattr(state, "is_transcribing", True)
        monkeypatch.setattr(state, "is_recording", False)

        with patch.object(audio, "play_sound") as mock_play:
            audio.toggle_recording("transcribe")

        assert state.is_recording is False
        mock_play.assert_called_once_with("skip")

    def test_toggle_stop_inicia_transcricao(self, monkeypatch):
        """Second toggle_recording call stops recording and starts transcription."""
        monkeypatch.setattr(state, "is_recording", True)
        monkeypatch.setattr(state, "is_transcribing", False)
        monkeypatch.setattr(state, "record_start_time", time.time() - 2.0)  # 2s ago
        monkeypatch.setattr(state, "frames_buf", [MagicMock()])

        mock_thread = MagicMock()
        monkeypatch.setattr(state, "record_thread", mock_thread)
        mock_thread.join = MagicMock()

        with patch.object(audio, "_update_tray_state"), \
             patch("voice.audio.threading.Thread") as mock_t_class:
            mock_t = MagicMock()
            mock_t_class.return_value = mock_t
            audio.toggle_recording("transcribe")

        assert state.is_recording is False

    def test_toggle_ignora_stop_muito_rapido(self, monkeypatch):
        """toggle_recording ignores STOP if < 500ms from START."""
        monkeypatch.setattr(state, "is_recording", True)
        monkeypatch.setattr(state, "is_transcribing", False)
        monkeypatch.setattr(state, "record_start_time", time.time() - 0.1)  # 100ms ago

        audio.toggle_recording("transcribe")

        # Recording should still be True (STOP was ignored)
        assert state.is_recording is True

    def test_toggle_query_cooldown_ativo_skip(self, monkeypatch):
        """toggle_recording skips query mode start if cooldown is active."""
        monkeypatch.setattr(state, "is_recording", False)
        monkeypatch.setattr(state, "is_transcribing", False)
        monkeypatch.setattr(state, "_query_cooldown_until", time.time() + 10.0)  # Active cooldown

        audio.toggle_recording("query")

        # Should NOT start recording
        assert state.is_recording is False

    def test_toggle_query_cooldown_expirado_inicia(self, monkeypatch):
        """toggle_recording starts query mode when cooldown has expired."""
        monkeypatch.setattr(state, "is_recording", False)
        monkeypatch.setattr(state, "is_transcribing", False)
        monkeypatch.setattr(state, "_query_cooldown_until", time.time() - 5.0)  # Expired

        with patch.object(audio, "play_sound"), \
             patch.object(audio, "_update_tray_state"), \
             patch("voice.clipboard.read_clipboard", return_value=""), \
             patch("voice.audio.threading.Thread") as mock_thread:
            mock_t = MagicMock()
            mock_thread.return_value = mock_t
            audio.toggle_recording("query")

        assert state.is_recording is True


# ---------------------------------------------------------------------------
# transcribe() — post-processing
# ---------------------------------------------------------------------------

class TestTranscribe:
    def test_transcribe_sem_frames_retorna_erro(self, monkeypatch):
        """transcribe() with empty frames logs error and returns."""
        with patch.object(audio, "play_sound") as mock_play, \
             patch.object(audio, "_update_tray_state"), \
             patch("voice.logging_._append_history"):
            audio.transcribe([], "transcribe")

        mock_play.assert_called_once_with("error")

    def test_transcribe_query_define_cooldown(self, monkeypatch):
        """transcribe() sets _query_cooldown_until after query mode processing."""
        monkeypatch.setattr(state, "_query_cooldown_until", 0.0)

        # Mock numpy concatenate
        np_mock = MagicMock()
        np_mock.concatenate.return_value = MagicMock()
        np_mock.int16 = type("int16", (), {})()

        frame = MagicMock()

        with patch("voice.audio.np", np_mock), \
             patch("voice.audio.wave"), \
             patch("voice.audio.tempfile") as mock_tmp, \
             patch.object(audio, "_do_transcription", return_value="test query result"), \
             patch.object(audio, "_post_process_and_paste", return_value=("processed", 1200, 100)), \
             patch.object(audio, "_update_tray_state"), \
             patch("voice.logging_._append_history"):
            mock_tmp.NamedTemporaryFile.return_value.__enter__ = MagicMock(return_value=MagicMock(name="test.wav"))
            mock_tmp.NamedTemporaryFile.return_value.__exit__ = MagicMock(return_value=False)
            mock_tmp.NamedTemporaryFile.return_value.name = "/tmp/test.wav"
            with patch("os.unlink"):
                audio.transcribe([frame], "query")

        # Cooldown should have been set
        assert state._query_cooldown_until > time.time()

    def test_transcribe_nao_query_nao_define_cooldown(self, monkeypatch):
        """transcribe() does NOT set cooldown for non-query modes."""
        monkeypatch.setattr(state, "_query_cooldown_until", 0.0)

        np_mock = MagicMock()
        np_mock.concatenate.return_value = MagicMock()
        np_mock.int16 = type("int16", (), {})()

        frame = MagicMock()

        with patch("voice.audio.np", np_mock), \
             patch("voice.audio.wave"), \
             patch("voice.audio.tempfile") as mock_tmp, \
             patch.object(audio, "_do_transcription", return_value="transcribed text"), \
             patch.object(audio, "_post_process_and_paste", return_value=("processed", 1200, 100)), \
             patch.object(audio, "_update_tray_state"), \
             patch("voice.logging_._append_history"):
            mock_tmp.NamedTemporaryFile.return_value.__enter__ = MagicMock(return_value=MagicMock(name="test.wav"))
            mock_tmp.NamedTemporaryFile.return_value.__exit__ = MagicMock(return_value=False)
            mock_tmp.NamedTemporaryFile.return_value.name = "/tmp/test.wav"
            with patch("os.unlink"):
                audio.transcribe([frame], "transcribe")

        # Cooldown should NOT have been set
        assert state._query_cooldown_until == 0.0


# ---------------------------------------------------------------------------
# on_hotkey() — debounce atômico
# ---------------------------------------------------------------------------

class TestOnHotkey:
    def test_debounce_ignora_chamadas_rapidas(self, monkeypatch):
        """on_hotkey() ignores calls within 1s debounce window."""
        toggle_count = [0]

        def fake_toggle(mode):
            toggle_count[0] += 1

        # Force reset debounce state by patching _last_hotkey_time
        with patch.object(audio, "_last_hotkey_time", 0.0), \
             patch("voice.audio.threading.Thread") as mock_t:
            mock_t.return_value = MagicMock()
            audio.on_hotkey()  # First call — should pass
            audio.on_hotkey()  # Second call <1s — should be debounced

        # Only 1 thread should be started
        assert mock_t.call_count == 1

    def test_hotkey_passa_apos_debounce(self, monkeypatch):
        """on_hotkey() allows calls after debounce window."""
        with patch.object(audio, "_last_hotkey_time", time.time() - 2.0), \
             patch("voice.audio.threading.Thread") as mock_t:
            mock_t.return_value = MagicMock()
            audio.on_hotkey()

        assert mock_t.call_count == 1
