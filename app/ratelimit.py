import logging
import time

import redis
from fastapi import Depends, HTTPException, status

from app.auth import require_reader
from app.cache import get_redis
from app.config import get_settings
from app.models import ApiKey

logger = logging.getLogger(__name__)

MINUTE = 60
DAY = 24 * 60 * 60


def check_limit(cache: redis.Redis, key: str, limit: int, window_seconds: int) -> int | None:
    """Fixed-window counter. Returns seconds until the window resets if over limit, else None."""
    now = int(time.time())
    window_start = now - now % window_seconds
    window_key = f"{key}:{window_start}"
    pipe = cache.pipeline(transaction=True)  # INCR and EXPIRE together, atomically
    pipe.incr(window_key)
    pipe.expire(window_key, window_seconds)
    count, _ = pipe.execute()
    if count > limit:
        return window_start + window_seconds - now
    return None


def _prefix() -> str:
    return f"{get_settings().environment}:ratelimit"


def _enforce(cache: redis.Redis, checks: list[tuple[str, int, int]], fail_open: bool) -> None:
    try:
        for key, limit, window in checks:
            retry_after = check_limit(cache, key, limit, window)
            if retry_after is not None:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(retry_after)},
                )
    except redis.RedisError as exc:
        if fail_open:
            logger.warning("Rate limiter unavailable; allowing request")
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiter unavailable; try again shortly",
        ) from exc


def search_rate_limit(
    key: ApiKey = Depends(require_reader), cache: redis.Redis = Depends(get_redis)
) -> ApiKey:
    """Search is cheap: if Redis is down, let it through."""
    limit = get_settings().rate_limit_search_per_minute
    _enforce(cache, [(f"{_prefix()}:search:{key.id}", limit, MINUTE)], fail_open=True)
    return key


def ask_rate_limit(
    key: ApiKey = Depends(require_reader), cache: redis.Redis = Depends(get_redis)
) -> ApiKey:
    """Ask spends money: per-key limit plus a global daily budget, and fail closed."""
    settings = get_settings()
    _enforce(
        cache,
        [
            (f"{_prefix()}:ask:{key.id}", settings.rate_limit_ask_per_minute, MINUTE),
            (f"{_prefix()}:ask:global", settings.ask_daily_budget, DAY),
        ],
        fail_open=False,
    )
    return key
