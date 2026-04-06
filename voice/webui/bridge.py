# voice/webui/bridge.py — Python API exposed to JavaScript via pywebview

from voice import state
from voice import __version__
from voice.config import (
    _save_env,
    _reload_config,
    validate_license_key,
    _test_gemini_key,
)


class WebBridge:
    """Methods exposed to JavaScript via window.pywebview.api.<method>().

    All public methods are automatically callable from JS.
    Return values must be JSON-serializable (dict, list, str, int, bool, None).
    """

    def __init__(self, done_callback=None):
        self._window = None  # set after create_window()
        self._done_callback = done_callback

    # ── Read state ──────────────────────────────────────────────────────────

    def get_config(self) -> dict:
        """Returns the full config dict for populating form fields."""
        cfg = dict(state._CONFIG)
        # Mask API keys — only show last 4 chars
        for k in ("GEMINI_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
            val = cfg.get(k)
            if val and len(val) > 4:
                cfg[k] = "***" + val[-4:]
            elif val:
                cfg[k] = "****"
        return cfg

    def get_state(self) -> dict:
        """Returns runtime state for live status display."""
        return {
            "tray_state": state._tray_state,
            "selected_mode": state.selected_mode,
            "is_recording": state.is_recording,
            "is_transcribing": state.is_transcribing,
            "version": __version__,
            "gemini_ok": state._GEMINI_API_KEY is not None,
            "tray_available": state._tray_available,
        }

    def get_version(self) -> str:
        return __version__

    # ── Write config ────────────────────────────────────────────────────────

    def save_config(self, values: dict) -> dict:
        """Save config values to .env and reload."""
        try:
            # Convert bools back to string for .env
            clean = {}
            for k, v in values.items():
                if isinstance(v, bool):
                    clean[k] = "true" if v else "false"
                elif v is None:
                    continue
                else:
                    clean[k] = str(v)
            _save_env(clean)
            _reload_config()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def select_mode(self, mode: str) -> dict:
        """Change active mode."""
        state.selected_mode = mode
        try:
            _save_env({"SELECTED_MODE": mode})
        except Exception as e:
            return {"ok": False, "error": str(e)}
        # Update tray tooltip
        try:
            from voice.tray import _update_tray_state
            _update_tray_state("idle")
        except Exception:
            pass
        return {"ok": True}

    # ── Validation ──────────────────────────────────────────────────────────

    def validate_license(self, key: str) -> dict:
        valid, msg = validate_license_key(key)
        return {"valid": valid, "message": msg}

    def test_gemini_key(self, key: str) -> dict:
        ok, msg = _test_gemini_key(key)
        return {"ok": ok, "message": msg}

    # ── Onboarding ──────────────────────────────────────────────────────────

    def test_openrouter_key(self, key: str) -> dict:
        """Validate OpenRouter API key format."""
        key = key.strip()
        if not key:
            return {"ok": False, "message": "Chave vazia"}
        if not key.startswith("sk-or-"):
            return {"ok": False, "message": "Formato inválido — chave deve começar com 'sk-or-'"}
        if len(key) < 20:
            return {"ok": False, "message": "Chave muito curta"}
        return {"ok": True, "message": "Formato OK"}

    def finish_onboarding(self, api_key: str, license_key: str, provider: str = "openrouter") -> dict:
        """Save keys from onboarding and mark as done."""
        try:
            env_vals = {}
            if api_key:
                if provider == "openrouter":
                    env_vals["OPENROUTER_API_KEY"] = api_key
                elif provider == "openai":
                    env_vals["OPENAI_API_KEY"] = api_key
                else:
                    env_vals["GEMINI_API_KEY"] = api_key
            if license_key:
                env_vals["LICENSE_KEY"] = license_key
            if env_vals:
                _save_env(env_vals)
            if self._done_callback:
                self._done_callback()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── Window control ──────────────────────────────────────────────────────

    def close_window(self) -> None:
        if self._window:
            self._window.destroy()

    def open_url(self, url: str) -> None:
        """Open external URL in the default browser."""
        import webbrowser
        if url and url.startswith("http"):
            webbrowser.open(url)

    def _on_window_closed(self) -> None:
        """Called when window is closed via X button."""
        pass

    # ── File dialogs ────────────────────────────────────────────────────────

    def pick_sound_file(self) -> str:
        """Open native file picker for WAV files."""
        if not self._window:
            return ""
        try:
            import webview
            result = self._window.create_file_dialog(
                dialog_type=webview.OPEN_DIALOG,
                file_types=("WAV files (*.wav)",),
            )
            if result and len(result) > 0:
                return result[0]
        except Exception:
            pass
        return ""
