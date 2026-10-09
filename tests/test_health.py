import redis

from app.cache import get_redis
from app.main import app


class BrokenRedis:
    """Stands in for a Redis server that is down."""

    def ping(self):
        raise redis.ConnectionError("simulated outage")


def test_liveness_needs_no_dependencies(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_ok_when_dependencies_up(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": "ok", "redis": "ok"}


def test_readiness_503_when_redis_down(client):
    app.dependency_overrides[get_redis] = lambda: BrokenRedis()
    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["redis"] == "unavailable"
    assert body["checks"]["database"] == "ok"
