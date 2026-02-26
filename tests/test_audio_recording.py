"""
Regression tests for voice/audio.py — recording and toggle_recording.

Bug fixed: frames_buf race condition
  Previously, record() accumulated audio in a local `frames` variable and only
  assigned it to state.frames_buf when the function returned (inside do_record()).
  If record_thread.join(timeout=3) timed out before the thread finished,
  state.frames_buf was still [] when transcribe() was called, causing a silent
  failure with a 200 Hz error beep.

Fix: record() now appends directly into state.frames_buf incrementally.
  toggle_recording STOP reads state.frames_buf after join(), which contains all
  frames captured so far regardless of whether join() timed out.
"""
import threading
import time
from unittest.mock import MagicMock


from voice import state, audio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_frame():
    """Return a MagicMock that simulates a numpy audio frame with .copy()."""
    frame = MagicMock()
    frame.copy.return_value = frame
    return frame


# ---------------------------------------------------------------------------
# record() — unit tests for incremental write to state.frames_buf
# ---------------------------------------------------------------------------

class TestRecordIncremental:
    """record() must write frames directly into state.frames_buf, not a local list."""

    def test_frames_written_to_state_buf_incrementally(self, monkeypatch, mock_config):
        """Each frame read from the stream is immediately in state.frames_buf."""
        fake_frame = _make_fake_frame()

        # Simulate: first read returns a frame, second read sees stop_event
        read_count = [0]
        stop_event_copy = threading.Event()

        def fake_read(chunk_size):
            read_count[0] += 1
            if read_count[0] == 1:
                return fake_frame, None
            # Stop after first frame
            stop_event_copy.set()
            state.stop_event.set()
            return fake_frame, None

        fake_stream = MagicMock()
        fake_stream.__enter__ = MagicMock(return_value=fake_stream)
        fake_stream.__exit__ = MagicMock(return_value=False)
        fake_stream.read = fake_read

        monkeypatch.setattr(state, "frames_buf", [])
        monkeypatch.setattr(state.stop_event, "is_set", lambda: state.stop_event._flag)

        import sounddevice as sd
        monkeypatch.setattr(sd, "InputStream", MagicMock(return_value=fake_stream))

        state.stop_event.clear()
        audio.record()

        # frames_buf must contain at least the first frame
        assert len(state.frames_buf) >= 1, (
            "record() must append frames to state.frames_buf directly — "
            "not to a local variable that is only assigned after the function returns"
        )

    def test_frames_buf_populated_before_thread_join_completes(self, monkeypatch, mock_config):
        """
        Regression: frames must be in state.frames_buf even if join() completes
        while record() is still inside its last stream.read() call.

        We simulate this by:
          1. Starting record() in a thread
          2. Letting it write one frame
          3. Setting stop_event
          4. Joining the thread
          5. Verifying frames_buf is not empty
        """
        fake_frame = _make_fake_frame()
        barrier = threading.Event()  # signals that at least one frame was appended
        read_count = [0]

        def fake_read(chunk_size):
            read_count[0] += 1
            if read_count[0] == 1:
                return fake_frame, None
            # Signal that first frame is in buf, then stop
            barrier.set()
            state.stop_event.set()
            return fake_frame, None

        fake_stream = MagicMock()
        fake_stream.__enter__ = MagicMock(return_value=fake_stream)
        fake_stream.__exit__ = MagicMock(return_value=False)
        fake_stream.read = fake_read

        import sounddevice as sd
        monkeypatch.setattr(sd, "InputStream", MagicMock(return_value=fake_stream))
        monkeypatch.setattr(state, "frames_buf", [])
        state.stop_event.clear()

        t = threading.Thread(target=audio.record, daemon=True)
        t.start()

        # Wait until at least one frame was appended (or timeout)
        barrier.wait(timeout=2.0)
        t.join(timeout=5)

        assert len(state.frames_buf) >= 1, (
            "state.frames_buf must be populated during recording, "
            "not only after record() returns"
        )

    def test_record_does_not_return_list(self, monkeypatch, mock_config):
        """record() return type is None — callers must read state.frames_buf directly."""
        fake_frame = _make_fake_frame()
        read_count = [0]

        def fake_read(chunk_size):
            read_count[0] += 1
            state.stop_event.set()
            return fake_frame, None

        fake_stream = MagicMock()
        fake_stream.__enter__ = MagicMock(return_value=fake_stream)
        fake_stream.__exit__ = MagicMock(return_value=False)
        fake_stream.read = fake_read

        import sounddevice as sd
        monkeypatch.setattr(sd, "InputStream", MagicMock(return_value=fake_stream))
        monkeypatch.setattr(state, "frames_buf", [])
        state.stop_event.clear()

        result = audio.record()
        assert result is None, "record() must return None (frames go to state.frames_buf)"


# ---------------------------------------------------------------------------
# toggle_recording() — integration: frames available after stop
# ---------------------------------------------------------------------------

class TestToggleRecordingFramesAvailable:
    """
    Regression: toggle_recording STOP must pass non-empty frames to transcribe().
    Previously, transcribe() received [] because state.frames_buf was only
    assigned after record() returned (inside do_record()), which could race
    with the join(timeout=3) expiring.
    """

    def test_transcribe_receives_frames_after_stop(self, monkeypatch, mock_config):
        """
        Full cycle: START recording → frames accumulated → STOP → transcribe gets frames.
        Verifies that list(state.frames_buf) passed to transcribe is not empty.
        """
        fake_frame = _make_fake_frame()
        transcribe_args = []

        # Patch transcribe to capture what it receives
        def fake_transcribe(frames, mode):
            transcribe_args.append((frames, mode))

        monkeypatch.setattr(audio, "transcribe", fake_transcribe)

        # Patch record() to simulate one frame being recorded then stopping
        def fake_record():
            state.frames_buf.append(fake_frame)  # simulate one frame captured
            # Wait for stop_event (simulates real recording loop)
            state.stop_event.wait(timeout=2.0)

        monkeypatch.setattr(audio, "record", fake_record)

        # Patch winsound
        import winsound
        monkeypatch.setattr(winsound, "Beep", MagicMock())

        # Patch _update_tray_state
        monkeypatch.setattr(audio, "_update_tray_state", MagicMock())

        # Reset state
        monkeypatch.setattr(state, "is_recording", False)
        monkeypatch.setattr(state, "is_transcribing", False)
        monkeypatch.setattr(state, "frames_buf", [])
        monkeypatch.setattr(state, "record_thread", None)
        state.stop_event.clear()

        # --- START recording ---
        audio.toggle_recording("transcribe")
        time.sleep(0.1)  # let record thread start and append one frame

        # Verify frame was captured in state.frames_buf DURING recording
        assert len(state.frames_buf) == 1, "Frame must be in state.frames_buf during recording"

        # Seed record_start_time to simulate 600ms elapsed — bypasses minimum recording guard.
        # This test validates the frames-available fix, not the minimum-time guard.
        monkeypatch.setattr(state, "record_start_time", time.time() - 0.6)

        # --- STOP recording ---
        audio.toggle_recording("transcribe")
        time.sleep(0.2)  # let transcribe thread launch

        # Verify transcribe received the frames
        assert len(transcribe_args) == 1, "transcribe() must be called once after STOP"
        frames_received, mode_received = transcribe_args[0]
        assert len(frames_received) == 1, (
            "transcribe() must receive the frames accumulated during recording — "
            "got empty list, indicating the race condition is present"
        )
        assert mode_received == "transcribe"


class TestOnHotkeyDebounce:
    """Debounce incondicional em on_hotkey() previne double-fire em qualquer estado."""

    def test_double_fire_is_blocked_unconditionally(self, monkeypatch, mock_config):
        """
        Regression: second on_hotkey() call within 1000ms must be ignored
        regardless of is_recording state (unconditional debounce).
        Root cause: keyboard library bounce arrives ~350-400ms after key-down,
        which passed the old 300ms debounce. New threshold is 1000ms.
        """
        import winsound
        monkeypatch.setattr(winsound, "Beep", MagicMock())
        monkeypatch.setattr(audio, "_update_tray_state", MagicMock())
        monkeypatch.setattr(audio, "record", lambda: time.sleep(5))  # record blocks
        monkeypatch.setattr(audio, "transcribe", MagicMock())

        monkeypatch.setattr(state, "is_recording", False)
        monkeypatch.setattr(state, "is_transcribing", False)
        monkeypatch.setattr(state, "frames_buf", [])
        monkeypatch.setattr(state, "record_thread", None)
        monkeypatch.setattr(audio, "_last_hotkey_time", 0.0)
        state.stop_event.clear()

        # First call: should START
        audio.on_hotkey()
        time.sleep(0.05)  # let toggle thread run
        assert state.is_recording is True

        # Second call immediately (bounce) — must be blocked even though is_recording=True
        audio.on_hotkey()
        time.sleep(0.05)

        # transcribe must NOT have been called (bounce blocked)
        audio.transcribe.assert_not_called()

    def test_stop_is_allowed_after_debounce_window(self, monkeypatch, mock_config):
        """STOP must work normally after the 1000ms debounce window has passed."""
        import winsound
        monkeypatch.setattr(winsound, "Beep", MagicMock())
        monkeypatch.setattr(audio, "_update_tray_state", MagicMock())
        monkeypatch.setattr(audio, "record", lambda: state.stop_event.wait(5))
        transcribe_calls = []
        monkeypatch.setattr(audio, "transcribe", lambda f, m: transcribe_calls.append((f, m)))

        monkeypatch.setattr(state, "is_recording", False)
        monkeypatch.setattr(state, "is_transcribing", False)
        monkeypatch.setattr(state, "frames_buf", [])
        monkeypatch.setattr(state, "record_thread", None)
        monkeypatch.setattr(audio, "_last_hotkey_time", 0.0)
        state.stop_event.clear()

        # START — also seed record_start_time far in the past so min-recording guard passes
        monkeypatch.setattr(state, "record_start_time", 0.0)
        audio.on_hotkey()
        time.sleep(1.1)  # wait past debounce window (1000ms)
        assert state.is_recording is True

        # STOP after debounce window — must be allowed
        audio.on_hotkey()
        time.sleep(0.2)

        assert len(transcribe_calls) == 1, "STOP must trigger transcribe after debounce window"


class TestMinimumRecordingTime:
    """Camada 2: STOP prematuro (<500ms do START) é ignorado silenciosamente."""

    def test_premature_stop_is_ignored(self, monkeypatch, mock_config):
        """
        Regression: se o STOP chegar antes de 500ms do início da gravação,
        toggle_recording() deve retornar silenciosamente sem chamar transcribe().
        Simula o segundo fire do keyboard library (~350-400ms após key-down)
        que passou o debounce antigo de 300ms mas agora é bloqueado por esta camada.
        """
        import winsound
        monkeypatch.setattr(winsound, "Beep", MagicMock())
        monkeypatch.setattr(audio, "_update_tray_state", MagicMock())
        monkeypatch.setattr(audio, "record", lambda: state.stop_event.wait(5))
        transcribe_mock = MagicMock()
        monkeypatch.setattr(audio, "transcribe", transcribe_mock)

        monkeypatch.setattr(state, "is_recording", False)
        monkeypatch.setattr(state, "is_transcribing", False)
        monkeypatch.setattr(state, "frames_buf", [])
        monkeypatch.setattr(state, "record_thread", None)
        state.stop_event.clear()

        # START recording
        audio.toggle_recording("transcribe")
        time.sleep(0.05)  # let record thread start
        assert state.is_recording is True, "Should be recording after START"

        # STOP prematuro — menos de 500ms após o START (simula bounce ~400ms)
        audio.toggle_recording("transcribe")
        time.sleep(0.1)

        # Gravação deve continuar — STOP foi ignorado
        assert state.is_recording is True, (
            "Recording must continue after premature STOP (<500ms) — "
            "minimum recording time guard should have blocked the STOP"
        )
        transcribe_mock.assert_not_called()

    def test_stop_allowed_after_minimum_recording_time(self, monkeypatch, mock_config):
        """STOP legítimo (>=500ms após START) deve funcionar normalmente."""
        import winsound
        monkeypatch.setattr(winsound, "Beep", MagicMock())
        monkeypatch.setattr(audio, "_update_tray_state", MagicMock())
        monkeypatch.setattr(audio, "record", lambda: state.stop_event.wait(5))
        transcribe_calls = []
        monkeypatch.setattr(audio, "transcribe", lambda f, m: transcribe_calls.append((f, m)))

        monkeypatch.setattr(state, "is_recording", False)
        monkeypatch.setattr(state, "is_transcribing", False)
        monkeypatch.setattr(state, "frames_buf", [])
        monkeypatch.setattr(state, "record_thread", None)
        state.stop_event.clear()

        # START recording
        audio.toggle_recording("transcribe")
        time.sleep(0.05)
        assert state.is_recording is True

        # Seed record_start_time to simulate 600ms elapsed (past 500ms threshold)
        monkeypatch.setattr(state, "record_start_time", time.time() - 0.6)

        # STOP legítimo
        audio.toggle_recording("transcribe")
        time.sleep(0.2)

        assert len(transcribe_calls) == 1, "Legitimate STOP (>=500ms) must trigger transcribe"
