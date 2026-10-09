import redis

from app.config import get_settings

# Short timeouts so a dead Redis fails fast instead of hanging a request.
redis_client = redis.Redis.from_url(
    get_settings().redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


def get_redis() -> redis.Redis:
    """FastAPI dependency. Tests replace it to simulate Redis being down."""
    return redis_client
