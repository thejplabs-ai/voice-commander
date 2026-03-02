# voice/user_profile.py — User Profile: facts about the user injected into all Gemini calls

import json
import os
import threading
from datetime import datetime

from voice import state

_profile_lock = threading.Lock()
_MAX_FACTS = 200


def _profile_path() -> str:
    return os.path.join(state._BASE_DIR, "user-profile.json")


def _default_profile() -> dict:
    now = datetime.now().isoformat()
    return {
        "version": 1,
        "last_briefing_at": None,
        "facts": [],
        "created_at": now,
        "updated_at": now,
    }


def load_profile() -> dict:
    """Carrega user-profile.json. Cria arquivo padrão se não existir. Thread-safe."""
    with _profile_lock:
        path = _profile_path()
        if not os.path.exists(path):
            profile = _default_profile()
            _write_profile(profile)
            return profile
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Garantir campos obrigatórios
            for key, val in _default_profile().items():
                if key not in data:
                    data[key] = val
            return data
        except Exception as e:
            print(f"[WARN] user-profile.json corrompido ({e}), recriando")
            profile = _default_profile()
            _write_profile(profile)
            return profile


def _write_profile(profile: dict) -> None:
    """Escrita atômica via .tmp. Deve ser chamado DENTRO de _profile_lock."""
    path = _profile_path()
    tmp_path = path + ".tmp"
    profile["updated_at"] = datetime.now().isoformat()
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception as e:
        print(f"[WARN] Falha ao salvar user-profile.json: {e}")
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def add_fact(fact: str) -> None:
    """Adiciona fato ao perfil (idempotente — ignora duplicatas). Trim em 200 fatos."""
    fact = fact.strip()
    if not fact:
        return
    with _profile_lock:
        path = _profile_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                profile = json.load(f)
        except Exception:
            profile = _default_profile()

        # Idempotência: não adicionar se já existe (case-insensitive)
        existing_lower = [f.lower() for f in profile.get("facts", [])]
        if fact.lower() in existing_lower:
            print(f"[INFO] Fato já existe no perfil: {fact}")
            return

        facts = profile.get("facts", [])
        facts.append(fact)
        # Trim para máximo de 200 fatos (remove os mais antigos)
        if len(facts) > _MAX_FACTS:
            facts = facts[-_MAX_FACTS:]
        profile["facts"] = facts
        _write_profile(profile)
    print(f"[OK]   Perfil atualizado: +\"{fact}\"")


def remove_fact(index: int) -> bool:
    """Remove fato pelo índice (0-based). Retorna True se removido."""
    with _profile_lock:
        path = _profile_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                profile = json.load(f)
        except Exception:
            return False
        facts = profile.get("facts", [])
        if index < 0 or index >= len(facts):
            return False
        removed = facts.pop(index)
        profile["facts"] = facts
        _write_profile(profile)
    print(f"[OK]   Fato removido do perfil: \"{removed}\"")
    return True


def update_last_briefing() -> None:
    """Grava timestamp do último briefing no user-profile.json."""
    with _profile_lock:
        path = _profile_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                profile = json.load(f)
        except Exception:
            profile = _default_profile()
        profile["last_briefing_at"] = datetime.now().isoformat()
        _write_profile(profile)


def get_profile_prefix() -> str:
    """Retorna bloco '[PERFIL DO USUÁRIO]...' ou '' se vazio/desativado."""
    if state._CONFIG.get("USER_PROFILE_ENABLED", "true").lower() != "true":
        return ""
    profile = state._user_profile
    facts = profile.get("facts", [])
    if not facts:
        return ""
    lines = "\n".join(f"- {f}" for f in facts)
    return f"[PERFIL DO USUÁRIO]\n{lines}\n\n"
