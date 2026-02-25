"""
Tests for validate_license_key(), _test_gemini_key(), _get_secret().
Pure logic — no hardware, no network.
"""
import base64
import hashlib
import hmac


import voice


# ---------------------------------------------------------------------------
# Helper — generate a valid test key using the same HMAC as voice.py
# ---------------------------------------------------------------------------

def _make_test_key(expiry_str: str) -> str:
    """Produce a well-formed HMAC-signed key for a given expiry date string."""
    secret = "jp-labs-vc-secret-2026"
    expiry_b64 = base64.urlsafe_b64encode(expiry_str.encode()).decode().rstrip("=")
    sig = hmac.new(secret.encode(), expiry_str.encode(), hashlib.sha256).hexdigest()[:12]
    return f"vc-{expiry_b64}-{sig}"


# ---------------------------------------------------------------------------
# _get_secret
# ---------------------------------------------------------------------------

def test_get_secret_retorna_string_correta():
    """_get_secret() must return the plain-text secret used for HMAC."""
    assert voice._get_secret() == "jp-labs-vc-secret-2026"


# ---------------------------------------------------------------------------
# validate_license_key
# ---------------------------------------------------------------------------

def test_chave_valida_futura():
    """A key with a far-future expiry is accepted."""
    key = _make_test_key("2099-12-31")
    ok, msg = voice.validate_license_key(key)
    assert ok is True
    assert "2099-12-31" in msg


def test_chave_expirada():
    """A key with a past expiry date is rejected with 'Expirada em...'."""
    key = _make_test_key("2020-01-01")
    ok, msg = voice.validate_license_key(key)
    assert ok is False
    assert "Expirada em" in msg


def test_hmac_errado():
    """Same structure but wrong HMAC signature → rejected as 'Chave inválida'."""
    expiry_str = "2099-12-31"
    expiry_b64 = base64.urlsafe_b64encode(expiry_str.encode()).decode().rstrip("=")
    bad_sig = "aabbccddeeff"  # 12 chars, but wrong
    bad_key = f"vc-{expiry_b64}-{bad_sig}"

    ok, msg = voice.validate_license_key(bad_key)
    assert ok is False
    assert msg == "Chave inválida"


def test_formato_invalido_partes():
    """String that doesn't have exactly 3 dash-separated parts → 'Formato inválido'."""
    ok, msg = voice.validate_license_key("vc-somente-duas")
    # The split gives ["vc", "somente", "duas"] which is 3 parts with parts[0]="vc"
    # so let's use a genuinely malformed key
    ok2, msg2 = voice.validate_license_key("invalid-key")
    assert ok2 is False
    assert msg2 == "Formato inválido"


def test_formato_invalido_prefix_errado():
    """Key not starting with 'vc' → 'Formato inválido'."""
    # Build valid structure but wrong prefix
    expiry_str = "2099-12-31"
    expiry_b64 = base64.urlsafe_b64encode(expiry_str.encode()).decode().rstrip("=")
    sig = hmac.new("jp-labs-vc-secret-2026".encode(), expiry_str.encode(), hashlib.sha256).hexdigest()[:12]
    bad_key = f"xx-{expiry_b64}-{sig}"

    ok, msg = voice.validate_license_key(bad_key)
    assert ok is False
    assert msg == "Formato inválido"


def test_base64_invalido():
    """Corrupted base64 in the expiry field → returns False."""
    bad_key = "vc-!!!NOTBASE64!!!-aabbccddeeff"
    ok, msg = voice.validate_license_key(bad_key)
    assert ok is False
    # Either "Chave inválida" from the except block
    assert msg in ("Chave inválida", "Formato inválido")


# ---------------------------------------------------------------------------
# _test_gemini_key
# ---------------------------------------------------------------------------

def test_gemini_key_valida():
    """Key starting with 'AIza' and at least 30 chars → (True, 'Formato OK')."""
    valid_key = "AIza" + "A" * 35  # 39 chars total
    ok, msg = voice._test_gemini_key(valid_key)
    assert ok is True
    assert msg == "Formato OK"


def test_gemini_key_invalida_sem_prefixo():
    """Key without 'AIza' prefix → (False, ...)."""
    ok, msg = voice._test_gemini_key("sk-abcdefghijklmnopqrstuvwxyz1234567")
    assert ok is False
    assert "AIza" in msg


def test_gemini_key_invalida_muito_curta():
    """Key with right prefix but too short → (False, ...)."""
    ok, msg = voice._test_gemini_key("AIza123")
    assert ok is False
    assert "curta" in msg


def test_gemini_key_invalida_vazia():
    """Empty string → (False, 'Chave vazia')."""
    ok, msg = voice._test_gemini_key("")
    assert ok is False
    assert "vazia" in msg
