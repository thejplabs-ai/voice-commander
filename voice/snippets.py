# voice/snippets.py — Snippets: expansão de texto por voz (Epic 5.2)
#
# Formato snippets.json (v2 — backward compatible):
#   { "trigger": { "text": "expansão", "mode": "replace"|"inline" }, ... }
#   Formato legado (v1): { "trigger": "expansão" } — tratado como mode="replace"
#
# Triggers são normalizados para lowercase no add/match.
# Save é atômico via .tmp + os.replace().
#
# Matching é sempre de FRASE COMPLETA (exato ou fuzzy de alta confiança sobre
# a frase inteira). O campo `mode` é aceito no CRUD mas não influencia o
# matching — o resultado é sempre o `text` do snippet.

import json
import os
import re
import unicodedata

from voice import state


_SNIPPETS_FILENAME = "snippets.json"
_FUZZY_THRESHOLD = 90


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


def _exact_match(norm_text: str, entries) -> str | None:
    """Estágio 1: frase inteira normalizada == trigger normalizado."""
    for trigger, norm_trigger, expansion in entries:
        if norm_text == norm_trigger:
            return expansion
    return None


def _fuzzy_match(norm_text: str, entries) -> str | None:
    """Estágio 2: fuzzy sobre a FRASE INTEIRA via rapidfuzz (len>=3, threshold 90).

    Retorna None se rapidfuzz não estiver disponível (ImportError).
    """
    try:
        from rapidfuzz import fuzz
        best_match = None
        best_score = 0
        for trigger, norm_trigger, expansion in entries:
            if len(norm_trigger) < 3:
                continue
            score = fuzz.ratio(norm_trigger, norm_text)
            if score >= _FUZZY_THRESHOLD and score > best_score:
                best_score = score
                best_match = expansion
        return best_match
    except ImportError:
        return None


def match_snippet(transcribed_text: str) -> str | None:
    """Verifica se a FRASE INTEIRA transcrita corresponde a um snippet.

    Dispara somente quando a frase ditada bate por inteiro com o trigger —
    nunca quando o trigger é apenas parte de uma ditação mais longa.

    Estratégia de match em cascata:
    1. Match exato normalizado (frase inteira == trigger)
    2. Fuzzy via rapidfuzz sobre a frase inteira (threshold alto)
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
        (trigger, _normalize(trigger), entry["text"])
        for trigger, entry in snippets.items()
    ]

    result = _exact_match(norm_text, entries)
    if result is not None:
        return result

    return _fuzzy_match(norm_text, entries)
