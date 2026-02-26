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
record_start_time: float = 0.0  # timestamp when recording started (for min-recording guard)

# Tray state
_tray_icon = None
_tray_available: bool = False
_tray_state: str = "idle"
_tray_last_mode: str = "—"

# Mutex handle
_mutex_handle = None

# Mode selection
selected_mode: str = "transcribe"

# Lazy singletons
_gemini_client = None
_whisper_model = None
_whisper_cache_key: tuple = ()
_openai_client = None
_OPENAI_API_KEY: str | None = None

# UI state
_ctk_available: bool = False
_settings_window_ref = None
_settings_window_lock = threading.Lock()

# AI rate limiting — cooldown de 2s entre chamadas AI (SEC-05)
_ai_last_call_time: float = 0.0
_AI_COOLDOWN_SECONDS: float = 2.0

# QW-1: cooldown pós-query — ignorar hotkey por 2s após processar modo query
_query_cooldown_until: float = 0.0
_QUERY_HOTKEY_COOLDOWN: float = 2.0

# QW-6: duração da gravação para tooltip da tray
_recording_start_time: float = 0.0
_tray_tooltip_thread = None

# Story 4.5.4: clipboard context capturado no início da gravação
_clipboard_context: str = ""
