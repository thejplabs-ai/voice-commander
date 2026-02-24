#!/usr/bin/env python3
"""
Voice Commander — Gerador de Chave de Licença
Uso: python generate_license_key.py [--days 30]

Gera chaves de licença assinadas via HMAC (mesmo algoritmo do voice.py).
Usar para gerar chaves de teste locais antes de conectar ao n8n/Stripe.
"""

import argparse
import base64
import datetime
import hmac
import hashlib

# MESMO secret do voice.py (obfuscado)
_K = [ord(c) ^ 0x42 for c in "jp-labs-vc-secret-2026"]


def _get_secret() -> str:
    return "".join(chr(c ^ 0x42) for c in _K)


def generate_key(days: int = 30) -> tuple[str, str]:
    """Gera uma chave de licença válida por N dias. Retorna (key, expiry_date)."""
    expiry = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
    expiry_b64 = base64.urlsafe_b64encode(expiry.encode()).decode().rstrip("=")
    sig = hmac.new(_get_secret().encode(), expiry.encode(), hashlib.sha256).hexdigest()[:12]
    return f"vc-{expiry_b64}-{sig}", expiry


def validate_key(key: str) -> tuple[bool, str]:
    """Valida uma chave (mesma lógica do voice.py)."""
    try:
        parts = key.strip().split("-", 2)
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gerar chave de licença Voice Commander")
    parser.add_argument("--days", type=int, default=30, help="Validade em dias (default: 30)")
    parser.add_argument("--validate", type=str, default="", help="Validar uma chave existente")
    args = parser.parse_args()

    if args.validate:
        ok, msg = validate_key(args.validate)
        status = "VÁLIDA" if ok else "INVÁLIDA"
        print(f"[{status}] {msg}")
        print(f"Chave: {args.validate}")
    else:
        key, expiry = generate_key(args.days)
        print(f"Chave: {key}")
        print(f"Expiry: {expiry} ({args.days} dias)")
        # Auto-validar
        ok, msg = validate_key(key)
        print(f"Auto-validação: {msg}")
