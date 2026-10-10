import logging
import uuid

from app.db import SessionLocal
from app.embeddings import get_embedder
from app.ingestion.pipeline import ingest_document
from app.storage import get_storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


def process_document(document_id: str) -> None:
    """Entry point the RQ worker runs for each queued document."""
    ingest_document(uuid.UUID(document_id), SessionLocal, get_storage(), get_embedder())
