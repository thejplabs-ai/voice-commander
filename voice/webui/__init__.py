# voice/webui/__init__.py — pywebview windows for Settings and Onboarding

import os


def _html_path(name: str) -> str:
    """Resolve path to an HTML file in the webui package."""
    import sys
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, "voice", "webui", name)  # type: ignore[attr-defined]
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, name)


# ── Onboarding (blocking, must run on main thread) ───────────────────────────

def run_onboarding(done_callback=None) -> None:
    """Opens the onboarding wizard. Blocks until the window is closed."""
    try:
        import webview
    except ImportError:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            "pywebview não instalado.\n"
            "Instale com: pip install pywebview\n\n"
            "Configure manualmente no arquivo .env",
            "Voice Commander — Erro",
            0x10,
        )
        return
    from voice.webui.bridge import WebBridge

    bridge = WebBridge(done_callback=done_callback)
    window = webview.create_window(
        "Voice Commander — Configuração Inicial",
        url=_html_path("onboarding.html"),
        js_api=bridge,
        width=560,
        height=680,
        resizable=False,
        frameless=False,
        min_size=(560, 680),
        background_color="#0F0F0F",
    )
    bridge._window = window
    window.events.closed += bridge._on_window_closed
    webview.start(gui="edgechromium", debug=False)


# ── Settings (blocking, called from main thread via event) ────────────────────

def _screen_size_90() -> tuple[int, int]:
    """Calcula ~90% da tela via ctypes (sem depender de tkinter)."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        return int(sw * 0.9), int(sh * 0.9)
    except Exception:
        return 1280, 800


def open_settings_blocking() -> None:
    """Opens settings window. Must be called from main thread (pywebview requirement)."""
    try:
        import webview
        from voice.webui.bridge import WebBridge

        bridge = WebBridge()
        html = _html_path("settings.html")
        print(f"[INFO] Abrindo settings: {html}")

        w, h = _screen_size_90()
        window = webview.create_window(
            "Voice Commander — Configurações",
            url=html,
            js_api=bridge,
            width=w,
            height=h,
            resizable=True,
            frameless=False,
            min_size=(800, 600),
            background_color="#0F0F0F",
        )
        bridge._window = window
        webview.start(gui="edgechromium", debug=False)
    except Exception as e:
        print(f"[ERRO] Falha ao abrir settings: {e}")
