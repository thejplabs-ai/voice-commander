"""
Tests for load_config() — pure .env parsing logic.
No hardware or network deps touched.
"""


import voice


def _write_env(tmp_path, content: str) -> None:
    """Write a .env file in tmp_path."""
    (tmp_path / ".env").write_text(content, encoding="utf-8")


def test_defaults_sem_env(tmp_path, monkeypatch):
    """When no .env file exists, load_config returns all correct defaults."""
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
    # Ensure no .env in tmp_path
    env_path = tmp_path / ".env"
    assert not env_path.exists()

    cfg = voice.load_config()

    assert cfg["GEMINI_API_KEY"] is None
    assert cfg["LICENSE_KEY"] is None
    assert cfg["WHISPER_MODEL"] == "tiny"  # 4.6.1: default mudou para tiny
    assert cfg["WHISPER_LANGUAGE"] == ""  # vazio = auto-detect PT+EN
    assert cfg["MAX_RECORD_SECONDS"] == 600  # default atual (Epic 5.x)
    assert cfg["AUDIO_DEVICE_INDEX"] is None
    assert cfg["QUERY_SYSTEM_PROMPT"] == ""
    assert cfg["HISTORY_MAX_ENTRIES"] == 500
    assert cfg["LOG_KEEP_SESSIONS"] == 5


def test_parse_valores_int(tmp_path, monkeypatch):
    """MAX_RECORD_SECONDS, HISTORY_MAX_ENTRIES, LOG_KEEP_SESSIONS become int."""
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
    _write_env(tmp_path, (
        "MAX_RECORD_SECONDS=60\n"
        "HISTORY_MAX_ENTRIES=200\n"
        "LOG_KEEP_SESSIONS=3\n"
    ))

    cfg = voice.load_config()

    assert cfg["MAX_RECORD_SECONDS"] == 60
    assert isinstance(cfg["MAX_RECORD_SECONDS"], int)
    assert cfg["HISTORY_MAX_ENTRIES"] == 200
    assert isinstance(cfg["HISTORY_MAX_ENTRIES"], int)
    assert cfg["LOG_KEEP_SESSIONS"] == 3
    assert isinstance(cfg["LOG_KEEP_SESSIONS"], int)


def test_placeholder_gemini_key(tmp_path, monkeypatch):
    """The placeholder 'your_gemini_api_key_here' is normalized to None."""
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
    _write_env(tmp_path, "GEMINI_API_KEY=your_gemini_api_key_here\n")

    cfg = voice.load_config()

    assert cfg["GEMINI_API_KEY"] is None


def test_comentarios_ignorados(tmp_path, monkeypatch):
    """Lines starting with '#' are treated as comments and ignored."""
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
    _write_env(tmp_path, (
        "# This is a comment\n"
        "WHISPER_MODEL=base\n"
        "# Another comment\n"
    ))

    cfg = voice.load_config()

    assert cfg["WHISPER_MODEL"] == "base"


def test_aspas_removidas(tmp_path, monkeypatch):
    """KEY=\"value\" and KEY='value' → stored without surrounding quotes."""
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
    _write_env(tmp_path, (
        'WHISPER_MODEL="base"\n'
        'GEMINI_MODEL=\'gemini-2.5-flash\'\n'
    ))

    cfg = voice.load_config()

    assert cfg["WHISPER_MODEL"] == "base"
    assert cfg["GEMINI_MODEL"] == "gemini-2.5-flash"


def test_chave_vazia_ignorada(tmp_path, monkeypatch):
    """KEY= (empty value) does not overwrite the default for int keys."""
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
    _write_env(tmp_path, (
        "MAX_RECORD_SECONDS=\n"
        "LOG_KEEP_SESSIONS=\n"
    ))

    cfg = voice.load_config()

    # Empty value → val is "" → `if key in config and val:` is False → default kept
    assert cfg["MAX_RECORD_SECONDS"] == 600  # default atual
    assert cfg["LOG_KEEP_SESSIONS"] == 5


def test_novas_variaveis_qw4_defaults(tmp_path, monkeypatch):
    """QW-4: WHISPER_BEAM_SIZE and PASTE_DELAY_MS have correct defaults."""
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))

    cfg = voice.load_config()

    assert cfg["WHISPER_BEAM_SIZE"] == 1  # 4.6.1: default mudou para 1
    assert isinstance(cfg["WHISPER_BEAM_SIZE"], int)
    assert cfg["PASTE_DELAY_MS"] == 50
    assert isinstance(cfg["PASTE_DELAY_MS"], int)


def test_novas_variaveis_stories_defaults(tmp_path, monkeypatch):
    """Stories 4.5.3/4/5: new config vars have correct defaults."""
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))

    cfg = voice.load_config()

    assert cfg["CYCLE_HOTKEY"] == "ctrl+shift+tab"
    assert cfg["CLIPBOARD_CONTEXT_ENABLED"] is True
    assert cfg["CLIPBOARD_CONTEXT_MAX_CHARS"] == 2000
    assert cfg["HISTORY_HOTKEY"] == "ctrl+shift+h"
    assert cfg["OVERLAY_ENABLED"] is True


def test_whisper_beam_size_parseable(tmp_path, monkeypatch):
    """WHISPER_BEAM_SIZE parses correctly from .env."""
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
    _write_env(tmp_path, "WHISPER_BEAM_SIZE=3\n")

    cfg = voice.load_config()

    assert cfg["WHISPER_BEAM_SIZE"] == 3
    assert isinstance(cfg["WHISPER_BEAM_SIZE"], int)


def test_clipboard_context_max_chars_parseable(tmp_path, monkeypatch):
    """CLIPBOARD_CONTEXT_MAX_CHARS parses correctly from .env."""
    monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
    _write_env(tmp_path, "CLIPBOARD_CONTEXT_MAX_CHARS=1000\n")

    cfg = voice.load_config()

    assert cfg["CLIPBOARD_CONTEXT_MAX_CHARS"] == 1000
