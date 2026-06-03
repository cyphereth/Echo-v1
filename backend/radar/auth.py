"""Minimal dependency-free auth: pbkdf2 password hashing + HMAC-signed tokens.

Token format: base64url(payload_json).base64url(hmac_sha256(payload)). Not a full
JWT, but the same shape and good enough for this app — swap for PyJWT if needed.
"""
from __future__ import annotations
import base64, hashlib, hmac, json, os, time

SECRET    = os.getenv("JWT_SECRET", "echo-dev-secret-change-me").encode()
TOKEN_TTL = 60 * 60 * 24 * 30  # 30 days
_ITERATIONS = 100_000


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")

def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"{salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), _ITERATIONS)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def _sign(body: str) -> str:
    return _b64(hmac.new(SECRET, body.encode(), hashlib.sha256).digest())


def create_token(uid: int, email: str, ttl: int = TOKEN_TTL) -> str:
    now = int(time.time())
    payload = {"uid": uid, "email": email, "iat": now, "exp": now + ttl}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}"


def decode_token(token: str) -> dict:
    body, sig = token.split(".", 1)
    if not hmac.compare_digest(sig, _sign(body)):
        raise ValueError("bad signature")
    payload = json.loads(_unb64(body))
    if payload.get("exp", 0) < int(time.time()):
        raise ValueError("expired")
    return payload
