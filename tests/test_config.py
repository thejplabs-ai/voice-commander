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

    assert cfg["CYCLE_HOTKEY"] == "ctrl+alt+m"
    assert cfg["CLIPBOARD_CONTEXT_ENABLED"] is True
    assert cfg["CLIPBOARD_CONTEXT_MAX_CHARS"] == 2000
    assert cfg["HISTORY_HOTKEY"] == "ctrl+alt+h"
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


class TestLegacyHotkeyMigration:
    """W3: CYCLE_HOTKEY/HISTORY_HOTKEY defaults changed (collided with browser/VS Code
    shortcuts once W2 made hotkeys Win32-exclusive). Users with the old value saved in
    .env get migrated in-memory on every load — no I/O side effect, no versioning
    framework, just the two exact-match checks."""

    def test_migrates_legacy_cycle_hotkey(self, tmp_path, monkeypatch):
        monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
        _write_env(tmp_path, "CYCLE_HOTKEY=ctrl+shift+tab\n")

        cfg = voice.load_config()

        assert cfg["CYCLE_HOTKEY"] == "ctrl+alt+m"

    def test_migrates_legacy_history_hotkey(self, tmp_path, monkeypatch):
        monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
        _write_env(tmp_path, "HISTORY_HOTKEY=ctrl+shift+h\n")

        cfg = voice.load_config()

        assert cfg["HISTORY_HOTKEY"] == "ctrl+alt+h"

    def test_preserves_custom_cycle_hotkey(self, tmp_path, monkeypatch):
        monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
        _write_env(tmp_path, "CYCLE_HOTKEY=ctrl+shift+f9\n")

        cfg = voice.load_config()

        assert cfg["CYCLE_HOTKEY"] == "ctrl+shift+f9"

    def test_preserves_custom_history_hotkey(self, tmp_path, monkeypatch):
        monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
        _write_env(tmp_path, "HISTORY_HOTKEY=alt+f2\n")

        cfg = voice.load_config()

        assert cfg["HISTORY_HOTKEY"] == "alt+f2"

    def test_cross_key_value_not_migrated(self, tmp_path, monkeypatch):
        """CYCLE_HOTKEY=ctrl+shift+h is a custom value for THIS key (the legacy
        default for HISTORY_HOTKEY, not CYCLE_HOTKEY) — must not be touched."""
        monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
        _write_env(tmp_path, "CYCLE_HOTKEY=ctrl+shift+h\n")

        cfg = voice.load_config()

        assert cfg["CYCLE_HOTKEY"] == "ctrl+shift+h"

    def test_new_values_pass_through_unchanged(self, tmp_path, monkeypatch):
        monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
        _write_env(tmp_path, "CYCLE_HOTKEY=ctrl+alt+m\nHISTORY_HOTKEY=ctrl+alt+h\n")

        cfg = voice.load_config()

        assert cfg["CYCLE_HOTKEY"] == "ctrl+alt+m"
        assert cfg["HISTORY_HOTKEY"] == "ctrl+alt+h"

    def test_missing_keys_get_new_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
        env_path = tmp_path / ".env"
        assert not env_path.exists()

        cfg = voice.load_config()

        assert cfg["CYCLE_HOTKEY"] == "ctrl+alt+m"
        assert cfg["HISTORY_HOTKEY"] == "ctrl+alt+h"

    def test_migration_does_not_write_env_file(self, tmp_path, monkeypatch):
        """load_config() migrates in-memory only — no I/O side effect on .env."""
        monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
        content = "CYCLE_HOTKEY=ctrl+shift+tab\n"
        _write_env(tmp_path, content)

        voice.load_config()

        assert (tmp_path / ".env").read_text(encoding="utf-8") == content

    def test_migration_logs_info_line(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
        _write_env(tmp_path, "CYCLE_HOTKEY=ctrl+shift+tab\n")

        voice.load_config()

        out = capsys.readouterr().out
        assert "[INFO]" in out
        assert "CYCLE_HOTKEY" in out


class TestReloadConfigSelectedMode:
    """W3 Task 2 — _reload_config() must not clobber an in-memory cycled mode
    when the persisted SELECTED_MODE didn't actually change between reloads.
    """

    def test_preserves_cycled_mode_when_persisted_value_unchanged(self, tmp_path, monkeypatch):
        """User cycled to 'email' in memory while .env still says transcribe
        (e.g. cycled, then opened Settings and saved an unrelated field) —
        reload must not revert the in-memory mode back to transcribe."""
        monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
        _write_env(tmp_path, "SELECTED_MODE=transcribe\n")
        monkeypatch.setattr(voice.state, "_CONFIG", {"SELECTED_MODE": "transcribe"})
        monkeypatch.setattr(voice.state, "selected_mode", "email")

        voice._reload_config()

        assert voice.state.selected_mode == "email"

    def test_applies_new_persisted_mode_when_env_changed(self, tmp_path, monkeypatch):
        """.env SELECTED_MODE genuinely changed (manual edit or deliberate
        selection saved right before reload) — the new value must apply."""
        monkeypatch.setattr(voice.state, "_BASE_DIR", str(tmp_path))
        _write_env(tmp_path, "SELECTED_MODE=query\n")
        monkeypatch.setattr(voice.state, "_CONFIG", {"SELECTED_MODE": "transcribe"})
        monkeypatch.setattr(voice.state, "selected_mode", "transcribe")

        voice._reload_config()

        assert voice.state.selected_mode == "query"
