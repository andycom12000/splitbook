"""PIN 雜湊與 signed cookie token（stdlib only，5 人小工具等級）。"""
import hashlib
import hmac
import os
import time


def hash_pin(pin: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 100_000)
    return f"{salt.hex()}${dk.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 100_000)
    return hmac.compare_digest(dk.hex(), dk_hex)


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_token(group_id: int, member_id: int, secret: str,
               now: int | None = None, ttl: int = 2592000) -> str:
    now = int(time.time()) if now is None else now
    payload = f"{group_id}.{member_id}.{now + ttl}"
    return f"{payload}.{_sign(payload, secret)}"


def parse_token(token: str, secret: str,
                now: int | None = None) -> tuple[int, int] | None:
    now = int(time.time()) if now is None else now
    parts = token.split(".")
    if len(parts) != 4:
        return None
    payload = ".".join(parts[:3])
    if not hmac.compare_digest(_sign(payload, secret), parts[3]):
        return None
    try:
        gid, mid, exp = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if exp < now:
        return None
    return gid, mid
