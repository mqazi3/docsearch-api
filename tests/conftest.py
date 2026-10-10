import os
import tempfile

# Point the app at a separate test database and a temp upload folder BEFORE any app
# module is imported, because settings and the engine are created at import time.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://docsearch:docsearch@localhost:5434/docsearch_test",
)
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="docsearch-test-uploads-")
os.environ["EMBEDDING_PROVIDER"] = "fake"
os.environ["ANSWER_PROVIDER"] = "fake"
os.environ["ENVIRONMENT"] = "test"

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from alembic import command  # noqa: E402
from app.auth import create_api_key  # noqa: E402
from app.cache import redis_client  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.jobs import get_ingestion_queue  # noqa: E402
from app.main import app  # noqa: E402


def _create_database_if_missing(url: str) -> None:
    db_url = make_url(url)
    admin = create_engine(db_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": db_url.database},
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{db_url.database}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def database():
    """Create the test database once and migrate it with the real migrations."""
    _create_database_if_missing(os.environ["DATABASE_URL"])
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture(autouse=True)
def clean_tables(database):
    """Every test starts with empty tables and fresh rate-limit counters."""
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE api_keys, chunks, documents RESTART IDENTITY CASCADE"))
    for key in redis_client.scan_iter("test:ratelimit:*"):
        redis_client.delete(key)
    yield


class RecordingQueue:
    """Stands in for RQ: records what would be queued instead of needing a worker."""

    def __init__(self) -> None:
        self.enqueued: list = []

    def enqueue_ingestion(self, document_id) -> None:
        self.enqueued.append(document_id)


@pytest.fixture
def ingestion_queue():
    return RecordingQueue()


@pytest.fixture
def admin_key():
    with SessionLocal() as db:
        _, raw_key = create_api_key(db, "test-admin", "admin")
    return raw_key


@pytest.fixture
def client(ingestion_queue, admin_key):
    """Authenticated as admin, so existing tests exercise behavior, not auth."""
    app.dependency_overrides[get_ingestion_queue] = lambda: ingestion_queue
    with TestClient(app, headers={"X-API-Key": admin_key}) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def anon_client():
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
