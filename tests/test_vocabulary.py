# tests/test_vocabulary.py — Unit tests for voice/vocabulary.py
import json


import voice.state as state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_vocab(tmp_path, data: dict) -> None:
    """Write a vocabulary JSON file to tmp_path."""
    path = tmp_path / "custom_vocabulary.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _read_vocab(tmp_path) -> dict:
    """Read vocabulary JSON from tmp_path."""
    path = tmp_path / "custom_vocabulary.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLoadVocabulary:
    def test_load_vocabulary_empty(self, tmp_path, monkeypatch):
        """Arquivo não existe -> retorna estrutura vazia."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        from voice import vocabulary
        result = vocabulary.load_vocabulary()

        assert result == {"words": [], "updated": ""}

    def test_load_vocabulary_valid(self, tmp_path, monkeypatch):
        """Arquivo válido -> retorna conteúdo."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        data = {"words": ["JP Labs", "OpenRouter"], "updated": "2026-04-06T10:00:00"}
        _write_vocab(tmp_path, data)

        from voice import vocabulary
        result = vocabulary.load_vocabulary()

        assert result["words"] == ["JP Labs", "OpenRouter"]
        assert result["updated"] == "2026-04-06T10:00:00"

    def test_load_vocabulary_corrupt(self, tmp_path, monkeypatch):
        """JSON inválido -> retorna fallback vazio."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        path = tmp_path / "custom_vocabulary.json"
        path.write_text("{ invalid json !!!", encoding="utf-8")

        from voice import vocabulary
        result = vocabulary.load_vocabulary()

        assert result == {"words": [], "updated": ""}

    def test_load_vocabulary_wrong_structure(self, tmp_path, monkeypatch):
        """JSON válido mas estrutura errada -> fallback vazio."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        path = tmp_path / "custom_vocabulary.json"
        path.write_text('["not", "a", "dict"]', encoding="utf-8")

        from voice import vocabulary
        result = vocabulary.load_vocabulary()

        assert result == {"words": [], "updated": ""}


class TestSaveVocabulary:
    def test_save_vocabulary(self, tmp_path, monkeypatch):
        """Salva e recarrega corretamente."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        from voice import vocabulary

        vocab = {"words": ["Supabase", "pywebview"], "updated": "2026-04-06T12:00:00"}
        vocabulary.save_vocabulary(vocab)

        result = _read_vocab(tmp_path)
        assert result["words"] == ["Supabase", "pywebview"]
        assert result["updated"] == "2026-04-06T12:00:00"

    def test_save_vocabulary_no_tmp_left(self, tmp_path, monkeypatch):
        """Arquivo .tmp não deve sobrar após save."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        from voice import vocabulary

        vocabulary.save_vocabulary({"words": [], "updated": ""})

        tmp_file = tmp_path / "custom_vocabulary.json.tmp"
        assert not tmp_file.exists()

    def test_save_vocabulary_utf8(self, tmp_path, monkeypatch):
        """Salva caracteres não-ASCII corretamente."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        from voice import vocabulary

        vocabulary.save_vocabulary({"words": ["João", "Caiçara"], "updated": ""})
        result = _read_vocab(tmp_path)

        assert "João" in result["words"]
        assert "Caiçara" in result["words"]


class TestAddWord:
    def test_add_word(self, tmp_path, monkeypatch):
        """Adiciona palavra nova corretamente."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        from voice import vocabulary

        added = vocabulary.add_word("Supabase")

        assert added is True
        assert "Supabase" in vocabulary.get_words()

    def test_add_word_duplicate(self, tmp_path, monkeypatch):
        """Não duplica palavra já existente."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        from voice import vocabulary

        vocabulary.add_word("Supabase")
        added_again = vocabulary.add_word("Supabase")

        assert added_again is False
        words = vocabulary.get_words()
        assert words.count("Supabase") == 1

    def test_add_word_empty_string(self, tmp_path, monkeypatch):
        """Palavra vazia não é adicionada."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        from voice import vocabulary

        added = vocabulary.add_word("   ")
        assert added is False

    def test_add_word_updates_timestamp(self, tmp_path, monkeypatch):
        """add_word atualiza o campo updated."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        from voice import vocabulary

        vocabulary.add_word("OpenRouter")
        vocab = vocabulary.load_vocabulary()

        assert vocab["updated"] != ""


class TestRemoveWord:
    def test_remove_word(self, tmp_path, monkeypatch):
        """Remove palavra existente."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        from voice import vocabulary

        vocabulary.add_word("Supabase")
        removed = vocabulary.remove_word("Supabase")

        assert removed is True
        assert "Supabase" not in vocabulary.get_words()

    def test_remove_word_missing(self, tmp_path, monkeypatch):
        """Retorna False para palavra inexistente."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        from voice import vocabulary

        removed = vocabulary.remove_word("NaoExiste")
        assert removed is False


class TestGetHotwordsString:
    def test_get_hotwords_string_includes_base(self, tmp_path, monkeypatch):
        """Inclui os _BASE_HOTWORDS mesmo sem palavras custom."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        from voice import vocabulary

        result = vocabulary.get_hotwords_string()

        assert "deploy" in result
        assert "pipeline" in result
        assert "API" in result

    def test_get_hotwords_string_includes_custom(self, tmp_path, monkeypatch):
        """Inclui palavras custom além dos base hotwords."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        from voice import vocabulary

        vocabulary.add_word("JP Labs")
        vocabulary.add_word("pywebview")
        result = vocabulary.get_hotwords_string()

        assert "deploy" in result
        assert "JP Labs" in result
        assert "pywebview" in result

    def test_get_hotwords_string_no_custom(self, tmp_path, monkeypatch):
        """Sem palavras custom, retorna apenas base hotwords."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        from voice import vocabulary

        result = vocabulary.get_hotwords_string()

        from voice.vocabulary import _BASE_HOTWORDS
        assert result == _BASE_HOTWORDS


class TestGetInitialPromptSuffix:
    def test_get_initial_prompt_suffix_empty(self, tmp_path, monkeypatch):
        """Sem palavras custom, retorna string vazia."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        from voice import vocabulary

        result = vocabulary.get_initial_prompt_suffix()
        assert result == ""

    def test_get_initial_prompt_suffix_format(self, tmp_path, monkeypatch):
        """Formato correto: ', palavra1, palavra2'."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        from voice import vocabulary

        vocabulary.add_word("JP Labs")
        vocabulary.add_word("OpenRouter")
        result = vocabulary.get_initial_prompt_suffix()

        assert result.startswith(", ")
        assert "JP Labs" in result
        assert "OpenRouter" in result


class TestLearnFromCorrection:
    def test_learn_from_correction(self, tmp_path, monkeypatch):
        """Extrai nomes próprios corrigidos que não estavam no raw."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        from voice import vocabulary

        raw = "o supabase e o openrouter estao funcionando"
        corrected = "o Supabase e o OpenRouter estão funcionando"

        candidates = vocabulary.learn_from_correction(raw, corrected)

        assert "Supabase" in candidates or "OpenRouter" in candidates

    def test_learn_from_correction_no_diff(self, tmp_path, monkeypatch):
        """Sem diferença entre raw e corrigido -> lista vazia."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        from voice import vocabulary

        text = "faz o deploy do pipeline"
        candidates = vocabulary.learn_from_correction(text, text)

        assert candidates == []

    def test_learn_from_correction_empty_inputs(self, tmp_path, monkeypatch):
        """Inputs vazios -> lista vazia."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        from voice import vocabulary

        assert vocabulary.learn_from_correction("", "") == []
        assert vocabulary.learn_from_correction("algo", "") == []
        assert vocabulary.learn_from_correction("", "algo") == []

    def test_learn_from_correction_no_duplicates(self, tmp_path, monkeypatch):
        """Palavras já no vocabulário não são retornadas como candidatas."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        from voice import vocabulary

        vocabulary.add_word("Supabase")
        raw = "o supabase"
        corrected = "o Supabase"

        candidates = vocabulary.learn_from_correction(raw, corrected)
        assert "Supabase" not in candidates

    def test_learn_from_correction_ignores_base_hotwords(self, tmp_path, monkeypatch):
        """Termos já nos base hotwords não são retornados como candidatos."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": True})

        from voice import vocabulary

        raw = "faz o deploy"
        corrected = "faz o Deploy"

        candidates = vocabulary.learn_from_correction(raw, corrected)
        # "Deploy" é variante de "deploy" que já está nos base hotwords
        assert "Deploy" not in candidates


class TestVocabularyDisabled:
    def test_vocabulary_disabled_add_returns_false(self, tmp_path, monkeypatch):
        """VOCABULARY_ENABLED=false: add_word retorna False."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": False})

        from voice import vocabulary

        result = vocabulary.add_word("Supabase")
        assert result is False

    def test_vocabulary_disabled_remove_returns_false(self, tmp_path, monkeypatch):
        """VOCABULARY_ENABLED=false: remove_word retorna False."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": False})

        from voice import vocabulary

        result = vocabulary.remove_word("Qualquer")
        assert result is False

    def test_vocabulary_disabled_get_words_empty(self, tmp_path, monkeypatch):
        """VOCABULARY_ENABLED=false: get_words retorna lista vazia."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": False})

        from voice import vocabulary

        result = vocabulary.get_words()
        assert result == []

    def test_vocabulary_disabled_hotwords_returns_base(self, tmp_path, monkeypatch):
        """VOCABULARY_ENABLED=false: get_hotwords_string retorna apenas base."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": False})

        from voice import vocabulary

        result = vocabulary.get_hotwords_string()
        from voice.vocabulary import _BASE_HOTWORDS
        assert result == _BASE_HOTWORDS

    def test_vocabulary_disabled_initial_prompt_suffix_empty(self, tmp_path, monkeypatch):
        """VOCABULARY_ENABLED=false: get_initial_prompt_suffix retorna ''."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": False})

        from voice import vocabulary

        result = vocabulary.get_initial_prompt_suffix()
        assert result == ""

    def test_vocabulary_disabled_learn_returns_empty(self, tmp_path, monkeypatch):
        """VOCABULARY_ENABLED=false: learn_from_correction retorna []."""
        monkeypatch.setattr(state, "_BASE_DIR", str(tmp_path))
        monkeypatch.setattr(state, "_CONFIG", {"VOCABULARY_ENABLED": False})

        from voice import vocabulary

        candidates = vocabulary.learn_from_correction("raw text", "Corrected Text")
        assert candidates == []
