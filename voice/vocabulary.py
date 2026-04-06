# voice/vocabulary.py — Custom vocabulary for Whisper hotwords and initial_prompt injection
# Persists user-specific terms (proper nouns, project names, technical jargon) to
# custom_vocabulary.json in _BASE_DIR. Improves transcription accuracy over time.

import json
import os
import re
from datetime import datetime

from voice import state

# Base hotwords that are always included (sourced from audio.py)
_BASE_HOTWORDS = (
    "deploy, build, pipeline, debounce, commit, branch, merge, "
    "webhook, script, frontend, backend, API, token, workflow, "
    "debug, SOP, prompt, buffer, cache, endpoint, payload, query"
)

# Regex: words that look like proper nouns or technical terms worth learning.
# Matches: CamelCase, ALL_CAPS (>=2), or Title-case words that differ from raw.
_PROPER_NOUN_RE = re.compile(r'\b([A-Z][a-z]{1,}(?:[A-Z][a-z]*)+|[A-Z]{2,}|[A-Z][a-z]+[A-Z][a-zA-Z]*)\b')


def _vocab_path() -> str:
    return os.path.join(state._BASE_DIR, "custom_vocabulary.json")


def _is_enabled() -> bool:
    return bool(state._CONFIG.get("VOCABULARY_ENABLED", True))


def load_vocabulary() -> dict:
    """Carrega custom_vocabulary.json. Retorna {"words": [], "updated": ""} se não existe ou inválido."""
    path = _vocab_path()
    if not os.path.exists(path):
        return {"words": [], "updated": ""}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("not a dict")
        if not isinstance(data.get("words"), list):
            raise ValueError("words not a list")
        return data
    except Exception as e:
        print(f"[WARN] vocabulary.json inválido ({e}), usando vazio")
        return {"words": [], "updated": ""}


def save_vocabulary(vocab: dict) -> None:
    """Salva custom_vocabulary.json atomicamente (escreve .tmp, depois os.replace)."""
    path = _vocab_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(vocab, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[WARN] Falha ao salvar vocabulário: {e}")
        # Limpar .tmp se sobrou
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def add_word(word: str) -> bool:
    """Adiciona palavra ao vocabulário (case-sensitive). Retorna True se adicionou."""
    if not _is_enabled():
        return False
    word = word.strip()
    if not word:
        return False
    vocab = load_vocabulary()
    if word in vocab["words"]:
        return False
    vocab["words"].append(word)
    vocab["updated"] = datetime.now().replace(microsecond=0).isoformat()
    save_vocabulary(vocab)
    return True


def remove_word(word: str) -> bool:
    """Remove palavra do vocabulário. Retorna True se removeu."""
    if not _is_enabled():
        return False
    word = word.strip()
    vocab = load_vocabulary()
    if word not in vocab["words"]:
        return False
    vocab["words"].remove(word)
    vocab["updated"] = datetime.now().replace(microsecond=0).isoformat()
    save_vocabulary(vocab)
    return True


def get_words() -> list[str]:
    """Retorna lista de palavras do vocabulário custom."""
    if not _is_enabled():
        return []
    return load_vocabulary().get("words", [])


def get_hotwords_string() -> str:
    """Retorna _BASE_HOTWORDS + palavras custom, separadas por vírgula.

    Usado no parâmetro `hotwords` do Whisper.
    """
    if not _is_enabled():
        return _BASE_HOTWORDS
    words = get_words()
    if not words:
        return _BASE_HOTWORDS
    custom_part = ", ".join(words)
    return f"{_BASE_HOTWORDS}, {custom_part}"


def get_initial_prompt_suffix() -> str:
    """Retorna sufixo para append ao initial_prompt com palavras custom.

    Formato: ', JP Labs, OpenRouter, pywebview'
    Se vocabulário vazio ou desabilitado, retorna ''.
    """
    if not _is_enabled():
        return ""
    words = get_words()
    if not words:
        return ""
    return ", " + ", ".join(words)


def learn_from_correction(raw_text: str, corrected_text: str) -> list[str]:
    """Extrai candidatos a vocabulário comparando raw vs corrigido.

    Retorna lista de palavras que:
    - Apareceram no texto corrigido mas não no raw (foram inseridas/corrigidas)
    - Parecem nomes próprios ou termos técnicos (CamelCase, ALL_CAPS, TitleCase especial)
    - Não estão já no vocabulário

    NAO adiciona automaticamente — retorna candidatos para o caller decidir.
    """
    if not _is_enabled():
        return []
    if not raw_text or not corrected_text:
        return []

    raw_words = set(raw_text.split())
    corrected_words = set(corrected_text.split())

    # Palavras que aparecem no corrigido mas não no raw
    new_words = corrected_words - raw_words

    candidates: list[str] = []
    existing = set(get_words())

    for word in new_words:
        # Limpar pontuação das bordas
        clean = word.strip(".,;:!?\"'()[]{}").strip()
        if not clean or len(clean) < 2:
            continue
        # Só candidatos que parecem nomes próprios ou termos técnicos
        if not _PROPER_NOUN_RE.match(clean):
            continue
        # Não duplicar o que já está no vocabulário
        if clean in existing:
            continue
        # Não duplicar os base hotwords
        if clean.lower() in _BASE_HOTWORDS.lower():
            continue
        candidates.append(clean)

    return candidates
