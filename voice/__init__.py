# voice/__init__.py — package entry point
# Loads submodules in correct order and re-exports for backward compatibility.

# 1. State first (no dependencies)
from voice import state  # noqa: F401

# 2. Paths — side-effect: populates state._BASE_DIR, _log_path, _history_path
from voice import paths  # noqa: F401
from voice.paths import _resource_path  # noqa: F401

# 3. Logging_ — side-effect: patches builtins.print with _log_print
from voice import logging_  # noqa: F401
from voice.logging_ import _rotate_log, _append_history  # noqa: F401

# 4. Config
from voice.config import load_config, _save_env, _reload_config  # noqa: F401

# 5. License
from voice.license import (  # noqa: F401
    _get_secret,
    validate_license_key,
    _test_gemini_key,
)

# 6. Gemini
from voice.gemini import _get_gemini_client  # noqa: F401
