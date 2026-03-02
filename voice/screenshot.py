# voice/screenshot.py — Captura de tela via PIL.ImageGrab (Feature 3)
# Pillow já está em requirements.txt — sem nova dependência.

import io
import threading


def capture_screen(max_width: int = 1280) -> bytes | None:
    """Captura a tela primária, redimensiona e retorna bytes PNG.

    Args:
        max_width: Largura máxima do screenshot (preserva aspect ratio).
    Returns:
        bytes PNG ou None se falhar.
    """
    try:
        from PIL import ImageGrab

        result = [None]

        def _grab():
            try:
                result[0] = ImageGrab.grab()
            except Exception as e:
                print(f"[WARN] ImageGrab falhou: {e}")

        t = threading.Thread(target=_grab, daemon=True)
        t.start()
        t.join(timeout=2.0)
        if t.is_alive():
            print("[WARN] Screenshot timeout (2s) — modo visual sem imagem")
            return None

        img = result[0]
        if img is None:
            return None

        # Redimensionar se necessário (preserva aspect ratio)
        w, h = img.size
        if w > max_width:
            ratio = max_width / w
            new_h = int(h * ratio)
            img = img.resize((max_width, new_h))

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    except Exception as e:
        print(f"[WARN] screenshot: {e}")
        return None
