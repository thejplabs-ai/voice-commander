# voice/ui.py — re-export hub (backward-compat facade)
#
# Classes live in dedicated modules:
#   OnboardingWindow  → voice/ui_onboarding.py
#   SettingsWindow    → voice/ui_settings.py
#   _apply_taskbar_icon → voice/ui_helpers.py
#
# External imports that MUST continue to work:
#   from voice.ui import OnboardingWindow        (tests/test_ui.py:54)
#   from voice.ui import SettingsWindow          (tests/test_ui.py:134)
#   from voice.ui import _apply_taskbar_icon     (tests/test_ui.py:224)
#   voice.ui._reload_config                      (tests/test_ui.py monkeypatch)
#   voice/app.py uses SettingsWindow

from voice.config import _save_env, _reload_config  # noqa: F401 — tests monkeypatch voice.ui._reload_config

from voice.ui_helpers import _apply_taskbar_icon  # noqa: F401
from voice.ui_onboarding import OnboardingWindow  # noqa: F401
from voice.ui_settings import SettingsWindow      # noqa: F401

from voice import state

# Tentar importar customtkinter — emite aviso amigável se ausente
try:
    import customtkinter  # noqa: F401
    state._ctk_available = True
except ImportError:
    print("[WARN] customtkinter não instalado — janela de configurações desativada. "
          "Instale com: pip install customtkinter==5.2.2")
