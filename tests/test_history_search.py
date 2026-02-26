"""
Tests for voice/history_search.py — _load_history, _search_entries, _format_entry.

UI tests (CTk window) são impossíveis sem display — fora de escopo.
Testar apenas a lógica de dados.
"""

import json

import pytest

from voice import state
from voice.history_search import _load_history, _search_entries, _format_entry


@pytest.fixture(autouse=True)
def setup_state(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
    monkeypatch.setattr(state, "_history_path", str(tmp_path / "history.jsonl"))
    monkeypatch.setattr(state, "_ctk_available", False)


def _write_history(tmp_path, entries: list[dict]) -> None:
    path = tmp_path / "history.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# _load_history()
# ---------------------------------------------------------------------------


class TestLoadHistory:
    def test_retorna_vazio_sem_arquivo(self):
        """_load_history() returns empty list when file doesn't exist."""
        result = _load_history()
        assert result == []

    def test_carrega_entradas(self, tmp_path):
        """_load_history() loads entries from history.jsonl."""
        entries = [
            {"timestamp": "2026-01-01T10:00:00", "mode": "transcribe",
             "raw_text": "Olá", "processed_text": "Olá mundo", "duration_seconds": 1.5, "chars": 10},
            {"timestamp": "2026-01-01T10:01:00", "mode": "query",
             "raw_text": "query aqui", "processed_text": "resposta", "duration_seconds": 2.0, "chars": 8},
        ]
        _write_history(tmp_path, entries)

        result = _load_history()

        assert len(result) == 2

    def test_retorna_mais_recente_primeiro(self, tmp_path):
        """_load_history() returns entries in reverse order (most recent first)."""
        entries = [
            {"timestamp": "2026-01-01T10:00:00", "mode": "transcribe",
             "raw_text": "primeiro", "processed_text": "primeiro", "duration_seconds": 1.0, "chars": 8},
            {"timestamp": "2026-01-01T11:00:00", "mode": "transcribe",
             "raw_text": "segundo", "processed_text": "segundo", "duration_seconds": 1.0, "chars": 7},
        ]
        _write_history(tmp_path, entries)

        result = _load_history()

        assert result[0]["raw_text"] == "segundo"
        assert result[1]["raw_text"] == "primeiro"

    def test_ignora_linhas_invalidas(self, tmp_path):
        """_load_history() skips malformed JSON lines gracefully."""
        path = tmp_path / "history.jsonl"
        path.write_text(
            '{"timestamp": "2026-01-01", "mode": "transcribe", "raw_text": "ok", "processed_text": "ok", "duration_seconds": 1.0, "chars": 2}\n'
            'LINHA INVÁLIDA\n'
            '{"timestamp": "2026-01-02", "mode": "query", "raw_text": "q", "processed_text": "r", "duration_seconds": 2.0, "chars": 1}\n',
            encoding="utf-8"
        )

        result = _load_history()

        assert len(result) == 2


# ---------------------------------------------------------------------------
# _search_entries()
# ---------------------------------------------------------------------------

class TestSearchEntries:
    @pytest.fixture
    def sample_entries(self):
        return [
            {"raw_text": "deploy no servidor", "processed_text": "Fazer deploy no servidor de produção"},
            {"raw_text": "bug no frontend", "processed_text": "Corrigir bug na tela de login"},
            {"raw_text": "reunião amanhã", "processed_text": None},
            {"raw_text": "", "processed_text": ""},
        ]

    def test_query_vazia_retorna_todas(self, sample_entries):
        """Empty query returns all entries."""
        result = _search_entries(sample_entries, "")
        assert result == sample_entries

    def test_query_espaco_retorna_todas(self, sample_entries):
        """Whitespace-only query returns all entries."""
        result = _search_entries(sample_entries, "   ")
        assert result == sample_entries

    def test_busca_em_raw_text(self, sample_entries):
        """Finds entries matching raw_text."""
        result = _search_entries(sample_entries, "deploy")
        assert len(result) == 1
        assert "deploy" in result[0]["raw_text"]

    def test_busca_em_processed_text(self, sample_entries):
        """Finds entries matching processed_text."""
        result = _search_entries(sample_entries, "login")
        assert len(result) == 1
        assert "login" in result[0]["processed_text"]

    def test_busca_case_insensitive(self, sample_entries):
        """Search is case-insensitive."""
        result = _search_entries(sample_entries, "DEPLOY")
        assert len(result) == 1

    def test_sem_resultado(self, sample_entries):
        """Query with no match returns empty list."""
        result = _search_entries(sample_entries, "xyz_inexistente_12345")
        assert result == []

    def test_processed_text_none_nao_levanta(self, sample_entries):
        """Entries with processed_text=None don't raise errors."""
        result = _search_entries(sample_entries, "reunião")
        assert len(result) == 1

    def test_ambos_raw_e_processed(self, sample_entries):
        """Query matching both raw_text and processed_text — entry included once."""
        result = _search_entries(sample_entries, "bug")
        assert len(result) == 1  # not duplicated


# ---------------------------------------------------------------------------
# _format_entry()
# ---------------------------------------------------------------------------

class TestFormatEntry:
    def test_formato_basico(self):
        """_format_entry() includes timestamp, mode and text preview."""
        entry = {
            "timestamp": "2026-02-26T14:30:00",
            "mode": "transcribe",
            "processed_text": "Texto processado aqui",
            "raw_text": "texto raw",
        }
        result = _format_entry(entry)

        assert "2026-02-26" in result
        assert "14:30" in result
        assert "transcribe" in result
        assert "Texto processado" in result

    def test_trunca_texto_longo(self):
        """_format_entry() truncates text at 80 chars with ellipsis."""
        entry = {
            "timestamp": "2026-01-01T00:00:00",
            "mode": "query",
            "processed_text": "A" * 150,
            "raw_text": "",
        }
        result = _format_entry(entry)

        assert "..." in result
        # The preview part should not exceed 80 chars + "..."
        preview_part = result.split("] [query] ")[1] if "] [query] " in result else result
        assert len(preview_part) <= 83  # 80 + "..."

    def test_usa_raw_text_se_processed_none(self):
        """_format_entry() falls back to raw_text when processed_text is None."""
        entry = {
            "timestamp": "2026-01-01T00:00:00",
            "mode": "transcribe",
            "processed_text": None,
            "raw_text": "raw text aqui",
        }
        result = _format_entry(entry)

        assert "raw text aqui" in result

    def test_sem_crash_sem_texto(self):
        """_format_entry() doesn't crash when both texts are empty."""
        entry = {
            "timestamp": "2026-01-01T00:00:00",
            "mode": "transcribe",
            "processed_text": "",
            "raw_text": "",
        }
        result = _format_entry(entry)
        assert isinstance(result, str)
