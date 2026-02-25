# voice/wakeword.py — Wake word listener using OpenWakeWord

import threading
import time

from voice import state


class WakeWordListener:
    """Escuta continuamente por wake word e chama on_detected() quando detectado."""

    def __init__(self, keyword: str, on_detected: callable):
        self.keyword = keyword
        self.on_detected = on_detected
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        try:
            from openwakeword.model import Model
            import sounddevice as sd
        except ImportError as e:
            print(f"[WARN] Wake word desativado — dependência ausente: {e}")
            print("[INFO] Instale com: pip install openwakeword onnxruntime")
            return

        try:
            model = Model(wakeword_models=[self.keyword], inference_framework="onnx")
        except Exception as e:
            print(f"[WARN] Wake word modelo '{self.keyword}' não carregado: {e}")
            return

        print(f"[OK]   Wake word escutando: '{self.keyword}'")

        try:
            with sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                                blocksize=1280) as stream:
                while not self._stop.is_set():
                    # Pausar durante gravação/transcrição para evitar conflito de mic
                    if state.is_recording or state.is_transcribing:
                        time.sleep(0.1)
                        continue
                    try:
                        audio, _ = stream.read(1280)
                        prediction = model.predict(audio.flatten())
                        score = prediction.get(self.keyword, 0)
                        if score > 0.5:
                            print(f"[WAKE] '{self.keyword}' detectado (score={score:.2f})")
                            self.on_detected()
                            time.sleep(2)  # debounce
                    except Exception as e:
                        print(f"[WARN] Wake word read error: {e}")
                        time.sleep(0.5)
        except Exception as e:
            print(f"[WARN] Wake word stream error: {e}")
