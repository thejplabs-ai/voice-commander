# voice/license.py — license validation, Gemini key test, expiry notification

import base64
import datetime
import hashlib
import hmac

from voice import state


# Obfuscated secret (evita extração por grep no .exe)
_K = [ord(c) ^ 0x42 for c in "jp-labs-vc-secret-2026"]


def _get_secret() -> str:
    return "".join(chr(c ^ 0x42) for c in _K)


def validate_license_key(key: str) -> tuple[bool, str]:
    """Valida chave de licença via HMAC local (sem servidor necessário)."""
    try:
        parts = key.strip().split("-", 2)  # ["vc", expiry_b64, sig]
        if len(parts) != 3 or parts[0] != "vc":
            return False, "Formato inválido"
        expiry_b64, sig = parts[1], parts[2]
        expiry = base64.urlsafe_b64decode(expiry_b64 + "==").decode()
        expected_sig = hmac.new(_get_secret().encode(), expiry.encode(), hashlib.sha256).hexdigest()[:12]
        if not hmac.compare_digest(sig, expected_sig):
            return False, "Chave inválida"
        expiry_date = datetime.date.fromisoformat(expiry)
        if datetime.date.today() > expiry_date:
            return False, f"Expirada em {expiry}"
        return True, f"Válida até {expiry}"
    except Exception:
        return False, "Chave inválida"


def _test_gemini_key(api_key: str) -> tuple[bool, str]:
    """Valida formato da chave Gemini sem fazer chamada à API.

    Não consumimos quota no setup — a chave é validada de verdade
    na primeira transcrição real. Formato AI Studio: AIza + ~35 chars.
    """
    key = api_key.strip()
    if not key:
        return False, "Chave vazia"
    if not key.startswith("AIza"):
        return False, "Formato inválido — chave deve começar com 'AIza'"
    if len(key) < 30:
        return False, "Chave muito curta — verifique se copiou completo"
    if len(key) > 60:
        return False, "Chave muito longa — verifique se há espaços extras"
    return True, "Formato OK"


def _show_license_expired_notification() -> None:
    """Notifica licença expirada via tray balloon — não bloqueia o teclado."""
    if state._tray_icon is not None and state._tray_available:
        try:
            state._tray_icon.notify(
                "Licença expirada — renove em voice.jplabs.ai",
                "Voice Commander",
            )
            return
        except Exception:
            pass
    # Fallback: só loga, não abre dialog bloqueante
    print("[WARN] Licença expirada — renove em voice.jplabs.ai")
