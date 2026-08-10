from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Dict, Optional

PBKDF2_ALGORITHM = "sha256"
DEFAULT_ITERATIONS = 600_000


def hash_password(password: str, *, iterations: int = DEFAULT_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(PBKDF2_ALGORITHM, password.encode("utf-8"), salt, iterations)
    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii").rstrip("=")
    digest_b64 = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"pbkdf2_sha256${iterations}${salt_b64}${digest_b64}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iteration_text, salt_b64, digest_b64 = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iteration_text)
        salt = base64.urlsafe_b64decode(salt_b64 + "=" * (-len(salt_b64) % 4))
        expected = base64.urlsafe_b64decode(digest_b64 + "=" * (-len(digest_b64) % 4))
        actual = hashlib.pbkdf2_hmac(PBKDF2_ALGORITHM, password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(48)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class AttemptWindow:
    count: int
    first_at: float
    blocked_until: float = 0.0


class LoginRateLimiter:
    """Small in-memory rate limiter for the local owner login page."""

    def __init__(self, max_attempts: int = 8, window_seconds: int = 300, block_seconds: int = 300):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.block_seconds = block_seconds
        self._attempts: Dict[str, AttemptWindow] = {}

    def can_attempt(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        item = self._attempts.get(key)
        if not item:
            return True, 0
        if item.blocked_until > now:
            return False, max(1, int(item.blocked_until - now))
        if now - item.first_at > self.window_seconds:
            self._attempts.pop(key, None)
        return True, 0

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        item = self._attempts.get(key)
        if not item or now - item.first_at > self.window_seconds:
            item = AttemptWindow(count=0, first_at=now)
            self._attempts[key] = item
        item.count += 1
        if item.count >= self.max_attempts:
            item.blocked_until = now + self.block_seconds

    def record_success(self, key: str) -> None:
        self._attempts.pop(key, None)
