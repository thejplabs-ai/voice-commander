# voice/snippets.py — Snippets: expansão de texto por voz (Epic 5.2)
#
# Formato snippets.json:
#   { "trigger phrase": "texto expandido completo", ... }
#
# Triggers são normalizados para lowercase no add/match.
# Save é atômico via .tmp + os.replace().

import json
import os

from voice import state


_SNIPPETS_FILENAME = "snippets.json"


def _snippets_path() -> str:
    return os.path.join(state._BASE_DIR, _SNIPPETS_FILENAME)


def load_snippets() -> dict:
    """Carrega snippets.json de _BASE_DIR.

    Retorna {} se o arquivo não existe ou se o JSON é inválido.
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
        # Normalizar triggers para lowercase na carga
        return {k.lower().strip(): v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
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


def add_snippet(trigger: str, text: str) -> None:
    """Adiciona ou atualiza um snippet. Trigger é normalizado para lowercase."""
    snippets = load_snippets()
    snippets[trigger.lower().strip()] = text
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
    """Retorna dict {trigger: text} com todos os snippets cadastrados."""
    return load_snippets()


def match_snippet(transcribed_text: str) -> str | None:
    """Verifica se o texto transcrito corresponde a um snippet.

    Estratégia de match (em ordem de prioridade):
    1. Match exato (case-insensitive, stripped)
    2. Match parcial: texto começa com um trigger
    3. Match parcial: texto termina com um trigger

    Retorna o texto de expansão se houver match, ou None.
    """
    if not state._CONFIG.get("SNIPPETS_ENABLED", True):
        return None

    snippets = load_snippets()
    if not snippets:
        return None

    normalized = transcribed_text.strip().lower()
    if not normalized:
        return None

    # 1. Match exato
    if normalized in snippets:
        return snippets[normalized]

    # 2. Match parcial: começa com trigger
    for trigger, expansion in snippets.items():
        if normalized.startswith(trigger):
            return expansion

    # 3. Match parcial: termina com trigger
    for trigger, expansion in snippets.items():
        if normalized.endswith(trigger):
            return expansion

    return None
