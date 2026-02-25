"""
Tests for _append_history() — writes to history.jsonl.
Uses tmp_base_dir fixture to isolate file I/O in a temp directory.
"""
import json

import pytest

import voice


def test_append_cria_arquivo(tmp_base_dir, mock_config):
    """First _append_history call creates history.jsonl."""
    history_file = tmp_base_dir / "history.jsonl"
    assert not history_file.exists()

    voice._append_history(
        mode="transcribe",
        raw_text="hello",
        processed_text="Hello.",
        duration_seconds=1.5,
    )

    assert history_file.exists()


def test_entry_campos_corretos(tmp_base_dir, mock_config):
    """Written JSON entry contains all required fields with correct types."""
    voice._append_history(
        mode="prompt",
        raw_text="raw text",
        processed_text="Processed text.",
        duration_seconds=2.34,
    )

    history_file = tmp_base_dir / "history.jsonl"
    line = history_file.read_text(encoding="utf-8").strip()
    entry = json.loads(line)

    assert "timestamp" in entry
    assert entry["mode"] == "prompt"
    assert entry["raw_text"] == "raw text"
    assert entry["processed_text"] == "Processed text."
    assert entry["duration_seconds"] == 2.34
    assert entry["chars"] == len("Processed text.")
    # No error field when error=False
    assert "error" not in entry


def test_entry_com_erro(tmp_base_dir, mock_config):
    """When error=True, entry has 'error': true and processed_text: null."""
    voice._append_history(
        mode="transcribe",
        raw_text="garbled audio",
        processed_text=None,
        duration_seconds=0.5,
        error=True,
    )

    history_file = tmp_base_dir / "history.jsonl"
    line = history_file.read_text(encoding="utf-8").strip()
    entry = json.loads(line)

    assert entry["error"] is True
    assert entry["processed_text"] is None
    assert entry["chars"] == 0


def test_encoding_utf8(tmp_base_dir, mock_config):
    """Portuguese text with accents is saved and read back correctly."""
    texto = "Transcrição com acentuação: ção, não, Ação, ômega"
    voice._append_history(
        mode="transcribe",
        raw_text=texto,
        processed_text=texto,
        duration_seconds=3.0,
    )

    history_file = tmp_base_dir / "history.jsonl"
    line = history_file.read_text(encoding="utf-8").strip()
    entry = json.loads(line)

    assert entry["raw_text"] == texto
    assert entry["processed_text"] == texto


def test_trim_mantém_max_entries(tmp_base_dir, mock_config):
    """After exceeding HISTORY_MAX_ENTRIES, only the most recent N entries remain."""
    max_entries = 5
    mock_config["HISTORY_MAX_ENTRIES"] = max_entries

    # Write max+5 entries (10 total)
    total = max_entries + 5
    for i in range(total):
        voice._append_history(
            mode="transcribe",
            raw_text=f"text_{i}",
            processed_text=f"processed_{i}",
            duration_seconds=float(i),
        )

    history_file = tmp_base_dir / "history.jsonl"
    lines = history_file.read_text(encoding="utf-8").strip().splitlines()

    assert len(lines) == max_entries

    # Verify that only the MOST RECENT entries are kept (last 5 of 10 → indices 5..9)
    last_entry = json.loads(lines[-1])
    assert last_entry["raw_text"] == f"text_{total - 1}"
