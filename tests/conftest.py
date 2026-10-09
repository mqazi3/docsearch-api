import os
import tempfile

# Point the app at a separate test database and a temp upload folder BEFORE any app
# module is imported, because settings and the engine are created at import time.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://docsearch:docsearch@localhost:5434/docsearch_test",
)
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="docsearch-test-uploads-")

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from alembic import command  # noqa: E402
from app.db import engine  # noqa: E402
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
    """Every test starts with empty tables."""
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE chunks, documents RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
