"""Password hashing (PBKDF2-HMAC-SHA256, stdlib only) and JWT access tokens (PyJWT)."""
from __future__ import annotations

import hashlib
import hmac
import os
import time

import jwt

ITERATIONS = 200_000
ALGORITHM = "HS256"


class AuthError(Exception):
    """Invalid, expired or malformed credentials/token."""


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(digest, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False


def create_token(user_id: int, secret: str, minutes: int = 60) -> str:
    now = int(time.time())
    payload = {"sub": str(user_id), "iat": now, "exp": now + minutes * 60}
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_token(token: str, secret: str) -> int:
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise AuthError("Invalid or expired token.") from exc
