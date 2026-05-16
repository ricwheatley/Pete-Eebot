"""Password and session-token hashing helpers."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import struct
import time

PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
DEFAULT_PBKDF2_ITERATIONS = 600_000
DEFAULT_SALT_BYTES = 16
DEFAULT_SESSION_TOKEN_BYTES = 32
DEFAULT_TOTP_SECRET_BYTES = 20
DEFAULT_TOTP_INTERVAL_SECONDS = 30
DEFAULT_TOTP_DIGITS = 6


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("ascii"))


def hash_password(
    password: str,
    *,
    iterations: int = DEFAULT_PBKDF2_ITERATIONS,
    salt: bytes | None = None,
) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string")
    if iterations <= 0:
        raise ValueError("iterations must be positive")

    resolved_salt = salt if salt is not None else secrets.token_bytes(DEFAULT_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        resolved_salt,
        iterations,
    )
    return "$".join(
        (
            PASSWORD_HASH_ALGORITHM,
            str(iterations),
            _b64encode(resolved_salt),
            _b64encode(digest),
        )
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iteration_text, salt_text, digest_text = encoded_hash.split("$", 3)
        if algorithm != PASSWORD_HASH_ALGORITHM:
            return False
        iterations = int(iteration_text)
        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)
    except (AttributeError, TypeError, ValueError):
        return False

    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        str(password or "").encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(candidate, expected)


def generate_session_token() -> str:
    return secrets.token_urlsafe(DEFAULT_SESSION_TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    if not isinstance(token, str) or not token:
        raise ValueError("session token must be a non-empty string")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(DEFAULT_TOTP_SECRET_BYTES)).decode("ascii").rstrip("=")


def generate_recovery_code() -> str:
    raw = secrets.token_hex(8).upper()
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:]}"


def recovery_code_hashes(codes: list[str] | tuple[str, ...]) -> list[str]:
    return [hash_password(code) for code in codes]


def totp_code(
    secret: str,
    *,
    for_time: int | float | None = None,
    interval_seconds: int = DEFAULT_TOTP_INTERVAL_SECONDS,
    digits: int = DEFAULT_TOTP_DIGITS,
) -> str:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    if digits <= 0:
        raise ValueError("digits must be positive")
    key = _decode_totp_secret(secret)
    counter = int((time.time() if for_time is None else for_time) // interval_seconds)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10**digits)).zfill(digits)


def verify_totp_code(
    secret: str,
    code: str,
    *,
    for_time: int | float | None = None,
    window: int = 1,
    interval_seconds: int = DEFAULT_TOTP_INTERVAL_SECONDS,
    digits: int = DEFAULT_TOTP_DIGITS,
) -> bool:
    candidate = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(candidate) != digits:
        return False
    base_time = time.time() if for_time is None else float(for_time)
    for offset in range(-window, window + 1):
        timestamp = base_time + (offset * interval_seconds)
        if hmac.compare_digest(candidate, totp_code(secret, for_time=timestamp, interval_seconds=interval_seconds, digits=digits)):
            return True
    return False


def _decode_totp_secret(secret: str) -> bytes:
    normalized = "".join(str(secret or "").split()).upper()
    if not normalized:
        raise ValueError("TOTP secret is required")
    padding = "=" * (-len(normalized) % 8)
    try:
        return base64.b32decode((normalized + padding).encode("ascii"), casefold=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid TOTP secret") from exc
