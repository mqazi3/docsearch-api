from datetime import UTC, datetime

import redis

from app.auth import create_api_key, hash_key
from app.cache import get_redis
from app.config import get_settings
from app.db import SessionLocal
from app.main import app


class BrokenRedis:
    def pipeline(self, *args, **kwargs):
        raise redis.ConnectionError("simulated outage")

    def get(self, key):
        raise redis.ConnectionError("simulated outage")

    def set(self, *args, **kwargs):
        raise redis.ConnectionError("simulated outage")


def make_key(role: str) -> dict:
    with SessionLocal() as db:
        _, raw_key = create_api_key(db, f"test-{role}", role)
    return {"X-API-Key": raw_key}


# --- Authentication and roles ---


def test_missing_key_is_rejected(anon_client):
    assert anon_client.get("/documents").status_code == 401


def test_invalid_key_is_rejected(anon_client):
    response = anon_client.get("/documents", headers={"X-API-Key": "dsk_not-a-real-key"})
    assert response.status_code == 401


def test_revoked_key_is_rejected(anon_client):
    with SessionLocal() as db:
        key, raw_key = create_api_key(db, "old", "reader")
        key.revoked_at = datetime.now(UTC)
        db.commit()

    assert anon_client.get("/documents", headers={"X-API-Key": raw_key}).status_code == 401


def test_health_stays_public(anon_client):
    assert anon_client.get("/health").status_code == 200


def test_reader_can_read_but_not_upload(anon_client):
    headers = make_key("reader")

    assert anon_client.get("/documents", headers=headers).status_code == 200
    upload = anon_client.post(
        "/documents", headers=headers, files={"file": ("a.txt", b"text", "text/plain")}
    )
    assert upload.status_code == 403


def test_keys_are_stored_only_as_hashes():
    with SessionLocal() as db:
        key, raw_key = create_api_key(db, "hash-check", "reader")

    assert raw_key.startswith("dsk_")
    assert key.key_hash == hash_key(raw_key)
    assert key.prefix == raw_key[:12]
    assert raw_key not in (key.key_hash, key.prefix)


# --- Rate limiting ---


def test_search_rate_limit_returns_429_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_search_per_minute", 2)

    responses = [client.get("/search", params={"q": "x", "mode": "keyword"}) for _ in range(3)]

    assert [r.status_code for r in responses] == [200, 200, 429]
    assert int(responses[2].headers["Retry-After"]) > 0


def test_ask_daily_budget_is_global(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "ask_daily_budget", 1)

    first = client.post("/ask", json={"question": "anything"})
    second = client.post("/ask", json={"question": "anything else"})

    assert first.status_code == 200
    assert second.status_code == 429


def test_ask_fails_closed_when_limiter_is_down(client):
    app.dependency_overrides[get_redis] = lambda: BrokenRedis()
    assert client.post("/ask", json={"question": "anything"}).status_code == 503


def test_search_fails_open_when_limiter_is_down(client):
    app.dependency_overrides[get_redis] = lambda: BrokenRedis()
    response = client.get("/search", params={"q": "x", "mode": "keyword"})
    assert response.status_code == 200
