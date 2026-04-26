# voice/sound.py — Sound playback helpers (extracted from voice/audio.py).
#
# Responsibility: play feedback sounds (start/success/error/warning/skip) using
# either a custom .wav configured in .env or a winsound.Beep fallback.
#
# Test coupling: tests patch `voice.audio.play_sound` (e.g. test_command_mode.py).
# voice/audio.py re-exports play_sound + _default_beep so monkeypatch.setattr on
# voice.audio.play_sound continues to work — every internal call inside audio.py
# resolves play_sound from the audio module namespace, which is the re-bound
# attribute, so patches intercept correctly.

import os
import threading

from voice import state

try:
    import winsound
except Exception as _e:
    print(f"[ERRO IMPORT] {_e}")
    import sys
    sys.exit(1)


def _default_beep(event: str) -> None:
    beeps = {
        "start":   [(880, 200)],
        "success": [(440, 100), (440, 100)],
        "error":   [(200, 300)],
        "warning": [(600, 200)],
        "skip":    [(300, 150)],
    }
    sequence = beeps.get(event, [])

    def _beep_thread():
        for freq, dur in sequence:
            winsound.Beep(freq, dur)

    threading.Thread(target=_beep_thread, daemon=True).start()


def play_sound(event: str) -> None:
    """Toca custom .wav ou fallback para beep padrão."""
    wav = state._CONFIG.get(f"SOUND_{event.upper()}", "")
    if wav and os.path.exists(wav):
        try:
            winsound.PlaySound(wav, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return
        except Exception as e:
            print(f"[WARN] Sound file error ({wav}): {e}")
    # Resolve _default_beep through voice.audio so monkeypatch.setattr on
    # voice.audio._default_beep is honored by tests (test_audio.py:84,91,99).
    # Lazy import avoids circular import at module load time — voice.audio
    # imports this module's symbols, and play_sound is only called at runtime.
    from voice import audio as _audio
    _audio._default_beep(event)
