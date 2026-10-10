import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ApiKey, ApiKeyRole

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
KEY_PREFIX = "dsk_"
PREFIX_LENGTH = 12
LAST_USED_RESOLUTION = timedelta(minutes=1)


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)  # 256 bits of randomness


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def create_api_key(db: Session, name: str, role: str) -> tuple[ApiKey, str]:
    """Create a key and return (record, raw key). The raw key is never stored."""
    raw_key = generate_key()
    key = ApiKey(name=name, role=role, prefix=raw_key[:PREFIX_LENGTH], key_hash=hash_key(raw_key))
    db.add(key)
    db.commit()
    db.refresh(key)
    return key, raw_key


def authenticate(
    raw_key: str | None = Security(API_KEY_HEADER),
    db: Session = Depends(get_db),
) -> ApiKey:
    if not raw_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key")
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_key(raw_key)))
    if key is None or key.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key"
        )

    # Record usage at most once a minute, so busy keys don't cause a write per request.
    now = datetime.now(UTC)
    if key.last_used_at is None or now - key.last_used_at > LAST_USED_RESOLUTION:
        key.last_used_at = now
        db.commit()
    return key


def require_role(*roles: str):
    def dependency(key: ApiKey = Depends(authenticate)) -> ApiKey:
        if key.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="This API key cannot do that"
            )
        return key

    return dependency


require_reader = require_role(ApiKeyRole.READER, ApiKeyRole.ADMIN)
require_admin = require_role(ApiKeyRole.ADMIN)
