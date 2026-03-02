# voice/logging_.py — print patch, log rotation, history append
# Side-effect on import: patches builtins.print with _log_print

import builtins
import datetime
import glob
import json
import os
import sys

from voice import state


_orig_print = builtins.print


def _log_print(*args, **kwargs):
    msg = " ".join(str(a) for a in args)
    # Só chama _orig_print se stdout existir (pythonw não tem console)
    if sys.stdout is not None:
        try:
            _orig_print(*args, **kwargs)
        except Exception:
            pass
    try:
        with open(state._log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


# Patch builtins.print on import (same as original voice.py)
builtins.print = _log_print


def _rotate_log() -> None:
    """
    Renomeia voice.log atual → voice.YYYY-MM-DD_HH-MM-SS.log (se existir).
    Mantém apenas LOG_KEEP_SESSIONS arquivos de sessão (os mais recentes por mtime).
    Silencioso — erros são ignorados; o log será registrado após abertura do novo arquivo.
    """
    keep = state._CONFIG.get("LOG_KEEP_SESSIONS", 5)

    # Renomear log atual se existir
    if os.path.exists(state._log_path):
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        archived = os.path.join(state._BASE_DIR, f"voice.{ts}.log")
        try:
            os.rename(state._log_path, archived)
        except Exception:
            pass

    # Listar e ordenar sessões arquivadas por mtime (mais recente primeiro)
    pattern = os.path.join(state._BASE_DIR, "voice.????-??-??_??-??-??.log")
    session_logs = glob.glob(pattern)
    if session_logs:
        session_logs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        # Deletar as sessões além do limite
        for old_log in session_logs[keep:]:
            try:
                os.remove(old_log)
            except Exception:
                pass


def _append_history(
    mode: str,
    raw_text: str,
    processed_text: str | None,
    duration_seconds: float,
    error: bool = False,
    timing_ms: dict | None = None,
) -> None:
    """
    Acrescenta uma entrada ao history.jsonl (append-only).
    Faz trim automático se o número de entradas ultrapassar HISTORY_MAX_ENTRIES.
    timing_ms: dict opcional com breakdown de tempo por fase (recording, whisper, gemini, paste, total).
    """
    max_entries = state._CONFIG.get("HISTORY_MAX_ENTRIES", 500)

    entry: dict = {
        "timestamp": datetime.datetime.now().isoformat(),
        "mode": mode,
        "raw_text": raw_text,
        "processed_text": processed_text,
        "duration_seconds": round(duration_seconds, 2),
        "chars": len(processed_text) if processed_text else 0,
    }
    if error:
        entry["error"] = True
        entry["processed_text"] = None
    if timing_ms:
        entry["timing_ms"] = timing_ms

    try:
        # Append da nova entrada
        with open(state._history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Trim: só reescreve quando ultrapassa max_entries * 1.1 (buffer de 10%)
        # Reduz writes de trim para ~1/50 das operações em relação ao trim por entrada
        trim_threshold = int(max_entries * 1.1)
        with open(state._history_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if len(lines) > trim_threshold:
            lines = lines[-max_entries:]
            with open(state._history_path, "w", encoding="utf-8") as f:
                f.writelines(lines)

    except Exception as e:
        print(f"[WARN] Falha ao salvar histórico: {e}")
