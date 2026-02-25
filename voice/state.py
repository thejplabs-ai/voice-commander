# voice/state.py — canonical namespace for all shared mutable globals
# NO imports from voice/* — this is the root of the dependency DAG.

import threading

# Config / credentials
_CONFIG: dict = {}
_GEMINI_API_KEY: str | None = None
_LICENSE_EXPIRED_NOTIFIED: bool = False

# Paths (populated by voice/paths.py on import)
_BASE_DIR: str = ""
_log_path: str = ""
_history_path: str = ""

# Recording state
stop_event = threading.Event()
is_recording: bool = False
is_transcribing: bool = False
frames_buf: list = []
record_thread = None
_toggle_lock = threading.Lock()
current_mode: str = "transcribe"

# Tray state
_tray_icon = None
_tray_available: bool = False
_tray_state: str = "idle"
_tray_last_mode: str = "—"

# Mutex handle
_mutex_handle = None

# Lazy singletons
_gemini_client = None
_whisper_model = None

# UI state
_ctk_available: bool = False
_settings_window_ref = None
_settings_window_lock = threading.Lock()
