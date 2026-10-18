import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import get_settings

COOKIE = "lodestone_session"
ALG = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(user_id: uuid.UUID) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user_id), "iat": now, "exp": now + timedelta(hours=s.session_hours)},
                      s.secret_key, algorithm=ALG)


def decode_token(token: str) -> uuid.UUID | None:
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=[ALG])
        return uuid.UUID(data["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
