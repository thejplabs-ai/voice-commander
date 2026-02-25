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
