"""本地账号认证工具。

第一版不引入外部 auth 依赖：密码用 PBKDF2-HMAC-SHA256 加盐哈希，访问 token 用
HMAC-SHA256 签名的短期 bearer token。token 只包含用户 id、用户名与过期时间，不包含密钥。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
from datetime import UTC, datetime, timedelta

from app.models import UserAccount

_PASSWORD_ALG = "pbkdf2_sha256"
_PASSWORD_ITERATIONS = 210_000
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_username(username: str) -> str:
    normalized = normalize_username(username)
    if not _USERNAME_RE.fullmatch(normalized):
        raise ValueError("用户名需为 3-64 位，只能包含字母、数字、下划线、点和连字符")
    return normalized


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("密码至少 8 位")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS
    )
    return "$".join(
        [
            _PASSWORD_ALG,
            str(_PASSWORD_ITERATIONS),
            _b64(salt),
            _b64(digest),
        ]
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        alg, raw_iters, salt_b64, digest_b64 = stored_hash.split("$", 3)
        if alg != _PASSWORD_ALG:
            return False
        iterations = int(raw_iters)
        salt = _unb64(salt_b64)
        expected = _unb64(digest_b64)
    except (binascii.Error, ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def create_access_token(user: UserAccount, *, secret: str, ttl_seconds: int) -> str:
    exp = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    payload = {
        "sub": user.id,
        "username": user.username,
        "exp": int(exp.timestamp()),
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _sign(body, secret)
    return f"{body}.{sig}"


def decode_access_token(token: str, *, secret: str) -> dict:
    try:
        body, sig = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("invalid token") from exc
    if not hmac.compare_digest(_sign(body, secret), sig):
        raise ValueError("invalid token signature")
    try:
        payload = json.loads(_unb64(body))
    except (binascii.Error, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("invalid token payload") from exc
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(datetime.now(UTC).timestamp()):
        raise ValueError("token expired")
    if not isinstance(payload.get("sub"), str):
        raise ValueError("token missing subject")
    return payload


def _sign(body: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return _b64(digest)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)
