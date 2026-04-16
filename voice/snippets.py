# voice/snippets.py — Snippets: expansão de texto por voz (Epic 5.2)
#
# Formato snippets.json (v2 — backward compatible):
#   { "trigger": { "text": "expansão", "mode": "replace"|"inline" }, ... }
#   Formato legado (v1): { "trigger": "expansão" } — tratado como mode="replace"
#
# Triggers são normalizados para lowercase no add/match.
# Save é atômico via .tmp + os.replace().

import json
import os
import re
import unicodedata

from voice import state


_SNIPPETS_FILENAME = "snippets.json"
_FUZZY_THRESHOLD = 82

# Mapa de vogais com acento para regex tolerante
_ACCENT_ALTS = {
    "a": "[aáàâãä]", "e": "[eéèêë]", "i": "[iíìîï]",
    "o": "[oóòôõö]", "u": "[uúùûü]", "c": "[cç]", "n": "[nñ]",
}


def _snippets_path() -> str:
    return os.path.join(state._BASE_DIR, _SNIPPETS_FILENAME)


def _normalize(text: str) -> str:
    """Normaliza texto para matching: lowercase, sem acentos, sem pontuacao."""
    t = text.lower().strip()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _trigger_to_pattern(trigger: str) -> re.Pattern:
    """Converte trigger em regex tolerante a acentos/hifens/case.

    Ex: "meu email" -> r'(?i)\\bmeu\\s+e[-\\s]?mail\\b'
    Aplicado direto no texto original (sem normalização).
    """
    norm_trigger = _normalize(trigger)
    words = norm_trigger.split()
    word_patterns = []
    for w in words:
        chars = []
        for c in w:
            if c in _ACCENT_ALTS:
                chars.append(_ACCENT_ALTS[c])
            else:
                chars.append(re.escape(c))
        # Permitir hifens opcionais entre chars (ex: e-mail, e mail, email)
        word_patterns.append(r"[-\s]?".join(chars))
    pattern_str = r"\b" + r"\s+" .join(word_patterns) + r"\b"
    return re.compile(pattern_str, re.IGNORECASE)


def _parse_entry(value) -> dict | None:
    """Normaliza entrada do snippets.json: string (v1) ou dict (v2)."""
    if isinstance(value, str):
        return {"text": value, "mode": "replace"}
    if isinstance(value, dict) and isinstance(value.get("text"), str):
        mode = value.get("mode", "replace")
        if mode not in ("replace", "inline"):
            mode = "replace"
        return {"text": value["text"], "mode": mode}
    return None


def load_snippets() -> dict:
    """Carrega snippets.json de _BASE_DIR.

    Retorna {} se o arquivo não existe ou se o JSON é inválido.
    Valores podem ser string (v1) ou dict (v2). Normaliza para v2 interno.
    """
    path = _snippets_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            print("[WARN] snippets.json não é um objeto JSON — ignorando")
            return {}
        result = {}
        for k, v in data.items():
            if not isinstance(k, str):
                continue
            entry = _parse_entry(v)
            if entry is not None:
                result[k.lower().strip()] = entry
        return result
    except json.JSONDecodeError as e:
        print(f"[WARN] snippets.json inválido ({e}) — ignorando")
        return {}
    except Exception as e:
        print(f"[WARN] Erro ao carregar snippets: {e}")
        return {}


def save_snippets(snippets: dict) -> None:
    """Salva snippets em snippets.json de forma atômica (.tmp → os.replace)."""
    path = _snippets_path()
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(snippets, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception as e:
        print(f"[ERRO] Falha ao salvar snippets: {e}")
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def add_snippet(trigger: str, text: str, mode: str = "replace") -> None:
    """Adiciona ou atualiza um snippet. Trigger é normalizado para lowercase."""
    if mode not in ("replace", "inline"):
        mode = "replace"
    snippets = load_snippets()
    snippets[trigger.lower().strip()] = {"text": text, "mode": mode}
    save_snippets(snippets)


def remove_snippet(trigger: str) -> bool:
    """Remove snippet pelo trigger. Retorna True se existia, False caso contrário."""
    snippets = load_snippets()
    key = trigger.lower().strip()
    if key not in snippets:
        return False
    del snippets[key]
    save_snippets(snippets)
    return True


def get_snippets() -> dict:
    """Retorna dict {trigger: {text, mode}} com todos os snippets cadastrados."""
    return load_snippets()


def _apply_inline(original_text: str, trigger: str, expansion: str) -> str | None:
    """Substitui o trigger dentro do texto original, preservando o contexto.

    Usa regex tolerante a acentos/hifens/case direto no texto original.
    Retorna o texto modificado, ou None se trigger não encontrado.
    """
    pattern = _trigger_to_pattern(trigger)
    m = pattern.search(original_text)
    if not m:
        return None
    return original_text[:m.start()] + expansion + original_text[m.end():]


def _exact_match(norm_text: str, original_text: str, entries) -> str | None:
    """Estágio 1: match exato normalizado. Para inline, aplica _apply_inline."""
    for trigger, norm_trigger, expansion, mode in entries:
        if norm_text == norm_trigger:
            if mode == "inline":
                return _apply_inline(original_text, trigger, expansion) or expansion
            return expansion
    return None


def _inline_match(original_text: str, entries) -> str | None:
    """Estágio 2a: inline via regex tolerante (len>=2, mode='inline' only)."""
    for trigger, norm_trigger, expansion, mode in entries:
        if mode != "inline":
            continue
        if len(norm_trigger) < 2:
            continue
        result = _apply_inline(original_text, trigger, expansion)
        if result is not None:
            return result
    return None


def _replace_containment_match(norm_text: str, entries) -> str | None:
    """Estágio 2b: replace via word boundary (len>=2, mode='replace' only)."""
    for trigger, norm_trigger, expansion, mode in entries:
        if mode != "replace":
            continue
        if len(norm_trigger) < 2:
            continue
        pattern = r"\b" + re.escape(norm_trigger) + r"\b"
        if re.search(pattern, norm_text):
            return expansion
    return None


def _fuzzy_match(norm_text: str, entries) -> str | None:
    """Estágio 3: fuzzy via rapidfuzz (len>=3, mode='replace', threshold 82).

    Retorna None se rapidfuzz não estiver disponível (ImportError).
    """
    try:
        from rapidfuzz import fuzz
        best_match = None
        best_score = 0
        for trigger, norm_trigger, expansion, mode in entries:
            if mode == "inline":
                continue
            if len(norm_trigger) < 3:
                continue
            score = fuzz.partial_ratio(norm_trigger, norm_text)
            if score >= _FUZZY_THRESHOLD and score > best_score:
                best_score = score
                best_match = expansion
        return best_match
    except ImportError:
        return None


def match_snippet(transcribed_text: str) -> str | None:
    """Verifica se o texto transcrito corresponde a um snippet.

    Retorna o texto final a ser colado:
    - mode=replace: retorna a expansão (substitui tudo)
    - mode=inline: retorna o texto com o trigger substituído pela expansão

    Estratégia de match em cascata:
    1. Match exato normalizado
    2. Containment normalizado (word boundary)
    3. Fuzzy via rapidfuzz (somente para mode=replace)
    """
    if not state._CONFIG.get("SNIPPETS_ENABLED", True):
        return None

    snippets = load_snippets()
    if not snippets:
        return None

    norm_text = _normalize(transcribed_text)
    if not norm_text:
        return None

    # Pre-compute normalized triggers
    entries = [
        (trigger, _normalize(trigger), entry["text"], entry["mode"])
        for trigger, entry in snippets.items()
    ]

    result = _exact_match(norm_text, transcribed_text, entries)
    if result is not None:
        return result

    result = _inline_match(transcribed_text, entries)
    if result is not None:
        return result

    result = _replace_containment_match(norm_text, entries)
    if result is not None:
        return result

    return _fuzzy_match(norm_text, entries)
