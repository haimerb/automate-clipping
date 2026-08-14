from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db import get_db
from .users import User

_bearer = HTTPBearer(auto_error=False)
_ALGO = "HS256"
_TOKEN_TTL = timedelta(hours=12)
_PBKDF2_ITERATIONS = 200_000


def _secret() -> str:
    """El secreto JWT viene SOLO del entorno; no hay fallback en el código."""
    secret = os.environ.get("EDGETAPE_JWT_SECRET")
    if not secret:
        raise RuntimeError(
            "Falta EDGETAPE_JWT_SECRET. Defínela en un archivo .env (ver .env.example) "
            "o en el entorno."
        )
    return secret


def hash_password(password: str) -> str:
    salt = uuid.uuid4().hex
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), _PBKDF2_ITERATIONS
    )
    return f"pbkdf2${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, hexdigest = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), _PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(hexdigest, digest.hex())


def create_token(user: User) -> str:
    payload = {
        "sub": user.id,
        "email": user.email,
        "exp": datetime.now(timezone.utc) + _TOKEN_TTL,
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGO)


def _decode_token(raw: str, db: Session) -> User:
    try:
        payload = jwt.decode(raw, _secret(), algorithms=[_ALGO])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada")
    user = db.get(User, payload.get("sub"))
    if user is None:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")
    return user


def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if cred is None:
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    return _decode_token(cred.credentials, db)


def get_current_user_media(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    token: str | None = None,
    db: Session = Depends(get_db),
) -> User:
    """Acepta el token también como query param, para <img>/<video> del navegador."""
    raw = cred.credentials if cred else token
    if not raw:
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    return _decode_token(raw, db)
