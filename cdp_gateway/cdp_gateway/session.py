import time

import jwt
from passlib.context import CryptContext

from .config import DURATIONS, JWT_SECRET, PASSWORD_FILE

_ALGORITHM = "HS256"
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ─── Password management ──────────────────────────────────────────────────────

def password_is_set() -> bool:
    return PASSWORD_FILE.exists() and PASSWORD_FILE.stat().st_size > 0


def set_password(plain: str) -> None:
    """Hash plain with bcrypt and write to PASSWORD_FILE (mode 0600)."""
    hashed = _pwd_context.hash(plain)
    PASSWORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    PASSWORD_FILE.write_text(hashed, encoding="utf-8")
    PASSWORD_FILE.chmod(0o600)


def verify_password(plain: str) -> bool:
    """Return True if plain matches the stored bcrypt hash."""
    if not password_is_set():
        return False
    stored = PASSWORD_FILE.read_text(encoding="utf-8").strip()
    return _pwd_context.verify(plain, stored)


# ─── JWT management ───────────────────────────────────────────────────────────

def issue_token(duration_key: str) -> str:
    """Sign and return a JWT valid for the requested duration."""
    seconds = DURATIONS[duration_key]
    payload = {
        "iat": int(time.time()),
        "exp": int(time.time()) + seconds,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=_ALGORITHM)


def validate_token(token: str) -> bool:
    """Return True if the token is valid and not expired."""
    if not JWT_SECRET or not token:
        return False
    try:
        jwt.decode(token, JWT_SECRET, algorithms=[_ALGORITHM])
        return True
    except jwt.ExpiredSignatureError:
        return False
    except jwt.PyJWTError:
        return False
