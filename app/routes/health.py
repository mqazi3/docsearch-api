import logging

import redis
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.cache import get_redis
from app.config import get_settings
from app.db import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Health"])


@router.get("/health")
def liveness() -> dict:
    """Liveness: the process is up. Checks no dependencies on purpose."""
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(
    response: Response,
    db: Session = Depends(get_db),
    cache: redis.Redis = Depends(get_redis),
) -> dict:
    """Readiness: can this instance serve real traffic right now?"""
    checks: dict[str, str] = {}

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except SQLAlchemyError:
        logger.exception("Readiness check: database unavailable")
        checks["database"] = "unavailable"

    try:
        cache.ping()
        checks["redis"] = "ok"
    except redis.RedisError:
        logger.exception("Readiness check: redis unavailable")
        checks["redis"] = "unavailable"

    ready = all(value == "ok" for value in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if ready else "not_ready",
        "checks": checks,
        "version": get_settings().app_version,
    }
