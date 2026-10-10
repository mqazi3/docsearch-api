import logging

from fastapi import FastAPI

from app.config import get_settings
from app.routes import documents, health, search

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

settings = get_settings()

app = FastAPI(
    title="DocSearch API",
    description="Document ingestion, hybrid search, and cited question answering.",
    version=settings.app_version,
)

app.include_router(health.router)
app.include_router(documents.router)
app.include_router(search.router)
