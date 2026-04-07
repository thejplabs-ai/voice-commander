"""
Tests for voice/snippets.py — Epic 5.2: Expansão de texto por voz.

Strategy:
- Redirecionar state._BASE_DIR para tmp_path em cada teste.
- Testar load/save/add/remove/match de forma isolada.
- Testar integração com transcribe() via mock.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

import voice.state as state
from voice import snippets


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_config(monkeypatch):
    """Garante SNIPPETS_ENABLED=True por padrão em todos os testes."""
    cfg = dict(state._CONFIG)
    cfg["SNIPPETS_ENABLED"] = True
    monkeypatch.setattr(state, "_CONFIG", cfg)


@pytest.fixture
def base_dir(tmp_path, monkeypatch):
    """Redireciona _BASE_DIR para tmp_path."""
    monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def snippets_file(base_dir):
    """Cria um snippets.json válido com dados de teste."""
    data = {
        "assinatura": "Atenciosamente,\nJoao Pedro\nJP Labs",
        "link reuniao": "https://meet.google.com/abc-def-ghi",
        "resposta padrao": "Obrigado pelo contato. Retorno em 24h.",
    }
    path = base_dir / "snippets.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return base_dir


# ---------------------------------------------------------------------------
# load_snippets()
# ---------------------------------------------------------------------------

class TestLoadSnippets:
    def test_load_snippets_empty_returns_empty_dict(self, base_dir):
        """Sem arquivo snippets.json, retorna {}."""
        result = snippets.load_snippets()
        assert result == {}

    def test_load_snippets_valid(self, snippets_file):
        """Arquivo válido é carregado corretamente."""
        result = snippets.load_snippets()
        assert "assinatura" in result
        assert "link reuniao" in result
        assert result["assinatura"]["text"] == "Atenciosamente,\nJoao Pedro\nJP Labs"
        assert result["assinatura"]["mode"] == "replace"

    def test_load_snippets_normalizes_triggers_to_lowercase(self, base_dir):
        """Triggers são normalizados para lowercase na carga."""
        data = {"ASSINATURA": "Texto qualquer", "Link Reuniao": "https://example.com"}
        (base_dir / "snippets.json").write_text(json.dumps(data), encoding="utf-8")
        result = snippets.load_snippets()
        assert "assinatura" in result
        assert "link reuniao" in result
        assert "ASSINATURA" not in result

    def test_load_snippets_corrupt_returns_empty_dict(self, base_dir):
        """JSON inválido retorna {} sem exceção."""
        (base_dir / "snippets.json").write_text("{not valid json}", encoding="utf-8")
        result = snippets.load_snippets()
        assert result == {}

    def test_load_snippets_non_dict_returns_empty_dict(self, base_dir):
        """JSON que não é objeto (ex: lista) retorna {}."""
        (base_dir / "snippets.json").write_text('["item1", "item2"]', encoding="utf-8")
        result = snippets.load_snippets()
        assert result == {}

    def test_load_snippets_skips_non_string_values(self, base_dir):
        """Entradas com valor não-string são ignoradas silenciosamente."""
        data = {"trigger_ok": "texto valido", "trigger_bad": 42}
        (base_dir / "snippets.json").write_text(json.dumps(data), encoding="utf-8")
        result = snippets.load_snippets()
        assert "trigger_ok" in result
        assert "trigger_bad" not in result


# ---------------------------------------------------------------------------
# save_snippets()
# ---------------------------------------------------------------------------

class TestSaveSnippets:
    def test_save_snippets_creates_file(self, base_dir):
        """save_snippets cria o arquivo se não existia."""
        data = {"oi": "Olá, tudo bem?"}
        snippets.save_snippets(data)
        path = base_dir / "snippets.json"
        assert path.exists()
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["oi"] == "Olá, tudo bem?"

    def test_save_and_reload(self, base_dir):
        """save_snippets + load_snippets retornam os mesmos dados."""
        data = {"chave": {"text": "valor", "mode": "replace"}, "outra chave": {"text": "outro valor", "mode": "inline"}}
        snippets.save_snippets(data)
        result = snippets.load_snippets()
        assert result == data

    def test_save_atomic_no_tmp_leftover(self, base_dir):
        """Após save bem-sucedido, não deve existir arquivo .tmp."""
        snippets.save_snippets({"x": "y"})
        tmp = base_dir / "snippets.json.tmp"
        assert not tmp.exists()

    def test_save_utf8_encoding(self, base_dir):
        """Caracteres especiais são salvos corretamente em UTF-8."""
        data = {"saudação": "Olá, João! Ação concluída com êxito."}
        snippets.save_snippets(data)
        result = snippets.load_snippets()
        assert result["saudação"]["text"] == "Olá, João! Ação concluída com êxito."


# ---------------------------------------------------------------------------
# add_snippet()
# ---------------------------------------------------------------------------

class TestAddSnippet:
    def test_add_snippet_creates_new_entry(self, base_dir):
        """add_snippet adiciona nova entrada."""
        snippets.add_snippet("meu trigger", "meu texto expandido")
        result = snippets.load_snippets()
        assert result["meu trigger"]["text"] == "meu texto expandido"
        assert result["meu trigger"]["mode"] == "replace"

    def test_add_snippet_normalizes_trigger_lowercase(self, base_dir):
        """Trigger é normalizado para lowercase ao adicionar."""
        snippets.add_snippet("MEU TRIGGER", "texto")
        result = snippets.load_snippets()
        assert "meu trigger" in result
        assert "MEU TRIGGER" not in result

    def test_add_snippet_overwrites_existing(self, base_dir):
        """add_snippet atualiza snippet existente sem duplicar."""
        snippets.add_snippet("trigger", "texto original")
        snippets.add_snippet("trigger", "texto atualizado")
        result = snippets.load_snippets()
        assert result["trigger"]["text"] == "texto atualizado"
        assert len(result) == 1

    def test_add_snippet_preserves_existing_entries(self, snippets_file):
        """Adicionar novo snippet não apaga os existentes."""
        snippets.add_snippet("novo", "novo texto")
        result = snippets.load_snippets()
        assert "assinatura" in result
        assert "novo" in result


# ---------------------------------------------------------------------------
# remove_snippet()
# ---------------------------------------------------------------------------

class TestRemoveSnippet:
    def test_remove_snippet_returns_true_when_exists(self, base_dir):
        """remove_snippet retorna True se o snippet existia."""
        snippets.add_snippet("para remover", "texto")
        result = snippets.remove_snippet("para remover")
        assert result is True

    def test_remove_snippet_actually_removes_entry(self, base_dir):
        """Após remoção, o trigger não existe mais no arquivo."""
        snippets.add_snippet("para remover", "texto")
        snippets.remove_snippet("para remover")
        remaining = snippets.load_snippets()
        assert "para remover" not in remaining

    def test_remove_snippet_returns_false_when_missing(self, base_dir):
        """remove_snippet retorna False se o trigger não existe."""
        result = snippets.remove_snippet("nao existe")
        assert result is False

    def test_remove_snippet_case_insensitive(self, base_dir):
        """Remoção funciona independente de case no trigger."""
        snippets.add_snippet("meu trigger", "texto")
        result = snippets.remove_snippet("MEU TRIGGER")
        assert result is True
        assert snippets.load_snippets() == {}


# ---------------------------------------------------------------------------
# get_snippets()
# ---------------------------------------------------------------------------

class TestGetSnippets:
    def test_get_snippets_returns_all(self, snippets_file):
        """get_snippets retorna todos os snippets."""
        result = snippets.get_snippets()
        assert len(result) == 3
        assert "assinatura" in result

    def test_get_snippets_empty(self, base_dir):
        """get_snippets retorna {} quando nenhum snippet cadastrado."""
        result = snippets.get_snippets()
        assert result == {}


# ---------------------------------------------------------------------------
# match_snippet()
# ---------------------------------------------------------------------------

class TestMatchSnippet:
    def test_match_exact_case_insensitive(self, snippets_file):
        """Match exato funciona independente de maiúsculas/minúsculas."""
        result = snippets.match_snippet("Assinatura")
        assert result == "Atenciosamente,\nJoao Pedro\nJP Labs"

    def test_match_exact_with_extra_spaces(self, snippets_file):
        """Match exato funciona com espaços no início/fim."""
        result = snippets.match_snippet("  assinatura  ")
        assert result == "Atenciosamente,\nJoao Pedro\nJP Labs"

    def test_match_exact_multi_word(self, snippets_file):
        """Match exato com trigger de múltiplas palavras."""
        result = snippets.match_snippet("link reuniao")
        assert result == "https://meet.google.com/abc-def-ghi"

    def test_match_partial_start(self, snippets_file):
        """Texto que começa com trigger retorna expansão."""
        result = snippets.match_snippet("assinatura por favor")
        assert result == "Atenciosamente,\nJoao Pedro\nJP Labs"

    def test_match_partial_end(self, snippets_file):
        """Texto que termina com trigger retorna expansão."""
        result = snippets.match_snippet("preciso da assinatura")
        assert result == "Atenciosamente,\nJoao Pedro\nJP Labs"

    def test_match_exact_takes_priority_over_partial(self, base_dir):
        """Match exato tem prioridade sobre match parcial."""
        snippets.save_snippets({
            "ok": "resultado exato",
            "ok agora": "resultado parcial",
        })
        # "ok" corresponde exatamente antes de checar parcial
        result = snippets.match_snippet("ok")
        assert result == "resultado exato"

    def test_match_none_when_no_match(self, snippets_file):
        """Sem match retorna None."""
        result = snippets.match_snippet("texto completamente diferente sem nenhum trigger")
        assert result is None

    def test_match_none_when_empty_text(self, snippets_file):
        """Texto vazio retorna None."""
        result = snippets.match_snippet("")
        assert result is None

    def test_match_none_when_only_spaces(self, snippets_file):
        """Texto com apenas espaços retorna None."""
        result = snippets.match_snippet("   ")
        assert result is None

    def test_match_none_when_no_snippets(self, base_dir):
        """Sem snippets cadastrados, retorna None."""
        result = snippets.match_snippet("assinatura")
        assert result is None


# ---------------------------------------------------------------------------
# SNIPPETS_ENABLED = false
# ---------------------------------------------------------------------------

class TestSnippetsDisabled:
    def test_match_returns_none_when_disabled(self, snippets_file, monkeypatch):
        """match_snippet retorna None quando SNIPPETS_ENABLED=False."""
        cfg = dict(state._CONFIG)
        cfg["SNIPPETS_ENABLED"] = False
        monkeypatch.setattr(state, "_CONFIG", cfg)
        result = snippets.match_snippet("assinatura")
        assert result is None

    def test_load_save_still_work_when_disabled(self, base_dir, monkeypatch):
        """load/save/add continuam funcionando independente de SNIPPETS_ENABLED."""
        cfg = dict(state._CONFIG)
        cfg["SNIPPETS_ENABLED"] = False
        monkeypatch.setattr(state, "_CONFIG", cfg)
        snippets.add_snippet("x", "y")
        result = snippets.load_snippets()
        assert result["x"]["text"] == "y"
        assert result["x"]["mode"] == "replace"


# ---------------------------------------------------------------------------
# Integration: transcribe() snippet path
# ---------------------------------------------------------------------------

class TestSnippetIntegrationAudio:
    """Testa o fluxo snippet dentro de transcribe() via mocks."""

    def _make_tmp_mock(self, fake_path: str = "/tmp/fake.wav") -> MagicMock:
        """Cria mock de NamedTemporaryFile que funciona como context manager."""
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=MagicMock(name=fake_path))
        cm.__enter__.return_value.name = fake_path
        cm.__exit__ = MagicMock(return_value=False)
        factory = MagicMock(return_value=cm)
        return factory

    def test_snippet_match_bypasses_ai(self, base_dir, monkeypatch):
        """Quando snippet faz match, AI não é chamada."""
        from voice import audio

        # Snippet cadastrado
        snippets.save_snippets({"assinatura": "Texto de assinatura completa"})

        mock_frames = [MagicMock()]

        # Patch _do_transcription para retornar "assinatura"
        monkeypatch.setattr(audio, "_do_transcription", lambda *a, **kw: "assinatura")

        mock_copy = MagicMock()
        mock_paste = MagicMock()
        mock_play = MagicMock()
        mock_append = MagicMock()
        mock_tray = MagicMock()

        monkeypatch.setattr(audio, "copy_to_clipboard", mock_copy)
        monkeypatch.setattr(audio, "paste_via_sendinput", mock_paste)
        monkeypatch.setattr(audio, "play_sound", mock_play)
        monkeypatch.setattr(audio, "_append_history", mock_append)
        monkeypatch.setattr(audio, "_update_tray_state", mock_tray)

        monkeypatch.setattr(state, "_CONFIG", {
            "SNIPPETS_ENABLED": True,
            "STT_PROVIDER": "whisper",
            "PASTE_DELAY_MS": 0,
            "SOUND_SUCCESS": "",
            "OVERLAY_ENABLED": False,
            "DEBUG_PERF": False,
            "CLIPBOARD_CONTEXT_ENABLED": False,
        })

        mock_ai = MagicMock(side_effect=AssertionError("AI não deve ser chamada para snippet"))

        with patch("voice.audio.tempfile.NamedTemporaryFile", self._make_tmp_mock()), \
             patch("voice.audio.wave.open"), \
             patch("voice.audio.os.unlink"), \
             patch("voice.audio.ai_provider.process", mock_ai):
            audio.transcribe(mock_frames, mode="transcribe")

        mock_copy.assert_called_once_with("Texto de assinatura completa")
        mock_paste.assert_called_once()
        mock_append.assert_called_once()
        call_args = mock_append.call_args
        assert call_args[0][2] == "Texto de assinatura completa"

    def test_no_snippet_match_calls_ai(self, base_dir, monkeypatch):
        """Quando não há snippet, o fluxo normal (AI) é executado."""
        from voice import audio

        # Sem snippets cadastrados
        (base_dir / "snippets.json").unlink(missing_ok=True)

        mock_frames = [MagicMock()]

        monkeypatch.setattr(audio, "_do_transcription", lambda *a, **kw: "hello world")

        mock_copy = MagicMock()
        mock_paste = MagicMock()
        mock_play = MagicMock()
        mock_append = MagicMock()
        mock_tray = MagicMock()
        mock_ai = MagicMock(return_value="hello world processado")

        monkeypatch.setattr(audio, "copy_to_clipboard", mock_copy)
        monkeypatch.setattr(audio, "paste_via_sendinput", mock_paste)
        monkeypatch.setattr(audio, "play_sound", mock_play)
        monkeypatch.setattr(audio, "_append_history", mock_append)
        monkeypatch.setattr(audio, "_update_tray_state", mock_tray)

        monkeypatch.setattr(state, "_CONFIG", {
            "SNIPPETS_ENABLED": True,
            "STT_PROVIDER": "whisper",
            "PASTE_DELAY_MS": 0,
            "SOUND_SUCCESS": "",
            "SOUND_ERROR": "",
            "OVERLAY_ENABLED": False,
            "DEBUG_PERF": False,
            "CLIPBOARD_CONTEXT_ENABLED": False,
            "GEMINI_MODEL": "gemini-2.5-flash",
        })

        with patch("voice.audio.tempfile.NamedTemporaryFile", self._make_tmp_mock()), \
             patch("voice.audio.wave.open"), \
             patch("voice.audio.os.unlink"), \
             patch("voice.audio.ai_provider.process", mock_ai):
            audio.transcribe(mock_frames, mode="transcribe")

        mock_ai.assert_called_once()
